# RepoPulse API Guide

The API runs at `http://localhost:8080`. All endpoints return JSON.

## Quick Access

- **Interactive API documentation:** http://localhost:8080/docs (Swagger UI)
- **Alternative documentation:** http://localhost:8080/redoc (ReDoc)
- **OpenAPI/Swagger JSON:** http://localhost:8080/openapi.json

No authentication required — all endpoints are public.

---

## Endpoints

### Health & Status

**GET `/health`** — Check if the API is working

**Curl:**
```bash
curl http://localhost:8080/health
```

**Response:**
```json
{ "status": "healthy", "service": "RepoPulse API", "version": "1.0.0" }
```

---

**GET `/health/db`** — Check if the database is working

**Curl:**
```bash
curl http://localhost:8080/health/db
```

**Response:**
```json
{ "status": "pass", "message": "Connected to InfluxDB" }
```

---

### Jobs (Async Analysis)

Submit a repo to analyze. The job runs in the background.

**POST `/jobs`** — Start a new analysis job

**Parameters:**
- `repo_url` (string, optional) — Public GitHub HTTPS URL (e.g., `https://github.com/owner/repo.git`)
- `local_path` (string, optional) — Absolute path to folder (e.g., `/path/to/repo`)

**Rules:**
- You MUST send one of them, not both
- `repo_url` must be public GitHub HTTPS URL
- `local_path` must be absolute path (starts with `/` or `C:\` on Windows)

**Curl (with GitHub URL):**
```bash
curl -X POST http://localhost:8080/jobs \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/owner/repo.git"}'
```

**Curl (with local path):**
```bash
curl -X POST http://localhost:8080/jobs \
  -H "Content-Type: application/json" \
  -d '{"local_path": "/absolute/path/to/repo"}'
```

**Response:**
```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "queued",
  "created_at": "2026-03-04T10:15:30.123456+00:00"
}
```

**GET `/jobs/{job_id}`** — Get job status and results

**Parameters:**
- `job_id` (string, required) — Job ID from POST /jobs response

**Curl:**
```bash
curl http://localhost:8080/jobs/f47ac10b-58cc-4372-a567-0e02b2c3d479
```

**Response:**
```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "completed",
  "result": {
    "total_loc": 12450,
    "total_files": 156,
    "total_blank_lines": 2100,
    "total_comment_lines": 1800
  }
}
```

---

**GET `/jobs`** — List all jobs

**Curl:**
```bash
curl http://localhost:8080/jobs
```

---

**GET `/workers/health`** — Check worker pool status

**Curl:**
```bash
curl http://localhost:8080/workers/health
```

**Response:**
```json
{
  "pool_size": 4,
  "active_workers": 2,
  "queued_jobs": 3,
  "completed_jobs": 47
}
```

---

### Metrics (Direct Analysis)

**POST `/metrics/loc`** — Count lines of code in a folder

**Parameters:**
- `repo_path` (string, required) — Absolute path to folder

**Curl:**
```bash
curl -X POST http://localhost:8080/metrics/loc \
  -H "Content-Type: application/json" \
  -d '{"repo_path": "/absolute/path/to/repo"}'
```

Returns a breakdown organized 3 ways: by package, by module, and by file.

**Response (simplified):**
```json
{
  "project_root": "/path/to/repo",
  "total_loc": 12450,
  "total_files": 156,
  "total_blank_lines": 2100,
  "total_comment_lines": 1800,
  "total_weighted_loc": 10500,
  "packages": [
    {
      "package": "com.example.app",
      "loc": 2500,
      "file_count": 25,
      "comment_lines": 400,
      "weighted_loc": 2100,
      "files": [{ "path": "Main.java", "loc": 120, ... }]
    }
  ],
  "modules": [...],
  "files": [...]
}
```

**POST `/analyze`** — Clone a GitHub repo, count lines, measure code changes, and save to database

**Parameters:**
- `repo_url` (string, required) — Public GitHub HTTPS URL
- `start_date` (string, optional) — Start date (format: `YYYY-MM-DD`, defaults to 7 days ago)
- `end_date` (string, optional) — End date (format: `YYYY-MM-DD`, defaults to today)

**Curl:**
```bash
curl -X POST http://localhost:8080/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/owner/repo.git",
    "start_date": "2026-02-01",
    "end_date": "2026-03-04"
  }'
```

**Response** — LOC data plus code churn (how many lines were added/deleted):
```json
{
  "repo_url": "https://github.com/owner/repo.git",
  "start_date": "2026-02-01",
  "end_date": "2026-03-04",
  "loc": { "total_loc": 12450, "total_files": 156, ... },
  "churn": { "added": 5200, "deleted": 3100, "modified": 3100, "total": 8300 },
  "churn_daily": {
    "2026-02-01": { "added": 150, "deleted": 80, "modified": 80, "total": 230 },
    "2026-02-02": { "added": 200, "deleted": 120, "modified": 120, "total": 320 }
  }
}
```

**What happens:**
1. Clones the repo (takes time — see timeouts below)
2. Counts all lines of code
3. Counts how many lines were added/deleted in each date
4. Saves metrics to InfluxDB
5. Returns everything

---

## Job Status

Jobs go through these stages:
- `queued` — Waiting to start
- `processing` — Currently running
- `completed` — Done
- `failed` — Error happened

---

## Error Codes & Messages

| Code | Meaning | Example |
|------|---------|----------|
| `200` | Success | Request completed successfully |
| `201` | Created | New job created successfully |
| `400` | Bad request | Missing required parameter or invalid format |
| `404` | Not found | Job ID doesn't exist |
| `422` | Unprocessable entity | repo_path doesn't exist or isn't readable |
| `500` | Server error | Internal API error (check logs) |
| `503` | Service unavailable | InfluxDB is down |

**Example error response:**
```json
{
  "detail": "Job not found: f47ac10b-58cc-4372-a567-0e02b2c3d479"
}
```

---

## Authentication

No authentication is required. All endpoints are publicly accessible.

If you need to restrict access, use a reverse proxy (Nginx, Caddy) in front of the API server.

---

## Timeouts

| Operation | Timeout |
|-----------|----------|
| Clone from GitHub | 120 seconds |
| Analyze repo | Unlimited (job runs in background) |
| Poll for job status | 30 seconds (HTTP timeout) |
| API request | 30 seconds |

If a job takes longer than 120 seconds to clone, use `local_path` instead of `repo_url`.

---

## What the API Counts

The API can count code in these languages:
- Java (.java files)
- Python (.py files)
- TypeScript (.ts files)

For each file, it reports:
- **LOC** — Lines of actual code
- **Blank lines** — Empty lines
- **Comment lines** — Lines that are just comments
- **Weighted LOC** — A score based on code complexity

---

## Postman Collection

To use Postman:

1. **Auto-import from OpenAPI:**
   - Open Postman
   - Click **Import**
   - Paste URL: `http://localhost:8080/openapi.json`
   - Click **Import**
   - All endpoints will be available to test

2. **Manual setup:**
  - Base URL: `http://localhost:8080`
   - All endpoints are in **Health & Status**, **Jobs**, and **Metrics** folders
   - No authentication headers required

---

## Code Quality Metrics

These endpoints analyze code quality metrics from GitHub repositories and write results to InfluxDB.

### **POST `/metrics/fog-index`** — Analyze readability of comments (Fog Index)

**Description:** Calculates the Flesch-Kincaid readability score for comments in source code.

**Parameters:**
- `user` (string, required) — GitHub username
- `repo` (string, required) — GitHub repository name
- `branch` (string, optional, default: "main") — Branch to analyze
- `high_threshold` (float, optional, default: 12.0) — High complexity threshold
- `low_threshold` (float, optional, default: 5.0) — Low complexity threshold
- `min_comment_words` (int, optional, default: 10) — Minimum words in comment
- `min_words` (int, optional, default: 30) — Minimum total words

**Curl:**
```bash
curl -X POST http://localhost:8080/metrics/fog-index \
  -H "Content-Type: application/json" \
  -d '{
    "user": "microsoft",
    "repo": "vscode",
    "branch": "main"
  }'
```

**Response:**
```json
{
  "repository": "microsoft/vscode",
  "branch": "main",
  "commit_sha": "abc123...",
  "analyzed_at": "2026-03-04T10:15:30.123456+00:00",
  "files": [
    {
      "score": 8.5,
      "status": "medium",
      "kind": "java",
      "path": "src/Main.java",
      "message": "Comment readability is at medium level"
    }
  ],
  "summary": {
    "file_count": 42
  }
}
```

---

### **POST `/metrics/class-coverage`** — Analyze JavaDoc coverage for classes

**Description:** Analyzes what percentage of classes have JavaDoc comments.

**Parameters:**
- `user` (string, required) — GitHub username
- `repo` (string, required) — GitHub repository name
- `branch` (string, optional, default: "main") — Branch to analyze

**Curl:**
```bash
curl -X POST http://localhost:8080/metrics/class-coverage \
  -H "Content-Type: application/json" \
  -d '{
    "user": "microsoft",
    "repo": "vscode",
    "branch": "main"
  }'
```

**Response:**
```json
{
  "repository": "microsoft/vscode",
  "branch": "main",
  "commit_sha": "abc123...",
  "analyzed_at": "2026-03-04T10:15:30.123456+00:00",
  "total_java_files": 125,
  "total_classes": 450,
  "documented_classes": 380,
  "overall_coverage_percent": 84.4,
  "files": [
    {
      "file_path": "src/Main.java",
      "total_classes": 3,
      "documented_classes": 2,
      "coverage_percent": 66.7
    }
  ]
}
```

---

### **POST `/metrics/method-coverage`** — Analyze JavaDoc coverage for methods

**Description:** Analyzes what percentage of methods have JavaDoc comments, broken down by visibility (public, protected, package, private).

**Parameters:**
- `user` (string, required) — GitHub username
- `repo` (string, required) — GitHub repository name
- `branch` (string, optional, default: "main") — Branch to analyze

**Curl:**
```bash
curl -X POST http://localhost:8080/metrics/method-coverage \
  -H "Content-Type: application/json" \
  -d '{
    "user": "microsoft",
    "repo": "vscode",
    "branch": "main"
  }'
```

**Response:**
```json
{
  "repository": "microsoft/vscode",
  "branch": "main",
  "commit_sha": "abc123...",
  "analyzed_at": "2026-03-04T10:15:30.123456+00:00",
  "public_coverage_percent": 92.1,
  "protected_coverage_percent": 78.5,
  "package_coverage_percent": 45.2,
  "private_coverage_percent": 15.0,
  "summary": {
    "public": {"coverage": 92.1, "documented": 300, "total": 326},
    "protected": {"coverage": 78.5, "documented": 200, "total": 255},
    "package": {"coverage": 45.2, "documented": 85, "total": 188},
    "private": {"coverage": 15.0, "documented": 50, "total": 334}
  }
}
```

---

### **POST `/metrics/taiga-metrics`** — Analyze Taiga sprint metrics

**Description:** Retrieves adopted work metrics from a Taiga project (user stories created during a sprint).

**Parameters:**
- `base_url` (string, optional) — Taiga instance URL (defaults to api.taiga.io)
- `slug` (string, optional) — Taiga project slug
- `taiga_id` (int, optional) — Taiga project ID (use if slug not available)

**Note:** Either `slug` or `taiga_id` must be provided.

**Curl:**
```bash
curl -X POST http://localhost:8080/metrics/taiga-metrics \
  -H "Content-Type: application/json" \
  -d '{
    "base_url": "https://api.taiga.io",
    "slug": "my-project"
  }'
```

**Response:**
```json
{
  "project_id": 12345,
  "project_slug": "my-project",
  "analyzed_at": "2026-03-04T10:15:30.123456+00:00",
  "sprints": [
    {
      "sprint_id": 1,
      "sprint_name": "Sprint 1",
      "adopted_work_count": 15,
      "created_stories": 50,
      "completed_stories": 48
    }
  ],
  "summary": {
    "sprint_count": 1
  }
}
```

---

## Data Storage

All metrics endpoints automatically write results to InfluxDB with the following measurements:

- `fog_index_score` — Fog Index scores per file
- `class_coverage` — Class JavaDoc coverage summary
- `class_coverage_by_file` — Per-file class coverage details
- `method_coverage` — Method JavaDoc coverage by visibility level
- `taiga_adopted_work` — Sprint adopted work counts

Query these measurements using Grafana dashboards or direct InfluxDB queries.

---

