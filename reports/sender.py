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
    Faqat 'daily' period_type yuboriladi.
    Body: { summary, states }
    """
    if report["meta"]["period_type"] != "daily":
        return False

    try:
        token = get_valid_token()
    except Exception as exc:
        logger.error("Report #%d — token olishda xato: %s", report_id, exc)
        return False

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    body = {
        "summary": report["summary"],
        "states":  report["states"],
    }

    logger.debug("Report #%d body: %s", report_id, json.dumps(body, ensure_ascii=False))

    try:
        resp = requests.post(
            EXTERNAL_REPORT_API_URL,
            json=body,
            headers=headers,
            timeout=EXTERNAL_API_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        logger.error("Report #%d — timeout (%ss): %s",
                     report_id, EXTERNAL_API_TIMEOUT, EXTERNAL_REPORT_API_URL)
        return False
    except requests.exceptions.ConnectionError as exc:
        logger.error("Report #%d — ulanish xatosi: %s", report_id, exc)
        return False
    except requests.exceptions.RequestException as exc:
        logger.error("Report #%d — so'rov xatosi: %s", report_id, exc)
        return False

    if not resp.ok:
        logger.error(
            "Report #%d — server xatosi: HTTP %d\n  URL: %s\n  Response: %s",
            report_id, resp.status_code,
            EXTERNAL_REPORT_API_URL,
            resp.text[:500] if resp.text else "(bo'sh)"
        )
        return False

    _mark_sent(report_id)
    logger.info("Report #%d yuborildi — HTTP %d", report_id, resp.status_code)
    return True


def retry_unsent():
    """Yuborib bo'lmaganlarni qayta urinadi."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, payload FROM reports WHERE sent = 0 ORDER BY created_at ASC
        """)
        rows = cur.fetchall()

    if not rows:
        return

    logger.info("Retry: %d ta yuborilmagan report", len(rows))
    for row in rows:
        try:
            report = json.loads(row["payload"])
        except json.JSONDecodeError as exc:
            logger.error("Report #%d — DB dagi payload noto'g'ri JSON: %s", row["id"], exc)
            continue
        send_to_external(report, row["id"])


def _mark_sent(report_id: int):
    with db_cursor() as cur:
        cur.execute("""
            UPDATE reports SET sent = 1, sent_at = ? WHERE id = ?
        """, (time.time(), report_id))
