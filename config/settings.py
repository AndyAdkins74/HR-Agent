"""Configuration layer.

Holds credentials paths, folder paths, and which mail connector is active.
Nothing environment-specific should be hard-coded inside the connection
or decision layers -- everything they need comes from here, sourced from
environment variables with sane local defaults.

This module must stay free of heavy third-party imports (no google-api,
no anthropic) so it can be imported by lightweight standalone scripts
(e.g. scripts/generate_token.py) without pulling in the full app.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """Populate os.environ from a simple KEY=VALUE file, without overriding
    variables already set in the real environment. This exists so a
    launchd job (which has no interactive shell to `read -rs` a key into)
    can pick up ANTHROPIC_API_KEY from a git-ignored .env file instead."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_env_file(BASE_DIR / ".env")

# --- Active connector -------------------------------------------------
# Which mail connector implementation the agent should use. Only "gmail"
# is implemented today; a future connector would add its own module under
# connectors/ and get selected here without touching the decision layer.
ACTIVE_CONNECTOR = os.environ.get("HR_AGENT_CONNECTOR", "gmail")

# --- Gmail connector settings ------------------------------------------
GMAIL_CREDENTIALS_PATH = os.environ.get(
    "GMAIL_CREDENTIALS_PATH", str(BASE_DIR / "config" / "credentials.json")
)
GMAIL_TOKEN_PATH = os.environ.get(
    "GMAIL_TOKEN_PATH", str(BASE_DIR / "config" / "token.json")
)
# gmail.modify is required (not just readonly) so the agent can apply the
# "processed" label below. It does not allow permanent deletion.
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# Applied to every email the agent has classified, whether or not it acted
# on it -- this is a dedup marker ("seen"), not a record of action taken.
# If you change the classification prompt/criteria and want previously
# seen emails reconsidered, run scripts/reset_processed_label.py rather
# than editing this label by hand.
GMAIL_PROCESSED_LABEL = os.environ.get("GMAIL_PROCESSED_LABEL", "HR-Agent-Processed")
# Applied in addition to the above when the decision layer returns
# action="flag_for_review", so a flagged email is visible in Gmail itself
# rather than only in the log file.
GMAIL_REVIEW_LABEL = os.environ.get("GMAIL_REVIEW_LABEL", "HR-Agent-NeedsReview")
GMAIL_QUERY = os.environ.get(
    "GMAIL_QUERY", f"in:inbox -label:{GMAIL_PROCESSED_LABEL}"
)
GMAIL_MAX_RESULTS = int(os.environ.get("GMAIL_MAX_RESULTS", "20"))

# --- Attachment storage --------------------------------------------------
ATTACHMENT_OUTPUT_DIR = os.environ.get(
    "ATTACHMENT_OUTPUT_DIR", str(BASE_DIR / "output" / "hr_attachments")
)

# --- Claude API (decision layer) ----------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

# --- Logging --------------------------------------------------------------
LOG_FILE_PATH = os.environ.get("HR_AGENT_LOG_PATH", str(BASE_DIR / "logs" / "decisions.log"))
