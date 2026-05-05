import json
import os
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

load_dotenv()

app = Flask(__name__)
CORS(app)

DB = dict(
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", "5433")),
    dbname=os.getenv("DB_NAME", "asset_tracking"),
    user=os.getenv("DB_USER", "postgres"),
    password=os.getenv("DB_PASS", ""),
)

VALID_TYPES = {"vehicle", "person", "equipment"}

# Sri Lanka Kandawala / Sri Lanka Grid (Transverse Mercator). Locally
# conformal — preserves angles and shapes for surveying/engineering use,
# unlike Web Mercator which is conformal globally but heavily area-distorted
# at high latitudes (Lec 2: Map Projections — Properties).
SRI_LANKA_GRID_SRID = 5234

GEOM_SELECT = (
    "ST_AsGeoJSON(geom) AS geojson_geom, "
    f"ST_X(ST_Transform(geom, {SRI_LANKA_GRID_SRID})) AS easting, "
    f"ST_Y(ST_Transform(geom, {SRI_LANKA_GRID_SRID})) AS northing"
)


def get_conn():
    return psycopg2.connect(**DB)


def row_to_feature(row):
    raw = row["geojson_geom"]
    geom = json.loads(raw) if raw is not None else None
    keys = row.keys() if hasattr(row, "keys") else []
    properties = {
        "id": row["id"],
        "name": row["name"],
        "asset_type": row["asset_type"],
        "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
    }
    if "easting" in keys and row["easting"] is not None:
        properties["easting"] = round(row["easting"], 2)
    if "northing" in keys and row["northing"] is not None:
        properties["northing"] = round(row["northing"], 2)
    if geom and geom.get("type") == "Point":
        lon, lat = geom["coordinates"]
        properties["lon"] = round(lon, 6)
        properties["lat"] = round(lat, 6)
    return {
        "type": "Feature",
        "geometry": geom,
        "properties": properties,
    }


@app.route("/api/assets", methods=["GET"])
def list_assets():
    type_filter = request.args.get("type")
    if type_filter is not None and type_filter not in VALID_TYPES:
        return jsonify({"error": f"type must be one of {sorted(VALID_TYPES)}"}), 400

    sql = f"SELECT id, name, asset_type, last_seen, {GEOM_SELECT} FROM assets"
    params = ()
    if type_filter:
        sql += " WHERE asset_type = %s"
        params = (type_filter,)
    sql += " ORDER BY id"

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    return jsonify(
        {"type": "FeatureCollection", "features": [row_to_feature(r) for r in rows]}
    )


@app.route("/api/assets/<int:asset_id>", methods=["GET"])
def get_asset(asset_id):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                f"SELECT id, name, asset_type, last_seen, {GEOM_SELECT} "
                "FROM assets WHERE id = %s",
                (asset_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row_to_feature(row))


@app.route("/api/history/range", methods=["GET"])
def history_range():
    """Earliest and latest recorded_at across the whole history table."""
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT MIN(recorded_at) AS earliest, "
                "MAX(recorded_at) AS latest FROM asset_history"
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return jsonify(
        {
            "earliest": row["earliest"].isoformat() if row["earliest"] else None,
            "latest": row["latest"].isoformat() if row["latest"] else None,
        }
    )


@app.route("/api/snapshot", methods=["GET"])
def snapshot():
    """Each asset's last known position at or before the given timestamp."""
    at = request.args.get("at")
    if not at:
        return jsonify({"error": "Missing 'at' query parameter (ISO timestamp)"}), 400
    try:
        # Frontend (Date.toISOString) sends UTC ending in 'Z'. Treat
        # naive strings as UTC too. The DB stores TIMESTAMP without tz
        # in server-local time, so convert to local naive for comparison.
        if at.endswith("Z"):
            aware = datetime.fromisoformat(at[:-1]).replace(tzinfo=timezone.utc)
        else:
            aware = datetime.fromisoformat(at)
            if aware.tzinfo is None:
                aware = aware.replace(tzinfo=timezone.utc)
        parsed = aware.astimezone().replace(tzinfo=None)
    except ValueError:
        return jsonify({"error": "'at' must be a valid ISO timestamp"}), 400

    type_filter = request.args.get("type")
    if type_filter is not None and type_filter not in VALID_TYPES:
        return jsonify({"error": f"type must be one of {sorted(VALID_TYPES)}"}), 400

    sql = (
        "SELECT DISTINCT ON (a.id) "
        "  a.id, a.name, a.asset_type, "
        "  h.recorded_at AS last_seen, "
        "  ST_AsGeoJSON(h.geom) AS geojson_geom, "
        f"  ST_X(ST_Transform(h.geom, {SRI_LANKA_GRID_SRID})) AS easting, "
        f"  ST_Y(ST_Transform(h.geom, {SRI_LANKA_GRID_SRID})) AS northing "
        "FROM assets a "
        "JOIN asset_history h ON h.asset_id = a.id "
        "WHERE h.recorded_at <= %s"
    )
    params = [parsed]
    if type_filter:
        sql += " AND a.asset_type = %s"
        params.append(type_filter)
    sql += " ORDER BY a.id, h.recorded_at DESC"

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    return jsonify(
        {
            "type": "FeatureCollection",
            "features": [row_to_feature(r) for r in rows],
            "metadata": {"snapshot_at": parsed.isoformat(), "count": len(rows)},
        }
    )


@app.route("/api/assets/<int:asset_id>/history", methods=["GET"])
def get_asset_history(asset_id):
    """Return recent positions for one asset as a GeoJSON LineString trail."""
    try:
        hours = max(1, min(int(request.args.get("hours", 1)), 24 * 7))
        limit = max(1, min(int(request.args.get("limit", 500)), 5000))
    except (TypeError, ValueError):
        return jsonify({"error": "hours and limit must be integers"}), 400

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT id, name, asset_type FROM assets WHERE id = %s", (asset_id,)
            )
            asset = cur.fetchone()
            if asset is None:
                return jsonify({"error": "Not found"}), 404

            cur.execute(
                """
                SELECT recorded_at, ST_X(geom) AS lon, ST_Y(geom) AS lat
                FROM asset_history
                WHERE asset_id = %s
                  AND recorded_at >= NOW() - make_interval(hours => %s)
                ORDER BY recorded_at ASC
                LIMIT %s
                """,
                (asset_id, hours, limit),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    coords = [[r["lon"], r["lat"]] for r in rows]
    timestamps = [r["recorded_at"].isoformat() for r in rows]

    features = []
    if len(coords) >= 2:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "asset_id": asset_id,
                    "name": asset["name"],
                    "asset_type": asset["asset_type"],
                    "kind": "trail",
                    "point_count": len(coords),
                    "first_seen": timestamps[0],
                    "last_seen": timestamps[-1],
                },
            }
        )
    elif len(coords) == 1:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coords[0]},
                "properties": {
                    "asset_id": asset_id,
                    "name": asset["name"],
                    "asset_type": asset["asset_type"],
                    "kind": "trail-origin",
                    "point_count": 1,
                    "first_seen": timestamps[0],
                    "last_seen": timestamps[0],
                },
            }
        )

    response = {"type": "FeatureCollection", "features": features}
    response["metadata"] = {
        "asset_id": asset_id,
        "name": asset["name"],
        "asset_type": asset["asset_type"],
        "point_count": len(coords),
        "hours": hours,
    }
    return jsonify(response)


@app.route("/api/assets", methods=["POST"])
def create_asset():
    """Create a new asset. Body: {"name": str, "asset_type": str, "latitude": float, "longitude": float}"""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    asset_type = (data.get("asset_type") or "").strip()
    lon, lat = data.get("longitude"), data.get("latitude")

    if not name:
        return jsonify({"error": "name is required"}), 400
    if asset_type not in VALID_TYPES:
        return jsonify({"error": f"asset_type must be one of {sorted(VALID_TYPES)}"}), 400
    if lon is None or lat is None:
        return jsonify({"error": "latitude and longitude are required"}), 400
    try:
        lon = float(lon)
        lat = float(lat)
    except (TypeError, ValueError):
        return jsonify({"error": "Coordinates must be numeric"}), 400
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return jsonify({"error": "Coordinates out of range"}), 400

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO assets (name, asset_type, geom) "
                "VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)) "
                "RETURNING id",
                (name, asset_type, lon, lat),
            )
            new_id = cur.fetchone()[0]
            conn.commit()
    finally:
        conn.close()
    return jsonify({"status": "success", "id": new_id}), 201


@app.route("/api/assets/<int:asset_id>", methods=["PUT"])
def update_asset(asset_id):
    data = request.get_json(silent=True) or {}
    lon, lat = data.get("longitude"), data.get("latitude")
    if lon is None or lat is None:
        return jsonify({"error": "Missing coordinates"}), 400
    try:
        lon = float(lon)
        lat = float(lat)
    except (TypeError, ValueError):
        return jsonify({"error": "Coordinates must be numeric"}), 400
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return jsonify({"error": "Coordinates out of range"}), 400

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE assets "
                "SET geom = ST_SetSRID(ST_MakePoint(%s, %s), 4326), last_seen = NOW() "
                "WHERE id = %s",
                (lon, lat, asset_id),
            )
            if cur.rowcount == 0:
                return jsonify({"error": "Not found"}), 404
            conn.commit()
    finally:
        conn.close()
    return jsonify({"status": "success"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
