import sys
import logging
import signal
import threading

from utils.database   import init_db
import collector.poller   as poller
import scheduler.runner   as scheduler
from api.routes       import run_api
from settings         import LOG_LEVEL, LOG_FILE

def _setup_logging():
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ]
    logging.basicConfig(level=getattr(logging, LOG_LEVEL, "INFO"),
                        format=fmt, handlers=handlers)

_shutdown = threading.Event()

def _handle_signal(sig, frame):
    logging.getLogger("main").info("Signal %s received — shutting down...", sig)
    poller.stop()
    scheduler.stop()
    _shutdown.set()
    sys.exit(0)

if __name__ == "__main__":
    _setup_logging()
    log = logging.getLogger("main")
    log.info("=== IFTA System starting ===")

    init_db()

    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    poller.start()
    scheduler.start()

    log.info("Starting API server...")
    try:
        run_api()
    except Exception:
        log.exception("API server crashed")
        poller.stop()
        scheduler.stop()
