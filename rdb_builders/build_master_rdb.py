"""Build the Ph0 dry-run master SQLite database."""

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from event_series.normalization import series_event_name
from event_state_axes import axes_from_legacy_occurrence
from master_db import (
    MASTER_DB,
    MASTER_MANIFEST,
    MASTER_SCHEMA,
    file_sha256,
    init_db,
    json_text,
    normalize_text,
    now_utc,
    stable_id,
    table_counts,
    write_schema_dump,
)


DATA = Path("data")
NOTION_DB = DATA / "notion_snapshot.sqlite"
SONG_OCCURRENCES = DATA / "song_occurrences.json"
OUT_REPORT = DATA / "master_rdb_ph0_dry_run_report.json"
OUT_REPORT_MD = DATA / "master_rdb_ph0_dry_run_report.md"
OBSERVED_PROMOTION_CANDIDATES = DATA / "observed_promotion_candidates.json"
REGISTERED_EVENT_INVESTIGATION_QUEUE = DATA / "registered_event_investigation_queue.json"
HISTORICAL_PROMOTION_CANDIDATES = DATA / "historical_promotion_candidates.json"
TODAY = date(2026, 6, 20)
TOKYO_23_AREAS = {
    "千代田区", "中央区", "港区", "新宿区", "文京区", "台東区", "墨田区", "江東区",
    "品川区", "目黒区", "大田区", "世田谷区", "渋谷区", "中野区", "杉並区", "豊島区",
    "北区", "荒川区", "板橋区", "練馬区", "足立区", "葛飾区", "江戸川区",
}


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows(db_path, table):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]


def parse_year(*values, default=2026):
    for value in values:
        match = re.search(r"(20\d{2})", str(value or ""))
        if match:
            return int(match.group(1))
    return default


def parse_months(value):
    months = []
    for match in re.finditer(r"(?<!\d)(1[0-2]|[1-9])\s*月?", str(value or "")):
        month = int(match.group(1))
        if month not in months:
            months.append(month)
    return months


def date_status(status, start_date):
    status = status or ""
    if "中止" in status:
        return "cancelled"
    if not start_date:
        return "unknown"
    if start_date < TODAY.isoformat():
        return "ended"
    if status in {"確認済み", "終了"}:
        return "confirmed"
    return "predicted"


def lifecycle_status(status):
    if status in {"確認済み", "終了"}:
        return "published"
    if status:
        return status
    return "draft"


class MasterBuilder:
    def __init__(self, conn):
        self.conn = conn
        self.now = now_utc()
        self.venue_by_page = {}
        self.venue_by_norm = {}
        self.song_by_page = {}
        self.song_by_norm = {}
        self.series_by_key = {}
        self.occurrence_by_series_year = {}
        self.occurrence_sequence = Counter()
        self.placeholder_counts = Counter()

    def external_link(self, system, source_key, external_id, master_table, master_id, relation_kind="primary"):
        if not external_id:
            return
        self.conn.execute(
            """
            INSERT OR IGNORE INTO external_record_links(
              system, source_key, external_id, master_table, master_id,
              relation_kind, last_seen_at, source_checksum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                system,
                source_key,
                external_id,
                master_table,
                master_id,
                relation_kind,
                self.now,
                "",
            ),
        )

    def add_venue(self, name, area="", address="", access="", scale="", public_intro="", past_memo="", source_url="", page_id=""):
        canonical = (name or "").strip()
        if not canonical:
            canonical = "名称未設定会場"
        normalized = normalize_text(canonical)
        key = (normalized, address or "")
        if key in self.venue_by_norm:
            venue_id = self.venue_by_norm[key]
        else:
            venue_id = stable_id("ven", canonical, address or area)
            self.conn.execute(
                """
                INSERT OR IGNORE INTO venues(
                  venue_id, origin, canonical_name, normalized_name, area, address, access, scale,
                  public_intro, past_memo, source_url, review_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    venue_id,
                    "curated",
                    canonical,
                    normalized,
                    area or "",
                    address or "",
                    access or "",
                    scale or "",
                    public_intro or "",
                    past_memo or "",
                    source_url or "",
                    "active",
                    self.now,
                    self.now,
                ),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO venue_aliases VALUES (?, ?, ?, ?, ?)",
                (venue_id, canonical, normalized, "canonical", "manual"),
            )
            self.venue_by_norm[key] = venue_id
        if page_id:
            self.venue_by_page[page_id] = venue_id
            self.external_link("notion", "venues", page_id, "venues", venue_id)
        return venue_id

    def venue_for_name(self, name):
        normalized = normalize_text(name)
        for (venue_norm, _address), venue_id in self.venue_by_norm.items():
            if venue_norm == normalized:
                return venue_id
        return None

    def add_song(self, title, category="", status="", evidence_count=None, source_url="", memo="", prior_tier="", target_area="", page_id=""):
        canonical = (title or "").strip()
        if not canonical:
            canonical = "名称未設定曲"
        normalized = normalize_text(canonical)
        if normalized in self.song_by_norm:
            song_id = self.song_by_norm[normalized]
        else:
            song_id = stable_id("song", canonical)
            self.conn.execute(
                """
                INSERT OR IGNORE INTO songs(
                  song_id, canonical_title, normalized_title, category, status, prior_tier,
                  target_area, evidence_count, source_url, memo, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    song_id,
                    canonical,
                    normalized,
                    category or "",
                    status or "active",
                    prior_tier or "",
                    target_area or "",
                    evidence_count,
                    source_url or "",
                    memo or "",
                    self.now,
                    self.now,
                ),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO song_aliases VALUES (?, ?, ?, ?, ?)",
                (song_id, canonical, normalized, "canonical", "manual"),
            )
            self.song_by_norm[normalized] = song_id
        if page_id:
            self.song_by_page[page_id] = song_id
            self.external_link("notion", "songs", page_id, "songs", song_id)
        return song_id

    def song_for_title(self, title):
        return self.song_by_norm.get(normalize_text(title))

    def add_series(self, event_name, venue_id=None, area="", program_type="", annual_months=None,
                   schedule_rule_type="", schedule_rule_detail="", public_intro="", source_url=""):
        canonical = series_event_name(event_name or "名称未設定イベント")
        venue_part = venue_id or ""
        series_key = stable_id("serkey", normalize_text(canonical), venue_part, length=12)
        if series_key in self.series_by_key:
            return self.series_by_key[series_key]
        series_id = stable_id("ser", series_key)
        self.conn.execute(
            """
            INSERT OR IGNORE INTO event_series(
              series_id, origin, series_key, canonical_name, normalized_name, usual_venue_id, area,
              program_type, annual_months_json, schedule_rule_type, schedule_rule_detail,
              public_intro, source_url, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                series_id,
                "curated",
                series_key,
                canonical,
                normalize_text(canonical),
                venue_id,
                area or "",
                program_type or "",
                json.dumps(annual_months or [], ensure_ascii=False),
                schedule_rule_type or "",
                schedule_rule_detail or "",
                public_intro or "",
                source_url or "",
                "active",
                self.now,
                self.now,
            ),
        )
        self.series_by_key[series_key] = series_id
        return series_id

    def add_occurrence(self, series_id, event_name, event_year, venue_id=None, date_start="", date_end="",
                       status="", source_kind="", source_url="", public_intro="", detail="", external_id=""):
        key = (series_id, int(event_year))
        if key in self.occurrence_by_series_year:
            occurrence_id = self.occurrence_by_series_year[key]
        else:
            self.occurrence_sequence[key] += 1
            sequence = self.occurrence_sequence[key]
            occurrence_id = stable_id("occ", series_id, event_year, sequence)
            dstatus = date_status(status, date_start)
            legacy_lifecycle = lifecycle_status(status)
            axes = axes_from_legacy_occurrence(
                {
                    "event_year": int(event_year),
                    "date_start": date_start or "",
                    "date_status": dstatus,
                    "lifecycle_status": legacy_lifecycle,
                    "source_kind": source_kind or "",
                    "source_url": source_url or "",
                }
            )
            self.conn.execute(
                """
                INSERT INTO event_occurrences(
                  occurrence_id, origin, series_id, event_year, occurrence_sequence, display_name,
                  venue_id, date_start, date_end, date_status, lifecycle_status,
                  current_event_state, date_certainty_tier, confidence,
                  source_kind, source_url, public_intro_override, detail, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    occurrence_id,
                    "curated",
                    series_id,
                    int(event_year),
                    sequence,
                    series_event_name(event_name or ""),
                    venue_id,
                    date_start or "",
                    date_end or "",
                    dstatus,
                    legacy_lifecycle,
                    axes["current_event_state"],
                    axes["date_certainty_tier"],
                    "confirmed" if dstatus in {"confirmed", "ended"} else "unknown",
                    source_kind or "",
                    source_url or "",
                    public_intro or "",
                    detail or "",
                    self.now,
                    self.now,
                ),
            )
            if date_start:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO occurrence_dates(
                      occurrence_date_id, occurrence_id, date_start, date_end, date_type,
                      confidence, basis, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stable_id("odate", occurrence_id, date_start, date_end),
                        occurrence_id,
                        date_start,
                        date_end or "",
                        dstatus,
                        "confirmed" if dstatus in {"confirmed", "ended"} else "unknown",
                        source_kind or "",
                        self.now,
                    ),
                )
            self.occurrence_by_series_year[key] = occurrence_id
        if external_id:
            self.external_link("notion", "events", external_id, "event_occurrences", occurrence_id)
            self.external_link("notion", "events", external_id, "event_series", series_id, "series_for_occurrence")
        return occurrence_id

    def add_evidence(self, ev):
        evidence_id = ev.get("id")
        if not evidence_id:
            return ""
        url = ev.get("url") or ""
        platform = "youtube" if "youtu" in url else ev.get("source") or "unknown"
        self.conn.execute(
            """
            INSERT OR IGNORE INTO evidence_items(
              evidence_id, platform, evidence_type, source_key, source_id, account_key,
              title, text_excerpt, url, published_at, observed_at, detected_event_date,
              raw_status, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                platform,
                ev.get("kind") or "unknown",
                ev.get("source") or "",
                ev.get("url") or "",
                ev.get("dancer_key") or "",
                "",
                ev.get("text") or "",
                url,
                "",
                ev.get("observed_at") or "",
                ev.get("date") or "",
                ev.get("role") or "",
                json_text(ev),
            ),
        )
        return evidence_id


def build_from_notion(builder, notion_db):
    venues = rows(notion_db, "notion_venues")
    events = rows(notion_db, "notion_events")
    songs = rows(notion_db, "notion_songs")
    relations = rows(notion_db, "notion_relations")
    event_venues = defaultdict(list)
    for relation in relations:
        if relation.get("property_name") == "会場":
            event_venues[relation["page_id"]].append(relation["related_page_id"])

    for row in venues:
        builder.add_venue(
            row.get("venue_name"),
            area=row.get("area"),
            address=row.get("address"),
            access=row.get("access"),
            scale=row.get("scale"),
            public_intro=row.get("public_intro"),
            past_memo=row.get("past_memo"),
            page_id=row.get("page_id"),
        )

    for row in songs:
        builder.add_song(
            row.get("song_name"),
            category=row.get("category"),
            status=row.get("status"),
            evidence_count=row.get("evidence_count"),
            source_url=row.get("source_url"),
            memo=row.get("memo"),
            page_id=row.get("page_id"),
        )

    for row in events:
        venue_ids = [builder.venue_by_page.get(page_id) for page_id in event_venues.get(row["page_id"], [])]
        venue_id = next((item for item in venue_ids if item), None)
        year = parse_year(row.get("start_date"), row.get("event_name"), default=2026)
        series_id = builder.add_series(
            row.get("event_name"),
            venue_id=venue_id,
            annual_months=parse_months(row.get("annual_months")),
            public_intro=row.get("public_intro"),
            source_url=row.get("source_url"),
        )
        builder.add_occurrence(
            series_id,
            row.get("event_name"),
            year,
            venue_id=venue_id,
            date_start=row.get("start_date"),
            date_end=row.get("end_date"),
            status=row.get("status"),
            source_kind="notion_events",
            source_url=row.get("source_url"),
            public_intro=row.get("public_intro"),
            detail=row.get("detail"),
            external_id=row.get("page_id"),
        )

    return {"notion_venues": len(venues), "notion_events": len(events), "notion_songs": len(songs)}


def song_role(song, occurrence_year):
    evidence = song.get("evidence") or []
    years = [ev.get("year") for ev in evidence if ev.get("year")]
    roles = {ev.get("role") for ev in evidence}
    if "result" in roles and occurrence_year in years:
        return "result"
    if years and max(years) < occurrence_year:
        return "prediction"
    return next((role for role in ["prediction", "historical_basis", "hint"] if role in roles), "hint")


def evidence_status(song, occurrence_year):
    evidence = song.get("evidence") or []
    years = [ev.get("year") for ev in evidence if ev.get("year")]
    kinds = {ev.get("kind") for ev in evidence}
    if years and max(years) < occurrence_year:
        return "inherited"
    if "observed" in kinds:
        return "observed"
    if "announced" in kinds:
        return "announced"
    return "predicted"


def quality_flags(event_name, venue_name):
    flags = []
    text = f"{event_name} {venue_name}"
    if not venue_name:
        flags.append("missing_venue")
    if len(str(venue_name or "")) > 40:
        flags.append("venue_too_long")
    if re.search(r"(https?://|!!|！|お客|飛び入り|有名な|流し踊り|動画|ver|全曲)", str(venue_name or ""), re.IGNORECASE):
        flags.append("venue_looks_like_text_fragment")
    if any(area in text for area in TOKYO_23_AREAS):
        flags.append("tokyo_23_hint")
    elif re.search(r"(鎌倉|尼崎|上野原|葉山|神戸|松戸|横浜|川崎|さいたま|千葉県|神奈川県|兵庫県|山梨県)", text):
        flags.append("outside_tokyo_23_hint")
    return flags


def build_from_song_occurrences(builder, path):
    data = load_json(path, {})
    occurrence_count = 0
    relation_count = 0
    unresolved_song_count = 0
    matched_occurrence_count = 0
    observed_only_count = 0
    discarded_garbage_count = 0
    for occurrence in data.get("occurrences") or []:
        event_name = occurrence.get("event_name") or ""
        venue_name = occurrence.get("venue") or ""
        year = int(occurrence.get("year") or parse_year(event_name))
        venue_id = builder.venue_for_name(venue_name)
        flags = quality_flags(event_name, venue_name)
        if "venue_looks_like_text_fragment" in flags:
            quality_status = "discard_candidate"
            discarded_garbage_count += 1
        elif "outside_tokyo_23_hint" in flags:
            quality_status = "out_of_scope"
        elif venue_id:
            quality_status = "matched_curated"
        else:
            quality_status = "review"

        normalized_event = normalize_text(series_event_name(event_name))
        normalized_venue = normalize_text(venue_name)
        matched_occurrence_id = None
        if venue_id:
            for (series_id, occ_year), candidate_id in builder.occurrence_by_series_year.items():
                if occ_year != year:
                    continue
                row = builder.conn.execute(
                    "SELECT s.normalized_name, o.venue_id FROM event_occurrences o JOIN event_series s ON s.series_id = o.series_id WHERE o.occurrence_id = ?",
                    (candidate_id,),
                ).fetchone()
                if row and row[0] == normalized_event and row[1] == venue_id:
                    matched_occurrence_id = candidate_id
                    break

        observed_occurrence_id = stable_id("obsocc", occurrence.get("occurrence_id") or "", event_name, venue_name, year)
        builder.conn.execute(
            """
            INSERT OR IGNORE INTO observed_occurrences(
              observed_occurrence_id, source, source_occurrence_id, raw_event_name, raw_venue_name,
              normalized_event_name, normalized_venue_name, event_year, matched_occurrence_id,
              match_status, quality_status, quality_flags_json, source_payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observed_occurrence_id,
                "song_occurrences",
                occurrence.get("occurrence_id") or "",
                event_name,
                venue_name,
                normalized_event,
                normalized_venue,
                year,
                matched_occurrence_id,
                "matched_curated" if matched_occurrence_id else "unmatched",
                quality_status,
                json.dumps(flags, ensure_ascii=False),
                json_text({key: occurrence.get(key) for key in ["occurrence_id", "event_name", "venue", "year"]}),
                builder.now,
                builder.now,
            ),
        )
        builder.external_link(
            "json",
            "song_occurrences",
            occurrence.get("occurrence_id"),
            "observed_occurrences",
            observed_occurrence_id,
        )
        if matched_occurrence_id:
            matched_occurrence_count += 1
        else:
            observed_only_count += 1
        occurrence_count += 1
        for song in occurrence.get("songs") or []:
            title = song.get("song_name") or ""
            normalized = normalize_text(title)
            song_id = builder.song_for_title(title)
            if not song_id:
                unresolved_song_count += 1
            role = song_role(song, year)
            occ_song_id = None
            evidence = song.get("evidence") or []
            observed_dates = sorted({ev.get("observed_at") for ev in evidence if ev.get("observed_at")})
            probability = (song.get("prediction") or {}).get("probability")
            prediction_reliability = [
                ev.get("reliability")
                for ev in evidence
                if ev.get("role") == "prediction" and ev.get("reliability") is not None
            ]
            evidence_urls = [ev.get("url") for ev in evidence if ev.get("url")][:5]
            setlist_complete = 1 if any(ev.get("setlist_complete") for ev in evidence) else 0
            if matched_occurrence_id:
                occ_song_id = stable_id("ocs", matched_occurrence_id, normalized, role)
                builder.conn.execute(
                    """
                    INSERT OR IGNORE INTO occurrence_songs(
                      occurrence_song_id, origin, occurrence_id, song_id, song_title_raw, normalized_title,
                      role, evidence_status, probability, confidence, source_count, evidence_count,
                      inherited_from_year, first_observed_at, last_observed_at, notes, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        occ_song_id,
                        "observed_matched",
                        matched_occurrence_id,
                        song_id,
                        title,
                        normalized,
                        role,
                        evidence_status(song, year),
                        probability,
                        "high" if probability and probability >= 90 else "unknown",
                        len({ev.get("url") for ev in evidence if ev.get("url")}),
                        song.get("evidence_count") or len(evidence),
                        (song.get("prediction") or {}).get("latest_year"),
                        observed_dates[0] if observed_dates else "",
                        observed_dates[-1] if observed_dates else "",
                        json_text({"basis": (song.get("prediction") or {}).get("basis")}),
                        builder.now,
                        builder.now,
                    ),
                )
            observed_song_id = stable_id("obsocs", observed_occurrence_id, normalized, role)
            builder.conn.execute(
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
                    observed_song_id,
                    observed_occurrence_id,
                    occ_song_id,
                    title,
                    normalized,
                    song_id,
                    "matched_song" if song_id else "unmatched",
                    role,
                    evidence_status(song, year),
                    probability,
                    song.get("evidence_count") or len(evidence),
                    song.get("speaker_count") or 0,
                    setlist_complete,
                    json_text(prediction_reliability),
                    json_text(evidence_urls),
                    json_text({"prediction": song.get("prediction") or {}}),
                    builder.now,
                    builder.now,
                ),
            )
            relation_count += 1
            for ev in evidence:
                evidence_id = builder.add_evidence(ev)
                if evidence_id and occ_song_id:
                    builder.conn.execute(
                        """
                        INSERT OR IGNORE INTO occurrence_song_evidence_links(
                          occurrence_song_id, evidence_id, link_status, confidence, notes
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            occ_song_id,
                            evidence_id,
                            "accepted",
                            float(ev.get("reliability") or 0),
                            ev.get("source") or "",
                        ),
                    )
    return {
        "song_occurrence_input_count": occurrence_count,
        "song_relation_input_count": relation_count,
        "unresolved_song_count": unresolved_song_count,
        "matched_curated_occurrence_count": matched_occurrence_count,
        "observed_only_occurrence_count": observed_only_count,
        "discard_candidate_observed_occurrence_count": discarded_garbage_count,
    }


def render_markdown(report):
    lines = [
        "# Master RDB Ph0 dry-run",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- database: {report['database']}",
        f"- dry_run: {report['dry_run']}",
        "",
        "## Source counts",
        "",
    ]
    for key, value in report["source_counts"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Table counts", ""])
    for key, value in report["table_counts"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Notes", ""])
    lines.append(f"- placeholder_counts: {report['placeholder_counts']}")
    lines.append(f"- manifest: {MASTER_MANIFEST}")
    return "\n".join(lines) + "\n"


def build(args):
    conn = init_db(args.out_db, force_rebuild_from_snapshot=args.force_rebuild_from_snapshot)
    builder = MasterBuilder(conn)
    source_counts = {}
    source_counts.update(build_from_notion(builder, Path(args.notion_db)))
    source_counts.update(build_from_song_occurrences(builder, Path(args.song_occurrences)))
    conn.commit()
    write_schema_dump(conn, args.out_schema)
    counts = table_counts(conn)
    report = {
        "generated_by": "build_master_rdb.py",
        "generated_at": now_utc(),
        "dry_run": True,
        "database": str(args.out_db),
        "schema": str(args.out_schema),
        "sources": {
            "notion_db": str(args.notion_db),
            "song_occurrences": str(args.song_occurrences),
        },
        "source_counts": source_counts,
        "table_counts": counts,
        "placeholder_counts": dict(builder.placeholder_counts),
    }
    write_json(args.report, report)
    Path(args.report_md).write_text(render_markdown(report), encoding="utf-8")
    manifest = {
        "generated_by": "build_master_rdb.py",
        "generated_at": report["generated_at"],
        "dry_run": True,
        "database": str(args.out_db),
        "schema": str(args.out_schema),
        "table_counts": counts,
        "source_checksums": {
            "notion_db": file_sha256(args.notion_db),
            "song_occurrences": file_sha256(args.song_occurrences),
        },
        "database_checksum": file_sha256(args.out_db),
        "report": str(args.report),
        "post_build_outputs": {
            "observed_promotion_candidates": str(OBSERVED_PROMOTION_CANDIDATES),
            "registered_event_investigation_queue": str(REGISTERED_EVENT_INVESTIGATION_QUEUE),
            "historical_promotion_candidates": str(HISTORICAL_PROMOTION_CANDIDATES),
        },
        "post_build_steps": [
            "promotion_candidates/build_observed_promotion_candidates.py",
            "promotion_candidates/build_registered_event_investigation_queue.py",
            "promotion_candidates/build_historical_promotion_candidates.py",
        ],
    }
    write_json(args.manifest, manifest)
    conn.close()
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--notion-db", default=str(NOTION_DB))
    parser.add_argument("--song-occurrences", default=str(SONG_OCCURRENCES))
    parser.add_argument("--out-db", default=str(MASTER_DB))
    parser.add_argument("--out-schema", default=str(MASTER_SCHEMA))
    parser.add_argument("--manifest", default=str(MASTER_MANIFEST))
    parser.add_argument("--report", default=str(OUT_REPORT))
    parser.add_argument("--report-md", default=str(OUT_REPORT_MD))
    parser.add_argument("--force-rebuild-from-snapshot", action="store_true",
                        help="Force rebuild from snapshot even if applied manual changes exist")
    args = parser.parse_args()
    report = build(args)
    print(
        "master rdb ph0 dry-run: "
        f"tables={report['table_counts']} "
        f"placeholders={report['placeholder_counts']}"
    )


if __name__ == "__main__":
    main()
