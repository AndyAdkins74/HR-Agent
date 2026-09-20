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
  `Decision` (is it HR-related, what action to take, why). Calls the
  Claude API for the actual judgement. Has zero knowledge of Gmail.
- **Configuration layer** (`config/settings.py`) -- all credentials
  paths, folder paths, and the active connector selection. Read via
  environment variables with local defaults; nothing environment
  specific is hard-coded in the other two layers.

`main.py` wires the three together into one triage run and writes the
audit log.

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

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

(Or put it in a `.env` file copied from `.env.example` and load it
yourself, e.g. `export $(cat .env | xargs)` -- `main.py` does not read
`.env` automatically.)

### 5. Run the agent

```bash
python main.py
```

This fetches unlabelled inbox emails (see `GMAIL_QUERY` below),
classifies each one, and depending on the decision layer's `action`:

- `save_attachments` -- downloads the flagged attachment(s) to
  `ATTACHMENT_OUTPUT_DIR`.
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

## Audit log

`logs/decisions.log` gets one line per email, whether or not the agent
acted on it, e.g.:

```
2026-09-19T12:34:56Z | msg_id=18d2f... | from=payroll@example.com | subject=October payslip | hr_related=True | decided_action=save_attachments | action_taken=saved:18d2f..._payslip.pdf | reasoning=Payroll email with a payslip attachment; kept for records.
2026-09-19T12:34:58Z | msg_id=18d30... | from=newsletter@vendor.com | subject=This week's deals | hr_related=False | decided_action=none | action_taken=no_action | reasoning=Marketing newsletter, unrelated to HR matters; no action taken.
```

## Known limitation of this build session

This code was written and reviewed in an environment with no browser
and no Gmail/Claude credentials, so the end-to-end run against a real
inbox has not yet been executed here -- you'll need to run through
Setup steps 2-5 yourself and confirm the loop behaves as expected
before we iterate further.

## Next step (once you've reviewed this)

A local web control panel to edit the classification prompt, HR
criteria, and folder-mapping rules without touching Python -- planned
as a second, independent app once this loop is confirmed working.
