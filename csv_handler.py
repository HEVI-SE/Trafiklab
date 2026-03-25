"""CSV import/export with deduplication for incremental data collection."""

import os
import subprocess

import pandas as pd

from config import DATA_DIR


SEGMENTS_CSV = os.path.join(DATA_DIR, "all_segments.csv")
DEADHEADS_CSV = os.path.join(DATA_DIR, "all_deadheads.csv")
OSRM_CSV = os.path.join(DATA_DIR, "osrm_cache.csv")
FETCHED_DAYS_CSV = os.path.join(DATA_DIR, "fetched_days.csv")


def push_data_to_git(message="Update cached data"):
    """Commit and push data/ CSV files to the current branch.

    Retries up to 4 times with exponential backoff on push failure.
    """
    import time as _time

    data_files = [SEGMENTS_CSV, DEADHEADS_CSV, OSRM_CSV, FETCHED_DAYS_CSV]
    existing = [f for f in data_files if os.path.exists(f)]
    if not existing:
        print("  Git push: inga data-filer att pusha.")
        return False

    try:
        # Ensure git user is configured (needed in Colab / CI environments)
        result = subprocess.run(
            ["git", "config", "user.email"], capture_output=True, text=True
        )
        if result.returncode != 0 or not result.stdout.strip():
            subprocess.run(
                ["git", "config", "user.email", "trafiklab-bot@hevi.se"],
                check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Trafiklab Bot"],
                check=True, capture_output=True,
            )

        subprocess.run(["git", "add"] + existing, check=True, capture_output=True)
        # Check if there are staged changes
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
        if result.returncode == 0:
            print("  Git push: inga ändringar att committa.")
            return True

        subprocess.run(
            ["git", "commit", "-m", message],
            check=True, capture_output=True,
        )

        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        for attempt in range(4):
            result = subprocess.run(
                ["git", "push", "-u", "origin", branch],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                print(f"  Git push: data pushad till {branch}")
                return True
            wait = 2 ** (attempt + 1)
            print(f"  Git push försök {attempt + 1} misslyckades, väntar {wait}s...")
            _time.sleep(wait)

        print(f"  Git push: kunde inte pusha efter 4 försök. Error: {result.stderr[:200]}")
        return False
    except Exception as e:
        print(f"  Git push: fel - {e}")
        return False


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


def get_fetched_days(path=None):
    """Get set of dates that have already been fully fetched.

    Reads from fetched_days.csv which is committed to git.
    Returns a set of date strings like {"2025-03-17", "2025-03-18"}.
    """
    path = path or FETCHED_DAYS_CSV
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return set()
    try:
        df = pd.read_csv(path)
        return set(df["date"].dropna().astype(str).tolist())
    except Exception:
        return set()


def mark_day_fetched(date_str, path=None):
    """Mark a date as fully fetched in the tracker CSV."""
    path = path or FETCHED_DAYS_CSV
    from datetime import datetime as _dt

    existing = get_fetched_days(path)
    if date_str in existing:
        return

    row = pd.DataFrame([{
        "date": date_str,
        "fetched_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
    }])

    if os.path.exists(path) and os.path.getsize(path) > 0:
        df = pd.read_csv(path)
        df = pd.concat([df, row], ignore_index=True)
    else:
        df = row

    df = df.drop_duplicates(subset=["date"], keep="last")
    df = df.sort_values("date").reset_index(drop=True)
    df.to_csv(path, index=False)
    print(f"  Markerad som hämtad: {date_str}")
