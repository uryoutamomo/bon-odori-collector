#!/usr/bin/env python3
"""Build a public JSON preview for the Ph2 Ebara fifth RDB update.

This is a narrow preview until the full RDB -> public exporter is promoted. It
patches only the reviewed Ebara fifth event and its new venue/geo row into a
separate output directory, then writes a diff summary for review.
"""

import argparse
import json
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from build_ph2_ebara_fifth_venue_plan import (
    EVENT_NAME,
    GEOCODE_MATCHED_TITLE,
    GEOCODE_SOURCE,
    NEW_VENUE_NAME,
)


DATA = Path("data")
PUBLIC = DATA / "public"
OUT_DIR = DATA / "ph2_ebara_fifth_public_preview"
OUT_JSON = DATA / "ph2_ebara_fifth_public_preview.json"
OUT_MD = DATA / "ph2_ebara_fifth_public_preview.md"


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


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def target_from_db(db_path):
    with sqlite3.connect(db_path) as conn:
        result = rows(
            conn,
            """
            SELECT o.display_name, o.date_start, o.date_end, o.date_status,
                   o.confidence, o.source_url,
                   v.venue_id, v.canonical_name AS venue_name, v.area,
                   v.address, v.access, v.scale, v.public_intro,
                   v.latitude, v.longitude
            FROM event_occurrences o
            JOIN venues v ON v.venue_id = o.venue_id
            WHERE o.display_name = ?
              AND o.event_year = 2026
            """,
            (EVENT_NAME,),
        )
    if len(result) != 1:
        raise ValueError(f"expected exactly one target in {db_path}, got {len(result)}")
    return result[0]


def date_note(start, end):
    return f"{start}〜{end}" if end and end != start else start


def patch_event(event, target):
    patched = deepcopy(event)
    for stale_key in (
        "season_confidence",
        "season_hint",
        "season_hint_label",
        "season_jun",
        "season_months",
    ):
        patched.pop(stale_key, None)
    patched.update(
        {
            "venue": target["venue_name"],
            "area": target["area"] or patched.get("area"),
            "months": [int(target["date_start"][5:7])],
            "address": target["address"],
            "lat": target["latitude"],
            "lng": target["longitude"],
            "date": target["date_start"],
            "date_end": target["date_end"] or target["date_start"],
            "status": "確認済み",
            "date_confidence": {
                "level": "confirmed",
                "label": "確認済み",
                "description": "開催日として確認済みです",
            },
            "date_candidates": [],
            "hints": [],
            "jun": {},
            "source_urls": [{"label": "公式告知あり", "url": target["source_url"], "kind": "official"}],
            "public_status": "upcoming_confirmed",
            "public_category": "upcoming",
            "public_status_label": "今後開催",
            "public_note": f"2026年日程確認済み: {date_note(target['date_start'], target['date_end'])}",
            "recurrence_label": "2026年確認済み",
            "recurrence_score": 1.0,
            "recurrence_reasons": ["2026年日付確認済み"],
            "recurrence_cautions": [],
            "display_tier": "confirmed",
        }
    )
    patched["description"] = (
        patched.get("description") or f"{target['venue_name']}を会場に行われる品川区民まつりの地域イベント。"
    ).replace("旧杜松小学校", target["venue_name"])
    patched["detail"] = (
        f"2026年公式情報: {date_note(target['date_start'], target['date_end'])}、"
        f"会場 {target['venue_name']}（{target['address']}）。"
    )
    return patched


def changed_fields(before, after):
    return [key for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)]


def patch_events(events, target):
    patched = deepcopy(events)
    matches = [idx for idx, row in enumerate(patched) if row.get("name") == EVENT_NAME]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one public event named {EVENT_NAME}, got {len(matches)}")
    index = matches[0]
    before = patched[index]
    after = patch_event(before, target)
    patched[index] = after
    return patched, before, after


def patch_venues(venues, target):
    patched = deepcopy(venues)
    existing = [row for row in patched if row.get("name") == target["venue_name"] and row.get("address") == target["address"]]
    created = False
    venue_row = {
        "name": target["venue_name"],
        "area": target["area"],
        "months": [int(target["date_start"][5:7])],
        "scale": target["scale"] or None,
        "access": target["access"] or None,
        "address": target["address"],
        "description": target["public_intro"] or f"{target['venue_name']}は、品川区民まつり荏原第五地区の会場。",
        "lat": target["latitude"],
        "lng": target["longitude"],
    }
    if existing:
        for idx, row in enumerate(patched):
            if row.get("name") == target["venue_name"] and row.get("address") == target["address"]:
                patched[idx] = {**row, **venue_row}
                break
    else:
        patched.append(venue_row)
        created = True
    return patched, venue_row, created


def patch_geo(geo_rows, target):
    patched = deepcopy(geo_rows)
    geo_row = {
        "name": target["venue_name"],
        "area": target["area"],
        "address": target["address"],
        "query": target["address"],
        "source": GEOCODE_SOURCE,
        "lat": target["latitude"],
        "lon": target["longitude"],
        "matched_title": GEOCODE_MATCHED_TITLE,
    }
    existing = [
        idx for idx, row in enumerate(patched)
        if row.get("name") == target["venue_name"] and row.get("address") == target["address"]
    ]
    created = False
    if existing:
        patched[existing[0]] = geo_row
    else:
        patched.append(geo_row)
        created = True
    return patched, geo_row, created


def write_events_js(path, events):
    text = "// Auto-generated Ph2 preview. Do not deploy directly.\n"
    text += "const EVENTS = "
    text += json.dumps(events, ensure_ascii=False, indent=2)
    text += ";\n"
    Path(path).write_text(text, encoding="utf-8")


def render_markdown(result):
    diff = result["event_diff"]
    lines = [
        "# Ph2 Ebara fifth public preview",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- source_db: `{result['sources']['db']}`",
        f"- output_dir: `{result['outputs']['dir']}`",
        f"- event_count_before: {result['summary']['event_count_before']}",
        f"- event_count_after: {result['summary']['event_count_after']}",
        f"- changed_event_count: {result['summary']['changed_event_count']}",
        f"- venue_created: {result['summary']['venue_created']}",
        f"- geo_created: {result['summary']['geo_created']}",
        "",
        "## Event Patch",
        "",
        "| field | before | after |",
        "| --- | --- | --- |",
    ]
    before = diff["before"]
    after = diff["after"]
    for field in diff["changed_fields"]:
        lines.append(f"| {field} | {before.get(field)} | {after.get(field)} |")
    lines.extend(
        [
            "",
            "## Map Pin",
            "",
            f"- venue: {result['geo_row']['name']}",
            f"- address: {result['geo_row']['address']}",
            f"- lat/lon: {result['geo_row']['lat']}, {result['geo_row']['lon']}",
            f"- source: {result['geo_row']['source']} ({result['geo_row']['matched_title']})",
            "",
            "## Guard Notes",
            "",
            "- This preview changes one public event row and appends/updates one venue + one geo row.",
            "- It does not write to `data/public/` and is not a deploy artifact.",
            "- Full public export still needs review before production deploy.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args):
    target = target_from_db(args.db)
    events = load_json(args.events, [])
    venues = load_json(args.venues, [])
    geo = load_json(args.geo, [])
    patched_events, event_before, event_after = patch_events(events, target)
    patched_venues, venue_row, venue_created = patch_venues(venues, target)
    patched_geo, geo_row, geo_created = patch_geo(geo, target)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "events_public.json", patched_events)
    write_events_js(args.out_dir / "events_public.js", patched_events)
    write_json(args.out_dir / "venues_public.json", patched_venues)
    write_json(args.out_dir / "venues_geo.json", patched_geo)

    changed = changed_fields(event_before, event_after)
    result = {
        "generated_by": "build_ph2_ebara_fifth_public_preview.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "db": str(args.db),
            "events": str(args.events),
            "venues": str(args.venues),
            "geo": str(args.geo),
        },
        "outputs": {
            "dir": str(args.out_dir),
            "json": str(args.out_json),
            "markdown": str(args.out_md),
        },
        "summary": {
            "event_count_before": len(events),
            "event_count_after": len(patched_events),
            "changed_event_count": 1,
            "changed_fields_count": len(changed),
            "venue_count_before": len(venues),
            "venue_count_after": len(patched_venues),
            "venue_created": venue_created,
            "geo_count_before": len(geo),
            "geo_count_after": len(patched_geo),
            "geo_created": geo_created,
        },
        "event_diff": {
            "name": EVENT_NAME,
            "changed_fields": changed,
            "before": event_before,
            "after": event_after,
        },
        "venue_row": venue_row,
        "geo_row": geo_row,
        "guard": {
            "wholesale_replacement": False,
            "legacy_song_occurrence_regeneration": False,
            "writes_data_public": False,
        },
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DATA / "ph2_ebara_fifth_apply_dry_run.sqlite")
    parser.add_argument("--events", type=Path, default=PUBLIC / "events_public.json")
    parser.add_argument("--venues", type=Path, default=PUBLIC / "venues_public.json")
    parser.add_argument("--geo", type=Path, default=PUBLIC / "venues_geo.json")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    args = parser.parse_args()
    result = run(args)
    print(
        "ph2 ebara fifth public preview: "
        f"changed_event_count={result['summary']['changed_event_count']} "
        f"venue_created={result['summary']['venue_created']} "
        f"geo_created={result['summary']['geo_created']} "
        f"out={args.out_json}"
    )


if __name__ == "__main__":
    main()
