#!/usr/bin/env python3
"""Merge Koto's YouTube 2025 review decisions into the manual queue decisions."""

import json
import tempfile
from datetime import date
from pathlib import Path

from youtube_backfill.export_youtube_2025_manual_confirmation_queue import decision_key


QUEUE = Path("data/youtube_2025_manual_confirmation_queue.json")
DECISIONS = Path("data/youtube_2025_manual_confirmation_decisions.json")
TODAY = date(2026, 6, 16).isoformat()


RULES = [
    ("肉フェス 2025 アニメメメ盆踊り", "hold_needs_2025_source", "こと判定: 肉フェス2025自体は確認できたが、公式プログラムで「アニメメメ盆踊り」の明記が取れず保留。"),
    ("神田明神 アニソン盆踊り 2025", "skip_registered", "こと判定: event-checker等で2025年神田明神納涼祭り内アニソン盆踊りを確認。DB/公開データ上は既存反映済み。"),
    ("歌舞伎町 BON ODORI 2025", "hold_mixed_events_needs_split", "こと判定: 8月の歌舞伎町BON ODORIは既存反映済み。10月の歌舞伎町まつり盆踊りは動画/X寄り根拠のため、混在行として保留し分割が必要。"),
    ("鴨台盆踊り2025", "skip_registered", "こと判定: 大正大学公式/PR TIMESで第15回鴨台盆踊り 2025-07-04〜05を確認し、Notionへ反映済み。"),
    ("神楽坂まつり 盆踊り", "skip_registered", "こと判定: 神楽坂通り商店会公式/新宿観光振興協会で2025-07-23〜24を確認し、Notionへ反映済み。"),
    ("BEGIN ライブ", "exclude_out_of_scope", "こと/おと判定: 金王八幡宮例大祭のBEGIN奉納ライブ動画で、盆踊り開催証拠ではないため除外。"),
    ("Ready, Set, Go!", "exclude_out_of_scope", "おと判定: linktr.ee/tokyohertzの散歩・ランウェイ等のノイズ混在行で、盆踊り候補として扱わない。"),
    ("渋谷盆踊り 2025", "skip_registered", "こと判定済みの第6回渋谷盆踊り2025と同一系統。DB上は既存反映済み。"),
    ("築地本願寺 納涼盆踊り大会 2025", "hold_needs_2025_source", "高優先度側と重複。候補公式URLが404で、2025年公式/準公式URLの再確認が必要なため保留。"),
    ("花園神社 盆踊り 2025", "skip_registered", "こと判定: 2025-08-01〜02の花園神社盆踊りを確認し、Notionへ反映済み。"),
    ("自由が丘納涼盆踊り 2025", "skip_registered", "こと判定済みの自由が丘盆踊り大会2025と同一系統。DB上は既存反映済み。"),
    ("恵比寿駅前盆踊り大会 2025", "skip_registered", "こと判定: 公式サイトで第70回 2025-07-25〜26を確認し、Notionへ反映済み。"),
    ("赤坂浄土寺盆踊り大会2025", "skip_registered", "こと判定: 赤坂あかね会X/地域ブログで2025-07-24〜25を確認し、Notionへ反映済み。"),
    ("下町ハイボールフェス2025", "hold_needs_scope_decision", "こと判定: フェス内ステージ出演枠としてのアニソン盆踊り協会で、独立した盆踊りイベントか判断保留。"),
    ("祐天寺み霊まつり盆踊り", "skip_registered", "こと判定: 祐天寺み魂まつり子ども盆踊り大会2025を確認。公開データ上は既存反映済み。"),
    ("下北沢 盆踊り 2025", "skip_registered", "こと判定: 下北沢盆踊り2025を商店街公式等で確認。公開データ上は既存反映済み。"),
    ("浦安市納涼盆踊り大会 2025", "exclude_out_of_scope", "おと判定: 浦安市は東京23区外のため本DB公開対象外として除外。"),
    ("TOKYOわっしょい", "hold_needs_scope_decision", "こと判定: 複合文化イベント内の盆踊りプログラムで、独立イベントとして登録すべきか判断保留。"),
    ("にっぽり 炭坑節まつり", "skip_registered", "こと判定: 荒川区公式/日本盆踊り協会で第11回 2025-09-14〜15を確認し、Notionへ反映済み。"),
]

BACKFILL_RULES = {
    "品川区民まつり 西大井広場公園 盆踊り": ("hold_source_video_mismatch", "盆まるで2025開催情報は確認できるが、キュー内YouTube動画は2024タイトルのため2025動画証拠としては保留。"),
    "みたままつり 納涼民踊のつどい": ("hold_needs_scope_decision", "神輿/奉納演奏中心の動画が混在し、納涼民踊としての扱いを再確認するまで保留。"),
    "京橋盆踊り": ("hold_source_video_mismatch", "公式ページで2025開催情報は確認できるが、キュー内YouTube動画は2024タイトルのため2025動画証拠としては保留。"),
    "根津神社 盆踊り（文京区）": ("exclude_out_of_scope", "ソースは古い根津神社系、動画は竜泉二丁目/外神田など別イベントにズレているため除外。"),
    "奥浅草盆踊り": ("skip_registered", "こと判定: 第3回奥浅草盆踊り2025を確認。DB/公開データ上は既存反映済み。"),
    "すみだ錦糸町河内音頭大盆踊り": ("skip_registered", "こと判定: 墨田区観光協会/公式サイトで第43回 2025-07-30〜31を確認。公開データ上は既存反映済み。"),
}


def load_json(path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def row_text(row):
    parts = []
    parts.extend(row.get("titles") or [])
    parts.extend(video.get("title") or "" for video in row.get("videos") or [])
    parts.extend(video.get("title") or "" for video in row.get("sample_videos") or [])
    parts.append(row.get("event_name") or "")
    return "\n".join(parts)


def decision_for(row):
    if row.get("queue") == "remaining_backfill":
        return BACKFILL_RULES.get(row.get("event_name") or "")
    text = row_text(row)
    if row.get("primary_url") == "https://goo.gl/maps/kSAEbnkyHSchcccY6":
        return ("exclude_out_of_scope", "おと判定: 浅草/渋谷/下北沢など雑多な散歩動画が混在したGoogle Maps短縮URL束で、単一イベント候補として扱えないため除外。")
    for needle, action, reason in RULES:
        if needle in text:
            return action, reason
    return None


def atomic_write_json(path, data):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".json", delete=False) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def main():
    queue = load_json(QUEUE, {"rows": []})
    decisions = load_json(DECISIONS, {"rows": []})
    by_key = {row.get("key"): row for row in decisions.get("rows") or [] if row.get("key")}
    applied = []
    for row in queue.get("rows") or []:
        decision = decision_for(row)
        if not decision:
            continue
        action, reason = decision
        key = decision_key(row)
        by_key[key] = {"key": key, "action": action, "reason": reason}
        applied.append({"key": key, "action": action})
    decisions["rows"] = list(by_key.values())
    decisions["generated_at"] = TODAY
    atomic_write_json(DECISIONS, decisions)
    print(f"koto decisions merged: {len(applied)} rows -> {DECISIONS}")


if __name__ == "__main__":
    main()
