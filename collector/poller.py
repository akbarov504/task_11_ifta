import time
import logging
import threading
import requests

from settings import (
    CAN_API_URL,
    GPS_API_URL,
    POLL_INTERVAL_SECONDS,
)
from utils.database import db_cursor

logger = logging.getLogger(__name__)

_stop_event = threading.Event()

def _fetch_json(url: str) -> dict | None:
    try:
        resp = requests.get(url, timeout=4)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("API fetch error [%s]: %s", url, exc)
        return None

def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None

def _poll_once():
    now = time.time()

    can = _fetch_json(CAN_API_URL) or {}
    gps = _fetch_json(GPS_API_URL) or {}

    row = {
        "ts": now,

        "latitude":      _safe_float(gps.get("latitude")),
        "longitude":     _safe_float(gps.get("longitude")),
        "gps_speed_mph": _safe_float(gps.get("speed_mph")),
        "direction":     gps.get("direction"),
        "degree":        _safe_float(gps.get("degree")),
        "state":         gps.get("state"),
        "state_code":    gps.get("state_code"),

        "vehicle_speed":  _safe_float(can.get("vehicle_speed")),
        "engine_speed":   _safe_float(can.get("engine_speed")),
        "wheel_speed":    _safe_float(can.get("wheel_based_speed")),
        "fuel_level":     _safe_float(can.get("fuel_level")),
        "trip_distance":  _safe_float(can.get("trip_distance")),
        "total_distance": _safe_float(can.get("total_distance")),
        "engine_load":    _safe_float(can.get("engine_load")),
        "engine_temp":    _safe_float(can.get("engine_temp")),
        "vin":            can.get("vin"),
        "def_level":      _safe_float(can.get("def_level")),
        "engine_hours":   _safe_float(can.get("engine_hours")),
        "engine_status":  can.get("status"),
    }

    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO telemetry (
                ts, latitude, longitude, gps_speed_mph, direction, degree,
                state, state_code,
                vehicle_speed, engine_speed, wheel_speed, fuel_level,
                trip_distance, total_distance, engine_load, engine_temp,
                vin, def_level, engine_hours, engine_status
            ) VALUES (
                :ts, :latitude, :longitude, :gps_speed_mph, :direction, :degree,
                :state, :state_code,
                :vehicle_speed, :engine_speed, :wheel_speed, :fuel_level,
                :trip_distance, :total_distance, :engine_load, :engine_temp,
                :vin, :def_level, :engine_hours, :engine_status
            )
        """, row)

    logger.debug("Polled OK  state=%s  speed=%.1f  fuel=%.1f%%",
                 row["state"], row["vehicle_speed"] or 0, row["fuel_level"] or 0)

def poll_loop():
    logger.info("Poller started (interval=%ds)", POLL_INTERVAL_SECONDS)
    while not _stop_event.is_set():
        try:
            _poll_once()
        except Exception:
            logger.exception("Unexpected error in poll_once")
        _stop_event.wait(POLL_INTERVAL_SECONDS)
    logger.info("Poller stopped")

def start() -> threading.Thread:
    _stop_event.clear()
    t = threading.Thread(target=poll_loop, name="Poller", daemon=True)
    t.start()
    return t

def stop():
    _stop_event.set()
