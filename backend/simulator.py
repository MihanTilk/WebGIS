"""Drive the asset-tracking demo: random-walk every existing asset every
INTERVAL seconds, and (optionally) spawn fresh assets over time.

CLI flags:
  --interval SECS         How often each tick fires (default 5)
  --spawn-every SECS      Auto-spawn a new asset every N ticks (default 0 = off)
  --spawn-max N           Stop spawning once total reaches N (default 50)
  --jitter DEG            Max degrees of random walk per axis per tick (default 0.002 ≈ 220 m)
  --center LON,LAT        Centre to spawn around (default 79.880,6.900 = Colombo)
  --spawn-radius DEG      How far from centre new assets can appear (default 0.02)
  --types LIST            Comma list of types to pick from (default vehicle,person,equipment)

Examples:
  python simulator.py                                     # vanilla, ticks 5s, no spawning
  python simulator.py --interval 2                        # faster ticks
  python simulator.py --spawn-every 6 --spawn-max 30      # +1 asset every 6 ticks, capped at 30
  python simulator.py --interval 1 --spawn-every 3        # busy demo: 1s ticks, frequent new assets
"""

import argparse
import os
import random
import sys
import time

import requests

from constants import NAME_POOL, SRI_LANKA_CITIES

# Override locally with API_BASE=https://your-app.onrender.com/api in the env.
API_BASE = os.getenv("API_BASE", "http://localhost:5000/api").rstrip("/")
API = f"{API_BASE}/assets"
INTERACTIONS_DETECT_URL = f"{API_BASE}/interactions/detect"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--interval", type=float, default=5)
    p.add_argument("--spawn-every", type=int, default=0,
                   help="0 disables spawning")
    p.add_argument("--spawn-max", type=int, default=50)
    p.add_argument("--jitter", type=float, default=0.002,
                   help="Max degrees per axis per tick (default 0.002 ≈ 220 m)")
    p.add_argument("--center", default="79.880,6.900",
                   help="LON,LAT pair around which new assets spawn (ignored if --island)")
    p.add_argument("--spawn-radius", type=float, default=0.02)
    p.add_argument("--types", default="vehicle,person,equipment")
    p.add_argument("--island", action="store_true",
                   help="Spread spawns across all major Sri Lankan cities "
                        "(overrides --center / --spawn-radius)")
    p.add_argument("--city-jitter", type=float, default=0.03,
                   help="Random offset in degrees applied to each city pick (default 0.03 = ~3 km)")
    return p.parse_args()


def random_position(center, radius):
    cx, cy = center
    return [
        cx + random.uniform(-radius, radius),
        cy + random.uniform(-radius, radius),
    ]


def random_city_position(jitter_deg):
    _, lon, lat = random.choice(SRI_LANKA_CITIES)
    return [
        lon + random.uniform(-jitter_deg, jitter_deg),
        lat + random.uniform(-jitter_deg, jitter_deg),
    ]


def random_name(asset_type, counters):
    pool = NAME_POOL.get(asset_type, [asset_type.title()])
    base = random.choice(pool)
    counters[base] = counters.get(base, 0) + 1
    return f"{base} {counters[base]}"


def fetch_existing():
    resp = requests.get(API, timeout=10)
    resp.raise_for_status()
    features = resp.json()["features"]
    return {
        f["properties"]["id"]: list(f["geometry"]["coordinates"]) for f in features
    }


def spawn_new(position_fn, types, counters):
    asset_type = random.choice(types)
    name = random_name(asset_type, counters)
    pos = position_fn()
    body = {"name": name, "asset_type": asset_type,
            "longitude": pos[0], "latitude": pos[1]}
    r = requests.post(API, json=body, timeout=5)
    if r.status_code != 201:
        print(f"  spawn failed: {r.status_code} {r.text}")
        return None
    new_id = r.json()["id"]
    print(f"  + spawned [{new_id}] {name} ({asset_type}) at {pos[0]:.4f},{pos[1]:.4f}")
    return new_id, pos


def jitter(value, amount):
    return value + random.uniform(-amount, amount)


def main():
    args = parse_args()
    try:
        cx, cy = (float(x) for x in args.center.split(","))
    except ValueError:
        print("--center must be LON,LAT (e.g. 79.880,6.900)", file=sys.stderr)
        sys.exit(1)
    types = [t.strip() for t in args.types.split(",") if t.strip() in NAME_POOL]
    if not types:
        print("--types must contain at least one of vehicle/person/equipment",
              file=sys.stderr)
        sys.exit(1)

    try:
        positions = fetch_existing()
    except requests.RequestException as e:
        print(f"Cannot reach Flask API at {API}: {e}", file=sys.stderr)
        print("Is `python app.py` running?", file=sys.stderr)
        sys.exit(1)

    if args.island:
        def position_fn():
            return random_city_position(args.city_jitter)
        spawn_desc = f"island-wide ({len(SRI_LANKA_CITIES)} cities, ±{args.city_jitter}°)"
    else:
        def position_fn():
            return random_position((cx, cy), args.spawn_radius)
        spawn_desc = f"around {cx:.3f},{cy:.3f} (±{args.spawn_radius}°)"

    counters = {}
    print(f"Tracking {len(positions)} assets, ticking every {args.interval}s "
          f"(Ctrl+C to stop)")
    if args.spawn_every > 0:
        print(f"Auto-spawn: +1 asset every {args.spawn_every} ticks, "
              f"cap {args.spawn_max}, {spawn_desc}")

    tick = 0
    while True:
        tick += 1

        # Move every existing asset
        for asset_id, (lon, lat) in list(positions.items()):
            new_lon = jitter(lon, args.jitter)
            new_lat = jitter(lat, args.jitter)
            positions[asset_id] = [new_lon, new_lat]
            try:
                r = requests.put(
                    f"{API}/{asset_id}",
                    json={"longitude": new_lon, "latitude": new_lat},
                    timeout=5,
                )
                if r.status_code != 200:
                    print(f"  asset {asset_id}: {r.status_code} {r.text}")
            except requests.RequestException as e:
                print(f"  asset {asset_id}: network error {e}")

        # Auto-spawn?
        if (args.spawn_every > 0
                and tick % args.spawn_every == 0
                and len(positions) < args.spawn_max):
            result = spawn_new(position_fn, types, counters)
            if result is not None:
                new_id, pos = result
                positions[new_id] = pos

        # Drive interaction detection on the same cadence as movement.
        try:
            r = requests.post(INTERACTIONS_DETECT_URL, timeout=10)
            if r.status_code == 200:
                d = r.json()
                if d.get("opened") or d.get("closed"):
                    print(f"  interactions: +{d['opened']} opened, "
                          f"{d['closed']} closed")
            else:
                print(f"  interactions detect: {r.status_code} {r.text}")
        except requests.RequestException as e:
            print(f"  interactions detect failed: {e}")

        print(f"tick {tick} — {len(positions)} assets")
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSimulator stopped.")
