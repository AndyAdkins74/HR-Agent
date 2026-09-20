# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An autonomous HR-triage agent that reads a Gmail inbox, classifies each email with the Claude API, and saves HR-relevant attachments to an output folder, with an auditable log of every decision (including emails it chose not to act on).

## Commands

```bash
# Setup
python -m venv .venv
source .venv/bin/activate        # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# One-off OAuth consent (needs a real browser; run locally, not headless)
python scripts/generate_token.py --credentials config/credentials.json --token config/token.json

# Run one triage pass
python main.py

# Force previously-seen emails to be re-classified (e.g. after editing a prompt)
python scripts/reset_processed_label.py [--query "after:2026/09/18"] [--label HR-Agent-NeedsReview]

# Control panel (edits config/rules.json; independent of main.py, no restart needed)
python webapp/app.py   # http://127.0.0.1:5151/
```

There is no test suite, linter, or build step configured in this repo.

## Architecture

Three layers that must stay separated (see also the module docstrings, which are the canonical description of each layer's contract):

- **Connection layer** — [connectors/gmail_connector.py](connectors/gmail_connector.py). The *only* module allowed to know about Gmail, OAuth, or the Google API client. Exposes plain functions returning dataclasses: `get_emails()`, `save_attachment()`, `mark_processed()`, `flag_for_review()`, `apply_folder_label()`, `remove_label_from_matching()`. A future connector would live under `connectors/` and be wired in via `HR_AGENT_CONNECTOR`/`_load_connector` in [main.py](main.py) — the decision layer must stay ignorant of it.
- **Decision layer** — [decision/engine.py](decision/engine.py). Takes plain `EmailInput` (subject/sender/body/attachment filenames) and returns a `Decision` (is it HR-related, what action, which folder category, why, which sub-agent handled it). Has zero knowledge of Gmail. Classification is up to two Claude tool-use calls, both built from `config/rules.json`, not hard-coded here:
  1. An **orchestrator** call routes the email to one configured sub-agent, or `"none"` (which short-circuits — no second call, `is_hr_related=False`).
  2. If routed, that sub-agent's own fully self-contained system prompt (not a fragment appended to something shared) makes the actual triage decision via `submit_hr_triage_decision`.
- **Configuration layer** — [config/settings.py](config/settings.py) + [config/rules.py](config/rules.py). `settings.py` holds credential paths, folder paths, and the active connector, from env vars with defaults; it must stay free of heavy third-party imports (no `google-api`, no `anthropic`) so lightweight scripts like `scripts/generate_token.py` can import it cheaply. `rules.py` holds the mutable behavioural config — orchestrator prompt, sub-agents (each with `name`/`description`/`prompt`), folder mappings, and the schedule — as JSON in `config/rules.json`, editable by hand or via the control panel. `load_rules()` merges in `DEFAULT_RULES` for anything missing and drops dead keys from older schema versions (e.g. the pre-orchestrator `classification_prompt`/`hr_criteria` fields), so it's the source of truth for what a valid rules dict looks like — read it before hand-editing `rules.json`.

[main.py](main.py) wires the three layers together into one triage run (`run()`) and writes the audit log; it also enforces the configured schedule (`is_within_schedule`/`should_throttle`/`record_run`) before touching Gmail or Claude at all. [webapp/app.py](webapp/app.py) is a second, independent Flask app for editing `config/rules.json` and viewing the audit log — it never imports the Gmail connector or the Anthropic client, and `main.py` never imports it; either runs without the other.

### Sub-agent routing and folder filing

Sub-agents are user-defined in the control panel, not fixed in code — `config/rules.py`'s `DEFAULT_RULES["sub_agents"]` is only the seed data for a fresh `rules.json`. The orchestrator's tool schema (the `subagent` enum) is generated from the current `sub_agents` list at classification time (`_build_route_tool`), so sub-agent names must never be hand-edited into `orchestrator_prompt`'s free text — the `{agents}` placeholder is where the bullet list gets substituted in.

Each classified email gets Gmail-labelled twice, for two different purposes:
- `GMAIL_PROCESSED_LABEL` / `GMAIL_REVIEW_LABEL` (flat, dedup/visibility markers — drives the fetch query's exclusion and whether a human sees it flagged).
- A nested `apply_folder_label` under `GMAIL_FOLDER_PREFIX/<sub-agent name>/<Not Processed|Processed|Review>` (`main.py`'s `ACTION_TO_FOLDER`), purely for Gmail-sidebar organisation per sub-agent, independent of the dedup labels above.

### Runtime state vs. config vs. secrets

- Secrets, git-ignored: `.env`, `config/credentials.json`, `config/token.json`.
- Mutable behavioural config, git-ignored, auto-seeded with defaults on first run of either app: `config/rules.json`.
- Runtime state, git-ignored: `config/.schedule_state.json` (last-run timestamp for interval throttling), `logs/`, `output/`.

`GMAIL_PROCESSED_LABEL` is a dedup marker ("seen"), not a record of whether the agent acted — don't confuse it with the decision's `action`.

### Scheduling

The schedule (day/time windows + per-day-of-week minimum run interval) lives in `rules.json["schedule"]` and is enforced in `main.py.run()`, independent of whatever external scheduler triggers the process (the `launchd` job in [launchd/com.hragent.triage.plist](launchd/com.hragent.triage.plist) triggers every 10 minutes regardless; the schedule decides whether that trigger does any real work). A trigger outside the window, or inside it but before the configured interval has elapsed, logs one line and exits before any Gmail/Claude call is made.
