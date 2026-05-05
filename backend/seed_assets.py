"""One-shot bulk loader: POST N random assets to the API and exit.

  python seed_assets.py 20 # 20 around default centre (Colombo)
  python seed_assets.py 50 --radius 0.05 # spread wider
  python seed_assets.py 30 --types vehicle # only vehicles
  python seed_assets.py 40 --island # spread across all of Sri Lanka
"""

import argparse
import random
import sys

import requests

API = "http://localhost:5000/api/assets"
NAME_POOL = {
    "vehicle": ["Truck", "Van", "Lorry", "Pickup", "Bus", "Bike"],
    "person": ["Surveyor", "Inspector", "Technician", "Field Agent", "Engineer"],
    "equipment": ["Generator", "Drone", "Crane", "Excavator", "Compactor", "Beacon"],
}

SRI_LANKA_CITIES = [
    ("Colombo", 79.861, 6.927),
    ("Negombo", 79.836, 7.208),
    ("Galle", 80.221, 6.054),
    ("Matara", 80.535, 5.949),
    ("Hambantota", 81.119, 6.124),
    ("Kandy", 80.634, 7.291),
    ("Nuwara Eliya", 80.789, 6.950),
    ("Ratnapura", 80.404, 6.683),
    ("Badulla", 81.055, 6.993),
    ("Kurunegala", 80.365, 7.486),
    ("Anuradhapura", 80.404, 8.311),
    ("Polonnaruwa", 81.019, 7.940),
    ("Sigiriya", 80.760, 7.957),
    ("Dambulla", 80.652, 7.868),
    ("Trincomalee", 81.234, 8.587),
    ("Batticaloa", 81.692, 7.717),
    ("Vavuniya", 80.497, 8.754),
    ("Mannar", 79.905, 8.981),
    ("Jaffna", 80.025, 9.661),
    ("Kegalle", 80.346, 7.251),
]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("count", type=int, help="how many assets to create")
    p.add_argument("--center", default="79.880,6.900",
                   help="LON,LAT (ignored if --island)")
    p.add_argument("--radius", type=float, default=0.02,
                   help="Spawn radius in degrees (ignored if --island)")
    p.add_argument("--types", default="vehicle,person,equipment")
    p.add_argument("--island", action="store_true",
                   help="Spread spawns across all major Sri Lankan cities")
    p.add_argument("--city-jitter", type=float, default=0.03)
    args = p.parse_args()

    cx, cy = (float(x) for x in args.center.split(","))
    types = [t.strip() for t in args.types.split(",") if t.strip() in NAME_POOL]
    if not types:
        print("Invalid --types", file=sys.stderr); sys.exit(1)

    if args.island:
        def position_fn():
            _, lon, lat = random.choice(SRI_LANKA_CITIES)
            return (
                lon + random.uniform(-args.city_jitter, args.city_jitter),
                lat + random.uniform(-args.city_jitter, args.city_jitter),
            )
    else:
        def position_fn():
            return (
                cx + random.uniform(-args.radius, args.radius),
                cy + random.uniform(-args.radius, args.radius),
            )

    counters = {}
    created = 0
    for _ in range(args.count):
        t = random.choice(types)
        base = random.choice(NAME_POOL[t])
        counters[base] = counters.get(base, 0) + 1
        lon, lat = position_fn()
        body = {
            "name": f"{base} {counters[base]}",
            "asset_type": t,
            "longitude": lon,
            "latitude":  lat,
        }
        r = requests.post(API, json=body, timeout=5)
        if r.status_code == 201:
            created += 1
            print(f"+ [{r.json()['id']}] {body['name']} ({t}) at {lon:.3f},{lat:.3f}")
        else:
            print(f"  fail: {r.status_code} {r.text}")
    print(f"\nCreated {created}/{args.count} assets")


if __name__ == "__main__":
    main()
