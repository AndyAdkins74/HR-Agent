"""Mutable behavioural configuration for the decision layer.

Holds the classification prompt, the criteria for what counts as
HR-related, and folder-mapping rules for saved attachments -- as plain
JSON rather than Python source, so the control panel web app
(webapp/app.py) can edit it without touching the decision layer, and
the agent picks up edits on its very next run without a restart.

Part of the configuration layer: no Gmail/OAuth or Anthropic imports
here, just stdlib.
"""
import json
import os
from pathlib import Path
from typing import Any, Dict

from config import settings

RULES_FILE_PATH = Path(
    os.environ.get("HR_AGENT_RULES_PATH", str(settings.BASE_DIR / "config" / "rules.json"))
)

DEFAULT_RULES: Dict[str, Any] = {
    "classification_prompt": (
        "You are an HR triage assistant reviewing one email at a time from a "
        "shared inbox. You are given its subject, sender, body, and a list of "
        "attachment filenames (not the attachment contents).\n\n"
        "An email counts as HR-related if it concerns any of:\n"
        "{criteria}\n\n"
        "Decide:\n"
        "1. Whether the email is HR-related.\n"
        "2. What should happen next: 'none' if no action is needed, "
        "'save_attachments' if the email is HR-related and it has an "
        "attachment worth keeping (e.g. a CV, contract, signed form, ID "
        "document), or 'flag_for_review' if it is HR-related but needs a "
        "human to look at it rather than an automatic action.\n"
        "3. If saving attachments, which folder category they belong in.\n\n"
        "Only list a filename in attachments_to_save if it is HR-related and "
        "plausibly worth keeping -- do not save attachments from unrelated "
        "or promotional email just because one is present.\n"
        "Always call the submit_hr_triage_decision tool with your answer, "
        "and make the reasoning specific enough that someone auditing the "
        "log later can see why you decided what you did."
    ),
    "hr_criteria": [
        "Recruitment and hiring",
        "Onboarding",
        "Payroll",
        "Benefits",
        "Leave requests",
        "Employee relations",
        "Policy",
        "Disciplinary matters",
    ],
    "folder_mappings": {
        "default": settings.ATTACHMENT_OUTPUT_DIR,
    },
}


def _deep_copy(value: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(value))


def load_rules() -> Dict[str, Any]:
    """Read the current rules, seeding the file with defaults if it doesn't exist yet."""
    if not RULES_FILE_PATH.exists():
        save_rules(DEFAULT_RULES)
        return _deep_copy(DEFAULT_RULES)

    with open(RULES_FILE_PATH, "r", encoding="utf-8") as f:
        rules = json.load(f)

    # Fill in anything missing (e.g. an older file from before a new field
    # was added) rather than failing at classification time.
    merged = _deep_copy(DEFAULT_RULES)
    merged.update(rules)
    if "default" not in merged.get("folder_mappings", {}):
        merged["folder_mappings"]["default"] = DEFAULT_RULES["folder_mappings"]["default"]
    return merged


def save_rules(rules: Dict[str, Any]) -> None:
    RULES_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RULES_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2)
        f.write("\n")
