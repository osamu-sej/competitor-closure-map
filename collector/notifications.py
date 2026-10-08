"""Gmail notifications for newly observed closure signals."""
from __future__ import annotations

import json
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate
from typing import Callable


STATUS_RANK = {"CLOSED_SUSPECTED": 1, "CLOSED_CONFIRMED": 2}
STATUS_LABELS = {"CLOSED_SUSPECTED": "閉店の可能性", "CLOSED_CONFIRMED": "閉店確認済み"}
BRAND_LABELS = {"FAMILY_MART": "ファミリーマート", "LAWSON": "ローソン"}
DEFAULT_APP_URL = "https://competitor-closure-map.onrender.com/"


def pending_notifications(state: dict) -> list[tuple[dict, dict]]:
    """Return each store event whose closure status has advanced since its last alert."""
    stores = {str(store["id"]): store for store in state.get("stores", [])}
    pending = []
    for event in state.get("events", []):
        status = str(event.get("status", ""))
        rank = STATUS_RANK.get(status, 0)
        previous_rank = STATUS_RANK.get(str(event.get("notified_status", "")), 0)
        store = stores.get(str(event.get("store_id", "")))
        if rank > previous_rank and store:
            pending.append((event, store))
    return pending


def build_email(items: list[tuple[dict, dict]], sender: str, app_url: str = DEFAULT_APP_URL) -> EmailMessage:
    count = len(items)
    message = EmailMessage()
    message["Subject"] = f"【競合閉店MAP】新しい閉店シグナル {count}件"
    message["From"] = sender
    message["To"] = sender
    message["Date"] = formatdate(localtime=False)
    message["X-Closure-Map-Events"] = ",".join(
        f"{event['id']}:{event['status']}" for event, _store in items
    )

    lines = [f"競合閉店MAPで新しい閉店シグナルを{count}件検知しました。", ""]
    for index, (event, store) in enumerate(items, start=1):
        lines.extend([
            f"{index}. {store.get('canonical_name') or '店舗名不明'}",
            f"ブランド: {BRAND_LABELS.get(str(store.get('brand_family')), store.get('brand_family', '不明'))}",
            f"状態: {STATUS_LABELS.get(str(event.get('status')), event.get('status', '不明'))}",
            f"住所: {store.get('address') or '住所不明'}",
            f"検知日: {event.get('detected_at') or '不明'}",
            f"最終確認日: {event.get('last_seen_at') or '不明'}",
        ])
        distance = event.get("distance_m")
        nearest_name = event.get("nearest_seven_name")
        if distance is not None:
            nearest = f"（{nearest_name}）" if nearest_name else ""
            lines.append(f"最寄りの収録セブン-イレブン: {float(distance):.0f}m{nearest}")
        else:
            lines.append("最寄りの収録セブン-イレブン: 距離未算出")
        lines.append("")
    lines.extend([
        "掲載元のデータから消えたことだけでは、閉店が確定したとは限りません。",
        f"地図で確認: {app_url}",
    ])
    message.set_content("\n".join(lines))
    return message


def send_gmail_notifications(
    items: list[tuple[dict, dict]],
    credentials_json: str,
    *,
    app_url: str = DEFAULT_APP_URL,
    smtp_factory: Callable = smtplib.SMTP,
) -> str:
    """Send one digest email and return its sender address."""
    try:
        credentials = json.loads(credentials_json)
    except json.JSONDecodeError as error:
        raise ValueError("GMAIL_SMTP_CREDENTIALS must be valid JSON") from error
    if not isinstance(credentials, dict):
        raise ValueError("GMAIL_SMTP_CREDENTIALS must be a JSON object")
    sender = str(credentials.get("email", "")).strip()
    password = str(credentials.get("app_password", "")).replace(" ", "")
    if not sender or not password:
        raise ValueError("GMAIL_SMTP_CREDENTIALS must contain email and app_password")

    message = build_email(items, sender, app_url)
    with smtp_factory("smtp.gmail.com", 587, timeout=30) as server:
        server.ehlo()
        server.starttls(context=ssl.create_default_context())
        server.ehlo()
        server.login(sender, password)
        server.send_message(message)
    return sender
