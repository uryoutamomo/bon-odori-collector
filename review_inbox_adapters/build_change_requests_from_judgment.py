#!/usr/bin/env python3
"""Turn accepted identity judgments into apply_change_requests.py requests.

The agent answers identity only -- which existing occurrence, series and venue this candidate
already is, or the literal "none". Picking the change type from that answer needs the whole
picture, so the machine does it here, reading the frozen candidate payload E0 wrote.

This module never writes to Master RDB. It opens the database read-only and emits a request file
for `python3 -m report_apply.apply_change_requests`, which keeps its own dry-run, backup, audit and
rollback guards (docs/local-judgment-e2-identity-to-change-request-v1.md).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from master_rdb.master_db import MASTER_DB, stable_id
from review_inbox_adapters.local_judgment_contract import IDENTITY_MATCH_NONE, IDENTITY_PAYLOAD_FIELDS

OUT_JSON = Path("data/change_requests/from_judgment.json")
OUT_MD = Path("data/change_requests/from_judgment.md")

# The apply layer only accepts these three source kinds for current-year facts, so the report type
# is mapped onto them rather than passed through as free text.
SOURCE_KINDS = {
    "official_notice": "official_current_year",
    "review_console_change_request": "official_current_year",
    "firsthand_new_event": "organizer_current_year",
}
# What the original proposal was asking for, when the answer says the occurrence already exists.
UPDATE_CHANGE_TYPES = {
    "add_historical_reference": "add_historical_reference",
    "update_venue": "update_venue",
}


def _json(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _identity_of(conn, decision) -> tuple[dict[str, str] | None, str | None]:
    """Return the identity answer for a terminal decision, and whose decision carried it.

    A user's accept only records that the hold was approved; the identity itself was answered by
    the agent that opened the hold, so it is read back through prior_agent_attempt_id.
    """
    payload = _json(decision["payload_json"], {})
    if IDENTITY_PAYLOAD_FIELDS <= set(payload):
        return {field: payload[field] for field in IDENTITY_PAYLOAD_FIELDS}, decision["decision_id"]
    prior = decision["prior_agent_attempt_id"]
    if not prior:
        return None, None
    row = conn.execute(
        "SELECT decision_id, payload_json FROM canonical_decision_ledger WHERE decision_id = ?",
        (prior,),
    ).fetchone()
    if not row:
        return None, None
    prior_payload = _json(row["payload_json"], {})
    if IDENTITY_PAYLOAD_FIELDS <= set(prior_payload):
        return {field: prior_payload[field] for field in IDENTITY_PAYLOAD_FIELDS}, row["decision_id"]
    return None, None


def _source_block(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform": "web",
        "url": report.get("source_url") or "",
        "kind": SOURCE_KINDS.get(report.get("report_type"), "official_current_year"),
        "title": report.get("source_title") or "",
    }


def _venue_block(identity: dict[str, str], proposal: dict[str, Any]) -> dict[str, Any]:
    if identity["venue_match"] != IDENTITY_MATCH_NONE:
        return {"venue_id": identity["venue_match"]}
    name = (proposal.get("venue") or {}).get("name")
    return {"name": name} if name else {}


def build_request(decision, identity: dict[str, str], candidate: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Return (request, reason). A None request carries the reason it could not be built."""
    proposal = candidate.get("proposal") or {}
    report = candidate.get("report") or {}
    source = _source_block(report)
    if not source["url"]:
        return None, "missing_source_url"
    request: dict[str, Any] = {
        "request_id": stable_id("chrq", decision["decision_id"]),
        "source": source,
        "note": proposal.get("detail_addendum") or "",
        "decision_id": decision["decision_id"],
    }
    venue = _venue_block(identity, proposal)
    if identity["occurrence_match"] != IDENTITY_MATCH_NONE:
        change_type = UPDATE_CHANGE_TYPES.get(proposal.get("legacy_action") or "", "confirm_current_year_date")
        request["change_type"] = change_type
        request["occurrence_id"] = identity["occurrence_match"]
        if change_type == "add_historical_reference":
            if not proposal.get("historical_year") or not proposal.get("historical_date"):
                return None, "missing_historical_date"
            request["event_year"] = proposal.get("event_year")
            request["historical_year"] = int(proposal["historical_year"])
            request["historical_date"] = proposal["historical_date"]
            return request, None
        if change_type == "update_venue":
            if not venue:
                return None, "missing_venue"
            request["venue"] = venue
            return request, None
        # 日付確定では会場を運ばない。会場を変えるのは update_venue だけの仕事にしておかないと、
        # 日付を直したつもりで会場が差し替わる。
        if not proposal.get("date_start") or not proposal.get("event_year"):
            return None, "missing_current_year_date"
        request["event_year"] = int(proposal["event_year"])
        request["date_start"] = proposal["date_start"]
        request["date_end"] = proposal.get("date_end") or proposal["date_start"]
        return request, None

    if not proposal.get("date_start") or not proposal.get("event_year"):
        return None, "missing_current_year_date"
    if not venue:
        return None, "missing_venue"
    display_name = proposal.get("event_name_hint")
    if not display_name:
        return None, "missing_event_name"
    request.update(
        {
            "display_name": display_name,
            "event_year": int(proposal["event_year"]),
            "date_start": proposal["date_start"],
            "date_end": proposal.get("date_end") or proposal["date_start"],
            "venue": venue,
        }
    )
    if identity["series_match"] != IDENTITY_MATCH_NONE:
        request["change_type"] = "create_current_year_occurrence"
        request["series_id"] = identity["series_match"]
        return request, None
    request["change_type"] = "create_event_series"
    request["series_name"] = display_name
    return request, None


def build_payload(conn) -> tuple[dict[str, Any], dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    decisions = conn.execute(
        """
        SELECT decision_id, inbox_id, domain, lane, action, actor_type, payload_json,
               prior_agent_attempt_id, decided_at
        FROM canonical_decision_ledger
        WHERE domain = 'event' AND action = 'accept' AND queue_state_after = 'closed'
        ORDER BY decided_at, decision_id
        """
    ).fetchall()
    requests: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for decision in decisions:
        if decision["decision_id"] in seen:
            continue
        seen.add(decision["decision_id"])
        identity, _carrier = _identity_of(conn, decision)
        if identity is None:
            skipped.append({"decision_id": decision["decision_id"], "reason": "identity_answer_missing"})
            continue
        row = conn.execute(
            "SELECT payload_json FROM review_inbox_items WHERE inbox_id = ?", (decision["inbox_id"],)
        ).fetchone()
        if not row:
            skipped.append({"decision_id": decision["decision_id"], "reason": "candidate_missing"})
            continue
        request, reason = build_request(decision, identity, _json(row["payload_json"], {}))
        if request is None:
            skipped.append({"decision_id": decision["decision_id"], "reason": reason})
            continue
        requests.append(request)
    payload = {
        "request_type": "rdb_change_requests",
        "generated_by": "build_change_requests_from_judgment.py",
        "scope": "accepted_identity_judgments",
        "requests": requests,
    }
    report = {
        "generated_by": payload["generated_by"],
        "decisions_read": len(decisions),
        "request_count": len(requests),
        "skipped_count": len(skipped),
        "change_types": {
            change_type: sum(1 for request in requests if request["change_type"] == change_type)
            for change_type in sorted({request["change_type"] for request in requests})
        },
        "skipped": skipped,
    }
    return payload, report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Change requests from accepted judgments",
        "",
        f"- decisions_read: {report['decisions_read']}",
        f"- request_count: {report['request_count']}",
        f"- skipped_count: {report['skipped_count']}",
        "",
        "## Change types",
        "",
    ]
    for change_type, count in report["change_types"].items():
        lines.append(f"- {change_type}: {count}")
    lines.extend(["", "## Skipped", ""])
    if not report["skipped"]:
        lines.append("- none")
    for entry in report["skipped"]:
        lines.append(f"- {entry['decision_id']}: {entry['reason']}")
    lines.append("")
    return "\n".join(lines)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(args) -> dict[str, Any]:
    # Read-only: this step decides nothing and writes nothing to the master database.
    conn = sqlite3.connect(f"file:{Path(args.db)}?mode=ro", uri=True)
    try:
        payload, report = build_payload(conn)
    finally:
        conn.close()
    write_json(Path(args.out_json), payload)
    Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_md).write_text(render_markdown(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=MASTER_DB)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    args = parser.parse_args()
    report = run(args)
    print(
        "change requests from judgment: "
        f"decisions_read={report['decisions_read']} requests={report['request_count']} "
        f"skipped={report['skipped_count']} out={args.out_json}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
