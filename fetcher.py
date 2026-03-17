"""Data fetching module for KoDa Trafiklab API."""

import gc
import os
import shutil
import time
import zipfile
from datetime import datetime

import pandas as pd
import py7zr
import requests
from google.transit import gtfs_realtime_pb2

from config import (
    API_KEY_KODA,
    DATA_DIR,
    NO_TRIP_LABEL,
    OPERATOR,
)
from utils import haversine_m, safe_str


def file_exists_nonempty(path):
    return os.path.exists(path) and os.path.getsize(path) > 0


def folder_has_pb_files(folder_path):
    if not os.path.exists(folder_path):
        return False
    for root, _, files_ in os.walk(folder_path):
        for fn in files_:
            if fn.endswith(".pb"):
                full = os.path.join(root, fn)
                if os.path.getsize(full) > 0:
                    return True
    return False


def fetch_with_retry(url, out_path, max_wait_minutes=25, sleep_seconds=30, force_download=False):
    """Fetch a URL, retrying on 202 Accepted (KoDa generates archives on demand)."""
    if (not force_download) and file_exists_nonempty(out_path):
        print(f"  Redan hämtad: {os.path.basename(out_path)}")
        return out_path

    deadline = pd.Timestamp.now() + pd.Timedelta(minutes=max_wait_minutes)
    attempt = 0
    while True:
        attempt += 1
        resp = requests.get(url, timeout=300)
        if resp.status_code == 202:
            now_str = datetime.now().strftime("%H:%M:%S")
            if pd.Timestamp.now() >= deadline:
                raise RuntimeError(f"KoDa svarade 202 i {max_wait_minutes} min för {url}")
            print(f"  [{now_str}] Försök {attempt}: 202, väntar {sleep_seconds}s...")
            time.sleep(sleep_seconds)
            continue
        resp.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(resp.content)
        return out_path


def load_static_gtfs(date_str, force_download=False):
    """Download and parse static GTFS data for a given date."""
    date_dir = os.path.join(DATA_DIR, f"static_{OPERATOR}_{date_str}")
    zip_path = os.path.join(DATA_DIR, f"static_{OPERATOR}_{date_str}.zip")
    os.makedirs(date_dir, exist_ok=True)

    url = f"https://api.koda.trafiklab.se/KoDa/api/v2/gtfs-static/{OPERATOR}?date={date_str}&key={API_KEY_KODA}"

    routes_txt = os.path.join(date_dir, "routes.txt")
    trips_txt = os.path.join(date_dir, "trips.txt")
    stops_txt = os.path.join(date_dir, "stops.txt")
    stop_times_txt = os.path.join(date_dir, "stop_times.txt")

    if force_download or not file_exists_nonempty(zip_path):
        print(f"Hämtar static GTFS för {date_str}...")
        fetch_with_retry(url, zip_path, max_wait_minutes=10, sleep_seconds=20, force_download=force_download)
    else:
        print(f"Använder cachad static GTFS för {date_str}.")

    if force_download or not os.path.exists(routes_txt):
        print(f"Extraherar static GTFS för {date_str}...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(date_dir)

    routes = pd.read_csv(routes_txt, dtype=str)
    trips = pd.read_csv(trips_txt, dtype=str)
    stops = pd.read_csv(stops_txt, dtype=str)
    stop_times = pd.read_csv(stop_times_txt, dtype=str)

    routes["route_id"] = routes["route_id"].astype(str)
    trips["route_id"] = trips["route_id"].astype(str)
    trips["trip_id"] = trips["trip_id"].astype(str)
    stops["stop_id"] = stops["stop_id"].astype(str)
    stops["stop_name"] = stops["stop_name"].astype(str)
    stops["stop_lat"] = pd.to_numeric(stops["stop_lat"], errors="coerce")
    stops["stop_lon"] = pd.to_numeric(stops["stop_lon"], errors="coerce")
    stop_times["trip_id"] = stop_times["trip_id"].astype(str)
    stop_times["stop_id"] = stop_times["stop_id"].astype(str)
    stop_times["stop_sequence"] = pd.to_numeric(stop_times["stop_sequence"], errors="coerce")

    return routes, trips, stops, stop_times


def build_trip_lookup(trips_df, routes_df, operator_df, stop_times_df, stops_df):
    """Build a trip_id -> metadata lookup table."""
    trips_sub = trips_df[["trip_id", "route_id", "direction_id", "trip_headsign"]].copy()
    routes_sub = routes_df[["route_id", "route_short_name", "route_long_name"]].copy()
    lookup = trips_sub.merge(routes_sub, on="route_id", how="left")

    operator_df = operator_df.copy()
    operator_df["route_short_name"] = operator_df["route_short_name"].astype(str)
    lookup["route_short_name"] = lookup["route_short_name"].astype(str)
    lookup = lookup.merge(operator_df, on="route_short_name", how="left")
    lookup["operator"] = lookup["operator"].fillna("Övrigt")
    lookup["direction_id"] = lookup["direction_id"].fillna("-")
    lookup["trip_headsign"] = lookup["trip_headsign"].fillna("-")
    lookup["route_short_name"] = lookup["route_short_name"].fillna(NO_TRIP_LABEL)

    # First and last stop per trip
    st = stop_times_df[["trip_id", "stop_id", "stop_sequence"]].copy()
    st = st.dropna(subset=["trip_id", "stop_id", "stop_sequence"])
    first_stop = (
        st.sort_values(["trip_id", "stop_sequence"])
        .groupby("trip_id", as_index=False)
        .first()[["trip_id", "stop_id"]]
        .rename(columns={"stop_id": "first_stop_id"})
    )
    last_stop = (
        st.sort_values(["trip_id", "stop_sequence"])
        .groupby("trip_id", as_index=False)
        .last()[["trip_id", "stop_id"]]
        .rename(columns={"stop_id": "last_stop_id"})
    )

    stops_small = stops_df[["stop_id", "stop_name"]].drop_duplicates()
    lookup = lookup.merge(first_stop, on="trip_id", how="left")
    lookup = lookup.merge(last_stop, on="trip_id", how="left")
    lookup = lookup.merge(
        stops_small.rename(columns={"stop_id": "first_stop_id", "stop_name": "first_stop_name"}),
        on="first_stop_id", how="left"
    )
    lookup = lookup.merge(
        stops_small.rename(columns={"stop_id": "last_stop_id", "stop_name": "last_stop_name"}),
        on="last_stop_id", how="left"
    )
    lookup["first_stop_name"] = lookup["first_stop_name"].fillna("-")
    lookup["last_stop_name"] = lookup["last_stop_name"].fillna("-")
    lookup = lookup.drop_duplicates(subset=["trip_id"]).set_index("trip_id")

    return lookup


def _parse_pb_files(folder_path, trip_lookup, active_states, finished_segments):
    """Parse protobuf vehicle position files into segments."""
    pb_files = []
    for root, _, files_ in os.walk(folder_path):
        for fn in files_:
            if fn.endswith(".pb"):
                full = os.path.join(root, fn)
                if os.path.getsize(full) > 0:
                    pb_files.append(full)
    pb_files = sorted(pb_files)
    obs_count = 0

    for pb_path in pb_files:
        feed = gtfs_realtime_pb2.FeedMessage()
        try:
            with open(pb_path, "rb") as f:
                feed.ParseFromString(f.read())
        except Exception:
            continue

        feed_ts = None
        try:
            if feed.header.timestamp:
                feed_ts = datetime.fromtimestamp(feed.header.timestamp)
        except Exception:
            feed_ts = None

        for ent in feed.entity:
            if not ent.HasField("vehicle"):
                continue
            v = ent.vehicle
            vehicle_id = str(v.vehicle.id) if v.vehicle.id else None
            if not vehicle_id:
                continue

            trip_id = str(v.trip.trip_id) if v.trip.trip_id else None
            rt_direction = None
            try:
                if v.trip.HasField("direction_id"):
                    rt_direction = str(v.trip.direction_id)
            except Exception:
                rt_direction = None

            vehicle_ts = None
            try:
                if v.timestamp:
                    vehicle_ts = datetime.fromtimestamp(v.timestamp)
            except Exception:
                vehicle_ts = None

            obs_time = feed_ts if feed_ts is not None else vehicle_ts
            if obs_time is None:
                continue

            lat, lon = None, None
            try:
                if v.position.latitude:
                    lat = float(v.position.latitude)
                if v.position.longitude:
                    lon = float(v.position.longitude)
            except Exception:
                lat, lon = None, None

            if trip_id and trip_id in trip_lookup.index:
                row = trip_lookup.loc[trip_id]
                route_short_name = safe_str(row["route_short_name"], NO_TRIP_LABEL)
                trip_headsign = safe_str(row["trip_headsign"], "-")
                direction_id = safe_str(row["direction_id"], "-")
                operator = safe_str(row["operator"], "Övrigt")
                first_stop_name = safe_str(row.get("first_stop_name", "-"), "-")
                last_stop_name = safe_str(row.get("last_stop_name", "-"), "-")
            else:
                route_short_name = NO_TRIP_LABEL
                trip_headsign = "-"
                direction_id = safe_str(rt_direction, "-")
                operator = "Övrigt"
                first_stop_name = "-"
                last_stop_name = "-"

            state = (route_short_name, direction_id)
            prev = active_states.get(vehicle_id)

            if prev is None:
                active_states[vehicle_id] = {
                    "vehicle_id": vehicle_id,
                    "trip_id": trip_id,
                    "start_time": obs_time,
                    "end_time": obs_time,
                    "route_short_name": route_short_name,
                    "direction_id": direction_id,
                    "trip_headsign": trip_headsign,
                    "operator": operator,
                    "first_stop_name": first_stop_name,
                    "last_stop_name": last_stop_name,
                    "start_lat": lat,
                    "start_lon": lon,
                    "end_lat": lat,
                    "end_lon": lon,
                    "state": state,
                }
            else:
                if state == prev["state"]:
                    prev["end_time"] = obs_time
                    prev["end_lat"] = lat
                    prev["end_lon"] = lon
                    if prev["trip_headsign"] in ["-", "nan", "None"] and trip_headsign not in ["-", "nan", "None"]:
                        prev["trip_headsign"] = trip_headsign
                    if prev["first_stop_name"] == "-" and first_stop_name != "-":
                        prev["first_stop_name"] = first_stop_name
                    if prev["last_stop_name"] == "-" and last_stop_name != "-":
                        prev["last_stop_name"] = last_stop_name
                else:
                    finished_segments.append({
                        "vehicle_id": prev["vehicle_id"],
                        "trip_id": prev["trip_id"],
                        "start_time": prev["start_time"],
                        "end_time": obs_time,
                        "route_short_name": prev["route_short_name"],
                        "direction_id": prev["direction_id"],
                        "trip_headsign": prev["trip_headsign"],
                        "operator": prev["operator"],
                        "first_stop_name": prev["first_stop_name"],
                        "last_stop_name": prev["last_stop_name"],
                        "start_lat": prev["start_lat"],
                        "start_lon": prev["start_lon"],
                        "end_lat": prev["end_lat"],
                        "end_lon": prev["end_lon"],
                    })
                    active_states[vehicle_id] = {
                        "vehicle_id": vehicle_id,
                        "trip_id": trip_id,
                        "start_time": obs_time,
                        "end_time": obs_time,
                        "route_short_name": route_short_name,
                        "direction_id": direction_id,
                        "trip_headsign": trip_headsign,
                        "operator": operator,
                        "first_stop_name": first_stop_name,
                        "last_stop_name": last_stop_name,
                        "start_lat": lat,
                        "start_lon": lon,
                        "end_lat": lat,
                        "end_lon": lon,
                        "state": state,
                    }
            obs_count += 1
    return obs_count


def fetch_vehicle_positions(date_str, hours, trip_lookup, force_download=False):
    """Fetch and parse vehicle positions for a single date and list of hours.

    Returns a DataFrame of segments (one row per continuous trip/state per vehicle).
    """
    active_states = {}
    finished_segments = []
    total_obs = 0

    for hour in hours:
        print(f"  Timme {hour:02d}...")
        hour_str = f"{hour:02d}"
        hour_7z = os.path.join(DATA_DIR, f"vp_{OPERATOR}_{date_str}_{hour_str}.7z")
        hour_dir = os.path.join(DATA_DIR, f"vp_{OPERATOR}_{date_str}_{hour_str}")
        url = (
            f"https://api.koda.trafiklab.se/KoDa/api/v2/gtfs-rt/"
            f"{OPERATOR}/VehiclePositions?date={date_str}&hour={hour_str}&key={API_KEY_KODA}"
        )

        try:
            fetch_with_retry(url, hour_7z, max_wait_minutes=20, sleep_seconds=30, force_download=force_download)
        except Exception as e:
            print(f"    Hoppar över timme {hour_str}: {e}")
            continue

        os.makedirs(hour_dir, exist_ok=True)
        try:
            if force_download or not folder_has_pb_files(hour_dir):
                print(f"    Extraherar...")
                with py7zr.SevenZipFile(hour_7z, mode="r") as z:
                    z.extractall(hour_dir)
        except Exception as e:
            print(f"    Kunde inte extrahera timme {hour_str}: {e}")
            continue

        try:
            obs_count = _parse_pb_files(hour_dir, trip_lookup, active_states, finished_segments)
            total_obs += obs_count
            print(f"    Observationer: {obs_count:,}  Segment: {len(finished_segments):,}")
        except Exception as e:
            print(f"    Fel vid parsing timme {hour_str}: {e}")

        gc.collect()

    # Flush remaining active states
    for prev in active_states.values():
        finished_segments.append({
            "vehicle_id": prev["vehicle_id"],
            "trip_id": prev["trip_id"],
            "start_time": prev["start_time"],
            "end_time": prev["end_time"],
            "route_short_name": prev["route_short_name"],
            "direction_id": prev["direction_id"],
            "trip_headsign": prev["trip_headsign"],
            "operator": prev["operator"],
            "first_stop_name": prev["first_stop_name"],
            "last_stop_name": prev["last_stop_name"],
            "start_lat": prev["start_lat"],
            "start_lon": prev["start_lon"],
            "end_lat": prev["end_lat"],
            "end_lon": prev["end_lon"],
        })

    if not finished_segments:
        return pd.DataFrame()

    seg_df = pd.DataFrame(finished_segments)
    seg_df["start_time"] = pd.to_datetime(seg_df["start_time"])
    seg_df["end_time"] = pd.to_datetime(seg_df["end_time"])
    seg_df = seg_df.sort_values(["vehicle_id", "start_time", "end_time"]).reset_index(drop=True)
    seg_df["duration_min"] = (
        (seg_df["end_time"] - seg_df["start_time"]).dt.total_seconds() / 60
    ).round(1).clip(lower=0)
    seg_df["move_m"] = seg_df.apply(
        lambda r: haversine_m(r["start_lat"], r["start_lon"], r["end_lat"], r["end_lon"]),
        axis=1,
    )
    seg_df["display_text"] = seg_df.apply(
        lambda r: NO_TRIP_LABEL if r["route_short_name"] == NO_TRIP_LABEL
        else f"{r['route_short_name']} | {r['trip_headsign']}",
        axis=1,
    )

    print(f"  Totalt observationer: {total_obs:,}, segment: {len(seg_df):,}")
    return seg_df
