"""CSV import/export with deduplication for incremental data collection."""

import os

import pandas as pd

from config import DATA_DIR


SEGMENTS_CSV = os.path.join(DATA_DIR, "all_segments.csv")
DEADHEADS_CSV = os.path.join(DATA_DIR, "all_deadheads.csv")


def save_segments(seg_df, path=None):
    """Save segments to CSV, merging with existing data and deduplicating."""
    path = path or SEGMENTS_CSV
    if seg_df.empty:
        return

    seg_df = seg_df.copy()
    seg_df["start_time"] = pd.to_datetime(seg_df["start_time"])
    seg_df["end_time"] = pd.to_datetime(seg_df["end_time"])

    if os.path.exists(path) and os.path.getsize(path) > 0:
        existing = pd.read_csv(path, parse_dates=["start_time", "end_time"])
        combined = pd.concat([existing, seg_df], ignore_index=True)
    else:
        combined = seg_df

    dedup_cols = ["vehicle_id", "start_time", "end_time", "route_short_name"]
    available_cols = [c for c in dedup_cols if c in combined.columns]
    combined = combined.drop_duplicates(subset=available_cols, keep="last")
    combined = combined.sort_values(["start_time", "vehicle_id"]).reset_index(drop=True)
    combined.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  Segment sparade: {len(combined)} rader -> {path}")
    return combined


def save_deadheads(dead_df, path=None):
    """Save deadheads to CSV, merging with existing data and deduplicating."""
    path = path or DEADHEADS_CSV
    if dead_df.empty:
        return dead_df

    dead_df = dead_df.copy()
    for col in ["deadhead_start", "deadhead_end"]:
        if col in dead_df.columns:
            dead_df[col] = pd.to_datetime(dead_df[col], errors="coerce")

    if os.path.exists(path) and os.path.getsize(path) > 0:
        existing = pd.read_csv(path, parse_dates=["deadhead_start", "deadhead_end"])
        combined = pd.concat([existing, dead_df], ignore_index=True)
    else:
        combined = dead_df

    dedup_cols = ["vehicle_id", "deadhead_start", "deadhead_end", "type"]
    available_cols = [c for c in dedup_cols if c in combined.columns]
    combined = combined.drop_duplicates(subset=available_cols, keep="last")
    combined = combined.sort_values(["deadhead_start"]).reset_index(drop=True)
    combined.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  Tomkörningar sparade: {len(combined)} rader -> {path}")
    return combined


def load_segments(path=None):
    """Load previously saved segments from CSV."""
    path = path or SEGMENTS_CSV
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame()
    df = pd.read_csv(path, parse_dates=["start_time", "end_time"])
    print(f"  Laddade {len(df)} segment från {path}")
    return df


def load_deadheads(path=None):
    """Load previously saved deadheads from CSV."""
    path = path or DEADHEADS_CSV
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame()
    df = pd.read_csv(path, parse_dates=["deadhead_start", "deadhead_end"])
    print(f"  Laddade {len(df)} tomkörningar från {path}")
    return df


def get_already_fetched_date_hours(path=None):
    """Check which date+hour combinations already exist in saved data.

    Returns a set of (date_str, hour) tuples.
    """
    path = path or SEGMENTS_CSV
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return set()

    df = pd.read_csv(path, usecols=["start_time"], parse_dates=["start_time"])
    if df.empty:
        return set()

    fetched = set()
    for ts in df["start_time"].dropna():
        fetched.add((ts.strftime("%Y-%m-%d"), ts.hour))
    return fetched
