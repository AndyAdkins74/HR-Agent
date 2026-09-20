# HR-Agent

An autonomous HR-triage agent that reads a Gmail inbox, classifies each
email using the Claude API, and saves HR-relevant attachments to an
output folder -- with an auditable, human-readable log of every
decision, including emails it chose not to act on.

## Architecture

The project is split into three layers that must stay separated:

- **Connection layer** (`connectors/gmail_connector.py`) -- the only
  module that knows about Gmail, OAuth, or the Google API client.
  Exposes `get_emails()`, `save_attachment()`, `mark_processed()`,
  `flag_for_review()`, `remove_label_from_matching()`.
- **Decision layer** (`decision/engine.py`) -- takes plain email content
  (subject, sender, body, attachment filenames) and returns a
  `Decision` (is it HR-related, what action to take, which folder
  category, why). Calls the Claude API for the actual judgement, built
  from the prompt/criteria/folder rules in `config/rules.json`. Has
  zero knowledge of Gmail.
- **Configuration layer** (`config/settings.py` + `config/rules.py`) --
  `settings.py` holds credentials paths, folder paths, and the active
  connector selection, read via environment variables. `rules.py` holds
  the mutable behavioural configuration (classification prompt, HR
  criteria, folder mappings) as JSON in `config/rules.json`, edited
  either by hand or via the control panel web app. Nothing environment-
  or behaviour-specific is hard-coded in the connection or decision
  layers.

`main.py` wires the three together into one triage run and writes the
audit log. `webapp/app.py` is a separate, second app for editing
`config/rules.json` -- see **Control panel** below.

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Create a Google Cloud OAuth client (one-off, in a browser)

1. Go to the [Google Cloud Console](https://console.cloud.google.com/),
   create (or pick) a project.
2. **APIs & Services > Library** -- enable the **Gmail API**.
3. **APIs & Services > OAuth consent screen** -- configure it (External
   is fine for a personal test inbox; add your own Gmail address as a
   test user).
4. **APIs & Services > Credentials > Create Credentials > OAuth client
   ID** -- Application type **Desktop app**. Download the JSON.
5. Save it as `config/credentials.json` in this project (this file is
   git-ignored -- never commit it).

### 3. Complete the OAuth consent flow locally

This step needs a real browser, so run it on your own machine (not in a
headless/remote sandbox):

```bash
python scripts/generate_token.py --credentials config/credentials.json --token config/token.json
```

This opens a Google consent screen once, then writes `config/token.json`
(also git-ignored). The agent refreshes this token automatically after
that -- you should not need to repeat this step unless you revoke
access or change scopes.

If you generated `token.json` on a different machine to the one running
`main.py`, copy the file over rather than committing it.

### 4. Set your Claude API key

Copy `.env.example` to `.env` in the project root and fill in your key:

```bash
cp .env.example .env
# then edit .env and set ANTHROPIC_API_KEY=sk-ant-...
chmod 600 .env
```

`config/settings.py` loads `.env` automatically on every run (it's
git-ignored, never committed) -- this is what makes the launchd job
below possible, since a scheduled job has no interactive terminal to
`export` a key into. A real environment variable, if you set one, still
takes precedence over `.env`.

### 5. Run the agent

```bash
python main.py
```

This fetches unlabelled inbox emails (see `GMAIL_QUERY` below),
classifies each one, and depending on the decision layer's `action`:

- `save_attachments` -- downloads the flagged attachment(s) to the
  folder mapped to the decision's `folder_category` in
  `config/rules.json` (falling back to the `default` category).
- `flag_for_review` -- applies the `HR-Agent-NeedsReview` label so the
  email is visible to a human in Gmail, not just in the log.
- `none` -- no action.

Every classified email -- regardless of action -- is labelled
`HR-Agent-Processed` in Gmail so it isn't re-fetched next run, and gets
one line appended to `logs/decisions.log`.

`HR-Agent-Processed` is a dedup marker ("seen"), not a record of
whether the agent acted. If you change the classification prompt or
criteria and want previously seen emails reconsidered, run:

```bash
python scripts/reset_processed_label.py
```

This removes the label from matching emails so the next `python
main.py` run re-classifies them. Pass `--query` to narrow it (e.g. to a
date range) or `--label` to reset `HR-Agent-NeedsReview` instead.

## Configuration

All of the below are environment variables with defaults in
`config/settings.py`:

| Variable | Default | Purpose |
|---|---|---|
| `HR_AGENT_CONNECTOR` | `gmail` | Which connector implementation to use. |
| `GMAIL_CREDENTIALS_PATH` | `config/credentials.json` | OAuth client secret file. |
| `GMAIL_TOKEN_PATH` | `config/token.json` | Cached OAuth token. |
| `GMAIL_PROCESSED_LABEL` | `HR-Agent-Processed` | Gmail label applied to every classified email (dedup marker). |
| `GMAIL_REVIEW_LABEL` | `HR-Agent-NeedsReview` | Gmail label applied when the decision is `flag_for_review`. |
| `GMAIL_QUERY` | `in:inbox -label:HR-Agent-Processed` | Gmail search query for emails to fetch. |
| `GMAIL_MAX_RESULTS` | `20` | Max emails fetched per run. |
| `ATTACHMENT_OUTPUT_DIR` | `output/hr_attachments` | Where saved attachments land. |
| `ANTHROPIC_API_KEY` | (required) | Claude API key. |
| `CLAUDE_MODEL` | `claude-sonnet-5` | Model used for classification. |
| `HR_AGENT_LOG_PATH` | `logs/decisions.log` | Audit log location. |
| `HR_AGENT_RULES_PATH` | `config/rules.json` | Classification prompt / HR criteria / folder mappings, editable via the control panel. |

The behavioural rules (`config/rules.json`) are separate from the above
-- see **Control panel**.

## Audit log

`logs/decisions.log` gets one line per email, whether or not the agent
acted on it, e.g.:

```
2026-09-19T12:34:56Z | msg_id=18d2f... | from=payroll@example.com | subject=October payslip | hr_related=True | decided_action=save_attachments | action_taken=saved:18d2f..._payslip.pdf | reasoning=Payroll email with a payslip attachment; kept for records.
2026-09-19T12:34:58Z | msg_id=18d30... | from=newsletter@vendor.com | subject=This week's deals | hr_related=False | decided_action=none | action_taken=no_action | reasoning=Marketing newsletter, unrelated to HR matters; no action taken.
```

## Control panel

A separate, lightweight local web app for editing the classification
prompt, HR criteria, and folder-mapping rules without touching Python.
It reads and writes `config/rules.json` -- the same file the decision
layer reads on every classification call -- so:

- It never needs `main.py` (the agent) running.
- The agent never needs it running: `main.py` just reads whatever is
  currently in `config/rules.json`, so edits saved here take effect on
  the agent's very next run.

Run it with:

```bash
python webapp/app.py
```

then open <http://127.0.0.1:5151/>. The form has three parts:

- **Classification prompt** -- the instructions given to Claude for
  every email. Use the literal text `{criteria}` where the HR criteria
  list below should be inserted.
- **HR criteria** -- one per line; what counts as HR-related.
- **Folder mappings** -- a default output folder, plus optional
  additional named categories (`category = folder/path`, one per
  line). The classifier picks one of these category names whenever it
  decides to save an attachment, so e.g. CVs and payslips can land in
  different folders.
- **Schedule** -- an optional per-day-of-week allow-list of time
  windows (e.g. Monday `09:00-17:00`) during which the agent is
  actually allowed to do any Gmail/Claude work. This applies no matter
  how `main.py` gets triggered -- manually or via the launchd job
  below. Leave the "Only run during these windows" box unchecked (the
  default) to run any time it's triggered, unrestricted.

`config/rules.json` is git-ignored (it's local runtime state, not a
secret) and is created automatically with sensible defaults the first
time either `main.py` or the control panel runs, if it doesn't already
exist.

## Always-on scheduling (launchd)

`main.py` itself is a one-shot script -- it processes whatever's
currently fetchable and exits. To have it run automatically every 10
minutes on macOS (rather than typing `python3 main.py` by hand each
time), use the provided `launchd` job:

```bash
cp launchd/com.hragent.triage.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.hragent.triage.plist
```

This runs `main.py` once immediately, then every 10 minutes, using the
absolute paths baked into the plist (`~/Documents/hr-agent`) -- edit
`launchd/com.hragent.triage.plist` first if your checkout lives
somewhere else, since launchd does not expand `~` or environment
variables. It reads `ANTHROPIC_API_KEY` from `.env` (see step 4 above),
so make sure that's set up before loading it.

Check it's running and see its output:

```bash
launchctl list | grep hragent
tail -f logs/launchd.out.log logs/launchd.err.log logs/decisions.log
```

Stop it with:

```bash
launchctl unload ~/Library/LaunchAgents/com.hragent.triage.plist
```

Two things worth knowing:

- This 10-minute cadence is *when it's triggered*, not *when it does
  work*. Use the control panel's **Schedule** section to restrict which
  of those triggers actually process email (e.g. only weekday office
  hours) -- outside those windows each trigger just logs one "skipped"
  line and exits, so it costs nothing beyond that.
- Your Gmail OAuth token is on a 7-day expiry (per the app's Testing
  publishing status) -- an always-on job will start failing quietly at
  that point. Check `logs/decisions.log` / `logs/launchd.err.log`
  periodically, or move the Google Cloud OAuth consent screen out of
  Testing if you want this to run unattended for longer.

## Status

The core triage loop, the control panel, and the always-on scheduling
have all been built and reviewed. The end-to-end loop (fetch, classify,
act, label, log) and the control panel (edit prompt/criteria/folder
mapping, confirm it changes the next run's behaviour with no restart)
have both been run against a real test Gmail inbox and confirmed
working. The launchd job and the Schedule control-panel section have
not yet been run for real, since this build session has no macOS
environment to load a launchd job into -- install it per the steps
above and confirm it fires every 10 minutes and respects a configured
schedule window.
