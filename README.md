# Trafiklab — moved to linjelogg

**The live data pipeline for this project now lives in
[hevi-se/linjelogg](https://github.com/hevi-se/linjelogg).**

That repository now contains everything in one place:

- the same Python pipeline (`fetcher.py`, `analysis.py`, `report.py`, …),
- **all historical data** (`data/*.csv`), copied over intact,
- a nightly GitHub Action that fetches the latest day, regenerates
  `index.html` with the full history, and publishes the site
  (linjelogg.se).

The scheduled workflows in this repository have been **deleted**. They were
still fetching the same KoDa data as linjelogg every day — roughly doubling
the GitHub Actions bill for duplicate data — so `daily-fetch.yml` and
`historical-fetch.yml` are gone, not just unscheduled.

> **Note:** deleting them on a branch is not enough on its own. GitHub runs
> scheduled workflows from the repository's **default branch**, so the crons
> keep firing until this change lands there (or the workflows are disabled
> from the Actions tab, or the repository is archived).

This repository is kept for reference/history. New work should happen in
linjelogg.
