-- Two-tier island-wide seed: ~150 assets total.
--   * 120 clustered: ~6 per city × 20 cities, ±300 m jitter (≈60% person)
--   * 30 roaming:    free-scattered across the Sri Lanka bbox (≈55% vehicle)
-- The verification query at the end groups by the city tag in the name —
-- the roaming tier shows up as a "Roaming" row.
--
-- Safe to re-run (it appends). To start from a clean island demo:
--
--   TRUNCATE asset_history;
--   TRUNCATE assets RESTART IDENTITY CASCADE;
--   \i sql/04_clustered_seed.sql

-- Hand-built Sri Lanka mainland polygon (~38 vertices, clockwise from
-- Point Pedro). Used by both the clustered and roaming tiers below to
-- guarantee no asset lands in the ocean.
WITH sri_lanka(geom) AS (
    SELECT ST_GeomFromText(
        'POLYGON((
            80.21 9.83, 80.50 9.65, 80.80 9.45, 81.10 9.05, 81.20 8.85,
            81.23 8.59, 81.30 8.30, 81.55 8.05, 81.70 7.72, 81.80 7.40,
            81.85 7.05, 81.85 6.75, 81.65 6.45, 81.45 6.30, 81.20 6.15,
            80.95 6.05, 80.78 5.98, 80.55 5.92, 80.40 5.94, 80.22 6.04,
            80.10 6.18, 80.00 6.43, 79.96 6.58, 79.88 6.85, 79.83 7.13,
            79.82 7.40, 79.80 7.57, 79.83 7.85, 79.83 8.03, 79.75 8.25,
            79.72 8.50, 79.78 8.75, 79.85 9.05, 79.92 9.30, 79.95 9.55,
            80.00 9.70, 80.10 9.78, 80.21 9.83
        ))',
        4326
    )
),
cities(city, lon, lat) AS (VALUES
    ('Colombo',      79.861::float, 6.927::float),
    ('Negombo',      79.836,        7.208),
    ('Galle',        80.221,        6.054),
    ('Matara',       80.535,        5.949),
    ('Hambantota',   81.119,        6.124),
    ('Kandy',        80.634,        7.291),
    ('Nuwara Eliya', 80.789,        6.950),
    ('Ratnapura',    80.404,        6.683),
    ('Badulla',      81.055,        6.993),
    ('Kurunegala',   80.365,        7.486),
    ('Anuradhapura', 80.404,        8.311),
    ('Polonnaruwa',  81.019,        7.940),
    ('Sigiriya',     80.760,        7.957),
    ('Dambulla',     80.652,        7.868),
    ('Trincomalee',  81.234,        8.587),
    ('Batticaloa',   81.692,        7.717),
    ('Vavuniya',     80.497,        8.754),
    ('Mannar',       79.905,        8.981),
    ('Jaffna',       80.025,        9.661),
    ('Kegalle',      80.346,        7.251)
),
-- Over-generate 12 candidates per city; we'll pick the first 6 that pass
-- the land-polygon test. Coastal cities sometimes lose a few candidates
-- to the sea — the cluster shrinks gracefully.
plan AS (
    SELECT
        c.city, c.lon, c.lat, gs AS seq,
        random() AS r_type,
        random() AS r_lon,
        random() AS r_lat,
        c.lon + (random() - 0.5) * 0.006 AS jit_lon,
        c.lat + (random() - 0.5) * 0.006 AS jit_lat
    FROM cities c, generate_series(1, 12) gs
),
on_land AS (
    SELECT p.*,
        ROW_NUMBER() OVER (PARTITION BY p.city ORDER BY p.seq) AS rn_in_city
    FROM plan p, sri_lanka sl
    WHERE ST_Contains(sl.geom, ST_SetSRID(ST_MakePoint(p.jit_lon, p.jit_lat), 4326))
),
typed AS (
    SELECT *,
        CASE
            WHEN r_type < 0.60 THEN 'person'      -- 60%
            WHEN r_type < 0.85 THEN 'vehicle'     -- 25%
            ELSE                     'equipment'  -- 15%
        END AS asset_type
    FROM on_land
    WHERE rn_in_city <= 6                          -- target 6 per city
),
named AS (
    SELECT
        asset_type, city, seq, jit_lon, jit_lat,
        CASE asset_type
            WHEN 'person'    THEN (ARRAY['Surveyor','Inspector','Technician','Field Agent','Engineer'])[1 + (random()*5)::int % 5]
            WHEN 'vehicle'   THEN (ARRAY['Truck','Van','Lorry','Pickup','Bus','Bike'])[1 + (random()*6)::int % 6]
            ELSE                  (ARRAY['Generator','Drone','Crane','Excavator','Compactor','Beacon'])[1 + (random()*6)::int % 6]
        END AS base_name
    FROM typed
)
INSERT INTO assets (name, asset_type, geom)
SELECT
    base_name || ' (' || city || ' ' || seq::text || ')' AS name,
    asset_type,
    ST_SetSRID(ST_MakePoint(jit_lon, jit_lat), 4326) AS geom
FROM named;

-- Roaming tier: ~30 assets scattered freely on Sri Lanka land (in-transit /
-- off-grid). Bias toward vehicles since real road traffic between cities is
-- mostly vehicular. We over-generate ~150 random bbox candidates and clip
-- against a hand-built Sri Lanka mainland polygon (PostGIS ST_Contains),
-- then take the first 30 that fall on land. This is the same containment
-- predicate used in the geofencing literature (Lec 1: spatial relationships).
WITH sri_lanka(geom) AS (
    -- Same detailed polygon as the clustered tier above. Duplicated rather
    -- than shared because the two INSERT statements are independent.
    SELECT ST_GeomFromText(
        'POLYGON((
            80.21 9.83, 80.50 9.65, 80.80 9.45, 81.10 9.05, 81.20 8.85,
            81.23 8.59, 81.30 8.30, 81.55 8.05, 81.70 7.72, 81.80 7.40,
            81.85 7.05, 81.85 6.75, 81.65 6.45, 81.45 6.30, 81.20 6.15,
            80.95 6.05, 80.78 5.98, 80.55 5.92, 80.40 5.94, 80.22 6.04,
            80.10 6.18, 80.00 6.43, 79.96 6.58, 79.88 6.85, 79.83 7.13,
            79.82 7.40, 79.80 7.57, 79.83 7.85, 79.83 8.03, 79.75 8.25,
            79.72 8.50, 79.78 8.75, 79.85 9.05, 79.92 9.30, 79.95 9.55,
            80.00 9.70, 80.10 9.78, 80.21 9.83
        ))',
        4326
    )
),
roam_candidates AS (
    SELECT
        gs,
        random() AS r_type,
        79.70 + random() * (81.85 - 79.70) AS lon,
        6.00  + random() * (9.70  - 6.00)  AS lat
    FROM generate_series(1, 200) gs
),
roam_on_land AS (
    SELECT
        rc.*,
        ROW_NUMBER() OVER (ORDER BY rc.gs) AS rn
    FROM roam_candidates rc, sri_lanka sl
    WHERE ST_Contains(sl.geom, ST_SetSRID(ST_MakePoint(rc.lon, rc.lat), 4326))
),
roam_typed AS (
    SELECT *,
        CASE
            WHEN r_type < 0.55 THEN 'vehicle'    -- 55%
            WHEN r_type < 0.85 THEN 'person'     -- 30%
            ELSE                     'equipment' -- 15%
        END AS asset_type
    FROM roam_on_land
    WHERE rn <= 30
),
roam_named AS (
    SELECT *,
        CASE asset_type
            WHEN 'person'    THEN (ARRAY['Surveyor','Inspector','Technician','Field Agent','Engineer'])[1 + (random()*5)::int % 5]
            WHEN 'vehicle'   THEN (ARRAY['Truck','Van','Lorry','Pickup','Bus','Bike'])[1 + (random()*6)::int % 6]
            ELSE                  (ARRAY['Generator','Drone','Crane','Excavator','Compactor','Beacon'])[1 + (random()*6)::int % 6]
        END AS base_name
    FROM roam_typed
)
INSERT INTO assets (name, asset_type, geom)
SELECT
    base_name || ' (Roaming ' || rn::text || ')' AS name,
    asset_type,
    ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS geom
FROM roam_named;

-- Synthetic past-walk: give each just-inserted asset ~30 historical
-- positions across the last ~45 minutes, so trail visualization works
-- immediately (without waiting for the simulator to accumulate history).
-- Random walk with ~60 m steps, anchored to current position and walked
-- backward in time. The AFTER-INSERT trigger already added the step=0
-- "now" row, so we skip step=0 here.
WITH RECURSIVE
recent_assets AS (
    SELECT id, geom FROM assets
    WHERE last_seen >= statement_timestamp() - INTERVAL '10 seconds'
),
walk(asset_id, step, lon, lat, recorded_at) AS (
    SELECT id, 0, ST_X(geom)::float, ST_Y(geom)::float, NOW()
    FROM recent_assets
    UNION ALL
    SELECT
        asset_id,
        step + 1,
        lon + (random() - 0.5) * 0.0006,    -- ~60 m per step
        lat + (random() - 0.5) * 0.0006,
        recorded_at - INTERVAL '90 seconds'  -- ~30 steps × 90 s = 45 min back
    FROM walk
    WHERE step < 29
)
INSERT INTO asset_history (asset_id, recorded_at, geom)
SELECT
    asset_id,
    recorded_at,
    ST_SetSRID(ST_MakePoint(lon, lat), 4326)
FROM walk
WHERE step > 0;

-- ---------------------------------------------------------------------------
-- Synthetic past interactions for the side-panel demo. Without this, the
-- panel is empty until the random-walk simulator happens to bring two
-- assets close enough for long enough — which can take many minutes given
-- the rule thresholds. We pre-populate the table with 25 plausible past
-- encounters drawn from existing in-cluster pairs.
--
-- Spread the start times across the last hour, durations from 30 s to a few
-- minutes, and leave 5 of them open (ended_at IS NULL) so the live indicator
-- in the side panel has something to show. Only insert into `interactions`
-- if the table is reachable (skip silently if 05_interactions.sql wasn't run).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF to_regclass('public.interactions') IS NULL THEN
        RAISE NOTICE 'interactions table not found — skipping synthetic backfill (run sql/05_interactions.sql first)';
        RETURN;
    END IF;

    WITH near_pairs AS (
        SELECT
            LEAST(a.id, b.id)    AS asset_a_id,
            GREATEST(a.id, b.id) AS asset_b_id,
            a.asset_type AS a_t,
            b.asset_type AS b_t,
            a.geom AS a_geom,
            b.geom AS b_geom,
            ST_Distance(a.geom::geography, b.geom::geography) AS dist_m
        FROM assets a
        JOIN assets b ON a.id < b.id
        WHERE ST_DWithin(a.geom::geography, b.geom::geography, 800)  -- in-cluster pairs
    ),
    typed_pairs AS (
        SELECT *,
            CASE
                WHEN (a_t='vehicle'   AND b_t='person')    OR (a_t='person'    AND b_t='vehicle')   THEN 'PICKUP'
                WHEN (a_t='vehicle'   AND b_t='equipment') OR (a_t='equipment' AND b_t='vehicle')   THEN 'LOADING'
                WHEN (a_t='person'    AND b_t='equipment') OR (a_t='equipment' AND b_t='person')    THEN 'OPERATING'
                WHEN  a_t='person'    AND b_t='person'                                              THEN 'MEETING'
                WHEN  a_t='vehicle'   AND b_t='vehicle'                                             THEN 'CONVOY'
            END AS kind
        FROM near_pairs
    ),
    -- Sample at most one pair per kind per city slot for variety
    sampled AS (
        SELECT *,
            random() AS r_age,        -- 0..1: how far back in the hour
            random() AS r_dur,        -- 0..1: duration spread
            row_number() OVER (PARTITION BY kind ORDER BY random()) AS k_rn,
            row_number() OVER (ORDER BY random())                   AS overall_rn
        FROM typed_pairs
        WHERE kind IS NOT NULL
    )
    INSERT INTO interactions (asset_a_id, asset_b_id, kind, started_at, ended_at, location)
    SELECT
        asset_a_id,
        asset_b_id,
        kind,
        NOW() - (INTERVAL '1 hour' * r_age) AS started_at,
        -- 5 of the 25 stay "active" (ended_at NULL); the rest closed after 30s–4min
        CASE
            WHEN overall_rn <= 5 THEN NULL
            ELSE NOW() - (INTERVAL '1 hour' * r_age)
                 + (INTERVAL '30 seconds' + INTERVAL '4 minutes' * r_dur)
        END AS ended_at,
        ST_Centroid(ST_Collect(a_geom, b_geom)) AS location
    FROM sampled
    WHERE k_rn <= 5            -- at most 5 of each kind
      AND overall_rn <= 25     -- 25 total
    ORDER BY overall_rn;
END $$;

-- Quick check: rows per city / type
SELECT split_part(split_part(name, '(', 2), ' ', 1) AS city,
       asset_type,
       COUNT(*)
FROM assets
GROUP BY city, asset_type
ORDER BY city, asset_type;

-- And how many history rows exist now
SELECT 'history rows total' AS metric, COUNT(*) AS value FROM asset_history;

-- And how many interactions (closed + active) the synthetic backfill produced
SELECT
    'interactions: ' || kind AS metric,
    COUNT(*) FILTER (WHERE ended_at IS NULL) AS active,
    COUNT(*) FILTER (WHERE ended_at IS NOT NULL) AS closed
FROM interactions
GROUP BY kind
ORDER BY kind;
