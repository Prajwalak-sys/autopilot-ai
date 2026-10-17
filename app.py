import os
import json
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from google import genai

from agent.executor import execute_plan
from tools.research import research_internships


# ==========================================
# CONFIGURATION
# ==========================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CSV_PATH = DATA_DIR / "internships.csv"
STATE_DIR = DATA_DIR / "task_states"

load_dotenv(BASE_DIR / ".env", override=True)

st.set_page_config(
    page_title="AutoPilot AI",
    page_icon="🤖",
    layout="wide",
)

st.title("🤖 AutoPilot AI")
st.subheader("Your Autonomous AI Operator")
st.write(
    "Give the agent a goal. It creates a plan, executes available tools, "
    "records progress, and presents the results."
)


# ==========================================
# GEMINI CONNECTION
# ==========================================

api_key = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-3.8-flash"
client = None

if api_key:
    try:
        client = genai.Client(api_key=api_key)
    except Exception:
        client = None

if not api_key:
    st.warning(
        "Gemini API key is missing. Select the built-in planner to continue "
        "without a Gemini API request."
    )


# ==========================================
# FALLBACK PLANNER
# ==========================================

def create_fallback_plan(field, location):
    """Create a predefined plan without using Gemini API requests."""
    return {
        "goal": (
            f"Find and organize {field} internship opportunities in {location}"
        ),
        "steps": [
            {
                "step": 1,
                "action": "research_internships",
                "description": f"Search for {field} internships in {location}",
            },
            {
                "step": 2,
                "action": "compare_results",
                "description": "Rank internships by relevance",
            },
            {
                "step": 3,
                "action": "verify_results",
                "description": "Check titles, descriptions, and URL formats",
            },
            {
                "step": 4,
                "action": "save_results",
                "description": "Save results to CSV through MCP",
            },
        ],
    }


# ==========================================
# GEMINI PLANNER
# ==========================================

def generate_plan(user_goal, field, location):
    """Use Gemini for planning; fall back if planning fails."""
    if client is None:
        st.warning("Gemini is unavailable. Using the built-in planner.")
        return create_fallback_plan(field, location)

    prompt = f"""
You are the planning engine of AutoPilot AI.

The user wants:
{user_goal}

Internship field: {field}
Preferred location: {location}

Return ONLY valid JSON in this structure:
{{
  "goal": "Short goal description",
  "steps": [
    {{"step": 1, "action": "research_internships", "description": "Search for internship opportunities"}},
    {{"step": 2, "action": "compare_results", "description": "Compare and rank search results"}},
    {{"step": 3, "action": "verify_results", "description": "Check result data quality"}},
    {{"step": 4, "action": "save_results", "description": "Save results to a CSV spreadsheet"}}
  ]
}}

Requirements:
- Include all four steps.
- Use the exact action names shown above.
- Keep the steps in the specified order.
- Do not include Markdown fences.
"""

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )
        response_text = (response.text or "").strip()

        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
            response_text = response_text.rsplit("```", 1)[0].strip()

        plan = json.loads(response_text)
        required_actions = [
            "research_internships",
            "compare_results",
            "verify_results",
            "save_results",
        ]
        actual_actions = [
            step.get("action") for step in plan.get("steps", [])
        ]

        if actual_actions != required_actions:
            raise ValueError("Gemini returned an incomplete or invalid plan.")

        return plan

    except Exception as error:
        st.warning(
            f"Gemini planning failed: {error}\n\n"
            "Using the built-in fallback plan instead."
        )
        return create_fallback_plan(field, location)


# ==========================================
# TASK STATE / DASHBOARD HELPERS
# ==========================================

ACTION_LABELS = {
    "research_internships": "Research internships",
    "compare_results": "Compare results",
    "verify_results": "Verify data quality",
    "save_results": "Save results",
}

def get_latest_matching_state(plan, field, location):
    """
    Find the executor's persisted state for the same plan.
    This only reads JSON files; it does not execute the workflow or call Gemini.
    """
    try:
        from agent.executor import create_task_id, get_state_file, load_task_state

        task_id = create_task_id(plan, field, location)
        state = load_task_state(task_id)
        return task_id, state
    except Exception:
        return None, None


def get_step_statuses(plan, execution):
    """Build dashboard step rows from actual executor log entries."""
    log_entries = execution.get("execution_log", []) if execution else []
    rows = []

    for step in plan.get("steps", []):
        matching = next(
            (
                entry for entry in reversed(log_entries)
                if entry.get("step") == step.get("step")
                and entry.get("action") == step.get("action")
            ),
            None,
        )

        status = matching.get("status", "pending") if matching else "pending"
        rows.append({
            "Step": step.get("step", ""),
            "Task": step.get("description", ACTION_LABELS.get(
                step.get("action", ""), step.get("action", "Unknown")
            )),
            "Status": status.replace("_", " ").title(),
            "Attempts": matching.get("attempts", 0) if matching else 0,
            "Details": matching.get("error", "") if matching else "",
            "_raw_status": status,
        })

    return rows


def show_dashboard(plan, execution):
    rows = get_step_statuses(plan, execution)
    raw_statuses = [row["_raw_status"] for row in rows]
    completed = sum(status == "completed" for status in raw_statuses)
    failed = sum(
        status in {"failed", "blocked", "no_results", "unsupported_action"}
        for status in raw_statuses
    )
    pending = len(rows) - completed - failed
    total = len(rows)
    progress = completed / total if total else 0.0

    st.divider()
    st.header("📈 Task Progress Dashboard")

    metric1, metric2, metric3, metric4 = st.columns(4)
    metric1.metric("Total steps", total)
    metric2.metric("Completed", completed)
    metric3.metric("Failed", failed)
    metric4.metric("Pending / running", pending)

    st.progress(progress, text=f"{completed} of {total} steps completed")

    display_rows = [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in rows
    ]
    st.dataframe(display_rows, use_container_width=True, hide_index=True)

    if execution:
        status = execution.get("task_status", "unknown")
        if status == "completed":
            st.success("Task completed successfully.")
        elif status == "partially_completed":
            st.warning("Task partially completed. Some actions are not implemented.")
        elif status == "incomplete":
            st.warning("Task is incomplete. Review the step statuses and execution log.")
        else:
            st.info(f"Current task status: {status}")

    return completed, failed, pending


# ==========================================
# USER INPUT
# ==========================================

st.divider()
st.header("🎯 Give Your AI a Goal")

user_goal = st.text_area(
    "What would you like the agent to do?",
    placeholder=(
        "Find AI/ML internships in Bengaluru, compare and verify "
        "the results, and save them to a spreadsheet."
    ),
    height=100,
)

col1, col2 = st.columns(2)

with col1:
    field = st.selectbox(
        "Internship field",
        [
            "AI/ML",
            "Python",
            "Data Science",
            "Software Development",
            "Web Development",
        ],
    )

with col2:
    location = st.text_input("Preferred location", value="Bengaluru")

use_fallback = st.checkbox(
    "Use built-in planner (no Gemini API request)",
    value=True,
    help=(
        "Recommended while your Gemini quota is limited. "
        "This creates the standard four-step plan locally."
    ),
)

# ==========================================
# PLAN AND EXECUTE
# ==========================================

if st.button("🧠 Analyze Task", type="primary"):
    if not user_goal.strip():
        st.warning("Please enter a goal.")
    elif not location.strip():
        st.warning("Please enter a location.")
    else:
        if use_fallback:
            plan = create_fallback_plan(field, location)
            plan["goal"] = user_goal.strip()
            st.info("Built-in planner selected. No Gemini API request was made.")
        else:
            plan = generate_plan(user_goal, field, location)

        st.session_state["autopilot_plan"] = plan
        st.session_state["autopilot_goal"] = user_goal.strip()
        st.session_state["autopilot_field"] = field
        st.session_state["autopilot_location"] = location
        # Clear the displayed execution for the newly selected plan.
        st.session_state.pop("autopilot_execution", None)
        st.success("Task plan created!")

if "autopilot_plan" in st.session_state:
    plan = st.session_state["autopilot_plan"]

    st.divider()
    st.header("📋 Execution Plan")
    st.write(f"**Goal:** {plan['goal']}")

    for step in plan.get("steps", []):
        st.write(
            f"**Step {step.get('step', '?')}:** "
            f"{step.get('description', step.get('action', ''))}"
        )

    # Display last execution and its progress, if present.
    current_execution = st.session_state.get("autopilot_execution")
    if current_execution:
        show_dashboard(plan, current_execution)

    if st.button("🚀 Execute / Resume Plan", type="primary"):
        with st.spinner("Executing the plan through your available tools..."):
            try:
                execution = execute_plan(
                    plan,
                    field=st.session_state["autopilot_field"],
                    location=st.session_state["autopilot_location"],
                )
                st.session_state["autopilot_execution"] = execution
                st.success("Execution finished.")
            except Exception as error:
                st.error(f"Execution failed: {error}")

        # Rerun to refresh dashboard and result panels with the latest state.
        st.rerun()

if "autopilot_execution" in st.session_state:
    execution = st.session_state["autopilot_execution"]
    results = execution.get("results", {})

    # Dashboard metrics also include useful output counts.
    research_results = results.get("research_results", []) or []
    comparison_results = results.get("comparison_results", []) or []
    verification_results = results.get("verification_results", []) or []
    save_result = results.get("save_result", {}) or {}

    st.divider()
    st.header("📊 Execution Results")

    status = execution.get("task_status", "unknown")
    if status == "completed":
        st.success("All planned steps completed!")
    elif status == "partially_completed":
        st.warning("Some steps are not implemented yet.")
    else:
        st.error(f"Task status: {status}")

    task_id = execution.get("task_id", "")
    st.caption(f"Task ID: {task_id}")

    m1, m2, m3 = st.columns(3)
    m1.metric("Internships researched", len(research_results))
    m2.metric("Ranked results", len(comparison_results))
    m3.metric("Basic checks performed", len(verification_results))

    if save_result:
        s1, s2 = st.columns(2)
        s1.metric("New CSV entries", save_result.get("new_entries", 0))
        s2.metric("Total saved entries", save_result.get("total_saved", 0))

    if execution.get("execution_log"):
        st.subheader("🧾 Execution Log")
        log_display = []
        for entry in execution["execution_log"]:
            log_display.append({
                "Step": entry.get("step", ""),
                "Action": ACTION_LABELS.get(
                    entry.get("action", ""), entry.get("action", "")
                ),
                "Status": str(entry.get("status", "")).replace("_", " ").title(),
                "Attempts": entry.get("attempts", 0),
                "Error": entry.get("error", ""),
                "Retry details": " | ".join(
                    f"Attempt {item.get('attempt')}: {item.get('error', '')}"
                    for item in entry.get("attempt_errors", [])
                    if isinstance(item, dict)
                ),
            })
        st.dataframe(log_display, use_container_width=True, hide_index=True)

    if execution.get("failed_step"):
        failed = execution["failed_step"]
        st.warning(
            f"Last failed step: {failed.get('step', '?')} "
            f"({failed.get('action', 'unknown')}) — "
            f"{failed.get('attempts', 0)} attempt(s)."
        )
    if execution.get("last_error"):
        st.error(f"Last error: {execution['last_error']}")
    if execution.get("last_updated"):
        st.caption(f"Last task update: {execution['last_updated']}")

    if research_results:
        with st.expander("🔎 Research Results", expanded=True):
            st.dataframe(research_results, use_container_width=True, hide_index=True)

    if comparison_results:
        with st.expander("⚖️ Comparison / Ranking Results"):
            st.dataframe(
                comparison_results, use_container_width=True, hide_index=True
            )

    if verification_results:
        with st.expander("✅ Basic Data-Quality Checks"):
            st.dataframe(
                verification_results, use_container_width=True, hide_index=True
            )
            st.caption(
                "These checks assess basic data quality; they do not confirm "
                "that an internship is genuine or currently open."
            )

    if save_result:
        with st.expander("💾 Spreadsheet Save Details"):
            st.json(save_result)

    if CSV_PATH.exists():
        with open(CSV_PATH, "rb") as csv_file:
            st.download_button(
                "⬇️ Download Internship CSV",
                data=csv_file.read(),
                file_name="internships.csv",
                mime="text/csv",
            )



# ==========================================
# PERSISTENT EXECUTION HISTORY
# ==========================================

with st.expander("🗂️ Execution History", expanded=False):
    st.caption(
        "History is loaded from saved JSON task-state files. "
        "Opening this section does not call Gemini or rerun research."
    )

    history_records = []
    if STATE_DIR.exists():
        for state_file in sorted(
            STATE_DIR.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            try:
                with open(state_file, "r", encoding="utf-8") as file:
                    saved_state = json.load(file)

                if not isinstance(saved_state, dict):
                    continue

                saved_results = saved_state.get("results", {})
                saved_log = saved_state.get("execution_log", [])
                if not isinstance(saved_results, dict):
                    saved_results = {}
                if not isinstance(saved_log, list):
                    saved_log = []

                completed_steps = sum(
                    entry.get("status") == "completed"
                    for entry in saved_log
                    if isinstance(entry, dict)
                )
                failed_steps = sum(
                    entry.get("status") in {
                        "failed", "blocked", "no_results", "unsupported_action"
                    }
                    for entry in saved_log
                    if isinstance(entry, dict)
                )
                research_count = len(saved_results.get("research_results", []) or [])
                save_info = saved_results.get("save_result", {}) or {}

                history_records.append({
                    "Task ID": saved_state.get("task_id", state_file.stem),
                    "Status": str(saved_state.get("status", "unknown")).replace(
                        "_", " "
                    ).title(),
                    "Completed steps": completed_steps,
                    "Failed steps": failed_steps,
                    "Research results": research_count,
                    "New CSV entries": save_info.get("new_entries", 0)
                    if isinstance(save_info, dict) else 0,
                    "State file": state_file.name,
                    "_state": saved_state,
                })
            except (OSError, json.JSONDecodeError):
                # Ignore unreadable or incomplete state files rather than
                # breaking the entire Streamlit page.
                continue

    if history_records:
        st.write(f"Found **{len(history_records)}** saved task record(s).")
        history_table = [
            {key: value for key, value in record.items() if not key.startswith("_")}
            for record in history_records
        ]
        st.dataframe(history_table, use_container_width=True, hide_index=True)

        history_options = {
            f"{record['Task ID']} — {record['Status']}": record
            for record in history_records
        }
        selected_history_label = st.selectbox(
            "Inspect a saved task",
            options=list(history_options.keys()),
            key="history_task_selection",
        )
        selected_record = history_options[selected_history_label]
        selected_state = selected_record["_state"]

        st.markdown(f"**Selected task ID:** `{selected_record['Task ID']}`")
        st.markdown(f"**Saved status:** {selected_record['Status']}")
        if selected_state.get("last_updated"):
            st.caption(f"Last updated: {selected_state['last_updated']}")
        if selected_state.get("failed_step"):
            st.warning(f"Saved failure details: {selected_state['failed_step']}")
        if selected_state.get("last_error"):
            st.error(f"Saved error: {selected_state['last_error']}")

        selected_log = selected_state.get("execution_log", [])
        if selected_log:
            history_log_rows = []
            for entry in selected_log:
                if not isinstance(entry, dict):
                    continue
                history_log_rows.append({
                    "Step": entry.get("step", ""),
                    "Action": ACTION_LABELS.get(
                        entry.get("action", ""), entry.get("action", "")
                    ),
                    "Status": str(entry.get("status", "")).replace(
                        "_", " "
                    ).title(),
                    "Attempts": entry.get("attempts", 0),
                    "Error": entry.get("error", ""),
                    "Retry details": " | ".join(
                        f"Attempt {item.get('attempt')}: {item.get('error', '')}"
                        for item in entry.get("attempt_errors", [])
                        if isinstance(item, dict)
                    ),
                })
            st.subheader("Saved execution log")
            st.dataframe(
                history_log_rows, use_container_width=True, hide_index=True
            )
        else:
            st.info("This saved task does not have execution-log entries yet.")

        selected_results = selected_state.get("results", {})
        if isinstance(selected_results, dict):
            with st.expander("View saved task results"):
                if selected_results:
                    st.json(selected_results)
                else:
                    st.info("No results have been saved for this task yet.")
    else:
        st.info(
            "No task history found yet. Execute a plan once and its saved state "
            "will appear here."
        )


# ==========================================
# MANUAL RESEARCH TOOL
# ==========================================

with st.expander("🔧 Manual Research Tool"):
    st.caption("This tool performs a fresh web search and does not call Gemini.")

    manual_field = st.text_input(
        "Research field",
        value="AI/ML",
        key="manual_field",
    )
    manual_location = st.text_input(
        "Research location",
        value="Bengaluru",
        key="manual_location",
    )

    if st.button("Search Manually"):
        try:
            with st.spinner("Searching for internships..."):
                manual_results = research_internships(
                    field=manual_field,
                    location=manual_location,
                    limit=5,
                )

            if manual_results:
                st.dataframe(
                    manual_results, use_container_width=True, hide_index=True
                )
            else:
                st.info("No results found.")
        except Exception as error:
            st.error(f"Research failed: {error}")
