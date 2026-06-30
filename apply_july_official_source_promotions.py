#!/usr/bin/env python3
"""Promote researched July 2026 source URLs to official current-year sources."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from manual_apply_guards import MASTER_RDB_ONE_OFF_CONFIRMATION, require_confirmation
from master_db import MASTER_DB, MASTER_MANIFEST, connect_existing, refresh_manifest_database_state


DATA = Path("data")
OUT_JSON = DATA / "july_official_source_promotions.json"
OUT_MD = DATA / "july_official_source_promotions.md"
BACKUP_DIR = DATA / "backups"

PROMOTIONS = [
    {
        "event_name": "みたままつり 納涼民踊のつどい",
        "source_url": "https://www.yasukuni.or.jp/schedule/saiji.html#saiji03",
        "reason": "靖国神社公式の祭事ページで、みたままつり 7月13日〜16日と期間中の盆踊りを確認。",
    },
    {
        "event_name": "佐竹ゲバゲバ盆踊り",
        "source_url": "https://satakeshotengai.com/satakeodori/",
        "reason": "佐竹商店街公式サイトのサタケオドリ専用ページで、2026年7月18日開催と佐竹ゲバゲバ盆踊りの内容を確認。",
    },
    {
        "event_name": "品川区民まつり 品川第二地区",
        "source_url": "https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html",
        "reason": "品川区公式ページで、2026年7月25日〜26日の天妙国寺境内の盆踊りを確認。既存URLの source_kind を公式扱いへ補正。",
    },
]


def rows(conn, query, params=()):
    conn.row_factory = __import__("sqlite3").Row
    return [dict(row) for row in conn.execute(query, params)]


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def backup_db(source: Path, now: str) -> Path:
    stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z")
    backup = BACKUP_DIR / f"{source.stem}.{stamp}{source.suffix}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def occurrence_state(conn, event_name: str):
    matches = rows(
        conn,
        """
        SELECT occurrence_id, display_name, event_year, date_start, date_end,
               date_status, lifecycle_status, source_kind, source_url
        FROM event_occurrences
        WHERE display_name = ?
        ORDER BY event_year DESC, occurrence_sequence
        """,
        (event_name,),
    )
    if len(matches) != 1:
        raise ValueError(f"expected one occurrence for {event_name!r}, found {len(matches)}")
    return matches[0]


def render_markdown(result):
    lines = [
        "# July official source promotions",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- applied: {result['applied']}",
        f"- checked_count: {result['summary']['checked_count']}",
        f"- updated_count: {result['summary']['updated_count']}",
        f"- already_current_count: {result['summary']['already_current_count']}",
        f"- backup_db: {result.get('backup_db') or ''}",
        "",
        "| event | changed | before source_kind | after source_kind | source_url | reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in result["promotions"]:
        before = item["before"]
        after = item["after"]
        lines.append(
            "| {event} | {changed} | {before_kind} | {after_kind} | {url} | {reason} |".format(
                event=item["event_name"],
                changed="yes" if item["changed"] else "no",
                before_kind=before.get("source_kind") or "",
                after_kind=after.get("source_kind") or "",
                url=after.get("source_url") or "",
                reason=item["reason"],
            )
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This is Master RDB only. Regenerate public JSON after apply to surface official links.",
            "- The script does not call Notion, S3, or any external API.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args):
    now = datetime.now(timezone.utc).isoformat()
    backup_path = ""
    result_rows = []
    with connect_existing(args.master_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for promotion in PROMOTIONS:
            before = occurrence_state(conn, promotion["event_name"])
            after = dict(before)
            after["source_kind"] = "official_current_year"
            after["source_url"] = promotion["source_url"]
            after["updated_at"] = now
            changed = (
                before.get("source_kind") != after["source_kind"]
                or before.get("source_url") != after["source_url"]
            )
            if args.apply and changed:
                if not backup_path:
                    backup_path = str(backup_db(args.master_db, now))
                conn.execute(
                    """
                    UPDATE event_occurrences
                    SET source_kind = 'official_current_year',
                        source_url = ?,
                        updated_at = ?
                    WHERE occurrence_id = ?
                    """,
                    (promotion["source_url"], now, before["occurrence_id"]),
                )
            result_rows.append(
                {
                    "event_name": promotion["event_name"],
                    "reason": promotion["reason"],
                    "changed": changed,
                    "before": before,
                    "after": after,
                }
            )
        changed_count = sum(1 for row in result_rows if row["changed"])
        if args.apply and changed_count:
            conn.commit()
            refresh_manifest_database_state(args.master_db, args.manifest, updated_at=now)
        fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()

    result = {
        "generated_by": "apply_july_official_source_promotions.py",
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "applied": bool(args.apply),
        "backup_db": backup_path,
        "summary": {
            "checked_count": len(result_rows),
            "updated_count": changed_count,
            "already_current_count": len(result_rows) - changed_count,
            "foreign_key_issue_count": len(fk_rows),
        },
        "promotions": result_rows,
        "foreign_key_issues": [tuple(row) for row in fk_rows],
    }
    write_json(args.out_json, result)
    args.out_md.write_text(render_markdown(result), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--manifest", type=Path, default=MASTER_MANIFEST)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            args.apply,
            args.confirm,
            MASTER_RDB_ONE_OFF_CONFIRMATION,
            "July official source promotion Master RDB update",
        )
    except ValueError as exc:
        parser.error(str(exc))
    result = run(args)
    print(
        "july official source promotions: "
        f"mode={result['mode']} applied={result['applied']} "
        f"checked={result['summary']['checked_count']} "
        f"updated={result['summary']['updated_count']} "
        f"already_current={result['summary']['already_current_count']} "
        f"fk_issues={result['summary']['foreign_key_issue_count']} out={args.out_json}"
    )
    return 1 if result["foreign_key_issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
