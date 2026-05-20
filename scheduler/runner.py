"""
ifta/scheduler/runner.py

Ikkita parallel scheduler ishlaydi:

1. INTERVAL SCHEDULER — har REPORT_SEND_INTERVAL_HOURS soatda report
   yaratib DB ga saqlaydi va external API ga yuboradi.

2. DAY-END SCHEDULER — har kuni 23:59:59 da "daily closing" report
   yuboradi. Bu shu kunning boshidan (00:00:00) 23:59:59 gacha
   bo'lgan to'liq kunni qamrab oladi.

Sabab: agar interval 4 soat bo'lsa va 22:00 da report ketsa,
keyingisi ertangi 02:00 da ketadi — bu holda bugungi kun
hech qachon yakunlanmay qoladi. Day-end scheduler shu muammoni
hal qiladi: 23:59:59 da albatta shu kunning yakuniy reporti
yuboriladi.
"""

import time
import logging
import threading
from datetime import datetime, timezone, date, timedelta

from settings import (
    REPORT_SEND_INTERVAL_HOURS,
    AUTO_REPORT_TYPES,
)
from reports.builder import build_report, _period_bounds
from reports.sender  import save_report, send_to_external, retry_unsent

logger = logging.getLogger(__name__)

_stop_event = threading.Event()


# ── Yordamchi ────────────────────────────────────────────────

def _today_start_end() -> tuple[float, float]:
    """Bugungi kunning 00:00:00 va 23:59:59 (UTC) Unix timestamp lari."""
    today = date.today()
    start = datetime(today.year, today.month, today.day,
                     0, 0, 0, tzinfo=timezone.utc).timestamp()
    end   = datetime(today.year, today.month, today.day,
                     23, 59, 59, tzinfo=timezone.utc).timestamp()
    return start, end


def _seconds_until_midnight() -> float:
    """Bugungi 23:59:59 UTC ga qancha soniya qolgan."""
    now   = time.time()
    today = date.today()
    eod   = datetime(today.year, today.month, today.day,
                     23, 59, 59, tzinfo=timezone.utc).timestamp()
    diff  = eod - now
    # Agar allaqachon o'tgan bo'lsa (masalan server aynan 23:59:59 da ishga tushdi)
    # ertangi kunga o'tkazamiz
    if diff <= 0:
        diff += 86400
    return diff


# ── Interval scheduler ───────────────────────────────────────

def _run_interval_cycle():
    """Har N soatda: retry + barcha period turlari uchun report."""
    retry_unsent()

    for period_type in AUTO_REPORT_TYPES:
        try:
            start_ts, end_ts = _period_bounds(period_type)
            report    = build_report(period_type)
            report_id = save_report(report, period_type, start_ts, end_ts)
            logger.info("Interval: saved %s report #%d", period_type, report_id)
            send_to_external(report, report_id)
        except Exception:
            logger.exception("Interval error for period_type=%s", period_type)


def interval_loop():
    interval_sec = REPORT_SEND_INTERVAL_HOURS * 3600
    logger.info("Interval scheduler started (every %.1fh)", REPORT_SEND_INTERVAL_HOURS)

    while not _stop_event.is_set():
        _run_interval_cycle()
        logger.info("Next interval run in %.1f hours", REPORT_SEND_INTERVAL_HOURS)
        _stop_event.wait(interval_sec)

    logger.info("Interval scheduler stopped")


# ── Kun yakunlash scheduler ──────────────────────────────────

def _run_day_end_cycle():
    """
    Bugungi kunning 00:00:00 → 23:59:59 oralig'idagi daily report.
    Bu kun bo'yi yig'ilgan barcha telemetriyani qamrab oladi.
    """
    try:
        start_ts, end_ts = _today_start_end()
        report    = build_report("daily",
                                 custom_start=start_ts,
                                 custom_end=end_ts)
        report_id = save_report(report, "daily", start_ts, end_ts)
        logger.info("Day-end closing report saved #%d  (%.0f→%.0f)",
                    report_id, start_ts, end_ts)
        send_to_external(report, report_id)
    except Exception:
        logger.exception("Day-end report error")


def day_end_loop():
    """
    Har kuni 23:59:59 da bir marta daily closing report yuboradi.
    Keyin ertangi 23:59:59 gacha kutadi.
    """
    logger.info("Day-end scheduler started")

    while not _stop_event.is_set():
        wait_sec = _seconds_until_midnight()
        logger.info("Day-end: next closing report in %.0f seconds (%.1f hours)",
                    wait_sec, wait_sec / 3600)

        # Kutamiz — to'xtatish signali kelsa chiqamiz
        _stop_event.wait(wait_sec)
        if _stop_event.is_set():
            break

        _run_day_end_cycle()

        # Bir soniya kutamiz (23:59:59 → 00:00:00 o'tib ketmasligi uchun)
        _stop_event.wait(1)

    logger.info("Day-end scheduler stopped")


# ── Public API ───────────────────────────────────────────────

def start() -> list[threading.Thread]:
    """Ikkala schedulerni background thread da ishga tushiradi."""
    _stop_event.clear()

    t1 = threading.Thread(target=interval_loop, name="IntervalScheduler", daemon=True)
    t2 = threading.Thread(target=day_end_loop,  name="DayEndScheduler",   daemon=True)
    t1.start()
    t2.start()

    return [t1, t2]


def stop():
    """Ikkala schedulerni to'xtatish."""
    _stop_event.set()
