from datetime import datetime
from typing import List, Dict, Any
import logging

from src.services.taiga_metrics import CYCLE_TIME_START_STATES, CYCLE_TIME_END_STATES

# Module logger for cycle time computations
logger = logging.getLogger(__name__)

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
            # Look for the first start state then the last end state after it
            if t.get("status") in CYCLE_TIME_START_STATES:
                start_time = t.get("timestamp")
                logger.debug("Found start_time for story_id=%s: %s", story_id, start_time)
                for t2 in transitions_sorted[idx+1:]:
                    if t2.get("status") in CYCLE_TIME_END_STATES:
                        end_time = t2.get("timestamp")
                        logger.debug("Found end_time for story_id=%s: %s", story_id, end_time)
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

def summarize_cycle_times(results):
    times = [r["cycle_time_hours"] for r in results if r["cycle_time_hours"] is not None]
    if not times:
        return {"average": None, "median": None, "min": None, "max": None}
    times.sort()
    n = len(times)
    avg = sum(times) / n
    if n % 2 == 1:
        median = times[n // 2]
    else:
        median = (times[n // 2 - 1] + times[n // 2]) / 2.0
    return {
        "average": avg,
        "median": median,
        "min": times[0],
        "max": times[-1]
    }
