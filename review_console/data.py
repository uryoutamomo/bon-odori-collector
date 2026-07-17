#!/usr/bin/env python3
"""Data loading and decision export for the local review console."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import collect_ops_metrics
from review_inbox_decision_stage import UPDATES_FILE, build_decision_stage, write_decision_stage
from youtube_title_parts import split_youtube_title


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CONSOLE_DIR = DATA_DIR / "review_console"
DECISIONS_PATH = CONSOLE_DIR / "decisions.json"
HISTORY_PATH = CONSOLE_DIR / "decision_history.json"
EXPORT_PATH = CONSOLE_DIR / "exported_decisions.json"
EXPORT_MD_PATH = CONSOLE_DIR / "exported_decisions.md"
INVENTORY_PATH = CONSOLE_DIR / "source_inventory.json"
INVENTORY_MD_PATH = CONSOLE_DIR / "source_inventory.md"
STAGED_DIR = CONSOLE_DIR / "staged"
STAGE_RESULT_PATH = STAGED_DIR / "stage_apply_result.json"
STAGE_ACK_PATH = STAGED_DIR / "stage_apply_ack.json"
SONG_MASTER_PATH = DATA_DIR / "youtube_song_master.json"

_INVENTORY_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_DECISION_LOCKS: dict[str, threading.RLock] = {}
_DECISION_LOCKS_GUARD = threading.Lock()
_SONG_TERM_CACHE: dict[str, tuple[tuple[str, int], dict[str, str]]] = {}

GENERIC_SONG_TERMS = {
    "盆踊り",
    "bon dance",
    "bon odori",
    "音頭",
    "民踊",
    "おどり",
    "踊り",
    "まつり",
    "祭り",
    "さくら",
    "春",
    "夏",
    "秋",
    "冬",
    "東京",
    "浅草",
    "青山",
}

DECISION_LABELS = {
    "accept": "レビュー採用",
    "reject": "却下",
    "hold": "保留",
    "needs_research": "要調査",
}

STATUS_LABELS = {
    "pending": "未レビュー",
    "reviewed": "決定済み",
    "closed": "処理済み",
}

APPLY_VALUE_LABELS = {
    "promote_historical_reference": "過去実績として採用",
    "confirm_current_date": "2026年日程確認済みにする",
    "reject": "不採用",
    "reject_candidate": "候補を不採用",
    "reject_prediction": "予測を不採用",
    "hold": "保留",
    "needs_research": "要調査",
    "source_research_required": "根拠URLを追加調査",
    "needs_date_research": "日付・曜日を再調査",
    "needs_song_research": "曲候補を再調査",
    "keep_historical_reference": "過去実績として維持",
    "remove_historical_reference": "過去実績から外す",
    "accept_confirmed_source": "確認済み根拠として採用",
    "promote_prediction": "予測日として採用",
    "keep_prediction_queue": "予測キューに残す",
    "fill_source_url": "根拠URLを補完",
    "fill_venue": "会場を補完",
    "create_venue_review": "会場レビューを作成",
    "official": "公式URLとして採用",
    "hp": "告知HPとして採用",
    "post": "告知投稿として採用",
    "append_existing_event": "既存イベントへ動画・曲を追加",
    "needs_official_confirmation": "公式確認待ち",
    "bon_component_of_parent_event": "親イベント内の盆踊り企画",
    "merge_to_existing": "既存開催回へ統合",
    "register_new_occurrence": "新規開催回として登録",
    "duplicate_year_drop": "重複年として除外",
    "include_in_main_event_db": "メインDBへ含める",
    "exclude": "除外",
    "promote": "情報源にする",
    "watch": "様子を見る",
    "confirm_non_x_source": "非X根拠で確認済み",
    "needs_non_x_backcheck": "非X根拠を追加調査",
    "stage_registration_candidate": "登録候補へ送る",
}

APPLY_VALUE_HELP = {
    "promote_historical_reference": "過去年の実績として扱い、2026年日程は未確認のまま残します。",
    "confirm_current_date": "今年の直接証拠で2026年日程が確認できた場合だけ使います。",
    "reject": "この候補を反映対象にしません。",
    "hold": "今は反映せず、文脈だけ残します。",
    "needs_research": "公式確認や同一性確認など追加調査に回します。",
    "source_research_required": "公開判断に使える根拠URLを追加で探します。",
    "needs_date_research": "採用済み過去実績の日付と曜日を確認します。",
    "needs_song_research": "採用済み過去実績の曲候補をYouTube/曲実績側で探します。",
    "keep_historical_reference": "不足を把握したうえで過去実績表示を維持します。",
    "remove_historical_reference": "公開価値が低い過去実績として外す判断に回します。",
    "append_existing_event": "イベントを新規作成せず、YouTube動画URLと曲名を既存イベントの証拠として残します。",
}

APPLY_VALUE_DECISIONS = {
    "reject": "reject",
    "reject_candidate": "reject",
    "reject_prediction": "reject",
    "exclude": "reject",
    "不採用": "reject",
    "hold": "hold",
    "保留": "hold",
    "needs_research": "needs_research",
    "source_research_required": "needs_research",
    "needs_date_research": "needs_research",
    "needs_song_research": "needs_research",
    "create_venue_review": "needs_research",
    "needs_official_confirmation": "needs_research",
    "needs_non_x_backcheck": "needs_research",
    "bon_component_of_parent_event": "hold",
    "remove_historical_reference": "reject",
    "watch": "hold",
}

X_REGISTRATION_DECISIONS = {
    "promote": "登録",
    "watch": "監視",
    "reject": "不採用",
    "hold": "保留",
}
DIRECT_SOURCE_DECISION_IDS = {"x_candidate_post"}


@dataclass(frozen=True)
class ReviewSource:
    id: str
    title: str
    path: str
    rows_path: str
    domain: str
    key_fields: tuple[str, ...]
    title_fields: tuple[str, ...]
    subtitle_fields: tuple[str, ...] = ()
    priority_fields: tuple[str, ...] = ("priority_label", "priority")
    score_fields: tuple[str, ...] = ("priority_score", "score", "suggested_score", "max_score")
    action_fields: tuple[str, ...] = (
        "recommended_action",
        "review_action",
        "action",
        "candidate_action",
        "decision_needed",
        "source_review",
    )
    source_decision_fields: tuple[str, ...] = ("decision", "current_decision")
    description_fields: tuple[str, ...] = ("reason", "next_step", "memo", "source_note", "basis")
    stale_if_generated_before_days: int | None = None
    pending_if_no_action: bool = True
    include_when_empty: bool = True
    final_decision_fields: tuple[str, ...] = ("existing_decision", "decided_by", "decided_at")
    urls_fields: tuple[str, ...] = (
        "source_url",
        "candidate_source_url",
        "video_url",
        "official_url_candidate",
        "checked_urls",
        "evidence_urls_sample",
        "observed_candidate.evidence_urls_sample",
        "videos.url",
        "sample_videos.url",
    )
    option_values: tuple[str, ...] = field(default_factory=tuple)


SOURCES: tuple[ReviewSource, ...] = (
    ReviewSource(
        id="review_inbox",
        title="統合レビュー受信箱",
        path="data/review_inbox.json",
        rows_path="items",
        domain="受信箱",
        key_fields=("inbox_id", "source_id", "source_key"),
        title_fields=("title", "event_name"),
        subtitle_fields=("kind", "event_year", "venue", "priority_label"),
        priority_fields=("priority_label",),
        score_fields=("priority_score",),
        action_fields=("recommended_action", "kind"),
        source_decision_fields=("status", "decision"),
        description_fields=("summary", "reason", "note", "payload.summary", "payload.reason", "payload.note"),
        urls_fields=("source_url", "payload.source_url", "payload.urls"),
        option_values=("confirm_current_date", "promote_historical_reference", "fill_venue", "fill_source_url", "needs_research", "reject", "hold"),
    ),
    ReviewSource(
        id="registered_event_investigation",
        title="登録済みイベント調査",
        path="data/registered_event_investigation_queue.json",
        rows_path="tasks",
        domain="開催日/会場",
        key_fields=("task_id", "occurrence_id"),
        title_fields=("event_name",),
        subtitle_fields=("known_venue_names", "status", "event_year"),
        option_values=("promote_historical_reference", "confirm_current_date", "needs_research", "reject", "hold"),
    ),
    ReviewSource(
        id="predicted_occurrence_research",
        title="予測日ソース再確認",
        path="data/predicted_occurrence_research_queue.json",
        rows_path="items",
        domain="開催日",
        key_fields=("predicted_date_id", "event_name"),
        title_fields=("event_name",),
        subtitle_fields=("predicted_date_start", "predicted_date_end", "usual_venue"),
        option_values=("accept_confirmed_source", "needs_research", "reject_prediction", "hold"),
    ),
    ReviewSource(
        id="predicted_occurrence_date_review",
        title="予測日レビュー",
        path="data/predicted_occurrence_date_review.json",
        rows_path="review",
        domain="開催日",
        key_fields=("predicted_date_id", "predicted.predicted_date_id", "event_name"),
        title_fields=("event_name", "predicted.target_event_name"),
        subtitle_fields=("predicted.date_start", "predicted.date_end", "current_status"),
        option_values=("promote_prediction", "keep_prediction_queue", "reject_prediction", "hold"),
    ),
    ReviewSource(
        id="missing_source_url",
        title="根拠URL不足",
        path="data/missing_source_url_review.json",
        rows_path="review",
        domain="根拠URL",
        key_fields=("occurrence_id", "event_name"),
        title_fields=("event_name",),
        subtitle_fields=("event_year", "date_start", "candidate_source_url"),
        option_values=("fill_source_url", "source_research_required", "reject_candidate", "hold"),
    ),
    ReviewSource(
        id="missing_occurrence_venue",
        title="会場不足レビュー",
        path="data/missing_occurrence_venue_review.json",
        rows_path="review",
        domain="会場",
        key_fields=("occurrence_id", "event_name"),
        title_fields=("event_name", "target_event_name"),
        subtitle_fields=("event_year", "candidate_venue_name", "venue"),
        option_values=("fill_venue", "create_venue_review", "reject", "hold"),
    ),
    ReviewSource(
        id="accepted_venue_song_missing_venue",
        title="曲実績由来の会場候補",
        path="data/accepted_venue_song_missing_venue_review.json",
        rows_path="rows",
        domain="会場",
        key_fields=("term", "suggested_venue", "evidence_url"),
        title_fields=("suggested_venue", "term"),
        subtitle_fields=("songs_text", "evidence_url"),
        option_values=("会場追加", "既存に統合", "不採用", "保留"),
    ),
    ReviewSource(
        id="daily_song_candidate",
        title="日次X曲候補",
        path="data/weekly_song_candidates_review.json",
        rows_path="rows",
        domain="曲",
        key_fields=("term", "canonical_song_name", "evidence_url"),
        title_fields=("canonical_song_name", "term"),
        subtitle_fields=("triage_reason", "evidence_count", "evidence_url"),
        priority_fields=("evidence_count", "category"),
        option_values=("曲として採用", "曲ではない", "分割", "用語集へ", "保留"),
    ),
    ReviewSource(
        id="daily_term_candidate",
        title="日次X用語・共起候補",
        path="data/weekly_harvest_review_candidates.json",
        rows_path="rows",
        domain="用語/曲",
        key_fields=("term", "category", "type", "evidence_url"),
        title_fields=("term",),
        subtitle_fields=("category", "type", "evidence_count"),
        priority_fields=("category", "evidence_count"),
        option_values=("採用", "不採用", "保留"),
    ),
    ReviewSource(
        id="publication_gap",
        title="採用済みと公開データの差分",
        path="data/publication_gap_review.json",
        rows_path="rows",
        domain="公開データ",
        key_fields=("gap_id", "term"),
        title_fields=("term", "song_name"),
        subtitle_fields=("gap_type", "reason"),
        priority_fields=("priority_label", "gap_type"),
        action_fields=("recommended_action",),
        description_fields=("reason", "review_reason"),
        option_values=("needs_research", "hold", "reject"),
    ),
    ReviewSource(
        id="historical_promotion_candidate",
        title="過去実績昇格候補",
        path="data/historical_promotion_candidate_review.json",
        rows_path="review",
        domain="過去実績",
        key_fields=("candidate_id", "target_occurrence_id", "event_name"),
        title_fields=("event_name",),
        subtitle_fields=("venue", "target_year", "historical_years"),
        option_values=("promote_historical_reference", "reject", "hold", "needs_research"),
    ),
    ReviewSource(
        id="historical_reference_quality",
        title="採用済み過去実績品質レビュー",
        path="data/historical_reference_quality_review.json",
        rows_path="review",
        domain="過去実績",
        key_fields=("quality_review_id", "event_name", "venue"),
        title_fields=("event_name", "name"),
        subtitle_fields=("venue", "historical_dates_label", "issue_summary"),
        option_values=(
            "needs_date_research",
            "needs_song_research",
            "keep_historical_reference",
            "remove_historical_reference",
            "hold",
        ),
    ),
    ReviewSource(
        id="official_source",
        title="公式/準公式URL候補",
        path="data/official_source_review_candidates.json",
        rows_path="rows",
        domain="根拠URL",
        key_fields=("id", "source_url", "venue", "event_name"),
        title_fields=("event_name", "venue"),
        subtitle_fields=("venue", "source_domain", "event_date_text"),
        option_values=("official", "hp", "post", "reject", "hold"),
    ),
    ReviewSource(
        id="youtube_active_video",
        title="YouTubeアクティブ動画レビュー",
        path="data/youtube_active_video_review.json",
        rows_path="rows",
        domain="YouTube",
        key_fields=("video_id", "video_url"),
        title_fields=("title",),
        subtitle_fields=("channel_title", "published_at", "action"),
        pending_if_no_action=False,
        option_values=(
            "append_existing_event",
            "needs_official_confirmation",
            "bon_component_of_parent_event",
            "reject",
            "hold",
        ),
    ),
    ReviewSource(
        id="youtube_year_backfill_review",
        title="YouTube年次バックフィル",
        path="data/youtube_year_backfill_review_queue.json",
        rows_path="groups",
        domain="YouTube",
        key_fields=("event_name", "venue", "target_year"),
        title_fields=("event_name",),
        subtitle_fields=("venue", "target_year", "video_count"),
        pending_if_no_action=False,
        option_values=("merge_to_existing", "register_new_occurrence", "duplicate_year_drop", "hold"),
    ),
    ReviewSource(
        id="youtube_user_confirmation",
        title="ユーザー判断待ちYouTube",
        path="data/youtube_user_confirmation_queue.json",
        rows_path="items",
        domain="YouTube",
        key_fields=("id", "label"),
        title_fields=("label",),
        subtitle_fields=("detected_event_date", "venue", "decision_needed"),
        option_values=("include_in_main_event_db", "hold", "exclude"),
    ),
    ReviewSource(
        id="x_candidate_post",
        title="X候補アカウント/投稿レビュー",
        path="data/x_candidate_post_review.json",
        rows_path="results",
        domain="X/RSS",
        key_fields=("handle", "name"),
        title_fields=("handle", "name"),
        subtitle_fields=("name", "recommendation", "promote_score"),
        source_decision_fields=("registration_decision", "recommendation"),
        final_decision_fields=("registration_decision",),
        option_values=("promote", "watch", "reject", "hold"),
    ),
    ReviewSource(
        id="rare_signal_backcheck",
        title="rare signal裏どり",
        path="data/rare_signal_backcheck_queue.json",
        rows_path="queue",
        domain="根拠URL",
        key_fields=("candidate_id", "primary_name"),
        title_fields=("primary_name", "possible_event_name"),
        subtitle_fields=("possible_date_text", "possible_venue", "possible_area"),
        priority_fields=("novelty_assessment", "promotion_target"),
        action_fields=("next_action", "backcheck_status"),
        source_decision_fields=("decision", "backcheck_status"),
        description_fields=("oto_interpreted_summary", "novelty_reason"),
        urls_fields=(
            "confirmed_source_urls",
            "internal_discovery_urls",
            "search_queries",
        ),
        option_values=("confirm_non_x_source", "needs_non_x_backcheck", "reject", "hold"),
    ),
)

PENDING_WORDS = (
    "review",
    "needs",
    "manual",
    "queue",
    "candidate",
    "confirm",
    "component",
    "recheck",
    "research",
    "missing",
    "hold",
    "保留",
    "要",
    "確認",
)

CLOSED_WORDS = (
    "already",
    "ignore",
    "out_of_scope",
    "skip_registered",
    "skip",
    "applied",
    "処理済",
    "確認済",
)

ACTION_GROUP_LABELS = {
    "current_date": "日付確認待ち",
    "historical_date": "過去実績日付再調査",
    "song_research": "曲候補待ち",
    "source_url": "根拠URL不足",
    "venue": "会場確認待ち",
    "identity": "同一イベント確認",
    "youtube": "YouTube候補確認",
    "social": "X/RSS確認",
    "other": "その他",
}

AUTO_CONFIRMED_REGISTERED_EVENT_VENUES = (
    {
        "canonical_venue": "京橋プラザ区民館",
        "aliases": ("京橋プラザ", "中央区京橋プラザ", "京橋プラザ区民館"),
        "required_event_tokens": ("銀座一丁目東町会", "新富町会"),
        "min_source_occurrence_count": 3,
        "min_evidence_url_count": 3,
        "decision": "auto_historical_reference_venue_confirmed",
        "reason": "過去実績日があり、複数の観測根拠と公式施設根拠で会場を確信できるため、人間レビューには出しません。",
    },
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def rel_path(path: Path, root: Path = ROOT) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        Path(tmp_name).replace(path)
        path.chmod(0o644)
    finally:
        tmp_path = Path(tmp_name)
        if tmp_path.exists():
            tmp_path.unlink()


def decision_file_lock(path: Path) -> threading.RLock:
    try:
        key = path.resolve().as_posix()
    except OSError:
        key = path.as_posix()
    with _DECISION_LOCKS_GUARD:
        lock = _DECISION_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _DECISION_LOCKS[key] = lock
        return lock


def get_path(obj: Any, dotted: str, default: Any = None) -> Any:
    def walk(cur: Any, parts: list[str]) -> Any:
        if not parts:
            return cur
        part = parts[0]
        rest = parts[1:]
        if isinstance(cur, dict):
            if part not in cur:
                return default
            return walk(cur[part], rest)
        if isinstance(cur, list):
            values = []
            for item in cur:
                value = walk(item, parts)
                if value is default:
                    continue
                if isinstance(value, list):
                    values.extend(value)
                else:
                    values.append(value)
            return values or default
        return default

    return walk(obj, dotted.split("."))


def get_rows(payload: Any, rows_path: str) -> list[Any]:
    if rows_path == ".":
        rows = payload
    else:
        rows = payload
        for part in rows_path.split("."):
            if isinstance(rows, dict):
                rows = rows.get(part, [])
            else:
                rows = []
                break
    return rows if isinstance(rows, list) else []


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "、".join(as_text(item) for item in value if as_text(item))
    if isinstance(value, dict):
        compact = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return compact[:280] + ("..." if len(compact) > 280 else "")
    return str(value).strip()


def first_text(row: dict[str, Any], fields: tuple[str, ...], default: str = "") -> str:
    for field_name in fields:
        text = as_text(get_path(row, field_name))
        if text:
            return text
    return default


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = as_text(value).casefold()
    return text in {"true", "1", "yes", "y", "はい"}


def apply_value_label(value: str) -> str:
    return APPLY_VALUE_LABELS.get(value, value)


def apply_value_help(value: str) -> str:
    return APPLY_VALUE_HELP.get(value, "")


def option_label_for(source: ReviewSource, row: dict[str, Any], value: str) -> str:
    if source.id == "x_candidate_post":
        return {
            "promote": "情報源にする",
            "watch": "様子を見る",
            "reject": "対象外",
            "hold": "後で見る",
        }.get(value, apply_value_label(value))
    if source.id == "historical_promotion_candidate":
        if value == "promote_historical_reference":
            return "同一イベントとして採用"
    if source.id == "registered_event_investigation":
        focus = registered_review_focus(row)
        if focus["id"] == "venue":
            if value == "promote_historical_reference":
                return "過去実績＋会場を採用"
            if value == "needs_research":
                return "会場を要調査"
        if focus["check_value"] == "過去実績日・曜日":
            if value == "needs_research":
                return "日付・曜日を要調査"
        if focus["check_value"] == "2026年日程":
            if value == "promote_historical_reference":
                return "過去実績だけ採用"
            if value == "needs_research":
                return "2026年日程を要調査"
    return apply_value_label(value)


def decision_for_apply_value(value: str) -> str:
    return APPLY_VALUE_DECISIONS.get(value, "accept")


def decision_route(source_id: str, apply_value: str) -> str:
    if source_id == "registered_event_investigation":
        if apply_value == "promote_historical_reference":
            return "historical_reference_only"
        if apply_value == "confirm_current_date":
            return "current_year_confirmed"
        if apply_value == "reject":
            return "reject_candidate"
        if apply_value == "hold":
            return "hold_candidate"
        if apply_value == "needs_research":
            return "research_candidate"
    return apply_value or "console_decision_only"


def effective_root(root: Path, decisions_path: Path) -> Path:
    if root != ROOT or decisions_path == DECISIONS_PATH:
        return root
    try:
        path = decisions_path.resolve()
    except OSError:
        path = decisions_path
    if (
        path.name == "decisions.json"
        and path.parent.name == "review_console"
        and path.parent.parent.name == "data"
    ):
        return path.parent.parent.parent
    return root


def normalize_event_lookup_text(value: str) -> str:
    text = as_text(value).casefold()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[\s　]+", "", text)
    text = re.sub(r"[「」『』【】\[\]()（）・･|｜/／,，、.。:：#＃\"'“”]", "", text)
    return text


def normalize_song_lookup_text(value: str) -> str:
    text = normalize_event_lookup_text(value)
    return re.sub(r"[\-ー–—!！?？]", "", text)


def load_known_song_terms(root: Path = ROOT) -> dict[str, str]:
    db_path = root / "data" / "bon_odori_master.sqlite"
    json_path = root / "data" / "youtube_song_master.json"
    stamp = tuple(
        (str(path), path.stat().st_mtime_ns if path.exists() else -1)
        for path in (db_path, json_path)
    )
    cache_key = str(root)
    cached = _SONG_TERM_CACHE.get(cache_key)
    if cached and cached[0] == stamp:
        return cached[1]

    terms: dict[str, str] = {}

    def add(term: Any, canonical: Any) -> None:
        label = as_text(term)
        canonical_label = as_text(canonical)
        norm = normalize_song_lookup_text(label)
        if not label or not canonical_label or label.casefold() in GENERIC_SONG_TERMS:
            return
        if len(norm) < 3:
            return
        terms.setdefault(norm, canonical_label)

    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            for row in conn.execute("select canonical_title from songs where coalesce(status, '') != '除外'"):
                add(row["canonical_title"], row["canonical_title"])
            for row in conn.execute(
                """
                select a.alias, s.canonical_title
                from song_aliases a
                join songs s on s.song_id = a.song_id
                where coalesce(s.status, '') != '除外'
                """
            ):
                add(row["alias"], row["canonical_title"])
        except sqlite3.Error:
            pass
        finally:
            try:
                conn.close()
            except UnboundLocalError:
                pass

    payload = read_json(json_path, {})
    songs = payload.get("songs") if isinstance(payload, dict) else []
    if isinstance(songs, list):
        for song in songs:
            if not isinstance(song, dict) or not song.get("public_ready", True):
                continue
            canonical = song.get("song_name")
            add(canonical, canonical)
            for alias in song.get("aliases") or []:
                add(alias, canonical)

    _SONG_TERM_CACHE[cache_key] = (stamp, terms)
    return terms


def known_song_matches(text: str, root: Path = ROOT) -> list[str]:
    haystack = normalize_song_lookup_text(text)
    matches: list[str] = []
    matched_norms: list[str] = []
    if not haystack:
        return matches
    for norm, canonical in sorted(load_known_song_terms(root).items(), key=lambda item: len(item[0]), reverse=True):
        if canonical.casefold() in GENERIC_SONG_TERMS:
            continue
        if any(norm in matched_norm or matched_norm in norm for matched_norm in matched_norms):
            continue
        if norm and norm in haystack and canonical not in matches:
            matches.append(canonical)
            matched_norms.append(norm)
        if len(matches) >= 12:
            break
    return matches


def existing_event_name_rows(root: Path = ROOT) -> list[dict[str, str]]:
    db_path = root / "data" / "bon_odori_master.sqlite"
    rows: list[dict[str, str]] = []
    if db_path.exists():
        query = """
            SELECT
              o.occurrence_id,
              o.display_name,
              o.event_year,
              o.date_start,
              o.date_end,
              s.canonical_name
            FROM event_occurrences o
            LEFT JOIN event_series s ON s.series_id = o.series_id
            WHERE COALESCE(o.lifecycle_status, '') != 'archived'
        """
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            for row in conn.execute(query):
                rows.append(
                    {
                        "id": as_text(row["occurrence_id"]),
                        "name": as_text(row["display_name"] or row["canonical_name"]),
                        "series_name": as_text(row["canonical_name"]),
                        "year": as_text(row["event_year"]),
                        "date": as_text(row["date_start"]),
                        "date_end": as_text(row["date_end"]),
                        "venue": "",
                        "source": "bon_odori_master.sqlite",
                    }
                )
        except sqlite3.Error:
            rows = []
        finally:
            try:
                conn.close()
            except UnboundLocalError:
                pass
    if rows:
        return rows
    public_path = root / "data" / "public" / "events_public.json"
    public_events = read_json(public_path, [])
    if isinstance(public_events, list):
        for index, event in enumerate(public_events):
            if not isinstance(event, dict):
                continue
            name = as_text(event.get("display_name") or event.get("name") or event.get("event_name"))
            if not name:
                continue
            rows.append(
                {
                    "id": as_text(event.get("id") or index),
                    "name": name,
                    "series_name": as_text(event.get("name") or event.get("event_name")),
                    "year": as_text(event.get("year") or event.get("event_year")),
                    "date": as_text(event.get("date") or event.get("date_start")),
                    "date_end": as_text(event.get("date_end")),
                    "venue": as_text(event.get("venue")),
                    "source": "events_public.json",
                }
            )
    return rows


def resolve_existing_event_name(name: str, root: Path = ROOT) -> dict[str, Any]:
    raw_name = as_text(name).strip()
    needle = normalize_event_lookup_text(raw_name)
    if not needle:
        return {"status": "empty", "matches": []}
    candidates = []
    for row in existing_event_name_rows(root):
        values = [row.get("name", ""), row.get("series_name", "")]
        normalized_values = [normalize_event_lookup_text(value) for value in values if value]
        if needle in normalized_values:
            row = {**row, "match_type": "exact"}
            candidates.append(row)
            continue
        if any(value.startswith(needle) or needle in value for value in normalized_values):
            row = {**row, "match_type": "partial"}
            candidates.append(row)
    deduped: dict[str, dict[str, str]] = {}
    for row in candidates:
        key = row.get("id") or f"{row.get('name')}|{row.get('year')}|{row.get('venue')}"
        deduped[key] = row
    matches = list(deduped.values())
    exact = [row for row in matches if row.get("match_type") == "exact"]
    if len(exact) == 1:
        return {"status": "ok", "match": exact[0], "matches": exact}
    if len(exact) > 1:
        return {"status": "ambiguous", "matches": exact[:8]}
    if len(matches) == 1:
        return {"status": "ok", "match": matches[0], "matches": matches}
    if len(matches) > 1:
        return {"status": "ambiguous", "matches": matches[:8]}
    return {"status": "not_found", "matches": []}


def format_event_match(row: dict[str, Any]) -> str:
    parts = [as_text(row.get("name"))]
    if as_text(row.get("year")):
        parts.append(as_text(row.get("year")))
    if as_text(row.get("venue")):
        parts.append(as_text(row.get("venue")))
    return " / ".join(part for part in parts if part)


def current_year_date_values(row: dict[str, Any]) -> list[str]:
    target_year = as_text(row.get("event_year") or row.get("target_event_year") or "2026")
    fields = (
        "date_start",
        "current_date_start",
        "current_date",
        "target_current_date",
        "confirmed_date_start",
    )
    values: list[str] = []
    for field_name in fields:
        text = as_text(get_path(row, field_name))
        if text and text.startswith(f"{target_year}-"):
            values.append(text)
    return values


WEEKDAY_LABELS = ["月", "火", "水", "木", "金", "土", "日"]


def parse_iso_date(value: Any) -> date | None:
    text = as_text(value)
    if not text or not re.match(r"^20\d{2}-\d{2}-\d{2}$", text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def date_with_weekday(value: Any) -> str:
    parsed = parse_iso_date(value)
    if not parsed:
        return as_text(value)
    return f"{parsed.isoformat()}（{WEEKDAY_LABELS[parsed.weekday()]}）"


def observed_candidate(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("observed_candidate")
    return value if isinstance(value, dict) else {}


def historical_date_values(row: dict[str, Any]) -> list[str]:
    observed = observed_candidate(row)
    values: list[str] = []
    raw_values = observed.get("proposed_date_values")
    if isinstance(raw_values, list):
        values.extend(as_text(value) for value in raw_values)
    for key in ("proposed_date_start", "proposed_date_end"):
        text = as_text(observed.get(key))
        if text:
            values.append(text)
    seen: set[str] = set()
    output = []
    for value in values:
        if not parse_iso_date(value) or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return sorted(output)


def historical_date_range_label(row: dict[str, Any]) -> str:
    values = historical_date_values(row)
    if not values:
        return ""
    if len(values) == 1:
        return date_with_weekday(values[0])
    return f"{date_with_weekday(values[0])}〜{date_with_weekday(values[-1])}"


def historical_weekday_label(row: dict[str, Any]) -> str:
    values = historical_date_values(row)
    if not values:
        return ""
    labels = []
    for value in (values[0], values[-1]):
        parsed = parse_iso_date(value)
        if parsed:
            label = WEEKDAY_LABELS[parsed.weekday()]
            if label not in labels:
                labels.append(label)
    return "〜".join(labels)


def registered_candidate_venue(row: dict[str, Any]) -> str:
    observed = observed_candidate(row)
    for field_name in (
        "proposed_venue",
        "target_current_venue",
        "current_venue",
    ):
        text = as_text(observed.get(field_name))
        if text:
            return text
    for field_name in (
        "candidate_venue_name",
        "venue",
        "target_current_venue",
        "current_venue",
    ):
        text = as_text(get_path(row, field_name))
        if text:
            return text
    known = row.get("known_venue_names")
    if isinstance(known, list):
        return "、".join(as_text(value) for value in known if as_text(value))
    return as_text(known)


def registered_review_focus(row: dict[str, Any]) -> dict[str, str]:
    has_historical_date = bool(historical_date_values(row))
    has_current_date = bool(current_year_date_values(row))
    missing_current_date = bool_value(row.get("missing_date")) or not has_current_date
    missing_venue = bool_value(row.get("missing_venue"))
    venue = registered_candidate_venue(row)

    if not has_historical_date:
        return {
            "id": "current_date",
            "label": "日付確認待ち",
            "reason": "過去実績日が不足しています。人間には日付・曜日を確認してほしい候補です。",
            "note": "過去実績の日付・曜日が確認できません。採用すると確認機会が減るため、保留または要調査を優先してください。",
            "check_label": "確認対象",
            "check_value": "過去実績日・曜日",
            "check_kind": "block",
            "check_message": "日付がないため、人間に確認してほしい主対象です。",
        }
    if missing_venue:
        if venue:
            reason = f"過去実績日は候補から取得済みです。確認してほしいのは会場「{venue}」を採用・要調査・保留のどれにするかです。"
            check_value = f"会場: {venue}"
            check_kind = "warn"
            check_message = "日付ではなく、この会場候補を採用してよいかを確認してください。"
        else:
            reason = "過去実績日は候補から取得済みです。確認してほしいのは会場不足を要調査に回すか、保留するかです。"
            check_value = "会場未確認"
            check_kind = "block"
            check_message = "会場候補がないため、採用より要調査または保留向きです。"
        return {
            "id": "venue",
            "label": "会場確認待ち",
            "reason": reason,
            "note": "過去実績日は候補から取得済みです。人間に確認してほしい主対象は会場です。",
            "check_label": "確認対象",
            "check_value": check_value,
            "check_kind": check_kind,
            "check_message": check_message,
        }
    if missing_current_date:
        return {
            "id": "current_date",
            "label": "日付確認待ち",
            "reason": "過去実績日は候補から取得済みです。確認してほしいのは2026年日程を未確認のまま扱うか、追加調査に回すかです。",
            "note": "この候補は2026年日程未確認です。採用する場合は「過去実績として採用」に留め、日程確認済みにはしません。",
            "check_label": "確認対象",
            "check_value": "2026年日程",
            "check_kind": "warn",
            "check_message": "過去日付ではなく、今年の日程を未確認扱いにするかを確認してください。",
        }
    return {
        "id": "identity",
        "label": "同一イベント確認",
        "reason": "日付と会場は揃っています。同一イベントとして扱ってよいかを確認します。",
        "note": "日付・会場が揃っているため、同一イベントとして扱えるかを確認してください。",
        "check_label": "確認対象",
        "check_value": "同一イベント性",
        "check_kind": "warn",
        "check_message": "既存イベント系列へ統合してよいかを確認してください。",
    }


def observed_count(observed: dict[str, Any], count_key: str, sample_key: str) -> int:
    value = observed.get(count_key)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    sample = observed.get(sample_key)
    return len(sample) if isinstance(sample, list) else 0


def load_historical_reference_index(root: Path = ROOT) -> dict[str, list[dict[str, Any]]]:
    db_path = root / "data" / "bon_odori_master.sqlite"
    if not db_path.exists():
        return {}
    query = """
        SELECT occurrence_id, date_start, date_end, confidence, basis
        FROM occurrence_dates
        WHERE date_type = 'historical_reference'
        ORDER BY date_start
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute(query)]
    except sqlite3.Error:
        return {}
    finally:
        try:
            conn.close()
        except UnboundLocalError:
            pass
    refs: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        basis_text = as_text(row.get("basis"))
        try:
            basis = json.loads(basis_text) if basis_text else {}
        except ValueError:
            basis = {"raw": basis_text} if basis_text else {}
        row["basis"] = basis if isinstance(basis, dict) else {"raw": basis}
        refs.setdefault(as_text(row.get("occurrence_id")), []).append(row)
    return refs


def historical_reference_range_label(ref: dict[str, Any]) -> str:
    start = as_text(ref.get("date_start"))
    end = as_text(ref.get("date_end"))
    if start and end and end != start:
        return f"{date_with_weekday(start)}〜{date_with_weekday(end)}"
    return date_with_weekday(start)


def existing_historical_reference_resolution(
    row: dict[str, Any],
    historical_refs: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, str] | None:
    occurrence_id = as_text(row.get("occurrence_id"))
    if not occurrence_id or not historical_refs:
        return None
    refs = historical_refs.get(occurrence_id) or []
    if not refs:
        return None
    ref = refs[-1]
    basis = ref.get("basis") if isinstance(ref.get("basis"), dict) else {}
    venue = as_text(basis.get("historical_venue_name")) or registered_candidate_venue(row)
    historical_date = historical_reference_range_label(ref)
    if not historical_date:
        return None
    return {
        "decision": "auto_stale_queue_historical_reference_already_recorded",
        "label": "自動解決",
        "reason": "過去実績日がマスターDBに登録済みのため、この調査キューは古いものとして人間レビューには出しません。",
        "canonical_venue": venue or "登録済み過去実績",
        "venue": venue,
        "historical_date": historical_date,
        "source_occurrence_count": "",
        "evidence_url_count": "",
    }


def compact_review_text(value: Any) -> str:
    return re.sub(r"[\s・/／()（）【】「」『』]+", "", as_text(value)).casefold()


def registered_auto_resolution(
    row: dict[str, Any],
    historical_refs: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, str] | None:
    existing = existing_historical_reference_resolution(row, historical_refs)
    if existing:
        return existing
    if not historical_date_values(row):
        return None
    observed = observed_candidate(row)
    venue = registered_candidate_venue(row)
    venue_norm = compact_review_text(venue)
    if not venue_norm:
        return None
    source_count = observed_count(observed, "source_occurrence_count", "source_occurrence_ids")
    evidence_count = observed_count(observed, "evidence_url_count", "evidence_urls_sample")
    context = compact_review_text(
        " ".join(
            [
                as_text(row.get("event_name")),
                as_text(observed.get("proposed_event_name")),
                as_text(observed.get("organizers")),
                as_text(observed.get("matched_tokens")),
            ]
        )
    )
    for rule in AUTO_CONFIRMED_REGISTERED_EVENT_VENUES:
        alias_norms = [compact_review_text(alias) for alias in rule["aliases"]]
        if not any(alias and (alias in venue_norm or venue_norm in alias) for alias in alias_norms):
            continue
        if source_count < rule["min_source_occurrence_count"]:
            continue
        if evidence_count < rule["min_evidence_url_count"]:
            continue
        if not all(compact_review_text(token) in context for token in rule["required_event_tokens"]):
            continue
        return {
            "decision": rule["decision"],
            "label": "自動解決",
            "reason": rule["reason"],
            "canonical_venue": rule["canonical_venue"],
            "venue": venue,
            "historical_date": historical_date_range_label(row),
            "source_occurrence_count": str(source_count),
            "evidence_url_count": str(evidence_count),
        }
    return None


def auto_source_resolution(
    source: ReviewSource,
    row: dict[str, Any],
    historical_refs: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, str] | None:
    if source.id == "registered_event_investigation":
        return registered_auto_resolution(row, historical_refs)
    return None


def youtube_target_event(row: dict[str, Any]) -> dict[str, Any] | None:
    matched = row.get("matched_public_event")
    if isinstance(matched, dict) and as_text(matched.get("name")):
        return {
            "name": as_text(matched.get("name")),
            "venue": as_text(matched.get("venue")),
            "date": as_text(matched.get("date")),
            "date_end": as_text(matched.get("date_end")),
            "area": as_text(matched.get("area")),
            "score": as_text(matched.get("score")),
            "match_reasons": matched.get("reasons") if isinstance(matched.get("reasons"), list) else [],
            "source": "matched_public_event",
        }
    occurrences = row.get("setlist_occurrences")
    if isinstance(occurrences, list):
        candidates = [
            occurrence
            for occurrence in occurrences
            if isinstance(occurrence, dict)
            and as_text(occurrence.get("event_name"))
            and isinstance(occurrence.get("matched_public_event"), dict)
            and as_text(occurrence["matched_public_event"].get("name"))
        ]
        candidates.sort(key=setlist_occurrence_rank, reverse=True)
        for occurrence in candidates:
            matched = occurrence["matched_public_event"]
            return {
                "id": as_text(matched.get("id") or occurrence.get("occurrence_key")),
                "name": as_text(matched.get("name")),
                "venue": as_text(matched.get("venue") or occurrence.get("venue")),
                "date": as_text(matched.get("date") or occurrence.get("event_date")),
                "date_end": as_text(matched.get("date_end")),
                "area": as_text(matched.get("area")),
                "score": as_text(matched.get("score") or occurrence.get("confidence")),
                "match_reasons": matched.get("reasons") if isinstance(matched.get("reasons"), list) else ["setlist_occurrence_public_match"],
                "source": "setlist_matched_public_event",
            }
    return None


def setlist_occurrence_rank(occurrence: dict[str, Any]) -> tuple[int, int, int]:
    try:
        song_count = int(occurrence.get("song_count") or 0)
    except (TypeError, ValueError):
        song_count = 0
    confidence_score = {"high": 3, "medium": 2, "low": 1}.get(
        as_text(occurrence.get("confidence")).casefold(),
        0,
    )
    name = as_text(occurrence.get("event_name"))
    branch_penalty = 0
    if re.search(r"^\s*[【\[]", name) and re.search(r"[0-9０-９]\s", name):
        branch_penalty += 1
    if re.search(r"[0-9０-９]+終?\s*$", name):
        branch_penalty += 1
    return (song_count, confidence_score, -branch_penalty)


def youtube_target_event_matches_name(target: dict[str, Any] | None, name: str) -> bool:
    if not target:
        return False
    needle = normalize_event_lookup_text(name)
    target_name = normalize_event_lookup_text(as_text(target.get("name")))
    if not needle or not target_name:
        return False
    return needle == target_name or needle in target_name


def youtube_target_event_match_payload(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": as_text(target.get("id")),
        "name": as_text(target.get("name")),
        "series_name": as_text(target.get("name")),
        "year": as_text(target.get("date"))[:4],
        "date": as_text(target.get("date")),
        "date_end": as_text(target.get("date_end")),
        "venue": as_text(target.get("venue")),
        "source": as_text(target.get("source")) or "youtube_target_event",
        "match_type": "youtube_target_event",
    }


def youtube_parent_component(row: dict[str, Any]) -> dict[str, str] | None:
    component = row.get("parent_event_component")
    if isinstance(component, dict):
        parent = as_text(component.get("parent_event_name"))
        label = as_text(component.get("component_label"))
        reason = as_text(component.get("component_reason"))
    else:
        parent = as_text(row.get("parent_event_name"))
        label = as_text(row.get("component_label"))
        reason = as_text(row.get("component_reason"))
    if not parent and not label:
        return None
    return {
        "parent_event_name": parent,
        "component_label": label,
        "component_reason": reason,
    }


def youtube_auto_closed_parent_component(row: dict[str, Any], root: Path = ROOT) -> bool:
    if not youtube_parent_component(row):
        return False
    if not youtube_song_candidates(row, root=root):
        return False
    return as_text(row.get("action")) == "bon_component_of_parent_event" or as_text(row.get("auto_review_note")) == "parent_event_song_clip_fragment"


def manual_youtube_target_event(name: str) -> dict[str, Any] | None:
    name = as_text(name).strip()
    if not name:
        return None
    return {
        "name": name,
        "venue": "",
        "date": "",
        "date_end": "",
        "area": "",
        "score": "",
        "match_reasons": ["manual_review_input"],
        "source": "manual_review_input",
    }


def youtube_song_candidates(row: dict[str, Any], root: Path = ROOT) -> list[str]:
    candidates: list[str] = []

    def add(value: Any) -> None:
        text = as_text(value).strip()
        if text and text not in candidates:
            candidates.append(text)

    songs = row.get("songs")
    if isinstance(songs, list):
        for song in songs:
            if isinstance(song, dict):
                add(song.get("name") or song.get("song_name") or song.get("title"))
            else:
                add(song)
    occurrences = row.get("setlist_occurrences")
    if isinstance(occurrences, list):
        for occurrence in occurrences:
            if not isinstance(occurrence, dict):
                continue
            for song in occurrence.get("setlist") or []:
                if isinstance(song, dict):
                    add(song.get("song_name") or song.get("name") or song.get("title"))
    title = as_text(row.get("title"))
    title_candidates = row.get("title_song_candidates")
    title_texts = [title]
    if isinstance(title_candidates, list):
        for candidate in title_candidates:
            title_texts.append(as_text(candidate))
    else:
        for candidate in split_youtube_title(title).get("title_song_candidates", []):
            title_texts.append(as_text(candidate))
    for song in known_song_matches(" ".join(title_texts), root=root):
        add(song)
    return candidates[:12]


def route_checks(
    source: ReviewSource,
    row: dict[str, Any],
    historical_refs: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, str]]:
    if source.id == "x_candidate_post":
        return [
            {
                "kind": "ok",
                "label": "保存先",
                "value": "x_candidate_post_review.json",
                "message": "この画面の判断は候補JSONの registration_decision に直接保存します。",
            },
            {
                "kind": "warn",
                "label": "変わらないもの",
                "value": "Notion/公開サイト",
                "message": "このボタンだけではNotion登録、公開JSON、Master RDBは変更しません。",
            },
            {
                "kind": "ok",
                "label": "次の評価",
                "value": "月次/シーズン中隔週",
                "message": "登録後は最近の有用投稿数、未来日程投稿、ノイズ率、最終有用投稿日で見直します。",
            },
        ]
    if source.id == "youtube_active_video":
        target = youtube_target_event(row)
        if not target:
            component = youtube_parent_component(row)
            if component:
                return [
                    {
                        "kind": "warn",
                        "label": "親イベント",
                        "value": component["parent_event_name"] or "未特定",
                        "message": "既存イベントに直接追加する候補ではなく、親イベント内の盆踊り企画として扱います。",
                    },
                    {
                        "kind": "ok",
                        "label": "盆踊り企画",
                        "value": component["component_label"] or "未特定",
                        "message": "保存するなら 3「親イベント内の盆踊り企画」を選んでください。",
                    },
                ]
            return [
                {
                    "kind": "block",
                    "label": "追加先イベント",
                    "value": "未特定",
                    "message": "右側の追加先イベント名に既存イベント名を書いてから、既存イベントへ追加を押してください。",
                }
            ]
        checks = [
            {
                "kind": "ok",
                "label": "追加先イベント",
                "value": target["name"],
                "message": "この既存イベントのYouTube動画・曲目候補・現場証拠として扱います。",
            }
        ]
        if target.get("date"):
            checks.append(
                {
                    "kind": "ok",
                    "label": "追加先日付",
                    "value": target["date"],
                    "message": "動画側の検出日付と既存イベントの日付照合に使います。",
                }
            )
        if target.get("venue"):
            checks.append(
                {
                    "kind": "ok",
                    "label": "追加先会場",
                    "value": target["venue"],
                    "message": "同名別イベントとの混同を避けるための確認材料です。",
                }
            )
        return checks
    if source.id == "rare_signal_backcheck":
        confirmed_urls = get_path(row, "confirmed_source_urls")
        confirmed_count = len(confirmed_urls) if isinstance(confirmed_urls, list) else (1 if as_text(confirmed_urls) else 0)
        checks = [
            {
                "kind": "block" if not confirmed_count else "ok",
                "label": "非X確認URL",
                "value": f"{confirmed_count}件" if confirmed_count else "未確認",
                "message": "公式/主催/自治体/会場/地域媒体など、X以外の根拠URLが必要です。",
            },
            {
                "kind": "warn",
                "label": "Xの扱い",
                "value": "発見ソースのみ",
                "message": "X本文は公開文に使わず、おとの要約と確認済み非X根拠から登録します。",
            },
        ]
        if as_text(row.get("possible_date_text")):
            checks.append(
                {
                    "kind": "ok",
                    "label": "日付候補",
                    "value": as_text(row.get("possible_date_text")),
                    "message": "確認URL側でも同じ日付を確認してください。",
                }
            )
        else:
            checks.append(
                {
                    "kind": "warn",
                    "label": "日付候補",
                    "value": "未抽出",
                    "message": "登録候補に進める前に日付または開催時期を補ってください。",
                }
            )
        venue_or_area = " / ".join(
            value for value in [as_text(row.get("possible_venue")), as_text(row.get("possible_area"))] if value
        )
        checks.append(
            {
                "kind": "ok" if venue_or_area else "warn",
                "label": "会場/地域候補",
                "value": venue_or_area or "未抽出",
                "message": "登録粒度に必要な会場または地域を確認してください。",
            }
        )
        return checks
    if source.id == "historical_reference_quality":
        issues = get_path(row, "issue_codes") if isinstance(get_path(row, "issue_codes"), list) else []
        date_label = as_text(row.get("historical_dates_label"))
        weekday = as_text(row.get("historical_weekdays_label"))
        song_count = as_text(row.get("song_count"))
        checks = []
        if "historical_date_missing" in issues or "historical_date_invalid" in issues or not date_label:
            checks.append(
                {
                    "kind": "block",
                    "label": "過去実績日",
                    "value": date_label or "未確認",
                    "message": "過去実績としての価値が低いため、日付・曜日の再確認が必要です。",
                }
            )
            checks.append(
                {
                    "kind": "block",
                    "label": "曜日",
                    "value": weekday or "未確認",
                    "message": "日付が確定しないと曜日も確定できません。",
                }
            )
        else:
            checks.append(
                {
                    "kind": "ok",
                    "label": "過去実績日",
                    "value": date_label,
                    "message": "過去年の開催日として残っています。",
                }
            )
            checks.append(
                {
                    "kind": "ok",
                    "label": "曜日",
                    "value": weekday,
                    "message": "日付から算出済みです。",
                }
            )
        if "historical_songs_missing" in issues:
            checks.append(
                {
                    "kind": "warn",
                    "label": "曲候補",
                    "value": "なし",
                    "message": "過去実績は残っていますが、曲収集のレビュー対象です。",
                }
            )
        else:
            checks.append(
                {
                    "kind": "ok",
                    "label": "曲候補",
                    "value": f"{song_count or '0'}曲",
                    "message": "曲候補があります。",
                }
            )
        return checks
    if source.id != "registered_event_investigation":
        return []
    observed = observed_candidate(row)
    date_label = historical_date_range_label(row)
    weekday = historical_weekday_label(row)
    confidence = as_text(row.get("observed_candidate_confidence") or observed.get("promotion_confidence"))
    evidence_count = observed_count(observed, "evidence_url_count", "evidence_urls_sample")
    source_count = observed_count(observed, "source_occurrence_count", "source_occurrence_ids")
    song_count = observed_count(observed, "song_title_count", "song_titles_sample")
    songs = observed.get("song_titles_sample") if isinstance(observed.get("song_titles_sample"), list) else []
    song_sample = "、".join(as_text(song) for song in songs[:3] if as_text(song))

    checks: list[dict[str, str]] = []
    auto = registered_auto_resolution(row, historical_refs)
    if auto:
        checks.append(
            {
                "kind": "ok",
                "label": "自動解決",
                "value": auto["canonical_venue"],
                "message": auto["reason"],
            }
        )
    else:
        focus = registered_review_focus(row)
        checks.append(
            {
                "kind": focus["check_kind"],
                "label": focus["check_label"],
                "value": focus["check_value"],
                "message": focus["check_message"],
            }
        )
    if date_label:
        checks.append(
            {
                "kind": "ok",
                "label": "過去実績日",
                "value": date_label,
                "message": "過去年の開催日として残せます。",
            }
        )
        checks.append(
            {
                "kind": "ok",
                "label": "曜日",
                "value": weekday,
                "message": "日付から算出済みです。",
            }
        )
    else:
        checks.append(
            {
                "kind": "block",
                "label": "過去実績日",
                "value": "未確認",
                "message": "日付・曜日がないため、過去実績採用より保留/要調査向きです。",
            }
        )
        checks.append(
            {
                "kind": "block",
                "label": "曜日",
                "value": "未確認",
                "message": "日付がないため曜日も確定できません。",
            }
        )

    if evidence_count:
        checks.append(
            {
                "kind": "ok",
                "label": "証拠URL",
                "value": f"{evidence_count}件",
                "message": "採用後の根拠確認に使えます。",
            }
        )
    else:
        checks.append(
            {
                "kind": "warn",
                "label": "証拠URL",
                "value": "なし",
                "message": "根拠URL不足なら保留/要調査にしてください。",
            }
        )

    if source_count or confidence:
        checks.append(
            {
                "kind": "ok" if confidence in {"high", "medium"} else "warn",
                "label": "過去候補強度",
                "value": " / ".join(value for value in [confidence, f"{source_count}件"] if value),
                "message": "同一イベントとして扱えるかの目安です。",
            }
        )

    if song_count:
        checks.append(
            {
                "kind": "warn",
                "label": "曲候補",
                "value": f"{song_count}曲" + (f": {song_sample}" if song_sample else ""),
                "message": "候補には残りますが、この採用操作だけでは曲を確定登録しません。",
            }
        )
    else:
        checks.append(
            {
                "kind": "warn",
                "label": "曲候補",
                "value": "なし",
                "message": "曲データ収集は別工程で必要です。",
            }
        )

    checks.append(
        {
            "kind": "warn",
            "label": "曲収集ルート",
            "value": "別工程",
            "message": "song_occurrences/YouTubeバックフィル側で確認します。必要なら要調査メモに残します。",
        }
    )
    return checks


def date_range_text(start: Any, end: Any = "") -> str:
    start_text = as_text(start)
    end_text = as_text(end)
    if start_text and end_text and end_text != start_text:
        return f"{start_text}〜{end_text}"
    return start_text or end_text


def historical_exact_dates_text(row: dict[str, Any]) -> str:
    exact_dates = row.get("exact_dates")
    if not isinstance(exact_dates, dict):
        return ""
    parts: list[str] = []
    for year, dates in sorted(exact_dates.items(), key=lambda item: str(item[0])):
        if isinstance(dates, list):
            date_text = " / ".join(as_text(date) for date in dates if as_text(date))
        else:
            date_text = as_text(dates)
        if date_text:
            parts.append(f"{year}: {date_text}")
    return "、".join(parts)


def historical_year_only_text(row: dict[str, Any]) -> str:
    year_only = row.get("year_only_evidence")
    if not isinstance(year_only, dict) or not year_only:
        return ""
    parts = [f"{year}: {count}件" for year, count in sorted(year_only.items(), key=lambda item: str(item[0]))]
    return "、".join(parts)


def comparison_summary(source: ReviewSource, row: dict[str, Any]) -> dict[str, Any] | None:
    if source.id != "historical_promotion_candidate":
        return None
    target_date = date_range_text(row.get("target_date_start"), row.get("target_date_end"))
    exact_dates = historical_exact_dates_text(row)
    year_only = historical_year_only_text(row)
    candidate_meta = [
        f"追加対象年: {as_text(row.get('insertable_historical_years')) or as_text(row.get('historical_years'))}",
        f"日付候補: {exact_dates}" if exact_dates else "",
        f"年のみ根拠: {year_only}" if year_only else "",
    ]
    evidence_meta = [
        f"match_score {as_text(row.get('match_score'))}" if as_text(row.get("match_score")) else "",
        f"confidence {as_text(row.get('promotion_confidence'))}" if as_text(row.get("promotion_confidence")) else "",
        f"証拠URL {as_text(row.get('evidence_url_count'))}件" if as_text(row.get("evidence_url_count")) else "",
        f"曲候補 {as_text(row.get('song_title_count'))}件" if as_text(row.get("song_title_count")) else "",
    ]
    return {
        "title": "同一イベントとして扱うか",
        "question": "左の過去実績候補を、右の既存開催回/イベント系列に紐づけてよいかを判断します。",
        "candidate": {
            "label": "過去実績候補",
            "name": as_text(row.get("event_name")),
            "meta": [text for text in candidate_meta if text],
        },
        "target": {
            "label": "紐づけ先の既存開催回",
            "name": as_text(row.get("event_name")),
            "meta": [
                text
                for text in [
                    f"開催年: {as_text(row.get('target_year'))}" if as_text(row.get("target_year")) else "",
                    f"開催日: {target_date}" if target_date else "",
                    f"会場: {as_text(row.get('venue'))}" if as_text(row.get("venue")) else "",
                    f"状態: {as_text(row.get('target_date_status'))}" if as_text(row.get("target_date_status")) else "",
                    f"occurrence_id: {as_text(row.get('target_occurrence_id'))}" if as_text(row.get("target_occurrence_id")) else "",
                ]
                if text
            ],
        },
        "evidence": [text for text in evidence_meta if text],
    }


def option_disabled_reason(source: ReviewSource, row: dict[str, Any], value: str) -> str:
    if source.id == "historical_reference_quality":
        issues = get_path(row, "issue_codes") if isinstance(get_path(row, "issue_codes"), list) else []
        has_date_issue = "historical_date_missing" in issues or "historical_date_invalid" in issues
        has_song_issue = "historical_songs_missing" in issues
        if value == "needs_date_research" and not has_date_issue:
            return "日付・曜日は残っているため、この行では曲候補の再調査が主対象です"
        if value == "needs_song_research" and not has_song_issue:
            return "曲候補は残っているため、この行では日付・曜日の再調査が主対象です"
    if source.id == "registered_event_investigation" and value == "promote_historical_reference":
        if not historical_date_values(row):
            return "過去実績の日付が無いため、採用せず保留/要調査にしてください"
    if source.id == "registered_event_investigation" and value == "confirm_current_date":
        if bool_value(row.get("missing_date")) or not current_year_date_values(row):
            return "この候補には2026年日程が無いため選べません"
    if source.id == "youtube_active_video" and value == "append_existing_event":
        if youtube_parent_component(row) and not youtube_target_event(row):
            return "既存イベント未登録の親イベント内企画です。3「親イベント内の盆踊り企画」を選んでください"
        return ""
    if source.id == "youtube_active_video" and value == "bon_component_of_parent_event":
        if youtube_parent_component(row) and youtube_target_event(row):
            return "追加先イベントが見つかっています。動画・曲を追加する場合は1を選んでください"
        return ""
    return ""


def option_help_for(source: ReviewSource, row: dict[str, Any], value: str) -> str:
    if source.id == "x_candidate_post":
        return {
            "promote": "このアカウントを今後の盆踊り情報源にします。候補JSONへ registration_decision=登録 を直接保存します。",
            "watch": "今すぐ登録せず、候補として様子を見ます。候補JSONへ registration_decision=監視 を保存します。",
            "reject": "盆踊り情報源として扱いません。候補JSONへ registration_decision=不採用 を保存します。",
            "hold": "判断を先送りします。候補JSONへ registration_decision=保留 を保存します。",
        }.get(value, "")
    if source.id == "historical_promotion_candidate":
        if value == "promote_historical_reference":
            return "左の過去実績候補を、右の既存開催回/イベント系列に紐づけます。"
        if value == "reject":
            return "同一イベントではない、または反映対象にしない場合に使います。"
        if value == "needs_research":
            return "同一イベントとして扱えるか追加確認が必要な場合に使います。"
    if source.id == "rare_signal_backcheck":
        if value == "confirm_non_x_source":
            return "公式/主催/自治体/会場/地域媒体など、X以外の確認URLが見つかった場合に使います。メモに確認URLと補足を書いてください。"
        if value == "needs_non_x_backcheck":
            return "X由来の発見として価値はあるが、確認URLがまだ無い場合に追加調査へ回します。"
        if value == "reject":
            return "別イベントではない、ノイズ、重複、または盆助に載せる粒度ではない場合に使います。"
        if value == "hold":
            return "判断材料が足りないが、すぐ却下しない場合に保留します。"
    if source.id == "registered_event_investigation":
        focus = registered_review_focus(row)
        venue = registered_candidate_venue(row)
        if (
            focus["id"] != "venue"
            and value == "needs_research"
            and (bool_value(row.get("missing_date")) or not current_year_date_values(row))
        ):
            return "追加調査に回します。2026年根拠は見つかったがこの行に日付が無い場合も、日付補完apply待ちとして使います。"
        if focus["id"] == "venue":
            if value == "promote_historical_reference":
                if venue:
                    return f"過去実績日は候補から採用します。会場「{venue}」も過去実績の会場候補として扱ってよい場合に使います。"
                return "過去実績日は候補から採用します。会場なしでも過去実績として残してよい場合だけ使います。"
            if value == "needs_research":
                return "会場が不明、または人間判断だけでは足りない場合に調査リストへ回します。"
            if value == "hold":
                return "今は調査リストにも入れず、次回以降に再判断します。"
        if focus["check_value"] == "過去実績日・曜日":
            if value == "needs_research":
                return "過去実績日・曜日を追加調査に回します。"
            if value == "hold":
                return "今は反映も調査化もせず、後で再判断します。"
        if focus["check_value"] == "2026年日程":
            if value == "promote_historical_reference":
                return "過去実績としては採用し、2026年日程は未確認のまま残します。"
    return apply_value_help(value)


def research_advice(source: ReviewSource, row: dict[str, Any]) -> dict[str, str]:
    if source.id == "rare_signal_backcheck":
        return {
            "status": "非X裏どり待ち",
            "priority": "high" if as_text(row.get("novelty_assessment")) == "new" else "medium",
            "message": "Xは発見ソースです。search_queries を使い、公式/主催/自治体/会場/地域媒体のURLで確認できたものだけ登録候補へ送ります。",
        }
    if source.id == "registered_event_investigation":
        focus = registered_review_focus(row)
        urls = urls_for(source, row)
        url_text = " ".join(urls).casefold()
        if "drive.google.com" in url_text:
            return {
                "status": "OCR待ち",
                "priority": "medium",
                "message": "Google Drive画像の本文OCRでイベント名・主催・時刻・日付を確認。2026公式告知が別にあるかも検索。",
            }
        if "x.com/" in url_text or "twitter.com/" in url_text:
            return {
                "status": "投稿確認待ち",
                "priority": "medium",
                "message": "X投稿本文と投稿者の信頼性を確認。公式/自治体/主催ページで裏取りできるか追加検索。",
            }
        if focus["id"] == "venue":
            return {
                "status": "同一性確認待ち",
                "priority": "medium",
                "message": "候補会場と既存会場が同じか確認。町会名・神社祭礼名・開催場所の対応を見る。",
            }
        if focus["check_value"] == "2026年日程":
            return {
                "status": "公式探索待ち",
                "priority": "high",
                "message": "2026年の公式/自治体/主催/会場告知を探す。過去年根拠だけなら2026確定にしない。",
            }
        if focus["check_value"] == "過去実績日・曜日":
            return {
                "status": "過去実績日確認待ち",
                "priority": "high",
                "message": "過去年の開催日・曜日が読める根拠を探す。日付が取れたら過去実績補完候補。",
            }
    if source.id == "predicted_occurrence_research":
        return {
            "status": "公式探索待ち",
            "priority": "high",
            "message": "予測日を2026確定にできる直接根拠を探す。過去年実績や曜日則だけなら予測保持/要調査。",
        }
    if source.id == "missing_source_url":
        return {
            "status": "根拠URL探索待ち",
            "priority": "high",
            "message": "公開判断に使える公式/自治体/主催/会場URLを探す。個人投稿だけなら弱い根拠として扱う。",
        }
    if source.id == "missing_occurrence_venue":
        return {
            "status": "会場同定待ち",
            "priority": "medium",
            "message": "候補会場名・住所・主催文脈を照合し、既存会場に統合するか新規会場にするか判断。",
        }
    if source.id == "youtube_active_video":
        return {
            "status": "公式裏取り待ち",
            "priority": "medium",
            "message": "動画は過去実績・曲目根拠として使い、開催日確定には公式/主催告知を優先して探す。",
        }
    return {
        "status": "追加確認待ち",
        "priority": "normal",
        "message": "採用・不採用に必要な不足情報を確認。",
    }


def apply_options(source: ReviewSource, row: dict[str, Any]) -> list[dict[str, Any]]:
    options = []
    for value in source.option_values:
        disabled_reason = option_disabled_reason(source, row, value)
        options.append(
            {
                "value": value,
                "label": option_label_for(source, row, value),
                "help": option_help_for(source, row, value),
                "decision": decision_for_apply_value(value),
                "disabled": bool(disabled_reason),
                "disabled_reason": disabled_reason,
            }
        )
    if source.id == "historical_reference_quality":
        options.sort(key=lambda option: (option["disabled"], source.option_values.index(option["value"])))
    return options


def route_note(
    source: ReviewSource,
    row: dict[str, Any],
    historical_refs: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    if source.id == "x_candidate_post":
        return "X/RSSの情報源候補です。ここは2段式ではありません。押した判断を候補JSONの registration_decision に直接保存します。"
    if source.id == "rare_signal_backcheck":
        return "X由来のrare signalです。X本文は公開文に使わず、非Xの確認URLが取れたものだけ登録候補へ進めます。"
    if source.id == "youtube_active_video":
        target = youtube_target_event(row)
        if target:
            return f"追加先候補: {target['name']}。この動画をイベント新規作成ではなく、既存イベントの動画・曲証拠として扱うか確認します。"
        component = youtube_parent_component(row)
        if component:
            label = component["component_label"] or "盆踊り企画"
            parent = component["parent_event_name"] or "親イベント"
            return f"{parent} 内の {label} です。既存イベントが未登録なので、1ではなく3「親イベント内の盆踊り企画」で文脈保持します。"
        return "追加先イベントが未特定です。既存イベントに紐付ける場合は、右側の追加先イベント名に既存イベント名を書いて保存してください。"
    if source.id == "historical_reference_quality":
        return "これは採用済み過去実績の再点検です。日付・曜日・曲候補が足りないものだけをレビューに出しています。"
    if source.id != "registered_event_investigation":
        return ""
    auto = registered_auto_resolution(row, historical_refs)
    if auto:
        return f"自動解決済みです。{auto['reason']}"
    return registered_review_focus(row)["note"]


def route_check_title(
    source: ReviewSource,
    row: dict[str, Any],
    historical_refs: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    if source.id == "x_candidate_post":
        return "この判断で変わるもの"
    if source.id == "rare_signal_backcheck":
        return "裏どりで確認してほしいこと"
    if source.id == "youtube_active_video":
        return "追加先イベント確認"
    if source.id == "registered_event_investigation":
        if registered_auto_resolution(row, historical_refs):
            return "自動解決したこと"
        return "確認してほしいこと"
    return "採用後に残る情報"


def action_group_for(
    source: ReviewSource,
    row: dict[str, Any],
    historical_refs: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, str]:
    source_groups = {
        "predicted_occurrence_research": ("current_date", "予測日を公開判断に使えるか確認します。"),
        "predicted_occurrence_date_review": ("current_date", "予測日を採用するか確認します。"),
        "missing_source_url": ("source_url", "公開判断に使う根拠URLを確認します。"),
        "official_source": ("source_url", "公式/準公式URLとして使えるか確認します。"),
        "missing_occurrence_venue": ("venue", "開催回の会場を確認します。"),
        "accepted_venue_song_missing_venue": ("venue", "曲実績由来の会場候補を確認します。"),
        "historical_promotion_candidate": ("identity", "過去実績として同一イベントに昇格できるか確認します。"),
        "youtube_year_backfill_review": ("identity", "YouTube由来の年次開催回を既存系列へ統合できるか確認します。"),
        "youtube_active_video": ("youtube", "YouTube動画を既存イベントに使えるか確認します。"),
        "youtube_user_confirmation": ("youtube", "YouTube候補をメインDBに含めるか確認します。"),
        "x_candidate_post": ("social", "X/RSS由来のアカウントを今後の情報源にするか確認します。"),
        "daily_song_candidate": ("song_research", "日次X読解で見つかった曲候補を確認します。"),
        "daily_term_candidate": ("social", "日次X読解で見つかった用語・曲会場共起を確認します。"),
        "publication_gap": ("other", "採用済みデータと公開JSONの差分を確認します。"),
        "rare_signal_backcheck": ("source_url", "X由来のrare signalを非X根拠で確認できるか確認します。"),
    }
    if source.id == "historical_reference_quality":
        issues = get_path(row, "issue_codes") if isinstance(get_path(row, "issue_codes"), list) else []
        if "historical_date_missing" in issues or "historical_date_invalid" in issues:
            group_id = "historical_date"
            reason = "採用済み過去実績の日付・曜日に不足があります。"
        elif "historical_songs_missing" in issues:
            group_id = "song_research"
            reason = "採用済み過去実績に曲候補がありません。"
        else:
            group_id = "other"
            reason = "採用済み過去実績の品質確認です。"
    elif source.id == "registered_event_investigation":
        auto = registered_auto_resolution(row, historical_refs)
        if auto:
            group_id = "venue"
            reason = auto["reason"]
        else:
            focus = registered_review_focus(row)
            group_id = focus["id"]
            reason = focus["reason"]
    elif source.id == "review_inbox":
        kind = str(row.get("kind") or "")
        if kind in {"current_year_confirmation", "predicted_date", "date_research"}:
            group_id = "current_date"
            reason = "統合受信箱に入った今年の日付確認候補です。"
        elif kind in {"historical_reference", "historical_date"}:
            group_id = "historical_date"
            reason = "統合受信箱に入った過去実績確認候補です。"
        elif kind in {"venue", "venue_review"}:
            group_id = "venue"
            reason = "統合受信箱に入った会場確認候補です。"
        elif kind in {"source_url", "official_source", "rare_signal"}:
            group_id = "source_url"
            reason = "統合受信箱に入った根拠URL確認候補です。"
        elif kind in {"song", "song_research"}:
            group_id = "song_research"
            reason = "統合受信箱に入った曲候補確認です。"
        else:
            group_id = "other"
            reason = "統合受信箱に入ったレビュー対象です。"
    elif source.id in source_groups:
        group_id, reason = source_groups[source.id]
    else:
        group_id = "other"
        reason = "その他のレビュー対象です。"
    return {
        "id": group_id,
        "label": ACTION_GROUP_LABELS.get(group_id, group_id),
        "reason": reason,
    }


def item_key(source: ReviewSource, row: dict[str, Any], index: int) -> str:
    values = [first_text(row, (field_name,)) for field_name in source.key_fields]
    values = [value for value in values if value]
    if not values:
        values = [str(index)]
    joined = "|".join(values)
    joined = re.sub(r"\s+", " ", joined).strip()
    return joined[:240]


def recursive_urls(value: Any, out: list[str]) -> None:
    if len(out) >= 20:
        return
    if isinstance(value, str):
        if value.startswith(("http://", "https://")) and value not in out:
            out.append(value)
        return
    if isinstance(value, dict):
        for child in value.values():
            recursive_urls(child, out)
    elif isinstance(value, list):
        for child in value:
            recursive_urls(child, out)


def urls_for(source: ReviewSource, row: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for field_name in source.urls_fields:
        value = get_path(row, field_name)
        recursive_urls(value, urls)
    recursive_urls(row, urls)
    return urls[:12]


def scalar_details(row: dict[str, Any], limit: int = 18) -> list[dict[str, str]]:
    preferred = (
        "event_name",
        "venue",
        "event_year",
        "date_start",
        "date_end",
        "status",
        "priority_label",
        "priority_score",
        "recommended_action",
        "review_action",
        "action",
        "reason",
        "next_step",
        "source_url",
        "candidate_source_url",
        "confidence",
        "score",
        "memo",
    )
    details: list[dict[str, str]] = []
    seen: set[str] = set()
    for key in preferred:
        text = as_text(get_path(row, key))
        if text:
            details.append({"label": key, "value": text})
            seen.add(key)
    for key, value in row.items():
        if len(details) >= limit:
            break
        if key in seen:
            continue
        text = as_text(value)
        if text:
            details.append({"label": key, "value": text})
    return details[:limit]


def load_decisions(path: Path = DECISIONS_PATH) -> dict[str, Any]:
    payload = read_json(path, {"schema_version": 1, "decisions": {}})
    if not isinstance(payload, dict):
        return {"schema_version": 1, "decisions": {}}
    decisions = payload.get("decisions")
    if not isinstance(decisions, dict):
        payload["decisions"] = {}
    return payload


def decision_history_path(decisions_path: Path = DECISIONS_PATH, history_path: Path | None = None) -> Path:
    if history_path is not None:
        return history_path
    if decisions_path == DECISIONS_PATH:
        return HISTORY_PATH
    return decisions_path.with_name("decision_history.json")


def load_decision_history(path: Path = HISTORY_PATH) -> dict[str, Any]:
    payload = read_json(path, {"schema_version": 1, "history": []})
    if not isinstance(payload, dict):
        return {"schema_version": 1, "history": []}
    history = payload.get("history")
    if not isinstance(history, list):
        payload["history"] = []
    return payload


def source_by_id(source_id: str) -> ReviewSource | None:
    return next((source for source in SOURCES if source.id == source_id), None)


def strip_x_registration_fields(row: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(row)
    for key in (
        "registration_decision",
        "user_approved",
        "approved_by_user",
        "reviewed_by_user_at",
        "reviewed_by",
        "review_note",
    ):
        cleaned.pop(key, None)
    return cleaned


def update_x_candidate_source_decision(
    item_id: str,
    apply_value: str,
    note: str,
    reviewer: str,
    root: Path,
    clear: bool = False,
) -> dict[str, Any] | None:
    source_id, _, key = item_id.partition(":")
    if source_id != "x_candidate_post":
        return None
    source = source_by_id(source_id)
    if not source:
        return None
    path = root / source.path
    payload = read_json(path, {})
    rows = get_rows(payload, source.rows_path)
    if not isinstance(payload, dict) or not isinstance(rows, list):
        raise ValueError("X/RSS候補ファイルを更新できません。")

    row_index = None
    before = None
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        if item_key(source, row, index) == key:
            row_index = index - 1
            before = clone_json(row)
            break
    if row_index is None or before is None:
        raise ValueError("X/RSS候補の元データが見つかりません。")

    if clear:
        after = strip_x_registration_fields(before)
    else:
        if apply_value not in X_REGISTRATION_DECISIONS:
            raise ValueError("X/RSS候補では、情報源にする/様子を見る/対象外/後で見るのいずれかを選んでください。")
        after = dict(before)
        after["registration_decision"] = X_REGISTRATION_DECISIONS[apply_value]
        after["reviewed_by_user_at"] = now_iso()
        after["reviewed_by"] = reviewer.strip() or "内田さん"
        if note.strip():
            after["review_note"] = note.strip()
        else:
            after.pop("review_note", None)
        if apply_value == "promote":
            after["user_approved"] = True
            after["approved_by_user"] = True
        else:
            after["user_approved"] = False
            after["approved_by_user"] = False

    rows[row_index] = after
    payload["updated_at"] = now_iso()
    payload["updated_by"] = "review_console"
    write_json_atomic(path, payload)
    return {
        "source_id": source_id,
        "path": rel_path(path, root),
        "row_key": key,
        "before": before,
        "after": clone_json(after),
    }


def restore_source_update(source_update: dict[str, Any], root: Path) -> None:
    if not source_update or source_update.get("source_id") != "x_candidate_post":
        return
    source = source_by_id("x_candidate_post")
    if not source:
        return
    path = root / source.path
    payload = read_json(path, {})
    rows = get_rows(payload, source.rows_path)
    if not isinstance(payload, dict) or not isinstance(rows, list):
        return
    row_key = as_text(source_update.get("row_key"))
    before = source_update.get("before")
    if not row_key or not isinstance(before, dict):
        return
    for index, row in enumerate(rows, 1):
        if isinstance(row, dict) and item_key(source, row, index) == row_key:
            rows[index - 1] = before
            payload["updated_at"] = now_iso()
            payload["updated_by"] = "review_console_undo"
            write_json_atomic(path, payload)
            return


def clone_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def decision_snapshot(value: dict[str, Any] | None) -> dict[str, str]:
    if not value:
        return {}
    return {
        "decision": as_text(value.get("decision")),
        "note": as_text(value.get("note")),
        "apply_value": as_text(value.get("apply_value")),
    }


def append_decision_history(
    item_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    action: str,
    decisions_path: Path = DECISIONS_PATH,
    history_path: Path | None = None,
    source_update: dict[str, Any] | None = None,
) -> None:
    if decision_snapshot(before) == decision_snapshot(after) and not source_update:
        return
    path = decision_history_path(decisions_path, history_path)
    payload = load_decision_history(path)
    payload.setdefault("schema_version", 1)
    payload["updated_at"] = now_iso()
    history = payload.setdefault("history", [])
    entry = {
        "history_id": f"undo_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}",
        "item_id": item_id,
        "source_id": item_id.partition(":")[0],
        "action": action,
        "before": clone_json(before) if before else None,
        "after": clone_json(after) if after else None,
        "created_at": now_iso(),
        "created_by": "review_console",
    }
    if source_update:
        entry["source_update"] = clone_json(source_update)
    history.append(entry)
    payload["history"] = history[-100:]
    write_json_atomic(path, payload)


def undo_status(
    decisions_path: Path = DECISIONS_PATH,
    history_path: Path | None = None,
) -> dict[str, Any]:
    path = decision_history_path(decisions_path, history_path)
    payload = load_decision_history(path)
    history = payload.get("history", [])
    last = history[-1] if history else None
    return {
        "generated_at": now_iso(),
        "path": rel_path(path, effective_root(ROOT, decisions_path)),
        "undo_count": len(history),
        "last": last or {},
    }


def undo_last_decision(
    decisions_path: Path = DECISIONS_PATH,
    history_path: Path | None = None,
) -> dict[str, Any]:
    root = effective_root(ROOT, decisions_path)
    with decision_file_lock(decisions_path):
        path = decision_history_path(decisions_path, history_path)
        history_payload = load_decision_history(path)
        history = history_payload.get("history", [])
        if not history:
            raise ValueError("取り消せる操作がありません。")
        entry = history.pop()
        item_id = as_text(entry.get("item_id"))
        if not item_id:
            raise ValueError("履歴のitem_idが空です。")
        decisions_payload = load_decisions(decisions_path)
        decisions_payload.setdefault("schema_version", 1)
        decisions_payload["updated_at"] = now_iso()
        decisions = decisions_payload.setdefault("decisions", {})
        before = entry.get("before")
        if isinstance(before, dict) and before:
            decisions[item_id] = before
        else:
            decisions.pop(item_id, None)
        restore_source_update(entry.get("source_update") or {}, root)
        write_json_atomic(decisions_path, decisions_payload)
        clear_inventory_cache()
        history_payload["updated_at"] = now_iso()
        history_payload["history"] = history
        write_json_atomic(path, history_payload)
        return {
            "item_id": item_id,
            "undone": entry,
            "restored_decision": decisions.get(item_id, {}),
            "undo_count": len(history),
        }


def validate_decision(
    item_id: str,
    decision: str,
    apply_value: str,
    root: Path,
    decisions_path: Path,
    target_event_name: str = "",
) -> None:
    source_id, _, _key = item_id.partition(":")
    apply_value = apply_value.strip()
    if source_id == "registered_event_investigation" and decision == "accept" and not apply_value:
        raise ValueError("登録済みイベント調査では、適用値候補から反映ルートを選んでください。")
    if source_id == "registered_event_investigation" and apply_value == "confirm_current_date":
        detail = load_item(item_id, root=root, decisions_path=decisions_path)
        row = detail.get("raw", {}) if detail else {}
        if bool_value(row.get("missing_date")) or not current_year_date_values(row):
            raise ValueError("2026年日程がこの候補に無いため、日程確認済みにはできません。過去実績として採用、保留、要調査のいずれかを選んでください。")
    if source_id == "registered_event_investigation" and apply_value == "promote_historical_reference":
        detail = load_item(item_id, root=root, decisions_path=decisions_path)
        row = detail.get("raw", {}) if detail else {}
        if not historical_date_values(row):
            raise ValueError("過去実績の日付・曜日が無いため、過去実績として採用できません。保留または要調査にしてください。")
    if source_id == "youtube_active_video" and apply_value == "append_existing_event":
        detail = load_item(item_id, root=root, decisions_path=decisions_path)
        row = detail.get("raw", {}) if detail else {}
        if not youtube_target_event(row) and not as_text(target_event_name).strip():
            raise ValueError("追加先イベント名を入力してください。既存イベント名が分からない場合は、公式確認待ちまたは保留にしてください。")


def save_decision(
    item_id: str,
    decision: str,
    note: str = "",
    apply_value: str = "",
    target_event_name: str = "",
    target_song_names: str | list[str] = "",
    reviewer: str = "内田さん",
    decisions_path: Path = DECISIONS_PATH,
    root: Path = ROOT,
    history_path: Path | None = None,
) -> dict[str, Any]:
    root = effective_root(root, decisions_path)
    with decision_file_lock(decisions_path):
        payload = load_decisions(decisions_path)
        payload.setdefault("schema_version", 1)
        payload.setdefault("created_by", "review_console")
        payload["updated_at"] = now_iso()
        decisions = payload.setdefault("decisions", {})
        before = clone_json(decisions.get(item_id)) if decisions.get(item_id) else None
        if decision == "clear":
            source_update = update_x_candidate_source_decision(
                item_id,
                "",
                "",
                reviewer,
                root,
                clear=True,
            )
            decisions.pop(item_id, None)
            write_json_atomic(decisions_path, payload)
            clear_inventory_cache()
            append_decision_history(
                item_id,
                before,
                None,
                "clear",
                decisions_path=decisions_path,
                history_path=history_path,
                source_update=source_update,
            )
            return {"item_id": item_id, "cleared": True}
        if decision not in DECISION_LABELS:
            raise ValueError(f"unknown decision: {decision}")
        source_id, _, key = item_id.partition(":")
        validate_decision(item_id, decision, apply_value, root, decisions_path, target_event_name=target_event_name)
        apply_value = apply_value.strip()
        target_event_name = as_text(target_event_name).strip()
        manual_target_event_match: dict[str, Any] | None = None
        if source_id == "youtube_active_video" and apply_value == "append_existing_event" and target_event_name:
            detail = load_item(item_id, root=root, decisions_path=decisions_path)
            row = detail.get("raw", {}) if detail else {}
            target_event = youtube_target_event(row)
            if youtube_target_event_matches_name(target_event, target_event_name):
                manual_target_event_match = youtube_target_event_match_payload(target_event or {})
                target_event_name = as_text(manual_target_event_match.get("name"))
            else:
                resolved = resolve_existing_event_name(target_event_name, root)
                if resolved["status"] == "ok":
                    manual_target_event_match = resolved["match"]
                    target_event_name = as_text(manual_target_event_match.get("name"))
                elif resolved["status"] == "ambiguous":
                    suggestions = " / ".join(format_event_match(row) for row in resolved.get("matches", [])[:5])
                    raise ValueError(f"追加先イベントが複数見つかりました。もう少し正確に入力してください: {suggestions}")
                else:
                    raise ValueError(f"既存イベントが見つかりません: {target_event_name}")
        if isinstance(target_song_names, list):
            song_names = [as_text(value).strip() for value in target_song_names if as_text(value).strip()]
        else:
            song_names = [
                text.strip()
                for text in re.split(r"[,、\n]+", as_text(target_song_names))
                if text.strip()
            ]
        source_update = update_x_candidate_source_decision(
            item_id,
            apply_value,
            note,
            reviewer,
            root,
        )
        saved = {
            "item_id": item_id,
            "source_id": source_id,
            "item_key": key,
            "decision": decision,
            "decision_label": DECISION_LABELS[decision],
            "note": note.strip(),
            "apply_value": apply_value,
            "apply_value_label": apply_value_label(apply_value) if apply_value else "",
            "decision_route": decision_route(source_id, apply_value),
            "reviewer": reviewer.strip() or "内田さん",
            "updated_at": now_iso(),
            "updated_by": "review_console",
        }
        if source_id == "youtube_active_video" and apply_value == "append_existing_event" and target_event_name:
            saved["manual_target_event_name"] = target_event_name
        if source_id == "youtube_active_video" and apply_value == "append_existing_event" and manual_target_event_match:
            saved["manual_target_event_match"] = manual_target_event_match
        if source_id == "youtube_active_video" and song_names:
            saved["manual_song_names"] = list(dict.fromkeys(song_names))
        decisions[item_id] = saved
        write_json_atomic(decisions_path, payload)
        clear_inventory_cache()
        append_decision_history(
            item_id,
            before,
            saved,
            "save",
            decisions_path=decisions_path,
            history_path=history_path,
            source_update=source_update,
        )
        return decisions[item_id]


def action_text(source: ReviewSource, row: dict[str, Any]) -> str:
    return " ".join(
        text
        for text in (first_text(row, (field_name,)) for field_name in source.action_fields)
        if text
    ).casefold()


def has_final_source_decision(
    source: ReviewSource,
    row: dict[str, Any],
    historical_refs: dict[str, list[dict[str, Any]]] | None = None,
    root: Path = ROOT,
) -> bool:
    if auto_source_resolution(source, row, historical_refs):
        return True
    if source.id == "youtube_active_video" and youtube_auto_closed_parent_component(row, root=root):
        return True
    for field_name in source.final_decision_fields:
        value = get_path(row, field_name)
        if isinstance(value, dict) and value:
            return True
        if as_text(value):
            return True
    candidate_action = as_text(get_path(row, "candidate_action")).casefold()
    if candidate_action == "already_decided":
        return True
    current = as_text(get_path(row, "current_decision"))
    decided_by = as_text(get_path(row, "decided_by"))
    if current and decided_by:
        return True
    return False


def infer_status(
    source: ReviewSource,
    row: dict[str, Any],
    console_decision: dict[str, Any] | None,
    historical_refs: dict[str, list[dict[str, Any]]] | None = None,
    root: Path = ROOT,
) -> str:
    if console_decision:
        return "reviewed"
    if has_final_source_decision(source, row, historical_refs, root=root):
        return "closed"
    text = action_text(source, row)
    if any(word in text for word in CLOSED_WORDS):
        return "closed"
    if any(word in text for word in PENDING_WORDS):
        return "pending"
    return "pending" if source.pending_if_no_action else "closed"


def normalize_item(
    source: ReviewSource,
    row: dict[str, Any],
    index: int,
    decisions: dict[str, Any],
    include_raw: bool = False,
    historical_refs: dict[str, list[dict[str, Any]]] | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    key = item_key(source, row, index)
    item_id = f"{source.id}:{key}"
    console_decision = decisions.get(item_id)
    status = infer_status(source, row, console_decision, historical_refs, root=root)
    title = first_text(row, source.title_fields, default=f"{source.title} #{index}")
    subtitle = first_text(row, source.subtitle_fields)
    priority_label = first_text(row, source.priority_fields)
    score = first_text(row, source.score_fields)
    action = first_text(row, source.action_fields)
    source_decision = first_text(row, source.source_decision_fields)
    description = first_text(row, source.description_fields)
    action_group = action_group_for(source, row, historical_refs)
    auto_resolution = auto_source_resolution(source, row, historical_refs)
    advice = research_advice(source, row)
    item = {
        "id": item_id,
        "source_id": source.id,
        "source_title": source.title,
        "source_path": source.path,
        "domain": source.domain,
        "action_group": action_group["id"],
        "action_group_label": action_group["label"],
        "action_group_reason": action_group["reason"],
        "research_advice": advice,
        "research_advice_status": advice["status"],
        "research_advice_priority": advice["priority"],
        "auto_resolution": auto_resolution,
        "key": key,
        "title": title,
        "subtitle": subtitle,
        "priority_label": priority_label,
        "score": score,
        "action": action,
        "source_decision": source_decision,
        "description": description,
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "console_decision": console_decision or {},
        "urls": urls_for(source, row),
        "details": scalar_details(row),
        "option_values": list(source.option_values),
        "apply_options": apply_options(source, row),
        "route_note": route_note(source, row, historical_refs),
        "route_check_title": route_check_title(source, row, historical_refs),
        "route_checks": route_checks(source, row, historical_refs),
        "comparison": comparison_summary(source, row),
    }
    if source.id == "youtube_active_video":
        title_parts = split_youtube_title(title)
        target_event = youtube_target_event(row) or manual_youtube_target_event(
            as_text((console_decision or {}).get("manual_target_event_name"))
        )
        item["target_event"] = target_event
        item["song_candidates"] = youtube_song_candidates(row, root=root)
        title_event_candidate = as_text(row.get("title_event_name_candidate") or title_parts.get("title_event_name_candidate"))
        item["title_event_name_candidate"] = "" if youtube_parent_component(row) and not target_event else title_event_candidate
    if include_raw:
        item["raw"] = row
    return item


def source_generated_at(payload: Any) -> str:
    if isinstance(payload, dict):
        return as_text(payload.get("generated_at") or payload.get("updated_at"))
    return ""


def inventory_cache_stamp(root: Path, decisions_path: Path) -> tuple[tuple[str, int], ...]:
    paths = [decisions_path, root / "data" / "bon_odori_master.sqlite"]
    paths.extend(root / source.path for source in SOURCES)
    stamp: list[tuple[str, int]] = []
    for path in paths:
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = -1
        stamp.append((rel_path(path, root), mtime))
    return tuple(stamp)


def clear_inventory_cache() -> None:
    _INVENTORY_CACHE.clear()


def inventory_without_items(inventory: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in inventory.items() if key != "items"}


def priority_rank(item: dict[str, Any]) -> tuple[int, int, float, str]:
    status_rank = {"pending": 0, "reviewed": 1, "closed": 2}.get(item["status"], 3)
    label = item.get("priority_label") or ""
    label_rank = {"P0": 0, "high": 0, "P1": 1, "normal": 1, "P2": 2, "low": 2}.get(label, 3)
    score_text = item.get("score") or ""
    try:
        score = -float(score_text)
    except ValueError:
        score = 0.0
    return (status_rank, label_rank, score, item.get("title") or "")


def build_inventory(root: Path = ROOT, decisions_path: Path = DECISIONS_PATH) -> dict[str, Any]:
    decisions_payload = load_decisions(decisions_path)
    decisions = decisions_payload.get("decisions", {})
    historical_refs = load_historical_reference_index(root)
    items: list[dict[str, Any]] = []
    sources_summary: list[dict[str, Any]] = []
    for source in SOURCES:
        path = root / source.path
        payload = read_json(path, {})
        rows = get_rows(payload, source.rows_path)
        source_items = [
            normalize_item(
                source,
                row if isinstance(row, dict) else {"value": row},
                index,
                decisions,
                historical_refs=historical_refs,
                root=root,
            )
            for index, row in enumerate(rows, 1)
        ]
        source_items.sort(key=priority_rank)
        counts = {"pending": 0, "reviewed": 0, "closed": 0}
        for item in source_items:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        if source.include_when_empty or source_items:
            sources_summary.append(
                {
                    "id": source.id,
                    "title": source.title,
                    "path": source.path,
                    "domain": source.domain,
                    "rows_path": source.rows_path,
                    "generated_at": source_generated_at(payload),
                    "count": len(source_items),
                    "pending_count": counts.get("pending", 0),
                    "reviewed_count": counts.get("reviewed", 0),
                    "closed_count": counts.get("closed", 0),
                    "option_values": list(source.option_values),
                    "missing": not path.exists(),
                }
            )
        items.extend(source_items)
    items.sort(key=priority_rank)
    totals = {"pending": 0, "reviewed": 0, "closed": 0}
    domain_counts: dict[str, dict[str, int]] = {}
    action_group_counts: dict[str, dict[str, Any]] = {}
    for item in items:
        totals[item["status"]] = totals.get(item["status"], 0) + 1
        domain = item["domain"]
        domain_counts.setdefault(domain, {"pending": 0, "reviewed": 0, "closed": 0, "total": 0})
        domain_counts[domain][item["status"]] = domain_counts[domain].get(item["status"], 0) + 1
        domain_counts[domain]["total"] += 1
        group = item.get("action_group") or "other"
        group_label = item.get("action_group_label") or ACTION_GROUP_LABELS.get(group, group)
        action_group_counts.setdefault(
            group,
            {"label": group_label, "pending": 0, "reviewed": 0, "closed": 0, "total": 0},
        )
        action_group_counts[group][item["status"]] = action_group_counts[group].get(item["status"], 0) + 1
        action_group_counts[group]["total"] += 1
    return {
        "generated_at": now_iso(),
        "root": rel_path(root, root),
        "decisions_path": rel_path(decisions_path, root),
        "sources": sources_summary,
        "items": items,
        "totals": {
            "total": len(items),
            "pending": totals.get("pending", 0),
            "reviewed": totals.get("reviewed", 0),
            "closed": totals.get("closed", 0),
        },
        "domain_counts": domain_counts,
        "action_group_counts": action_group_counts,
    }


def load_inventory(
    root: Path = ROOT,
    decisions_path: Path = DECISIONS_PATH,
    include_items: bool = True,
) -> dict[str, Any]:
    root = effective_root(root, decisions_path)
    key = (str(root.resolve()), str(decisions_path.resolve()))
    stamp = inventory_cache_stamp(root, decisions_path)
    cached = _INVENTORY_CACHE.get(key)
    if not cached or cached.get("stamp") != stamp:
        cached = {"stamp": stamp, "inventory": build_inventory(root, decisions_path)}
        _INVENTORY_CACHE[key] = cached
    inventory = cached["inventory"]
    if include_items:
        return inventory
    return inventory_without_items(inventory)


def load_item(item_id: str, root: Path = ROOT, decisions_path: Path = DECISIONS_PATH) -> dict[str, Any] | None:
    decisions = load_decisions(decisions_path).get("decisions", {})
    historical_refs = load_historical_reference_index(root)
    source_id, _, key = item_id.partition(":")
    source = next((item for item in SOURCES if item.id == source_id), None)
    if not source:
        return None
    payload = read_json(root / source.path, {})
    for index, row in enumerate(get_rows(payload, source.rows_path), 1):
        row_obj = row if isinstance(row, dict) else {"value": row}
        if item_key(source, row_obj, index) == key:
            return normalize_item(
                source,
                row_obj,
                index,
                decisions,
                include_raw=True,
                historical_refs=historical_refs,
                root=root,
            )
    return None


def reviewed_items(root: Path = ROOT, decisions_path: Path = DECISIONS_PATH) -> list[dict[str, Any]]:
    inventory = load_inventory(root, decisions_path)
    return [item for item in inventory["items"] if item.get("console_decision")]


def build_export_payload(root: Path = ROOT, decisions_path: Path = DECISIONS_PATH) -> dict[str, Any]:
    by_source: dict[str, list[dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []
    for item in reviewed_items(root, decisions_path):
        if item.get("source_id") in DIRECT_SOURCE_DECISION_IDS:
            continue
        detail = load_item(item["id"], root, decisions_path) or item
        decision = detail.get("console_decision", {})
        row = {
            "item_id": detail["id"],
            "source_id": detail["source_id"],
            "source_title": detail["source_title"],
            "source_path": detail["source_path"],
            "domain": detail["domain"],
            "action_group": detail.get("action_group", ""),
            "action_group_label": detail.get("action_group_label", ""),
            "action_group_reason": detail.get("action_group_reason", ""),
            "item_key": detail["key"],
            "title": detail["title"],
            "decision": decision.get("decision"),
            "decision_label": decision.get("decision_label"),
            "note": decision.get("note", ""),
            "apply_value": decision.get("apply_value", ""),
            "apply_value_label": decision.get("apply_value_label", ""),
            "decision_route": decision.get("decision_route", ""),
            "manual_target_event_name": decision.get("manual_target_event_name", ""),
            "manual_song_names": decision.get("manual_song_names", []),
            "research_advice": detail.get("research_advice", {}),
            "research_advice_status": detail.get("research_advice_status", ""),
            "research_advice_priority": detail.get("research_advice_priority", ""),
            "route_checks": detail.get("route_checks", []),
            "reviewer": decision.get("reviewer", ""),
            "reviewed_at": decision.get("updated_at", ""),
            "urls": detail.get("urls", []),
            "raw": detail.get("raw", {}),
        }
        rows.append(row)
        by_source.setdefault(detail["source_id"], []).append(row)
    payload = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "generated_by": "review_console",
        "decision_count": len(rows),
        "rows": rows,
        "by_source_counts": {source_id: len(source_rows) for source_id, source_rows in by_source.items()},
    }
    return payload


def export_decisions(root: Path = ROOT, decisions_path: Path = DECISIONS_PATH, out_path: Path | None = None) -> dict[str, Any]:
    if out_path is None:
        out_path = root / "data" / "review_console" / "exported_decisions.json"
    payload = build_export_payload(root, decisions_path)
    write_json_atomic(out_path, payload)
    write_export_markdown(payload, EXPORT_MD_PATH if out_path == EXPORT_PATH else out_path.with_suffix(".md"))
    return payload


def write_export_markdown(payload: dict[str, Any], path: Path) -> None:
    lines = [
        "# レビューコンソール決定エクスポート",
        "",
        f"- generated_at: {payload.get('generated_at', '')}",
        f"- decision_count: {payload.get('decision_count', 0)}",
        "",
        "## By Source",
        "",
    ]
    counts = payload.get("by_source_counts", {})
    if counts:
        for source_id, count in sorted(counts.items()):
            lines.append(f"- {source_id}: {count}")
    else:
        lines.append("- なし")
    lines.extend(["", "## Decisions", ""])
    for row in payload.get("rows", []):
        note = row.get("note") or ""
        apply_label = row.get("apply_value_label") or row.get("apply_value") or ""
        lines.append(
            f"- [{row.get('decision_label')}] {row.get('source_title')} / "
            f"{row.get('title')} / {apply_label} / {note}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_inventory(root: Path = ROOT, decisions_path: Path = DECISIONS_PATH) -> dict[str, Any]:
    inventory = load_inventory(root, decisions_path)
    inventory_summary = {key: value for key, value in inventory.items() if key != "items"}
    write_json_atomic(INVENTORY_PATH, inventory_summary)
    lines = [
        "# レビューソース棚卸し",
        "",
        f"- generated_at: {inventory['generated_at']}",
        f"- total: {inventory['totals']['total']}",
        f"- pending: {inventory['totals']['pending']}",
        f"- reviewed: {inventory['totals']['reviewed']}",
        f"- closed: {inventory['totals']['closed']}",
        "",
        "## By Next Action",
        "",
        "| 次アクション | 件数 | 未レビュー | 決定済み | 処理済み |",
        "|---|---:|---:|---:|---:|",
    ]
    for _group_id, counts in sorted(
        inventory.get("action_group_counts", {}).items(),
        key=lambda item: (-int(item[1].get("pending", 0)), str(item[1].get("label") or item[0])),
    ):
        lines.append(
            f"| {counts.get('label', _group_id)} | {counts.get('total', 0)} | "
            f"{counts.get('pending', 0)} | {counts.get('reviewed', 0)} | "
            f"{counts.get('closed', 0)} |"
        )
    lines.extend(
        [
            "",
            "## By Source",
            "",
            "| ソース | 種類 | 件数 | 未レビュー | 決定済み | 処理済み | ファイル |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for source in inventory["sources"]:
        lines.append(
            f"| {source['title']} | {source['domain']} | {source['count']} | "
            f"{source['pending_count']} | {source['reviewed_count']} | "
            f"{source['closed_count']} | `{source['path']}` |"
        )
    INVENTORY_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    INVENTORY_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return inventory


def stage_apply(root: Path = ROOT, decisions_path: Path = DECISIONS_PATH, write: bool = False) -> dict[str, Any]:
    export = export_decisions(root, decisions_path) if write else build_export_payload(root, decisions_path)
    inbox_stage = build_decision_stage(export)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in export["rows"]:
        if row["source_id"] == "review_inbox":
            continue
        grouped.setdefault(row["source_id"], []).append(row)
    staged_dir = root / "data" / "review_console" / "staged"
    if write:
        staged_dir.mkdir(parents=True, exist_ok=True)
        for old_path in staged_dir.glob("*_decisions.json"):
            old_path.unlink()
        updates_path = staged_dir / UPDATES_FILE
        if updates_path.exists():
            updates_path.unlink()
        ack_path = staged_dir / "stage_apply_ack.json"
        if ack_path.exists():
            ack_path.unlink()
    staged_files = []
    for source_id, rows in sorted(grouped.items()):
        source = next((item for item in SOURCES if item.id == source_id), None)
        payload = {
            "schema_version": 1,
            "generated_at": now_iso(),
            "generated_by": "apply_review_console_decisions.py",
            "source_id": source_id,
            "source_path": source.path if source else "",
            "write_mode": "staged_only",
            "decision_count": len(rows),
            "rows": rows,
        }
        path = staged_dir / f"{source_id}_decisions.json"
        if write:
            write_json_atomic(path, payload)
        staged_files.append({"source_id": source_id, "path": rel_path(path, root), "decision_count": len(rows)})
    if inbox_stage["decision_count"]:
        if write:
            inbox_files = write_decision_stage(inbox_stage, staged_dir)
            for item in inbox_files:
                item["path"] = rel_path(Path(item["path"]), root)
        else:
            inbox_files = [
                {
                    "source_id": f"review_inbox:{route}",
                    "path": rel_path(staged_dir / f"review_inbox_{route}_decisions.json", root),
                    "decision_count": count,
                    "decision_route": route,
                }
                for route, count in inbox_stage["route_counts"].items()
                if count
            ]
        staged_files.extend(inbox_files)
    result = {
        "generated_at": now_iso(),
        "write": write,
        "decision_count": export["decision_count"],
        "review_inbox_decision_count": inbox_stage["decision_count"],
        "staged_files": staged_files,
        "note": "staged_only: operational RDB/Notion/public JSON were not modified",
    }
    if write:
        write_json_atomic(staged_dir / "stage_apply_result.json", result)
    return result


def stage_status(root: Path = ROOT, decisions_path: Path = DECISIONS_PATH) -> dict[str, Any]:
    staged_dir = root / "data" / "review_console" / "staged"
    result_path = staged_dir / "stage_apply_result.json"
    ack_path = staged_dir / "stage_apply_ack.json"
    result = read_json(result_path, {})
    ack = read_json(ack_path, {})
    staged_files: list[dict[str, Any]] = []
    if staged_dir.exists():
        for path in sorted(staged_dir.glob("*_decisions.json")):
            payload = read_json(path, {})
            staged_files.append(
                {
                    "source_id": as_text(payload.get("source_id")) or path.name.removesuffix("_decisions.json"),
                    "path": rel_path(path, root),
                    "decision_count": int(payload.get("decision_count") or 0),
                    "generated_at": as_text(payload.get("generated_at")),
                }
            )
    decision_count = sum(item["decision_count"] for item in staged_files)
    result_count = int(result.get("decision_count") or 0) if isinstance(result, dict) else 0
    if result_count and not decision_count:
        decision_count = result_count
    generated_at = as_text(result.get("generated_at")) if isinstance(result, dict) else ""
    decisions_payload = load_decisions(decisions_path)
    decisions_updated_at = as_text(decisions_payload.get("updated_at"))
    stage_dt = parse_iso(generated_at)
    decisions_dt = parse_iso(decisions_updated_at)
    is_outdated = bool(stage_dt and decisions_dt and decisions_dt > stage_dt)
    has_staged_decisions = decision_count > 0
    ack_stage_generated_at = as_text(ack.get("stage_generated_at")) if isinstance(ack, dict) else ""
    is_acknowledged = bool(
        has_staged_decisions
        and generated_at
        and ack_stage_generated_at == generated_at
        and not is_outdated
    )
    if not has_staged_decisions:
        status = "empty"
        label = "準備なし"
        message = "反映準備ファイルはありません。"
    elif is_outdated:
        status = "outdated"
        label = "反映準備が古い可能性"
        message = "反映準備後にレビュー判断が更新されています。個別apply前にもう一度、反映準備ファイルを作ってください。"
    elif is_acknowledged:
        status = "acknowledged"
        label = "個別反映済み"
        message = "この反映準備は個別apply済みとして記録されています。"
    else:
        status = "pending_external_apply"
        label = "反映準備あり"
        message = "反映準備ファイルがあります。個別applyをdry-runしてから明示実行してください。"
    needs_attention = has_staged_decisions and (is_outdated or not is_acknowledged)
    return {
        "generated_at": generated_at,
        "decisions_updated_at": decisions_updated_at,
        "status": status,
        "label": label,
        "message": message,
        "has_staged_decisions": has_staged_decisions,
        "is_acknowledged": is_acknowledged,
        "acknowledged_at": as_text(ack.get("acknowledged_at")) if isinstance(ack, dict) else "",
        "acknowledged_by": as_text(ack.get("acknowledged_by")) if isinstance(ack, dict) else "",
        "needs_attention": needs_attention,
        "is_outdated": is_outdated,
        "decision_count": decision_count,
        "staged_file_count": len(staged_files),
        "staged_files": staged_files,
        "result_path": rel_path(result_path, root),
        "ack_path": rel_path(ack_path, root),
        "note": "This is a reminder only. The review console does not run domain-specific apply scripts.",
    }


def acknowledge_stage(
    root: Path = ROOT,
    decisions_path: Path = DECISIONS_PATH,
    acknowledged_by: str = "内田さん",
) -> dict[str, Any]:
    status = stage_status(root, decisions_path)
    if not status["has_staged_decisions"]:
        raise ValueError("no staged decisions to acknowledge")
    if status["is_outdated"]:
        raise ValueError("staged decisions are outdated; restage before acknowledging")
    payload = {
        "schema_version": 1,
        "acknowledged_at": now_iso(),
        "acknowledged_by": acknowledged_by.strip() or "内田さん",
        "stage_generated_at": status["generated_at"],
        "decision_count": status["decision_count"],
        "staged_file_count": status["staged_file_count"],
        "staged_files": status["staged_files"],
        "note": "Acknowledges that a domain-specific apply was handled outside the review console.",
    }
    write_json_atomic(root / "data" / "review_console" / "staged" / "stage_apply_ack.json", payload)
    return payload


def int_metric(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def attention_item(
    level: str,
    title: str,
    value: Any = 0,
    message: str = "",
    target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "level": level,
        "title": title,
        "value": value,
        "message": message,
        "target": target or {},
    }


OPS_TREND_METRICS = [
    {
        "key": "youtube_candidates_total",
        "label": "YouTube候補",
        "group": "YouTube",
        "kind": "more_can_be_work",
    },
    {
        "key": "youtube_candidates_strong",
        "label": "strong",
        "group": "YouTube",
        "kind": "more_can_be_good",
    },
    {
        "key": "youtube_candidates_review",
        "label": "review",
        "group": "YouTube",
        "kind": "more_needs_review",
    },
    {
        "key": "youtube_candidates_weak",
        "label": "weak",
        "group": "YouTube",
        "kind": "more_can_be_noise",
    },
    {
        "key": "youtube_run_remaining_after",
        "label": "今回対象の残り",
        "group": "収集",
        "kind": "less_is_good",
    },
    {
        "key": "low_confidence_review_unreviewed_rows",
        "label": "低信頼未判断",
        "group": "レビュー",
        "kind": "less_is_good",
    },
    {
        "key": "registered_events_incomplete",
        "label": "登録済み不完全",
        "group": "正本整備",
        "kind": "less_is_good",
    },
    {
        "key": "missing_venue_occurrences",
        "label": "missing venue",
        "group": "正本整備",
        "kind": "less_is_good",
    },
    {
        "key": "missing_source_url_occurrences",
        "label": "missing source URL",
        "group": "正本整備",
        "kind": "less_is_good",
    },
    {
        "key": "missing_date_start_count",
        "label": "missing date_start",
        "group": "正本整備",
        "kind": "less_is_good",
    },
    {
        "key": "public_date_prediction_applied",
        "label": "日付予測",
        "group": "公開補助",
        "kind": "watch",
    },
    {
        "key": "public_historical_reference_applied",
        "label": "過去実績表示",
        "group": "公開補助",
        "kind": "watch",
    },
    {
        "key": "public_season_hint_applied",
        "label": "季節ヒント",
        "group": "公開補助",
        "kind": "watch",
    },
]


def metric_delta(current: dict[str, Any], previous: dict[str, Any] | None, key: str) -> int | None:
    if not previous:
        return None
    return int_metric(current.get(key)) - int_metric(previous.get(key))


def build_admin_attention(review: dict[str, Any], stage: dict[str, Any], ops: dict[str, Any]) -> list[dict[str, Any]]:
    attention: list[dict[str, Any]] = []
    if stage.get("needs_attention"):
        attention.append(
            attention_item(
                "danger",
                stage.get("label") or "ステージ確認が必要です",
                int_metric(stage.get("decision_count")),
                stage.get("message") or "",
                {"view": "review", "status": "reviewed"},
            )
        )
    pending = int_metric(review.get("pending"))
    if pending > 0:
        attention.append(
            attention_item(
                "warn",
                "未レビューがあります",
                pending,
                "レビュー判断がまだ保存されていない候補があります。",
                {"view": "review", "status": "pending"},
            )
        )
    missing_source = int_metric(ops.get("missing_source_url_occurrences"))
    if missing_source > 0:
        attention.append(
            attention_item(
                "warn",
                "根拠URL不足があります",
                missing_source,
                "公開判断の根拠リンクを確認する対象があります。",
                {"view": "review", "source": "missing_source_url", "status": "pending"},
            )
        )
    missing_venue = int_metric(ops.get("missing_venue_occurrences"))
    if missing_venue > 0:
        attention.append(
            attention_item(
                "warn",
                "会場不足レビューがあります",
                missing_venue,
                "開催回に会場を紐づける確認対象があります。",
                {"view": "review", "source": "missing_occurrence_venue", "status": "pending"},
            )
        )
    missing_date_start = int_metric(ops.get("missing_date_start_count"))
    if missing_date_start > 0:
        attention.append(
            attention_item(
                "info",
                "開始日未整備の開催回があります",
                missing_date_start,
                "登録済みイベント調査や日付確認の優先度を見る対象です。",
                {"view": "review", "source": "registered_event_investigation", "status": "pending"},
            )
        )
    undecided_youtube = int_metric(ops.get("youtube_review_queue_undecided_groups"))
    if undecided_youtube > 0:
        attention.append(
            attention_item(
                "warn",
                "YouTube年次バックフィルに未判断があります",
                undecided_youtube,
                "過去年動画からの候補グループに人手判断が必要です。",
                {"view": "review", "source": "youtube_year_backfill_review", "status": "pending"},
            )
        )
    youtube_status = as_text(ops.get("youtube_run_status"))
    if youtube_status in {"quota_limited", "harvested_until_quota_limited"}:
        attention.append(
            attention_item(
                "info",
                "YouTube収集はquota条件で停止しました",
                youtube_status,
                "quota停止は通常の停止条件です。残数と候補品質を確認してください。",
                {"view": "metrics"},
            )
        )
    return attention


def load_admin_summary(root: Path = ROOT, decisions_path: Path = DECISIONS_PATH) -> dict[str, Any]:
    inventory = load_inventory(root, decisions_path, include_items=False)
    totals = inventory.get("totals", {})
    review = {
        "total": int_metric(totals.get("total")),
        "pending": int_metric(totals.get("pending")),
        "reviewed": int_metric(totals.get("reviewed")),
        "closed": int_metric(totals.get("closed")),
        "domains": inventory.get("domain_counts", {}),
        "sources": inventory.get("sources", []),
        "decisions_path": inventory.get("decisions_path", ""),
    }
    stage = stage_status(root, decisions_path)
    ops = collect_ops_metrics.collect_metrics(data_dir=root / "data")
    return {
        "schema_version": 1,
        "generated_at": now_iso(),
        "root": rel_path(root, root),
        "review": review,
        "stage": stage,
        "ops": ops,
        "attention": build_admin_attention(review, stage, ops),
    }


def load_ops_metrics(root: Path = ROOT, history_limit: int = 30) -> dict[str, Any]:
    data_dir = root / "data"
    current = collect_ops_metrics.collect_metrics(data_dir=data_dir)
    history_path = data_dir / "ops_metrics_history.jsonl"
    history = collect_ops_metrics.read_jsonl(history_path)
    rows = collect_ops_metrics.merge_history(history, current, replace_same_date=True)
    previous = collect_ops_metrics.previous_row(rows, current)
    limited_rows = rows[-history_limit:] if history_limit > 0 else rows
    deltas = {
        item["key"]: metric_delta(current, previous, item["key"])
        for item in OPS_TREND_METRICS
    }
    return {
        "schema_version": 1,
        "generated_at": now_iso(),
        "history_path": rel_path(history_path, root),
        "current": current,
        "previous": previous or {},
        "deltas": deltas,
        "history": limited_rows,
        "trend_metrics": OPS_TREND_METRICS,
        "note": "Read-only snapshot for the admin console. This endpoint does not write history files.",
    }


def file_summary(root: Path, relative_path: str, rows_path: str = "") -> dict[str, Any]:
    path = root / relative_path
    summary: dict[str, Any] = {
        "path": relative_path,
        "exists": path.exists(),
        "modified_at": "",
        "generated_at": "",
        "count": 0,
    }
    if not path.exists():
        return summary
    try:
        summary["modified_at"] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        pass
    payload = read_json(path, {})
    if isinstance(payload, dict):
        summary["generated_at"] = as_text(payload.get("generated_at"))
        if rows_path:
            summary["count"] = len(get_rows(payload, rows_path))
        elif isinstance(payload.get("rows"), list):
            summary["count"] = len(payload["rows"])
        elif isinstance(payload.get("items"), list):
            summary["count"] = len(payload["items"])
        elif isinstance(payload.get("candidates"), list):
            summary["count"] = len(payload["candidates"])
        elif isinstance(payload.get("results"), list):
            summary["count"] = len(payload["results"])
    elif isinstance(payload, list):
        summary["count"] = len(payload)
    return summary


def source_status(inventory: dict[str, Any], source_id: str) -> dict[str, Any]:
    for source in inventory.get("sources") or []:
        if source.get("id") == source_id:
            return {
                "id": source_id,
                "title": source.get("title") or source_id,
                "pending": int_metric(source.get("pending_count")),
                "reviewed": int_metric(source.get("reviewed_count")),
                "closed": int_metric(source.get("closed_count")),
                "total": int_metric(source.get("count")),
                "target": {"view": "review", "source": source_id, "status": "pending"},
            }
    return {
        "id": source_id,
        "title": source_id,
        "pending": 0,
        "reviewed": 0,
        "closed": 0,
        "total": 0,
        "target": {"view": "review", "source": source_id, "status": "pending"},
    }


def operation_status(root: Path, op_id: str, label: str, command: list[str], note: str) -> dict[str, Any]:
    return {
        "id": op_id,
        "label": label,
        "command": " ".join(command),
        "note": note,
    }


LOCAL_OPERATIONS: dict[str, dict[str, Any]] = {
    "youtube_dry_run": {
        "label": "YouTube dry-run",
        "command": [
            "python3",
            "run_daily_youtube_backfill.py",
            "--month",
            "6",
            "--auto-next-month",
            "--focus-month",
            "6",
            "--focus-month",
            "7",
            "--limit",
            "1",
            "--max-results",
            "5",
            "--retry-selected",
            "--until-quota-limited",
            "--max-batches",
            "1",
            "--mail-reminder",
            "--dry-run",
        ],
        "note": "API quotaを使わず、次に選ばれるYouTube対象だけ確認します。",
    },
    "post_batch_maintenance": {
        "label": "保守レポート再生成",
        "command": ["python3", "run_post_batch_maintenance.py"],
        "note": "既存データを読み、post-batch maintenance reportを再生成します。",
    },
    "x_digest": {
        "label": "X digest再生成",
        "command": ["python3", "build_x_news_digest_for_oto.py"],
        "note": "既取得X/RSSデータだけを読み、おと向け読解リストを再生成します。",
    },
    "rare_signal_queue": {
        "label": "rare signal裏どりキュー再生成",
        "command": ["python3", "build_rare_signal_backcheck_queue.py"],
        "note": "おと解釈済み候補から、非X裏どり待ちキューを作り直します。",
    },
    "ops_metrics": {
        "label": "運用メトリクス保存",
        "command": ["python3", "collect_ops_metrics.py"],
        "note": "現在の運用メトリクスをhistory/latest/dashboardへ保存します。",
    },
}


def load_collection_status(root: Path = ROOT, decisions_path: Path = DECISIONS_PATH) -> dict[str, Any]:
    inventory = load_inventory(root, decisions_path, include_items=False)
    ops = collect_ops_metrics.collect_metrics(data_dir=root / "data")
    youtube_report = file_summary(root, "data/youtube_daily_backfill_report.json")
    youtube_candidates = file_summary(root, "data/youtube_year_backfill_candidates.json", "candidates")
    youtube_review_queue = file_summary(root, "data/youtube_year_backfill_review_queue.json", "groups")
    youtube_active = file_summary(root, "data/youtube_active_video_review.json", "rows")

    voices = file_summary(root, "data/voices.json")
    x_digest = file_summary(root, "data/x_news_digest_for_oto.json", "candidates")
    x_reviews = file_summary(root, "data/x_news_digest_oto_reviews.json", "reviews")
    rare_candidates = file_summary(root, "data/rare_signal_candidates.json", "candidates")
    rare_queue = file_summary(root, "data/rare_signal_backcheck_queue.json", "queue")
    weekly_song = file_summary(root, "data/weekly_song_candidates_review.json", "rows")
    weekly_terms = file_summary(root, "data/weekly_harvest_review_candidates.json", "rows")
    x_candidate_post = file_summary(root, "data/x_candidate_post_review.json", "results")

    youtube_sources = [
        source_status(inventory, "youtube_active_video"),
        source_status(inventory, "youtube_year_backfill_review"),
        source_status(inventory, "youtube_user_confirmation"),
    ]
    x_sources = [
        source_status(inventory, "daily_song_candidate"),
        source_status(inventory, "daily_term_candidate"),
        source_status(inventory, "rare_signal_backcheck"),
        source_status(inventory, "x_candidate_post"),
    ]

    return {
        "schema_version": 1,
        "generated_at": now_iso(),
        "links": {
            "youtube_pr": "https://github.com/uryoutamomo/bon-odori-collector/pull/3",
            "youtube_workflow": "https://github.com/uryoutamomo/bon-odori-collector/actions/workflows/youtube_daily_backfill.yml",
            "collect_workflow": "https://github.com/uryoutamomo/bon-odori-collector/actions/workflows/collect.yml",
            "review_x_workflow": "https://github.com/uryoutamomo/bon-odori-collector/actions/workflows/review_x_candidate_posts.yml",
            "discover_x_workflow": "https://github.com/uryoutamomo/bon-odori-collector/actions/workflows/discover_x_social_graph.yml",
        },
        "lanes": [
            {
                "id": "youtube",
                "title": "YouTube",
                "status": as_text(ops.get("youtube_run_status")) or "unknown",
                "summary": [
                    {"label": "最新実行", "value": youtube_report.get("generated_at") or youtube_report.get("modified_at")},
                    {"label": "選択", "value": ops.get("youtube_run_selected_rows")},
                    {"label": "完了バッチ", "value": ops.get("youtube_run_completed_batches")},
                    {"label": "残り", "value": ops.get("youtube_run_remaining_after")},
                    {"label": "候補", "value": ops.get("youtube_candidates_total")},
                    {"label": "review", "value": ops.get("youtube_candidates_review")},
                ],
                "files": [youtube_report, youtube_candidates, youtube_review_queue, youtube_active],
                "sources": youtube_sources,
                "operations": [
                    operation_status(root, "youtube_dry_run", "次回対象をdry-run", LOCAL_OPERATIONS["youtube_dry_run"]["command"], LOCAL_OPERATIONS["youtube_dry_run"]["note"]),
                    operation_status(root, "post_batch_maintenance", "保守レポート再生成", LOCAL_OPERATIONS["post_batch_maintenance"]["command"], LOCAL_OPERATIONS["post_batch_maintenance"]["note"]),
                    operation_status(root, "ops_metrics", "メトリクス保存", LOCAL_OPERATIONS["ops_metrics"]["command"], LOCAL_OPERATIONS["ops_metrics"]["note"]),
                ],
            },
            {
                "id": "x",
                "title": "X / RSS",
                "status": "collect.yml",
                "summary": [
                    {"label": "voices", "value": voices.get("count")},
                    {"label": "digest", "value": x_digest.get("count")},
                    {"label": "おと読解", "value": x_reviews.get("count")},
                    {"label": "rare signal", "value": rare_candidates.get("count")},
                    {"label": "裏どり待ち", "value": rare_queue.get("count")},
                    {"label": "曲/用語レビュー", "value": weekly_song.get("count") + weekly_terms.get("count")},
                ],
                "files": [voices, x_digest, x_reviews, rare_candidates, rare_queue, weekly_song, weekly_terms, x_candidate_post],
                "sources": x_sources,
                "operations": [
                    operation_status(root, "x_digest", "X digest再生成", LOCAL_OPERATIONS["x_digest"]["command"], LOCAL_OPERATIONS["x_digest"]["note"]),
                    operation_status(root, "rare_signal_queue", "rare signalキュー再生成", LOCAL_OPERATIONS["rare_signal_queue"]["command"], LOCAL_OPERATIONS["rare_signal_queue"]["note"]),
                    operation_status(root, "ops_metrics", "メトリクス保存", LOCAL_OPERATIONS["ops_metrics"]["command"], LOCAL_OPERATIONS["ops_metrics"]["note"]),
                ],
            },
        ],
    }


def run_console_operation(operation_id: str, root: Path = ROOT) -> dict[str, Any]:
    operation = LOCAL_OPERATIONS.get(operation_id)
    if not operation:
        raise ValueError(f"unknown operation: {operation_id}")
    result = subprocess.run(
        operation["command"],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=180,
    )
    return {
        "operation_id": operation_id,
        "label": operation["label"],
        "command": " ".join(operation["command"]),
        "returncode": result.returncode,
        "stdout": result.stdout[-8000:],
        "stderr": result.stderr[-8000:],
        "ok": result.returncode == 0,
    }
