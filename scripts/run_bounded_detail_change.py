"""Cloud orchestration for a reviewed, bounded detail correction.

All DB mutations go through report_apply.apply_change_requests. This entry point
adds snapshot, whole-DB scope, projection parity and CAS checks around it.
"""
import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from master_rdb.master_db import file_sha256
from report_apply.apply_change_requests import (
    _source_evidence_id, run as apply_requests, validate_apply_allowed, validate_payload,
)
from export_public_events import build_public_events, load_public_projection_inputs, project_public_events, clean_public_text, public_detail_text


ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    "occ_35fcf0374711a3bd": ("2026-10-10", "小山台小学校"),
    "occ_ba6a308f4bcbfff2": ("2026-10-18", "京陽小学校"),
    "occ_400f1f551ca689a7": ("2026-10-11", "上神明小学校"),
}
SUMMARY_URL = "https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html"
FOURTH_URL = "https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/shisetsu-kuyakusyo-chiiki-eba4/shisetsu-kuyakusyo-chiiki-eba4-oshirase/20260911090941.html"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_control(control):
    require(control.get("operation") == "ebara_official_20261010", "unknown operation")
    require(control.get("stage") in {"dry_run", "apply"}, "unknown stage")
    require(re.fullmatch(r"[0-9a-f]{40}", control.get("request_ref", "")), "request_ref must be immutable")
    require(control.get("request_path") in {
        "data/change_requests/ebara_official_20261010.json",
        "data/change_requests/ebara_official_20261010_reviewed.json",
    }, "unexpected request path")
    require(set(control.get("scope", {})) == set(ALLOWED), "scope must contain exactly the three approved occurrences")
    for field in ("request_sha256", "collector_public_sha256"):
        require(re.fullmatch(r"[0-9a-f]{64}", control.get(field, "")), f"invalid {field}")
    for scope in control["scope"].values():
        for field in ("expected_detail_sha256", "expected_master_detail_sha256"):
            require(re.fullmatch(r"[0-9a-f]{64}", scope.get(field, "")), f"invalid scoped {field}")
    if control["stage"] == "apply":
        require(control["request_path"].endswith("_reviewed.json"), "apply requires reviewed requests")
        require(re.fullmatch(r"[0-9a-f]{64}", control.get("expected_remote_checksum", "")), "apply requires reviewed remote checksum")
        require(isinstance(control.get("reviewed_run_id"), int) and control["reviewed_run_id"] > 0, "apply requires reviewed dry-run run ID")
        require(control.get("reviewed_by") and control.get("review_note"), "apply requires manual review attestation")
    return control


def validate_requests(control, path):
    require(file_sha256(path) == control["request_sha256"], "request snapshot mismatch")
    payload = read(path)
    validate_payload(payload)
    requests = payload["requests"]
    require(len(requests) == 3 and {r["occurrence_id"] for r in requests} == set(ALLOWED), "request scope mismatch")
    for request in requests:
        identifier = request["occurrence_id"]
        require(request["change_type"] == "confirm_current_year_date", "only finite date/detail confirmation is supported")
        require(request["event_year"] == 2026 and request["date_start"] == ALLOWED[identifier][0], "date changes are outside scope")
        require(request.get("detail_and_source_only") is True and "confidence" not in request, "occurrence facts must be preserved")
        require(request.get("date_end") in {None, request["date_start"]}, "date range changes are outside scope")
        require(not any(k in request for k in ("venue", "predicted_date_id", "expected_source_url")), "unsupported side effects")
        source = request["source"]
        require(source["kind"] == "official_current_year" and source["url"] == (FOURTH_URL if identifier == "occ_400f1f551ca689a7" else SUMMARY_URL), "source outside approved official evidence")
        approved = control["scope"][identifier]
        require(request["detail_replacement"] == approved["detail_replacement"] and request["expected_detail_sha256"] == approved["expected_master_detail_sha256"], "detail differs from approved snapshot")
    if control["stage"] == "apply":
        validate_apply_allowed(payload)
        require(payload.get("reviewed_by") == control["reviewed_by"], "reviewer mismatch")
    else:
        require(all(r.get("dry_run_only") is True for r in requests), "initial dry-run must use unpromoted requests")
    return payload


def inspect_master(db, requests, approved=None):
    with sqlite3.connect(db) as conn:
        for request in requests:
            identifier = request["occurrence_id"]
            row = conn.execute("SELECT o.date_start, o.date_end, v.canonical_name, o.detail, o.event_year FROM event_occurrences o LEFT JOIN venues v ON v.venue_id=o.venue_id WHERE o.occurrence_id=?", (identifier,)).fetchone()
            require(row is not None, f"missing occurrence: {identifier}")
            require((row[0], row[2]) == ALLOWED[identifier] and row[1] in {None, "", row[0]} and row[4] == 2026, f"master date/venue mismatch: {identifier}")
            current_hash = hashlib.sha256((row[3] or "").encode()).hexdigest()
            require(current_hash == request["expected_detail_sha256"], f"master detail hash mismatch: {identifier}")
            if approved is not None:
                public_hash = hashlib.sha256(public_detail_text(clean_public_text(row[3])).encode()).hexdigest()
                require(public_hash == approved[identifier]["expected_detail_sha256"], f"master public detail mismatch: {identifier}")


def diagnose_master(db, today):
    """Only the authorized three identities and public facts/hashes leave the runner."""
    projected = {row["occurrence_id"]: row for row in project(db, today)
        if row["occurrence_id"] in ALLOWED}
    diagnostics = []
    with sqlite3.connect(db) as conn:
        for identifier, (expected_date, expected_venue) in ALLOWED.items():
            row = conn.execute("SELECT o.date_start, o.date_end, v.canonical_name, o.detail, o.event_year FROM event_occurrences o LEFT JOIN venues v ON v.venue_id=o.venue_id WHERE o.occurrence_id=?", (identifier,)).fetchone()
            public = projected.get(identifier)
            diagnostics.append({
                "occurrence_id": identifier,
                "expected": {"date_start": expected_date, "venue": expected_venue, "event_year": 2026},
                "master": None if row is None else {"date_start": row[0], "date_end": row[1],
                    "venue": row[2], "event_year": row[4],
                    "detail_sha256": hashlib.sha256((row[3] or "").encode()).hexdigest()},
                "public_projection": None if public is None else {"date_start": public.get("date"),
                    "date_end": public.get("date_end"), "venue": public.get("venue"),
                    "event_year": public.get("event_year"),
                    "detail_sha256": hashlib.sha256((public.get("detail") or "").encode()).hexdigest()},
            })
    return diagnostics


def verify_db_scope(before, after, requests):
    """Reject differences anywhere outside the three occurrences and their evidence."""
    identifiers = sorted(ALLOWED)
    evidence_ids = sorted(_source_evidence_id(r) for r in requests)
    restrictions = {
        "event_occurrences": ("occurrence_id", identifiers),
        "occurrence_evidence_links": ("occurrence_id", identifiers),
        "evidence_items": ("evidence_id", evidence_ids),
    }
    differences = {}
    with sqlite3.connect(after) as conn:
        conn.execute("ATTACH DATABASE ? AS before", (str(before),))
        schema = "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        require(set(conn.execute(schema)) == set(conn.execute(schema.replace("sqlite_master", "before.sqlite_master"))), "schema changed")
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            quoted = '"' + table.replace('"', '""') + '"'
            column, values = restrictions.get(table, (None, []))
            where = f" WHERE {column} NOT IN ({','.join('?' for _ in values)})" if column else ""
            for left, right in (("main", "before"), ("before", "main")):
                sql = f"SELECT * FROM {left}.{quoted}{where} EXCEPT SELECT * FROM {right}.{quoted}{where} LIMIT 1"
                require(conn.execute(sql, values + values).fetchone() is None, f"out-of-scope DB change: {table}")
            count = conn.execute(f"SELECT COUNT(*) FROM (SELECT * FROM main.{quoted} EXCEPT SELECT * FROM before.{quoted})").fetchone()[0]
            if count:
                differences[table] = count
        for identifier in identifiers:
            conn.row_factory = sqlite3.Row
            old = conn.execute("SELECT * FROM before.event_occurrences WHERE occurrence_id=?", (identifier,)).fetchone()
            new = conn.execute("SELECT * FROM main.event_occurrences WHERE occurrence_id=?", (identifier,)).fetchone()
            require(old is not None and new is not None, f"occurrence membership changed: {identifier}")
            changed = sorted(key for key in old.keys() if old[key] != new[key])
            require(set(changed) <= {"detail", "source_url", "updated_at"}, f"occurrence fact changed: {identifier}")
    return differences


def project(db, today):
    events, *_ = build_public_events(target_year=2026, db_path=str(db))
    return project_public_events(events, target_year=2026, today=today,
        inputs=load_public_projection_inputs(target_year=2026, db_path=str(db)))["public_events"]


def bounded_public_rows(before, after, baseline, requests):
    def index(rows):
        indexed = {r["occurrence_id"]: r for r in rows}
        require(len(indexed) == len(rows), "duplicate public occurrence")
        return indexed
    old, new, published = map(index, (before, after, baseline))
    require(set(old) == set(new), "projection membership changed")
    request_by_id = {r["occurrence_id"]: r for r in requests}
    result = []
    for identifier in old:
        changes = {k for k in old[identifier].keys() | new[identifier].keys() if old[identifier].get(k) != new[identifier].get(k)}
        require(not changes or identifier in ALLOWED and changes <= {"detail", "source_urls"}, f"out-of-scope projection change: {identifier}")
        if identifier not in ALLOWED:
            continue
        require(identifier in published, f"public occurrence missing: {identifier}")
        target = published[identifier]
        require((target["date"], target["venue"]) == ALLOWED[identifier], f"published identity mismatch: {identifier}")
        request = request_by_id[identifier]
        require(old[identifier]["detail"] == target["detail"], f"master public detail differs from published snapshot: {identifier}")
        require(new[identifier]["detail"] == request["detail_replacement"], f"replacement did not reach public projection: {identifier}")
        result.append({"occurrence_id": identifier, "detail": new[identifier]["detail"], "source_urls": new[identifier]["source_urls"]})
    require(len(result) == 3, "public scope incomplete")
    return sorted(result, key=lambda r: r["occurrence_id"])


def execute(args):
    control = validate_control(read(args.control))
    if args.validate_only:
        return {"stage": control["stage"], "request_ref": control["request_ref"]}
    payload = validate_requests(control, args.requests)
    require(file_sha256(ROOT / "data/public/events_public.json") == control["collector_public_sha256"], "collector public snapshot changed; review again")
    checksum = file_sha256(args.master_db)
    if control["stage"] == "apply":
        require(checksum == control["expected_remote_checksum"], "master changed since reviewed dry-run; repeat review")
    args.output.mkdir(parents=True, exist_ok=True)
    diagnostics = diagnose_master(args.master_db, args.today)
    (args.output / "diagnostics.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n")
    print("BOUNDED_DETAIL_DIAGNOSTICS=" + json.dumps(diagnostics, ensure_ascii=False, separators=(",", ":")), flush=True)
    inspect_master(args.master_db, payload["requests"], control["scope"])
    baseline_db = args.output / "before.sqlite"
    shutil.copy2(args.master_db, baseline_db)
    dry_db = args.output / "dry-run.sqlite"
    def apply_to(dry):
        return apply_requests(argparse.Namespace(requests=args.requests, master_db=args.master_db,
            out_db=dry_db, out_json=args.output / ("dry-run.json" if dry else "apply.json"),
            out_md=args.output / ("dry-run.md" if dry else "apply.md"), apply=not dry,
            confirm="" if dry else "APPLY CHANGE REQUESTS"))
    result = apply_to(True)
    require(not result["issues"] and not result["audit"]["issues_by_severity"].get("high")
        and len(result["applied"]["requests_applied"]) == 3, "dry-run did not resolve exactly three requests or audit failed")
    db_changes = verify_db_scope(baseline_db, dry_db, payload["requests"])
    with sqlite3.connect(dry_db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("ATTACH DATABASE ? AS before", (str(baseline_db),))
        occurrence_columns = {}
        for identifier in ALLOWED:
            old = conn.execute("SELECT * FROM before.event_occurrences WHERE occurrence_id=?", (identifier,)).fetchone()
            new = conn.execute("SELECT * FROM main.event_occurrences WHERE occurrence_id=?", (identifier,)).fetchone()
            occurrence_columns[identifier] = sorted(key for key in old.keys() if old[key] != new[key])
    baseline_projection = project(baseline_db, args.today)
    rows = bounded_public_rows(baseline_projection, project(dry_db, args.today), read(ROOT / "data/public/events_public.json"), payload["requests"])
    receipt = {"stage": control["stage"], "request_ref": control["request_ref"], "request_sha256": control["request_sha256"], "fetched_checksum": checksum, "db_changes": db_changes, "occurrence_changed_columns": occurrence_columns, "master_public_detail_matches": True, "public_rows": rows}
    if control["stage"] == "apply":
        applied = apply_to(False)
        require(not applied["issues"] and applied["write_guard"]["db_committed"], "apply failed")
        verify_db_scope(baseline_db, args.master_db, payload["requests"])
        require(rows == bounded_public_rows(baseline_projection, project(args.master_db, args.today), read(ROOT / "data/public/events_public.json"), payload["requests"]), "apply projection differs from dry-run")
        receipt["published_checksum"] = file_sha256(args.master_db)
        subprocess.run([sys.executable, "master_db_s3_artifact.py", "--db", str(args.master_db), "publish", "--expect-remote-checksum", checksum, "--snapshot-id", args.snapshot_id], cwd=ROOT, check=True)
        subprocess.run([sys.executable, "master_db_s3_artifact.py", "--db", str(args.master_db), "fetch", "--overwrite"], cwd=ROOT, check=True)
        require(file_sha256(args.master_db) == receipt["published_checksum"], "published DB refetch checksum mismatch")
        require(rows == bounded_public_rows(baseline_projection, project(args.master_db, args.today), read(ROOT / "data/public/events_public.json"), payload["requests"]), "published projection differs")
    (args.output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print("BOUNDED_DETAIL_RECEIPT=" + json.dumps(receipt, ensure_ascii=False, separators=(",", ":")))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--requests", type=Path)
    parser.add_argument("--master-db", type=Path, default=ROOT / "data/bon_odori_master.sqlite")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--today")
    parser.add_argument("--snapshot-id")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if not args.validate_only:
        if not all((args.requests, args.output, args.today)):
            parser.error("requests, output and today required")
        if read(args.control).get("stage") == "apply" and not args.snapshot_id:
            parser.error("apply requires unique snapshot-id")
    execute(args)


if __name__ == "__main__":
    main()
