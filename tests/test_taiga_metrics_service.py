"""
Comprehensive tests for taiga_metrics service module.
Tests authentication, project structure retrieval, and adopted work calculation.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone
from src.services.taiga_metrics import (
    auth,
    get_structure,
    get_adopted_work,
    get_transition_history,
    CYCLE_TIME_START_STATES,
    CYCLE_TIME_END_STATES,
    get_cycle_time_state_boundaries,
    parse_utc,
)


class TestTaigaAuth:
    """Test Taiga API authentication functionality."""
    
    def test_auth_success_with_default_url(self):
        """Test successful authentication with default Taiga API URL"""
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            result = auth('')
            
            assert result["status"] == "success"
            assert "200" in result["message"]
            mock_get.assert_called_once_with("https://api.taiga.io/api/v1/projects")
    
    def test_auth_success_with_custom_url(self):
        """Test successful authentication with custom Taiga URL"""
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            result = auth('https://custom.taiga.io/api/v1')
            
            assert result["status"] == "success"
            mock_get.assert_called_once_with("https://custom.taiga.io/api/v1/projects")
    
    def test_auth_failure_404(self):
        """Test authentication failure with 404 response"""
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 404
            mock_get.return_value = mock_response
            
            result = auth('')
            
            assert result["status"] == "error"
            assert "404" in result["message"]
            assert "did not authenticate" in result["message"]
    
    def test_auth_failure_500(self):
        """Test authentication failure with 500 response"""
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 500
            mock_get.return_value = mock_response
            
            result = auth('')
            
            assert result["status"] == "success"  # 500 is not 404, treated as success
            assert "500" in result["message"]
    
    def test_auth_request_exception(self):
        """Test authentication failure due to network exception"""
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            mock_get.side_effect = __import__('requests').exceptions.RequestException("Network error")
            
            result = auth('')
            
            assert result["status"] == "error"
            assert "Request exception" in result["message"]


class TestTaigaGetStructure:
    """Test project structure retrieval from Taiga API."""
    
    def test_get_structure_by_slug(self):
        """Test retrieving project structure using slug"""
        project_data = {
            "id": 1,
            "name": "Test Project",
            "created_date": "2024-01-01T00:00:00Z"
        }
        sprint_data = [
            {
                "id": 10,
                "name": "Sprint 1",
                "estimated_start": "2024-01-01",
                "estimated_finish": "2024-01-14"
            }
        ]
        user_story_data = [
            {
                "id": 100,
                "subject": "Feature 1",
                "milestone": 10,
                "created_date": "2024-01-05T00:00:00Z"
            }
        ]
        task_data = [
            {
                "id": 1000,
                "subject": "Task 1",
                "user_story": 100,
                "created_date": "2024-01-05T00:00:00Z"
            }
        ]
        
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            responses = [
                Mock(status_code=200, json=lambda: project_data),
                Mock(status_code=200, json=lambda: sprint_data),
                Mock(status_code=200, json=lambda: user_story_data),
                Mock(status_code=200, json=lambda: task_data),
            ]
            mock_get.side_effect = responses
            
            result = get_structure('', 'test-project', -1)
            
            assert isinstance(result, dict)
            assert result["project_name"] == "Test Project"
            assert result["project_id"] == 1
            assert len(result["project_sprints"]) == 1
            assert result["project_sprints"][0]["sprint_name"] == "Sprint 1"
    
    def test_get_structure_by_id(self):
        """Test retrieving project structure using project ID"""
        project_data = {
            "id": 5,
            "name": "Existing Project",
            "created_date": "2023-06-01T00:00:00Z"
        }
        
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            responses = [
                Mock(status_code=200, json=lambda: project_data),
                Mock(status_code=200, json=lambda: []),
                Mock(status_code=200, json=lambda: []),
                Mock(status_code=200, json=lambda: []),
            ]
            mock_get.side_effect = responses
            
            result = get_structure('', '', 5)
            
            assert result["project_id"] == 5
            assert result["project_name"] == "Existing Project"
    
    def test_get_structure_project_not_found(self):
        """Test handling of project not found (404)"""
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            mock_get.return_value = Mock(status_code=404)
            
            result = get_structure('', '', 999)
            
            assert isinstance(result, str)
            assert "404" in result
            assert "Error" in result
    
    def test_get_structure_sprint_error(self):
        """Test handling of sprint retrieval error"""
        project_data = {"id": 1, "name": "Project", "created_date": "2024-01-01T00:00:00Z"}
        
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            responses = [
                Mock(status_code=200, json=lambda: project_data),
                Mock(status_code=500),
            ]
            mock_get.side_effect = responses
            
            result = get_structure('', '', 1)
            
            assert isinstance(result, str)
            assert "Sprints" in result
            assert "500" in result
    
    def test_get_structure_request_exception(self):
        """Test handling of network request exception"""
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            mock_get.side_effect = __import__('requests').exceptions.RequestException()
            
            result = get_structure('', '', 1)
            
            assert isinstance(result, dict)
            assert result.get("status") == "error"
            assert "Request exception" in result.get("message", "")
    
    def test_get_structure_groups_tasks_by_story(self):
        """Test that tasks are correctly grouped by user story"""
        project_data = {
            "id": 1,
            "name": "Test",
            "created_date": "2024-01-01T00:00:00Z"
        }
        sprint_data = [{"id": 10, "name": "S1", "estimated_start": "2024-01-01", "estimated_finish": "2024-01-14"}]
        user_story_data = [
            {"id": 100, "subject": "Story 1", "milestone": 10, "created_date": "2024-01-05T00:00:00Z"}
        ]
        task_data = [
            {"id": 1000, "subject": "Task 1", "user_story": 100, "created_date": "2024-01-05T00:00:00Z"},
            {"id": 1001, "subject": "Task 2", "user_story": 100, "created_date": "2024-01-06T00:00:00Z"},
            {"id": 1002, "subject": "Task 3", "user_story": 200, "created_date": "2024-01-07T00:00:00Z"},
        ]
        
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            responses = [
                Mock(status_code=200, json=lambda: project_data),
                Mock(status_code=200, json=lambda: sprint_data),
                Mock(status_code=200, json=lambda: user_story_data),
                Mock(status_code=200, json=lambda: task_data),
            ]
            mock_get.side_effect = responses
            
            result = get_structure('', '', 1)
            
            tasks = result["project_sprints"][0]["sprint_user_stories"][0]["user_story_tasks"]
            assert len(tasks) == 2
            assert tasks[0]["task_name"] == "Task 1"
            assert tasks[1]["task_name"] == "Task 2"


class TestTaigaGetAdoptedWork:
    """Test adopted work calculation from Taiga metrics."""
    
    def test_get_adopted_work_calculation(self):
        """Test that adopted work is correctly calculated (stories after sprint start)"""
        project_data = {
            "id": 1,
            "name": "Test Project",
            "created_date": "2024-01-01T00:00:00Z"
        }
        sprint_data = [
            {
                "id": 10,
                "name": "Sprint 1",
                "estimated_start": "2024-01-08T00:00:00Z",
                "estimated_finish": "2024-01-21T00:00:00Z"
            }
        ]
        user_story_data = [
            {
                "id": 100,
                "subject": "Story Created Before Sprint",
                "milestone": 10,
                "created_date": "2024-01-05T00:00:00Z"
            },
            {
                "id": 101,
                "subject": "Story Created During Sprint",
                "milestone": 10,
                "created_date": "2024-01-10T00:00:00Z"
            },
            {
                "id": 102,
                "subject": "Story Created After Sprint",
                "milestone": 10,
                "created_date": "2024-01-25T00:00:00Z"
            }
        ]
        
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            responses = [
                Mock(status_code=200, json=lambda: project_data),
                Mock(status_code=200, json=lambda: sprint_data),
                Mock(status_code=200, json=lambda: user_story_data),
                Mock(status_code=200, json=lambda: []),
            ]
            mock_get.side_effect = responses
            
            result = get_adopted_work('', '', -1)
            
            assert result["status"] == "success"
            assert len(result["sprints"]) == 1
            adopted_count = result["sprints"][0]["adopted_count"]
            adopted_stories = result["sprints"][0]["adopted_stories"]
            
            # Stories created after sprint start (2 out of 3)
            assert adopted_count == 2
            assert len(adopted_stories) == 2
    
    def test_get_adopted_work_no_stories(self):
        """Test adopted work calculation with no user stories"""
        project_data = {
            "id": 1,
            "name": "Test Project",
            "created_date": "2024-01-01T00:00:00Z"
        }
        sprint_data = [
            {
                "id": 10,
                "name": "Sprint 1",
                "estimated_start": "2024-01-08T00:00:00Z",
                "estimated_finish": "2024-01-21T00:00:00Z"
            }
        ]
        
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            responses = [
                Mock(status_code=200, json=lambda: project_data),
                Mock(status_code=200, json=lambda: sprint_data),
                Mock(status_code=200, json=lambda: []),
                Mock(status_code=200, json=lambda: []),
            ]
            mock_get.side_effect = responses
            
            result = get_adopted_work('', '', -1)
            
            assert result["status"] == "success"
            assert result["sprints"][0]["adopted_count"] == 0
            assert len(result["sprints"][0]["adopted_stories"]) == 0
    
    def test_get_adopted_work_invalid_project(self):
        """Test adopted work when project retrieval fails"""
        with patch('src.services.taiga_metrics.get_structure') as mock_get:
            mock_get.return_value = "Error: 404"
            
            result = get_adopted_work('', '', -1)
            
            assert result["status"] == "error"
            assert "404" in result["message"]
    
    def test_get_adopted_work_no_valid_dates(self):
        """Test adopted work with stories that have empty created_date"""
        project_data = {
            "id": 1,
            "name": "Test Project",
            "created_date": "2024-01-01T00:00:00Z"
        }
        sprint_data = [
            {
                "id": 10,
                "name": "Sprint 1",
                "estimated_start": "2024-01-08T00:00:00Z",
                "estimated_finish": "2024-01-21T00:00:00Z"
            }
        ]
        user_story_data = [
            {
                "id": 100,
                "subject": "Story with Valid Date",
                "milestone": 10,
                "created_date": "2024-01-10T00:00:00Z"
            },
            {
                "id": 101,
                "subject": "Story Missing Date",
                "milestone": 10,
                "created_date": ""
            }
        ]
        
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            responses = [
                Mock(status_code=200, json=lambda: project_data),
                Mock(status_code=200, json=lambda: sprint_data),
                Mock(status_code=200, json=lambda: user_story_data),
                Mock(status_code=200, json=lambda: []),
            ]
            mock_get.side_effect = responses
            
            result = get_adopted_work('', '', -1)
            
            # Should handle mixed valid/invalid dates, only count valid ones
            assert result["status"] == "success"
            assert result["sprints"][0]["adopted_count"] == 1
    
    def test_get_adopted_work_multiple_sprints(self):
        """Test adopted work calculation across multiple sprints"""
        project_data = {
            "id": 1,
            "name": "Test Project",
            "created_date": "2024-01-01T00:00:00Z"
        }
        sprint_data = [
            {
                "id": 10,
                "name": "Sprint 1",
                "estimated_start": "2024-01-08T00:00:00Z",
                "estimated_finish": "2024-01-21T00:00:00Z"
            },
            {
                "id": 11,
                "name": "Sprint 2",
                "estimated_start": "2024-01-22T00:00:00Z",
                "estimated_finish": "2024-02-04T00:00:00Z"
            }
        ]
        user_story_data = [
            {"id": 100, "subject": "S1 Story", "milestone": 10, "created_date": "2024-01-10T00:00:00Z"},
            {"id": 101, "subject": "S2 Story", "milestone": 11, "created_date": "2024-01-25T00:00:00Z"}
        ]
        
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            responses = [
                Mock(status_code=200, json=lambda: project_data),
                Mock(status_code=200, json=lambda: sprint_data),
                Mock(status_code=200, json=lambda: user_story_data),
                Mock(status_code=200, json=lambda: []),
            ]
            mock_get.side_effect = responses
            
            result = get_adopted_work('', '', -1)
            
            assert result["status"] == "success"
            assert len(result["sprints"]) == 2
            assert result["sprints"][0]["adopted_count"] == 1
            assert result["sprints"][1]["adopted_count"] == 1


class TestTaigaTransitionHistory:
    """Test transition history retrieval for user stories."""

    def test_get_transition_history_success(self):
        project_data = {"id": 1, "slug": "test-project"}
        user_story_data = [
            {"id": 100, "subject": "Story 1"},
            {"id": 101, "subject": "Story 2"},
        ]
        story_1_history = [
            {
                "created_at": "2024-01-10T10:00:00Z",
                "values_diff": {"status": [1, "Backlog", 2, "In Progress"]},
            },
            {
                "created_at": "2024-01-12T10:00:00Z",
                "values_diff": {"status": ["In Progress", "Done"]},
            },
        ]
        story_2_history = [
            {
                "created_at": "2024-01-11T09:00:00Z",
                "values_diff": {"status": ["Backlog", "Ready"]},
            }
        ]

        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            mock_get.side_effect = [
                Mock(status_code=200, json=lambda: project_data),
                Mock(status_code=200, json=lambda: user_story_data),
                Mock(status_code=200, json=lambda: story_1_history),
                Mock(status_code=200, json=lambda: story_2_history),
            ]

            result = get_transition_history('', 'test-project', -1, sprint_id=10)

            assert result["status"] == "success"
            assert result["project_id"] == 1
            assert result["project_slug"] == "test-project"
            assert result["sprint_id"] == 10
            assert len(result["stories"]) == 2
            assert len(result["stories"][0]["transitions"]) == 2
            assert result["stories"][0]["transitions"][0]["from_status"] == "Backlog"
            assert result["stories"][0]["transitions"][0]["to_status"] == "In Progress"

            user_stories_call = mock_get.call_args_list[1].args[0]
            assert "milestone=10" in user_stories_call

    def test_get_transition_history_ignores_non_status_events(self):
        project_data = {"id": 1, "slug": "test-project"}
        user_story_data = [{"id": 100, "subject": "Story 1"}]
        history_events = [
            {
                "created_at": "2024-01-10T10:00:00Z",
                "values_diff": {"subject": ["Old", "New"]},
            },
            {
                "created_at": "2024-01-11T10:00:00Z",
                "values_diff": {"status": ["Backlog"]},
            },
        ]

        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            mock_get.side_effect = [
                Mock(status_code=200, json=lambda: project_data),
                Mock(status_code=200, json=lambda: user_story_data),
                Mock(status_code=200, json=lambda: history_events),
            ]

            result = get_transition_history('', 'test-project', -1)

            assert result["status"] == "success"
            assert len(result["stories"]) == 1
            assert result["stories"][0]["transitions"] == []

    def test_get_transition_history_project_error(self):
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            mock_get.return_value = Mock(status_code=404)

            result = get_transition_history('', 'missing-project', -1)

            assert result["status"] == "error"
            assert "Project" in result["message"]
            assert "404" in result["message"]

    def test_get_transition_history_request_exception(self):
        with patch('src.services.taiga_metrics.requests.get') as mock_get:
            mock_get.side_effect = __import__('requests').exceptions.RequestException()

            result = get_transition_history('', 'test-project', -1)

            assert result["status"] == "error"
            assert "Request exception" in result["message"]


class TestCycleTimeStateBoundaries:
    """Test canonical cycle-time boundary state definitions."""

    def test_cycle_time_boundary_constants(self):
        """Cycle time boundaries should include all known start states and End='Done'."""
        assert "In Progress" in CYCLE_TIME_START_STATES
        assert "In progress" in CYCLE_TIME_START_STATES
        assert "New" in CYCLE_TIME_START_STATES
        assert CYCLE_TIME_END_STATES == ("Done",)

    def test_cycle_time_boundary_accessor_contract(self):
        """Accessor should expose the canonical boundary states consistently."""
        boundaries = get_cycle_time_state_boundaries()

        assert "In Progress" in boundaries["start_states"]
        assert boundaries["end_states"] == ("Done",)


class TestTaigaParseUTC:
    """Test UTC date parsing functionality."""
    
    def test_parse_utc_valid_z_format(self):
        """Test parsing UTC date with Z suffix"""
        dt = parse_utc("2024-01-15T10:30:00Z")
        
        assert dt is not None
        assert isinstance(dt, datetime)
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
        assert dt.hour == 10
        assert dt.tzinfo is not None
    
    def test_parse_utc_valid_offset_format(self):
        """Test parsing UTC date with +00:00 offset"""
        dt = parse_utc("2024-01-15T10:30:00+00:00")
        
        assert dt is not None
        assert dt.year == 2024
        assert dt.tzinfo is not None
    
    def test_parse_utc_empty_string(self):
        """Test parsing empty UTC string"""
        dt = parse_utc("")
        
        assert dt is None
    
    def test_parse_utc_none_value(self):
        """Test parsing None value"""
        dt = parse_utc(None)
        
        assert dt is None
    
    def test_parse_utc_comparison(self):
        """Test that parsed dates can be compared"""
        dt1 = parse_utc("2024-01-15T10:00:00Z")
        dt2 = parse_utc("2024-01-15T11:00:00Z")
        
        assert dt1 < dt2
        assert dt2 > dt1
    
    def test_parse_utc_timezone_aware(self):
        """Test that parsed dates are timezone aware"""
        dt = parse_utc("2024-01-15T10:30:00Z")
        
        assert dt.tzinfo is not None
        assert dt.tzinfo == timezone.utc
