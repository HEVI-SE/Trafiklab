#!/usr/bin/env python3
"""Standalone script to fetch all configured data periods.

Designed to run unattended for hours/days. Resumes automatically
from where it left off using fetched_days.csv.

Usage:
    # On any machine with Python 3.8+:
    pip install pandas requests py7zr gtfs-realtime-bindings
    python fetch_all.py

    # Run in background (survives terminal close):
    nohup python fetch_all.py > fetch.log 2>&1 &

    # Follow progress:
    tail -f fetch.log
"""

import os
import sys
import time
from datetime import datetime, timedelta

# Ensure we're in the repo root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

os.environ["KODA_API_KEY"] = os.environ.get(
    "KODA_API_KEY", "4psdkvdO9UIYsziDkp3AlnGUL5N5a4tE19N2TSja28I"
)

import pandas as pd
from config import OPERATOR_MAPPING
from fetcher import load_static_gtfs, build_trip_lookup, fetch_vehicle_positions, filter_bus_segments
from csv_handler import (
    load_segments, get_fetched_days, mark_day_fetched,
    save_segments, push_data_to_git,
)

# ---- PERIODS TO FETCH ----
MONTH_RANGES = [
    ("2025-04-01", "2025-04-30"),
    ("2025-05-01", "2025-05-31"),
    ("2025-09-01", "2025-09-30"),
    ("2025-10-01", "2025-10-31"),
    ("2025-11-01", "2025-11-30"),
    ("2026-02-01", "2026-02-28"),
    ("2026-03-01", "2026-03-28"),
]

HOURS = list(range(0, 24))


def generate_dates(month_ranges):
    dates = []
    for start_str, end_str in month_ranges:
        d = datetime.strptime(start_str, "%Y-%m-%d")
        end = datetime.strptime(end_str, "%Y-%m-%d")
        while d <= end:
            dates.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)
    return dates


def load_gtfs_for_all_periods(month_ranges):
    """Load and merge GTFS for all month ranges."""
    gtfs_dates = sorted(set(start for start, _ in month_ranges))
    all_routes, all_trips, all_stops, all_stop_times = [], [], [], []

    for date in gtfs_dates:
        try:
            r, t, s, st = load_static_gtfs(date)
            all_routes.append(r)
            all_trips.append(t)
            all_stops.append(s)
            all_stop_times.append(st)
            print(f"  GTFS {date}: {len(r)} routes, {len(t)} trips, {len(s)} stops")
        except Exception as e:
            print(f"  GTFS {date}: FEL - {e}")

    routes = pd.concat(all_routes, ignore_index=True).drop_duplicates(subset=["route_id"], keep="last")
    trips = pd.concat(all_trips, ignore_index=True).drop_duplicates(subset=["trip_id"], keep="last")
    stops = pd.concat(all_stops, ignore_index=True).drop_duplicates(subset=["stop_id"], keep="last")
    stop_times = pd.concat(all_stop_times, ignore_index=True).drop_duplicates(
        subset=["trip_id", "stop_id", "stop_sequence"], keep="last"
    )
    return routes, trips, stops, stop_times


def main():
    start_time = time.time()
    print("=" * 60)
    print(f"FETCH ALL — Started {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Generate all dates
    all_dates = generate_dates(MONTH_RANGES)
    print(f"\nTotal dagar i config: {len(all_dates)}")

    # Check already fetched
    fetched = get_fetched_days()
    to_fetch = [d for d in all_dates if d not in fetched]
    print(f"Redan hämtade: {len(fetched)}")
    print(f"Kvar att hämta: {len(to_fetch)}")

    if not to_fetch:
        print("\nAlla dagar redan hämtade!")
        return

    # Load GTFS
    print("\nLaddar GTFS...")
    routes, trips, stops, stop_times = load_gtfs_for_all_periods(MONTH_RANGES)
    operator_df = pd.DataFrame(OPERATOR_MAPPING)
    trip_lookup = build_trip_lookup(trips, routes, operator_df, stop_times, stops)
    print(f"Trip lookup: {len(trip_lookup)} trips\n")

    # Load cached segments
    cached_segments = load_segments()
    all_new_segments = []

    for idx, date in enumerate(to_fetch, 1):
        day_start = time.time()
        print(f"\n{'='*60}")
        print(f"[{idx}/{len(to_fetch)}] {date}  ({datetime.now().strftime('%H:%M:%S')})")
        print(f"{'='*60}")

        try:
            seg = fetch_vehicle_positions(date, HOURS, trip_lookup)
        except Exception as e:
            print(f"  KRITISKT FEL för {date}: {e}")
            print(f"  Fortsätter med nästa dag...")
            continue

        if seg.empty:
            print(f"  Varning: ingen data för {date}, hoppar över.")
            continue

        all_new_segments.append(seg)
        mark_day_fetched(date)

        # Save combined segments
        parts = [cached_segments] + all_new_segments if not cached_segments.empty else all_new_segments
        combined = pd.concat(parts, ignore_index=True)
        combined = filter_bus_segments(combined)
        dedup_cols = ["vehicle_id", "start_time", "end_time", "route_short_name"]
        available = [c for c in dedup_cols if c in combined.columns]
        combined = combined.drop_duplicates(subset=available, keep="last").reset_index(drop=True)
        save_segments(combined)

        # Push to git
        push_data_to_git(f"Data: {date} ({idx}/{len(to_fetch)})")

        elapsed_day = time.time() - day_start
        elapsed_total = time.time() - start_time
        days_done = idx
        days_left = len(to_fetch) - idx
        avg_per_day = elapsed_total / days_done
        eta_hours = (days_left * avg_per_day) / 3600

        print(f"\n  Dag klar på {elapsed_day/60:.1f} min")
        print(f"  Totalt: {days_done} dagar på {elapsed_total/3600:.1f}h")
        print(f"  Uppskattat kvar: {days_left} dagar ≈ {eta_hours:.1f}h")

    print(f"\n{'='*60}")
    print(f"KLART! {len(to_fetch)} dagar hämtade på {(time.time()-start_time)/3600:.1f}h")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
