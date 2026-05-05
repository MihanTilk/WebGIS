-- WebGIS Asset Tracking - 6 sample assets around Colombo, Sri Lanka
-- Run inside the asset_tracking database after 01_schema.sql

INSERT INTO assets (name, asset_type, geom) VALUES
('Truck 1', 'vehicle', ST_SetSRID(ST_MakePoint(79.880, 6.900), 4326)),
('Truck 2', 'vehicle', ST_SetSRID(ST_MakePoint(79.870, 6.910), 4326)),
('Van 1', 'vehicle', ST_SetSRID(ST_MakePoint(79.890, 6.895), 4326)),
('Surveyor', 'person', ST_SetSRID(ST_MakePoint(79.875, 6.905), 4326)),
('Generator', 'equipment', ST_SetSRID(ST_MakePoint(79.885, 6.915), 4326)),
('Drone 1', 'equipment', ST_SetSRID(ST_MakePoint(79.882, 6.902), 4326));

-- Quick verification
SELECT id, name, asset_type, ST_AsText(geom) AS location FROM assets ORDER BY id;
