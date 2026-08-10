import json
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
HTTP_402_FAILURE_THRESHOLD = 1


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def new_health_report(*, collection_enabled, collection_required=False, started_at=None):
    return {
        "schema_version": SCHEMA_VERSION,
        "collection_enabled": bool(collection_enabled),
        "collection_required": bool(collection_required),
        "started_at": started_at or _now_iso(),
        "finished_at": None,
        "status": "pending",
        "failure_reasons": [],
        "warnings": [],
        "totals": {},
        "lanes": {},
    }


def _lane(report, lane_name):
    return report["lanes"].setdefault(
        lane_name,
        {
            "planned_units": 0,
            "completed_units": 0,
            "attempts": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "http_errors": {},
            "tweets_fetched": 0,
            "items_accepted": 0,
            "estimated_cost_usd": 0.0,
            "skipped_reason": None,
            "units": {},
        },
    )


def _unit(report, lane_name, unit_id):
    lane = _lane(report, lane_name)
    return lane["units"].setdefault(
        str(unit_id),
        {
            "attempts": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "http_errors": {},
            "tweets_fetched": 0,
            "items_accepted": 0,
            "estimated_cost_usd": 0.0,
            "completed": False,
            "incomplete_reason": None,
        },
    )


def set_planned_units(report, lane_name, count):
    if report is None:
        return
    _lane(report, lane_name)["planned_units"] = int(count)


def mark_lane_skipped(report, lane_name, reason):
    if report is None:
        return
    _lane(report, lane_name)["skipped_reason"] = str(reason)


def record_attempt(report, lane_name, unit_id):
    if report is None:
        return
    lane = _lane(report, lane_name)
    unit = _unit(report, lane_name, unit_id)
    lane["attempts"] += 1
    unit["attempts"] += 1


def record_success(report, lane_name, unit_id, *, tweets_fetched, estimated_cost_usd):
    if report is None:
        return
    lane = _lane(report, lane_name)
    unit = _unit(report, lane_name, unit_id)
    lane["successful_requests"] += 1
    unit["successful_requests"] += 1
    lane["tweets_fetched"] += int(tweets_fetched)
    unit["tweets_fetched"] += int(tweets_fetched)
    lane["estimated_cost_usd"] += float(estimated_cost_usd)
    unit["estimated_cost_usd"] += float(estimated_cost_usd)


def record_failure(report, lane_name, unit_id, *, error, http_status=None):
    if report is None:
        return
    lane = _lane(report, lane_name)
    unit = _unit(report, lane_name, unit_id)
    lane["failed_requests"] += 1
    unit["failed_requests"] += 1
    unit["incomplete_reason"] = str(error)[:500]
    if http_status is not None:
        key = str(http_status)
        lane["http_errors"][key] = lane["http_errors"].get(key, 0) + 1
        unit["http_errors"][key] = unit["http_errors"].get(key, 0) + 1


def record_accepted(report, lane_name, unit_id, count):
    if report is None:
        return
    lane = _lane(report, lane_name)
    unit = _unit(report, lane_name, unit_id)
    lane["items_accepted"] += int(count)
    unit["items_accepted"] += int(count)


def mark_unit_complete(report, lane_name, unit_id):
    if report is None:
        return
    lane = _lane(report, lane_name)
    unit = _unit(report, lane_name, unit_id)
    if not unit["completed"]:
        unit["completed"] = True
        unit["incomplete_reason"] = None
        lane["completed_units"] += 1


def mark_unit_incomplete(report, lane_name, unit_id, reason):
    if report is None:
        return
    unit = _unit(report, lane_name, unit_id)
    if not unit.get("incomplete_reason"):
        unit["incomplete_reason"] = str(reason)[:500]


def finalize_health_report(report, *, finished_at=None):
    lanes = report.get("lanes") or {}
    totals = {
        "planned_units": sum(lane.get("planned_units", 0) for lane in lanes.values()),
        "completed_units": sum(lane.get("completed_units", 0) for lane in lanes.values()),
        "attempts": sum(lane.get("attempts", 0) for lane in lanes.values()),
        "successful_requests": sum(lane.get("successful_requests", 0) for lane in lanes.values()),
        "failed_requests": sum(lane.get("failed_requests", 0) for lane in lanes.values()),
        "http_402_count": sum(lane.get("http_errors", {}).get("402", 0) for lane in lanes.values()),
        "tweets_fetched": sum(lane.get("tweets_fetched", 0) for lane in lanes.values()),
        "items_accepted": sum(lane.get("items_accepted", 0) for lane in lanes.values()),
        "estimated_cost_usd": round(
            sum(lane.get("estimated_cost_usd", 0.0) for lane in lanes.values()),
            8,
        ),
    }
    failures = []
    warnings = []
    if report.get("collection_required") and not report.get("collection_enabled"):
        failures.append("x_collection_required_but_disabled")
    if report.get("collection_enabled"):
        if totals["http_402_count"] >= HTTP_402_FAILURE_THRESHOLD:
            failures.append(
                f"http_402_threshold:{totals['http_402_count']}>={HTTP_402_FAILURE_THRESHOLD}"
            )
        if totals["items_accepted"] == 0:
            failures.append("x_items_accepted_zero")
        for lane_name, lane in lanes.items():
            planned = lane.get("planned_units", 0)
            completed = lane.get("completed_units", 0)
            if planned and completed < planned:
                warnings.append(f"{lane_name}_units_incomplete:{completed}/{planned}")
    else:
        warnings.append("x_collection_disabled")

    report["finished_at"] = finished_at or _now_iso()
    report["totals"] = totals
    report["failure_reasons"] = failures
    report["warnings"] = warnings
    report["status"] = "unhealthy" if failures else "healthy"
    return report


def render_github_summary(report):
    totals = report.get("totals") or {}
    lines = [
        "## X collection health",
        "",
        f"- status: **{report.get('status', 'unknown')}**",
        (
            f"- required / enabled: {report.get('collection_required', False)} / "
            f"{report.get('collection_enabled', False)}"
        ),
        f"- accepted: {totals.get('items_accepted', 0)}",
        f"- fetched: {totals.get('tweets_fetched', 0)}",
        f"- HTTP 402: {totals.get('http_402_count', 0)}",
        f"- estimated cost: ${totals.get('estimated_cost_usd', 0.0):.5f}",
        "",
        "| lane / query or batch | requests ok/failed | accepted | HTTP 402 | cost | state |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for lane_name, lane in (report.get("lanes") or {}).items():
        if not lane.get("units"):
            state = f"skipped: {lane.get('skipped_reason')}" if lane.get("skipped_reason") else "no units"
            lines.append(f"| {lane_name} | 0/0 | 0 | 0 | $0.00000 | {state} |")
            continue
        for unit_id, unit in lane["units"].items():
            state = "complete" if unit.get("completed") else (unit.get("incomplete_reason") or "incomplete")
            lines.append(
                f"| {lane_name} / {unit_id} | "
                f"{unit.get('successful_requests', 0)}/{unit.get('failed_requests', 0)} | "
                f"{unit.get('items_accepted', 0)} | "
                f"{unit.get('http_errors', {}).get('402', 0)} | "
                f"${unit.get('estimated_cost_usd', 0.0):.5f} | {state} |"
            )
    if report.get("failure_reasons"):
        lines.extend(["", "### Failure reasons", ""])
        lines.extend(f"- `{reason}`" for reason in report["failure_reasons"])
    if report.get("warnings"):
        lines.extend(["", "### Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def write_health_report(report, path, *, github_summary_path=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if github_summary_path:
        with Path(github_summary_path).open("a", encoding="utf-8") as handle:
            handle.write(render_github_summary(report))


def check_health_report(path):
    path = Path(path)
    if not path.exists():
        print(f"X collection health report missing: {path}")
        return 1
    report = json.loads(path.read_text(encoding="utf-8"))
    print(render_github_summary(report), end="")
    return 1 if report.get("status") != "healthy" else 0
