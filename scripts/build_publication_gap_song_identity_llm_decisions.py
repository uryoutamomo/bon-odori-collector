#!/usr/bin/env python3
"""Build the frozen LLM adjudication for publication-gap song identities.

The source rows mix real song titles, aliases/performance qualifiers, and
YouTube/event-title fragments.  This builder records the finite LLM decision
without changing the song catalog or public occurrence facts.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import connect_existing, normalize_text
from review_inbox_adapters.low_priority_adapters import build_snapshot
from review_inbox_adapters.parity import item_payload_hash
from review_inbox_adapters.source_adapter import input_sha256
from review_inbox_adapters.x_song_resolution_contract import catalog_snapshot


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data/publication_gap_song_identity_llm_decisions.json"
GAP_TYPE = "公開曲実績の曲名が曲マスタにない"

NOISE_TITLES = {
    "24",
    "24年赤坂日枝神社盆踊り",
    "25",
    "25 / Bon dance to tune of Southern All Stars in Tokyo.",
    "25 in Ebisu, Tokyo.",
    "25 with heavy rain.",
    "25 中編",
    "25 前編",
    "25 後編",
    "25, Tokyo, Japan.",
    "25.",
    "25】",
    "DJタイム",
    "EDM盆踊り",
    "おどりはだり1",
    "おどりはだり3",
    "おどりはだり4",
    "おどりはだり5",
    "お囃子&獅子舞",
    "まとめ1",
    "まとめ2",
    "ラジオ体操",
    "下北沢駅東口周辺で開かれる街なかの踊り",
    "円光院駐車場周辺で開かれる街なかの踊り",
    "切腹ピストルズ開催鳴らし",
    "千歳船橋駅前広場周辺で開かれる街なかの踊り",
    "南口広場周辺で開かれる街なかの踊り",
    "周辺で開かれる街なかの踊り",
    "外国人も一緒になって阿波踊り",
    "大井町駅前中央通り周辺で開かれる街なかの踊り",
    "好きの有志が季節",
    "浅草右近屋",
    "激混み会場で外国人も踊り",
    "特設会場周辺で開かれる街なかの踊り",
    "盆おどり",
    "祖師谷神明社周辺で開かれる街なかの踊り",
    "終 10連合同総踊り",
    "終 〆太鼓",
    "終 お囃子~打ち上げ花火",
    "終 ねぶた囃子、跳人",
    "終 まとめ3",
    "終 パレード",
    "終 堀切あやめ連流し踊り",
    "終 大角会和太鼓演奏",
    "終 木遣り・纏振り",
    "終 池袋盆BAND",
    "終 浅草右近屋パフォーマンス",
    "終 番外編",
    "終 関東やまと太鼓",
    "終 関東やまと太鼓〆太鼓",
    "都立大学駅西口緑道周辺で開かれる街なかの踊り",
    "阿波踊り",
    "阿波踊り「和楽連」",
    "阿波踊り「和樂連」",
    "飛鳥山公園の檜舞台での踊り",
}

NEW_SONG_TARGETS = {
    "BLUE BLUR(Live)": "BLUE BLUR",
    "ムーンライトステーション": "ムーンライトステーション",
    "ムーンライト伝説": "ムーンライト伝説",
    "千本櫻": "千本櫻",
    "瀧野家秀月(泉州音頭)": "泉州音頭",
    "生駒尚子(星屑の御堂筋)": "星屑の御堂筋",
    "終 初音節2": "初音節",
    "終 津具「チョイナ節」": "チョイナ節",
}

TARGET_OVERRIDES = {
    "65日の紙飛行機": "365日の紙飛行機",
    "おどりはだり2ドダレバチサンバ": "どだればちサンバ",
    "ドダレバチ(津軽甚句)": "津軽甚句",
    "大人の部": "相馬盆唄",
    "大大和会(江州音頭)": "江州音頭",
    "大大和稔龍(江州音頭)": "江州音頭",
    "子どもの部": "相馬盆唄",
    "月乃家寿子(河内音頭)": "河内音頭",
    "月乃家小菊(江州音頭)": "江州音頭",
    "松原光司(河内音頭)": "河内音頭",
    "松原慎之介(河内音頭)": "河内音頭",
    "猫の子(白鳥)": "猫の子",
    "猫の子(郡上)": "猫の子",
    "生駒みづき (河内音頭)": "河内音頭",
    "生駒一久 河内音頭(一部)": "河内音頭",
    "生駒尚子(河内音頭)": "河内音頭",
    "終 おどりはだり6ドダレバチサンバ": "どだればちサンバ",
    "終 ジャンボリーミッキー": "ジャンボリミッキー",
    "終 ボンゴ天国〆太鼓": "ボンゴ天国",
    "終 メガヒッツ盆踊り": "メガ盆",
    "終 一般の部": "相馬盆唄",
    "終 山中一平": "河内音頭",
    "終 江州音頭2": "江州音頭",
    "終 生駒竜也(河内音頭)": "河内音頭",
    "音頭「七福神」": "七福神音頭",
    "音頭「福よ来い」": "福よ来い",
}


def cleaned_title(value: str) -> str:
    title = value.removeprefix("終 ").strip()
    title = re.sub(r"\(生歌\)$", "", title).strip()
    title = re.sub(r"[・ ~]?〆太鼓$", "", title).strip()
    return title


def catalog_index(path: Path, master_db: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    index: dict[str, dict] = {}
    with connect_existing(master_db) as conn:
        for song in catalog_snapshot(conn):
            values = [song["canonical_title"], *(row["alias"] for row in song["aliases"])]
            for value in values:
                normalized = normalize_text(value)
                if normalized and normalized not in index:
                    index[normalized] = {
                        "song_name": song["canonical_title"],
                        "song_id": song["song_id"],
                        "status": song["status"],
                        "public_ready": None,
                        "matched_text": value,
                        "catalog_source": "master_rdb",
                    }
    for song in payload.get("songs") or []:
        name = str(song.get("song_name") or "").strip()
        if not name:
            continue
        values = [name, *(song.get("aliases") or [])]
        for value in values:
            normalized = normalize_text(value)
            if normalized and normalized not in index:
                index[normalized] = {
                    "song_name": name,
                    "song_id": None,
                    "status": song.get("status"),
                    "public_ready": song.get("public_ready"),
                    "matched_text": value,
                    "catalog_source": "youtube_song_master",
                }
    return index


def build(*, generated_at: str, master_db: Path) -> dict:
    review_path = ROOT / "data/publication_gap_review.json"
    master_path = ROOT / "data/youtube_song_master.json"
    occurrence_path = ROOT / "data/public/event_song_occurrences_public.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    source_rows = [row for row in review.get("rows") or [] if row.get("gap_type") == GAP_TYPE]
    if len(source_rows) != 147:
        raise ValueError(f"expected 147 song identity gaps, got {len(source_rows)}")

    snapshot = build_snapshot("publication_gap", decision_overlay_path=None)
    current = {item["source_key"]: item for item in snapshot["items"]}
    catalog = catalog_index(master_path, master_db)
    occurrences = json.loads(occurrence_path.read_text(encoding="utf-8")).get("occurrences") or []
    evidence_by_name: dict[str, list[str]] = {}
    for occurrence in occurrences:
        for song in occurrence.get("songs") or []:
            name = str(song.get("name") or "")
            evidence_by_name.setdefault(name, []).extend(song.get("evidence_urls") or [])

    decisions = []
    for row in source_rows:
        raw_title = row["song_name"]
        source_key = f"gap:{row['gap_id']}"
        item = current.get(source_key)
        if item is None:
            raise ValueError(f"current publication gap missing: {source_key}")

        if raw_title in NOISE_TITLES:
            decision = "曲名ノイズとして除外"
            target = None
            catalog_match = None
            confidence = "high"
            reason = "曲名ではなく、年・動画区分・会場説明・出演/演目区分などのタイトル断片である。"
        elif raw_title in NEW_SONG_TARGETS:
            decision = "新規曲候補として維持"
            target = NEW_SONG_TARGETS[raw_title]
            catalog_match = None
            confidence = "medium"
            reason = "個別曲名として読めるが、現行の曲マスタに安全に統合できる同一曲がない。"
        else:
            decision = "既存曲へ統合"
            query = TARGET_OVERRIDES.get(raw_title, cleaned_title(raw_title))
            catalog_match = catalog.get(normalize_text(query))
            if catalog_match is None:
                raise ValueError(f"target song is absent from current catalog: {raw_title!r} -> {query!r}")
            target = catalog_match["song_name"]
            confidence = "high"
            reason = "表記差・終端表示・生歌/演者/締め太鼓等の修飾を除くと、現行曲マスタの同一曲に一致する。"

        evidence_urls = sorted(set(evidence_by_name.get(raw_title) or []))[:5]
        decisions.append(
            {
                "source_id": "publication_gap",
                "source_key": source_key,
                "inbox_id": item["inbox_id"],
                "source_payload_hash": item_payload_hash(item),
                "gap_id": row["gap_id"],
                "raw_song_name": raw_title,
                "decision": decision,
                "target_song_name": target,
                "target_catalog_match": catalog_match,
                "confidence": confidence,
                "reason_detail": reason,
                "evidence_urls": evidence_urls,
                "actor_type": "agent",
                "actor_id": "おと（Codex）",
                "decided_at": generated_at,
            }
        )

    counts = {value: sum(row["decision"] == value for row in decisions) for value in (
        "既存曲へ統合", "曲名ノイズとして除外", "新規曲候補として維持"
    )}
    return {
        "schema_version": 1,
        "generated_by": "おと（Codex）",
        "generated_at": generated_at,
        "input": {
            "publication_gap_review": str(review_path.relative_to(ROOT)),
            "publication_gap_review_sha256": input_sha256(review_path.read_bytes()),
            "youtube_song_master": str(master_path.relative_to(ROOT)),
            "youtube_song_master_sha256": input_sha256(master_path.read_bytes()),
            "master_rdb": str(master_db),
            "master_rdb_sha256": input_sha256(master_db.read_bytes()),
            "event_song_occurrences_public": str(occurrence_path.relative_to(ROOT)),
            "event_song_occurrences_public_sha256": input_sha256(occurrence_path.read_bytes()),
        },
        "summary": {"total": len(decisions), **counts, "unresolved": 0},
        "decisions": decisions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--master-db", type=Path, required=True)
    parser.add_argument("--generated-at")
    args = parser.parse_args()
    generated_at = args.generated_at or datetime.now(timezone.utc).isoformat()
    payload = build(generated_at=generated_at, master_db=args.master_db)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
