# RepoPulse API Guide

The API runs at `http://localhost:8080`. All endpoints return JSON.

## Quick access

- **Interactive API documentation:** http://localhost:8080/docs (Swagger UI)
- **Alternative documentation:** http://localhost:8080/redoc (ReDoc)
- **OpenAPI/Swagger JSON:** http://localhost:8080/openapi.json

No authentication required — all endpoints are public.

---

## Endpoint overview

| Group | Method | Endpoint | Description |
| --- | --- | --- | --- |
| Health | GET | `/` | Root welcome message. |
| Health | GET | `/health` | API health check. |
| Health | GET | `/health/db` | InfluxDB connectivity check. |
| Jobs | POST | `/jobs` | Submit an async analysis job (LOC + optional code quality metrics). |
| Jobs | GET | `/jobs` | List all jobs and status. |
| Jobs | GET | `/jobs/{job_id}` | Get job status/progress. |
| Jobs | GET | `/jobs/{job_id}/results` | Retrieve formatted results for completed jobs. |
| Workers | GET | `/workers/health` | Worker pool health summary. |
| LOC | POST | `/metrics/loc` | LOC analysis for a local path (no DB write). |
| Analysis | POST | `/analyze` | Clone repo, compute LOC + churn, and write to InfluxDB. |
| WIP | POST | `/metrics/wip` | Work-in-progress metrics from Taiga (kanban or sprint). |
| Time-series | GET | `/metrics/timeseries/snapshots/{repo_id}/latest` | Latest LOC snapshot. |
| Time-series | GET | `/metrics/timeseries/snapshots/{repo_id}/range` | Snapshot history for a time range. |
| Time-series | GET | `/metrics/timeseries/snapshots/{repo_id}/at/{timestamp}` | Snapshot at or before timestamp. |
| Time-series | GET | `/metrics/timeseries/snapshots/{repo_id}/commit/{commit_hash}` | Snapshots for a commit. |
| Time-series | GET | `/metrics/timeseries/commits/{repo_id}` | Commit list for time range. |
| Time-series | GET | `/metrics/timeseries/commits/{repo_id}/compare` | Compare snapshots between two commits. |
| Time-series | GET | `/metrics/timeseries/trend/{repo_id}` | LOC trend by time range. |
| Time-series | GET | `/metrics/timeseries/by-branch/{repo_id}` | Current LOC by branch. |
| Time-series | GET | `/metrics/timeseries/change/{repo_id}` | LOC delta between two timestamps. |
| Code quality | POST | `/metrics/fog-index` | Readability analysis for code comments. |
| Code quality | POST | `/metrics/class-coverage` | JavaDoc coverage for classes. |
| Code quality | POST | `/metrics/method-coverage` | JavaDoc coverage for methods. |
| Taiga | POST | `/metrics/taiga-metrics` | Adopted/found work + cycle-time data. |
| Cycle time | GET | `/cycle-time` | Cycle time metrics for Taiga user stories. |

---

## Health & status

### GET `/`

**Response**
```json
{ "message": "Welcome to RepoPulse API" }
```

### GET `/health`

**Response**
```json
{ "status": "healthy", "service": "RepoPulse API", "version": "1.0.0" }
```

### GET `/health/db`

**Response**
```json
{ "status": "pass", "message": "ready for queries and writes" }
```

---

## Jobs (async analysis)

### POST `/jobs`

Submit a background job. Provide either `repo_url` or `local_path` (not both). Optional `metrics` can include `fog_index`, `class_coverage`, `method_coverage`. Optional `start_date`/`end_date` scope churn.

**Request** (from `tests/test_job_results.py`)
```json
{
	"repo_url": "https://github.com/owner/repo",
	"metrics": ["fog_index", "method_coverage"],
	"start_date": "2026-03-01",
	"end_date": "2026-03-31"
}
```

**Response** (201 Created)
```json
{
	"job_id": "baf0d4aa-9f34-4b4e-9f79-4c1c8b35ddaa",
	"status": "queued",
	"repo_url": "https://github.com/owner/repo",
	"local_path": null,
	"metrics": ["fog_index", "method_coverage"],
	"start_date": "2026-03-01",
	"end_date": "2026-03-31",
	"created_at": "2026-03-04T10:15:30.123456+00:00",
	"message": "Job queued for processing"
}
```

### GET `/jobs/{job_id}`

**Response**
```json
{
	"job_id": "baf0d4aa-9f34-4b4e-9f79-4c1c8b35ddaa",
	"status": "completed",
	"progress": 100,
	"repo_url": "https://github.com/octocat/hello-world",
	"metrics": ["fog_index", "class_coverage"],
	"start_date": "2026-03-01",
	"end_date": "2026-03-31",
	"created_at": "2026-03-04T10:15:30.123456+00:00",
	"started_at": "2026-03-04T10:15:31.000000+00:00",
	"completed_at": "2026-03-04T10:15:55.000000+00:00",
	"result": {
		"project_root": "/tmp/repo",
		"total_loc": 14500,
		"total_files": 212,
		"total_blank_lines": 1300,
		"total_excluded_lines": 120,
		"total_comment_lines": 2300,
		"total_weighted_loc": 15650.0,
		"fog_index": { "summary": { "file_count": 42 }, "files": [] },
		"class_coverage": {
			"total_java_files": 120,
			"total_classes": 450,
			"documented_classes": 380,
			"overall_coverage_percent": 84.4,
			"files": []
		}
	},
	"error": null
}
```

### GET `/jobs/{job_id}/results`

Returns formatted LOC + churn results for completed jobs.

**Response** (from `tests/test_job_results.py`)
```json
{
	"job_id": "baf0d4aa-9f34-4b4e-9f79-4c1c8b35ddaa",
	"status": "completed",
	"metadata": {
		"repository": "https://github.com/owner/repo",
		"analysed_at": "2026-03-04T10:15:55.000000+00:00",
		"scope": "project"
	},
	"loc": {
		"total_loc": 14,
		"total_files": 2,
		"total_blank_lines": 0,
		"total_excluded_lines": 0,
		"total_comment_lines": 1,
		"total_weighted_loc": 14.0
	},
	"churn": { "added": 10, "deleted": 3, "modified": 3, "total": 13 }
}
```

### GET `/jobs`

**Response**
```json
[
	{
		"job_id": "baf0d4aa-9f34-4b4e-9f79-4c1c8b35ddaa",
		"status": "completed",
		"progress": 100,
		"repo_url": "https://github.com/octocat/hello-world",
		"metrics": ["fog_index"],
		"created_at": "2026-03-04T10:15:30.123456+00:00"
	}
]
```

### GET `/workers/health`

**Response**
```json
{
	"pool_size": 4,
	"active_workers": 1,
	"queued_jobs": 0,
	"processing_jobs": 1,
	"completed_jobs": 42,
	"failed_jobs": 2,
	"total_jobs": 45
}
```

---

## LOC metrics

### POST `/metrics/loc`

Compute LOC for a local repo path. Supports `.java`, `.py`, `.ts`.

**Request** (from `tests/test_loc.py`)
```json
{ "repo_path": "/absolute/path/to/tests/sample_files/java_project" }
```

**Response** (actual test data)
```json
{
	"project_root": "/absolute/path/to/tests/sample_files/java_project",
	"total_files": 3,
	"total_loc": 25,
	"total_blank_lines": 15,
	"total_excluded_lines": 11,
	"total_comment_lines": 0,
	"total_weighted_loc": 25.0,
	"packages": [
		{
			"package": "com.example",
			"loc": 18,
			"file_count": 2,
			"comment_lines": 0,
			"weighted_loc": 18.0
		},
		{
			"package": "com.example.util",
			"loc": 7,
			"file_count": 1,
			"comment_lines": 0,
			"weighted_loc": 7.0
		}
	],
	"modules": [
		{
			"module": "default",
			"loc": 25,
			"file_count": 3,
			"comment_lines": 0,
			"weighted_loc": 25.0
		}
	],
	"files": [
		{
			"path": "src/com/example/Calculator.java",
			"total_lines": 26,
			"loc": 12,
			"blank_lines": 8,
			"excluded_lines": 6,
			"comment_lines": 0,
			"weighted_loc": 12.0
		},
		{
			"path": "src/com/example/Main.java",
			"total_lines": 11,
			"loc": 6,
			"blank_lines": 3,
			"excluded_lines": 2,
			"comment_lines": 0,
			"weighted_loc": 6.0
		},
		{
			"path": "src/com/example/util/StringHelper.java",
			"total_lines": 14,
			"loc": 7,
			"blank_lines": 4,
			"excluded_lines": 3,
			"comment_lines": 0,
			"weighted_loc": 7.0
		}
	]
}
```

---

## Repository analysis

### POST `/analyze`

Clones a repo, computes LOC + churn, writes to InfluxDB, and returns results.

**Request** (from `tests/test_analyze.py`)
```json
{
	"repo_url": "https://github.com/test/repo",
	"start_date": "2000-01-01",
	"end_date": "2100-01-01"
}
```

**Response** (actual test data)
```json
{
	"repo_url": "https://github.com/test/repo",
	"start_date": "2000-01-01",
	"end_date": "2100-01-01",
	"loc": {
		"project_root": "/tmp/repo",
		"total_loc": 2,
		"total_files": 1,
		"total_blank_lines": 0,
		"total_excluded_lines": 0,
		"total_comment_lines": 0,
		"total_weighted_loc": 2.0,
		"packages": [],
		"modules": [],
		"files": [
			{
				"path": "hello.py",
				"total_lines": 2,
				"loc": 2,
				"blank_lines": 0,
				"excluded_lines": 0,
				"comment_lines": 0,
				"weighted_loc": 2.0
			}
		]
	},
	"churn": { "added": 2, "deleted": 0, "modified": 0, "total": 2 },
	"churn_daily": {}
}
```

---

## WIP metrics

### POST `/metrics/wip`

Compute WIP for a Taiga project. Provide either `taiga_url` (scrum) or `kanban_url` (kanban). Optional `recent_days` limits to most recent sprints.

**Request (kanban)** (from `tests/test_wip_api.py`)
```json
{
	"kanban_url": "https://taiga.io/project/demo-project",
	"recent_days": 7
}
```

**Response (kanban)** (actual test data)
```json
{
	"project_id": 10,
	"project_slug": "demo-project",
	"sprints_count": 1,
	"sprints": [
		{
			"project_id": 10,
			"project_slug": "demo-project",
			"sprint_id": null,
			"sprint_name": "kanban",
			"date_range_start": "2026-03-01",
			"date_range_end": "2026-03-03",
			"daily_wip": [
				{ "date": "2026-03-01", "wip_count": 3, "backlog_count": 2, "done_count": 1 },
				{ "date": "2026-03-02", "wip_count": 4, "backlog_count": 1, "done_count": 2 }
			]
		}
	]
}
```

**Request (scrum)** (from `tests/test_wip_api.py`)
```json
{ "taiga_url": "https://taiga.io/project/team-space", "recent_days": 30 }
```

**Response (scrum)** (actual test data)
```json
{
	"project_id": 20,
	"project_slug": "team-space",
	"sprints_count": 2,
	"sprints": [
		{
			"project_id": 20,
			"project_slug": "team-space",
			"sprint_id": 1,
			"sprint_name": "Sprint 1",
			"date_range_start": "2026-03-01",
			"date_range_end": "2026-03-07",
			"daily_wip": [
				{ "date": "2026-03-01", "wip_count": 2, "backlog_count": 3, "done_count": 1 }
			]
		},
		{
			"project_id": 20,
			"project_slug": "team-space",
			"sprint_id": 2,
			"sprint_name": "Sprint 2",
			"date_range_start": "2026-03-08",
			"date_range_end": "2026-03-14",
			"daily_wip": [
				{ "date": "2026-03-08", "wip_count": 1, "backlog_count": 2, "done_count": 4 }
			]
		}
	]
}
```

---

## Time-series LOC snapshots

These endpoints read from the `timeseries_snapshot` measurement.

### GET `/metrics/timeseries/snapshots/{repo_id}/latest?granularity=project`

**Response** (from `tests/test_routes_timeseries.py`)
```json
{
	"repo_id": "r1",
	"repo_name": "repo",
	"latest_snapshot": {
		"timestamp": "2026-01-01T00:00:00Z",
		"repo_id": "r1",
		"repo_name": "repo",
		"commit_hash": "abc",
		"branch": "main",
		"granularity": "project",
		"metrics": { "total_loc": 100, "code_loc": 80, "comment_loc": 10, "blank_loc": 10 },
		"file_path": null,
		"package_name": null
	}
}
```

### GET `/metrics/timeseries/snapshots/{repo_id}/range`

**Example** (from `tests/test_routes_timeseries.py`)
`/metrics/timeseries/snapshots/r1/range?start_time=2026-01-01T00:00:00Z&end_time=2026-02-01T00:00:00Z&granularity=project`

**Response** (actual test data)
```json
{
	"repo_id": "r1",
	"repo_name": "repo",
	"granularity": "project",
	"start_time": "2026-01-01T00:00:00Z",
	"end_time": "2026-02-01T00:00:00Z",
	"snapshots": [
		{
			"timestamp": "2026-01-01T00:00:00Z",
			"repo_id": "r1",
			"repo_name": "repo",
			"commit_hash": "a",
			"branch": "main",
			"granularity": "project",
			"metrics": { "total_loc": 100, "code_loc": 80, "comment_loc": 10, "blank_loc": 10 },
			"file_path": null,
			"package_name": null
		}
	],
	"count": 1
}
```

### GET `/metrics/timeseries/snapshots/{repo_id}/at/{timestamp}`

**Response** (from `tests/test_routes_timeseries.py`)
```json
{
	"timestamp": "2026-01-01T00:00:00Z",
	"repo_id": "r1",
	"repo_name": "repo",
	"commit_hash": "a",
	"branch": "main",
	"granularity": "project",
	"metrics": { "total_loc": 100, "code_loc": 80, "comment_loc": 10, "blank_loc": 10 },
	"file_path": null,
	"package_name": null
}
```

### GET `/metrics/timeseries/snapshots/{repo_id}/commit/{commit_hash}`

**Response** (from `tests/test_routes_timeseries.py`)
```json
{
	"repo_id": "r1",
	"repo_name": "repo",
	"commit_hash": "abc123",
	"snapshots": [
		{
			"timestamp": "2026-01-01T00:00:00Z",
			"repo_id": "r1",
			"repo_name": "repo",
			"commit_hash": "abc123",
			"branch": "main",
			"granularity": "project",
			"metrics": { "total_loc": 100, "code_loc": 80, "comment_loc": 10, "blank_loc": 10 },
			"file_path": null,
			"package_name": null
		}
	],
	"count": 1
}
```

### GET `/metrics/timeseries/commits/{repo_id}`

**Response** (from `tests/test_routes_timeseries.py`)
```json
{
	"repo_id": "r1",
	"start_time": "2026-01-01T00:00:00Z",
	"end_time": "2026-02-01T00:00:00Z",
	"branch": "main",
	"commits": [
		{ "commit_hash": "abc", "branch": "main", "time": "2026-01-15T00:00:00Z" }
	],
	"count": 1
}
```

### GET `/metrics/timeseries/commits/{repo_id}/compare`

**Example** (from `tests/test_routes_timeseries.py`)
`/metrics/timeseries/commits/r1/compare?commit1=a&commit2=b&granularity=project`

**Response** (actual test data)
```json
{
	"repo_id": "r1",
	"commit1": "a",
	"commit2": "b",
	"granularity": "project",
	"snapshots_commit1": [],
	"snapshots_commit2": []
}
```

### GET `/metrics/timeseries/trend/{repo_id}`

**Response** (from `tests/test_routes_timeseries.py`)
```json
{
	"repo_id": "r1",
	"granularity": "project",
	"start_time": "2026-01-01T00:00:00Z",
	"end_time": "2026-02-01T00:00:00Z",
	"trend": [
		{ "time": "2026-01-01T00:00:00Z", "total_loc": 100 }
	],
	"count": 1
}
```

### GET `/metrics/timeseries/by-branch/{repo_id}`

**Response** (from `tests/test_routes_timeseries.py`)
```json
{
	"repo_id": "r1",
	"branches": [
		{ "branch": "main", "total_loc": 500, "updated_at": "2026-01-01T00:00:00Z" }
	],
	"count": 1
}
```

### GET `/metrics/timeseries/change/{repo_id}`

**Example** (from `tests/test_routes_timeseries.py`)
`/metrics/timeseries/change/r1?timestamp1=2026-01-01T00:00:00Z&timestamp2=2026-02-01T00:00:00Z&granularity=project`

**Response** (actual test data)
```json
{
	"repo_id": "r1",
	"granularity": "project",
	"timestamp1": "2026-01-01T00:00:00Z",
	"timestamp2": "2026-02-01T00:00:00Z",
	"loc_at_time1": 1000,
	"loc_at_time2": 1050,
	"absolute_change": 50,
	"percent_change": 5.0
}
```

---

## Code quality metrics

### POST `/metrics/fog-index`

Analyzes code comments using Flesch-Kincaid readability scoring.

**Request** (from `tests/test_fog_index_service.py`)
```json
{ "user": "microsoft", "repo": "vscode", "branch": "main" }
```

**Response** (actual test data)
```json
{
	"repository": "microsoft/vscode",
	"branch": "main",
	"commit_sha": "abc123def456",
	"analyzed_at": "2026-03-04T10:15:30+00:00",
	"files": [
		{
			"score": -2.035,
			"status": "low",
			"kind": "python",
			"path": "test.py",
			"message": "Comment readability is at low level"
		}
	],
	"summary": { "file_count": 1 }
}
```

### POST `/metrics/class-coverage`

Analyzes JavaDoc coverage for Java classes.

**Request** (from `tests/test_class_coverage_service.py`)
```json
{ "user": "microsoft", "repo": "vscode", "branch": "main" }
```

**Response** (actual test data)
```json
{
	"repository": "microsoft/vscode",
	"branch": "main",
	"commit_sha": "abc123def456",
	"analyzed_at": "2026-03-04T10:15:30+00:00",
	"total_java_files": 1,
	"total_classes": 3,
	"documented_classes": 2,
	"overall_coverage_percent": 66.7,
	"files": [
		{
			"file_path": "Example.java",
			"total_classes": 3,
			"documented_classes": 2,
			"coverage_percent": 66.7
		}
	]
}
```

### POST `/metrics/method-coverage`

Analyzes JavaDoc coverage for methods by visibility level (public, protected, private, default).

**Request** (from `tests/test_method_coverage_service.py`)
```json
{ "user": "microsoft", "repo": "vscode", "branch": "main" }
```

**Response** (actual test data)
```json
{
	"repository": "microsoft/vscode",
	"branch": "main",
	"commit_sha": "abc123def456",
	"analyzed_at": "2026-03-04T10:15:30+00:00",
	"public_coverage_percent": 50.0,
	"protected_coverage_percent": 100.0,
	"package_coverage_percent": 0.0,
	"private_coverage_percent": 100.0,
	"summary": {
		"public": { "coverage": 50.0, "documented": 1, "total": 2 },
		"protected": { "coverage": 100.0, "documented": 1, "total": 1 },
		"default": { "coverage": 0.0, "documented": 0, "total": 0 },
		"private": { "coverage": 100.0, "documented": 1, "total": 1 }
	}
}
```

---

## Taiga metrics

### POST `/metrics/taiga-metrics`

**Request**
```json
{ "slug": "demo-project", "base_url": "https://api.taiga.io/api/v1" }
```

**Response**
```json
{
	"project_id": 1,
	"project_slug": "demo-project",
	"analyzed_at": "2026-03-04T10:15:30+00:00",
	"sprints": [
		{
			"sprint_id": 10,
			"sprint_name": "Sprint 1",
			"adopted_work_count": 3,
			"found_work_count": 1,
			"created_stories": 8,
			"completed_stories": 5
		}
	],
	"summary": {
		"sprint_count": 1,
		"cycle_time_story_count": 2,
		"average_cycle_time_hours": 34.5
	}
}
```

---

## Cycle time

### GET `/cycle-time`

**Example** (from `tests/test_cycle_time_api.py`)
`/cycle-time?start=2026-03-01&end=2026-03-10&slug=demo-project`

**Response** (actual test data)
```json
{
	"project_id": 10,
	"project_slug": "demo-project",
	"start_date": "2026-03-01",
	"end_date": "2026-03-10",
	"story_cycle_times": [
		{ "story_id": 1, "cycle_time_hours": 48.0 }
	],
	"summary": { "average": 48.0, "median": 48.0, "min": 48.0, "max": 48.0 }
}
```

**Validation errors:**
- Invalid date format: `400 Bad Request` with message "Invalid date format"
- Start date after end date: `400 Bad Request` with message containing "start"
- Missing slug or taiga_id: `400 Bad Request` with message "Missing 'slug' or 'taiga_id' parameter"

---

## Job status glossary

Jobs go through these stages:
- `queued` — waiting to start
- `processing` — running now
- `completed` — finished
- `failed` — error occurred

---

## Error codes

| Code | Meaning | Example |
| --- | --- | --- |
| `200` | Success | Request completed successfully |
| `201` | Created | New job created successfully |
| `400` | Bad request | Missing or invalid parameter |
| `404` | Not found | Job ID doesn't exist |
| `422` | Unprocessable entity | Invalid payload (validation) |
| `500` | Server error | Internal API error |
| `503` | Service unavailable | InfluxDB is down |

---

## Authentication

No authentication is required. All endpoints are publicly accessible.

---

## Timeouts

| Operation | Timeout |
| --- | --- |
| Clone from GitHub | 120 seconds |
| Analyze repo | Unlimited (job runs in background) |
| API request | 30 seconds |

If a job takes longer than 120 seconds to clone, use `local_path` instead of `repo_url`.

---

## Postman collection

1. Open Postman → **Import**
2. Paste `http://localhost:8080/openapi.json`
3. Import and use the generated collection


The API runs at `http://localhost:8080`. All endpoints return JSON.
