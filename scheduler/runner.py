import logging
import threading

from settings import (
    REPORT_SEND_INTERVAL_HOURS,
    AUTO_REPORT_TYPES,
)
from reports.builder import build_report, _period_bounds
from reports.sender  import save_report, send_to_external, retry_unsent

logger = logging.getLogger(__name__)

_stop_event = threading.Event()

def _run_cycle():
    retry_unsent()

    for period_type in AUTO_REPORT_TYPES:
        try:
            start_ts, end_ts = _period_bounds(period_type)
            report = build_report(period_type)

            report_id = save_report(report, period_type, start_ts, end_ts)
            logger.info("Saved %s report #%d", period_type, report_id)

            send_to_external(report, report_id)

        except Exception:
            logger.exception("Error in scheduler cycle for period_type=%s", period_type)

def scheduler_loop():
    interval_sec = REPORT_SEND_INTERVAL_HOURS * 3600
    logger.info("Scheduler started (interval=%.1fh)", REPORT_SEND_INTERVAL_HOURS)

    while not _stop_event.is_set():
        _run_cycle()
        logger.info("Next scheduler run in %.1f hours", REPORT_SEND_INTERVAL_HOURS)
        _stop_event.wait(interval_sec)

    logger.info("Scheduler stopped")

def start() -> threading.Thread:
    _stop_event.clear()
    t = threading.Thread(target=scheduler_loop, name="Scheduler", daemon=True)
    t.start()
    return t

def stop():
    _stop_event.set()
