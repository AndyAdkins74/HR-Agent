"""One-time local OAuth helper for the Gmail connector.

This script is NOT part of the agent's runtime loop. Run it once, on a
machine with a web browser (not in a headless/remote sandbox), to
complete Google's OAuth consent screen and produce a token.json. Copy
the resulting token.json into config/token.json (or wherever
GMAIL_TOKEN_PATH points) so main.py can use it.

Usage:
    python scripts/generate_token.py \
        --credentials config/credentials.json \
        --token config/token.json
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow

from config import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a Gmail OAuth token.json for HR-Agent.")
    parser.add_argument(
        "--credentials",
        default=settings.GMAIL_CREDENTIALS_PATH,
        help="Path to the OAuth client secret file downloaded from Google Cloud Console.",
    )
    parser.add_argument(
        "--token",
        default=settings.GMAIL_TOKEN_PATH,
        help="Where to write the resulting token.json.",
    )
    args = parser.parse_args()

    if not Path(args.credentials).exists():
        raise SystemExit(
            f"Credentials file not found at {args.credentials}. Download it from "
            "Google Cloud Console (APIs & Services > Credentials > OAuth client "
            "ID, Desktop app type) first."
        )

    flow = InstalledAppFlow.from_client_secrets_file(args.credentials, settings.GMAIL_SCOPES)
    creds = flow.run_local_server(port=0)

    token_path = Path(args.token)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")

    print(f"Saved token to {token_path}")


if __name__ == "__main__":
    main()
