"""Gmail implementation of the connection layer.

This is the only module in the project allowed to know that it is
talking to Gmail, OAuth, or the Google API client. It exposes plain
functions -- get_emails(), save_attachment(), mark_processed() -- that
return simple dataclasses/paths, so the decision layer never has to
know where an email came from.
"""
import base64
import os
from dataclasses import dataclass, field
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import settings


@dataclass
class Attachment:
    attachment_id: str
    filename: str
    mime_type: str


@dataclass
class EmailMessage:
    message_id: str
    thread_id: str
    subject: str
    sender: str
    body: str
    attachments: List[Attachment] = field(default_factory=list)


def _get_credentials() -> Credentials:
    if not os.path.exists(settings.GMAIL_TOKEN_PATH):
        raise RuntimeError(
            f"No Gmail token found at {settings.GMAIL_TOKEN_PATH}. Run "
            "scripts/generate_token.py on a machine with a browser to "
            "complete the OAuth consent flow, then copy the resulting "
            "token.json here."
        )
    creds = Credentials.from_authorized_user_file(
        settings.GMAIL_TOKEN_PATH, settings.GMAIL_SCOPES
    )
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(settings.GMAIL_TOKEN_PATH, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())
    return creds


def _service():
    creds = _get_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _extract_header(headers, name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _decode_body(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode("UTF-8")).decode("UTF-8", errors="replace")


def _extract_body_and_attachments(payload: dict):
    body_parts: List[str] = []
    attachments: List[Attachment] = []

    def walk(part: dict) -> None:
        mime_type = part.get("mimeType", "")
        filename = part.get("filename", "")
        body = part.get("body", {})

        if filename:
            attachment_id = body.get("attachmentId")
            if attachment_id:
                attachments.append(
                    Attachment(attachment_id=attachment_id, filename=filename, mime_type=mime_type)
                )
        elif mime_type == "text/plain" and body.get("data"):
            body_parts.append(_decode_body(body["data"]))
        elif mime_type == "text/html" and body.get("data") and not body_parts:
            body_parts.append(_decode_body(body["data"]))

        for sub_part in part.get("parts", []) or []:
            walk(sub_part)

    walk(payload)
    return "\n".join(body_parts).strip(), attachments


def get_emails(query: Optional[str] = None, max_results: Optional[int] = None) -> List[EmailMessage]:
    """Fetch emails matching `query` and return them as plain EmailMessage objects."""
    service = _service()
    query = settings.GMAIL_QUERY if query is None else query
    max_results = settings.GMAIL_MAX_RESULTS if max_results is None else max_results

    response = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    message_refs = response.get("messages", [])

    emails: List[EmailMessage] = []
    for ref in message_refs:
        full_message = (
            service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        )
        payload = full_message.get("payload", {})
        headers = payload.get("headers", [])
        body, attachments = _extract_body_and_attachments(payload)
        emails.append(
            EmailMessage(
                message_id=full_message["id"],
                thread_id=full_message.get("threadId", ""),
                subject=_extract_header(headers, "Subject"),
                sender=_extract_header(headers, "From"),
                body=body,
                attachments=attachments,
            )
        )
    return emails


def save_attachment(message_id: str, attachment: Attachment, output_dir: Optional[str] = None) -> str:
    """Download one attachment from Gmail and write it to `output_dir`. Returns the saved path."""
    service = _service()
    output_dir = settings.ATTACHMENT_OUTPUT_DIR if output_dir is None else output_dir
    os.makedirs(output_dir, exist_ok=True)

    raw = (
        service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=message_id, id=attachment.attachment_id)
        .execute()
    )
    data = base64.urlsafe_b64decode(raw["data"].encode("UTF-8"))

    safe_filename = os.path.basename(attachment.filename)
    destination = os.path.join(output_dir, f"{message_id}_{safe_filename}")
    with open(destination, "wb") as f:
        f.write(data)
    return destination


def _get_or_create_label(service, label_name: str) -> str:
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for label in labels:
        if label["name"] == label_name:
            return label["id"]
    created = (
        service.users()
        .labels()
        .create(
            userId="me",
            body={
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )
        .execute()
    )
    return created["id"]


def mark_processed(message_id: str, label_name: Optional[str] = None) -> None:
    """Apply the processed label to a message so future queries skip it."""
    service = _service()
    label_name = settings.GMAIL_PROCESSED_LABEL if label_name is None else label_name
    label_id = _get_or_create_label(service, label_name)
    service.users().messages().modify(
        userId="me", id=message_id, body={"addLabelIds": [label_id]}
    ).execute()


def flag_for_review(message_id: str, label_name: Optional[str] = None) -> None:
    """Apply the needs-review label so a flagged email is visible in Gmail
    itself, not just in the decision log."""
    service = _service()
    label_name = settings.GMAIL_REVIEW_LABEL if label_name is None else label_name
    label_id = _get_or_create_label(service, label_name)
    service.users().messages().modify(
        userId="me", id=message_id, body={"addLabelIds": [label_id]}
    ).execute()


def remove_label_from_matching(label_name: str, query: Optional[str] = None) -> int:
    """Remove `label_name` from every message currently carrying it (optionally
    narrowed by `query`). Used to force re-triage of previously seen emails
    after the classification prompt/criteria change. Returns the number of
    messages updated."""
    service = _service()
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    label_id = next((label["id"] for label in labels if label["name"] == label_name), None)
    if label_id is None:
        return 0

    search_query = f"label:{label_name}" if query is None else f"{query} label:{label_name}"
    updated = 0
    page_token = None
    while True:
        list_kwargs = {"userId": "me", "q": search_query}
        if page_token:
            list_kwargs["pageToken"] = page_token
        response = service.users().messages().list(**list_kwargs).execute()

        for ref in response.get("messages", []):
            service.users().messages().modify(
                userId="me", id=ref["id"], body={"removeLabelIds": [label_id]}
            ).execute()
            updated += 1

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return updated
