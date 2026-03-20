"""Deadhead (tomkörning) analysis module with safety checks and OSRM filtering."""

import time

import pandas as pd
import requests

from config import (
    BUS_ROUTE_TYPES,
    MAX_DEADHEAD_DURATION_MIN,
    MAX_DEADHEAD_SPEED_KMH,
    MIN_DEADHEAD_DURATION_MIN,
    MIN_DEADHEAD_MOVE_METERS,
    MIN_DEADHEAD_SPEED_KMH,
    NO_TRIP_LABEL,
)
from utils import classify_period, haversine_m, safe_str


def nearest_stop_name(lat, lon, stops_df):
    """Find the nearest stop name to a GPS coordinate."""
    if pd.isna(lat) or pd.isna(lon):
        return None
    valid = stops_df.dropna(subset=["stop_lat", "stop_lon"]).copy()
    if valid.empty:
        return None
    dists = valid.apply(
        lambda r: haversine_m(lat, lon, r["stop_lat"], r["stop_lon"]),
        axis=1,
    )
    idx = dists.idxmin()
    if pd.isna(idx):
        return None
    return safe_str(valid.loc[idx, "stop_name"], default=None)


def prepare_row_labels(seg_df):
    """Assign row labels to vehicles for visualization."""
    seg_df = seg_df.copy()

    def resolve_operator(series):
        vals = [str(x).strip() for x in series.dropna().tolist()]
        vals = [x for x in vals if x != ""]
        real_ops = sorted(set(x for x in set(vals) if x != "Övrigt"))
        if len(real_ops) == 0:
            return "Övrigt"
        elif len(real_ops) == 1:
            return real_ops[0]
        else:
            return "Flera"

    row_info = (
        seg_df.groupby("vehicle_id", as_index=False)
        .agg(
            resolved_operator=("operator", resolve_operator),
            first_start=("start_time", "min"),
        )
        .sort_values(["first_start", "vehicle_id"])
        .reset_index(drop=True)
    )
    row_info["row_no"] = range(1, len(row_info) + 1)
    row_info["row_label"] = row_info["row_no"].apply(lambda n: f"Rad {int(n):04d}")

    seg_df = seg_df.merge(
        row_info[["vehicle_id", "resolved_operator", "row_label", "row_no", "first_start"]],
        on="vehicle_id",
        how="left",
    )
    seg_df["operator"] = seg_df["resolved_operator"]
    seg_df = seg_df.drop(columns=["resolved_operator"], errors="ignore")
    seg_df["row_label"] = seg_df["row_label"].fillna("Rad okänd")

    ordered_rows = row_info.sort_values("row_no")["row_label"].dropna().drop_duplicates().tolist()
    return seg_df, ordered_rows


def _validate_deadhead(move_m, duration_min):
    """Apply safety checks to a potential deadhead.

    Returns (is_valid, rejection_reason).
    """
    if move_m is None or move_m < MIN_DEADHEAD_MOVE_METERS:
        return False, "rörelse_för_kort"

    if duration_min < MIN_DEADHEAD_DURATION_MIN:
        return False, "för_kort_tid"

    if duration_min > MAX_DEADHEAD_DURATION_MIN:
        return False, "för_lång_tid"

    speed_kmh = (move_m / 1000.0) / (duration_min / 60.0) if duration_min > 0 else 0

    if speed_kmh > MAX_DEADHEAD_SPEED_KMH:
        return False, f"för_snabb ({speed_kmh:.0f} km/h)"

    if speed_kmh < MIN_DEADHEAD_SPEED_KMH:
        return False, f"för_långsam ({speed_kmh:.1f} km/h)"

    return True, None


def _parse_gtfs_time_to_minutes(t):
    """Parse GTFS time string (HH:MM:SS, can be >24h) to total minutes from midnight."""
    if not t or t == "-" or pd.isna(t):
        return None
    try:
        parts = str(t).split(":")
        return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60
    except Exception:
        return None


def _period_from_gtfs_time(t):
    """Classify a GTFS time string into a traffic period."""
    minutes = _parse_gtfs_time_to_minutes(t)
    if minutes is None:
        return "Bas"
    h = int(minutes // 60) % 24
    if 6 <= h < 9:
        return "FM-topp"
    if 15 <= h < 18:
        return "EM-topp"
    if h >= 21 or h < 5:
        return "Natt"
    return "Bas"


def build_observed_deadheads(seg_df, stops_df):
    """Identify observed deadheads from vehicle position segments."""
    df = seg_df.sort_values(["vehicle_id", "start_time"]).reset_index(drop=True).copy()
    records = []
    rejected_counts = {}

    for vehicle_id, g in df.groupby("vehicle_id"):
        g = g.sort_values("start_time").reset_index(drop=True)
        i = 0
        while i < len(g) - 2:
            prev_seg = g.iloc[i]
            if prev_seg["route_short_name"] == NO_TRIP_LABEL:
                i += 1
                continue

            j = i + 1
            unknown_group = []
            while j < len(g) and g.iloc[j]["route_short_name"] == NO_TRIP_LABEL:
                unknown_group.append(g.iloc[j])
                j += 1

            if len(unknown_group) == 0:
                i += 1
                continue
            if j >= len(g):
                break

            next_seg = g.iloc[j]
            if next_seg["route_short_name"] == NO_TRIP_LABEL:
                i += 1
                continue

            unknown_df = pd.DataFrame(unknown_group)
            start_unknown = unknown_df.iloc[0]
            end_unknown = unknown_df.iloc[-1]

            from_lat = start_unknown["start_lat"]
            from_lon = start_unknown["start_lon"]
            to_lat = end_unknown["end_lat"]
            to_lon = end_unknown["end_lon"]

            move_m = haversine_m(from_lat, from_lon, to_lat, to_lon)

            deadhead_start = pd.to_datetime(start_unknown["start_time"])
            deadhead_end = pd.to_datetime(end_unknown["end_time"])
            duration_min = round((deadhead_end - deadhead_start).total_seconds() / 60.0, 1)

            is_valid, reason = _validate_deadhead(move_m, duration_min)
            if not is_valid:
                rejected_counts[reason] = rejected_counts.get(reason, 0) + 1
                i += 1
                continue

            from_stop_obs = nearest_stop_name(from_lat, from_lon, stops_df)
            to_stop_obs = nearest_stop_name(to_lat, to_lon, stops_df)

            if not from_stop_obs and not to_stop_obs:
                i += 1
                continue

            speed_kmh = (move_m / 1000.0) / (duration_min / 60.0) if duration_min > 0 else 0

            records.append({
                "type": "observed",
                "vehicle_id": vehicle_id,
                "operator": safe_str(prev_seg["operator"], "Övrigt"),
                "prev_route": safe_str(prev_seg["route_short_name"], "-"),
                "prev_headsign": safe_str(prev_seg["trip_headsign"], "-"),
                "prev_last_stop_planned": safe_str(prev_seg["last_stop_name"], "-"),
                "next_route": safe_str(next_seg["route_short_name"], "-"),
                "next_headsign": safe_str(next_seg["trip_headsign"], "-"),
                "next_first_stop_planned": safe_str(next_seg["first_stop_name"], "-"),
                "deadhead_start": deadhead_start,
                "deadhead_end": deadhead_end,
                "duration_min": duration_min,
                "period": classify_period(deadhead_start),
                "from_stop_observed": safe_str(from_stop_obs, "-"),
                "to_stop_observed": safe_str(to_stop_obs, "-"),
                "from_lat": from_lat,
                "from_lon": from_lon,
                "to_lat": to_lat,
                "to_lon": to_lon,
                "move_m": round(move_m, 1) if move_m is not None else None,
                "speed_kmh": round(speed_kmh, 1),
            })
            i = j

    if rejected_counts:
        print(f"  Avvisade tomkörningskandidater: {rejected_counts}")

    dead_df = pd.DataFrame(records)
    if dead_df.empty:
        return dead_df

    dead_df["deadhead_label"] = dead_df.apply(
        lambda r: f"{r['from_stop_observed']} \u2192 {r['to_stop_observed']}", axis=1
    )
    return dead_df.sort_values(["deadhead_start", "operator", "vehicle_id"]).reset_index(drop=True)


def build_planned_deadheads(trips_df, stop_times_df, stops_df, routes_df, operator_df):
    """Identify planned deadheads from static GTFS schedule."""
    if "block_id" not in trips_df.columns:
        print("  Ingen block_id i GTFS-data, kan inte beräkna planerade tomkörningar.")
        return pd.DataFrame()

    trips = trips_df.copy()
    trips = trips.dropna(subset=["block_id"])
    trips = trips[trips["block_id"].str.strip() != ""]

    if trips.empty:
        print("  Inga block_id hittades i turdata.")
        return pd.DataFrame()

    print(f"  {len(trips)} turer med block_id ({trips['block_id'].nunique()} block)")

    st = stop_times_df[["trip_id", "stop_id", "stop_sequence", "departure_time", "arrival_time"]].copy()
    st = st.dropna(subset=["trip_id", "stop_id", "stop_sequence"])
    st["stop_sequence"] = pd.to_numeric(st["stop_sequence"], errors="coerce")

    first_stops = (
        st.sort_values(["trip_id", "stop_sequence"])
        .groupby("trip_id", as_index=False)
        .first()
        .rename(columns={
            "stop_id": "first_stop_id",
            "departure_time": "first_departure",
        })[["trip_id", "first_stop_id", "first_departure"]]
    )

    last_stops = (
        st.sort_values(["trip_id", "stop_sequence"])
        .groupby("trip_id", as_index=False)
        .last()
        .rename(columns={
            "stop_id": "last_stop_id",
            "arrival_time": "last_arrival",
        })[["trip_id", "last_stop_id", "last_arrival"]]
    )

    trips = trips.merge(first_stops, on="trip_id", how="left")
    trips = trips.merge(last_stops, on="trip_id", how="left")

    # Merge route info and filter to bus routes only
    route_cols = ["route_id", "route_short_name"]
    if "route_type" in routes_df.columns:
        route_cols.append("route_type")
    routes_sub = routes_df[route_cols].copy()
    trips = trips.merge(routes_sub, on="route_id", how="left")

    if "route_type" in trips.columns:
        trips["route_type"] = trips["route_type"].astype(str).str.strip()
        bus_mask = trips["route_type"].isin(BUS_ROUTE_TYPES)
        n_before = len(trips)
        trips = trips[bus_mask].reset_index(drop=True)
        print(f"  Filtrerat till bussar: {len(trips)} av {n_before} turer")

    op_df = operator_df.copy()
    op_df["route_short_name"] = op_df["route_short_name"].astype(str)
    trips["route_short_name"] = trips["route_short_name"].astype(str)
    trips = trips.merge(op_df, on="route_short_name", how="left")
    trips["operator"] = trips["operator"].fillna("Övrigt")

    stops_small = stops_df[["stop_id", "stop_name", "stop_lat", "stop_lon"]].drop_duplicates(subset=["stop_id"])

    trips = trips.merge(
        stops_small.rename(columns={"stop_id": "first_stop_id", "stop_name": "first_stop_name",
                                     "stop_lat": "first_lat", "stop_lon": "first_lon"}),
        on="first_stop_id", how="left",
    )
    trips = trips.merge(
        stops_small.rename(columns={"stop_id": "last_stop_id", "stop_name": "last_stop_name",
                                     "stop_lat": "last_lat", "stop_lon": "last_lon"}),
        on="last_stop_id", how="left",
    )

    trips = trips.sort_values(["block_id", "first_departure"]).reset_index(drop=True)

    records = []
    for block_id, block_trips in trips.groupby("block_id"):
        block_trips = block_trips.sort_values("first_departure").reset_index(drop=True)
        for idx in range(len(block_trips) - 1):
            curr = block_trips.iloc[idx]
            nxt = block_trips.iloc[idx + 1]

            if curr["last_stop_id"] == nxt["first_stop_id"]:
                continue

            last_lat = curr.get("last_lat")
            last_lon = curr.get("last_lon")
            first_lat = nxt.get("first_lat")
            first_lon = nxt.get("first_lon")

            move_m = haversine_m(last_lat, last_lon, first_lat, first_lon)

            if move_m is not None and move_m < MIN_DEADHEAD_MOVE_METERS:
                continue

            # Calculate planned duration from GTFS times
            t_start = _parse_gtfs_time_to_minutes(curr.get("last_arrival"))
            t_end = _parse_gtfs_time_to_minutes(nxt.get("first_departure"))
            duration_min = None
            if t_start is not None and t_end is not None:
                duration_min = round(t_end - t_start, 1)
                if duration_min < 0:
                    duration_min = None

            period = _period_from_gtfs_time(curr.get("last_arrival"))

            speed_kmh = None
            if duration_min and duration_min > 0 and move_m:
                speed_kmh = round((move_m / 1000.0) / (duration_min / 60.0), 1)

            records.append({
                "type": "planned",
                "vehicle_id": f"block_{block_id}",
                "operator": safe_str(curr.get("operator", "Övrigt")),
                "prev_route": safe_str(curr.get("route_short_name", "-")),
                "prev_headsign": safe_str(curr.get("trip_headsign", "-")),
                "prev_last_stop_planned": safe_str(curr.get("last_stop_name", "-")),
                "next_route": safe_str(nxt.get("route_short_name", "-")),
                "next_headsign": safe_str(nxt.get("trip_headsign", "-")),
                "next_first_stop_planned": safe_str(nxt.get("first_stop_name", "-")),
                "deadhead_start": curr.get("last_arrival", "-"),
                "deadhead_end": nxt.get("first_departure", "-"),
                "duration_min": duration_min,
                "period": period,
                "from_stop_observed": safe_str(curr.get("last_stop_name", "-")),
                "to_stop_observed": safe_str(nxt.get("first_stop_name", "-")),
                "from_lat": float(last_lat) if pd.notna(last_lat) else None,
                "from_lon": float(last_lon) if pd.notna(last_lon) else None,
                "to_lat": float(first_lat) if pd.notna(first_lat) else None,
                "to_lon": float(first_lon) if pd.notna(first_lon) else None,
                "move_m": round(move_m, 1) if move_m is not None else None,
                "speed_kmh": speed_kmh,
            })

    dead_df = pd.DataFrame(records)
    if dead_df.empty:
        return dead_df

    dead_df["deadhead_label"] = dead_df.apply(
        lambda r: f"{r['from_stop_observed']} \u2192 {r['to_stop_observed']}", axis=1
    )
    return dead_df.sort_values(["deadhead_start", "operator"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# OSRM-based filtering
# ---------------------------------------------------------------------------

_osrm_cache = {}


def _osrm_route_duration(lat1, lon1, lat2, lon2):
    """Query OSRM for driving duration in minutes between two points."""
    key = (round(lat1, 4), round(lon1, 4), round(lat2, 4), round(lon2, 4))
    if key in _osrm_cache:
        return _osrm_cache[key]

    url = (
        f"http://router.project-osrm.org/route/v1/driving/"
        f"{key[1]},{key[0]};{key[3]},{key[2]}?overview=false"
    )
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("code") == "Ok" and data.get("routes"):
            duration_min = data["routes"][0]["duration"] / 60.0
            _osrm_cache[key] = duration_min
            return duration_min
    except Exception:
        pass

    _osrm_cache[key] = None
    return None


def filter_deadheads_osrm(dead_df, min_ratio=0.5, max_ratio=2.0):
    """Filter deadheads where observed duration is unrealistic vs OSRM driving time.

    Removes deadheads that are >100% slower or >50% faster than OSRM estimate.
    """
    if dead_df.empty:
        return dead_df

    needed_cols = ["from_lat", "from_lon", "to_lat", "to_lon", "duration_min"]
    if not all(c in dead_df.columns for c in needed_cols):
        print("  OSRM-filter: saknar koordinater, hoppar över.")
        return dead_df

    # Get unique coordinate pairs
    coord_df = dead_df[["from_lat", "from_lon", "to_lat", "to_lon"]].dropna()
    pairs = (
        coord_df
        .apply(lambda r: (round(r["from_lat"], 4), round(r["from_lon"], 4),
                          round(r["to_lat"], 4), round(r["to_lon"], 4)), axis=1)
        .unique()
    )

    print(f"  OSRM: frågar {len(pairs)} unika rutter...")
    for i, (la1, lo1, la2, lo2) in enumerate(pairs):
        _osrm_route_duration(la1, lo1, la2, lo2)
        if (i + 1) % 50 == 0:
            print(f"    {i + 1}/{len(pairs)} klara")
            time.sleep(0.5)  # Be nice to the public server
        elif (i + 1) % 10 == 0:
            time.sleep(0.1)

    def is_valid(row):
        if pd.isna(row.get("from_lat")) or pd.isna(row.get("duration_min")):
            return True
        key = (round(row["from_lat"], 4), round(row["from_lon"], 4),
               round(row["to_lat"], 4), round(row["to_lon"], 4))
        osrm_min = _osrm_cache.get(key)
        if osrm_min is None or osrm_min <= 0:
            return True
        ratio = row["duration_min"] / osrm_min
        return min_ratio <= ratio <= max_ratio

    mask = dead_df.apply(is_valid, axis=1)
    n_removed = (~mask).sum()
    n_cached = sum(1 for v in _osrm_cache.values() if v is not None)
    print(f"  OSRM-filter: {n_removed} tomkörningar borttagna, {n_cached} rutter med OSRM-data")
    return dead_df[mask].reset_index(drop=True)
