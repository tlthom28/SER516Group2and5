from datetime import datetime
from typing import List, Dict, Any
import logging

from src.services.taiga_metrics import CYCLE_TIME_START_STATES, CYCLE_TIME_END_STATES

# Module logger for cycle time computations
logger = logging.getLogger(__name__)

def compute_cycle_times(user_stories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    logger.debug("Starting compute_cycle_times for %d stories", len(user_stories))
    logger.info(
        "Cycle time calculation started story_count=%s start_states=%s end_states=%s",
        len(user_stories),
        ",".join(CYCLE_TIME_START_STATES),
        ",".join(CYCLE_TIME_END_STATES),
    )
    for story in user_stories:
        story_id = story.get("story_id")
        transitions = story.get("transitions", [])
        logger.debug("Processing story_id=%s with %d transitions", story_id, len(transitions))

        if not transitions:
            logger.info("Cycle time skipped story_id=%s reason=no_transitions", story_id)
            results.append({"story_id": story_id, "cycle_time_hours": None})
            continue

        try:
            transitions_sorted = sorted(transitions, key=lambda t: t["timestamp"])
        except Exception as exc:
            logger.exception("Failed to sort transitions for story_id=%s: %s", story_id, exc)
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

        # Fallback: if no explicit start transition, use the from_status of the
        # first end-state transition (e.g. New → Done with no In Progress step)
        if not start_time and not end_time:
            for t in transitions_sorted:
                if t.get("status") in CYCLE_TIME_END_STATES:
                    from_status = t.get("from_status")
                    if from_status in CYCLE_TIME_START_STATES:
                        # Use story created_date as start if available
                        created_date = story.get("created_date")
                        if created_date:
                            start_time = created_date
                        else:
                            start_time = transitions_sorted[0].get("timestamp")
                        end_time = t.get("timestamp")
                        logger.debug(
                            "Fallback: using created_date as start for story_id=%s",
                            story_id,
                        )
                    break

        if not start_time or not end_time:
            logger.info(
                "Cycle time skipped story_id=%s reason=missing_boundary start=%s end=%s transitions=%s",
                story_id,
                start_time,
                end_time,
                len(transitions_sorted),
            )
            results.append({"story_id": story_id, "cycle_time_hours": None})
            continue

        try:
            start_dt = datetime.fromisoformat(start_time)
            end_dt = datetime.fromisoformat(end_time)
            cycle_time = (end_dt - start_dt).total_seconds() / 3600.0
            if cycle_time < 0:
                logger.warning("Negative cycle time computed for story_id=%s (start=%s end=%s); ignoring", story_id, start_time, end_time)
                results.append({"story_id": story_id, "cycle_time_hours": None})
                continue
        except Exception as exc:
            logger.exception("Failed to parse timestamps for story_id=%s: %s", story_id, exc)
            results.append({"story_id": story_id, "cycle_time_hours": None})
            continue

        logger.info(
            "Cycle time computed story_id=%s cycle_time_hours=%.2f transition_count=%s start=%s end=%s",
            story_id,
            cycle_time,
            len(transitions_sorted),
            start_time,
            end_time,
        )
        results.append({
            "story_id": story_id,
            "cycle_time_hours": cycle_time
        })

    computed_count = sum(1 for result in results if result["cycle_time_hours"] is not None)
    logger.info(
        "Cycle time calculation finished story_count=%s computed_count=%s missing_count=%s",
        len(results),
        computed_count,
        len(results) - computed_count,
    )
    logger.debug("Finished compute_cycle_times; produced %d results", len(results))
    return results


def validate_cycle_time_input(story):
    if not isinstance(story, dict):
        logger.debug("validate_cycle_time_input: invalid type: %s", type(story))
        return False
    if "transitions" not in story:
        logger.debug("validate_cycle_time_input: 'transitions' missing in story")
        return False
    transitions = story["transitions"]
    if not isinstance(transitions, list) or len(transitions) == 0:
        logger.debug("validate_cycle_time_input: transitions not a non-empty list")
        return False
    for t in transitions:
        if "status" not in t or "timestamp" not in t:
            logger.debug("validate_cycle_time_input: transition missing keys: %s", t)
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
