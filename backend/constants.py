"""Shared constants used by simulator.py and seed_assets.py.

Both scripts spawn assets with realistic names and place them around real
Sri Lankan towns. Keeping the lists in one module prevents the two files
from drifting out of sync.
"""

NAME_POOL = {
    "vehicle": ["Truck", "Van", "Lorry", "Pickup", "Bus", "Bike"],
    "person": ["Surveyor", "Inspector", "Technician", "Field Agent", "Engineer"],
    "equipment": ["Generator", "Drone", "Crane", "Excavator", "Compactor", "Beacon"],
}

# (city_name, lon, lat). Spawning around these keeps assets on land and
# looks like a realistic distribution rather than a uniform bbox sprinkle.
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
