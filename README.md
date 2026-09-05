# Trafiklab — moved to linjelogg

**The live data pipeline for this project now lives in
[hevi-se/linjelogg](https://github.com/hevi-se/linjelogg).**

That repository now contains everything in one place:

- the same Python pipeline (`fetcher.py`, `analysis.py`, `report.py`, …),
- **all historical data** (`data/*.csv`), copied over intact,
- a nightly GitHub Action that fetches the latest day, regenerates
  `index.html` with the full history, and publishes the site
  (linjelogg.se).

The scheduled workflows in this repository have been **disabled** (they now
only run on manual `workflow_dispatch`) so the two repositories don't fetch
the same data in parallel and diverge.

This repository is kept for reference/history. New work should happen in
linjelogg.
