-- Clustered island-wide seed: ~120 assets across 20 Sri Lankan cities,
-- ~6 per city with tight (~300 m) jitter so each city looks like a real
-- cluster rather than a uniform sprinkle. Biased toward people (~60%).
--
-- Safe to re-run (it appends). To start from a clean island demo:
--
--   TRUNCATE asset_history;
--   TRUNCATE assets RESTART IDENTITY CASCADE;
--   \i sql/04_clustered_seed.sql

WITH cities(city, lon, lat) AS (VALUES
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
plan AS (
    -- Pull all four randoms ONCE per row. Stacking independent random()
    -- calls inside CASE/WHEN compounds probabilities (the second test only
    -- runs for rows that failed the first), so 60/25/15 would actually have
    -- come out as 60/34/6.
    SELECT
        c.city, c.lon, c.lat, gs AS seq,
        random() AS r_type,
        random() AS r_lon,
        random() AS r_lat
    FROM cities c, generate_series(1, 6) gs           -- 6 assets per city → 120 total
),
typed AS (
    SELECT *,
        CASE
            WHEN r_type < 0.60 THEN 'person'      -- 60%
            WHEN r_type < 0.85 THEN 'vehicle'     -- 25%
            ELSE                     'equipment'  -- 15%
        END AS asset_type
    FROM plan
),
named AS (
    SELECT
        asset_type, city, seq, lon, lat, r_lon, r_lat,
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
    ST_SetSRID(ST_MakePoint(
        lon + (r_lon - 0.5) * 0.006,    -- ±0.003° ≈ ±330 m
        lat + (r_lat - 0.5) * 0.006
    ), 4326) AS geom
FROM named;

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

-- Quick check: rows per city / type
SELECT split_part(split_part(name, '(', 2), ' ', 1) AS city,
       asset_type,
       COUNT(*)
FROM assets
GROUP BY city, asset_type
ORDER BY city, asset_type;

-- And how many history rows exist now
SELECT 'history rows total' AS metric, COUNT(*) AS value FROM asset_history;
