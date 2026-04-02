# RepoPulse

RepoPulse is a tool that analyzes GitHub repositories and computes software metrics — Lines of Code (LOC), Code Churn, and Work In Progress (WIP). It is built with FastAPI, InfluxDB, and Grafana, all running in Docker containers.

This project was built as part of SER 516 at Arizona State University.

## Attribution & Sources

**Metric Implementations & Formulas:**

The following software metrics and their implementations are based on established academic and industry standards:

- **Lines of Code (LOC)** — Standard software measurement; implementation based on language-specific parsing
  - Reference: [SLOC Definition - Wikipedia](https://en.wikipedia.org/wiki/Source_lines_of_code)
  - Tools: [CLOC](https://github.com/AlDanial/cloc), [SonarQube LOC](https://docs.sonarqube.org/latest/user-guide/metric-definitions/)

- **Code Churn** — Calculated from git history using `git show --numstat`; measure of code volatility
  - Reference: [Code Churn - Agile Metrics](https://en.wikipedia.org/wiki/Churn_(software))
  - Git Documentation: [git-show](https://git-scm.com/docs/git-show)

- **Work In Progress (WIP)** — Agile metric tracking status of work items in project management systems
  - Reference: [WIP Limits - Lean Software Development](https://en.wikipedia.org/wiki/Work_in_process)
  - Platform: [Taiga Project Management](https://www.taiga.io/) (Open Source)

- **Fog Index (Flesch-Kincaid Readability)** — Published readability formula for measuring text complexity
  - Formula: `grade = 0.39 * (words/sentences) + 11.8 * (syllables/words) - 15.59`
  - Source: Flesch, R. (1948). "A New Readability Yardstick" - Journal of Applied Psychology
  - Reference: [Flesch-Kincaid Grade Level - Wikipedia](https://en.wikipedia.org/wiki/Flesch%E2%80%93Kincaid_readability_tests)
  - Open Source Implementation: [textstat](https://github.com/shayneobrien/textstat) (Python library)

- **JavaDoc Coverage (Class & Method)** — Best practice metric for API documentation coverage
  - Reference: [JavaDoc Specification](https://www.oracle.com/technical-resources/articles/java/javadoc-tool.html)
  - Tools: [Checkstyle JavadocMethod](https://checkstyle.sourceforge.io/checks/javadoc/javadocmethod.html)

- **Taiga Integration (Adopted Work)** — Agile metric for tracking work scope changes mid-sprint
  - Platform: [Taiga API Documentation](https://docs.taiga.io/api/) (Open Source)
  - GitHub: [Taiga Backend](https://github.com/taigaio/taiga-back)

**Technology Stack (Open Source):**
- [FastAPI](https://github.com/tiangolo/fastapi) — Modern Python web framework
- [InfluxDB](https://github.com/influxdata/influxdb) — Time-series database
- [Grafana](https://github.com/grafana/grafana) — Open source visualization platform
- [Docker](https://www.docker.com/) — Container platform

All metric calculations and integrations were implemented by the development team based on documented definitions and algorithmic research.

## Prerequisites

- [Git](https://git-scm.com/)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose)

## Getting Started

1. Clone the repo and create a `.env` file:

   ```sh
   git clone https://github.com/tlthom28/SER516Group2and5.git
   cd SER516Group2and5

   # Unix / macOS
   cp .env.example .env

   # Windows PowerShell
   Copy-Item .env.example .env

   # Windows CMD
   copy .env.example .env
   ```

   Check the `.env` file for Grafana and InfluxDB credentials.

2. Build and run:

   ```sh
   # Unix / macOS
   chmod +x build.sh
   ./build.sh

   # Windows (PowerShell or CMD)
   .\build.bat
   ```

3. The build script will:
   - Check that Git and Docker are installed
   - Build all containers
   - Run the test suite with pytest
   - Start the application in the background

### Build Options

```sh
./build.sh                # full build + test + start
./build.sh --skip-tests   # build + start (skip tests)
./build.sh stop           # stop all containers
./build.sh restart        # stop, rebuild, test, start
```

## How RepoPulse Works

The main entry point is `POST /jobs`. When you submit a job, RepoPulse runs an integrated analysis pipeline in a background worker thread. A single job triggers all of the following steps automatically:

1. **Clone** the repository (shallow clone for speed, or use a local path)
2. **Compute LOC** — scans every supported file (.java, .py, .ts) and counts code lines, comment lines, blank lines, and weighted LOC
3. **Write LOC metrics to InfluxDB** — project-level, package-level, and file-level data points are written in a single batch
4. **Compute Code Churn** — walks the full git history with `git show --numstat` to calculate lines added, deleted, and modified
5. **Compute Daily Churn** — aggregates churn by date
6. **Write Churn metrics to InfluxDB** — both total and daily churn are stored

Once the metrics are in InfluxDB, the time-series query endpoints and the Grafana dashboard read from that data automatically. You do not need to call any other endpoint — the `/jobs` pipeline handles everything end to end.

The standalone endpoints (`POST /metrics/loc`, `POST /analyze`, `POST /metrics/wip`) exist for one-off queries outside the jobs pipeline.

## API Endpoints

The API runs at **http://localhost:8080** once the containers are up. Interactive Swagger docs are available at [http://localhost:8080/docs](http://localhost:8080/docs).

### Core Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Welcome message |
| GET | `/health` | Health check |
| GET | `/health/db` | InfluxDB connection check |
| POST | `/jobs` | Submit a repo analysis job (runs LOC + churn + InfluxDB writes) |
| GET | `/jobs/{job_id}` | Get job status and progress |
| GET | `/jobs/{job_id}/results` | Get structured results (LOC + Churn + metadata) |
| GET | `/workers/health` | Worker pool health (pool size, queue depth, etc.) |

### Standalone Metric Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/metrics/loc` | Compute LOC for a local repo path |
| POST | `/analyze` | Clone a repo, compute LOC + churn, store in InfluxDB |
| POST | `/metrics/wip` | Compute WIP metrics from a Taiga board |
| POST | `/metrics/fog-index` | Compute Fog Index (code readability) for Python/Markdown |
| POST | `/metrics/class-coverage` | Compute JavaDoc coverage for Java classes |
| POST | `/metrics/method-coverage` | Compute JavaDoc coverage by method visibility (public/private) |
| POST | `/metrics/taiga-metrics` | Compute adopted work and sprint metrics from Taiga |

## Using the Jobs API

`POST /jobs` is the primary way to run analysis. Pass either a `repo_url` (public GitHub URL) or a `local_path` (path to a repo inside the container).

### Submit a job

```sh
curl -s -X POST http://localhost:8080/jobs \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/SimplifyJobs/Summer2026-Internships.git"}' \
  | python3 -m json.tool
```

Or with a local path:

```sh
curl -s -X POST http://localhost:8080/jobs \
  -H "Content-Type: application/json" \
  -d '{"local_path": "/app/src"}' \
  | python3 -m json.tool
```

### Check job status

Use the `job_id` from the response to poll for progress:

```sh
curl -s http://localhost:8080/jobs/<job_id> | python3 -m json.tool
```

### Get structured results

Once the job completes, this returns LOC and churn in a clean format:

```sh
curl -s http://localhost:8080/jobs/<job_id>/results | python3 -m json.tool
```

Example response:

```json
{
  "job_id": "abc-123",
  "status": "completed",
  "metadata": {
    "repository": "https://github.com/owner/repo",
    "analysed_at": "2026-02-27T12:00:00+00:00",
    "scope": "project"
  },
  "loc": {
    "total_loc": 1250,
    "total_files": 15,
    "total_blank_lines": 180,
    "total_excluded_lines": 42,
    "total_comment_lines": 95,
    "total_weighted_loc": 1297.5
  },
  "churn": {
    "added": 142,
    "deleted": 38,
    "modified": 38,
    "total": 180
  }
}
```

| Scenario | Response |
|----------|----------|
| Job completed | Full LOC + churn + metadata |
| Job still running | `{ "status": "processing", "message": "..." }` |
| Job not found | 404 with `{ "detail": "Job not found" }` |

After a job completes, the metrics are in InfluxDB and the Grafana dashboard picks them up automatically.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `INFLUX_INIT_TOKEN` | `devtoken12345` | InfluxDB admin token |
| `INFLUX_ORG` | `RepoPulseOrg` | InfluxDB organization |
| `INFLUX_BUCKET` | `repopulse_metrics` | InfluxDB bucket |
| `INFLUX_RETENTION_DAYS` | `90` | Metric retention in days |
| `WORKER_POOL_SIZE` | `4` | Concurrent analysis workers |
| `GF_ADMIN_USER` | `admin` | Grafana admin username |
| `GF_ADMIN_PASSWORD` | `admin` | Grafana admin password |

## Services

| Container | Image | URL | Purpose |
|-----------|-------|-----|---------|
| `repopulse-dev` | local build | http://localhost:8080 | FastAPI backend (19 endpoints) |
| `repopulse-influx` | `influxdb:2.8` | http://localhost:8086 | Time-series database |
| `repopulse-grafana` | `grafana/grafana:11.5.1` | http://localhost:3000 | Dashboard visualization (3 dashboards) |

### Grafana Dashboards

Three auto-provisioned dashboards provide comprehensive insights:

1. **RepoPulse Overview** — LOC, churn, and code trends
2. **Code Quality Metrics** — Fog Index, class/method coverage (with repo & branch filters)
3. **Taiga Sprint Metrics** — Adopted work and sprint velocity (with project filter)

All dashboards update automatically when new metrics are written to InfluxDB.

## Project Structure

```
RepoPulse/
  src/
    main.py              # FastAPI entrypoint + worker pool lifecycle
    api/
      models.py          # Pydantic request/response models
      routes.py          # All API endpoints (19 endpoints total)
    core/
      config.py          # Environment variable config
      git_clone.py       # Git clone utility (shallow clone)
      influx.py          # InfluxDB client wrapper + query functions
    metrics/
      loc.py             # LOC counting logic
      churn.py           # Code churn computation
      wip.py             # WIP metrics via Taiga API
      git_history.py     # Git history traversal
    services/
      fog_index.py       # Code readability (Fog Index / Flesch-Kincaid)
      class_coverage.py  # JavaDoc coverage for Java classes
      method_coverage.py # JavaDoc coverage by method visibility
      taiga_metrics.py   # Sprint metrics & adopted work from Taiga
    worker/
      pool.py            # Thread-pool worker pool + job queue
      worker.py          # Background metric writer
  tests/                 # Pytest test suite (405+ tests, 81% coverage)
  monitoring/
    dashboards/          # Grafana dashboard JSON (with templated variables)
    provisioning/        # Grafana auto-provisioning configs
  docs/
    API.md               # Detailed API documentation
    DEPLOYMENT.md        # Deployment guide
    PERFORMANCE_BASELINE.md  # Performance benchmarks
  docker-compose.yml
  Dockerfile
  Jenkinsfile            # CI pipeline
  requirements.txt
  build.sh / build.bat   # Build automation (Unix/Windows)
  .env.example
```

## Running Tests Locally

```sh
# Create a virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate          # Unix / macOS
.venv\Scripts\Activate.ps1         # Windows PowerShell
.venv\Scripts\activate             # Windows CMD

# Install dependencies and run tests
pip install -r requirements.txt
pytest
```

To run only the performance benchmarks:

```sh
pytest -m performance -s tests/test_performance.py
```

To run everything except performance tests:

```sh
pytest -m "not performance"
```

Or just use the build script — it runs tests inside Docker automatically.

## Performance Testing

RepoPulse includes automated performance benchmarks (see `tests/test_performance.py`):

- **LOC benchmark**: generates a synthetic repository with 10,000 source files and measures execution time, peak memory, and throughput of `count_loc_in_directory`.
- **Churn benchmark**: creates a git repository with 1,000 commits and measures execution time, peak memory, and throughput of `compute_repo_churn` and `compute_daily_churn`.

Baseline results and threshold details are documented in [docs/PERFORMANCE_BASELINE.md](docs/PERFORMANCE_BASELINE.md).

## Test Coverage

RepoPulse includes a comprehensive test suite with 405+ tests covering all services and endpoints.
