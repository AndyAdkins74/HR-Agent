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

GMAIL_PROCESSED_LABEL = os.environ.get("GMAIL_PROCESSED_LABEL", "HR-Agent-Processed")
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
