"""
Taiga project metrics - Found Work and Adopted Work analysis.
Integrates with Taiga API to extract sprint and user story data.
"""
import requests
from datetime import datetime, timezone


def auth(base_url):
    """Authenticate with Taiga API by getting projects list."""
    if base_url == '':
        base_url = "https://api.taiga.io/api/v1"
    try:
        response = requests.get(f"{base_url}/projects")
        if response.status_code == 404:
            return {
                "status": "error",
                "message": f"Taiga did not authenticate (status code {response.status_code})"
            }
        else:
            return {
                "status": "success",
                "message": f"Taiga authenticated with status code {response.status_code}"
            }
    except requests.exceptions.RequestException:
        return {
            "status": "error",
            "message": "Request exception when trying to authenticate with Taiga api"
        }


def get_structure(base_url, slug, taiga_id):
    """Get structure of a Taiga board and return a project dictionary."""
    if base_url == '':
        base_url = "https://api.taiga.io/api/v1"

    try:
        project_res = {}
        if slug != '' and taiga_id == -1:
            project_res = requests.get(f"{base_url}/projects/by_slug?slug={slug}")
            if project_res.status_code == 200:
                taiga_id = int(project_res.json().get('id'))
            else:
                return f"Error: Taiga response code {project_res.status_code}"
        else:
            project_res = requests.get(f"{base_url}/projects/{taiga_id}")
            if project_res.status_code != 200:
                return f"Error: Taiga response code (Project) {project_res.status_code}"

        sprint_res = requests.get(f"{base_url}/milestones?project={taiga_id}")
        if sprint_res.status_code != 200:
            return f"Error: Taiga response code (Sprints) {sprint_res.status_code}"

        user_story_res = requests.get(f"{base_url}/userstories?project={taiga_id}")
        if user_story_res.status_code != 200:
            return f"Error: Taiga response code (User stories) {user_story_res.status_code}"

        tasks_res = requests.get(f"{base_url}/tasks?project={taiga_id}")
        if tasks_res.status_code != 200:
            return f"Error: Taiga response code (Tasks) {tasks_res.status_code}"

        proj_data = project_res.json()
        sprint_data = sprint_res.json()
        user_story_data = user_story_res.json()
        task_data = tasks_res.json()

        # Group tasks by user story id
        tasks_by_story = {}
        for task in task_data:
            us_id = task.get("user_story")
            if us_id not in tasks_by_story:
                tasks_by_story[us_id] = []
            tasks_by_story[us_id].append({
                "task_id": int(task["id"]),
                "task_name": task["subject"],
                "created_date": task["created_date"]
            })

        # Group user stories by sprints
        stories_by_sprint = {}
        for user_story in user_story_data:
            sprint_id = int(user_story["milestone"])
            if sprint_id not in stories_by_sprint:
                stories_by_sprint[sprint_id] = []
            stories_by_sprint[sprint_id].append({
                "user_story_name": user_story["subject"],
                "user_story_id": int(user_story["id"]),
                "user_story_created_date": user_story["created_date"],
                "user_story_tasks": tasks_by_story.get(int(user_story["id"]), [])
            })

        project = {
            "project_name": proj_data["name"],
            "project_id": proj_data["id"],
            "project_created_date": proj_data["created_date"],
            "project_sprints": []
        }

        # Add sprints into project
        for sprint in sprint_data:
            sprint_id = int(sprint["id"])
            project["project_sprints"].append({
                "sprint_name": sprint["name"],
                "sprint_id": sprint_id,
                "sprint_start": sprint["estimated_start"],
                "sprint_finish": sprint["estimated_finish"],
                "sprint_user_stories": stories_by_sprint.get(sprint_id, [])
            })

        return project
    except requests.exceptions.RequestException:
        return {
            "status": "error",
            "message": "Request exception when trying to communicate with Taiga api"
        }


def get_adopted_work(base_url, slug='', taiga_id=-1):
    """Calculate adopted work (stories created after sprint start)."""
    if base_url == '':
        base_url = "https://api.taiga.io/api/v1"

    us_order = ["user_story_name", "user_story_id", "created_date"]
    sprint_order = ["sprint_name", "sprint_id", "sprint_start", "sprint_finish", "adopted_count", "adopted_stories"]

    project = get_structure(base_url, slug, taiga_id)

    if project is None or isinstance(project, str) or (isinstance(project, dict) and project.get("status") == "error"):
        return {
            "status": "error",
            "message": project if isinstance(project, str) else "Could not fetch project from Taiga."
        }

    sprints_result = []
    for sprint in project["project_sprints"]:
        sprint_start_dt = parse_utc(sprint["sprint_start"])
        adopted = []

        for story in sprint["sprint_user_stories"]:
            raw_created = story.get("user_story_created_date", "")
            created_dt = parse_utc(raw_created)

            if created_dt is None or sprint_start_dt is None:
                continue

            if created_dt > sprint_start_dt:
                story_dict = {
                    "user_story_name": story["user_story_name"],
                    "user_story_id": story["user_story_id"],
                    "created_date": raw_created,
                }
                adopted.append({key: story_dict[key] for key in us_order if key in story_dict})

        sprint_dict = {
            "sprint_name": sprint["sprint_name"],
            "sprint_id": sprint["sprint_id"],
            "sprint_start": sprint["sprint_start"],
            "sprint_finish": sprint["sprint_finish"],
            "adopted_count": len(adopted),
            "adopted_stories": adopted,
        }
        sprints_result.append({key: sprint_dict[key] for key in sprint_order if key in sprint_dict})

    return {
        "status": "success",
        "sprints": sprints_result,
    }


def parse_utc(date):
    """Parse UTC date string to datetime object."""
    if not date:
        return None
    dt = datetime.fromisoformat(date.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
