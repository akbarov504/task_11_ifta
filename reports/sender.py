import json
import time
import logging
import requests

from settings import (
    EXTERNAL_REPORT_API_URL,
    EXTERNAL_API_TIMEOUT,
)
from utils.database import db_cursor
from utils.token_manager import get_valid_token

logger = logging.getLogger(__name__)


def save_report(report: dict, period_type: str,
                period_start: float, period_end: float) -> int:
    """To'liq reportni (meta+current_status+summary+states) DB ga saqlaydi."""
    payload = json.dumps(report, ensure_ascii=False)
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO reports
                (created_at, period_type, period_start, period_end, payload, sent)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (time.time(), period_type, period_start, period_end, payload))
        return cur.lastrowid


def send_to_external(report: dict, report_id: int) -> bool:
    """
    External logistika API ga yuboradi.
    Body: faqat { summary, states } — meta va current_status yuborilmaydi.
    """
    token = get_valid_token()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    body = {
        "summary": report["summary"],
        "states":  report["states"],
    }
    json_body = json.dumps(body)
    print("JSON BODY - ", body)
    try:
        resp = requests.post(
            EXTERNAL_REPORT_API_URL,
            json=json_body,
            headers=headers,
            timeout=EXTERNAL_API_TIMEOUT,
        )
        resp.raise_for_status()
        _mark_sent(report_id)
        logger.info("Report #%d sent to external API (status=%d)", report_id, resp.status_code)
        return True
    except requests.exceptions.RequestException as exc:
        logger.error("Failed to send report #%d: %s", report_id, exc)
        return False


def retry_unsent():
    """Yuborib bo'lmaganlarni qayta urinadi."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, payload FROM reports WHERE sent = 0 ORDER BY created_at ASC
        """)
        rows = cur.fetchall()

    if not rows:
        return

    logger.info("Retrying %d unsent report(s)", len(rows))
    for row in rows:
        report = json.loads(row["payload"])
        send_to_external(report, row["id"])


def _mark_sent(report_id: int):
    with db_cursor() as cur:
        cur.execute("""
            UPDATE reports SET sent = 1, sent_at = ? WHERE id = ?
        """, (time.time(), report_id))
