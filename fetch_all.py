#!/usr/bin/env python3
"""Standalone script to fetch all configured data periods.

Designed to run unattended for hours/days. Resumes automatically
from where it left off using fetched_days.csv.

For each day:
1. Fetches vehicle positions (segments) — kept in memory only
2. Computes deadheads directly from segments
3. Fetches TripUpdates and saves aggregated delay stats
4. Pushes deadheads + delay stats + fetched_days to git

Segments are NOT saved to disk (too large, >100MB). Only the
useful outputs (deadheads, delay stats) are persisted.

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
from fetcher import (
    load_static_gtfs, build_trip_lookup,
    fetch_vehicle_positions, filter_bus_segments,
    fetch_trip_updates,
)
from analysis import build_observed_deadheads, filter_deadheads_osrm
from csv_handler import (
    get_fetched_days, mark_day_fetched,
    load_deadheads, save_deadheads,
    save_delay_stats, push_data_to_git,
)

# ---- PERIODS TO FETCH ----
# In GitHub Actions: only fetch yesterday (latest complete day).
# Locally: fetch all configured historical periods.
if os.environ.get("GITHUB_ACTIONS"):
    _yesterday = (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    MONTH_RANGES = [(_yesterday, _yesterday)]
    print(f"GitHub Actions: hämtar endast {_yesterday}")
else:
    MONTH_RANGES = [
        ("2025-04-01", "2025-04-30"),
        ("2025-05-01", "2025-05-31"),
        ("2025-09-01", "2025-09-30"),
        ("2025-10-01", "2025-10-31"),
        ("2025-11-01", "2025-11-30"),
        ("2026-02-01", "2026-02-28"),
        ("2026-03-01", "2026-03-28"),
    ]
    # Auto-add current month so local runs include today's data
    _today = datetime.today()
    _month_start = _today.replace(day=1).strftime("%Y-%m-%d")
    _month_end = _today.strftime("%Y-%m-%d")
    if not any(start == _month_start for start, _ in MONTH_RANGES):
        MONTH_RANGES.append((_month_start, _month_end))

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
    all_routes, all_trips, all_stops, all_stop_times, all_shapes = [], [], [], [], []

    for date in gtfs_dates:
        try:
            r, t, s, st, sh = load_static_gtfs(date)
            all_routes.append(r)
            all_trips.append(t)
            all_stops.append(s)
            all_stop_times.append(st)
            if sh is not None:
                all_shapes.append(sh)
            print(f"  GTFS {date}: {len(r)} routes, {len(t)} trips, {len(s)} stops")
        except Exception as e:
            print(f"  GTFS {date}: FEL - {e}")

    routes = pd.concat(all_routes, ignore_index=True).drop_duplicates(subset=["route_id"], keep="last")
    trips = pd.concat(all_trips, ignore_index=True).drop_duplicates(subset=["trip_id"], keep="last")
    stops = pd.concat(all_stops, ignore_index=True).drop_duplicates(subset=["stop_id"], keep="last")
    stop_times = pd.concat(all_stop_times, ignore_index=True).drop_duplicates(
        subset=["trip_id", "stop_id", "stop_sequence"], keep="last"
    )
    shapes = pd.concat(all_shapes, ignore_index=True).drop_duplicates(
        subset=["shape_id", "shape_pt_sequence"], keep="last"
    ) if all_shapes else None
    return routes, trips, stops, stop_times, shapes


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
    routes, trips, stops, stop_times, shapes = load_gtfs_for_all_periods(MONTH_RANGES)
    operator_df = pd.DataFrame(OPERATOR_MAPPING)
    trip_lookup = build_trip_lookup(trips, routes, operator_df, stop_times, stops)
    print(f"Trip lookup: {len(trip_lookup)} trips\n")

    for idx, date in enumerate(to_fetch, 1):
        day_start = time.time()
        print(f"\n{'='*60}")
        print(f"[{idx}/{len(to_fetch)}] {date}  ({datetime.now().strftime('%H:%M:%S')})")
        print(f"{'='*60}")

        # --- Fetch vehicle positions (segments in memory only) ---
        try:
            seg = fetch_vehicle_positions(date, HOURS, trip_lookup)
        except Exception as e:
            print(f"  KRITISKT FEL för {date}: {e}")
            print(f"  Fortsätter med nästa dag...")
            continue

        if seg.empty:
            print(f"  Varning: ingen data för {date}, hoppar över.")
            continue

        # --- Compute deadheads directly from segments ---
        seg = filter_bus_segments(seg)
        print(f"  Beräknar tomkörningar från {len(seg):,} segment...")
        observed = build_observed_deadheads(seg, stops)

        if not observed.empty:
            observed = filter_deadheads_osrm(observed, min_ratio=0.5, max_ratio=2.0)
            save_deadheads(observed)
            print(f"  {len(observed)} deadheads sparade")

        # --- Fetch TripUpdates and save delay stats ---
        try:
            delays = fetch_trip_updates(date, HOURS, trip_lookup)
            if not delays.empty:
                save_delay_stats(delays)
                print(f"  Förseningsdata: {len(delays):,} poster sparade")
        except Exception as e:
            print(f"  Kunde inte hämta TripUpdates: {e}")

        mark_day_fetched(date)

        # Push to git (deadheads + delay stats + fetched_days)
        push_data_to_git(f"Data: {date} ({idx}/{len(to_fetch)})")

        # Segments are not saved — free the memory
        del seg, observed
        import gc
        gc.collect()

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
