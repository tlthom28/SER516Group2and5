from datetime import datetime
from typing import List, Dict, Any

def compute_cycle_times(user_stories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for story in user_stories:
        story_id = story.get("story_id")
        transitions = story.get("transitions", [])
        if not transitions:
            results.append({"story_id": story_id, "cycle_time_hours": None})
            continue
        try:
            transitions_sorted = sorted(transitions, key=lambda t: t["timestamp"])
        except Exception:
            results.append({"story_id": story_id, "cycle_time_hours": None})
            continue
        start_time = None
        end_time = None
        for idx, t in enumerate(transitions_sorted):
            if t["status"] == "In Progress":
                start_time = t["timestamp"]
                for t2 in transitions_sorted[idx+1:]:
                    if t2["status"] == "Done":
                        end_time = t2["timestamp"]
                break
        if not start_time or not end_time:
            results.append({"story_id": story_id, "cycle_time_hours": None})
            continue
        try:
            start_dt = datetime.fromisoformat(start_time)
            end_dt = datetime.fromisoformat(end_time)
            cycle_time = (end_dt - start_dt).total_seconds() / 3600.0
            if cycle_time < 0:
                results.append({"story_id": story_id, "cycle_time_hours": None})
                continue
        except Exception:
            results.append({"story_id": story_id, "cycle_time_hours": None})
            continue
        results.append({
            "story_id": story_id,
            "cycle_time_hours": cycle_time
        })
    return results


def validate_cycle_time_input(story):
    if not isinstance(story, dict):
        return False
    if "transitions" not in story:
        return False
    transitions = story["transitions"]
    if not isinstance(transitions, list) or len(transitions) == 0:
        return False
    for t in transitions:
        if "status" not in t or "timestamp" not in t:
            return False
    return True
