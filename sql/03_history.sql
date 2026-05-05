-- Movement history: log every position change automatically via trigger.
-- Safe to re-run.

CREATE TABLE IF NOT EXISTS asset_history (
    id          SERIAL PRIMARY KEY,
    asset_id    INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    recorded_at TIMESTAMP NOT NULL DEFAULT NOW(),
    geom        GEOMETRY(Point, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_history_asset_time
    ON asset_history (asset_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_history_geom
    ON asset_history USING GIST (geom);

-- Trigger function: log every position change to history.
CREATE OR REPLACE FUNCTION log_asset_position() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.geom IS DISTINCT FROM NEW.geom THEN
        INSERT INTO asset_history (asset_id, recorded_at, geom)
        VALUES (NEW.id, NEW.last_seen, NEW.geom);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_log_asset_position ON assets;
CREATE TRIGGER trg_log_asset_position
AFTER UPDATE OF geom ON assets
FOR EACH ROW
EXECUTE FUNCTION log_asset_position();

-- Backfill a starting snapshot for each existing asset so trails have an origin.
INSERT INTO asset_history (asset_id, recorded_at, geom)
SELECT id, last_seen, geom
FROM assets
WHERE NOT EXISTS (
    SELECT 1 FROM asset_history WHERE asset_id = assets.id
);
