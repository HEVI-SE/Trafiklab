"""Utility functions for the Stockholm bus deadhead analysis tool."""

import math
import pandas as pd


def haversine_m(lat1, lon1, lat2, lon2):
    """Calculate distance in meters between two GPS coordinates."""
    if any(pd.isna(v) for v in [lat1, lon1, lat2, lon2]):
        return None
    r = 6371000.0
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def safe_str(x, default="-"):
    """Convert value to string safely, returning default for NaN/None/empty."""
    if pd.isna(x):
        return default
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return default
    return s


def classify_period(ts):
    """Classify a timestamp into a traffic period."""
    if pd.isna(ts):
        return "Bas"
    h = ts.hour
    if 6 <= h < 9:
        return "FM-topp"
    if 15 <= h < 18:
        return "EM-topp"
    if h >= 21 or h < 5:
        return "Natt"
    return "Bas"


def classify_day_type(ts):
    """Classify a timestamp as weekday (Vardag) or weekend (Helg)."""
    if pd.isna(ts):
        return "Vardag"
    ts = pd.to_datetime(ts)
    return "Helg" if ts.dayofweek >= 5 else "Vardag"


def html_escape(s):
    """Escape HTML special characters."""
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
