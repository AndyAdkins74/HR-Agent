"""Orchestrates the connection, decision, and logging layers into one
end-to-end HR triage run.

This module is the only place that wires the three layers together. It
picks the active connector from config, feeds each email into the
decision layer as plain content, carries out whatever action the
decision layer recommends via the connector, and writes one auditable
log line per email -- including emails it chose not to act on, and why.
"""
import logging
import os
import sys
from pathlib import Path
from types import ModuleType

from config import settings
from config.rules import is_within_schedule, load_rules, record_run, should_throttle
from decision.engine import EmailInput, classify


def _load_connector(name: str) -> ModuleType:
    if name == "gmail":
        from connectors import gmail_connector

        return gmail_connector
    raise ValueError(
        f"Unknown connector '{name}'. Implement it under connectors/ and add it "
        "here to make it selectable via config.settings.ACTIVE_CONNECTOR."
    )


def _setup_logger() -> logging.Logger:
    log_path = Path(settings.LOG_FILE_PATH)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("hr_agent")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def _sanitize(text: str) -> str:
    """Collapse an arbitrary string to a single line for the log file."""
    return " ".join((text or "").split())


def _log_decision(logger: logging.Logger, email, decision, action_taken: str) -> None:
    logger.info(
        "msg_id=%s | from=%s | subject=%s | subagent=%s | hr_related=%s | decided_action=%s | "
        "action_taken=%s | reasoning=%s",
        email.message_id,
        _sanitize(email.sender),
        _sanitize(email.subject) or "(no subject)",
        decision.subagent,
        decision.is_hr_related,
        decision.action,
        action_taken,
        _sanitize(decision.reasoning),
    )


def run() -> None:
    logger = _setup_logger()
    rules = load_rules()

    if not is_within_schedule(rules):
        logger.info("Outside configured schedule window; skipping this run.")
        return

    if should_throttle(rules):
        logger.info("Within schedule window but skipping: configured run interval hasn't elapsed yet.")
        return

    record_run()

    connector = _load_connector(settings.ACTIVE_CONNECTOR)

    emails = connector.get_emails()
    logger.info("Fetched %d email(s) to triage.", len(emails))

    for email in emails:
        email_input = EmailInput(
            subject=email.subject,
            sender=email.sender,
            body=email.body,
            attachment_filenames=[a.filename for a in email.attachments],
        )

        try:
            decision = classify(email_input)
        except Exception as exc:  # decision layer failure must not kill the run or go unlogged
            logger.info(
                "msg_id=%s | from=%s | subject=%s | subagent=UNKNOWN | hr_related=UNKNOWN | "
                "decided_action=none | action_taken=classification_failed | reasoning=%s",
                email.message_id,
                _sanitize(email.sender),
                _sanitize(email.subject) or "(no subject)",
                _sanitize(str(exc)),
            )
            continue

        actions_taken = []
        if decision.action == "save_attachments" and decision.attachments_to_save:
            folder_mappings = rules.get("folder_mappings", {})
            output_dir = folder_mappings.get(decision.folder_category, folder_mappings.get("default"))
            attachments_by_name = {a.filename: a for a in email.attachments}
            for filename in decision.attachments_to_save:
                attachment = attachments_by_name.get(filename)
                if attachment is None:
                    actions_taken.append(f"skip_missing:{filename}")
                    continue
                saved_path = connector.save_attachment(email.message_id, attachment, output_dir=output_dir)
                actions_taken.append(
                    f"saved:{os.path.basename(saved_path)}(category={decision.folder_category})"
                )
        elif decision.action == "flag_for_review":
            connector.flag_for_review(email.message_id)
            actions_taken.append("flagged_for_review")

        action_taken_summary = "; ".join(actions_taken) if actions_taken else "no_action"
        _log_decision(logger, email, decision, action_taken_summary)

        connector.mark_processed(email.message_id)


if __name__ == "__main__":
    run()
