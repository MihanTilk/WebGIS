# WebGIS Asset Tracking

A small WebGIS application that tracks moving assets (vehicles, people, equipment) on an interactive map. Locations are stored in PostGIS, served as GeoJSON by a Flask REST API, and rendered with OpenLayers in the browser. A simulator script periodically updates each asset's position to mimic real-time movement.

Built for the *Building a WebGIS Asset Tracking Application* assignment (Index 226121P).

## Architecture

```
OpenLayers (browser)  --HTTP/GeoJSON-->  Flask API  --SQL-->  PostgreSQL + PostGIS
```

- **Database**: PostgreSQL 18 with PostGIS, single `assets` table holding a WGS84 point geometry per asset.
- **Backend**: Flask exposing `GET /api/assets`, `GET /api/assets/<id>`, `PUT /api/assets/<id>`. Returns standard GeoJSON `FeatureCollection`.
- **Frontend**: OpenLayers 7 over an OpenStreetMap base layer. Polls the API every 5 seconds, supports asset-type filtering, click popups, and a colour-coded legend.
- **Simulator**: a small Python script that random-walks each asset and PUTs the new coordinates to the API.

## Project layout

```
.
├── backend/
│   ├── app.py             # Flask REST API
│   ├── simulator.py       # Periodic location updater
│   ├── smoke_test.ps1     # PowerShell smoke test for all endpoints
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── index.html         # OpenLayers map with periodic refresh
├── sql/
│   ├── 01_schema.sql      # CREATE TABLE assets + GIST index
│   └── 02_sample_data.sql # 6 seed assets around Colombo
└── docs/
    └── screenshots/
```

## Quick start (Windows)

### 1. Database

Install PostgreSQL 18 with PostGIS, then in `psql`:

```sql
CREATE DATABASE asset_tracking;
\c asset_tracking
```

Load the schema and sample data:

```powershell
psql -U postgres -p 5433 -d asset_tracking -f sql\01_schema.sql
psql -U postgres -p 5433 -d asset_tracking -f sql\02_sample_data.sql
```

### 2. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # then edit DB_PASS
python app.py
```

API serves on http://localhost:5000.

### 3. Frontend

In a second terminal:

```powershell
cd frontend
python -m http.server 8000
```

Open http://localhost:8000 in your browser.

### 4. Simulator (optional, shows movement)

In a third terminal:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python simulator.py
```

Each asset's position is nudged every 5 seconds; the map reflects the change on its next poll.

## API reference

| Method | Path                       | Description                                                  |
|--------|----------------------------|--------------------------------------------------------------|
| GET    | `/api/assets`              | All assets as GeoJSON. Supports `?type=vehicle\|person\|equipment` |
| GET    | `/api/assets/<id>`         | Single asset as GeoJSON Feature                              |
| PUT    | `/api/assets/<id>`         | Update location: JSON body `{"latitude":..,"longitude":..}`  |

Run `backend\smoke_test.ps1` to exercise every endpoint.

## Tech stack

- PostgreSQL 18 + PostGIS 3.x
- Python 3.13, Flask, psycopg2, flask-cors, python-dotenv, requests
- OpenLayers 7.5
- OpenStreetMap tiles
