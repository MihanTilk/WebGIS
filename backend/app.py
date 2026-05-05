import json
import os
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


def get_conn():
    return psycopg2.connect(**DB)


def row_to_feature(row):
    return {
        "type": "Feature",
        "geometry": json.loads(row["geojson_geom"]),
        "properties": {
            "id": row["id"],
            "name": row["name"],
            "asset_type": row["asset_type"],
            "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
        },
    }


@app.route("/api/assets", methods=["GET"])
def list_assets():
    type_filter = request.args.get("type")
    sql = (
        "SELECT id, name, asset_type, last_seen, "
        "ST_AsGeoJSON(geom) AS geojson_geom FROM assets"
    )
    params = ()
    if type_filter:
        sql += " WHERE asset_type = %s"
        params = (type_filter,)
    sql += " ORDER BY id"

    with get_conn() as conn, conn.cursor(
        cursor_factory=psycopg2.extras.DictCursor
    ) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return jsonify(
        {"type": "FeatureCollection", "features": [row_to_feature(r) for r in rows]}
    )


@app.route("/api/assets/<int:asset_id>", methods=["GET"])
def get_asset(asset_id):
    with get_conn() as conn, conn.cursor(
        cursor_factory=psycopg2.extras.DictCursor
    ) as cur:
        cur.execute(
            "SELECT id, name, asset_type, last_seen, "
            "ST_AsGeoJSON(geom) AS geojson_geom FROM assets WHERE id = %s",
            (asset_id,),
        )
        row = cur.fetchone()
    if row is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row_to_feature(row))


@app.route("/api/assets/<int:asset_id>", methods=["PUT"])
def update_asset(asset_id):
    data = request.get_json(silent=True) or {}
    lon, lat = data.get("longitude"), data.get("latitude")
    if lon is None or lat is None:
        return jsonify({"error": "Missing coordinates"}), 400

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE assets "
            "SET geom = ST_SetSRID(ST_MakePoint(%s, %s), 4326), last_seen = NOW() "
            "WHERE id = %s",
            (lon, lat, asset_id),
        )
        if cur.rowcount == 0:
            return jsonify({"error": "Not found"}), 404
        conn.commit()
    return jsonify({"status": "success"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
