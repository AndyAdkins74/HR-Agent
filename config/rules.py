"""Mutable behavioural configuration for the decision layer.

Holds the classification prompt, the criteria for what counts as
HR-related, and folder-mapping rules for saved attachments -- as plain
JSON rather than Python source, so the control panel web app
(webapp/app.py) can edit it without touching the decision layer, and
the agent picks up edits on its very next run without a restart.

Part of the configuration layer: no Gmail/OAuth or Anthropic imports
here, just stdlib.
"""
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from config import settings

RULES_FILE_PATH = Path(
    os.environ.get("HR_AGENT_RULES_PATH", str(settings.BASE_DIR / "config" / "rules.json"))
)

# Tracks when the agent last actually did Gmail/Claude work (as opposed to
# being triggered and skipping), so schedule.intervals below can throttle
# runs independently of how often the scheduler (e.g. launchd, every 10
# minutes) actually triggers main.py. Runtime state, not user config --
# git-ignored like token.json.
SCHEDULE_STATE_PATH = Path(
    os.environ.get(
        "HR_AGENT_SCHEDULE_STATE_PATH", str(settings.BASE_DIR / "config" / ".schedule_state.json")
    )
)

# Selectable in the control panel; 0 means "no extra throttling beyond
# however often the scheduler triggers the agent" (the original behaviour).
INTERVAL_CHOICES_MINUTES = [0, 15, 30, 60, 120, 240]

# Monday-first, matching datetime.weekday().
DAY_NAMES = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

DEFAULT_RULES: Dict[str, Any] = {
    # Routing prompt: given one email, decide which sub-agent below should
    # handle it (or "none"). {agents} is replaced at classification time
    # with a bullet list built from sub_agents' name/description -- do not
    # hand-edit sub-agent names into this text, since the tool's enum (and
    # therefore which name Claude is allowed to return) is generated from
    # the sub_agents list, not from this prompt.
    "orchestrator_prompt": (
        "You are the orchestrator for an HR inbox triage system. You are given "
        "one email's subject, sender, body, and attachment filenames. Decide "
        "which specialist sub-agent below should handle it, based on what the "
        "email is actually about -- not just keywords in the subject line.\n\n"
        "Available sub-agents:\n{agents}\n\n"
        "If the email isn't HR-related at all (e.g. promotional, a security "
        "alert, personal correspondence unrelated to work), choose 'none'.\n\n"
        "Always call the route_to_subagent tool with your choice and a short "
        "reasoning."
    ),
    # Each sub-agent's prompt is fully self-contained (its own complete set
    # of instructions, not a fragment appended to something shared) so it
    # can be edited independently in the control panel without affecting
    # any other sub-agent. It is used as the system prompt for the second,
    # sub-agent-specific classification call once the orchestrator has
    # routed an email here.
    "sub_agents": [
        {
            "name": "Recruitment & Onboarding",
            "description": "Hiring, interviews, candidate CVs, job offers, right-to-work checks, and onboarding of new starters.",
            "prompt": (
                "You are the Recruitment & Onboarding specialist within an HR "
                "triage system, reviewing one email at a time from a shared "
                "inbox. You are given its subject, sender, body, and a list of "
                "attachment filenames (not the attachment contents). This email "
                "has already been routed to you because it appears to concern "
                "recruitment, hiring, interviews, job offers, or onboarding a "
                "new employee.\n\n"
                "Decide:\n"
                "1. What should happen next: 'none' if no action is needed, "
                "'save_attachments' if there's an attachment worth keeping "
                "(e.g. a CV/resume, signed offer letter, right-to-work document, "
                "or onboarding paperwork), or 'flag_for_review' if it needs a "
                "human to look at it rather than an automatic action.\n"
                "2. If saving attachments, which folder category they belong in.\n"
                "3. If, on closer inspection, this email is not actually "
                "HR-related after all, set is_hr_related to false and action "
                "to 'none'.\n\n"
                "Only list a filename in attachments_to_save if it is plausibly "
                "worth keeping -- do not save attachments just because one is "
                "present.\n"
                "Always call the submit_hr_triage_decision tool with your "
                "answer, and make the reasoning specific enough that someone "
                "auditing the log later can see why you decided what you did."
            ),
        },
        {
            "name": "Payroll & Benefits",
            "description": "Pay, tax, payslips, pensions, and employee benefits enrollment.",
            "prompt": (
                "You are the Payroll & Benefits specialist within an HR triage "
                "system, reviewing one email at a time from a shared inbox. You "
                "are given its subject, sender, body, and a list of attachment "
                "filenames (not the attachment contents). This email has "
                "already been routed to you because it appears to concern "
                "payroll, pay, tax, pensions, or employee benefits.\n\n"
                "Decide:\n"
                "1. What should happen next: 'none' if no action is needed, "
                "'save_attachments' if there's an attachment worth keeping "
                "(e.g. a payslip, P45/P60, pension statement, or benefits "
                "enrollment form), or 'flag_for_review' if it needs a human to "
                "look at it rather than an automatic action.\n"
                "2. If saving attachments, which folder category they belong in.\n"
                "3. If, on closer inspection, this email is not actually "
                "HR-related after all, set is_hr_related to false and action "
                "to 'none'.\n\n"
                "Only list a filename in attachments_to_save if it is plausibly "
                "worth keeping -- do not save attachments just because one is "
                "present.\n"
                "Always call the submit_hr_triage_decision tool with your "
                "answer, and make the reasoning specific enough that someone "
                "auditing the log later can see why you decided what you did."
            ),
        },
        {
            "name": "Leave & Absence",
            "description": "Annual leave, sick leave, maternity/paternity leave, and other absence requests.",
            "prompt": (
                "You are the Leave & Absence specialist within an HR triage "
                "system, reviewing one email at a time from a shared inbox. You "
                "are given its subject, sender, body, and a list of attachment "
                "filenames (not the attachment contents). This email has "
                "already been routed to you because it appears to concern an "
                "employee's leave or absence -- annual leave, sick leave, "
                "maternity/paternity leave, or a resignation/notice period.\n\n"
                "Decide:\n"
                "1. What should happen next: 'none' if no action is needed, "
                "'save_attachments' if there's an attachment worth keeping (e.g. "
                "a signed leave request form or medical certificate), or "
                "'flag_for_review' if it needs a human to review and "
                "acknowledge -- lean towards flag_for_review for anything that "
                "needs approval or a personal response, rather than treating "
                "silence as the safe default.\n"
                "2. If saving attachments, which folder category they belong in.\n"
                "3. If, on closer inspection, this email is not actually "
                "HR-related after all, set is_hr_related to false and action "
                "to 'none'.\n\n"
                "Only list a filename in attachments_to_save if it is plausibly "
                "worth keeping -- do not save attachments just because one is "
                "present.\n"
                "Always call the submit_hr_triage_decision tool with your "
                "answer, and make the reasoning specific enough that someone "
                "auditing the log later can see why you decided what you did."
            ),
        },
        {
            "name": "Employee Relations & Policy",
            "description": "Grievances, disciplinary matters, complaints, and company policy questions or acknowledgements.",
            "prompt": (
                "You are the Employee Relations & Policy specialist within an "
                "HR triage system, reviewing one email at a time from a shared "
                "inbox. You are given its subject, sender, body, and a list of "
                "attachment filenames (not the attachment contents). This email "
                "has already been routed to you because it appears to concern "
                "employee relations, a grievance, a disciplinary matter, or "
                "company policy.\n\n"
                "Decide:\n"
                "1. What should happen next: 'none' if no action is needed, "
                "'save_attachments' if there's an attachment worth keeping (e.g. "
                "a signed policy acknowledgement or grievance letter), or "
                "'flag_for_review' if it needs a human to look at it -- these "
                "are sensitive matters, so default to flag_for_review unless "
                "the email is purely informational with nothing to act on.\n"
                "2. If saving attachments, which folder category they belong in.\n"
                "3. If, on closer inspection, this email is not actually "
                "HR-related after all, set is_hr_related to false and action "
                "to 'none'.\n\n"
                "Only list a filename in attachments_to_save if it is plausibly "
                "worth keeping -- do not save attachments just because one is "
                "present.\n"
                "Always call the submit_hr_triage_decision tool with your "
                "answer, and make the reasoning specific enough that someone "
                "auditing the log later can see why you decided what you did."
            ),
        },
    ],
    "folder_mappings": {
        "default": settings.ATTACHMENT_OUTPUT_DIR,
    },
    # When "enabled" is False (the default), the agent runs whenever it's
    # triggered, on any day, at any time -- unchanged from before this
    # feature existed. When True, main.py only does any Gmail/Claude work
    # if the current day and time fall inside that day's window(s); a
    # trigger outside those hours logs one line and does nothing else, so
    # e.g. a launchd job firing every 10 minutes only actually costs a
    # Claude API call during hours you've allowed.
    "schedule": {
        "enabled": False,
        "windows": {
            "monday": "09:00-17:00",
            "tuesday": "09:00-17:00",
            "wednesday": "09:00-17:00",
            "thursday": "09:00-17:00",
            "friday": "09:00-17:00",
            "saturday": "",
            "sunday": "",
        },
        # Minutes between actual runs on that day; 0 = every trigger (no
        # extra throttling). See is_within_schedule/should_throttle below.
        "intervals": {day: 0 for day in DAY_NAMES},
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

    # A rules.json from before the orchestrator/sub-agent model (which had
    # classification_prompt + hr_criteria instead) still carries those two
    # keys once merged in above -- drop them rather than leave dead config
    # sitting alongside the new fields it's been replaced by.
    merged.pop("classification_prompt", None)
    merged.pop("hr_criteria", None)

    sub_agents = merged.get("sub_agents")
    if not isinstance(sub_agents, list) or not sub_agents:
        sub_agents = _deep_copy(DEFAULT_RULES["sub_agents"])
    merged["sub_agents"] = [
        {
            "name": agent.get("name", ""),
            "description": agent.get("description", ""),
            "prompt": agent.get("prompt", ""),
        }
        for agent in sub_agents
        if isinstance(agent, dict) and agent.get("name", "").strip()
    ]

    schedule = merged.get("schedule", {})
    windows = schedule.get("windows", {})
    for day in DAY_NAMES:
        windows.setdefault(day, "")
    schedule["windows"] = windows

    intervals = schedule.get("intervals", {})
    for day in DAY_NAMES:
        try:
            intervals[day] = int(intervals.get(day, 0) or 0)
        except (TypeError, ValueError):
            intervals[day] = 0
    schedule["intervals"] = intervals

    schedule.setdefault("enabled", False)
    merged["schedule"] = schedule

    return merged


def save_rules(rules: Dict[str, Any]) -> None:
    RULES_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RULES_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2)
        f.write("\n")


def _parse_windows(windows_text: str):
    """Parse "09:00-17:00, 18:00-19:00" into a list of (start, end) times.
    Malformed entries are skipped rather than raising, since this runs on
    every trigger and a typo in the control panel shouldn't take the whole
    schedule check down."""
    parsed = []
    for window in windows_text.split(","):
        window = window.strip()
        if not window or "-" not in window:
            continue
        start_str, _, end_str = window.partition("-")
        try:
            start = dt.datetime.strptime(start_str.strip(), "%H:%M").time()
            end = dt.datetime.strptime(end_str.strip(), "%H:%M").time()
        except ValueError:
            continue
        parsed.append((start, end))
    return parsed


def is_within_schedule(rules: Dict[str, Any], now: Optional[dt.datetime] = None) -> bool:
    """True if the agent is allowed to do any work right now.

    If schedule.enabled is False, always True (unrestricted -- the
    original, pre-schedule behaviour). Otherwise, checks the current
    local day-of-week against that day's configured windows. An empty or
    absent window for a day means no processing that day. Windows that
    span midnight (e.g. "22:00-02:00") are not supported -- split them
    into two same-day windows instead.
    """
    schedule = rules.get("schedule", {})
    if not schedule.get("enabled", False):
        return True

    now = now or dt.datetime.now()
    day_name = DAY_NAMES[now.weekday()]
    windows_text = schedule.get("windows", {}).get(day_name, "")

    for start, end in _parse_windows(windows_text):
        if start <= now.time() <= end:
            return True
    return False


def _load_last_run_at() -> Optional[dt.datetime]:
    if not SCHEDULE_STATE_PATH.exists():
        return None
    try:
        with open(SCHEDULE_STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
        return dt.datetime.fromisoformat(state["last_run_at"])
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return None


def record_run(now: Optional[dt.datetime] = None) -> None:
    """Called once main.py has decided to actually do work, so the next
    trigger can measure elapsed time against schedule.intervals. Must be
    called at most once per real run -- not on runs skipped by
    is_within_schedule/should_throttle -- or the interval would never
    have a chance to elapse."""
    now = now or dt.datetime.now()
    SCHEDULE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHEDULE_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"last_run_at": now.isoformat()}, f)


def should_throttle(rules: Dict[str, Any], now: Optional[dt.datetime] = None) -> bool:
    """True if today's configured interval hasn't elapsed since the last
    real run yet, so this trigger should be skipped even though it falls
    inside today's window. This is independent of how often the
    scheduler (e.g. launchd, every 10 minutes) actually triggers main.py
    -- it throttles on top of that, it doesn't replace it."""
    schedule = rules.get("schedule", {})
    if not schedule.get("enabled", False):
        return False

    now = now or dt.datetime.now()
    day_name = DAY_NAMES[now.weekday()]
    interval_minutes = schedule.get("intervals", {}).get(day_name, 0) or 0
    if interval_minutes <= 0:
        return False

    last_run = _load_last_run_at()
    if last_run is None:
        return False

    elapsed_minutes = (now - last_run).total_seconds() / 60.0
    return elapsed_minutes < interval_minutes
