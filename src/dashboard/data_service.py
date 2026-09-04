import ast
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List

import yaml

from config.app_config import JOB_SITE
from config.constants import LOG_DIR, OUTPUT_DIR_INDEED, OUTPUT_DIR_LINKEDIN, SEARCH_CONFIG_FILE
from src.dashboard.runtime import (
    CONTROL_FILE,
    EVENTS_FILE,
    ROOT_DIR,
    SNAPSHOT_FILE,
    get_control_state,
    get_process_info,
    get_screenshot_history,
    get_snapshot,
    read_events,
    read_events_for_run,
    sync_process_state,
)
from src.pydantic_models.config_models import SearchConfig
from src.utils.utils import save_yaml_file

OUTPUT_DIR = OUTPUT_DIR_LINKEDIN if JOB_SITE == "linkedin" else OUTPUT_DIR_INDEED
APP_CONFIG_FILE = ROOT_DIR / "config" / "app_config.py"
LAST_RUN_FILE = ROOT_DIR / OUTPUT_DIR / "last_run.yaml"
SUCCESS_FILE = ROOT_DIR / OUTPUT_DIR / "success.yaml"
SKIPPED_FILE = ROOT_DIR / OUTPUT_DIR / "skipped.yaml"
FAILED_FILE = ROOT_DIR / OUTPUT_DIR / "failed.yaml"
INTERESTING_FILE = ROOT_DIR / OUTPUT_DIR / "interesting_jobs.yaml"
LLM_CALLS_FILE = ROOT_DIR / LOG_DIR / "llm_api_calls.yaml"
MESSAGES_FILE = ROOT_DIR / OUTPUT_DIR / "messages_dry_run.yaml"
EDITABLE_APP_CONFIG_KEYS = {
    "MAX_APPLIES_NUM",
    "HEADLESS_MODE",
    "MONKEY_MODE",
    "TEST_MODE",
    "COLLECT_INFO_MODE",
    "EASY_APPLY_ONLY_MODE",
    "INDEED_DOMAIN",
    "INDEED_SEARCH_RADIUS",
    "LINKEDIN_RECOMMENDED_JOBS_MODE",
    "LINKEDIN_TOP_APPLICANT_JOBS_MODE",
    "RESTART_EVERY_DAY",
    "MINIMUM_WAIT_TIME_SEC",
    "FREE_TIER",
    "FREE_TIER_RPM_LIMIT",
    "MINIMUM_LOG_LEVEL",
    "LLM_MODEL_TYPE",
    "EASY_APPLY_MODEL",
    "APPLY_AGENT_MODEL",
    "TEMPERATURE",
    "RESUME_STYLE",
}


def _read_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    return deepcopy(default) if data is None else data


def _flatten_company_jobs(
    data: Dict[str, List[Dict[str, Any]]], status: str
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for company_name, jobs in (data or {}).items():
        for job in jobs or []:
            rows.append(
                {
                    "status": status,
                    "company_name": job.get("company_name") or company_name,
                    "job_title": job.get("job_title", ""),
                    "url": job.get("url", ""),
                    "skip_reason": job.get("skip_reason", ""),
                    "interest_score": job.get("interest_score"),
                    "interest_reason": job.get("interest_reason"),
                    "skills": job.get("skills"),
                    "llm_time_seconds": job.get("llm_time_seconds", 0.0),
                    "executed_at": job.get("executed_at"),
                    "submitted_resume_path": job.get("submitted_resume_path"),
                }
            )
    return rows


def _flatten_interesting_jobs(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"status": "interesting", **job} for job in data or []]


def _job_url_key(url: str | None) -> str:
    value = (url or "").strip()
    linkedin_job_id = re.search(r"/jobs/view/(\d+)", value)
    if linkedin_job_id:
        return f"linkedin:{linkedin_job_id.group(1)}"
    return value.split("?", 1)[0].rstrip("/")


def _load_jobs_board() -> List[Dict[str, Any]]:
    jobs = []
    jobs.extend(_flatten_company_jobs(_read_yaml(SUCCESS_FILE, {}), "applied"))
    jobs.extend(_flatten_company_jobs(_read_yaml(SKIPPED_FILE, {}), "skipped"))
    jobs.extend(_flatten_company_jobs(_read_yaml(FAILED_FILE, {}), "failed"))

    seen_urls = {_job_url_key(job.get("url")) for job in jobs if job.get("url")}
    for job in _flatten_interesting_jobs(_read_yaml(INTERESTING_FILE, [])):
        if job.get("url") and _job_url_key(job.get("url")) in seen_urls:
            continue
        jobs.append(job)

    jobs.sort(
        key=lambda job: (
            job.get("status") != "in_progress",
            job.get("company_name") or "",
            job.get("job_title") or "",
        )
    )

    snapshot = get_snapshot()
    current_job = snapshot.get("current_job")
    if current_job:
        jobs.insert(
            0,
            {
                "status": "in_progress",
                "company_name": current_job.get("company"),
                "job_title": current_job.get("title"),
                "url": current_job.get("url"),
                "skip_reason": "",
                "interest_score": current_job.get("score"),
                "interest_reason": "",
                "skills": None,
                "llm_time_seconds": current_job.get("llm_time_seconds", 0.0),
                "executed_at": current_job.get("executed_at") or snapshot.get("last_event_at"),
                "submitted_resume_path": current_job.get("submitted_resume_path"),
            },
        )

    return jobs


def _apply_job_filters(
    rows: List[Dict[str, Any]], status: str | None = None, search: str | None = None
) -> List[Dict[str, Any]]:
    if status:
        rows = [row for row in rows if row.get("status") == status]
    if search:
        term = search.lower()
        rows = [
            row
            for row in rows
            if term in (row.get("job_title") or "").lower()
            or term in (row.get("company_name") or "").lower()
            or term in (row.get("url") or "").lower()
        ]
    return rows


def _build_run_jobs(run_id: str) -> List[Dict[str, Any]]:
    events = read_events_for_run(run_id=run_id, limit=5000)
    jobs: Dict[str, Dict[str, Any]] = {}

    for event in events:
        payload = event.get("payload", {})
        url = (
            payload.get("url")
            or f"unknown:{payload.get('company_name') or ''}:{payload.get('job_title') or ''}"
        )
        if url not in jobs:
            jobs[url] = {
                "status": "discovered",
                "company_name": payload.get("company_name"),
                "job_title": payload.get("job_title"),
                "url": payload.get("url") or "",
                "skip_reason": "",
                "interest_score": 0,
                "interest_reason": "",
                "skills": None,
                "llm_time_seconds": 0.0,
                "executed_at": event.get("timestamp"),
                "submitted_resume_path": payload.get("submitted_resume_path"),
                "stage": payload.get("stage"),
                "last_message": event.get("message"),
                "updated_at": event.get("timestamp"),
            }

        job = jobs[url]
        job["company_name"] = payload.get("company_name") or job.get("company_name")
        job["job_title"] = payload.get("job_title") or job.get("job_title")
        job["url"] = payload.get("url") or job.get("url")
        job["stage"] = payload.get("stage") or job.get("stage")
        job["last_message"] = event.get("message") or job.get("last_message")
        job["updated_at"] = event.get("timestamp") or job.get("updated_at")
        job["submitted_resume_path"] = payload.get("submitted_resume_path") or job.get(
            "submitted_resume_path"
        )

        event_type = event.get("type")
        if event_type == "llm_call_completed":
            job["llm_time_seconds"] = payload.get(
                "total_job_llm_time_seconds", job.get("llm_time_seconds", 0.0)
            )
            continue

        if event_type == "job_evaluated":
            job["interest_score"] = payload.get("score")
            job["interest_reason"] = payload.get("reasoning") or job.get("interest_reason", "")
            job["llm_time_seconds"] = payload.get(
                "llm_time_seconds", job.get("llm_time_seconds", 0.0)
            )
            job["status"] = "interesting" if payload.get("interesting") else "skipped"
            if not payload.get("interesting") and not job.get("skip_reason"):
                job["skip_reason"] = payload.get("reasoning") or "Vacancy is not interesting"
        elif event_type in {
            "job_loaded",
            "job_progress",
            "job_application_started",
            "job_evaluation_started",
        }:
            if job.get("status") not in {"applied", "skipped", "failed"}:
                job["status"] = "in_progress"
        elif event_type == "job_result":
            result = str(payload.get("result", "")).lower()
            job["llm_time_seconds"] = payload.get(
                "llm_time_seconds", job.get("llm_time_seconds", 0.0)
            )
            job["executed_at"] = event.get("timestamp") or job.get("executed_at")
            if result == "success":
                job["status"] = "applied"
            elif result == "skip":
                job["status"] = "skipped"
                job["skip_reason"] = payload.get("reason") or job.get("skip_reason", "")
            elif result in {"error", "failed"}:
                job["status"] = "failed"
                job["skip_reason"] = payload.get("reason") or job.get("skip_reason", "")

    saved_jobs_by_url: Dict[str, Dict[str, Any]] = {}
    for saved_job in (
        _flatten_company_jobs(_read_yaml(SUCCESS_FILE, {}), "applied")
        + _flatten_company_jobs(_read_yaml(SKIPPED_FILE, {}), "skipped")
        + _flatten_company_jobs(_read_yaml(FAILED_FILE, {}), "failed")
        + _flatten_interesting_jobs(_read_yaml(INTERESTING_FILE, []))
    ):
        if saved_job.get("url"):
            saved_jobs_by_url[_job_url_key(saved_job.get("url"))] = saved_job

    rows = []
    for job in jobs.values():
        saved_job = saved_jobs_by_url.get(_job_url_key(job.get("url")))
        if saved_job:
            if saved_job.get("status") == "interesting" and job.get("status") != "applied":
                job["status"] = "interesting"
            for field in ("company_name", "job_title", "skip_reason", "interest_reason"):
                job[field] = job.get(field) or saved_job.get(field)
            if job.get("interest_score") in (None, 0):
                job["interest_score"] = saved_job.get("interest_score")
            if not job.get("skills"):
                job["skills"] = saved_job.get("skills")
            if not job.get("llm_time_seconds"):
                job["llm_time_seconds"] = saved_job.get("llm_time_seconds", 0.0)
            if not job.get("submitted_resume_path"):
                job["submitted_resume_path"] = saved_job.get("submitted_resume_path")
            job["executed_at"] = job.get("executed_at") or saved_job.get("executed_at")
        rows.append(job)

    rows.sort(
        key=lambda job: (
            job.get("status") != "in_progress",
            -(0 if not job.get("updated_at") else 1),
            job.get("updated_at") or "",
        ),
        reverse=True,
    )
    return rows


def _build_run_history() -> List[Dict[str, Any]]:
    events = read_events(limit=5000)
    runs: Dict[str, Dict[str, Any]] = {}

    for event in events:
        run_id = event.get("run_id")
        if not run_id:
            continue

        run = runs.setdefault(
            run_id,
            {
                "run_id": run_id,
                "status": "unknown",
                "started_at": None,
                "finished_at": None,
                "last_event_at": None,
                "last_message": None,
                "jobs": {
                    "applied": 0,
                    "skipped": 0,
                    "failed": 0,
                    "interesting": 0,
                    "discovered": 0,
                },
            },
        )

        event_type = event.get("type")
        payload = event.get("payload", {})
        timestamp = event.get("timestamp")

        run["last_event_at"] = timestamp
        run["last_message"] = event.get("message")

        if event_type == "run_started":
            run["status"] = "running"
            run["started_at"] = timestamp
        elif event_type == "run_completed":
            run["status"] = "completed"
            run["finished_at"] = timestamp
        elif event_type == "run_failed":
            run["status"] = "failed"
            run["finished_at"] = timestamp
        elif event_type == "run_stopped":
            run["status"] = "stopped"
            run["finished_at"] = timestamp
        elif event_type == "jobs_discovered":
            run["jobs"]["discovered"] = max(
                run["jobs"]["discovered"],
                int(payload.get("total_discovered", payload.get("count", 0))),
            )
        elif event_type == "job_evaluated" and payload.get("interesting"):
            run["jobs"]["interesting"] += 1
        elif event_type == "job_result":
            result = str(payload.get("result", "")).lower()
            if result == "success":
                run["jobs"]["applied"] += 1
            elif result == "skip":
                run["jobs"]["skipped"] += 1
            elif result in {"error", "failed"}:
                run["jobs"]["failed"] += 1

    return sorted(runs.values(), key=lambda run: run.get("started_at") or "", reverse=True)


def _load_last_run() -> Dict[str, Any]:
    return _read_yaml(ROOT_DIR / LAST_RUN_FILE, {})


def _read_llm_totals() -> Dict[str, Any]:
    if not LLM_CALLS_FILE.exists():
        return {"calls": 0, "total_tokens": 0, "total_cost": 0.0, "total_time_seconds": 0.0}

    calls, total_tokens, total_cost, total_time = 0, 0, 0.0, 0.0
    with LLM_CALLS_FILE.open(encoding="utf-8") as f:
        for doc in yaml.safe_load_all(f):
            if not isinstance(doc, dict):
                continue
            calls += 1
            total_tokens += doc.get("total_tokens") or 0
            total_cost += doc.get("total_cost") or 0.0
            total_time += doc.get("response_time_seconds") or 0.0

    return {
        "calls": calls,
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 6),
        "total_time_seconds": round(total_time, 3),
    }


def get_summary() -> Dict[str, Any]:
    sync_process_state()
    jobs = _load_jobs_board()
    last_run = _load_last_run()
    snapshot = get_snapshot()
    process_info = get_process_info()
    llm_totals = _read_llm_totals()

    return {
        "run": {
            "status": snapshot.get("run_status"),
            "run_id": snapshot.get("run_id"),
            "paused": snapshot.get("paused"),
            "started_at": snapshot.get("started_at"),
            "finished_at": snapshot.get("finished_at"),
            "last_event_at": snapshot.get("last_event_at"),
            "page_num": snapshot.get("page_num"),
            "current_job": snapshot.get("current_job"),
            "control": get_control_state(),
            "process": process_info,
            "snapshot": snapshot,
        },
        "totals": {
            "applied": sum(1 for job in jobs if job["status"] == "applied"),
            "skipped": sum(1 for job in jobs if job["status"] == "skipped"),
            "failed": sum(1 for job in jobs if job["status"] == "failed"),
            "interesting": sum(1 for job in jobs if job["status"] == "interesting"),
            "discovered_live": snapshot.get("counters", {}).get("discovered", 0),
            "evaluated_live": snapshot.get("counters", {}).get("evaluated", 0),
            "interesting_live": snapshot.get("counters", {}).get("interesting", 0),
            "applied_live": snapshot.get("counters", {}).get("applied", 0),
            "skipped_live": snapshot.get("counters", {}).get("skipped", 0),
            "failed_live": snapshot.get("counters", {}).get("failed", 0),
            "llm_calls": llm_totals["calls"],
            "llm_total_tokens": llm_totals["total_tokens"],
            "llm_total_cost": llm_totals["total_cost"],
            "llm_total_time_seconds": llm_totals["total_time_seconds"],
        },
        "last_run": last_run,
    }


def get_jobs(status: str | None = None, search: str | None = None) -> List[Dict[str, Any]]:
    return _apply_job_filters(_load_jobs_board(), status=status, search=search)


def get_jobs_payload(status: str | None = None, search: str | None = None) -> Dict[str, Any]:
    jobs = _load_jobs_board()
    filtered_jobs = _apply_job_filters(jobs, status=status, search=search)
    return {
        "jobs": filtered_jobs,
        "filtered_count": len(filtered_jobs),
        "total_count": len(jobs),
    }


def get_messages(
    category: str | None = None,
    status: str | None = None,
) -> List[Dict[str, Any]]:
    entries = _read_yaml(MESSAGES_FILE, [])
    if not isinstance(entries, list):
        entries = []

    if category:
        entries = [e for e in entries if e.get("category") == category]
    if status:
        entries = [e for e in entries if e.get("processing_status") == status]

    entries.sort(key=lambda e: e.get("updated_at") or "", reverse=True)
    return entries


def get_live_state() -> Dict[str, Any]:
    sync_process_state()
    return {
        "snapshot": get_snapshot(),
        "events": read_events(limit=120),
        "control": get_control_state(),
        "process": get_process_info(),
        "paths": {
            "events": str(EVENTS_FILE.relative_to(ROOT_DIR)),
            "snapshot": str(SNAPSHOT_FILE.relative_to(ROOT_DIR)),
            "control": str(CONTROL_FILE.relative_to(ROOT_DIR)),
        },
    }


def get_run_events(run_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    return read_events_for_run(run_id=run_id, limit=limit)


def get_run_jobs(
    run_id: str, status: str | None = None, search: str | None = None
) -> List[Dict[str, Any]]:
    return _apply_job_filters(_build_run_jobs(run_id), status=status, search=search)


def get_run_jobs_payload(
    run_id: str, status: str | None = None, search: str | None = None
) -> Dict[str, Any]:
    jobs = _build_run_jobs(run_id)
    filtered_jobs = _apply_job_filters(jobs, status=status, search=search)
    return {
        "run_id": run_id,
        "jobs": filtered_jobs,
        "filtered_count": len(filtered_jobs),
        "total_count": len(jobs),
    }


def get_run_detail(run_id: str) -> Dict[str, Any]:
    runs = {run["run_id"]: run for run in get_run_history()}
    return {
        "run": runs.get(
            run_id,
            {
                "run_id": run_id,
                "status": "unknown",
                "started_at": None,
                "finished_at": None,
                "last_event_at": None,
                "last_message": None,
                "jobs": {
                    "applied": 0,
                    "skipped": 0,
                    "failed": 0,
                    "interesting": 0,
                    "discovered": 0,
                },
            },
        ),
        "jobs": get_run_jobs(run_id),
        "events": get_run_events(run_id, limit=120),
        "screenshots": get_run_screenshots(run_id),
    }


def get_run_screenshots(run_id: str) -> List[Dict[str, Any]]:
    screenshots = get_screenshot_history(run_id)
    screenshots.sort(key=lambda entry: entry.get("timestamp") or "", reverse=True)
    return screenshots


def get_run_history() -> List[Dict[str, Any]]:
    sync_process_state()
    history = _build_run_history()
    snapshot = get_snapshot()

    if snapshot.get("run_id") and not any(run["run_id"] == snapshot["run_id"] for run in history):
        history.insert(
            0,
            {
                "run_id": snapshot.get("run_id"),
                "status": snapshot.get("run_status"),
                "started_at": snapshot.get("started_at"),
                "finished_at": snapshot.get("finished_at"),
                "last_event_at": snapshot.get("last_event_at"),
                "last_message": (
                    snapshot.get("current_job", {}).get("stage")
                    if snapshot.get("current_job")
                    else None
                ),
                "jobs": {
                    "applied": snapshot.get("counters", {}).get("applied", 0),
                    "skipped": snapshot.get("counters", {}).get("skipped", 0),
                    "failed": snapshot.get("counters", {}).get("failed", 0),
                    "interesting": snapshot.get("counters", {}).get("interesting", 0),
                    "discovered": snapshot.get("counters", {}).get("discovered", 0),
                },
            },
        )

    return history


def get_search_config() -> Dict[str, Any]:
    config = _read_yaml(ROOT_DIR / SEARCH_CONFIG_FILE, {})
    date_config = config.setdefault("date", {})
    if "day_24_hours" in date_config and "24_hours" not in date_config:
        date_config["24_hours"] = bool(date_config.pop("day_24_hours"))
    return config


def update_search_config(config: Dict[str, Any]) -> Dict[str, Any]:
    config = deepcopy(config)
    date_config = config.setdefault("date", {})
    if "24_hours" in date_config:
        date_config["day_24_hours"] = date_config["24_hours"]

    validated = SearchConfig(**config).model_dump()
    validated_date = validated.setdefault("date", {})
    validated_date["24_hours"] = bool(validated_date.pop("day_24_hours", False))

    save_yaml_file(ROOT_DIR / SEARCH_CONFIG_FILE, validated, sort_keys=False)
    return validated


def get_app_config() -> Dict[str, Any]:
    content = APP_CONFIG_FILE.read_text(encoding="utf-8")
    tree = ast.parse(content)
    values: Dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        key = node.targets[0].id
        if key not in EDITABLE_APP_CONFIG_KEYS:
            continue
        try:
            values[key] = ast.literal_eval(node.value)
        except Exception:
            continue
    return values


def update_app_config(changes: Dict[str, Any]) -> Dict[str, Any]:
    unsupported = sorted(set(changes) - EDITABLE_APP_CONFIG_KEYS)
    if unsupported:
        raise ValueError(f"Unsupported app config keys: {', '.join(unsupported)}")

    lines = APP_CONFIG_FILE.read_text(encoding="utf-8").splitlines()
    for key, value in changes.items():
        replacement = f"{key} = {json.dumps(value) if isinstance(value, str) else repr(value)}"
        for index, line in enumerate(lines):
            if re.match(rf"^{re.escape(key)}\s*=", line):
                lines[index] = replacement
                break
        else:
            raise ValueError(f"Could not locate app config key: {key}")

    APP_CONFIG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return get_app_config()
