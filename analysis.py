"""Deadhead (tomkörning) analysis module with safety checks."""

import pandas as pd

from config import (
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
    Checks:
    - Minimum movement distance
    - Duration within reasonable bounds
    - Speed within realistic bus range (not too slow = parked, not too fast = GPS error)
    """
    if move_m is None or move_m < MIN_DEADHEAD_MOVE_METERS:
        return False, "rörelse_för_kort"

    if duration_min < MIN_DEADHEAD_DURATION_MIN:
        return False, "för_kort_tid"

    if duration_min > MAX_DEADHEAD_DURATION_MIN:
        return False, "för_lång_tid"

    # Speed check: distance / time
    speed_kmh = (move_m / 1000.0) / (duration_min / 60.0) if duration_min > 0 else 0

    if speed_kmh > MAX_DEADHEAD_SPEED_KMH:
        return False, f"för_snabb ({speed_kmh:.0f} km/h)"

    if speed_kmh < MIN_DEADHEAD_SPEED_KMH:
        return False, f"för_långsam ({speed_kmh:.1f} km/h)"

    return True, None


def build_observed_deadheads(seg_df, stops_df):
    """Identify observed deadheads from vehicle position segments.

    An observed deadhead is a period where a vehicle moves between two known trips
    without passengers (detected as 'Okänd tur' segments between real trips).
    """
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

            move_m = haversine_m(
                start_unknown["start_lat"], start_unknown["start_lon"],
                end_unknown["end_lat"], end_unknown["end_lon"],
            )

            deadhead_start = pd.to_datetime(start_unknown["start_time"])
            deadhead_end = pd.to_datetime(end_unknown["end_time"])
            duration_min = round((deadhead_end - deadhead_start).total_seconds() / 60.0, 1)

            # Safety validation
            is_valid, reason = _validate_deadhead(move_m, duration_min)
            if not is_valid:
                rejected_counts[reason] = rejected_counts.get(reason, 0) + 1
                i += 1
                continue

            from_stop_obs = nearest_stop_name(start_unknown["start_lat"], start_unknown["start_lon"], stops_df)
            to_stop_obs = nearest_stop_name(end_unknown["end_lat"], end_unknown["end_lon"], stops_df)

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
        lambda r: f"{r['from_stop_observed']} → {r['to_stop_observed']}", axis=1
    )
    return dead_df.sort_values(["deadhead_start", "operator", "vehicle_id"]).reset_index(drop=True)


def build_planned_deadheads(trips_df, stop_times_df, stops_df, routes_df, operator_df):
    """Identify planned deadheads from static GTFS schedule.

    A planned deadhead occurs when the same block_id has consecutive trips
    where the last stop of trip N differs from the first stop of trip N+1.
    """
    if "block_id" not in trips_df.columns:
        print("  Ingen block_id i GTFS-data, kan inte beräkna planerade tomkörningar.")
        return pd.DataFrame()

    trips = trips_df.copy()
    trips = trips.dropna(subset=["block_id"])
    trips = trips[trips["block_id"].str.strip() != ""]

    if trips.empty:
        print("  Inga block_id hittades i turdata.")
        return pd.DataFrame()

    # Get first/last stop info per trip
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

    # Add route info
    routes_sub = routes_df[["route_id", "route_short_name"]].copy()
    trips = trips.merge(routes_sub, on="route_id", how="left")

    # Add operator info
    op_df = operator_df.copy()
    op_df["route_short_name"] = op_df["route_short_name"].astype(str)
    trips["route_short_name"] = trips["route_short_name"].astype(str)
    trips = trips.merge(op_df, on="route_short_name", how="left")
    trips["operator"] = trips["operator"].fillna("Övrigt")

    # Add stop names
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

    # Sort by block and departure time
    trips = trips.sort_values(["block_id", "first_departure"]).reset_index(drop=True)

    records = []
    for block_id, block_trips in trips.groupby("block_id"):
        block_trips = block_trips.sort_values("first_departure").reset_index(drop=True)
        for idx in range(len(block_trips) - 1):
            curr = block_trips.iloc[idx]
            nxt = block_trips.iloc[idx + 1]

            # If last stop of current trip != first stop of next trip, it's a planned deadhead
            if curr["last_stop_id"] == nxt["first_stop_id"]:
                continue

            move_m = haversine_m(
                curr.get("last_lat"), curr.get("last_lon"),
                nxt.get("first_lat"), nxt.get("first_lon"),
            )

            if move_m is not None and move_m < MIN_DEADHEAD_MOVE_METERS:
                continue

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
                "duration_min": None,
                "period": "-",
                "from_stop_observed": safe_str(curr.get("last_stop_name", "-")),
                "to_stop_observed": safe_str(nxt.get("first_stop_name", "-")),
                "move_m": round(move_m, 1) if move_m is not None else None,
                "speed_kmh": None,
            })

    dead_df = pd.DataFrame(records)
    if dead_df.empty:
        return dead_df

    dead_df["deadhead_label"] = dead_df.apply(
        lambda r: f"{r['from_stop_observed']} → {r['to_stop_observed']}", axis=1
    )
    return dead_df.sort_values(["deadhead_start", "operator"]).reset_index(drop=True)
