"""
{
  "meta": { period_type, start, end, generated_at },
  "current_status": { ... },   ← eng so'nggi qator
  "summary": { total_miles, total_drive_seconds, total_idle_seconds },
  "states": [
    {
      "state": "TX", "state_name": "Texas",
      "entry_time": "...", "exit_time": "...",
      "miles": 123.4, "drive_seconds": 4500, "idle_seconds": 300
    },
    ...
  ]
}
"""

import time
import logging
from datetime import datetime, timezone
from utils.database import get_connection

logger = logging.getLogger(__name__)

SPEED_THRESHOLD_MPH = 1.0

def _unix_to_iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

def _period_bounds(period_type: str) -> tuple[float, float]:
    now = time.time()
    from datetime import date, timedelta

    today = date.today()

    if period_type == "daily":
        start_date = today
        end_date   = today

    elif period_type == "weekly":
        start_date = today - timedelta(days=today.weekday())
        end_date   = today

    elif period_type == "monthly":
        start_date = today.replace(day=1)
        end_date   = today

    else:
        raise ValueError(f"Unknown period_type: {period_type}")

    def to_unix(d):
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()

    end_unix = to_unix(end_date) + 86400 - 0.001

    return to_unix(start_date), min(end_unix, now)

def _fetch_rows(start_ts: float, end_ts: float) -> list[dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT ts, latitude, longitude, gps_speed_mph,
                   state, state_code,
                   vehicle_speed, fuel_level, total_distance,
                   engine_hours, engine_status, vin, def_level
            FROM telemetry
            WHERE ts >= ? AND ts <= ?
            ORDER BY ts ASC
        """, (start_ts, end_ts))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def _fetch_latest() -> dict | None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT ts, latitude, longitude, gps_speed_mph, direction,
                   state, state_code,
                   vehicle_speed, fuel_level, total_distance,
                   engine_speed, engine_hours, engine_status, vin, def_level
            FROM telemetry
            ORDER BY ts DESC LIMIT 1
        """)
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def _determine_status(row: dict) -> str:
    """Truck holati: moving | idle | stopped"""
    if not row:
        return "unknown"
    status = (row.get("engine_status") or "").upper()
    speed  = row.get("vehicle_speed") or row.get("gps_speed_mph") or 0
    if status == "OFF":
        return "stopped"
    if speed >= SPEED_THRESHOLD_MPH:
        return "moving"
    return "idle"

def _build_state_segments(rows: list[dict]) -> list[dict]:
    if not rows:
        return []

    segments   = []
    cur_state  = rows[0].get("state_code") or "UNKNOWN"
    seg_start  = rows[0]["ts"]
    seg_miles  = 0.0
    seg_drive  = 0.0
    seg_idle   = 0.0
    prev_row   = rows[0]
    prev_odo   = rows[0].get("total_distance") or 0.0

    for row in rows[1:]:
        dt       = row["ts"] - prev_row["ts"]          # soniya
        odo      = row.get("total_distance") or 0.0
        d_miles  = max(0.0, odo - prev_odo)            # delta odometer
        speed    = row.get("vehicle_speed") or row.get("gps_speed_mph") or 0

        state_code = row.get("state_code") or "UNKNOWN"

        if state_code != cur_state:
            segments.append({
                "state":        prev_row.get("state") or cur_state,
                "state_code":   cur_state,
                "entry_time":   _unix_to_iso(seg_start),
                "exit_time":    _unix_to_iso(prev_row["ts"]),
                "miles":        round(seg_miles, 2),
                "drive_seconds": round(seg_drive),
                "idle_seconds":  round(seg_idle),
            })
            cur_state = state_code
            seg_start = row["ts"]
            seg_miles = 0.0
            seg_drive = 0.0
            seg_idle  = 0.0

        seg_miles += d_miles
        status = (row.get("engine_status") or "").upper()
        if status == "OFF":
            pass
        elif speed >= SPEED_THRESHOLD_MPH:
            seg_drive += dt
        else:
            seg_idle += dt

        prev_row = row
        prev_odo = odo

    segments.append({
        "state":         prev_row.get("state") or cur_state,
        "state_code":    cur_state,
        "entry_time":    _unix_to_iso(seg_start),
        "exit_time":     _unix_to_iso(prev_row["ts"]),
        "miles":         round(seg_miles, 2),
        "drive_seconds": round(seg_drive),
        "idle_seconds":  round(seg_idle),
    })

    return segments

def build_report(period_type: str,
                 custom_start: float | None = None,
                 custom_end:   float | None = None) -> dict:
    
    if custom_start is not None and custom_end is not None:
        start_ts, end_ts = custom_start, custom_end
    else:
        start_ts, end_ts = _period_bounds(period_type)

    rows    = _fetch_rows(start_ts, end_ts)
    latest  = _fetch_latest()
    segs    = _build_state_segments(rows)

    total_miles  = round(sum(s["miles"]         for s in segs), 2)
    total_drive  = round(sum(s["drive_seconds"]  for s in segs))
    total_idle   = round(sum(s["idle_seconds"]   for s in segs))

    current = {}
    if latest:
        current = {
            "status":          _determine_status(latest),
            "state":           latest.get("state"),
            "state_code":      latest.get("state_code"),
            "latitude":        latest.get("latitude"),
            "longitude":       latest.get("longitude"),
            "speed_mph":       latest.get("vehicle_speed") or latest.get("gps_speed_mph"),
            "fuel_level_pct":  latest.get("fuel_level"),
            "odometer_miles":  latest.get("total_distance"),
            "engine_hours":    latest.get("engine_hours"),
            "vin":             latest.get("vin"),
            "as_of":           _unix_to_iso(latest.get("ts")),
        }

    report = {
        "meta": {
            "period_type":   period_type,
            "period_start":  _unix_to_iso(start_ts),
            "period_end":    _unix_to_iso(end_ts),
            "generated_at":  _unix_to_iso(time.time()),
            "data_points":   len(rows),
        },
        "current_status": current,
        "summary": {
            "total_miles":        total_miles,
            "total_drive_seconds": total_drive,
            "total_idle_seconds":  total_idle,
        },
        "states": segs,
    }

    logger.info("Report built: %s  rows=%d  states=%d  miles=%.1f",
                period_type, len(rows), len(segs), total_miles)
    return report
