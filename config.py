"""Configuration constants for the Stockholm bus deadhead analysis tool."""

import os

# API
API_KEY_KODA = os.environ.get("KODA_API_KEY", "4psdkvdO9UIYsziDkp3AlnGUL5N5a4tE19N2TSja28I")
OPERATOR = "sl"

# Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Deadhead detection thresholds
MIN_DEADHEAD_MOVE_METERS = 500       # Minimum movement to count as deadhead
MAX_DEADHEAD_SPEED_KMH = 90          # Max realistic speed for a bus (km/h)
MIN_DEADHEAD_SPEED_KMH = 2           # Min speed - slower is likely parked, not moving
MAX_DEADHEAD_DURATION_MIN = 180      # Max duration for a single deadhead (3 hours)
MIN_DEADHEAD_DURATION_MIN = 1        # Min duration - shorter is likely GPS noise

# Label constants
NO_TRIP_LABEL = "Okänd tur"
NO_TRIP_COLOR = "#5f6368"

# Operator mapping for known bus routes
OPERATOR_MAPPING = [
    {"route_short_name": "172", "operator": "Nobina"},
    {"route_short_name": "173", "operator": "Nobina"},
    {"route_short_name": "176", "operator": "Nobina"},
    {"route_short_name": "177", "operator": "Nobina"},
    {"route_short_name": "160", "operator": "Nobina"},
    {"route_short_name": "161", "operator": "Nobina"},
    {"route_short_name": "144", "operator": "Nobina"},
    {"route_short_name": "188", "operator": "Nobina"},
    {"route_short_name": "676", "operator": "Transdev"},
    {"route_short_name": "639", "operator": "Transdev"},
    {"route_short_name": "641", "operator": "Transdev"},
    {"route_short_name": "657", "operator": "Transdev"},
    {"route_short_name": "658", "operator": "Transdev"},
    {"route_short_name": "4", "operator": "Keolis"},
    {"route_short_name": "6", "operator": "Keolis"},
    {"route_short_name": "40", "operator": "Keolis"},
    {"route_short_name": "41", "operator": "Keolis"},
    {"route_short_name": "43", "operator": "Keolis"},
    {"route_short_name": "43X", "operator": "Keolis"},
    {"route_short_name": "48", "operator": "Keolis"},
    {"route_short_name": "80", "operator": "Keolis"},
    {"route_short_name": "82", "operator": "Keolis"},
    {"route_short_name": "84", "operator": "Keolis"},
]
