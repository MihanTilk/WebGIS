# WebGIS Asset Tracking

A WebGIS application that tracks moving assets (vehicles, people, equipment) on an interactive map of Sri Lanka. Locations are stored in PostGIS, served as GeoJSON by a Flask REST API, and rendered with OpenLayers in the browser. A simulator script periodically updates each asset's position to mimic real-time movement.

Built for the *Building a WebGIS Asset Tracking Application* assignment (Index 226121P).

## Features

- **Live map** of all assets, polled every 5 seconds, colour-coded by type.
- **Asset-type filter** (vehicles / people / equipment).
- **Click popup** showing name, type, last-seen timestamp, **WGS84 lat/lon (EPSG:4326)**, and **Sri Lanka Kandawala Grid easting/northing (EPSG:5234)** — the locally conformal projection used for surveying in Sri Lanka.
- **Movement trails** — when you click an asset, a coloured dashed line shows where it has been in the last hour. Auto-populated for fresh assets via a database trigger plus a synthetic past-walk on the seed.
- **Direction arrow & speed** — clicking an asset draws an arrow at its current position oriented to its heading (computed from the last two history rows via `ST_Azimuth`); the popup shows speed in km/h. Yellow arrow = moving fast (≥ 5 km/h), white = slow.
- **Density heatmap** — toggle a kernel-density heatmap of historical positions over a configurable window (1h / 6h / 24h / 3d), with recency-weighted intensity.
- **Time-travel playback** — switch from Live to Playback mode and scrub a slider, or hit Play to watch the whole fleet move through history at 1×/5×/30× speed.
- **Proximity search** — toggle proximity mode, click anywhere on the map to draw a search circle, all assets inside are highlighted (uses PostGIS `ST_DWithin` on the geography type for true-metre radius).
- **Asset interaction events** — pairs of assets are joined spatially-and-by-type to detect typed encounters. Five rules: `PICKUP` (vehicle ↔ person), `LOADING` (vehicle ↔ equipment), `OPERATING` (person ↔ equipment), `MEETING` (person ↔ person), `CONVOY` (vehicle ↔ vehicle). The realistic real-world thresholds are 5–20 m and 10–60 s, but the demo loosens these to 80–300 m and 4–6 s so events are visible during a short random-walk demo (the real values are documented in the source). Detection runs in PostGIS each simulator tick; a side panel feeds the events with click-to-zoom-and-highlight, an "ⓘ" rule popover on each chip, an info-toggle on each event, and a circular border at the meeting location showing the rule's proximity threshold. Stars on the map mark each event midpoint, color-coded by kind.
- **Fit-to-all** button — auto-zoom the view to all visible assets.

## Architecture

```
OpenLayers (browser)  --HTTP/GeoJSON-->  Flask API  --SQL-->  PostgreSQL + PostGIS
```

- **Database** — PostgreSQL 18 with PostGIS 3.x. Two tables: `assets` (current positions) and `asset_history` (every position change, populated by a trigger). GIST indexes on geometry columns for fast spatial queries.
- **Backend** — Flask with `flask-cors` and `psycopg2`. Returns standard GeoJSON `FeatureCollection`s. All distance/proximity work happens in PostGIS via `ST_DWithin`, `ST_Distance`, `ST_Azimuth`, `ST_Transform`, `ST_AsGeoJSON`.
- **Frontend** — OpenLayers 7 over an OpenStreetMap base layer. Periodic polling with `setInterval`; an SVG-based direction arrow icon; OpenLayers Heatmap layer for density visualization.
- **Simulator** — a Python script that random-walks every asset and PUTs the new coordinates to the API on a configurable interval. Optionally auto-spawns new assets over time across all major Sri Lankan cities.

## Project layout

```
.
├── backend/
│   ├── app.py             # Flask REST API (16 route-method handlers)
│   ├── simulator.py       # Periodic location updater + auto-spawn
│   ├── seed_assets.py     # One-shot bulk loader (POSTs N assets)
│   ├── constants.py       # Shared name pool + Sri Lankan city list
│   ├── smoke_test.ps1     # PowerShell smoke test for every endpoint
│   ├── Procfile           # Gunicorn entrypoint for production
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── index.html         # OpenLayers map, single self-contained file
├── sql/
│   ├── 01_schema.sql            # CREATE TABLE assets + GIST index
│   ├── 02_sample_data.sql       # 6 seed assets around Colombo
│   ├── 03_history.sql           # asset_history + INSERT/UPDATE trigger
│   ├── 04_clustered_seed.sql    # 120 clustered assets across 20 SL cities
│   └── 05_interactions.sql      # interactions table + view for typed encounters
├── docs/
│   └── screenshots/
├── render.yaml            # Render Blueprint (DB + API + static frontend)
└── create_report.py       # Generates the assignment writeup .docx
```

## Quick start (Windows)

### 0. Prerequisites

- **PostgreSQL 18** with the **PostGIS 3.x** extension. The commands below assume it is listening on port `5433` (Postgres' default-installer second-instance port). If yours is on `5432`, swap `-p 5433` for `-p 5432` everywhere.
- **Python 3.11+** on `PATH`.
- **PowerShell** (the commands use PS syntax — `Activate.ps1`, `Copy-Item`).

If `psql` is not on `PATH`, either add `C:\Program Files\PostgreSQL\18\bin` to your `PATH` or call it by full path.

### 1. Database

Create and seed the database (run from the repo root):

```powershell
psql -U postgres -p 5433 -c "CREATE DATABASE asset_tracking;"
psql -U postgres -p 5433 -d asset_tracking -f sql\01_schema.sql
psql -U postgres -p 5433 -d asset_tracking -f sql\02_sample_data.sql
psql -U postgres -p 5433 -d asset_tracking -f sql\03_history.sql
psql -U postgres -p 5433 -d asset_tracking -f sql\05_interactions.sql
```

For an island-wide demo (120 assets across 20 cities, with synthetic past trails):

```powershell
psql -U postgres -p 5433 -d asset_tracking -c "TRUNCATE asset_history; TRUNCATE assets RESTART IDENTITY CASCADE;"
psql -U postgres -p 5433 -d asset_tracking -f sql\04_clustered_seed.sql
```

### 2. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env       # then edit DB_PASS
python app.py
```

API serves on http://localhost:5000.

### 3. Frontend

In a second terminal:

```powershell
cd frontend
python -m http.server 8000
```

The page is hard-coded to call the **deployed** API (see the `<meta name="api-root">` tag in [frontend/index.html](frontend/index.html#L7)). To point it at your local backend, append a query parameter:

```
http://localhost:8000/?api_root=http://localhost:5000/api
```

(Alternatively, edit the meta tag's `content` attribute to `http://localhost:5000/api` for the duration of local dev — but don't commit that change.)

To verify the API is reachable: <http://localhost:5000/api/health> should return `{"ok": true}`.

### 4. Simulator (shows movement)

In a third terminal:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python simulator.py --interval 2
```

Each asset's position is nudged every 2 seconds; the map reflects the change on its next poll.

Other useful invocations:

```powershell
python simulator.py --interval 1 --spawn-every 3 --spawn-max 200 --island   # busy demo
python seed_assets.py 40 --island                                            # bulk-add 40 assets
```

To point the simulator at a deployed API instead of localhost, set `API_BASE`:

```powershell
$env:API_BASE = "https://asset-tracking-api.onrender.com/api"
python simulator.py --interval 2
```

### 5. Smoke test (optional)

With the API running, exercise every endpoint at once:

```powershell
cd backend
.\smoke_test.ps1
```

## API reference

| Method | Path                                | Description                                                                  |
|--------|-------------------------------------|------------------------------------------------------------------------------|
| GET    | `/api/health`                       | Liveness probe. Returns `{"ok": true}` without touching the database.        |
| GET    | `/api/assets`                       | All assets as GeoJSON. Optional `?type=vehicle\|person\|equipment`.          |
| GET    | `/api/assets/<id>`                  | Single asset as a GeoJSON Feature.                                           |
| POST   | `/api/assets`                       | Create a new asset. Body: `{name, asset_type, latitude, longitude}`.         |
| PUT    | `/api/assets/<id>`                  | Update asset location. Body: `{latitude, longitude}`.                        |
| DELETE | `/api/assets/<id>`                  | Delete an asset. Cascades to its history rows and interactions.              |
| GET    | `/api/assets/<id>/history`          | Last `?hours=N` of positions for one asset as a GeoJSON LineString trail.    |
| GET    | `/api/assets/<id>/motion`           | Speed (km/h, m/s) and heading (deg) from the last two history rows.          |
| GET    | `/api/history/range`                | Earliest and latest `recorded_at` across the whole history table (playback). |
| GET    | `/api/snapshot?at=<iso>`            | Each asset's last known position at or before `<iso>` timestamp (playback).  |
| GET    | `/api/heatmap?hours=N`              | Density heatmap input — point features with recency-decay weights.           |
| GET    | `/api/proximity?lon&lat&radius_m`   | All assets within `radius_m` metres of (lon, lat). Spheroid-accurate.        |
| GET    | `/api/interactions?kind&since&limit` | Recent typed encounters as a GeoJSON FeatureCollection of stars at midpoints.|
| POST   | `/api/interactions/detect`          | Run one detection sweep (open new, close stale). Idempotent.                 |
| GET    | `/api/interactions/rules`           | The 5 rule definitions (type pairs, distance, min duration, kind).           |

Run `backend\smoke_test.ps1` to exercise every endpoint.

## Deployment

[render.yaml](render.yaml) is a Render Blueprint that provisions a Postgres+PostGIS database, the Flask API (gunicorn via [backend/Procfile](backend/Procfile)), and the static frontend in one click. After the first deploy, manually apply the SQL files (`01_schema.sql`, `03_history.sql`, `04_clustered_seed.sql`, `05_interactions.sql`) against the new DB and update the `api-root` meta tag in `frontend/index.html` to the deployed backend URL. The simulator stays local — point it at the deployed API by setting `API_BASE` (see step 4).

## Tech stack

- PostgreSQL 18 + PostGIS 3.x (extensions: `postgis`)
- Python 3.13, Flask, psycopg2, flask-cors, python-dotenv, requests
- OpenLayers 7.5 (incl. OpenLayers Heatmap layer)
- OpenStreetMap raster tiles
- EPSG:4326 (WGS84) for storage and exchange; EPSG:3857 (Web Mercator) for display; EPSG:5234 (Sri Lanka Kandawala Grid) for surveying-grade local coordinates in the popup.
