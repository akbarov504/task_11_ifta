import json
import logging
from datetime import timezone, datetime
from flask import Flask, jsonify, request

from reports.builder import build_report
from utils.database  import get_connection
from settings        import APP_HOST, APP_PORT, DEBUG

logger = logging.getLogger(__name__)
app    = Flask(__name__)

@app.get("/api/status")
def get_status():
    """
    Eng so'nggi telemetriya qatoridan joriy truck holati.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT ts, latitude, longitude, gps_speed_mph, direction,
                   state, state_code,
                   vehicle_speed, fuel_level, total_distance,
                   engine_speed, engine_hours, engine_status, vin, def_level
            FROM telemetry ORDER BY ts DESC LIMIT 1
        """)
        row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        return jsonify({"error": "No telemetry data yet"}), 404

    d = dict(row)
    speed = d.get("vehicle_speed") or d.get("gps_speed_mph") or 0
    status_str = d.get("engine_status", "OFF")

    if (status_str or "").upper() == "OFF":
        motion = "stopped"
    elif speed >= 1.0:
        motion = "moving"
    else:
        motion = "idle"

    return jsonify({
        "status":          motion,
        "engine_status":   status_str,
        "state":           d.get("state"),
        "state_code":      d.get("state_code"),
        "latitude":        d.get("latitude"),
        "longitude":       d.get("longitude"),
        "speed_mph":       speed,
        "fuel_level_pct":  d.get("fuel_level"),
        "odometer_miles":  d.get("total_distance"),
        "engine_hours":    d.get("engine_hours"),
        "def_level_pct":   d.get("def_level"),
        "vin":             d.get("vin"),
        "as_of":           _unix_to_iso(d.get("ts")),
    })

@app.get("/api/report")
def get_report():
    """
    Yangi report yaratib qaytaradi.

    Query params:
        period = daily | weekly | monthly   (default: daily)
    """
    period = request.args.get("period", "daily").lower()
    if period not in ("daily", "weekly", "monthly"):
        return jsonify({
            "error": "period must be 'daily', 'weekly', or 'monthly'"
        }), 400

    try:
        report = build_report(period)
        return jsonify(report)
    except Exception as exc:
        logger.exception("Error building report")
        return jsonify({"error": str(exc)}), 500

@app.get("/api/report/history")
def get_report_history():
    """
    Avval yaratilgan va saqlangan reportlar ro'yxati.

    Query params:
        period = daily | weekly | monthly   (ixtiyoriy)
        limit  = 1..100                     (default: 10)
    """
    period = request.args.get("period")
    limit  = min(int(request.args.get("limit", 10)), 100)

    conn = get_connection()
    try:
        cur = conn.cursor()
        if period:
            cur.execute("""
                SELECT id, created_at, period_type, period_start, period_end,
                       sent, sent_at, payload
                FROM reports
                WHERE period_type = ?
                ORDER BY created_at DESC LIMIT ?
            """, (period, limit))
        else:
            cur.execute("""
                SELECT id, created_at, period_type, period_start, period_end,
                       sent, sent_at, payload
                FROM reports
                ORDER BY created_at DESC LIMIT ?
            """, (limit,))
        rows = cur.fetchall()
    finally:
        conn.close()

    result = []
    for r in rows:
        d = dict(r)
        d["payload"]    = json.loads(d["payload"])
        d["created_at"] = _unix_to_iso(d["created_at"])
        d["sent_at"]    = _unix_to_iso(d["sent_at"]) if d["sent_at"] else None
        d["period_start"] = _unix_to_iso(d["period_start"])
        d["period_end"]   = _unix_to_iso(d["period_end"])
        result.append(d)

    return jsonify({"count": len(result), "reports": result})

def _unix_to_iso(ts) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def run_api():
    """Flask serverni ishga tushiradi (blocking)."""
    app.run(host=APP_HOST, port=APP_PORT, debug=DEBUG, use_reloader=False)
