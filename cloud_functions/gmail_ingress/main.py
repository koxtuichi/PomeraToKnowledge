"""
Gmail Push notification ingress for PomeraToKnowledge.

Gmail publishes mailbox notifications to Pub/Sub. This function receives those
notifications, resolves changed Gmail messages via the History API, classifies
subjects, and forwards matching mail bodies to the existing processing Cloud
Functions.
"""
import base64
import email
import imaplib
import json
import os
import re
from datetime import datetime, timezone
from email.header import decode_header

import functions_framework
import requests
from google.cloud import storage
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
DEFAULT_ENDPOINT_BASE = "https://asia-northeast1-pomeradriven.cloudfunctions.net"
STATE_PATH = os.environ.get("GMAIL_STATE_PATH", "gmail_push/state.json")
MAX_PROCESSED_IDS = int(os.environ.get("GMAIL_MAX_PROCESSED_IDS", "1000"))
POLL_MAX_MESSAGES = int(os.environ.get("GMAIL_POLL_MAX_MESSAGES", "10"))


ROUTES = [
    {
        "category": "POMERA",
        "include": ["POMERA"],
        "exclude": [],
        "endpoint_env": "PROCESS_DIARY_URL",
        "default_path": "process-diary",
        "source": "pomera",
        "needs_body": True,
    },
    {
        "category": "DIARY",
        "include": ["DIARY"],
        "exclude": [],
        "endpoint_env": "PROCESS_DIARY_URL",
        "default_path": "process-diary",
        "source": "diary",
        "needs_body": True,
    },
    {
        "category": "BLOG",
        "include": ["BLOG"],
        "exclude": ["POMERA"],
        "endpoint_env": "PROCESS_BLOG_URL",
        "default_path": "process-blog",
        "source": "blog",
        "needs_body": True,
    },
    {
        "category": "STORY",
        "include": ["STORY"],
        "exclude": ["POMERA", "BLOG"],
        "endpoint_env": "PROCESS_STORY_URL",
        "default_path": "process-story",
        "source": "story",
        "needs_body": False,
    },
    {
        "category": "SECBLOG",
        "include": ["SECBLOG"],
        "exclude": [],
        "endpoint_env": "PROCESS_SECBLOG_URL",
        "default_path": "process-secblog",
        "source": "secblog",
        "needs_body": True,
    },
    {
        "category": "FINCTX",
        "include": ["FINCTX"],
        "exclude": [],
        "endpoint_env": "PROCESS_FINANCE_URL",
        "default_path": None,
        "source": "finance",
        "needs_body": True,
    },
]


@functions_framework.cloud_event
def gmail_ingress(cloud_event):
    """Handle a Gmail Pub/Sub CloudEvent."""
    notification = _decode_pubsub_notification(cloud_event.data)
    history_id = notification.get("historyId")
    if not history_id:
        print(f"⚠️ historyId missing in notification: {notification}")
        return

    state = _load_state()
    start_history_id = state.get("history_id")
    if not start_history_id:
        state["history_id"] = history_id
        state["initialized_at"] = _now()
        _save_state(state)
        print(f"✅ Gmail history state initialized at {history_id}")
        return

    service = _gmail_service()
    processed_history = state.get("processed_message_ids", [])
    processed_ids = set(processed_history)
    newly_processed = []
    try:
        message_ids = _list_changed_message_ids(service, start_history_id)
    except HttpError as exc:
        if exc.resp.status == 404:
            state["history_id"] = history_id
            state["history_reset_at"] = _now()
            state["history_reset_reason"] = "startHistoryId expired"
            _save_state(state)
            print(f"⚠️ Gmail history expired. Reset cursor to {history_id}")
            return
        raise
    print(f"📬 Gmail notification {start_history_id} -> {history_id}: {len(message_ids)} changed messages")

    routed = []
    failures = []
    for message_id in message_ids:
        if message_id in processed_ids:
            continue

        message = _get_message(service, message_id)
        if _require_unread() and "UNREAD" not in message.get("labelIds", []):
            continue

        subject = _get_subject(message)
        route = _match_route(subject)
        if not route:
            continue

        body = _get_plain_body(service, message)
        if route["needs_body"] and not body:
            failures.append({"id": message_id, "subject": subject, "error": "empty body"})
            continue

        try:
            _forward_message(route, subject, body, message_id, history_id)
            routed.append({"id": message_id, "subject": subject, "category": route["category"]})
            processed_ids.add(message_id)
            newly_processed.append(message_id)
            if _mark_read_enabled() and "UNREAD" in message.get("labelIds", []):
                try:
                    _mark_read(service, message_id)
                except Exception as exc:
                    print(f"⚠️ Failed to mark read: {message_id}: {exc}")
        except Exception as exc:
            failures.append({"id": message_id, "subject": subject, "error": str(exc)})

    state["processed_message_ids"] = (processed_history + newly_processed)[-MAX_PROCESSED_IDS:]
    state["last_notification_history_id"] = history_id
    state["last_checked_at"] = _now()

    if failures:
        state["last_failures"] = failures[-20:]
        _save_state(state)
        raise RuntimeError(f"Gmail ingress failures: {json.dumps(failures, ensure_ascii=False)}")

    state["history_id"] = history_id
    state["last_routed"] = routed[-20:]
    state.pop("last_failures", None)
    _save_state(state)
    print(f"✅ Gmail ingress completed: routed={len(routed)}")


@functions_framework.http
def poll_gmail(request):
    """Poll unread Gmail messages over IMAP. Used when OAuth watch is unavailable."""
    if request.method == "OPTIONS":
        return ("", 204, _cors_headers())

    account = os.environ.get("GMAIL_ACCOUNT")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not account or not password:
        return _json_response({"error": "GMAIL_ACCOUNT or GMAIL_APP_PASSWORD is not set"}, 500)

    state = _load_state()
    processed_history = state.get("poll_processed_message_ids", [])
    processed_ids = set(processed_history)
    newly_processed = []
    routed = []
    failures = []

    mailbox = os.environ.get("GMAIL_MAILBOX", "INBOX")
    search_query = os.environ.get("GMAIL_IMAP_SEARCH", "UNSEEN")

    with imaplib.IMAP4_SSL(os.environ.get("GMAIL_IMAP_SERVER", "imap.gmail.com"), timeout=30) as mail:
        mail.login(account, password)
        status, _ = mail.select(mailbox)
        if status != "OK":
            return _json_response({"error": f"failed to select mailbox: {mailbox}"}, 500)

        status, data = mail.search(None, search_query)
        if status != "OK":
            return _json_response({"error": f"failed to search mailbox: {search_query}"}, 500)

        raw_ids = data[0].split()
        if POLL_MAX_MESSAGES > 0:
            raw_ids = raw_ids[-POLL_MAX_MESSAGES:]

        for raw_id in raw_ids:
            uid = _imap_uid(mail, raw_id)
            if not uid or uid in processed_ids:
                continue

            subject = _imap_subject(mail, raw_id)
            route = _match_route(subject)
            if not route:
                continue

            status, message_data = mail.fetch(raw_id, "(BODY.PEEK[])")
            if status != "OK" or not message_data:
                continue

            message = None
            for item in message_data:
                if isinstance(item, tuple):
                    message = email.message_from_bytes(item[1])
                    break
            if message is None:
                continue

            body = _plain_body_from_email(message)
            if route["needs_body"] and not body:
                failures.append({"uid": uid, "subject": subject, "error": "empty body"})
                continue

            try:
                _forward_message(route, subject, body, uid, state.get("last_notification_history_id", "imap"))
                routed.append({"uid": uid, "subject": subject, "category": route["category"]})
                processed_ids.add(uid)
                newly_processed.append(uid)
                if _mark_read_enabled():
                    mail.store(raw_id, "+FLAGS", "\\Seen")
            except Exception as exc:
                failures.append({"uid": uid, "subject": subject, "error": str(exc)})

    state["poll_processed_message_ids"] = (processed_history + newly_processed)[-MAX_PROCESSED_IDS:]
    state["poll_last_checked_at"] = _now()
    state["poll_last_routed"] = routed[-20:]

    if failures:
        state["poll_last_failures"] = failures[-20:]
        _save_state(state)
        return _json_response({"status": "partial_failure", "routed": routed, "failures": failures}, 500)

    state.pop("poll_last_failures", None)
    _save_state(state)
    return _json_response({"status": "ok", "routed_count": len(routed), "routed": routed})


@functions_framework.http
def refresh_gmail_watch(request):
    """Renew the Gmail watch. Run daily from Cloud Scheduler."""
    if request.method == "OPTIONS":
        return ("", 204, _cors_headers())

    topic_name = os.environ.get("GMAIL_PUBSUB_TOPIC")
    if not topic_name:
        return _json_response({"error": "GMAIL_PUBSUB_TOPIC is not set"}, 500)

    label_ids = _csv_env("GMAIL_LABEL_IDS", default=["INBOX"])
    body = {
        "topicName": topic_name,
        "labelIds": label_ids,
        "labelFilterBehavior": "INCLUDE",
    }

    service = _gmail_service()
    response = service.users().watch(userId=_gmail_user(), body=body).execute()
    state = _load_state()
    if not state.get("history_id"):
        state["history_id"] = response.get("historyId")
        state["initialized_at"] = _now()
    state["watch_history_id"] = response.get("historyId")
    state["watch_expiration"] = response.get("expiration")
    state["watch_refreshed_at"] = _now()
    state["watch_label_ids"] = label_ids
    _save_state(state)

    print(f"✅ Gmail watch refreshed: {json.dumps(response, ensure_ascii=False)}")
    return _json_response({"status": "ok", "watch": response})


def _decode_pubsub_notification(data):
    message = data.get("message", data) if isinstance(data, dict) else {}
    encoded = message.get("data", "")
    if not encoded:
        return {}
    padding = "=" * (-len(encoded) % 4)
    decoded = base64.urlsafe_b64decode((encoded + padding).encode("ascii")).decode("utf-8")
    return json.loads(decoded)


def _gmail_service():
    refresh_token = os.environ.get("GMAIL_OAUTH_REFRESH_TOKEN")
    client_id = os.environ.get("GMAIL_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GMAIL_OAUTH_CLIENT_SECRET")
    if not refresh_token or not client_id or not client_secret:
        raise RuntimeError("Gmail OAuth env vars are not set")

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _gmail_user():
    return os.environ.get("GMAIL_ACCOUNT") or "me"


def _list_changed_message_ids(service, start_history_id):
    ids = []
    page_token = None
    while True:
        try:
            request = service.users().history().list(
                userId=_gmail_user(),
                startHistoryId=start_history_id,
                historyTypes=["messageAdded"],
                pageToken=page_token,
                maxResults=100,
            )
            response = request.execute()
        except HttpError:
            raise

        for item in response.get("history", []):
            for added in item.get("messagesAdded", []):
                message_id = added.get("message", {}).get("id")
                if message_id:
                    ids.append(message_id)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return list(dict.fromkeys(ids))


def _get_message(service, message_id):
    return service.users().messages().get(userId=_gmail_user(), id=message_id, format="full").execute()


def _get_subject(message):
    headers = message.get("payload", {}).get("headers", [])
    raw = next((h.get("value", "") for h in headers if h.get("name", "").lower() == "subject"), "")
    return _decode_header(raw)


def _decode_header(value):
    parts = []
    for fragment, encoding in decode_header(value or ""):
        if isinstance(fragment, bytes):
            parts.append(fragment.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(fragment)
    return "".join(parts)


def _imap_uid(mail, raw_id):
    status, data = mail.fetch(raw_id, "(UID)")
    if status != "OK" or not data or not data[0]:
        return None
    text = data[0].decode("utf-8", errors="replace") if isinstance(data[0], bytes) else str(data[0])
    match = re.search(r"UID (\d+)", text)
    return match.group(1) if match else None


def _imap_subject(mail, raw_id):
    status, data = mail.fetch(raw_id, "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
    if status != "OK" or not data:
        return ""
    for item in data:
        if isinstance(item, tuple):
            header_message = email.message_from_bytes(item[1])
            return _decode_header(header_message.get("Subject", ""))
    return ""


def _plain_body_from_email(message):
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in (part.get("Content-Disposition") or ""):
                return _decode_email_payload(part)
        for part in message.walk():
            filename = part.get_filename() or ""
            if filename.lower().endswith(".txt"):
                return _decode_email_payload(part)
        return ""
    return _decode_email_payload(message)


def _decode_email_payload(part):
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace").strip()


def _get_plain_body(service, message):
    message_id = message.get("id")
    payload = message.get("payload", {})
    text = _extract_text_part(service, message_id, payload)
    if text:
        return text.strip()
    attachment_text = _extract_text_attachment(service, message_id, payload)
    return attachment_text.strip() if attachment_text else ""


def _extract_text_part(service, message_id, part):
    mime_type = part.get("mimeType", "")
    filename = part.get("filename", "")
    body = part.get("body", {})
    if mime_type == "text/plain" and not filename and body.get("data"):
        return _decode_body_data(body["data"])

    for child in part.get("parts", []) or []:
        text = _extract_text_part(service, message_id, child)
        if text:
            return text
    return ""


def _extract_text_attachment(service, message_id, part):
    filename = part.get("filename", "")
    body = part.get("body", {})
    if filename.lower().endswith(".txt") and body.get("attachmentId"):
        attachment = service.users().messages().attachments().get(
            userId=_gmail_user(),
            messageId=message_id,
            id=body["attachmentId"],
        ).execute()
        return _decode_body_data(attachment.get("data", ""))

    for child in part.get("parts", []) or []:
        text = _extract_text_attachment(service, message_id, child)
        if text:
            return text
    return ""


def _decode_body_data(data):
    padding = "=" * (-len(data) % 4)
    raw = base64.urlsafe_b64decode((data + padding).encode("ascii"))
    return raw.decode("utf-8", errors="replace")


def _match_route(subject):
    normalized = subject.upper()
    for route in ROUTES:
        if not _endpoint_for(route):
            continue
        if all(term.upper() in normalized for term in route["include"]) and not any(
            term.upper() in normalized for term in route["exclude"]
        ):
            return route
    return None


def _endpoint_for(route):
    value = os.environ.get(route["endpoint_env"])
    if value:
        return value
    if not route["default_path"]:
        return ""
    base = os.environ.get("PROCESS_ENDPOINT_BASE", DEFAULT_ENDPOINT_BASE).rstrip("/")
    return f"{base}/{route['default_path']}"


def _forward_message(route, subject, body, message_id, history_id):
    payload = {
        "subject": subject,
        "body": body,
        "source": route["source"],
        "gmail_message_id": message_id,
        "gmail_history_id": history_id,
    }
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("POMERA_INTERNAL_TOKEN")
    if token:
        headers["X-Pomera-Internal-Token"] = token

    timeout = int(os.environ.get("PROCESS_REQUEST_TIMEOUT_SECONDS", "540"))
    endpoint = _endpoint_for(route)
    response = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(f"{route['category']} endpoint failed: {response.status_code} {response.text[:200]}")
    print(f"✅ Routed {message_id} to {route['category']}: {subject}")


def _mark_read(service, message_id):
    service.users().messages().modify(
        userId=_gmail_user(),
        id=message_id,
        body={"removeLabelIds": ["UNREAD"]},
    ).execute()


def _mark_read_enabled():
    return os.environ.get("GMAIL_MARK_READ", "true").lower() == "true"


def _require_unread():
    return os.environ.get("GMAIL_REQUIRE_UNREAD", "true").lower() == "true"


def _csv_env(name, default=None):
    value = os.environ.get(name)
    if not value:
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]


def _load_state():
    bucket = _bucket()
    blob = bucket.blob(STATE_PATH)
    if not blob.exists():
        return {}
    return json.loads(blob.download_as_text(encoding="utf-8"))


def _save_state(state):
    bucket = _bucket()
    blob = bucket.blob(STATE_PATH)
    blob.upload_from_string(
        json.dumps(state, ensure_ascii=False, indent=2),
        content_type="application/json",
    )


def _bucket():
    bucket_name = os.environ.get("GCS_BUCKET", "pomera-knowledge-data")
    return storage.Client().bucket(bucket_name)


def _json_response(body, status=200):
    return (json.dumps(body, ensure_ascii=False), status, {"Content-Type": "application/json", **_cors_headers()})


def _cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Max-Age": "3600",
    }


def _now():
    return datetime.now(timezone.utc).isoformat()
