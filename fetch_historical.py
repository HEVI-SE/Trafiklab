#!/usr/bin/env python3
"""Fetches the next N unfetched days from the historical date range.

Designed to run daily via GitHub Actions. Each run picks up where the
previous one left off by checking fetched_days.csv.

Range: 2025-09-01 → 2026-03-31
Days per run: 3 (configurable via DAYS_PER_RUN env var)
"""

import os
import sys
import time
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

os.environ["KODA_API_KEY"] = os.environ.get(
    "KODA_API_KEY", "4psdkvdO9UIYsziDkp3AlnGUL5N5a4tE19N2TSja28I"
)

import pandas as pd
from config import OPERATOR_MAPPING
from fetcher import (
    load_static_gtfs, build_trip_lookup,
    fetch_vehicle_positions, filter_bus_segments,
    fetch_trip_updates,
)
from analysis import build_observed_deadheads, filter_deadheads_osrm
from csv_handler import (
    get_fetched_days, mark_day_fetched,
    save_deadheads, save_delay_stats, push_data_to_git,
)

# ---- CONFIG ----
RANGE_START = "2025-09-01"
RANGE_END   = "2026-03-31"
DAYS_PER_RUN = int(os.environ.get("DAYS_PER_RUN", "3"))
HOURS = list(range(0, 24))


def all_dates_in_range(start_str, end_str):
    dates = []
    d = datetime.strptime(start_str, "%Y-%m-%d")
    end = datetime.strptime(end_str, "%Y-%m-%d")
    while d <= end:
        dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return dates


def main():
    print("=" * 60)
    print(f"HISTORICAL FETCH — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Range: {RANGE_START} → {RANGE_END}  |  {DAYS_PER_RUN} days per run")
    print("=" * 60)

    all_dates = all_dates_in_range(RANGE_START, RANGE_END)
    fetched = get_fetched_days()
    to_fetch = [d for d in all_dates if d not in fetched]

    print(f"\nTotal i range:    {len(all_dates)} dagar")
    print(f"Redan hämtade:    {len(fetched)} dagar")
    print(f"Återstår:         {len(to_fetch)} dagar")

    if not to_fetch:
        print("\nAlla dagar i range är hämtade — du kan ta bort denna action!")
        return

    batch = to_fetch[:DAYS_PER_RUN]
    print(f"\nDenna körning:    {batch}")

    # Load GTFS for all unique months in the batch
    month_starts = sorted(set(d[:8] + "01" for d in batch))
    all_routes, all_trips, all_stops, all_stop_times, all_shapes = [], [], [], [], []
    print("\nLaddar GTFS...")
    for ms in month_starts:
        try:
            r, t, s, st, sh = load_static_gtfs(ms)
            all_routes.append(r)
            all_trips.append(t)
            all_stops.append(s)
            all_stop_times.append(st)
            if sh is not None:
                all_shapes.append(sh)
            print(f"  {ms}: {len(r)} routes, {len(t)} trips")
        except Exception as e:
            print(f"  {ms}: FEL - {e}")

    routes = pd.concat(all_routes).drop_duplicates(subset=["route_id"], keep="last")
    trips = pd.concat(all_trips).drop_duplicates(subset=["trip_id"], keep="last")
    stops = pd.concat(all_stops).drop_duplicates(subset=["stop_id"], keep="last")
    stop_times = pd.concat(all_stop_times).drop_duplicates(
        subset=["trip_id", "stop_id", "stop_sequence"], keep="last"
    )
    operator_df = pd.DataFrame(OPERATOR_MAPPING)
    trip_lookup = build_trip_lookup(trips, routes, operator_df, stop_times, stops)
    print(f"Trip lookup: {len(trip_lookup)} trips\n")

    for idx, date in enumerate(batch, 1):
        day_start = time.time()
        print(f"\n{'='*60}")
        print(f"[{idx}/{len(batch)}] {date}  ({datetime.now().strftime('%H:%M:%S')})")
        print(f"{'='*60}")

        try:
            seg = fetch_vehicle_positions(date, HOURS, trip_lookup)
        except Exception as e:
            print(f"  KRITISKT FEL för {date}: {e} — hoppar över.")
            continue

        if seg.empty:
            print(f"  Varning: ingen data för {date}, hoppar över.")
            continue

        seg = filter_bus_segments(seg)
        print(f"  Beräknar tomkörningar från {len(seg):,} segment...")
        observed = build_observed_deadheads(seg, stops)

        if not observed.empty:
            observed = filter_deadheads_osrm(observed, min_ratio=0.5, max_ratio=2.0)
            save_deadheads(observed)
            print(f"  {len(observed)} deadheads sparade")

        try:
            delays = fetch_trip_updates(date, HOURS, trip_lookup)
            if not delays.empty:
                save_delay_stats(delays)
                print(f"  Förseningsdata: {len(delays):,} poster sparade")
        except Exception as e:
            print(f"  Kunde inte hämta TripUpdates: {e}")

        mark_day_fetched(date)
        push_data_to_git(f"Historical: {date} ({len(all_dates)-len(to_fetch)+idx}/{len(all_dates)})")

        del seg, observed
        import gc; gc.collect()

        print(f"  Dag klar på {(time.time()-day_start)/60:.1f} min")

    remaining_after = len(to_fetch) - len(batch)
    print(f"\n{'='*60}")
    print(f"Batch klar! {remaining_after} dagar kvar i range.")
    if remaining_after == 0:
        print("KLART — alla dagar hämtade. Du kan nu ta bort historical-fetch.yml.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
