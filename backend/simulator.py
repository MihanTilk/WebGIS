"""Simulate moving assets by random-walking each one and PUT-ing the new
location to the Flask API every few seconds. Run alongside `app.py`."""

import random
import time

import requests

API = "http://localhost:5000/api/assets"
INTERVAL_SECONDS = 5
JITTER_DEGREES = 0.0008  # roughly 80 m per tick


def jitter(value):
    return value + random.uniform(-JITTER_DEGREES, JITTER_DEGREES)


def main():
    resp = requests.get(API, timeout=10)
    resp.raise_for_status()
    features = resp.json()["features"]
    positions = {
        f["properties"]["id"]: list(f["geometry"]["coordinates"]) for f in features
    }
    print(f"Tracking {len(positions)} assets")

    while True:
        for asset_id, (lon, lat) in positions.items():
            new_lon, new_lat = jitter(lon), jitter(lat)
            positions[asset_id] = [new_lon, new_lat]
            r = requests.put(
                f"{API}/{asset_id}",
                json={"longitude": new_lon, "latitude": new_lat},
                timeout=5,
            )
            if r.status_code != 200:
                print(f"  asset {asset_id}: {r.status_code} {r.text}")
        print(f"tick — moved {len(positions)} assets")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
