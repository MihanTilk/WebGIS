-- WebGIS Asset Tracking - schema
-- Run inside the asset_tracking database. Safe to re-run.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS assets (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    asset_type  TEXT NOT NULL,
    last_seen   TIMESTAMP DEFAULT NOW(),
    geom        GEOMETRY(Point, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_assets_geom ON assets USING GIST (geom);

-- Tighten existing tables (NOOP if already NOT NULL).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'assets'
          AND column_name = 'geom'
          AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE assets ALTER COLUMN geom SET NOT NULL;
    END IF;
END $$;
