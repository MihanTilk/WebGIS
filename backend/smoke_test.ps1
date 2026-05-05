# Smoke-test the asset-tracking API. Run while `python app.py` is up.
$base = "http://localhost:5000/api/assets"

Write-Host "`n[1] GET all assets" -ForegroundColor Cyan
$all = Invoke-RestMethod $base
"  feature count: $($all.features.Count)"

Write-Host "`n[2] GET single asset (id=1)" -ForegroundColor Cyan
$one = Invoke-RestMethod "$base/1"
"  name: $($one.properties.name) | coords: $($one.geometry.coordinates -join ',')"

Write-Host "`n[3] GET filtered (type=vehicle)" -ForegroundColor Cyan
$veh = Invoke-RestMethod "${base}?type=vehicle"
"  vehicles: $($veh.features.Count)"

Write-Host "`n[4] PUT update asset 1" -ForegroundColor Cyan
$body = @{ longitude = 79.895; latitude = 6.920 } | ConvertTo-Json
$put = Invoke-RestMethod -Method Put -Uri "$base/1" -Body $body -ContentType "application/json"
"  status: $($put.status)"

Write-Host "`n[5] GET asset 1 again to confirm update" -ForegroundColor Cyan
$check = Invoke-RestMethod "$base/1"
"  new coords: $($check.geometry.coordinates -join ',')"
"  last_seen:  $($check.properties.last_seen)"

Write-Host "`n[6] PUT with missing fields (expect 400)" -ForegroundColor Cyan
try {
    Invoke-RestMethod -Method Put -Uri "$base/1" -Body '{}' -ContentType "application/json" | Out-Null
} catch {
    "  status: $($_.Exception.Response.StatusCode) | body: $($_.ErrorDetails.Message)"
}

Write-Host "`n[7] GET non-existent asset 999 (expect 404)" -ForegroundColor Cyan
try { Invoke-RestMethod "$base/999" | Out-Null } catch {
    "  status: $($_.Exception.Response.StatusCode)"
}

Write-Host "`nDone." -ForegroundColor Green
