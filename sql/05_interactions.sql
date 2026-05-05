-- Typed proximity encounters: each asset_type pair maps to a kind (PICKUP/LOADING/OPERATING/MEETING/CONVOY). Safe to re-run.

CREATE TABLE IF NOT EXISTS interactions (
    id SERIAL PRIMARY KEY,
    asset_a_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    asset_b_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMP, -- NULL = still active
    location GEOMETRY(Point, 4326) NOT NULL, -- midpoint at start
    CHECK (asset_a_id < asset_b_id), -- deduplicate (a,b)/(b,a)
    CHECK (kind IN ('PICKUP','LOADING','OPERATING','MEETING','CONVOY'))
);

CREATE INDEX IF NOT EXISTS idx_interactions_started ON interactions (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_interactions_active ON interactions (asset_a_id, asset_b_id, kind) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_interactions_geom ON interactions USING GIST (location);

-- Read-only view used by the GET endpoint; joins names + computes live duration.
CREATE OR REPLACE VIEW interactions_view AS
SELECT
    i.id,
    i.asset_a_id, a.name AS asset_a_name, a.asset_type AS asset_a_type,
    i.asset_b_id, b.name AS asset_b_name, b.asset_type AS asset_b_type,
    i.kind,
    i.started_at,
    i.ended_at,
    EXTRACT(EPOCH FROM (COALESCE(i.ended_at, NOW()) - i.started_at))::int AS duration_s,
    ST_X(i.location) AS lon,
    ST_Y(i.location) AS lat,
    i.location
FROM interactions i
JOIN assets a ON a.id = i.asset_a_id
JOIN assets b ON b.id = i.asset_b_id;
