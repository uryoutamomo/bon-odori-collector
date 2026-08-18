#!/usr/bin/env python3
"""Build a read-only canonical apply plan for the completed LLM review backlog.

This command deliberately has no apply mode.  It pins the reviewed master DB by
SHA-256, opens SQLite in read-only/query-only mode, and reports the materializer
or additional evidence required before any canonical write can be proposed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DEFAULT_JSON = DATA / "review_backlog_canonical_apply_plan.json"
DEFAULT_MARKDOWN = DATA / "review_backlog_canonical_apply_plan.md"

SOURCE_FILES = {
    "publication_song_identity": DATA / "publication_gap_song_identity_llm_decisions.json",
    "youtube": DATA / "review_backlog_youtube_llm_decisions_remaining.json",
    "historical_reference_quality": DATA / "historical_reference_quality_llm_research.json",
    "publication_event_date": DATA / "publication_gap_event_date_research.json",
    "x_gap": DATA / "x_gap_kuramae_research.json",
    "general_overlay": DATA / "review_backlog_decision_overlay.json",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value: object) -> str:
    value = re.sub(r"\s+", "", str(value or ""))
    value = re.sub(r"[\W_]+", "", value)
    return value.casefold()


def connect_read_only(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve(strict=True)
    uri = f"file:{quote(resolved.as_posix(), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def require_tables(connection: sqlite3.Connection) -> None:
    required = {
        "songs",
        "song_aliases",
        "occurrence_songs",
        "occurrence_song_evidence_links",
        "evidence_items",
        "observed_occurrence_songs",
    }
    present = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    missing = sorted(required - present)
    if missing:
        raise ValueError(f"master DB is missing required tables: {', '.join(missing)}")


def find_target_songs(
    connection: sqlite3.Connection, *, target_song_id: str | None, target_title: str
) -> list[dict]:
    if target_song_id:
        rows = connection.execute(
            """
            SELECT song_id, canonical_title, normalized_title, status
            FROM songs
            WHERE song_id = ?
            """,
            (target_song_id,),
        ).fetchall()
        if rows:
            return [dict(row) for row in rows]

    normalized = normalize_text(target_title)
    rows = connection.execute(
        """
        SELECT DISTINCT s.song_id, s.canonical_title, s.normalized_title, s.status
        FROM songs AS s
        LEFT JOIN song_aliases AS a ON a.song_id = s.song_id
        WHERE s.normalized_title = ? OR a.normalized_alias = ?
        ORDER BY s.song_id
        """,
        (normalized, normalized),
    ).fetchall()
    return [dict(row) for row in rows]


def raw_occurrence_song_rows(
    connection: sqlite3.Connection, raw_title: str
) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
          os.occurrence_song_id,
          os.occurrence_id,
          os.song_id,
          os.song_title_raw,
          os.normalized_title,
          os.role,
          os.origin,
          os.evidence_status,
          COUNT(link.evidence_id) AS evidence_link_count
        FROM occurrence_songs AS os
        LEFT JOIN occurrence_song_evidence_links AS link
          ON link.occurrence_song_id = os.occurrence_song_id
        WHERE os.normalized_title = ?
        GROUP BY os.occurrence_song_id
        ORDER BY os.occurrence_song_id
        """,
        (normalize_text(raw_title),),
    ).fetchall()
    return [dict(row) for row in rows]


def conflict_count(
    connection: sqlite3.Connection, *, source_rows: list[dict], target: dict
) -> int:
    total = 0
    for row in source_rows:
        if row.get("song_id") == target["song_id"]:
            continue
        found = connection.execute(
            """
            SELECT COUNT(*)
            FROM occurrence_songs
            WHERE occurrence_id = ?
              AND role = ?
              AND occurrence_song_id != ?
              AND (song_id = ? OR normalized_title = ?)
            """,
            (
                row["occurrence_id"],
                row["role"],
                row["occurrence_song_id"],
                target["song_id"],
                target["normalized_title"],
            ),
        ).fetchone()[0]
        total += int(found > 0)
    return total


def build_song_identity_plan(
    connection: sqlite3.Connection, decisions: list[dict]
) -> dict:
    items: list[dict] = []
    raw_row_total = 0
    conflict_row_total = 0
    target_missing_total = 0

    for decision in decisions:
        raw_rows = raw_occurrence_song_rows(connection, decision["raw_song_name"])
        raw_row_total += len(raw_rows)
        action: str
        target_rows: list[dict] = []
        conflicts = 0

        if decision["decision"] == "既存曲へ統合":
            frozen_target = decision.get("target_catalog_match") or {}
            target_rows = find_target_songs(
                connection,
                target_song_id=frozen_target.get("song_id"),
                target_title=decision.get("target_song_name") or "",
            )
            if not target_rows:
                action = "blocked_target_song_missing_from_rdb"
                target_missing_total += 1
            elif len(target_rows) > 1:
                action = "blocked_ambiguous_target_song"
            elif not raw_rows:
                action = "source_public_only_no_rdb_row"
            else:
                target = target_rows[0]
                rows_needing_relink = [
                    row for row in raw_rows if row.get("song_id") != target["song_id"]
                ]
                if not rows_needing_relink:
                    action = "already_matched_current_rdb"
                else:
                    conflicts = conflict_count(
                        connection, source_rows=rows_needing_relink, target=target
                    )
                    action = (
                        "requires_merge_materializer"
                        if conflicts
                        else "requires_relink_materializer"
                    )
        elif decision["decision"] == "曲名ノイズとして除外":
            action = (
                "requires_retraction_materializer"
                if raw_rows
                else "source_public_only_no_rdb_row"
            )
        elif decision["decision"] == "新規曲候補として維持":
            action = (
                "requires_candidate_registration_and_relink"
                if raw_rows
                else "requires_candidate_registration_from_public_source"
            )
        else:
            raise ValueError(f"unsupported song identity decision: {decision['decision']}")

        conflict_row_total += conflicts
        items.append(
            {
                "source_key": decision["source_key"],
                "inbox_id": decision["inbox_id"],
                "raw_song_name": decision["raw_song_name"],
                "decision": decision["decision"],
                "target_song_name": decision.get("target_song_name"),
                "resolved_target_song_ids": [row["song_id"] for row in target_rows],
                "rdb_source_row_count": len(raw_rows),
                "rdb_evidence_link_count": sum(
                    row["evidence_link_count"] for row in raw_rows
                ),
                "rdb_conflict_row_count": conflicts,
                "action": action,
            }
        )

    return {
        "summary": {
            "decision_count": len(items),
            "decision_counts": dict(Counter(row["decision"] for row in items)),
            "action_counts": dict(Counter(row["action"] for row in items)),
            "rdb_source_row_count": raw_row_total,
            "rdb_conflict_row_count": conflict_row_total,
            "target_missing_from_rdb_count": target_missing_total,
        },
        "items": items,
    }


def video_id(source_key: str) -> str:
    match = re.match(r"^video:([^|]+)(?:\||$)", source_key)
    if not match:
        raise ValueError(f"invalid YouTube source_key: {source_key}")
    return match.group(1)


def build_youtube_plan(
    connection: sqlite3.Connection, decisions: list[dict]
) -> dict:
    items: list[dict] = []
    for decision in decisions:
        identifier = video_id(decision["source_key"])
        pattern = f"%{identifier}%"
        evidence_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM evidence_items
            WHERE COALESCE(url, '') LIKE ?
               OR COALESCE(source_key, '') LIKE ?
               OR COALESCE(source_id, '') LIKE ?
            """,
            (pattern, pattern, pattern),
        ).fetchone()[0]
        observed_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM observed_occurrence_songs
            WHERE evidence_urls_json LIKE ?
               OR source_payload_json LIKE ?
            """,
            (pattern, pattern),
        ).fetchone()[0]
        present = bool(evidence_count or observed_count)

        if decision["decision"] == "採用":
            action = (
                "already_present_or_partially_materialized"
                if present
                else "requires_identity_packet_before_materialize"
            )
        elif decision["decision"] == "不採用":
            action = (
                "no_write_retraction_review_required"
                if present
                else "no_canonical_write"
            )
        else:
            raise ValueError(f"unsupported YouTube decision: {decision['decision']}")

        items.append(
            {
                "source_key": decision["source_key"],
                "inbox_id": decision["inbox_id"],
                "video_id": identifier,
                "decision": decision["decision"],
                "evidence_item_count": evidence_count,
                "observed_song_row_count": observed_count,
                "action": action,
            }
        )

    return {
        "summary": {
            "decision_count": len(items),
            "decision_counts": dict(Counter(row["decision"] for row in items)),
            "action_counts": dict(Counter(row["action"] for row in items)),
        },
        "items": items,
    }


def identity_only(row: dict, *, action: str, extra: dict | None = None) -> dict:
    result = {
        "source_key": row["source_key"],
        "inbox_id": row["inbox_id"],
        "action": action,
    }
    if extra:
        result.update(extra)
    return result


def build_no_write_plan(sources: dict[str, dict]) -> dict:
    historical = [
        identity_only(
            row,
            action="no_canonical_write_keep_historical_reference",
            extra={"decision": row["decision"]},
        )
        for row in sources["historical_reference_quality"]["decisions"]
    ]
    event_dates = [
        {
            "source_key": f"gap:{row['gap_id']}",
            "inbox_id": row["inbox_id"],
            "classification": row["classification"],
            "action": "no_write_current_year_date_unconfirmed",
        }
        for row in sources["publication_event_date"]["decisions"]
    ]
    x_gaps = [
        identity_only(
            row,
            action="no_write_official_confirmation_required",
            extra={
                "classification": row["classification"],
                "recommended_decision": row["recommended_decision"],
            },
        )
        for row in sources["x_gap"]["decisions"]
    ]
    return {
        "summary": {
            "decision_count": len(historical) + len(event_dates) + len(x_gaps),
            "historical_reference_count": len(historical),
            "event_date_count": len(event_dates),
            "x_gap_count": len(x_gaps),
        },
        "historical_reference_quality": historical,
        "publication_event_date": event_dates,
        "x_gap": x_gaps,
    }


def build_publication_sync_plan(general_overlay: dict) -> dict:
    rows = [
        identity_only(
            row,
            action="separate_bon_odori_site_sync_plan_required",
            extra={"decision": row["decision"]},
        )
        for row in general_overlay["decisions"]
        if row.get("source_id") == "publication_gap"
        and row.get("decision") == "公開同期対象"
    ]
    return {"summary": {"decision_count": len(rows)}, "items": rows}


def source_lineage() -> dict:
    return {
        name: {
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256(path),
        }
        for name, path in SOURCE_FILES.items()
    }


def build_plan(*, master_db: Path, generated_at: str) -> dict:
    sources = {name: load_json(path) for name, path in SOURCE_FILES.items()}
    expected_db_sha = sources["publication_song_identity"]["input"][
        "master_rdb_sha256"
    ]
    actual_db_sha = sha256(master_db)
    if actual_db_sha != expected_db_sha:
        raise ValueError(
            "master DB SHA-256 differs from the frozen review input: "
            f"expected {expected_db_sha}, got {actual_db_sha}"
        )

    with connect_read_only(master_db) as connection:
        require_tables(connection)
        song_plan = build_song_identity_plan(
            connection, sources["publication_song_identity"]["decisions"]
        )
        youtube_plan = build_youtube_plan(connection, sources["youtube"]["decisions"])

    no_write = build_no_write_plan(sources)
    publication_sync = build_publication_sync_plan(sources["general_overlay"])
    counts = {
        "youtube": youtube_plan["summary"]["decision_count"],
        "publication_song_identity": song_plan["summary"]["decision_count"],
        "historical_reference_quality": no_write["summary"][
            "historical_reference_count"
        ],
        "publication_event_date": no_write["summary"]["event_date_count"],
        "publication_sync": publication_sync["summary"]["decision_count"],
        "x_gap": no_write["summary"]["x_gap_count"],
    }
    total = sum(counts.values())
    if counts != {
        "youtube": 247,
        "publication_song_identity": 147,
        "historical_reference_quality": 60,
        "publication_event_date": 38,
        "publication_sync": 12,
        "x_gap": 1,
    }:
        raise ValueError(f"unexpected reviewed decision inventory: {counts}")

    return {
        "schema_version": 1,
        "generated_by": "おと（Codex）",
        "generated_at": generated_at,
        "mode": "read_only_dry_run",
        "master_db": {
            "provided_path": str(master_db),
            "sha256": actual_db_sha,
            "matches_frozen_review_input": True,
            "opened_read_only": True,
        },
        "input_lineage": source_lineage(),
        "summary": {
            "review_decision_count": total,
            "decision_counts": counts,
            "production_write_ready_count": 0,
            "canonical_write_performed": False,
            "separate_repository_sync_count": publication_sync["summary"][
                "decision_count"
            ],
            "date_promotions_allowed": 0,
        },
        "canonical_write_boundary": {
            "would_write": False,
            "apply_mode_exists": False,
            "reason": (
                "The required relink, merge, retraction, candidate-registration, "
                "identity-packet, and public-site sync materializers are not part of "
                "this read-only plan. Production application also requires separate "
                "explicit user approval for an exact target and action."
            ),
        },
        "publication_song_identity": song_plan,
        "youtube": youtube_plan,
        "no_write_decisions": no_write,
        "publication_sync": publication_sync,
    }


def render_markdown(plan: dict) -> str:
    song = plan["publication_song_identity"]["summary"]
    youtube = plan["youtube"]["summary"]
    no_write = plan["no_write_decisions"]["summary"]
    sync = plan["publication_sync"]["summary"]

    action_rows = []
    for action, count in sorted(song["action_counts"].items()):
        action_rows.append(f"| 曲名判断 | `{action}` | {count} |")
    for action, count in sorted(youtube["action_counts"].items()):
        action_rows.append(f"| YouTube判断 | `{action}` | {count} |")

    return "\n".join(
        [
            "# LLMレビュー判断の正本反映 dry-run",
            "",
            f"生成日時: {plan['generated_at']}",
            "",
            "この計画は読み取り専用です。SQLiteはSHA-256を照合してからread-onlyで開き、DB・公開データ・reader設定を変更しません。",
            "",
            "## 結論",
            "",
            f"- 対象判断: {plan['summary']['review_decision_count']}件",
            "- そのまま本番書き込み可能: 0件",
            f"- 公開サイト側の別同期計画: {sync['decision_count']}件",
            "- 2026年日付へ昇格可能: 0件",
            "",
            "専用のrelink・merge・retraction・候補登録処理、YouTube identity packet、公開サイト側同期が未作成です。正本反映には、各処理の実装・コピーDBでの検証・対象を特定した明示GOが別途必要です。",
            "",
            "## DB照合結果",
            "",
            f"- 判断時点DBとのSHA一致: `{plan['master_db']['matches_frozen_review_input']}`",
            f"- 曲名判断: {song['decision_count']}件 / 該当occurrence_songs {song['rdb_source_row_count']}行",
            f"- RDBに統合先がない判断: {song['target_missing_from_rdb_count']}件",
            f"- 同一開催・役割内でmergeが必要な衝突行: {song['rdb_conflict_row_count']}行",
            f"- YouTube判断: {youtube['decision_count']}件",
            "",
            "| 分類 | dry-run action | 件数 |",
            "|---|---|---:|",
            *action_rows,
            "",
            "## 書き込み禁止として維持する判断",
            "",
            f"- 過去実績維持: {no_write['historical_reference_count']}件（現在年の事実へ転用しない）",
            f"- 2026年日付の根拠不足: {no_write['event_date_count']}件",
            f"- X由来・公式確認待ち: {no_write['x_gap_count']}件",
            f"- YouTube不採用: {youtube['decision_counts'].get('不採用', 0)}件",
            "",
            "## 次の安全な実装単位",
            "",
            "1. 曲名relink/merge/retractionをコピーDBだけに適用するmaterializerを作る。",
            "2. 新規曲候補を根拠URL付きで登録するmaterializerを作る。",
            "3. 採用YouTubeをイベント・曲へ結ぶidentity packetを作り、曖昧一致を人手確認へ戻す。",
            "4. 公開同期12件は `bon-odori-site` 側で別計画・別承認にする。",
            "",
            "イベント日付について、2025年以前、YouTube、年次未指定の恒例案内を2026年日付へ転用しません。",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master-db", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-markdown", type=Path, default=DEFAULT_MARKDOWN)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plan = build_plan(master_db=args.master_db, generated_at=args.generated_at)
    args.output_json.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.output_markdown.write_text(render_markdown(plan), encoding="utf-8")
    print(
        json.dumps(
            {
                "output_json": str(args.output_json),
                "output_markdown": str(args.output_markdown),
                "summary": plan["summary"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
