"""
1. INTERVAL SCHEDULER — har REPORT_SEND_INTERVAL_HOURS soatda report yuboradi.
   Har tsikl FAQAT o'sha intervalning oralig'ini hisoblaydi (window-based):
     - 1-tsikl: start → start+1h   (masalan 10:00→11:00)
     - 2-tsikl: start+1h → start+2h (masalan 11:00→12:00)
   Kumulativ EMAS — har safar reset bo'ladi.

2. DAY-END SCHEDULER — har kuni UTC 23:59:59 da "daily closing" report yuboradi.
   Bu shu UTC kunning 00:00:00 → 23:59:59 ni qamrab oladi (to'liq kun).
"""

import time
import logging
import threading
from datetime import datetime, timezone, timedelta

from settings import (
    REPORT_SEND_INTERVAL_HOURS,
    AUTO_REPORT_TYPES,
)
from reports.builder import build_report
from reports.sender  import save_report, send_to_external, retry_unsent

logger = logging.getLogger(__name__)

_stop_event = threading.Event()

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

def _now_ts() -> float:
    return time.time()

def _today_utc_start_end() -> tuple[float, float]:
    """Bugungi UTC 00:00:00 → 23:59:59 Unix timestamp."""
    now   = _utc_now()
    start = now.replace(hour=0,  minute=0,  second=0,  microsecond=0)
    end   = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return start.timestamp(), end.timestamp()

def _seconds_until_utc_eod() -> float:
    """Bugungi UTC 23:59:59 ga qancha soniya qolgan."""
    now  = _utc_now()
    eod  = now.replace(hour=23, minute=59, second=59, microsecond=0)
    diff = (eod - now).total_seconds()
    if diff <= 0:
        eod  = eod + timedelta(days=1)
        diff = (eod - now).total_seconds()
    return diff

def _run_interval_cycle(window_start: float, window_end: float):
    retry_unsent()

    utc_str = _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info("Interval report window: [%.0f → %.0f]  UTC=%s",
                window_start, window_end, utc_str)

    for period_type in AUTO_REPORT_TYPES:
        try:
            report = build_report(
                period_type,
                custom_start=window_start,
                custom_end=window_end,
            )
            report_id = save_report(report, period_type, window_start, window_end)
            logger.info("Interval: saved %s report #%d  UTC=%s",
                        period_type, report_id, utc_str)
            send_to_external(report, report_id)
        except Exception:
            logger.exception("Interval error for period_type=%s", period_type)

def interval_loop():
    interval_sec = REPORT_SEND_INTERVAL_HOURS * 3600
    logger.info("Interval scheduler started (every %.1fh)", REPORT_SEND_INTERVAL_HOURS)

    window_start = _now_ts()

    while not _stop_event.is_set():
        _stop_event.wait(interval_sec)
        if _stop_event.is_set():
            break

        window_end   = _now_ts()
        _run_interval_cycle(window_start, window_end)
        window_start = window_end

    logger.info("Interval scheduler stopped")

def _run_day_end_cycle():
    start_ts, end_ts = _today_utc_start_end()
    utc_str = _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        report = build_report(
            "daily",
            custom_start=start_ts,
            custom_end=end_ts,
        )
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
        logger.info("Day-end: next closing in %.0fs (%.2fh)  UTC=%s",
                    wait_sec, wait_sec / 3600,
                    _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"))

        _stop_event.wait(wait_sec)
        if _stop_event.is_set():
            break

        _run_day_end_cycle()
        _stop_event.wait(1)

    logger.info("Day-end scheduler stopped")

def start() -> list[threading.Thread]:
    _stop_event.clear()
    t1 = threading.Thread(target=interval_loop, name="IntervalScheduler", daemon=True)
    t2 = threading.Thread(target=day_end_loop,  name="DayEndScheduler",   daemon=True)
    t1.start()
    t2.start()
    return [t1, t2]

def stop():
    _stop_event.set()
