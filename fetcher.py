"""Data fetching module for KoDa Trafiklab API."""

import gc
import os
import shutil
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    rt_cols = ["route_id", "route_short_name", "route_long_name"]
    if "route_type" in routes_df.columns:
        rt_cols.append("route_type")
    routes_sub = routes_df[rt_cols].copy()
    lookup = trips_sub.merge(routes_sub, on="route_id", how="left")
    if "route_type" not in lookup.columns:
        lookup["route_type"] = ""

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
                route_type = safe_str(row.get("route_type", ""), "")
            else:
                route_short_name = NO_TRIP_LABEL
                trip_headsign = "-"
                direction_id = safe_str(rt_direction, "-")
                operator = "Övrigt"
                first_stop_name = "-"
                last_stop_name = "-"
                route_type = ""

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
                    "route_type": route_type,
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
                    if prev["route_type"] == "" and route_type != "":
                        prev["route_type"] = route_type
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
                        "route_type": prev["route_type"],
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
                        "route_type": route_type,
                        "start_lat": lat,
                        "start_lon": lon,
                        "end_lat": lat,
                        "end_lon": lon,
                        "state": state,
                    }
            obs_count += 1
    return obs_count


def _download_and_extract_hour(date_str, hour, force_download=False):
    """Download and extract a single hour's vehicle position data. Thread-safe."""
    hour_str = f"{hour:02d}"
    hour_7z = os.path.join(DATA_DIR, f"vp_{OPERATOR}_{date_str}_{hour_str}.7z")
    hour_dir = os.path.join(DATA_DIR, f"vp_{OPERATOR}_{date_str}_{hour_str}")
    url = (
        f"https://api.koda.trafiklab.se/KoDa/api/v2/gtfs-rt/"
        f"{OPERATOR}/VehiclePositions?date={date_str}&hour={hour_str}&key={API_KEY_KODA}"
    )

    try:
        fetch_with_retry(url, hour_7z, max_wait_minutes=25, sleep_seconds=30, force_download=force_download)
    except Exception as e:
        print(f"    Hoppar över timme {hour_str}: {e}")
        return hour, None

    os.makedirs(hour_dir, exist_ok=True)
    try:
        if force_download or not folder_has_pb_files(hour_dir):
            with py7zr.SevenZipFile(hour_7z, mode="r") as z:
                z.extractall(hour_dir)
    except Exception as e:
        print(f"    Kunde inte extrahera timme {hour_str}: {e}")
        return hour, None

    return hour, hour_dir


def fetch_vehicle_positions(date_str, hours, trip_lookup, force_download=False, max_workers=3):
    """Fetch and parse vehicle positions for a single date and list of hours.

    Downloads hours in parallel (max_workers threads), then parses sequentially.
    Failed hours are retried once after all others complete.
    Returns a DataFrame of segments (one row per continuous trip/state per vehicle).
    """
    active_states = {}
    finished_segments = []
    total_obs = 0

    # Phase 1: Download & extract hours in parallel
    print(f"  Laddar ner {len(hours)} timmar parallellt (max {max_workers} trådar)...")
    hour_dirs = {}
    failed_hours = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_download_and_extract_hour, date_str, hour, force_download): hour
            for hour in hours
        }
        for future in as_completed(futures):
            hour, hour_dir = future.result()
            if hour_dir is not None:
                hour_dirs[hour] = hour_dir
                print(f"    Timme {hour:02d} klar")
            else:
                failed_hours.append(hour)

    # Retry failed hours sequentially (often timeout due to parallel load)
    if failed_hours:
        print(f"  Försöker igen med {len(failed_hours)} misslyckade timmar...")
        time.sleep(5)
        for hour in sorted(failed_hours):
            print(f"    Retry timme {hour:02d}...")
            hour, hour_dir = _download_and_extract_hour(date_str, hour, force_download)
            if hour_dir is not None:
                hour_dirs[hour] = hour_dir
                print(f"    Timme {hour:02d} klar (retry)")

    print(f"  Nedladdning klar: {len(hour_dirs)}/{len(hours)} timmar")

    # Phase 2: Parse in chronological order (must be sequential for segment state tracking)
    for hour in sorted(hour_dirs.keys()):
        hour_dir = hour_dirs[hour]
        try:
            obs_count = _parse_pb_files(hour_dir, trip_lookup, active_states, finished_segments)
            total_obs += obs_count
            print(f"    Timme {hour:02d} parsed: {obs_count:,} obs, {len(finished_segments):,} segment")
        except Exception as e:
            print(f"    Fel vid parsing timme {hour:02d}: {e}")
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
            "route_type": prev.get("route_type", ""),
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


def filter_bus_segments(seg_df, bus_route_types=None):
    """Keep only vehicles that operate at least one bus route.

    Unknown-trip segments for bus vehicles are kept (needed for deadhead detection).
    """
    from config import BUS_ROUTE_TYPES

    if bus_route_types is None:
        bus_route_types = BUS_ROUTE_TYPES

    if "route_type" not in seg_df.columns:
        print("  Varning: route_type saknas – ingen filtrering gjord.")
        return seg_df

    bus_vehicles = seg_df[seg_df["route_type"].isin(bus_route_types)]["vehicle_id"].unique()
    filtered = seg_df[seg_df["vehicle_id"].isin(bus_vehicles)].copy()

    n_removed = seg_df["vehicle_id"].nunique() - filtered["vehicle_id"].nunique()
    print(f"  Bussfilter: {filtered['vehicle_id'].nunique()} bussfordon behålls, {n_removed} icke-buss borttagna")
    return filtered.reset_index(drop=True)


def _download_and_extract_tu_hour(date_str, hour, force_download=False):
    """Download and extract a single hour's TripUpdates data. Thread-safe."""
    hour_str = f"{hour:02d}"
    hour_7z = os.path.join(DATA_DIR, f"tu_{OPERATOR}_{date_str}_{hour_str}.7z")
    hour_dir = os.path.join(DATA_DIR, f"tu_{OPERATOR}_{date_str}_{hour_str}")
    url = (
        f"https://api.koda.trafiklab.se/KoDa/api/v2/gtfs-rt/"
        f"{OPERATOR}/TripUpdates?date={date_str}&hour={hour_str}&key={API_KEY_KODA}"
    )

    try:
        fetch_with_retry(url, hour_7z, max_wait_minutes=25, sleep_seconds=30, force_download=force_download)
    except Exception as e:
        print(f"    Hoppar över TripUpdates timme {hour_str}: {e}")
        return hour, None

    os.makedirs(hour_dir, exist_ok=True)
    try:
        if force_download or not folder_has_pb_files(hour_dir):
            with py7zr.SevenZipFile(hour_7z, mode="r") as z:
                z.extractall(hour_dir)
    except Exception as e:
        print(f"    Kunde inte extrahera TripUpdates timme {hour_str}: {e}")
        return hour, None

    return hour, hour_dir


def fetch_trip_updates(date_str, hours, trip_lookup, force_download=False, max_workers=3):
    """Fetch GTFS-RT TripUpdates and extract per-stop delay data.

    Downloads hours in parallel, then parses sequentially.
    Returns a DataFrame with columns: route_short_name, direction_id, stop_id, delay_seconds.
    """
    records = []

    # Phase 1: Download & extract hours in parallel
    print(f"  Laddar ner TripUpdates {len(hours)} timmar parallellt (max {max_workers} trådar)...")
    hour_dirs = {}
    failed_hours = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_download_and_extract_tu_hour, date_str, hour, force_download): hour
            for hour in hours
        }
        for future in as_completed(futures):
            hour, hour_dir = future.result()
            if hour_dir is not None:
                hour_dirs[hour] = hour_dir
                print(f"    TU timme {hour:02d} nedladdad")
            else:
                failed_hours.append(hour)

    if failed_hours:
        print(f"  Försöker igen med {len(failed_hours)} misslyckade TU-timmar...")
        time.sleep(5)
        for hour in sorted(failed_hours):
            hour, hour_dir = _download_and_extract_tu_hour(date_str, hour, force_download)
            if hour_dir is not None:
                hour_dirs[hour] = hour_dir

    print(f"  TripUpdates nedladdning klar: {len(hour_dirs)}/{len(hours)} timmar")

    # Phase 2: Parse in chronological order
    for hour in sorted(hour_dirs.keys()):
        hour_dir = hour_dirs[hour]

        pb_files = []
        for root, _, files_ in os.walk(hour_dir):
            for fn in files_:
                if fn.endswith(".pb"):
                    full = os.path.join(root, fn)
                    if os.path.getsize(full) > 0:
                        pb_files.append(full)
        pb_files = sorted(pb_files)

        seen_trips = set()
        for pb_path in pb_files:
            feed = gtfs_realtime_pb2.FeedMessage()
            try:
                with open(pb_path, "rb") as f:
                    feed.ParseFromString(f.read())
            except Exception:
                continue

            for ent in feed.entity:
                if not ent.HasField("trip_update"):
                    continue
                tu = ent.trip_update
                trip_id = str(tu.trip.trip_id) if tu.trip.trip_id else None
                if not trip_id or trip_id not in trip_lookup.index:
                    continue

                trip_key = trip_id
                if trip_key in seen_trips:
                    continue
                seen_trips.add(trip_key)

                row = trip_lookup.loc[trip_id]
                rsn = safe_str(row["route_short_name"], None)
                did = safe_str(row["direction_id"], "0")
                if rsn is None or rsn == NO_TRIP_LABEL:
                    continue

                for stu in tu.stop_time_update:
                    stop_id = str(stu.stop_id) if stu.stop_id else None
                    if not stop_id:
                        continue
                    delay = None
                    try:
                        if stu.HasField("arrival") and stu.arrival.delay:
                            delay = stu.arrival.delay
                        elif stu.HasField("departure") and stu.departure.delay:
                            delay = stu.departure.delay
                    except Exception:
                        pass
                    if delay is not None:
                        records.append({
                            "route_short_name": rsn,
                            "direction_id": did,
                            "stop_id": stop_id,
                            "delay_seconds": delay,
                            "year": int(date_str[:4]),
                            "hour": hour,
                        })

        print(f"    TripUpdates timme {hour:02d}: {len(seen_trips)} turer, {len(records)} delay-poster totalt")
        gc.collect()

    if not records:
        print("  Inga TripUpdates-data hittades.")
        return pd.DataFrame()

    df = pd.DataFrame(records)
    print(f"  TripUpdates totalt: {len(df):,} delay-poster")
    return df


def build_line_stop_data(routes_df, trips_df, stop_times_df, stops_df, delays_df=None):
    """Build per-line stop sequences with optional delay data.

    Returns a dict: {route_short_name: [{stop_id, stop_name, lat, lon, seq, avg_delay, n_obs}, ...]}
    """
    from config import BUS_ROUTE_TYPES

    # Filter to bus routes
    bus_routes = routes_df[routes_df["route_type"].astype(str).isin(BUS_ROUTE_TYPES)].copy()
    if bus_routes.empty:
        print("  Inga bussrutter hittades i GTFS.")
        return {}

    # Build route_id -> route_short_name
    rid_to_rsn = dict(zip(bus_routes["route_id"].astype(str), bus_routes["route_short_name"].astype(str)))

    # For each route, pick the trip with the most stops as representative
    st = stop_times_df[["trip_id", "stop_id", "stop_sequence"]].copy()
    st["stop_sequence"] = pd.to_numeric(st["stop_sequence"], errors="coerce")
    st = st.dropna(subset=["stop_sequence"])

    trips_bus = trips_df[trips_df["route_id"].astype(str).isin(rid_to_rsn)].copy()

    # Pick one representative trip per (route, direction) — the one with most stops
    trip_stop_counts = st[st["trip_id"].isin(trips_bus["trip_id"])].groupby("trip_id").size()
    trips_bus = trips_bus.copy()
    trips_bus["n_stops"] = trips_bus["trip_id"].map(trip_stop_counts).fillna(0)
    trips_bus["route_short_name"] = trips_bus["route_id"].astype(str).map(rid_to_rsn)

    best = (
        trips_bus.sort_values("n_stops", ascending=False)
        .groupby(["route_short_name", "direction_id"], as_index=False)
        .first()
    )

    stops_small = stops_df[["stop_id", "stop_name", "stop_lat", "stop_lon"]].drop_duplicates(subset=["stop_id"])

    # Build delay lookup if available
    delay_lookup = {}
    if delays_df is not None and not delays_df.empty:
        agg = delays_df.groupby(["route_short_name", "stop_id"]).agg(
            avg_delay=("delay_seconds", "mean"),
            n_obs=("delay_seconds", "size"),
        ).reset_index()
        for _, r in agg.iterrows():
            delay_lookup[(r["route_short_name"], r["stop_id"])] = {
                "avg_delay": round(r["avg_delay"], 1),
                "n_obs": int(r["n_obs"]),
            }

    result = {}
    for _, trip_row in best.iterrows():
        rsn = trip_row["route_short_name"]
        tid = trip_row["trip_id"]
        did = str(trip_row.get("direction_id", "0"))

        trip_stops = (
            st[st["trip_id"] == tid]
            .sort_values("stop_sequence")
            .merge(stops_small, on="stop_id", how="left")
        )

        stop_list = []
        for _, s in trip_stops.iterrows():
            delay_info = delay_lookup.get((rsn, s["stop_id"]), {"avg_delay": None, "n_obs": 0})
            stop_list.append({
                "stop_id": s["stop_id"],
                "stop_name": safe_str(s["stop_name"], "?"),
                "lat": float(s["stop_lat"]) if pd.notna(s["stop_lat"]) else None,
                "lon": float(s["stop_lon"]) if pd.notna(s["stop_lon"]) else None,
                "seq": int(s["stop_sequence"]),
                "avg_delay": delay_info["avg_delay"],
                "n_obs": delay_info["n_obs"],
            })

        key = rsn if did == "0" else f"{rsn}_r"
        result[key] = {
            "name": rsn,
            "direction": did,
            "stops": stop_list,
        }

    print(f"  Linjedata: {len(result)} linjeriktningar")
    return result
