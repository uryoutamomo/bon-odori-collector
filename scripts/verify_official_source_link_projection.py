#!/usr/bin/env python3
"""Prove an exporter revision promotes only DB-bound official source links."""
import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

if __package__:
    from . import compare_public_projection_revisions as projection
else:
    import compare_public_projection_revisions as projection


def _canonical(value):
    return projection.canonical_json(value)


def load_review_registry(path):
    payload = projection.load_json(path)
    if not isinstance(payload, dict) or payload.get("schema") != "public_official_source_links_v1":
        raise ValueError("official source registry schema is invalid")
    reviews = payload.get("reviews")
    if not isinstance(reviews, list): raise ValueError("official source registry reviews is invalid")
    indexed = {}
    for row in reviews:
        if not isinstance(row, dict) or not isinstance(row.get("occurrence_id"), str): raise ValueError("official source registry row is invalid")
        key = row["occurrence_id"]
        if key in indexed: raise ValueError("official source registry occurrence is duplicate")
        if not isinstance(row.get("event_year"), int) or not all(isinstance(row.get(k), str) for k in ("date_start", "date_end", "source_url")):
            raise ValueError("official source registry binding is invalid")
        indexed[key] = row
    return indexed


def load_corrections(path):
    payload = projection.load_json(path)
    if not isinstance(payload, dict) or payload.get("schema") != "public_source_kind_corrections_v1" or not isinstance(payload.get("corrections"), list):
        raise ValueError("source kind correction manifest is invalid")
    indexed = {}
    for row in payload["corrections"]:
        required = ("occurrence_id", "event_year", "source_kind", "source_url", "old_source_urls", "new_source_urls", "reason")
        if not isinstance(row, dict) or not all(key in row for key in required) or not isinstance(row["occurrence_id"], str) or isinstance(row["event_year"], bool) or not isinstance(row["event_year"], int) or not isinstance(row["source_kind"], str) or not isinstance(row["source_url"], str) or not isinstance(row["old_source_urls"], list) or not isinstance(row["new_source_urls"], list):
            raise ValueError("source kind correction row is invalid")
        if row["occurrence_id"] in indexed: raise ValueError("source kind correction occurrence is duplicate")
        indexed[row["occurrence_id"]] = row
    return indexed


def _source_rows(database):
    with sqlite3.connect(f"{Path(database).resolve().as_uri()}?mode=ro&immutable=1", uri=True) as connection:
        rows = connection.execute("""
            SELECT occurrence_id, event_year, date_start, date_end, source_kind, source_url
            FROM event_occurrences
        """).fetchall()
    return {row[0]: {"event_year": row[1], "date_start": row[2] or "", "date_end": row[3] or "", "source_kind": row[4], "source_url": row[5]} for row in rows}


def _urls(row):
    value = row.get("source_urls", [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("source_urls must be a list of objects")
    return value


def _primary_official(url):
    return {"label": "公式告知あり", "url": url, "kind": "official"}


def _verify_source_change(old, new, db_source, review, correction):
    old_urls, new_urls = _urls(old), _urls(new)
    if _canonical(old_urls) == _canonical(new_urls):
        return None
    if correction is not None:
        if (correction["event_year"] != db_source["event_year"] or correction["source_kind"] != db_source["source_kind"] or correction["source_url"] != db_source["source_url"]
                or _canonical(correction["old_source_urls"]) != _canonical(old_urls)
                or _canonical(correction["new_source_urls"]) != _canonical(new_urls)):
            raise ValueError("source kind correction does not exactly bind DB and public payload")
        if any(item.get("kind") == "official" for item in new_urls):
            raise ValueError("source kind correction cannot promote official URL")
        return {"old": old_urls, "new": new_urls, "url": db_source["source_url"], "kind": db_source["source_kind"], "replacement": "reviewed_source_kind_correction"}
    if review is None or db_source["source_kind"] != "official_current_year" or db_source["source_url"] != review["source_url"]:
        raise ValueError("source_urls changed without reviewed typed current-year official source")
    if not isinstance(db_source["source_url"], str) or not db_source["source_url"]:
        raise ValueError(f"source_urls changed without typed current-year official source: db={db_source!r} old={old_urls!r} new={new_urls!r}")
    primary = _primary_official(db_source["source_url"])
    if not new_urls or _canonical(new_urls[0]) != _canonical(primary):
        raise ValueError(f"promoted source must be the primary DB official URL: expected={primary!r} actual={new_urls!r}")
    if sum(1 for item in new_urls if item.get("url") == db_source["source_url"] and item.get("kind") == "official") != 1:
        raise ValueError("promoted official URL must appear exactly once")
    # Only replace one pre-existing official button. All non-official evidence
    # remains byte-for-byte as JSON values and in order.
    old_official = [item for item in old_urls if item.get("kind") == "official"]
    if len(old_official) > 1:
        raise ValueError("baseline has multiple official URLs")
    old_other = [item for item in old_urls if item.get("kind") != "official"]
    new_other = [item for item in new_urls if item.get("kind") != "official"]
    replacement = None
    # The exporter can promote an already-listed web URL, or replace its one
    # anonymous count=1 fallback. Everything else must survive verbatim.
    same_url_web = [item for item in old_other if item.get("kind") == "web"
                    and int(item.get("count") or 1) == 1
                    and item.get("url") == db_source["source_url"]]
    if len(same_url_web) == 1:
        old_other.remove(same_url_web[0])
        replacement = "same_url_web"
    elif len(old_other) == 1:
        candidate = old_other[0]
        if (candidate.get("kind") == "web" and int(candidate.get("count") or 1) == 1
                and not candidate.get("url") and len(old_urls) == 1):
            old_other = []
            replacement = "sole_anonymous_web"
    if _canonical(old_other) != _canonical(new_other):
        raise ValueError("source_urls changed non-official evidence")
    if old_official and old_official[0].get("url") == db_source["source_url"]:
        raise ValueError("source_urls changed despite unchanged primary official URL")
    return {"old": old_urls, "new": new_urls, "url": db_source["source_url"], "kind": db_source["source_kind"], "replacement": replacement or "old_official"}


def verify_event_rows(baseline, candidate, source_map, database, reviews=None, corrections=None):
    if len(baseline) != len(candidate):
        raise ValueError("event count changed")
    mapped = source_map.get("rows") if isinstance(source_map, dict) else None
    if not isinstance(mapped, list) or len(mapped) != len(candidate):
        raise ValueError("source map must bind every event row")
    sources = _source_rows(database)
    changes = []
    seen = set()
    for index, (old, new, mapping) in enumerate(zip(baseline, candidate, mapped)):
        if not isinstance(old, dict) or not isinstance(new, dict) or not isinstance(mapping, dict):
            raise ValueError("event and source-map rows must be objects")
        occurrence_id, event_year = mapping.get("occurrence_id"), mapping.get("event_year")
        if not isinstance(occurrence_id, str) or occurrence_id in seen:
            raise ValueError("source map occurrence binding is missing or duplicate")
        seen.add(occurrence_id)
        if (new.get("occurrence_id") != occurrence_id or new.get("event_year") != event_year
                or projection.public_event_key(new) != mapping.get("public_event_key")):
            raise ValueError("public row does not match source-map occurrence binding")
        db_source = sources.get(occurrence_id)
        if not db_source or db_source["event_year"] != event_year:
            raise ValueError("source-map occurrence is not bound to readonly DB")
        old_without, new_without = dict(old), dict(new)
        old_without.pop("source_urls", None); new_without.pop("source_urls", None)
        if _canonical(old_without) != _canonical(new_without):
            raise ValueError("public field other than source_urls changed")
        review = (reviews or {}).get(occurrence_id)
        if review and (review["event_year"] != event_year or review["event_year"] != db_source["event_year"]
                       or review["date_start"] != db_source["date_start"] or review["date_end"] != db_source["date_end"]
                       or review["date_start"] != (new.get("date") or "") or review["date_end"] != (new.get("date_end") or "")):
            raise ValueError(f"review registry does not match public occurrence date: id={occurrence_id}, review={review['date_start']}/{review['date_end']}, db={db_source['date_start']}/{db_source['date_end']}, public={new.get('date')}/{new.get('date_end')}")
        detail = _verify_source_change(old, new, db_source, review, (corrections or {}).get(occurrence_id))
        if detail:
            changes.append({"index": index, "occurrence_id": occurrence_id, "event_year": event_year, **detail})
    return changes


def verify(args):
    repo = args.candidate_repo.resolve()
    bundle = projection.verify_bundle(args.input_bundle, today=args.today, target_year=args.target_year)
    registry_before = projection.sha256(args.official_source_links)
    reviews = load_review_registry(args.official_source_links)
    corrections_before = projection.sha256(args.source_kind_corrections)
    corrections = load_corrections(args.source_kind_corrections)
    baseline_sha = projection.git_revision(repo, args.baseline_revision)
    if baseline_sha != bundle["metadata"]["git_sha"]:
        raise ValueError("baseline revision must match verified bundle metadata")
    cases = []
    with tempfile.TemporaryDirectory(prefix="bonsuke-official-source-links-") as temporary:
        root = Path(temporary); baseline, candidate = root / "baseline", root / "candidate"
        projection.snapshot_baseline(repo, baseline_sha, baseline); projection.snapshot_candidate(repo, candidate)
        checkouts = {"baseline": baseline, "candidate": candidate}; databases = {}; manifests = {}
        for label, checkout in checkouts.items():
            databases[label] = root / label / "private-input" / "bon_odori_master.sqlite"
            manifests[label] = projection.copy_bundle_inputs(args.input_bundle, checkout, databases[label])
        runtime = {label: projection.runtime_source_manifest(checkout) for label, checkout in checkouts.items()}
        def export(label, output, today, year):
            projection.verify_isolated_inputs(checkouts[label], databases[label], manifests[label], bundle["hashes"])
            try: projection.export_once(checkouts[label], output, databases[label], today, year, sys.executable, True)
            finally:
                projection.verify_isolated_inputs(checkouts[label], databases[label], manifests[label], bundle["hashes"])
                if projection.runtime_source_manifest(checkouts[label]) != runtime[label]:
                    raise ValueError("runtime source changed during source-link verification")
        seed = root / "seed"; export("baseline", seed, f"{args.target_year}-01-01", args.target_year)
        matrix = projection.date_matrix(projection.load_json(seed / "events_public.json"), today=args.today, target_year=args.target_year, source_map=projection.load_json(seed / "public_event_source_map.json"))
        for case in matrix:
            outputs = {label: root / "runs" / case["name"] / label for label in checkouts}
            for label, output in outputs.items(): export(label, output, case["today"], case["target_year"])
            old, new = outputs["baseline"], outputs["candidate"]
            for name in ("event_songs_public.json", "public_event_source_map.json"):
                if (old / name).read_bytes() != (new / name).read_bytes(): raise ValueError(f"source-link revision changed {name}")
            source_map = projection.load_json(old / "public_event_source_map.json")
            json_changes = verify_event_rows(projection.load_json(old / "events_public.json"), projection.load_json(new / "events_public.json"), source_map, databases["candidate"], reviews, corrections)
            js_changes = verify_event_rows(projection.parse_javascript_events(old / "events_public.js"), projection.parse_javascript_events(new / "events_public.js"), source_map, databases["candidate"], reviews, corrections)
            if _canonical(json_changes) != _canonical(js_changes): raise ValueError("JSON and JS source URL changes differ")
            cases.append({**case, "status": "pass", "event_count": len(source_map["rows"]), "source_url_changes": json_changes})
            print(f"{case['name']}: pass ({len(json_changes)} source URL changes)", flush=True)
        after = projection.verify_bundle(args.input_bundle, today=args.today, target_year=args.target_year)
        if after["hashes"] != bundle["hashes"]: raise ValueError("verified bundle changed")
        if projection.sha256(args.official_source_links) != registry_before: raise ValueError("official source registry changed during verification")
        if projection.sha256(args.source_kind_corrections) != corrections_before: raise ValueError("source kind correction manifest changed during verification")
        if args.normal_output:
            args.normal_output.mkdir(parents=True, exist_ok=True)
            for name in projection.ARTIFACTS: shutil.copy2(root / "runs" / "normal" / "candidate" / name, args.normal_output / name)
    return {"status": "pass", "contract": "only DB-bound official_current_year source_urls promotions; all other public fields and songs/source-map bytes exact", "baseline_revision": baseline_sha, "candidate_revision": projection.git_revision(repo, "HEAD"), "runtime_python_sha256": {label: projection.manifest_digest(value) for label, value in runtime.items()}, "input_sha256": bundle["hashes"], "official_source_links_sha256": registry_before, "source_kind_corrections_sha256": corrections_before, "matrix": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-bundle", required=True, type=Path); parser.add_argument("--baseline-revision", required=True)
    parser.add_argument("--candidate-repo", required=True, type=Path); parser.add_argument("--today", required=True); parser.add_argument("--target-year", required=True, type=int)
    parser.add_argument("--official-source-links", required=True, type=Path); parser.add_argument("--source-kind-corrections", required=True, type=Path); parser.add_argument("--normal-output", type=Path); parser.add_argument("--out-json", required=True, type=Path)
    args = parser.parse_args()
    try: report = verify(args)
    except (ValueError, projection.ComparisonError) as error:
        print(f"official source-link projection refused: {error}", file=sys.stderr); return 2
    args.out_json.parent.mkdir(parents=True, exist_ok=True); args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n"); return 0

if __name__ == "__main__": raise SystemExit(main())
