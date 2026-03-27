"""
Taiga project metrics - Found Work and Adopted Work analysis.
Integrates with Taiga API to extract sprint and user story data.
"""
import requests
from datetime import datetime, timezone
from fastapi import FastAPI, Query
from typing import Optional

app = FastAPI()

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

def parse_utc(date):
    """Parse UTC date string to datetime object."""
    if not date:
        return None
    dt = datetime.fromisoformat(date.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def found_work(project):
    # order expected for user story and sprint return
    us_order = ["user_story_name", "user_story_id",
                "user_story_created_date", "user_story_found_work_percentage", "user_story_tasks"]
    sprint_order = ["sprint_name", "sprint_id",
                    "sprint_start", "sprint_finish", "sprint_found_work_percentage",
                    "sprint_user_stories"]
    for j, sprint in enumerate(project["project_sprints"]):
        sprint_tasks = 0
        sprint_FW = 0
        sprint_start_date = parse_utc(sprint["sprint_start"])
        for i, user_story in enumerate(sprint["sprint_user_stories"]):
            user_story_tasks = 0
            user_story_FW = 0
            for task in user_story["user_story_tasks"]:
                task_start_date = parse_utc(task["created_date"])
                if task_start_date and sprint_start_date:
                    if task_start_date > sprint_start_date:
                        user_story_FW += 1
                        task.update({"is_found_work": True})
                    else:
                        task.update({"is_found_work": False})
                # if date not found, then no found work
                else:
                    task.update({"is_found_work": False})
                user_story_tasks += 1
            if user_story_tasks > 0:
                user_story.update(
                    {"user_story_found_work_percentage": round(user_story_FW / user_story_tasks, 2)})
            else:
                user_story.update(
                    {"user_story_found_work_percentage": 0.0})
            sprint["sprint_user_stories"][i] = {key: user_story[key]
                                                for key in us_order if key in user_story}
            sprint_tasks += user_story_tasks
            sprint_FW += user_story_FW
        if sprint_tasks > 0:
            sprint.update(
                {"sprint_found_work_percentage": round(sprint_FW/sprint_tasks, 2)})
        else:
            sprint.update(
                {"sprint_found_work_percentage": 0})
        project["project_sprints"][j] = {key: sprint[key]
                                         for key in sprint_order if key in sprint}
    return project

@app.get("/taiga/found_work/", summary="Found work of Taiga project", description="Analyzes a Taiga project and returns found work")
async def taiga_found_work(
    base_url: Optional[str] = Query(
        "https://api.taiga.io/api/v1", example="https://api.taiga.io/api/v1", description="Base url for Taiga instance"),
    slug: Optional[str] = Query("jozefmak-t1e2018", example="jozefmak-t1e2018",
                                description="Slug of Taiga instance (needs either slug or ID)"),
    id: Optional[int] = Query(-1, example=-1,
                              description="ID of Taiga instance (needs either slug or ID, ID takes precedence), default -1 to use slug"),
):
    # get project
    project = get_structure(base_url=base_url, slug=slug, taiga_id=id)
    # if no project structure returned, then error; send error back and print to console
    if (type(project) == str):
        print(project)
        return {
            "status": "Error",
            "return": project
        }
    # else project successfully retrieved
    return found_work(project=project)

if __name__ == "__main__":
    taiga_found_work("https://api.taiga.io/api/v1", "jozefmak-t1e2018", -1)
