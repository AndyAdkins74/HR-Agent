"""Force previously seen emails to be reconsidered.

main.py labels every email it classifies with GMAIL_PROCESSED_LABEL (a
dedup marker, not a record of whether it acted) and then excludes that
label from its fetch query on future runs. That's necessary so the agent
doesn't re-classify (and re-bill) the same email every run -- but it also
means an email skipped under an old or under-specified prompt stays
skipped forever, even after you fix the prompt.

Run this after changing the classification prompt/criteria to remove the
processed label from matching emails, so the next `python main.py` run
reconsiders them.

Usage:
    # Reset every email the agent has seen
    python scripts/reset_processed_label.py

    # Reset only ones also matching a Gmail search, e.g. a date range
    python scripts/reset_processed_label.py --query "after:2026/09/18"

    # Reset the needs-review label instead
    python scripts/reset_processed_label.py --label "HR-Agent-NeedsReview"
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from connectors import gmail_connector


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove a triage label so matching emails are re-triaged.")
    parser.add_argument(
        "--label",
        default=settings.GMAIL_PROCESSED_LABEL,
        help=f"Label to remove (default: {settings.GMAIL_PROCESSED_LABEL}).",
    )
    parser.add_argument(
        "--query",
        default=None,
        help="Optional Gmail search to narrow which labelled emails get reset, e.g. 'after:2026/09/18'.",
    )
    args = parser.parse_args()

    updated = gmail_connector.remove_label_from_matching(args.label, query=args.query)
    print(f"Removed '{args.label}' from {updated} email(s). They will be re-fetched on the next run.")


if __name__ == "__main__":
    main()
