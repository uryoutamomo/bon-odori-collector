"""Apply reviewed public_intro copies from Notion snapshot drift decisions.

Default mode writes to a copied SQLite DB. Apply mode mutates only the master
RDB and does not write Notion or public JSON.
"""

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from master_db import MASTER_DB, connect_existing, refresh_manifest_database_state


DATA = Path("data")
DECISIONS = DATA / "notion_snapshot_master_drift_decisions.json"
OUT_DB = DATA / "notion_drift_public_intro_dry_run.sqlite"
OUT_JSON = DATA / "notion_drift_public_intro_apply_report.json"
OUT_MD = DATA / "notion_drift_public_intro_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY NOTION DRIFT PUBLIC INTRO"


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_db(source, out_db):
    out_db = Path(out_db)
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    shutil.copy2(source, out_db)


def backup_db(source, now):
    source = Path(source)
    stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z")
    backup = BACKUP_DIR / f"{source.stem}.{stamp}{source.suffix}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def load_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def build_plan(decisions):
    planned = []
    skipped = []
    for row in decisions.get("decisions") or []:
        if row.get("decision") != "candidate_copy_notion_public_intro":
            continue
        item = {
            "decision_id": row.get("decision_id") or "",
            "entity_type": row.get("entity_type") or "",
            "series_id": row.get("entity_id") or "",
            "title": row.get("title") or "",
            "field": row.get("field") or "",
            "public_intro": row.get("notion_snapshot_value") or "",
            "reason": row.get("reason") or "",
        }
        if not row.get("apply_ready"):
            skipped.append({**item, "skip_reason": "decision_not_apply_ready"})
        elif item["entity_type"] != "event_series" or item["field"] != "public_intro":
            skipped.append({**item, "skip_reason": "unsupported_decision_target"})
        elif not item["series_id"] or not item["public_intro"]:
            skipped.append({**item, "skip_reason": "missing_series_or_intro"})
        else:
            planned.append(item)
    return planned, skipped


def apply_plan(conn, planned, now):
    applied = []
    skipped = []
    for item in planned:
        current = rows(
            conn,
            """
            SELECT series_id, canonical_name, public_intro
            FROM event_series
            WHERE series_id = ?
            """,
            (item["series_id"],),
        )
        if not current:
            skipped.append({**item, "skip_reason": "missing_event_series"})
            continue
        before = current[0]
        if before.get("public_intro"):
            skipped.append({**item, "skip_reason": "master_public_intro_already_set", "before": before})
            continue
        conn.execute(
            """
            UPDATE event_series
            SET public_intro = ?,
                updated_at = ?
            WHERE series_id = ?
            """,
            (item["public_intro"], now, item["series_id"]),
        )
        after = rows(
            conn,
            """
            SELECT series_id, canonical_name, public_intro
            FROM event_series
            WHERE series_id = ?
            """,
            (item["series_id"],),
        )[0]
        applied.append({**item, "before": before, "after": after})
    return applied, skipped


def render_markdown(result):
    summary = result["summary"]
    lines = [
        "# Notion drift public intro apply report",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- applied: {result['applied']}",
        f"- planned_count: {summary['planned_count']}",
        f"- applied_count: {summary['applied_count']}",
        f"- skipped_count: {summary['skipped_count']}",
        "- writes: Master RDB only; Notion and public JSON untouched",
        "",
        "## Applied",
        "",
    ]
    if not result["applied_items"]:
        lines.append("- none")
    for item in result["applied_items"]:
        lines.append(f"- {item['title']}: public_intro copied from Notion snapshot")
    if result["skipped_items"]:
        lines.extend(["", "## Skipped", ""])
        for item in result["skipped_items"]:
            lines.append(f"- {item.get('title') or item.get('series_id')}: {item.get('skip_reason')}")
    return "\n".join(lines) + "\n"


def run(args):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    decisions = load_json(args.decisions)
    planned, pre_skipped = build_plan(decisions)

    if args.apply:
        if args.confirm != CONFIRM:
            raise SystemExit(f"--confirm must be exactly: {CONFIRM}")
        target_db = Path(args.master_db)
        backup = str(backup_db(target_db, now))
    else:
        target_db = Path(args.out_db)
        copy_db(args.master_db, target_db)
        backup = ""

    with connect_existing(target_db) as conn:
        applied_items, skipped_items = apply_plan(conn, planned, now)
        skipped_items = pre_skipped + skipped_items
        conn.commit()

    result = {
        "generated_by": "apply_notion_drift_public_intro.py",
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "applied": bool(args.apply),
        "master_db": str(args.master_db),
        "target_db": str(target_db),
        "backup": backup,
        "decisions": str(args.decisions),
        "summary": {
            "planned_count": len(planned),
            "applied_count": len(applied_items),
            "skipped_count": len(skipped_items),
        },
        "applied_items": applied_items,
        "skipped_items": skipped_items,
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    if args.apply:
        refresh_manifest_database_state(Path(args.master_db))
    print(
        "notion drift public intro: "
        f"mode={result['mode']} applied_count={len(applied_items)} "
        f"skipped_count={len(skipped_items)} out={args.out_json}"
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--decisions", type=Path, default=DECISIONS)
    parser.add_argument("--out-db", type=Path, default=OUT_DB)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
