"""
Performance tests & benchmarks for RepoPulse metrics.

US-54 – Establish performance testing and benchmarking.

Acceptance criteria addressed:
  1. LOC calculation on a large repo (10 000+ files)
  2. Code Churn on long history (1 000+ commits)
  3. Benchmark results documented (execution time, memory usage)
  4. Performance baseline established
  5. Tests automated with pytest
  6. Results compared against baseline in future sprints

Run **only** performance tests:
    pytest -m performance -s tests/test_performance.py

Run everything **except** performance tests:
    pytest -m "not performance"

The ``-s`` flag is recommended so that the benchmark summary table is
visible on stdout.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import string
import subprocess
import tempfile
import textwrap
import time
import tracemalloc
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pytest

from src.metrics.loc import count_loc_in_directory
from src.metrics.churn import compute_repo_churn, compute_daily_churn

# ──────────────────────────────────────────────────────────────────────
# Baselines — update these after each sprint to track regressions
# ──────────────────────────────────────────────────────────────────────
LOC_TIME_BASELINE_SEC = 60.0        # max seconds for 10 000-file LOC scan
LOC_MEMORY_BASELINE_MB = 512.0      # max peak memory (MB)
CHURN_TIME_BASELINE_SEC = 120.0     # max seconds for 1 000-commit churn
CHURN_MEMORY_BASELINE_MB = 256.0    # max peak memory (MB)

# ──────────────────────────────────────────────────────────────────────
# Synthetic file-count / commit-count knobs
# ──────────────────────────────────────────────────────────────────────
LOC_FILE_COUNT = 10_000     # AC-1: ≥ 10 000 files
CHURN_COMMIT_COUNT = int(os.getenv("CHURN_COMMIT_COUNT", "1000")) # AC-2: ≥ 1 000 commits on local, 200 on CI

# File distribution across languages
LOC_JAVA_RATIO = 0.50
LOC_PYTHON_RATIO = 0.30
LOC_TS_RATIO = 0.20

# Lines per generated file (min/max)
LINES_PER_FILE_MIN = 10
LINES_PER_FILE_MAX = 200


# ──────────────────────────────────────────────────────────────────────
# Dataclass for benchmark results
# ──────────────────────────────────────────────────────────────────────
@dataclass
class BenchmarkResult:
    """Stores timing and memory metrics for a single benchmark run."""
    name: str
    elapsed_sec: float = 0.0
    peak_memory_mb: float = 0.0
    item_count: int = 0           # files or commits
    extra: dict = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"[{self.name}] "
            f"items={self.item_count}  "
            f"time={self.elapsed_sec:.2f}s  "
            f"peak_mem={self.peak_memory_mb:.2f}MB"
        )


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _random_identifier(length: int = 12) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))


def _generate_java_file(lines: int) -> str:
    """Return a synthetic Java source file of *roughly* ``lines`` lines."""
    class_name = "Cls" + _random_identifier(8).capitalize()
    body_lines = max(lines - 6, 1)
    body = "\n".join(
        f'    private int {_random_identifier(6)} = {i};' for i in range(body_lines)
    )
    return textwrap.dedent(f"""\
        package com.generated;

        /**
         * Auto-generated Java class for benchmarking.
         */
        public class {class_name} {{
        {body}
        }}
    """)


def _generate_python_file(lines: int) -> str:
    """Return a synthetic Python source file of *roughly* ``lines`` lines."""
    body_lines = max(lines - 4, 1)
    body = "\n".join(
        f"    _{_random_identifier(6)} = {i}" for i in range(body_lines)
    )
    return textwrap.dedent(f"""\
        \"\"\"Auto-generated module for benchmarking.\"\"\"


        class {_random_identifier(8).capitalize()}:
        {body}
    """)


def _generate_ts_file(lines: int) -> str:
    """Return a synthetic TypeScript source file of *roughly* ``lines`` lines."""
    body_lines = max(lines - 4, 1)
    body = "\n".join(
        f"  private {_random_identifier(6)}: number = {i};" for i in range(body_lines)
    )
    return textwrap.dedent(f"""\
        // Auto-generated TypeScript file for benchmarking
        export class {_random_identifier(8).capitalize()} {{
        {body}
        }}
    """)


_GENERATORS = {
    ".java": _generate_java_file,
    ".py": _generate_python_file,
    ".ts": _generate_ts_file,
}


def _pick_extension() -> str:
    r = random.random()
    if r < LOC_JAVA_RATIO:
        return ".java"
    elif r < LOC_JAVA_RATIO + LOC_PYTHON_RATIO:
        return ".py"
    return ".ts"


def _run_git(args: list[str], cwd: str, extra_env: dict | None = None) -> str:
    env = {**os.environ, **(extra_env or {})}
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def large_repo(tmp_path_factory) -> str:
    """Create a temporary directory with 10 000+ synthetic source files.

    The files are distributed across multiple nested packages to
    simulate a realistic project structure.
    """
    base = str(tmp_path_factory.mktemp("large_repo"))

    # Pre-compute package directories (200 packages × ~50 files each)
    num_packages = 200
    packages = []
    for i in range(num_packages):
        depth = random.randint(1, 4)
        parts = [_random_identifier(6) for _ in range(depth)]
        pkg_dir = os.path.join(base, *parts)
        os.makedirs(pkg_dir, exist_ok=True)
        packages.append(pkg_dir)

    for file_idx in range(LOC_FILE_COUNT):
        ext = _pick_extension()
        lines = random.randint(LINES_PER_FILE_MIN, LINES_PER_FILE_MAX)
        content = _GENERATORS[ext](lines)
        pkg = packages[file_idx % num_packages]
        filename = f"File{file_idx}{ext}"
        filepath = os.path.join(pkg, filename)
        with open(filepath, "w") as f:
            f.write(content)

    return base


@pytest.fixture(scope="module")
def large_git_repo(tmp_path_factory) -> str:
    """Create a git repo with 1 000+ commits spread over 60 days.

    Each commit modifies 1-3 files with small, realistic changes so
    that ``compute_repo_churn`` and ``compute_daily_churn`` exercise
    their full codepaths.
    """
    base = str(tmp_path_factory.mktemp("churn_repo"))
    _run_git(["init"], cwd=base)
    _run_git(["config", "user.email", "bench@repopulse.test"], cwd=base)
    _run_git(["config", "user.name", "Benchmark"], cwd=base)

    # Seed a few initial files so that later commits can modify them
    seed_files = []
    for i in range(20):
        fname = f"module_{i}.py"
        fpath = os.path.join(base, fname)
        with open(fpath, "w") as f:
            f.write(f"# module {i}\nx = {i}\n")
        seed_files.append(fname)
    _run_git(["add", "."], cwd=base)
    _run_git(["commit", "-m", "seed"], cwd=base)

    # Generate CHURN_COMMIT_COUNT commits spanning 60 days
    start_date = datetime(2025, 1, 1, 8, 0, 0)
    for c in range(CHURN_COMMIT_COUNT):
        # Pick 1-3 files to modify
        num_changes = random.randint(1, 3)
        files_to_change = random.sample(seed_files, min(num_changes, len(seed_files)))
        for fname in files_to_change:
            fpath = os.path.join(base, fname)
            with open(fpath, "a") as f:
                f.write(f"line_{c}_{_random_identifier(4)} = {c}\n")
        _run_git(["add", "."], cwd=base)

        # Spread commits over the 60-day window
        commit_date = start_date + timedelta(
            seconds=int(c * (60 * 86400) / CHURN_COMMIT_COUNT)
        )
        date_str = commit_date.isoformat()
        _run_git(
            ["commit", "-m", f"commit-{c}"],
            cwd=base,
            extra_env={
                "GIT_AUTHOR_DATE": date_str,
                "GIT_COMMITTER_DATE": date_str,
            },
        )

    return base


# ──────────────────────────────────────────────────────────────────────
# LOC Performance Tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.performance
class TestLOCPerformance:
    """Benchmark ``count_loc_in_directory`` on a 10 000-file synthetic repo."""

    def test_loc_execution_time(self, large_repo: str):
        """AC-1 / AC-3: LOC scan completes within the time baseline."""
        start = time.perf_counter()
        result = count_loc_in_directory(large_repo)
        elapsed = time.perf_counter() - start

        print(f"\n{'='*60}")
        print(f"LOC BENCHMARK — Execution Time")
        print(f"  Files scanned : {result.total_files}")
        print(f"  Total LOC     : {result.total_loc}")
        print(f"  Packages      : {len(result.packages)}")
        print(f"  Elapsed       : {elapsed:.2f} s")
        print(f"  Baseline      : {LOC_TIME_BASELINE_SEC} s")
        print(f"{'='*60}")

        assert result.total_files >= LOC_FILE_COUNT, (
            f"Expected ≥{LOC_FILE_COUNT} files, got {result.total_files}"
        )
        assert elapsed < LOC_TIME_BASELINE_SEC, (
            f"LOC scan took {elapsed:.2f}s, exceeds baseline of "
            f"{LOC_TIME_BASELINE_SEC}s"
        )

    def test_loc_memory_usage(self, large_repo: str):
        """AC-3: Peak memory stays within the memory baseline."""
        tracemalloc.start()
        _ = count_loc_in_directory(large_repo)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_mb = peak / (1024 * 1024)

        print(f"\n{'='*60}")
        print(f"LOC BENCHMARK — Memory Usage")
        print(f"  Peak memory : {peak_mb:.2f} MB")
        print(f"  Baseline    : {LOC_MEMORY_BASELINE_MB} MB")
        print(f"{'='*60}")

        assert peak_mb < LOC_MEMORY_BASELINE_MB, (
            f"LOC scan used {peak_mb:.2f}MB peak, exceeds baseline of "
            f"{LOC_MEMORY_BASELINE_MB}MB"
        )

    def test_loc_throughput(self, large_repo: str):
        """AC-4: Establish throughput baseline (files / second)."""
        start = time.perf_counter()
        result = count_loc_in_directory(large_repo)
        elapsed = time.perf_counter() - start

        throughput = result.total_files / elapsed if elapsed > 0 else float("inf")

        print(f"\n{'='*60}")
        print(f"LOC BENCHMARK — Throughput")
        print(f"  Files scanned   : {result.total_files}")
        print(f"  Elapsed         : {elapsed:.2f} s")
        print(f"  Throughput      : {throughput:.0f} files/s")
        print(f"  LOC per second  : {result.total_loc / elapsed:.0f} LOC/s")
        print(f"{'='*60}")

        # Throughput should be at least 100 files/sec on any reasonable machine
        assert throughput > 100, (
            f"LOC throughput {throughput:.0f} files/s is below minimum 100 files/s"
        )


# ──────────────────────────────────────────────────────────────────────
# Code Churn Performance Tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.performance
class TestChurnPerformance:
    """Benchmark ``compute_repo_churn`` and ``compute_daily_churn``
    on a git repository with 1 000+ commits."""

    def test_churn_execution_time(self, large_git_repo: str):
        """AC-2 / AC-3: Churn analysis completes within the time baseline."""
        start = time.perf_counter()
        result = compute_repo_churn(
            large_git_repo, "2025-01-01", "2025-03-02"
        )
        elapsed = time.perf_counter() - start

        print(f"\n{'='*60}")
        print(f"CHURN BENCHMARK — Execution Time (compute_repo_churn)")
        print(f"  Added    : {result['added']}")
        print(f"  Deleted  : {result['deleted']}")
        print(f"  Modified : {result['modified']}")
        print(f"  Total    : {result['total']}")
        print(f"  Elapsed  : {elapsed:.2f} s")
        print(f"  Baseline : {CHURN_TIME_BASELINE_SEC} s")
        print(f"{'='*60}")

        assert elapsed < CHURN_TIME_BASELINE_SEC, (
            f"compute_repo_churn took {elapsed:.2f}s, exceeds baseline of "
            f"{CHURN_TIME_BASELINE_SEC}s"
        )

    def test_churn_memory_usage(self, large_git_repo: str):
        """AC-3: Peak memory for churn stays within the memory baseline."""
        tracemalloc.start()
        _ = compute_repo_churn(
            large_git_repo, "2025-01-01", "2025-03-02"
        )
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_mb = peak / (1024 * 1024)

        print(f"\n{'='*60}")
        print(f"CHURN BENCHMARK — Memory Usage")
        print(f"  Peak memory : {peak_mb:.2f} MB")
        print(f"  Baseline    : {CHURN_MEMORY_BASELINE_MB} MB")
        print(f"{'='*60}")

        assert peak_mb < CHURN_MEMORY_BASELINE_MB, (
            f"compute_repo_churn used {peak_mb:.2f}MB peak, exceeds baseline of "
            f"{CHURN_MEMORY_BASELINE_MB}MB"
        )

    def test_daily_churn_execution_time(self, large_git_repo: str):
        """AC-2: Daily churn aggregation also stays within baseline."""
        start = time.perf_counter()
        daily = compute_daily_churn(
            large_git_repo, "2025-01-01", "2025-03-02"
        )
        elapsed = time.perf_counter() - start

        num_days = len(daily)

        print(f"\n{'='*60}")
        print(f"CHURN BENCHMARK — Execution Time (compute_daily_churn)")
        print(f"  Days with commits : {num_days}")
        print(f"  Elapsed           : {elapsed:.2f} s")
        print(f"  Baseline          : {CHURN_TIME_BASELINE_SEC} s")
        print(f"{'='*60}")

        assert elapsed < CHURN_TIME_BASELINE_SEC, (
            f"compute_daily_churn took {elapsed:.2f}s, exceeds baseline of "
            f"{CHURN_TIME_BASELINE_SEC}s"
        )

    def test_churn_throughput(self, large_git_repo: str):
        """AC-4: Establish commits-per-second throughput baseline."""
        start = time.perf_counter()
        result = compute_repo_churn(
            large_git_repo, "2024-12-31", "2025-03-05"
        )
        elapsed = time.perf_counter() - start

        # Count commits via git (same wide window)
        log_output = _run_git(
            ["log", "--oneline", "--since=2024-12-31", "--until=2025-03-05"],
            cwd=large_git_repo,
        )
        num_commits = len(log_output.strip().splitlines())
        throughput = num_commits / elapsed if elapsed > 0 else float("inf")

        print(f"\n{'='*60}")
        print(f"CHURN BENCHMARK — Throughput")
        print(f"  Commits processed : {num_commits}")
        print(f"  Elapsed           : {elapsed:.2f} s")
        print(f"  Throughput        : {throughput:.1f} commits/s")
        print(f"{'='*60}")

        assert num_commits >= CHURN_COMMIT_COUNT, (
            f"Expected ≥{CHURN_COMMIT_COUNT} commits, got {num_commits}"
        )


# ──────────────────────────────────────────────────────────────────────
# Benchmark Summary (collected at end of module)
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.performance
class TestBenchmarkSummary:
    """Print a consolidated summary of all benchmark thresholds."""

    def test_print_baselines(self):
        """AC-4 / AC-6: Display current baselines for comparison."""
        print(f"\n{'='*60}")
        print(f"PERFORMANCE BASELINES (compare against future sprints)")
        print(f"-"*60)
        print(f"  LOC time limit       : {LOC_TIME_BASELINE_SEC} s")
        print(f"  LOC memory limit     : {LOC_MEMORY_BASELINE_MB} MB")
        print(f"  LOC file count       : {LOC_FILE_COUNT}")
        print(f"  Churn time limit     : {CHURN_TIME_BASELINE_SEC} s")
        print(f"  Churn memory limit   : {CHURN_MEMORY_BASELINE_MB} MB")
        print(f"  Churn commit count   : {CHURN_COMMIT_COUNT}")
        print(f"{'='*60}")
