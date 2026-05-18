import sqlite3
import logging
from contextlib import contextmanager
from settings import DB_PATH

logger = logging.getLogger(__name__)

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

@contextmanager
def db_cursor():
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with db_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS telemetry (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ts              REAL    NOT NULL,  -- Unix timestamp (float)

                -- GPS
                latitude        REAL,
                longitude       REAL,
                gps_speed_mph   REAL,
                direction       TEXT,
                degree          REAL,
                state           TEXT,   -- masalan "Texas"
                state_code      TEXT,   -- masalan "TX"

                -- CAN
                vehicle_speed   REAL,
                engine_speed    REAL,
                wheel_speed     REAL,
                fuel_level      REAL,
                trip_distance   REAL,
                total_distance  REAL,   -- odometer (miles)
                engine_load     REAL,
                engine_temp     REAL,
                vin             TEXT,
                def_level       REAL,
                engine_hours    REAL,
                engine_status   TEXT    -- "ON" | "OFF"
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_telemetry_ts
            ON telemetry(ts)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at   REAL    NOT NULL,   -- Unix timestamp
                period_type  TEXT    NOT NULL,   -- daily|weekly|monthly
                period_start REAL    NOT NULL,   -- Unix timestamp
                period_end   REAL    NOT NULL,   -- Unix timestamp
                payload      TEXT    NOT NULL,   -- JSON string
                sent         INTEGER NOT NULL DEFAULT 0,  -- 0|1
                sent_at      REAL                         -- Unix timestamp
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_reports_period
            ON reports(period_type, period_start)
        """)

    logger.info("DB initialized: %s", DB_PATH)
