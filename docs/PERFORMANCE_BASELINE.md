# Performance Baseline — RepoPulse

> **US-54** – Establish performance testing and benchmarking  
> **Date:** 2025-07-17  
> **Machine:** Apple MacBook Pro (Apple Silicon), Python 3.14, macOS  
> **Branch:** `Period-02`

---

## Overview

This document records the **initial performance baseline** for the two
primary RepoPulse metric engines:

| Engine | Input Scale | Key Metric |
|--------|-------------|------------|
| **LOC** (Lines of Code) | 10 000 synthetic source files | Elapsed time, peak memory, throughput |
| **Code Churn** | 1 000 git commits over 60 days | Elapsed time, peak memory, throughput |

Tests are automated via **pytest** (marker: `performance`) and live in
[`tests/test_performance.py`](../tests/test_performance.py).

---

## 1. LOC Calculation (`count_loc_in_directory`)

| Metric | Measured | Baseline Threshold |
|--------|----------|-------------------|
| Files scanned | **10 000** | ≥ 10 000 |
| Total LOC | ~1 017 000 | — |
| Elapsed time | **1.07 s** | < 60 s |
| Peak memory | **2.56 MB** | < 512 MB |
| Throughput | **9 371 files/s** | > 100 files/s |
| LOC / second | **953 178 LOC/s** | — |

### Observations

* The LOC engine is I/O-bound; it reads each file once and classifies
  lines in a single pass.
* Memory usage is minimal because results are accumulated into dataclass
  aggregates — no file contents are retained after counting.
* At ~9 400 files/s the engine can handle very large monorepos without
  any batching or parallelism.

---

## 2. Code Churn (`compute_repo_churn` / `compute_daily_churn`)

| Metric | Measured | Baseline Threshold |
|--------|----------|-------------------|
| Commits processed | **1 000** | ≥ 1 000 |
| Lines added (total) | ~2 018 | — |
| `compute_repo_churn` elapsed | **13.36 s** | < 120 s |
| `compute_daily_churn` elapsed | **11.88 s** | < 120 s |
| Peak memory | **0.63 MB** | < 256 MB |
| Throughput | **84.6 commits/s** | — |
| Days with activity | **61** | — |

### Observations

* Churn computation spawns one `git show --numstat` subprocess **per
  commit**, so the dominant cost is process creation overhead.
* Daily churn is slightly faster because it aggregates the same commits
  into day-level buckets without extra subprocess calls.
* Memory is negligible since each commit's output is parsed and discarded
  before moving to the next.

---

## 3. Baseline Thresholds (for CI / regression detection)

These thresholds are intentionally generous to avoid flaky failures on
slower CI hardware while still catching catastrophic regressions.

```python
LOC_TIME_BASELINE_SEC    = 60.0     # seconds (actual ~1 s)
LOC_MEMORY_BASELINE_MB   = 512.0    # MB      (actual ~3 MB)
CHURN_TIME_BASELINE_SEC  = 120.0    # seconds (actual ~13 s)
CHURN_MEMORY_BASELINE_MB = 256.0    # MB      (actual ~1 MB)
```

Future sprints should tighten these once more data points are collected.

---

## 4. How to Run

```bash
# Run only performance benchmarks (recommended: -s for stdout)
pytest -m performance -s tests/test_performance.py

# Run all tests except performance
pytest -m "not performance"

# Run everything
pytest
```

---

## 5. Updating the Baseline

1. Run the performance tests with `-s` and record the numbers.
2. Update the table above.
3. If measured values are **consistently** below a threshold by a large
   margin across multiple runs, tighten the threshold constants in
   `tests/test_performance.py`.
4. Commit the updated baseline document alongside the code changes.

---

## 6. Synthetic Test Data

| Parameter | Value |
|-----------|-------|
| LOC file count | 10 000 |
| LOC language mix | 50 % Java, 30 % Python, 20 % TypeScript |
| LOC package count | 200 nested directories (depth 1-4) |
| Lines per file | 10 – 200 (random) |
| Churn commit count | 1 000 |
| Churn time span | 60 days (2025-01-01 → 2025-03-02) |
| Churn files per commit | 1 – 3 (random, from pool of 20 seed files) |
