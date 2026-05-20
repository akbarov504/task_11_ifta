"""
ifta/scheduler/runner.py

Ikkita parallel scheduler:

1. INTERVAL SCHEDULER — har REPORT_SEND_INTERVAL_HOURS soatda report yuboradi.

2. DAY-END SCHEDULER — har kuni UTC 23:59:59 da "daily closing" report yuboradi.
   Bu shu UTC kunning 00:00:00 → 23:59:59 oralig'ini qamrab oladi.

MUHIM: Barcha vaqt hisoblari UTC da. date.today() ISHLATILMAYDI.
"""

import time
import logging
import threading
from datetime import datetime, timezone, timedelta

from settings import (
    REPORT_SEND_INTERVAL_HOURS,
    AUTO_REPORT_TYPES,
)
from reports.builder import build_report, _period_bounds
from reports.sender  import save_report, send_to_external, retry_unsent

logger = logging.getLogger(__name__)

_stop_event = threading.Event()


# ── UTC yordamchi funksiyalar ────────────────────────────────

def _utc_now() -> datetime:
    """Hozirgi UTC datetime."""
    return datetime.now(timezone.utc)


def _today_utc_start_end() -> tuple[float, float]:
    """
    UTC bo'yicha bugungi kunning boshlanishi va oxiri (Unix timestamp).
    00:00:00 UTC → 23:59:59 UTC
    """
    now   = _utc_now()
    start = now.replace(hour=0,  minute=0,  second=0,  microsecond=0)
    end   = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return start.timestamp(), end.timestamp()


def _seconds_until_utc_eod() -> float:
    """
    Bugungi UTC 23:59:59 ga qancha soniya qolgan.
    Agar o'tib ketgan bo'lsa — ertangi UTC 23:59:59 gacha.
    """
    now = _utc_now()
    eod = now.replace(hour=23, minute=59, second=59, microsecond=0)
    diff = (eod - now).total_seconds()
    if diff <= 0:
        # O'tib ketgan — ertangi eod
        eod  = eod + timedelta(days=1)
        diff = (eod - now).total_seconds()
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
            logger.info("Interval: saved %s report #%d  UTC=%s",
                        period_type, report_id,
                        _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"))
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
    UTC bugungi kunning 00:00:00 → 23:59:59 oralig'idagi daily closing report.
    """
    start_ts, end_ts = _today_utc_start_end()
    utc_str = _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        report    = build_report("daily",
                                 custom_start=start_ts,
                                 custom_end=end_ts)
        report_id = save_report(report, "daily", start_ts, end_ts)
        logger.info("Day-end closing report #%d saved  UTC=%s  range=[%.0f → %.0f]",
                    report_id, utc_str, start_ts, end_ts)
        send_to_external(report, report_id)
    except Exception:
        logger.exception("Day-end report error at UTC=%s", utc_str)


def day_end_loop():
    """Har kuni UTC 23:59:59 da bir marta daily closing report yuboradi."""
    logger.info("Day-end scheduler started (fires at UTC 23:59:59 daily)")

    while not _stop_event.is_set():
        wait_sec = _seconds_until_utc_eod()
        logger.info("Day-end: next closing report in %.0fs (%.2fh)  UTC=%s",
                    wait_sec, wait_sec / 3600,
                    _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"))

        _stop_event.wait(wait_sec)
        if _stop_event.is_set():
            break

        _run_day_end_cycle()

        # 1 soniya — 23:59:59 → 00:00:00 o'tib ketmasligi uchun
        _stop_event.wait(1)

    logger.info("Day-end scheduler stopped")


# ── Public API ───────────────────────────────────────────────

def start() -> list[threading.Thread]:
    _stop_event.clear()
    t1 = threading.Thread(target=interval_loop, name="IntervalScheduler", daemon=True)
    t2 = threading.Thread(target=day_end_loop,  name="DayEndScheduler",   daemon=True)
    t1.start()
    t2.start()
    return [t1, t2]


def stop():
    _stop_event.set()
