# Smoke-test every endpoint of the asset-tracking API.
# Run while `python app.py` is up:
#   .\smoke_test.ps1

$base = "http://localhost:5000/api"

function Section($title) {
    Write-Host ""
    Write-Host "[$title]" -ForegroundColor Cyan
}

# ---- assets ----
Section "GET /api/assets"
$all = Invoke-RestMethod "$base/assets"
"  feature count: $($all.features.Count)"
if ($all.features.Count -eq 0) {
    Write-Host "  (no assets — load 02_sample_data.sql or 04_clustered_seed.sql first)" -ForegroundColor Yellow
    exit
}
$firstId = $all.features[0].properties.id

Section "GET /api/assets/$firstId"
$one = Invoke-RestMethod "$base/assets/$firstId"
"  name: $($one.properties.name) | coords: $($one.geometry.coordinates -join ',')"
"  WGS84 lat/lon: $($one.properties.lat),$($one.properties.lon)"
"  SLG E/N:        $($one.properties.easting),$($one.properties.northing)"

Section "GET /api/assets?type=vehicle"
$veh = Invoke-RestMethod "$base/assets?type=vehicle"
"  vehicles: $($veh.features.Count)"

Section "PUT /api/assets/$firstId  (update location)"
$body = @{ longitude = 79.895; latitude = 6.920 } | ConvertTo-Json
$put = Invoke-RestMethod -Method Put -Uri "$base/assets/$firstId" `
    -Body $body -ContentType "application/json"
"  status: $($put.status)"

Section "GET /api/assets/$firstId  (confirm update)"
$check = Invoke-RestMethod "$base/assets/$firstId"
"  new coords: $($check.geometry.coordinates -join ',')"

Section "POST /api/assets  (create new)"
$createBody = @{ name="Smoke Test Asset"; asset_type="equipment"; longitude=79.881; latitude=6.901 } | ConvertTo-Json
$created = Invoke-RestMethod -Method Post -Uri "$base/assets" `
    -Body $createBody -ContentType "application/json"
"  new id: $($created.id)"

# ---- history & motion ----
Section "GET /api/assets/$firstId/history?hours=24"
$hist = Invoke-RestMethod "$base/assets/$firstId/history?hours=24"
"  history rows: $($hist.metadata.point_count)"

Section "GET /api/assets/$firstId/motion"
$motion = Invoke-RestMethod "$base/assets/$firstId/motion"
if ($motion.speed_kmh -ne $null) {
    "  speed: $($motion.speed_kmh) km/h | heading: $($motion.heading_deg)°"
} else {
    "  not enough history to compute (need >=2 rows)"
}

Section "GET /api/history/range"
$range = Invoke-RestMethod "$base/history/range"
"  earliest: $($range.earliest)"
"  latest:   $($range.latest)"

# ---- snapshot ----
Section "GET /api/snapshot?at=<now>"
$now = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$snap = Invoke-RestMethod "$base/snapshot?at=$now"
"  assets at snapshot: $($snap.metadata.count)"

# ---- heatmap ----
Section "GET /api/heatmap?hours=24"
$heat = Invoke-RestMethod "$base/heatmap?hours=24"
"  weighted points: $($heat.metadata.count)"

# ---- proximity ----
Section "GET /api/proximity?lon=79.86&lat=6.92&radius_m=10000"
$prox = Invoke-RestMethod "$base/proximity?lon=79.86&lat=6.92&radius_m=10000"
"  assets within 10 km of central Colombo: $($prox.metadata.count)"

# ---- error paths ----
Section "Error paths (expected to fail)"
try {
    Invoke-RestMethod -Method Put -Uri "$base/assets/$firstId" -Body '{}' -ContentType "application/json" | Out-Null
} catch {
    "  PUT empty body  -> $($_.Exception.Response.StatusCode) (expected 400)"
}
try { Invoke-RestMethod "$base/assets/9999999" | Out-Null } catch {
    "  GET missing id  -> $($_.Exception.Response.StatusCode) (expected 404)"
}
try { Invoke-RestMethod "$base/assets?type=alien" | Out-Null } catch {
    "  GET bad type    -> $($_.Exception.Response.StatusCode) (expected 400)"
}
try { Invoke-RestMethod "$base/proximity?lon=200&lat=0&radius_m=100" | Out-Null } catch {
    "  GET bad coords  -> $($_.Exception.Response.StatusCode) (expected 400)"
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
