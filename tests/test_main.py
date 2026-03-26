import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


# Block InfluxDB writes so test jobs don't pollute the real database.
@pytest.fixture(autouse=True)
def _no_influx_writes():
    with patch("src.core.influx.write_loc_metric"), \
         patch("src.core.influx.batch_write_loc_metrics"):
        yield


def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to RepoPulse API"}


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "RepoPulse API"
    assert data["version"] == "1.0.0"


def test_create_job_with_repo_url():
    response = client.post(
        "/jobs",
        json={"repo_url": "https://github.com/kperam1/RepoPulse"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "queued"
    assert data["repo_url"] == "https://github.com/kperam1/RepoPulse"
    assert data["local_path"] is None
    assert data["message"] == "Job queued for processing"
    assert "job_id" in data
    assert "created_at" in data


def test_create_job_with_local_path():
    response = client.post(
        "/jobs",
        json={"local_path": "/home/user/projects/my-repo"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "queued"
    assert data["local_path"] == "/home/user/projects/my-repo"
    assert data["repo_url"] is None
    assert data["message"] == "Job queued for processing"


def test_create_job_missing_fields():
    response = client.post("/jobs", json={})
    assert response.status_code == 400
    assert "detail" in response.json()


def test_create_job_both_fields_provided():
    response = client.post(
        "/jobs",
        json={
            "repo_url": "https://github.com/kperam1/RepoPulse",
            "local_path": "/home/user/projects/my-repo",
        },
    )
    assert response.status_code == 400


def test_create_job_invalid_repo_url():
    response = client.post(
        "/jobs",
        json={"repo_url": "not-a-valid-url"},
    )
    assert response.status_code == 400


def test_create_job_invalid_local_path():
    response = client.post(
        "/jobs",
        json={"local_path": "relative/path/to/repo"},
    )
    assert response.status_code == 400


def test_job_id_is_valid_uuid():
    response = client.post(
        "/jobs",
        json={"repo_url": "https://github.com/kperam1/RepoPulse"},
    )
    assert response.status_code == 201
    import uuid
    job_id = response.json()["job_id"]
    uuid.UUID(job_id)


def test_repo_url_missing_owner_or_repo():
    response = client.post(
        "/jobs",
        json={"repo_url": "https://github.com/"},
    )
    assert response.status_code == 400


def test_repo_url_not_github():
    response = client.post(
        "/jobs",
        json={"repo_url": "https://gitlab.com/owner/repo"},
    )
    assert response.status_code == 400


def test_repo_url_random_string():
    response = client.post(
        "/jobs",
        json={"repo_url": "ftp://something.com/stuff"},
    )
    assert response.status_code == 400


def test_repo_url_empty_string():
    response = client.post(
        "/jobs",
        json={"repo_url": ""},
    )
    assert response.status_code == 400


def test_repo_url_whitespace_only():
    response = client.post(
        "/jobs",
        json={"repo_url": "   "},
    )
    assert response.status_code == 400


def test_local_path_with_dotdot():
    response = client.post(
        "/jobs",
        json={"local_path": "/home/user/../etc/passwd"},
    )
    assert response.status_code == 400


def test_local_path_empty_string():
    response = client.post(
        "/jobs",
        json={"local_path": ""},
    )
    assert response.status_code == 400


def test_error_response_has_detail():
    response = client.post(
        "/jobs",
        json={"repo_url": "bad-url"},
    )
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert isinstance(data["detail"], list)
    assert len(data["detail"]) > 0


def test_openapi_docs_available():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert data["info"]["title"] == "RepoPulse API"
    assert "/health" in data["paths"]
    assert "/jobs" in data["paths"]

