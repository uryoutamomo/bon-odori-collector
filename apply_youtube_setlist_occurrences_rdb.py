"""Ingest data/youtube_setlist_occurrences.json into the master RDB as observed evidence.

This is the "new direct path" chosen over reviving the frozen legacy
build_song_occurrences.py pipeline (see data/master_rdb_migration_freeze.json,
group legacy_song_occurrence_generation, still active). It writes new
observed_occurrences / observed_occurrence_songs / evidence_items /
occurrence_song_evidence_links rows sourced from cleaned YouTube setlist data
(see commit 5944839 fixing extract_youtube_setlists.py's input-bloat bugs).

Deliberately does NOT populate probability itself: song_processing/song_occurrences.py's
prediction_probability()/evidence_view_for_year() are not RDB-native, so this script only
raises real observed-setlist evidence into the RDB. calibrate_song_probabilities_rdb.py
(2026-07-24 follow-up) computes probability from what lands here on a separate pass; it
must not fabricate a probability value itself.

Every setlist item's title goes through a song-title quality gate (resolve_song(), see
its docstring) before being written to occurrence_songs: matched against the curated
songs master after noise stripping, registered as a new songs.status='候補' row if
it looks like a plausible but previously unseen song name, or left out of
occurrence_songs entirely (staying visible only in observed_occurrence_songs.raw_song_title)
if it doesn't. This exists because extract_youtube_setlists.py's per-video title parsing
sometimes yields non-song fragments (event names, sponsor annotations, bare "第70回") or
bakes a venue name into every song from that venue (see extract_youtube_setlists.py's
2026-07-24 花園神社/下町盆踊りフェス venue-detection fix for a case that produced it).

Default mode writes only to a copied SQLite DB. Production writes require
--apply and the confirmation phrase.
"""

import argparse
import json
import re
import shutil
import sqlite3
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import audit_master_rdb
from rdb_builders.build_master_rdb import quality_flags
from master_rdb.master_db import (
    MASTER_DB,
    connect_existing,
    json_text,
    normalize_text,
    now_utc,
    refresh_manifest_database_state,
    stable_id,
    table_counts,
)
from report_apply.event_report_helpers import find_occurrence_candidates


DATA = Path("data")
SOURCE = DATA / "youtube_setlist_occurrences.json"
OUT_DB = DATA / "youtube_setlist_occurrences_apply_dry_run.sqlite"
OUT_JSON = DATA / "youtube_setlist_occurrences_apply_report.json"
OUT_MD = DATA / "youtube_setlist_occurrences_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM_PHRASE = "APPLY YOUTUBE SETLIST OCCURRENCES RDB"
SCRIPT_NAME = "apply_youtube_setlist_occurrences_rdb.py"

# Chosen from a manual spot-check of find_occurrence_candidates() scores against this
# dataset (2026-07-24): every match >=0.7 sampled was correct; 0.6-0.7 contained a real
# false positive (飛鳥山公園盆踊り会 -> 鳥山町町内会 at 0.631, wrong venue) alongside
# several correct-but-noisy matches. Missing a match is safe (row stays unmatched and is
# still stored as raw evidence); a wrong match is not, so this errs toward precision.
MATCH_SCORE_THRESHOLD = 0.7
RELIABILITY_BY_CONFIDENCE = {"high": 0.95, "medium": 0.80, "low": 0.55}

# Manual overrides for occurrences that scored 0.6-0.7 (below MATCH_SCORE_THRESHOLD) in a
# 2026-07-24 spot-check but were individually verified correct -- unlike the false positive
# in that band noted above (飛鳥山公園盆踊り会 -> 鳥山町町内会), each of these has the target
# venue's name spelled out directly in the raw event name (e.g. "神田明神アニソン盆踊り" names
# 神田明神 itself), or was confirmed against the event's own listing page (神楽坂夏まつり,
# 新橋こいち祭). Generic names with no venue signal in this same score band (bare "盆踊り",
# "Bon Dance", "🇯🇵 アニソン盆踊り") were deliberately left out -- low score AND no identifying
# text is not enough evidence, per this script's precision-over-recall policy.
MANUAL_MATCH_OVERRIDES = {
    "27fbabb50bb4686e": "occ_8e0883279b40b8d5",  # 青山善光寺盆踊り -> 青山善光寺
    "e08bf844d75187f8": "occ_e3b28f80971f144f",  # 神田明神納涼盆踊り -> 神田明神境内
    "6b5a1e3b6ff379b8": "occ_1a303dadd13493de",  # 住友ビル三角広場盆踊り -> 新宿住友ビル三角広場
    "8328af495806e0c4": "occ_e3b28f80971f144f",  # 神田明神アニソン盆踊り -> 神田明神境内
    "c26c985165101664": "occ_5d45c1530c27585f",  # GMOシブヤエンタメ祭 -> 宮下公園
    "00b59e1aaaf4d301": "occ_56d48c1deeded4ab",  # 郡上おどり in 青山(最終日) -> 秩父宮ラグビー場駐車場
    "ab1e6c8b8b8a12da": "occ_56d48c1deeded4ab",  # 郡上おどりin青山1日目 -> 秩父宮ラグビー場駐車場
    "16b010c1c8a53cc4": "occ_eb5984603eeb0f18",  # 鴨台盆踊り(2025) -> 大正大学
    "eafab5ecc7b3c7c5": "occ_54ba9f31ac0f3844",  # 自由が丘納涼盆踊り -> 自由が丘駅前ロータリー特設会場
    "e55e46fe4a7f01d2": "occ_54ba9f31ac0f3844",  # 自由が丘納涼盆踊り -> 同上
    "e7e3dbe98b0fbb15": "occ_bc8483c70338a8e1",  # 神楽坂まつり盆踊り -> りそな銀行神楽坂支店前（tokyofesta.com/23ku/31347/で確認）
    "a3a3d01cb7d70444": "occ_85b5772373d4e5df",  # 新橋こいち祭(盆踊り) -> 桜田公園（summer.walkerplus.com等で確認）
    "e81a973a438f23ba": "occ_4788691d8f385e40",  # 大銀座盆踊り -> 中央通り（銀座1丁目〜8丁目）
    "d4912039e5a8f6d6": "occ_e3b28f80971f144f",  # 神田明神納涼祭り2025アニソン盆踊り -> 神田明神境内
    "3ea563d2dc5087c9": "occ_c2b890eb32b32469",  # 東本願寺盆踊り2025第二部 -> 東本願寺（浅草）
    "b925071dc7b07871": "occ_f50ea02c13ee9d07",  # 六本木ヒルズ盆踊り2025(DAY1) -> 六本木ヒルズアリーナ
    "c0ae3b6f30fe2789": "occ_f50ea02c13ee9d07",  # 六本木ヒルズ盆踊り2025(DAY2) -> 同上
    "6373c67bc69269c6": "occ_f50ea02c13ee9d07",  # 六本木ヒルズ盆踊り2025(DAY2) -> 同上
    "85b48ad9ca88a07c": "occ_090e320504061682",  # 【にっぽり炭坑節まつり】 -> JR日暮里駅前広場
    "76f7438bd0d1ffb7": "occ_e3afc61ae62aa5f3",  # ビールと浴衣de盆踊り -> 上野恩賜公園（public_sync_exact_approvals.jsonの既承認名と同一venue）
    "cc9f00c24644bca1": "occ_63ae1b3a246f34f0",  # 鴨台盆踊り(2026) -> 大正大学（2026-07-24に本スクリプトの外でRDB追加した新occurrence）
    "357fb1eef78e0f45": "occ_5d45c1530c27585f",  # GMOシブヤエンタメ祭 盆踊り -> 宮下公園
}

# --- Song title quality gate (2026-07-24 follow-up) ---------------------------------
#
# extract_youtube_setlists.py's setlist items are per-video title parses, not always
# clean song names -- some are annotation-laden fragments like "Hey Mr 恵比寿(地元企業:
# サッポロ)第70回" or bare noise like "第70回" / "25】". The extractor's own
# title_looks_like_song()/clean_song_from_title() are built to split a *whole video
# title* into event+song, not to re-validate an already-extracted title, so they don't
# catch these. This gate runs on the already-extracted setlist item title instead:
#   1. strip known noise (回数 suffix, operator/sponsor annotations, a leading venue-name
#      suffix such as "新宿 花園神社" tacked onto every song from that venue's videos)
#   2. try an exact match against the curated songs master (authoritative; a hit means
#      trust the master's canonical spelling over the raw YouTube text)
#   3. if no match, apply a conservative shape check; titles that fail it (multi-song
#      "/" jams, leftover parenthetical annotations, bracket-only fragments, >24 chars)
#      are not written to occurrence_songs at all -- they stay visible only in
#      observed_occurrence_songs.raw_song_title (the raw-evidence layer) instead of
#      reaching the public-facing occurrence_songs layer
#   4. titles that pass the shape check but aren't in the master become new
#      songs.status='候補' rows (deduped by normalized_title) rather than being
#      silently dropped -- a real song the master hasn't seen before is exactly what
#      "first sighting" data collection is supposed to surface, per 内田さん 2026-07-24:
#      "曲名データベースに照合して一致しないのは表記揺れか、曲名ではないと推察できる…
#      未知の曲と推定して、曲データベースで曲候補として持っても良い"
#
# Deliberately NOT using difflib-style fuzzy string matching against the master: a
# 2026-07-24 spot-check found Japanese song names sharing the common "○○音頭"/"○○おどり"
# suffix score deceptively high on pure string similarity despite being different songs
# (e.g. "東西南北音頭" vs "東京北都音頭" = 0.67, "ソーラン北海" vs "ソーラン節" = 0.73,
# "ハワイ音頭" vs "イデ音頭" = 0.67) -- fuzzy-matching those would silently merge distinct
# songs. Only exact match (after noise stripping) is trusted to identify a known song.
NOISE_SUFFIX_RE = re.compile(
    r"\s*(?:第[0-9０-９]{1,3}回|20\d{2}年\s*(?:初日|二日目|三日目|最終日)?)\s*$"
)
ANNOTATION_PAREN_RE = re.compile(r"[(（][^)）]*[)）]")
LEADING_STRIP_RE = re.compile(r"^(?:終|ラスト|最後)\s*")
BRACKET_ONLY_RE = re.compile(r"^[0-9０-９]{0,3}[】\)\.]+$")
# A closing bracket with no matching opener is a leftover fragment from splitting a
# video title mid-phrase (e.g. "日枝神社 山王祭 】後半" -- the "【" that opened this
# stayed in a different fragment), not a real song name.
UNBALANCED_CLOSE_BRACKET_RE = re.compile(r"[】』」\)］]")
OPEN_BRACKET_RE = re.compile(r"[【『「\(［]")
SONG_TITLE_MAX_LEN = 24


def strip_venue_suffix(title, venue):
    """Strip a trailing "<at most one token> <venue>" tail, e.g. "きよしのズンドコ節
    新宿 花園神社" with venue="花園神社" -> "きよしのズンドコ節". Per-song YouTube
    videos from a venue whose known-event pattern was missing in
    extract_youtube_setlists.py end up with the venue name (and often a preceding
    place qualifier like "新宿") baked into every song's title (see that module's
    2026-07-24 花園神社/下町盆踊りフェス venue-detection fix).

    Must run on a space-preserving title, before normalize_text() collapses all
    whitespace -- once whitespace is gone the token boundary is gone too, and a
    lookback pattern here over-matches (2026-07-24 bug: on the pre-collapsed
    "りんご節新宿花園神社" a \\S{0,10} lookback from "花園神社" swallowed the whole
    "りんご節新宿" prefix instead of just "新宿", erasing the song name)."""
    if not venue or venue not in title:
        return title
    pattern = re.compile(r"(?:\s+\S{1,10})?\s*" + re.escape(venue) + r"\s*$")
    stripped = pattern.sub("", title).strip()
    return stripped or title


def clean_song_candidate_title(raw_title, venue=""):
    """Produce a display-quality song title: light cleanup only (NFKC width
    normalization, drop known noise), NOT the aggressive symbol/whitespace/case
    folding normalize_text() does for matching keys -- this value is stored as
    occurrence_songs.song_title_raw and shown to the public, so it must keep
    real punctuation and casing (e.g. "Let's ONDO Again")."""
    title = unicodedata.normalize("NFKC", str(raw_title or "")).strip()
    title = ANNOTATION_PAREN_RE.sub("", title)
    title = NOISE_SUFFIX_RE.sub("", title)
    title = LEADING_STRIP_RE.sub("", title)
    title = strip_venue_suffix(title, venue)
    return re.sub(r"\s+", " ", title).strip()


def song_title_passes_shape_check(title):
    if not title or len(title) > SONG_TITLE_MAX_LEN:
        return False
    if BRACKET_ONLY_RE.match(title):
        return False
    if re.fullmatch(r"第[0-9０-９]{1,3}回", title):
        return False
    if "/" in title:
        return False
    # "~"/"〜"-joined titles are the same multi-song jam problem "/" already guards
    # against, just from a different video-title convention (2026-07-24 spot-check found
    # e.g. "六本人音頭~花火音頭", "東京音頭~新橋音頭〜ハワイ音頭~炭坑節" reaching
    # occurrence_songs as single fabricated "song" entries).
    if "~" in title or "〜" in title:
        return False
    if "(" in title or "（" in title:
        return False
    if UNBALANCED_CLOSE_BRACKET_RE.search(title) and not OPEN_BRACKET_RE.search(title):
        return False
    # The converse of the check above: an opening bracket with no matching closer is
    # also a leftover fragment from splitting a video title mid-phrase (2026-07-24
    # spot-check: "日本の芸能:『加賀万歳" -- the 』 that should close 『 stayed in a
    # different fragment), not a real song name.
    if OPEN_BRACKET_RE.search(title) and not UNBALANCED_CLOSE_BRACKET_RE.search(title):
        return False
    return bool(re.search(r"[A-Za-z一-龥ぁ-んァ-ヶー]", title))


SONG_CANDIDATE_STATUS = "候補"  # matches the existing convention (e.g. build_event_song_candidates.py
# / glossary_v2 initial registration), NOT the English "candidate" -- songs.status
# already mixes 有効/無効/候補 (Japanese) with active (English, from a different
# writer); introducing a second "candidate" spelling would just add another
# inconsistent status value instead of joining the existing one.


def resolve_song(conn, raw_title, venue, now, register_candidate=True):
    """Return (song_id, display_title, verdict). verdict is one of
    'matched' (exact hit in the curated songs master), 'candidate_new'
    (new songs.status='候補' row created), 'candidate_existing'
    (matched an existing 候補 row), 'rejected' (fails the shape
    check; caller should not write an occurrence_songs row for it), or
    'unmatched_no_register' (no master hit and register_candidate=False,
    so nothing was written to songs -- used for occurrences that never
    matched a curated event and therefore can't reach occurrence_songs
    anyway; registering a candidate there would just be master pollution
    with no occurrence_songs row ever consuming it, as happened for the
    276/308 unmatched occurrences in this fix's initial dry-run)."""
    cleaned = clean_song_candidate_title(raw_title, venue)
    normalized = normalize_text(cleaned)
    existing = conn.execute(
        "SELECT song_id, canonical_title, status FROM songs WHERE normalized_title = ?",
        (normalized,),
    ).fetchone()
    if existing:
        verdict = "matched" if existing[2] != SONG_CANDIDATE_STATUS else "candidate_existing"
        return existing[0], existing[1], verdict
    if not register_candidate:
        return None, None, "unmatched_no_register"
    if not song_title_passes_shape_check(cleaned):
        return None, None, "rejected"
    song_id = stable_id("song_cand", normalized)
    conn.execute(
        """
        INSERT INTO songs(
          song_id, canonical_title, normalized_title, status, memo, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            song_id,
            cleaned,
            normalized,
            SONG_CANDIDATE_STATUS,
            "auto-registered from YouTube setlist extraction (apply_youtube_setlist_occurrences_rdb.py)",
            now,
            now,
        ),
    )
    return song_id, cleaned, "candidate_new"


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def scalar(conn, query, params=()):
    return conn.execute(query, params).fetchone()[0]


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_db(source, out_db):
    source = Path(source)
    out_db = Path(out_db)
    if not source.exists():
        raise FileNotFoundError(source)
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    shutil.copy2(source, out_db)


def backup_db(source, now):
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(source)
    stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z")
    backup = BACKUP_DIR / f"{source.stem}.{stamp}{source.suffix}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def validate_apply_request(args):
    if not args.apply:
        return
    if args.confirm != CONFIRM_PHRASE:
        raise ValueError(f"--apply requires --confirm '{CONFIRM_PHRASE}'")
    if Path(args.out_db) == Path(args.master_db):
        raise ValueError("--out-db must not equal --master-db")


def occurrence_year(occurrence):
    for date_value in (occurrence.get("event_date"), (occurrence.get("matched_public_event") or {}).get("date")):
        if date_value:
            try:
                return int(str(date_value)[:4])
            except ValueError:
                continue
    return None


def best_match(conn, occurrence, year):
    override_occurrence_id = MANUAL_MATCH_OVERRIDES.get(occurrence.get("occurrence_key") or "")
    if override_occurrence_id:
        return {"occurrence_id": override_occurrence_id, "match_score": None}
    if year is None:
        return None
    candidates = find_occurrence_candidates(
        conn,
        occurrence["event_name_hint"],
        venue_name_hint=occurrence.get("venue"),
        event_year=year,
        limit=1,
    )
    if not candidates or candidates[0]["match_score"] < MATCH_SCORE_THRESHOLD:
        return None
    return candidates[0]


def apply_occurrence(conn, occurrence, now):
    event_name = occurrence.get("event_name_hint") or ""
    venue_name = occurrence.get("venue") or ""
    occurrence_key = occurrence.get("occurrence_key") or ""
    year = occurrence_year(occurrence)
    match = best_match(conn, occurrence, year)
    matched_occurrence_id = match["occurrence_id"] if match else None

    flags = quality_flags(event_name, venue_name)
    if not year:
        flags = flags + ["missing_event_date"]
    if "venue_looks_like_text_fragment" in flags:
        quality_status = "discard_candidate"
    elif "outside_tokyo_23_hint" in flags:
        quality_status = "out_of_scope"
    elif matched_occurrence_id:
        quality_status = "matched_curated"
    else:
        quality_status = "review"

    observed_occurrence_id = stable_id(
        "obsocc", "youtube_setlist", occurrence_key, event_name, venue_name, year or 0
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO observed_occurrences(
          observed_occurrence_id, source, source_occurrence_id, raw_event_name, raw_venue_name,
          normalized_event_name, normalized_venue_name, event_year, matched_occurrence_id,
          match_status, quality_status, quality_flags_json, source_payload_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observed_occurrence_id,
            "youtube_setlist_occurrences",
            occurrence_key,
            event_name,
            venue_name,
            normalize_text(event_name),
            normalize_text(venue_name),
            year or 0,
            matched_occurrence_id,
            "matched_curated" if matched_occurrence_id else "unmatched",
            quality_status,
            json.dumps(flags, ensure_ascii=False),
            json_text(
                {
                    "occurrence_key": occurrence_key,
                    "event_name_hint": event_name,
                    "venue": venue_name,
                    "event_date": occurrence.get("event_date"),
                    "accounts": occurrence.get("accounts"),
                    "confidence": occurrence.get("confidence"),
                    "matched_public_event": occurrence.get("matched_public_event"),
                    "match_score": match["match_score"] if match else None,
                }
            ),
            now,
            now,
        ),
    )

    confidence = occurrence.get("confidence") or "low"
    reliability = RELIABILITY_BY_CONFIDENCE.get(confidence, 0.55)
    setlist_complete = 1 if confidence == "high" else 0
    accounts = occurrence.get("accounts") or []
    speaker_count = len(set(accounts)) or 1
    source_videos = occurrence.get("source_videos") or []
    first_video = source_videos[0] if source_videos else {}

    song_relation_count = 0
    evidence_count = 0
    rejected_title_count = 0
    candidate_song_count = 0
    for song in occurrence.get("setlist") or []:
        title = song.get("title") or ""
        if not title:
            continue
        normalized = normalize_text(title)
        role = "result"
        song_id, display_title, verdict = resolve_song(
            conn, title, venue_name, now, register_candidate=bool(matched_occurrence_id)
        )
        if verdict == "candidate_new":
            candidate_song_count += 1
        occurrence_song_id = None
        if matched_occurrence_id and verdict != "rejected":
            clean_normalized = normalize_text(display_title)
            # occurrence_songs.occurrence_song_id is not a stable function of its own unique key
            # across every writer (e.g. the firsthand field-report pipeline uses an "osong_" prefix
            # instead of this script's "ocs_"). The real identity is the UNIQUE(occurrence_id,
            # normalized_title, role) constraint, so look up an existing row by that key first and
            # reuse its id -- otherwise a fresh INSERT OR IGNORE silently no-ops on the unique
            # conflict while leaving our freshly-computed id unreferenced, and the next statement's
            # FK to it fails.
            existing = conn.execute(
                """
                SELECT occurrence_song_id FROM occurrence_songs
                WHERE occurrence_id = ? AND normalized_title = ? AND role = ?
                """,
                (matched_occurrence_id, clean_normalized, role),
            ).fetchone()
            if existing:
                occurrence_song_id = existing[0]
                conn.execute(
                    """
                    UPDATE occurrence_songs
                    SET evidence_count = evidence_count + 1,
                        source_count = source_count + 1,
                        last_observed_at = COALESCE(NULLIF(?, ''), last_observed_at),
                        updated_at = ?
                    WHERE occurrence_song_id = ?
                    """,
                    (first_video.get("published_at") or "", now, occurrence_song_id),
                )
            else:
                occurrence_song_id = stable_id("ocs", matched_occurrence_id, clean_normalized, role)
                conn.execute(
                    """
                    INSERT INTO occurrence_songs(
                      occurrence_song_id, origin, occurrence_id, song_id, song_title_raw, normalized_title,
                      role, evidence_status, probability, confidence, source_count, evidence_count,
                      inherited_from_year, first_observed_at, last_observed_at, notes, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        occurrence_song_id,
                        "observed_youtube_setlist",
                        matched_occurrence_id,
                        song_id,
                        display_title,
                        clean_normalized,
                        role,
                        "observed",
                        None,
                        "unknown",
                        1,
                        1,
                        None,
                        first_video.get("published_at") or "",
                        first_video.get("published_at") or "",
                        json_text(
                            {
                                "basis": "youtube_observed_setlist",
                                "extraction_confidence": confidence,
                                "title_quality_verdict": verdict,
                                "raw_title": title,
                            }
                        ),
                        now,
                        now,
                    ),
                )
        elif verdict == "rejected":
            rejected_title_count += 1

        observed_occurrence_song_id = stable_id("obsocs", observed_occurrence_id, normalized, role)
        conn.execute(
            """
            INSERT OR IGNORE INTO observed_occurrence_songs(
              observed_occurrence_song_id, observed_occurrence_id, occurrence_song_id,
              raw_song_title, normalized_title, matched_song_id, match_status, role,
              evidence_status, probability, evidence_count, speaker_count, setlist_complete,
              prediction_reliability_json, evidence_urls_json, source_payload_json,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observed_occurrence_song_id,
                observed_occurrence_id,
                occurrence_song_id,
                title,
                normalized,
                song_id,
                "matched_song" if song_id else "unmatched",
                role,
                "observed",
                None,
                1,
                speaker_count,
                setlist_complete,
                json_text([reliability]),
                json_text([song.get("url")] if song.get("url") else []),
                json_text({"confidence": confidence, "reliability_key": occurrence.get("reliability_key")}),
                now,
                now,
            ),
        )
        song_relation_count += 1

        evidence_id = stable_id("ev", "youtube_setlist", observed_occurrence_id, normalized, song.get("url") or "")
        conn.execute(
            """
            INSERT OR IGNORE INTO evidence_items(
              evidence_id, platform, evidence_type, source_key, source_id, account_key,
              title, text_excerpt, url, published_at, observed_at, detected_event_date,
              raw_status, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                "youtube",
                "observed",
                "youtube_setlist_occurrences",
                occurrence_key,
                ",".join(accounts),
                first_video.get("title") or "",
                "",
                song.get("url") or "",
                first_video.get("published_at") or "",
                first_video.get("published_at") or "",
                occurrence.get("event_date") or "",
                "result",
                json_text(
                    {
                        "song_number": song.get("number"),
                        "occurrence_key": occurrence_key,
                        "confidence": confidence,
                    }
                ),
            ),
        )
        evidence_count += 1
        if occurrence_song_id:
            conn.execute(
                """
                INSERT OR IGNORE INTO occurrence_song_evidence_links(
                  occurrence_song_id, evidence_id, link_status, confidence, notes
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (occurrence_song_id, evidence_id, "linked", reliability, "youtube_setlist_occurrences"),
            )

    return {
        "observed_occurrence_id": observed_occurrence_id,
        "occurrence_key": occurrence_key,
        "matched_occurrence_id": matched_occurrence_id,
        "match_score": match["match_score"] if match else None,
        "quality_status": quality_status,
        "song_relation_count": song_relation_count,
        "evidence_count": evidence_count,
        "rejected_title_count": rejected_title_count,
        "candidate_song_count": candidate_song_count,
    }


def apply_all(conn, occurrences, now):
    results = [apply_occurrence(conn, occurrence, now) for occurrence in occurrences]
    return results


def consistency_checks(conn, results, now):
    issues = []
    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_rows:
        issues.append(
            {
                "severity": "high",
                "issue_type": "foreign_key_check_failed",
                "count": len(fk_rows),
                "sample": [tuple(row) for row in fk_rows[:10]],
            }
        )
    matched_count = sum(1 for r in results if r["matched_occurrence_id"])
    if matched_count == 0:
        issues.append({"severity": "high", "issue_type": "no_matches_produced"})
    orphan_links = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM occurrence_song_evidence_links l
        LEFT JOIN occurrence_songs s ON s.occurrence_song_id = l.occurrence_song_id
        LEFT JOIN evidence_items e ON e.evidence_id = l.evidence_id
        WHERE s.occurrence_song_id IS NULL OR e.evidence_id IS NULL
        """,
    )
    if orphan_links:
        issues.append({"severity": "high", "issue_type": "orphan_evidence_link", "count": orphan_links})
    # Scoped to rows created_at == this run's `now`, not the whole origin: this script
    # itself never writes a probability value (always None on INSERT, and its UPDATE path
    # for pre-existing rows never touches the column) -- see docstring. But
    # calibrate_song_probabilities_rdb.py (2026-07-24 follow-up) legitimately computes and
    # writes probability for origin='observed_youtube_setlist' rows created by earlier runs
    # of this script, so checking the whole origin unconditionally started flaging that
    # expected state as a false positive once calibration existed. Only a row this exact
    # run inserted with a non-null probability would be a real fabrication.
    fabricated_probability = scalar(
        conn,
        """
        SELECT COUNT(*) FROM occurrence_songs
        WHERE origin = 'observed_youtube_setlist' AND probability IS NOT NULL AND created_at = ?
        """,
        (now,),
    )
    if fabricated_probability:
        issues.append(
            {
                "severity": "high",
                "issue_type": "fabricated_probability_value",
                "count": fabricated_probability,
            }
        )
    return issues


def audit_db(db_path, out_json=None, out_md=None):
    args = SimpleNamespace(
        db=str(db_path),
        notion_db=str(audit_master_rdb.NOTION_DB),
        song_occurrences=str(audit_master_rdb.SONG_OCCURRENCES),
        manifest=str(audit_master_rdb.MASTER_MANIFEST),
        out_json=str(out_json or OUT_JSON.with_suffix(".audit.json")),
        out_md=str(out_md or OUT_MD.with_suffix(".audit.md")),
    )
    return audit_master_rdb.audit(args)


def issue_summary(issues):
    return dict(Counter(row.get("severity") for row in issues))


def render_markdown(result):
    summary = result["summary"]
    lines = [
        "# YouTube setlist occurrences RDB apply report",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- target_db: `{result['outputs']['target_db']}`",
        f"- backup_db: `{result['outputs']['backup_db']}`",
        f"- db_committed: {result['write_guard']['db_committed']}",
        f"- rolled_back: {result['write_guard']['rolled_back']}",
        f"- match_score_threshold: {MATCH_SCORE_THRESHOLD}",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary.items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "- probability: intentionally left NULL (RDB-native computation is a separate follow-up)",
            "- Notion write-back: skipped",
            "- public JSON write: skipped (not wired into export_public_events.py yet)",
            "",
        ]
    )
    if result["issues"]:
        lines.extend(["## Issues", ""])
        for issue in result["issues"]:
            lines.append(f"- {issue['severity']} {issue['issue_type']}: {issue}")
        lines.append("")
    return "\n".join(lines)


def run(args):
    validate_apply_request(args)
    now = now_utc()
    data = json.loads(Path(args.source).read_text(encoding="utf-8"))
    occurrences = data.get("occurrences") or []

    target_db = Path(args.master_db if args.apply else args.out_db)
    backup_path = ""
    if args.apply:
        preflight_db = DATA / "youtube_setlist_occurrences_apply_preflight.sqlite"
        copy_db(args.master_db, preflight_db)
        with connect_existing(preflight_db) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            preflight_results = apply_all(conn, occurrences, now)
            preflight_issues = consistency_checks(conn, preflight_results, now)
            conn.commit()
        preflight_audit = audit_db(preflight_db)
        if any(row.get("severity") == "high" for row in preflight_issues + preflight_audit["issues"]):
            raise ValueError(
                "preflight refused high severity issues: "
                f"checks={issue_summary(preflight_issues)} "
                f"audit={preflight_audit['issues_by_severity']}"
            )
        backup_path = str(backup_db(args.master_db, now))
    else:
        copy_db(args.master_db, args.out_db)

    committed = False
    rolled_back = False
    with connect_existing(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        results = apply_all(conn, occurrences, now)
        issues = consistency_checks(conn, results, now)
        has_high_issue = any(row.get("severity") == "high" for row in issues)
        if has_high_issue:
            conn.rollback()
            rolled_back = True
        else:
            conn.commit()
            committed = True
        counts = table_counts(conn)

    audit_result = audit_db(
        target_db,
        out_json=args.out_json.with_suffix(".audit.json"),
        out_md=args.out_md.with_suffix(".audit.md"),
    )
    if args.apply and audit_result["issues_by_severity"].get("high"):
        raise ValueError(f"post-apply audit has high issues: {audit_result['issues_by_severity']}")
    if args.apply and committed:
        refresh_manifest_database_state(args.master_db, updated_at=now)

    matched_results = [r for r in results if r["matched_occurrence_id"]]
    result = {
        "generated_by": SCRIPT_NAME,
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "sources": {"master_db": str(args.master_db), "source_json": str(args.source)},
        "outputs": {
            "target_db": str(target_db),
            "dry_run_db": "" if args.apply else str(args.out_db),
            "backup_db": backup_path,
            "json": str(args.out_json),
            "markdown": str(args.out_md),
        },
        "options": {"apply": bool(args.apply), "match_score_threshold": MATCH_SCORE_THRESHOLD},
        "write_guard": {
            "db_committed": committed,
            "rolled_back": rolled_back,
            "rollback_reason": "high_severity_issue" if rolled_back else "",
        },
        "summary": {
            "occurrences_processed": len(results),
            "occurrences_matched": len(matched_results),
            "occurrences_unmatched": len(results) - len(matched_results),
            "song_relations_written": sum(r["song_relation_count"] for r in results),
            "evidence_items_written": sum(r["evidence_count"] for r in results),
            "song_titles_rejected": sum(r["rejected_title_count"] for r in results),
            "candidate_songs_registered": sum(r["candidate_song_count"] for r in results),
            "issues_by_severity": issue_summary(issues),
            "audit_issues_by_severity": audit_result["issues_by_severity"],
            "table_counts": counts,
        },
        "matched_sample": matched_results[:20],
        "issues": issues,
        "audit": {
            "issue_count": audit_result["issue_count"],
            "issues_by_severity": audit_result["issues_by_severity"],
            "issues_by_type": audit_result["issues_by_type"],
        },
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out-db", type=Path, default=OUT_DB)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        result = run(args)
    except ValueError as exc:
        parser.error(str(exc))
    print(
        "youtube setlist occurrences rdb apply: "
        f"mode={result['mode']} "
        f"committed={result['write_guard']['db_committed']} "
        f"matched={result['summary']['occurrences_matched']}/{result['summary']['occurrences_processed']} "
        f"song_relations={result['summary']['song_relations_written']} "
        f"issues={result['summary']['issues_by_severity']} "
        f"audit={result['summary']['audit_issues_by_severity']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
