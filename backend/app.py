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

# Asset-interaction rules. Each pair of types means a different real-world
# phenomenon, so the proximity threshold and the minimum dwell time differ.
# Distances are metres on the WGS84 spheroid (geography type), durations are
# seconds. Types are unordered — the SQL handles (a,b) and (b,a) equivalently.
#
# DEMO VALUES vs REAL-WORLD VALUES: the original/spec thresholds (5–20 m,
# 10–60 s) are realistic for actual GPS pings but never fire in this random-
# walk simulation, where assets jitter ~200 m per tick and rarely linger in
# the same spot. The values below are deliberately loosened so encounter
# events are visible during a 1–2 minute demo. For a real deployment with
# real GPS, swap them back to the column on the right.
#                                              demo  /  real-world
INTERACTION_RULES = [
    # (type_a,    type_b,      distance_m, min_duration_s, kind)
    ("vehicle",   "person",    150.0,  4, "PICKUP"),     # 10 m, 30 s
    ("vehicle",   "equipment", 150.0,  4, "LOADING"),    # 10 m, 30 s
    ("person",    "equipment",  80.0,  6, "OPERATING"),  #  5 m, 60 s
    ("person",    "person",     80.0,  6, "MEETING"),    #  5 m, 60 s
    ("vehicle",   "vehicle",   300.0,  4, "CONVOY"),     # 20 m, 10 s
]
VALID_KINDS = {r[4] for r in INTERACTION_RULES}

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


def utc_iso(dt):
    """Render a datetime as an ISO 8601 string with explicit UTC `Z`.

    DB columns are TIMESTAMP without time zone, but on Render the server
    runs in UTC and `NOW()` returns UTC, so naive values here are
    effectively UTC. Without the `Z` suffix, browsers interpret the ISO
    string as local time and the slider/snapshot epoch math drifts by
    the client's offset.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def row_to_feature(row):
    raw = row["geojson_geom"]
    geom = json.loads(raw) if raw is not None else None
    keys = row.keys() if hasattr(row, "keys") else []
    properties = {
        "id": row["id"],
        "name": row["name"],
        "asset_type": row["asset_type"],
        "last_seen": utc_iso(row["last_seen"]),
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


@app.route("/api/health", methods=["GET"])
def health():
    """Liveness probe — DB-independent so it passes during a fresh deploy
    before the schema has been loaded. Render points its health check here."""
    return jsonify({"ok": True})


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
            "earliest": utc_iso(row["earliest"]),
            "latest": utc_iso(row["latest"]),
        }
    )


@app.route("/api/snapshot", methods=["GET"])
def snapshot():
    """Each asset's last known position at or before the given timestamp."""
    at = request.args.get("at")
    if not at:
        return jsonify({"error": "Missing 'at' query parameter (ISO timestamp)"}), 400
    try:
        # Frontend (Date.toISOString) sends UTC ending in 'Z'. Treat naive
        # strings as UTC too. DB column is TIMESTAMP-without-tz holding
        # UTC, so we compare against a naive UTC datetime regardless of
        # what timezone the Flask process happens to be running in.
        if at.endswith("Z"):
            aware = datetime.fromisoformat(at[:-1]).replace(tzinfo=timezone.utc)
        else:
            aware = datetime.fromisoformat(at)
            if aware.tzinfo is None:
                aware = aware.replace(tzinfo=timezone.utc)
        parsed = aware.astimezone(timezone.utc).replace(tzinfo=None)
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
            "metadata": {"snapshot_at": utc_iso(parsed), "count": len(rows)},
        }
    )


@app.route("/api/heatmap", methods=["GET"])
def heatmap():
    """Density of historical positions over a time window.

    Returns one Point feature per history row, with a recency-decay weight
    in [0,1] so the heatmap emphasises recent dwell. Useful for answering
    'where do people spend the most time?' (Lec 1a: continuous-field view
    of discrete observations; Lec 1b: dynamic visualization of geo data).
    """
    try:
        hours = max(1, min(int(request.args.get("hours", 24)), 24 * 7))
        limit = max(1, min(int(request.args.get("limit", 5000)), 20000))
    except (TypeError, ValueError):
        return jsonify({"error": "hours and limit must be integers"}), 400

    type_filter = request.args.get("type")
    if type_filter is not None and type_filter not in VALID_TYPES:
        return jsonify({"error": f"type must be one of {sorted(VALID_TYPES)}"}), 400

    sql = (
        "SELECT ST_X(h.geom) AS lon, ST_Y(h.geom) AS lat, "
        "       EXTRACT(EPOCH FROM (NOW() - h.recorded_at)) AS age_s "
        "FROM asset_history h "
        "JOIN assets a ON a.id = h.asset_id "
        "WHERE h.recorded_at >= NOW() - make_interval(hours => %s)"
    )
    params = [hours]
    if type_filter:
        sql += " AND a.asset_type = %s"
        params.append(type_filter)
    sql += " ORDER BY h.recorded_at DESC LIMIT %s"
    params.append(limit)

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    window_seconds = hours * 3600
    features = []
    for r in rows:
        # Linear decay: a point recorded `window_seconds` ago has weight 0,
        # a point recorded just now has weight 1. EXTRACT(EPOCH ...) comes
        # back as Decimal; cast so the float subtraction doesn't TypeError.
        age_s = float(r["age_s"])
        weight = max(0.0, 1.0 - (age_s / window_seconds))
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                "properties": {"weight": round(weight, 4)},
            }
        )

    return jsonify(
        {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "hours": hours,
                "count": len(features),
                "type": type_filter,
            },
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

            # Take the MOST RECENT `limit` rows within the time window
            # (subquery sorts DESC + LIMIT), then re-order ASC so the
            # LineString draws oldest → newest.
            cur.execute(
                """
                SELECT recorded_at, lon, lat
                FROM (
                    SELECT recorded_at, ST_X(geom) AS lon, ST_Y(geom) AS lat
                    FROM asset_history
                    WHERE asset_id = %s
                      AND recorded_at >= NOW() - make_interval(hours => %s)
                    ORDER BY recorded_at DESC
                    LIMIT %s
                ) t
                ORDER BY recorded_at ASC
                """,
                (asset_id, hours, limit),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    coords = [[r["lon"], r["lat"]] for r in rows]
    timestamps = [utc_iso(r["recorded_at"]) for r in rows]

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


@app.route("/api/assets/<int:asset_id>/motion", methods=["GET"])
def get_motion(asset_id):
    """Latest speed and heading derived from the two most recent history rows.

    - Speed is a *ratio-scale* attribute: distance over time, in metres/second
      and km/h. Zero means truly motionless.
    - Heading is a *cyclic-scale* attribute on [0, 360): degrees clockwise
      from true north (ST_Azimuth convention). 359° is adjacent to 0°.
    Both classifications come from Lec 1a "attribute scales of measurement".
    """
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                WITH last2 AS (
                    SELECT recorded_at, geom,
                           ROW_NUMBER() OVER (ORDER BY recorded_at DESC) AS rn
                    FROM asset_history
                    WHERE asset_id = %s
                    ORDER BY recorded_at DESC
                    LIMIT 2
                )
                SELECT
                    EXTRACT(EPOCH FROM (p1.recorded_at - p2.recorded_at)) AS dt_s,
                    ST_Distance(geography(p1.geom), geography(p2.geom)) AS distance_m,
                    DEGREES(ST_Azimuth(p2.geom, p1.geom)) AS heading_deg,
                    p1.recorded_at AS at_time
                FROM last2 p1, last2 p2
                WHERE p1.rn = 1 AND p2.rn = 2
                """,
                (asset_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None or row["dt_s"] is None or float(row["dt_s"]) <= 0:
        return jsonify(
            {"asset_id": asset_id, "speed_mps": None, "speed_kmh": None,
             "heading_deg": None, "sample_seconds": None, "distance_m": None}
        )

    # EXTRACT(EPOCH ...) returns Decimal; ST_Distance returns float. Coerce both.
    distance_m = float(row["distance_m"])
    dt_s = float(row["dt_s"])
    speed_mps = distance_m / dt_s

    heading = row["heading_deg"]
    if heading is not None:
        heading = float(heading) % 360.0

    return jsonify(
        {
            "asset_id": asset_id,
            "speed_mps": round(speed_mps, 2),
            "speed_kmh": round(speed_mps * 3.6, 2),
            "heading_deg": round(heading, 1) if heading is not None else None,
            "sample_seconds": round(dt_s, 1),
            "distance_m": round(distance_m, 1),
            "at_time": utc_iso(row["at_time"]),
        }
    )


@app.route("/api/proximity", methods=["GET"])
def proximity():
    """Find every asset within radius_m metres of (lon, lat).

    Uses ST_DWithin on the geography type so the radius is interpreted
    in real metres on the WGS84 spheroid (independent of latitude
    distortion). The GIST index on `assets.geom` makes this O(log n)
    bounding-box pruning before the precise distance check — the
    canonical 'proximity' relationship from Lec 1.
    """
    try:
        lon = float(request.args["lon"])
        lat = float(request.args["lat"])
        radius_m = float(request.args.get("radius_m", 5000))
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "lon, lat (required) and radius_m must be numeric"}), 400
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return jsonify({"error": "Coordinates out of range"}), 400
    if not (1 <= radius_m <= 1_000_000):
        return jsonify({"error": "radius_m must be between 1 and 1,000,000"}), 400

    type_filter = request.args.get("type")
    if type_filter is not None and type_filter not in VALID_TYPES:
        return jsonify({"error": f"type must be one of {sorted(VALID_TYPES)}"}), 400

    sql = (
        f"SELECT id, name, asset_type, last_seen, {GEOM_SELECT}, "
        "       ST_Distance(geom::geography, "
        "                   ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) AS distance_m "
        "FROM assets "
        "WHERE ST_DWithin(geom::geography, "
        "                 ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)"
    )
    params = [lon, lat, lon, lat, radius_m]
    if type_filter:
        sql += " AND asset_type = %s"
        params.append(type_filter)
    sql += " ORDER BY distance_m ASC"

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    features = []
    for r in rows:
        f = row_to_feature(r)
        f["properties"]["distance_m"] = round(r["distance_m"], 1)
        features.append(f)

    return jsonify(
        {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "lon": lon,
                "lat": lat,
                "radius_m": radius_m,
                "count": len(features),
            },
        }
    )


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


@app.route("/api/assets/<int:asset_id>", methods=["DELETE"])
def delete_asset(asset_id):
    """Delete an asset. ON DELETE CASCADE removes its history and interactions."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM assets WHERE id = %s", (asset_id,))
            if cur.rowcount == 0:
                return jsonify({"error": "Not found"}), 404
            conn.commit()
    finally:
        conn.close()
    return jsonify({"status": "deleted", "id": asset_id})


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


# ----------------------------- Interactions ---------------------------------

# Reusable VALUES list: ('vehicle','person',10.0,'PICKUP'),...
_RULE_VALUES_SQL = ",".join(
    f"('{r[0]}','{r[1]}',{r[2]},'{r[4]}')" for r in INTERACTION_RULES
)
_DURATION_VALUES_SQL = ",".join(
    f"('{r[4]}',{r[3]})" for r in INTERACTION_RULES
)


@app.route("/api/interactions/detect", methods=["POST"])
def detect_interactions():
    """Run one detection sweep across the current `assets` table.

    Idempotent: opens new interactions for type-pairs that satisfy a rule's
    distance threshold and aren't already active; closes (sets `ended_at`)
    interactions whose pair has now drifted out of range. Intended to be
    called periodically by the simulator after every tick.
    """
    open_sql = f"""
        WITH rules(a_t, b_t, dist_m, kind) AS (VALUES {_RULE_VALUES_SQL}),
        candidate_pairs AS (
            SELECT
                LEAST(a.id, b.id)    AS asset_a_id,
                GREATEST(a.id, b.id) AS asset_b_id,
                r.kind,
                ST_Centroid(ST_Collect(a.geom, b.geom)) AS midpoint
            FROM assets a
            JOIN assets b ON a.id < b.id
            JOIN rules r ON
                ((a.asset_type = r.a_t AND b.asset_type = r.b_t)
              OR (a.asset_type = r.b_t AND b.asset_type = r.a_t))
            WHERE ST_DWithin(a.geom::geography, b.geom::geography, r.dist_m)
        )
        INSERT INTO interactions (asset_a_id, asset_b_id, kind, started_at, location)
        SELECT cp.asset_a_id, cp.asset_b_id, cp.kind, NOW(), cp.midpoint
        FROM candidate_pairs cp
        WHERE NOT EXISTS (
            SELECT 1 FROM interactions i
            WHERE i.asset_a_id = cp.asset_a_id
              AND i.asset_b_id = cp.asset_b_id
              AND i.kind = cp.kind
              AND i.ended_at IS NULL
        )
    """

    close_sql = f"""
        WITH rules(a_t, b_t, dist_m, kind) AS (VALUES {_RULE_VALUES_SQL}),
        current_pairs AS (
            SELECT
                LEAST(a.id, b.id)    AS asset_a_id,
                GREATEST(a.id, b.id) AS asset_b_id,
                r.kind
            FROM assets a
            JOIN assets b ON a.id < b.id
            JOIN rules r ON
                ((a.asset_type = r.a_t AND b.asset_type = r.b_t)
              OR (a.asset_type = r.b_t AND b.asset_type = r.a_t))
            WHERE ST_DWithin(a.geom::geography, b.geom::geography, r.dist_m)
        )
        UPDATE interactions i
        SET ended_at = NOW()
        WHERE i.ended_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM current_pairs cp
              WHERE cp.asset_a_id = i.asset_a_id
                AND cp.asset_b_id = i.asset_b_id
                AND cp.kind = i.kind
          )
    """

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(open_sql)
            opened = cur.rowcount
            cur.execute(close_sql)
            closed = cur.rowcount
            conn.commit()
    finally:
        conn.close()

    return jsonify({"opened": opened, "closed": closed, "rules": len(INTERACTION_RULES)})


@app.route("/api/interactions", methods=["GET"])
def list_interactions():
    """Recent interactions, filtered by min-duration per kind, plus optional
    `kind`, `since` (ISO ts), `limit`, and `active_only` query params."""
    kind = request.args.get("kind")
    if kind is not None and kind not in VALID_KINDS:
        return jsonify({"error": f"kind must be one of {sorted(VALID_KINDS)}"}), 400

    since = request.args.get("since")
    parsed_since = None
    if since:
        try:
            if since.endswith("Z"):
                aware = datetime.fromisoformat(since[:-1]).replace(tzinfo=timezone.utc)
            else:
                aware = datetime.fromisoformat(since)
                if aware.tzinfo is None:
                    aware = aware.replace(tzinfo=timezone.utc)
            # Compare naive-UTC against the TIMESTAMP-without-tz column —
            # see snapshot() above for the reasoning.
            parsed_since = aware.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            return jsonify({"error": "'since' must be a valid ISO timestamp"}), 400

    try:
        limit = max(1, min(int(request.args.get("limit", 200)), 2000))
    except (TypeError, ValueError):
        return jsonify({"error": "limit must be an integer"}), 400

    active_only = request.args.get("active_only", "false").lower() in ("1", "true", "yes")

    sql = f"""
        WITH rules(kind, min_duration_s) AS (VALUES {_DURATION_VALUES_SQL})
        SELECT v.*
        FROM interactions_view v
        JOIN rules r ON r.kind = v.kind
        WHERE v.duration_s >= r.min_duration_s
    """
    params = []
    if kind:
        sql += " AND v.kind = %s"
        params.append(kind)
    if parsed_since:
        sql += " AND v.started_at >= %s"
        params.append(parsed_since)
    if active_only:
        sql += " AND v.ended_at IS NULL"
    sql += " ORDER BY v.started_at DESC LIMIT %s"
    params.append(limit)

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": {
                "id": r["id"],
                "kind": r["kind"],
                "asset_a_id": r["asset_a_id"],
                "asset_a_name": r["asset_a_name"],
                "asset_a_type": r["asset_a_type"],
                "asset_b_id": r["asset_b_id"],
                "asset_b_name": r["asset_b_name"],
                "asset_b_type": r["asset_b_type"],
                "started_at": utc_iso(r["started_at"]),
                "ended_at": utc_iso(r["ended_at"]),
                "duration_s": r["duration_s"],
                "active": r["ended_at"] is None,
            },
        }
        for r in rows
    ]
    return jsonify(
        {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "count": len(features),
                "kind": kind,
                "since": utc_iso(parsed_since),
                "active_only": active_only,
            },
        }
    )


@app.route("/api/interactions/rules", methods=["GET"])
def interaction_rules():
    """Expose the rule table so the frontend can render filter chips/icons
    without hard-coding it."""
    return jsonify(
        [
            {"type_a": a, "type_b": b, "distance_m": d, "min_duration_s": t, "kind": k}
            for (a, b, d, t, k) in INTERACTION_RULES
        ]
    )


if __name__ == "__main__":
    # Local dev only. In production, gunicorn imports `app` directly
    # (see Procfile) and this block doesn't run.
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
