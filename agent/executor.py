import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlparse

from agent.mcp_client import (
    search_internships_mcp,
    save_internships_mcp,
)

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "data" / "task_states"

MAX_RETRIES = 3


# ==========================================
# MCP RESPONSE HANDLING
# ==========================================

def parse_mcp_response(response):
    """Convert MCP text content into Python data."""
    if isinstance(response, (dict, list)):
        return response

    if isinstance(response, str):
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return response

    if isinstance(response, list):
        for item in response:
            if isinstance(item, str):
                try:
                    return json.loads(item)
                except json.JSONDecodeError:
                    continue

    return response


# ==========================================
# TASK STATE MANAGEMENT
# ==========================================

def create_task_id(plan, field, location):
    task_information = {
        "goal": plan.get("goal", ""),
        "steps": plan.get("steps", []),
        "field": field,
        "location": location,
    }

    task_string = json.dumps(task_information, sort_keys=True)

    return hashlib.sha256(
        task_string.encode("utf-8")
    ).hexdigest()[:16]


def get_state_file(task_id):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / f"{task_id}.json"


def load_task_state(task_id):
    state_file = get_state_file(task_id)

    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as file:
                state = json.load(file)

            if isinstance(state, dict):
                return state

        except (json.JSONDecodeError, OSError):
            pass

    return {
        "task_id": task_id,
        "status": "not_started",
        "results": {},
        "execution_log": [],
    }


def save_task_state(task_id, state):
    state_file = get_state_file(task_id)
    temporary_file = state_file.with_suffix(".tmp")

    with open(temporary_file, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=4, ensure_ascii=False)

    temporary_file.replace(state_file)


# ==========================================
# INTERNSHIP COMPARISON
# ==========================================

def compare_internships(internships, field):
    if not internships:
        raise RuntimeError("No results available for comparison.")

    keywords_by_field = {
        "AI/ML": [
            "ai",
            "artificial intelligence",
            "machine learning",
            "ml",
            "deep learning",
            "data science",
        ],
        "Python": [
            "python",
            "django",
            "flask",
            "programming",
        ],
        "Data Science": [
            "data science",
            "data analyst",
            "analytics",
            "machine learning",
            "python",
        ],
        "Software Development": [
            "software development",
            "software engineer",
            "developer",
            "programming",
        ],
        "Web Development": [
            "web development",
            "frontend",
            "backend",
            "full stack",
            "react",
            "javascript",
        ],
    }

    keywords = keywords_by_field.get(field, [field.lower()])
    ranked_results = []

    for item in internships:
        title = str(item.get("title", ""))
        snippet = str(item.get("snippet", ""))

        title_text = title.lower()
        snippet_text = snippet.lower()

        title_matches = [
            word for word in keywords if word in title_text
        ]

        description_matches = [
            word for word in keywords if word in snippet_text
        ]

        score = len(title_matches) * 3 + len(description_matches)

        ranked_results.append({
            **item,
            "relevance_score": score,
            "matching_keywords": list(
                dict.fromkeys(title_matches + description_matches)
            ),
            "comparison_basis": "Keyword relevance",
        })

    ranked_results.sort(
        key=lambda item: item["relevance_score"],
        reverse=True,
    )

    for rank, item in enumerate(ranked_results, start=1):
        item["rank"] = rank

    return ranked_results


# ==========================================
# INTERNSHIP VERIFICATION
# ==========================================

def verify_internships(internships):
    """
    Perform basic data-quality checks.

    These checks do not prove that an internship is genuine,
    currently available, or suitable for the applicant.
    """

    if not internships:
        raise RuntimeError("No results available for verification.")

    verified_results = []

    for item in internships:
        title = str(item.get("title", "")).strip()
        snippet = str(item.get("snippet", "")).strip()
        url = str(item.get("url", "")).strip()

        parsed_url = urlparse(url)

        valid_url_format = (
            parsed_url.scheme in {"http", "https"}
            and bool(parsed_url.netloc)
            and "." in parsed_url.netloc
        )

        checks = {
            "has_title": bool(title),
            "has_description": bool(snippet),
            "has_valid_url_format": valid_url_format,
        }

        passed_checks = sum(checks.values())

        quality_status = (
            "passed_basic_checks"
            if passed_checks == len(checks)
            else "needs_review"
        )

        verified_results.append({
            **item,
            "verification_checks": checks,
            "checks_passed": passed_checks,
            "checks_total": len(checks),
            "quality_status": quality_status,
            "verification_note": (
                "Basic data-quality checks only. "
                "The listing, deadline, eligibility and availability "
                "have not been independently verified."
            ),
        })

    return verified_results


# ==========================================
# EXECUTE ONE ACTION
# ==========================================

def execute_action(action, results, field, location):

    # Research through the MCP server
    if action == "research_internships":

        mcp_response = search_internships_mcp(
            field=field,
            location=location,
            limit=5,
        )

        research_results = parse_mcp_response(mcp_response)

        if isinstance(research_results, dict):
            research_results = research_results.get(
                "results",
                research_results.get("content", []),
            )

        if not isinstance(research_results, list):
            raise RuntimeError(
                "MCP research returned an unexpected response."
            )

        if not research_results:
            raise RuntimeError("Research returned no results.")

        # Handle JSON strings inside the response list.
        normalized_results = []

        for item in research_results:
            if isinstance(item, str):
                item = parse_mcp_response(item)

            if isinstance(item, dict):
                normalized_results.append(item)

        if not normalized_results:
            raise RuntimeError(
                "MCP research returned no usable internship records."
            )

        results["research_results"] = normalized_results

        return "completed"

    # Compare research results
    elif action == "compare_results":

        source_results = results.get("research_results", [])

        if not source_results:
            raise RuntimeError("Research results are missing.")

        results["comparison_results"] = compare_internships(
            source_results,
            field,
        )

        return "completed"

    # Verify basic data quality
    elif action == "verify_results":

        source_results = results.get("research_results", [])

        if not source_results:
            raise RuntimeError("Research results are missing.")

        results["verification_results"] = verify_internships(
            source_results
        )

        return "completed"

    # Save through the MCP server
    elif action == "save_results":

        source_results = (
            results.get("verification_results")
            or results.get("research_results", [])
        )

        if not source_results:
            raise RuntimeError("Research results are missing.")

        mcp_response = save_internships_mcp(source_results)
        save_result = parse_mcp_response(mcp_response)

        if isinstance(save_result, dict):
            if save_result.get("success") is False:
                raise RuntimeError(
                    save_result.get("message", "MCP saving failed.")
                )

            results["save_result"] = save_result

        else:
            raise RuntimeError(
                "MCP saving returned an unexpected response."
            )

        return "completed"

    elif action == "draft_emails":
        return "not_implemented"

    return "unsupported_action"


# ==========================================
# RETRY LOGIC
# ==========================================

def execute_with_retry(action, results, field, location):

    if action == "draft_emails":
        return {
            "status": "not_implemented",
            "attempts": 0,
        }

    if action not in {
        "research_internships",
        "compare_results",
        "verify_results",
        "save_results",
    }:
        return {
            "status": "unsupported_action",
            "attempts": 0,
        }

    last_error = None
    attempt_errors = []

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            status = execute_action(
                action,
                results,
                field,
                location,
            )

            return {
                "status": status,
                "attempts": attempt,
                "attempt_errors": attempt_errors,
            }

        except Exception as error:
            last_error = str(error)
            attempt_errors.append({
                "attempt": attempt,
                "error": last_error,
            })

            if attempt < MAX_RETRIES:
                time.sleep(attempt)

    return {
        "status": "failed",
        "attempts": MAX_RETRIES,
        "error": last_error,
        "attempt_errors": attempt_errors,
    }


# ==========================================
# EXECUTE PLAN WITH PERSISTENT STATE
# ==========================================

def execute_plan(plan, field="AI/ML", location="Bengaluru"):

    task_id = create_task_id(plan, field, location)
    state = load_task_state(task_id)

    results = state.get("results", {})
    execution_log = state.get("execution_log", [])

    if not isinstance(results, dict):
        results = {}

    if not isinstance(execution_log, list):
        execution_log = []

    state["status"] = "running"
    save_task_state(task_id, state)

    for step in plan.get("steps", []):

        step_number = step.get("step")
        action = step.get("action", "")

        already_completed = any(
            entry.get("step") == step_number
            and entry.get("action") == action
            and entry.get("status") == "completed"
            for entry in execution_log
        )

        if already_completed:
            continue

        log_entry = {
            "step": step_number,
            "action": action,
            "status": "running",
            "attempts": 0,
        }

        existing_index = next(
            (
                index
                for index, entry in enumerate(execution_log)
                if entry.get("step") == step_number
                and entry.get("action") == action
            ),
            None,
        )

        if existing_index is None:
            execution_log.append(log_entry)
        else:
            execution_log[existing_index] = log_entry

        state["results"] = results
        state["execution_log"] = execution_log
        save_task_state(task_id, state)

        outcome = execute_with_retry(
            action,
            results,
            field,
            location,
        )

        log_entry["status"] = outcome["status"]
        log_entry["attempts"] = outcome["attempts"]

        if "error" in outcome:
            log_entry["error"] = outcome["error"]

        # Keep retry details so the interface can explain what happened.
        if outcome.get("attempt_errors"):
            log_entry["attempt_errors"] = outcome["attempt_errors"]

        state["results"] = results
        state["execution_log"] = execution_log
        state["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_task_state(task_id, state)

        if log_entry["status"] in {
            "failed",
            "blocked",
            "no_results",
        }:
            state["last_error"] = log_entry.get("error", "Step failed.")
            state["failed_step"] = {
                "step": step_number,
                "action": action,
                "attempts": log_entry.get("attempts", 0),
            }
            save_task_state(task_id, state)
            break

    # Determine overall task status.
    final_entries = []

    for step in plan.get("steps", []):
        matching_entry = next(
            (
                entry
                for entry in reversed(execution_log)
                if entry.get("step") == step.get("step")
                and entry.get("action") == step.get("action")
            ),
            None,
        )

        if matching_entry:
            final_entries.append(matching_entry)

    statuses = [
        entry.get("status")
        for entry in final_entries
    ]

    if any(
        status in {"failed", "blocked", "no_results"}
        for status in statuses
    ):
        task_status = "incomplete"

    elif any(
        status in {"not_implemented", "unsupported_action"}
        for status in statuses
    ):
        task_status = "partially_completed"

    elif statuses and all(
        status == "completed"
        for status in statuses
    ):
        task_status = "completed"

    else:
        task_status = "incomplete"

    state["status"] = task_status
    state["results"] = results
    state["execution_log"] = execution_log
    state["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")

    if task_status == "completed":
        state.pop("last_error", None)
        state.pop("failed_step", None)
    elif not state.get("last_error"):
        failed_entry = next(
            (
                entry for entry in reversed(final_entries)
                if entry.get("status") in {"failed", "blocked", "no_results"}
            ),
            None,
        )
        if failed_entry:
            state["last_error"] = failed_entry.get(
                "error", "Step did not complete."
            )
            state["failed_step"] = {
                "step": failed_entry.get("step"),
                "action": failed_entry.get("action"),
                "attempts": failed_entry.get("attempts", 0),
            }

    save_task_state(task_id, state)

    return {
        "task_id": task_id,
        "task_status": task_status,
        "results": results,
        "execution_log": execution_log,
        "last_error": state.get("last_error"),
        "failed_step": state.get("failed_step"),
        "last_updated": state.get("last_updated"),
    }