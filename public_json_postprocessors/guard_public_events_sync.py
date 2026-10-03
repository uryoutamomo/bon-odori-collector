"""Guard public events JSON before any wholesale sync or deploy.

This script is read-only. It compares the raw collector public JSON with the
site public JSON.  It never regenerates historical or season fields: missing
collector values must block wholesale sync until the collector projection is
fixed.
"""

import argparse
import copy
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from public_export_support.occurrence_identity import (
    identity_key, index_events as identity_index_events, legacy_event_key, occurrence_id, event_year, paired_indexes,
)

from public_json_postprocessors.classify_public_events_diff import (
    HIGH_RISK_FIELDS,
    changed_fields,
    classify_diff,
    compact_value,
    event_key,
    field_family,
    recommended_event_action,
    value_side,
)


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
COLLECTOR_EVENTS = DATA / "public" / "events_public.json"
SITE_EVENTS = Path("/Users/ryotauchida/bon-odori-site/data/events_public.json")
FIXED_DATE_RULES = DATA / "public_fixed_date_rules.json"
OUT_JSON = DATA / "public_events_sync_guard.json"
OUT_MD = DATA / "public_events_sync_guard.md"
MASTER_DB = DATA / "bon_odori_master.sqlite"
PUBLICATION_GAP_REVIEW = DATA / "publication_gap_review.json"
REVIEWED_APPROVALS = DATA / "public_sync_exact_approvals.json"
REVIEWED_APPROVALS_SCHEMA = "public_sync_exact_approvals_v1"


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


def full_event_sha256(event):
    """Hash every public field for occurrence-scoped approvals."""
    payload = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonical_event_sha256(event):
    """v1 hash adapter: omit only identity metadata absent from the v1 ledger."""
    return full_event_sha256({key: value for key, value in event.items()
                              if key not in {"occurrence_id", "event_year"}})


def _approval_is_occurrence_scoped(approval):
    return isinstance(approval, dict) and "occurrence_id" in approval


def _approval_hash(event, approval):
    return full_event_sha256(event) if _approval_is_occurrence_scoped(approval) else canonical_event_sha256(event)


def _comparison_positions(collector_rows, site_rows):
    """Return paired identity maps and mutable-site positions without alias overwrite."""
    collector, site = paired_indexes(collector_rows, site_rows)
    original_positions = {id(row): index for index, row in enumerate(site_rows)}
    return collector, {key: original_positions[id(row)] for key, row in site.items()}


def _legacy_unique_key(rows, alias):
    matches = [row for row in rows if legacy_event_key(row) == alias]
    if len(matches) != 1:
        return None
    return identity_key(matches[0])


def _approval_key(approval, legacy_field, identity_field="occurrence_id"):
    """Read an approval selector; v2 selectors are exact stable IDs."""
    if _approval_is_occurrence_scoped(approval):
        value = approval.get(identity_field)
        if not isinstance(value, str):
            return None
        # Reuse public ID validation, including explicitly invalid values.
        occurrence_id({"occurrence_id": value})
        return f"occurrence:{value}"
    value = approval.get(legacy_field)
    return value if isinstance(value, str) and value else None


def _approval_scope(approval, *, arrival=False):
    """Scope lifecycle exemptions to the exact stable occurrence when present."""
    if _approval_is_occurrence_scoped(approval):
        field = "collector_occurrence_id" if arrival and approval.get("kind") == "key_replacement" else "occurrence_id"
        return _approval_key(approval, "collector_event_key" if arrival else "event_key", field)
    if approval.get("kind") == "key_replacement":
        return str(approval.get("collector_event_key") or "") if arrival else ""
    return str(approval.get("event_key") or "")


def parse_iso_date(value):
    """Parse the guard's CLI date without importing a legacy postprocessor."""
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def song_only_stale_approval_warnings(collector_rows, site_rows, payload, results):
    """Explain a current songs-only diff without weakening identity binding."""
    if not isinstance(payload, dict) or payload.get("schema") != REVIEWED_APPROVALS_SCHEMA:
        return []
    approvals = payload.get("approvals")
    if not isinstance(approvals, list) or len(approvals) != len(results):
        return []
    collector_by_alias, site_by_alias = defaultdict(list), defaultdict(list)
    collector_by_id, site_by_id = defaultdict(list), defaultdict(list)
    for row in collector_rows:
        collector_by_alias[event_key(row)].append(row)
        identifier = occurrence_id(row)
        if identifier is not None:
            collector_by_id[identifier].append(row)
    for row in site_rows:
        site_by_alias[event_key(row)].append(row)
        identifier = occurrence_id(row)
        if identifier is not None:
            site_by_id[identifier].append(row)

    warnings = []
    for approval, result in zip(approvals, results):
        if not isinstance(approval, dict) or result.get("status") != "hash_mismatch":
            continue
        if (not isinstance(approval.get("id"), str) or not approval["id"].strip()
                or result.get("id") != approval["id"]):
            continue
        if not all(isinstance(approval.get(field), str) and len(approval[field]) == 64
                   and all(char in "0123456789abcdef" for char in approval[field])
                   for field in ("site_sha256", "collector_sha256")):
            continue
        kind = approval.get("kind")
        v2 = _approval_is_occurrence_scoped(approval)
        if v2:
            # New approvals never fall back to a display alias. A wrong ID
            # remains a blocking hash mismatch even if a real alias is songs-only.
            try:
                identifier = occurrence_id({"occurrence_id": approval.get("occurrence_id")})
            except ValueError:
                continue
            if kind == "key_replacement":
                continue  # replacement IDs are distinct selectors; no songs exemption.
            if kind != "same_key_update":
                continue
            candidates_left, candidates_right = collector_by_id[identifier], site_by_id[identifier]
            key = f"occurrence:{identifier}"
        else:
            if kind == "same_key_update":
                key = approval.get("event_key")
            elif kind == "key_replacement":
                key = approval.get("collector_event_key")
                old_key = approval.get("site_event_key")
                if (not isinstance(old_key, str) or not old_key or old_key == key
                        or collector_by_alias.get(old_key) or site_by_alias.get(old_key)):
                    continue
            else:
                continue
            if not isinstance(key, str) or not key:
                continue
            candidates_left, candidates_right = collector_by_alias[key], site_by_alias[key]
        if len(candidates_left) != 1 or len(candidates_right) != 1:
            continue
        collector, site = candidates_left[0], candidates_right[0]
        if v2 and (occurrence_id(collector) != identifier or occurrence_id(site) != identifier
                   or event_year(collector) != event_year(site)):
            continue
        if not isinstance(collector.get("songs"), list) or not isinstance(site.get("songs"), list):
            continue
        hasher = full_event_sha256 if v2 else canonical_event_sha256
        collector_hash, site_hash = hasher(collector), hasher(site)
        if collector_hash == site_hash:
            continue
        left_without_songs = {k: v for k, v in collector.items() if k != "songs"}
        right_without_songs = {k: v for k, v in site.items() if k != "songs"}
        if hasher(left_without_songs) != hasher(right_without_songs):
            continue
        warnings.append({"id": result["id"], "kind": kind, "event_key": key,
            "reason": "current_event_diff_is_songs_only", "changed_fields": ["songs"],
            "raw_collector_sha256": collector_hash, "raw_site_sha256": site_hash})
    return warnings


def mark_superseded_same_key_approvals(results, approvals):
    """Retire an older exact approval after a later approved value reached site.

    Approval manifests are append-only, so one event can have a chain such as
    A -> B -> C.  Once C is live, the A -> B entry no longer matches either
    current payload.  That is expected history, not unreviewed drift.  Only a
    later, value-pinned same-key approval whose reviewed event key and site
    hash equal the older approval's arrival key and hash may supersede it.  A
    key replacement arrives at ``collector_event_key`` instead of
    ``event_key``; that is the only extra case handled here.  The latest
    collector-vs-site drift is still left to the normal high-risk classifier.
    """
    proven_successors = {}
    safe_statuses = {
        "applied",
        "consumed_at_site",
        "already_synced",
        "retired_after_ended_transition",
        "retired_after_expired_slide",
        "superseded",
    }

    for index in range(len(results) - 1, -1, -1):
        approval = approvals[index] if index < len(approvals) else None
        result = results[index]
        if not isinstance(approval, dict):
            continue

        kind = approval.get("kind")
        if kind == "same_key_update":
            event_key_value = _approval_scope(approval)
            arrival_key = _approval_scope(approval, arrival=True)
        elif kind == "key_replacement":
            event_key_value = ""
            arrival_key = _approval_scope(approval, arrival=True)
        else:
            continue

        site_hash = str(approval.get("site_sha256") or "")
        arrival_hash = str(approval.get("collector_sha256") or "")
        if (
            result.get("status") == "hash_mismatch"
            and arrival_key
            and arrival_hash
        ):
            successor_id = proven_successors.get((arrival_key, arrival_hash))
            if successor_id:
                result["status"] = "superseded"
                result["superseded_by"] = successor_id

        if result.get("status") in safe_statuses and event_key_value and site_hash:
            proven_successors[(event_key_value, site_hash)] = result.get("id")


def mark_retired_temporal_approvals(
    results, approvals, ended_transition_event_keys, expired_slide_event_keys
):
    """Retire only the latest stale approval for each proven time-only change.

    The current collector/site payload comparison is the safety boundary: the
    caller supplies ended events and independently verified expired slides.
    Retiring the newest matching approval lets the existing hash-linked
    successor logic supersede older history. Unlinked older approvals remain
    ``hash_mismatch`` and keep the guard closed.
    """
    pending_keys = {
        key: "ended_transition_downgrade"
        for key in (ended_transition_event_keys or ())
    }
    pending_keys.update({
        key: "expired_historical_slide_downgrade"
        for key in (expired_slide_event_keys or ())
    })
    if not pending_keys:
        return

    for index in range(len(results) - 1, -1, -1):
        approval = approvals[index] if index < len(approvals) else None
        result = results[index]
        if not isinstance(approval, dict) or result.get("status") != "hash_mismatch":
            continue

        kind = approval.get("kind")
        if kind in {"same_key_update", "key_replacement"}:
            arrival_key = _approval_scope(approval, arrival=True)
        else:
            continue

        if arrival_key not in pending_keys:
            continue
        if pending_keys[arrival_key] == "expired_historical_slide_downgrade" and not all(
            isinstance(approval.get(field), str)
            and len(approval[field]) == 64
            and all(char in "0123456789abcdef" for char in approval[field])
            for field in ("site_sha256", "collector_sha256")
        ):
            continue
        action = pending_keys.pop(arrival_key)
        result["status"] = (
            "retired_after_expired_slide"
            if action == "expired_historical_slide_downgrade"
            else "retired_after_ended_transition"
        )
        result["retired_by"] = action


def verified_expired_slide_keys(collector_rows, site_rows, classified, today):
    """Allow stale approval retirement only for an expired, content-identical slide.

    The normal classifier recognizes a historical-slide downgrade but does not
    check the date or all public fields. Those extra checks are required before
    retiring a value-pinned approval whose old hash no longer matches.
    """
    collector, site = paired_indexes(collector_rows, site_rows)
    allowed_fields = {
        "date_certainty_tier", "display_tier", "historical_display_tier",
        "historical_reference", "historical_slide", "historical_slide_basis",
        "historical_slide_date", "historical_slide_date_end",
        "historical_slide_method", "predicted_date", "predicted_date_end",
        "prediction_basis", "prediction_confidence",
    }
    verified = set()
    for row in classified["event_rows"]:
        if row["recommended_action"] != "expired_historical_slide_downgrade":
            continue
        key = row.get("identity_key", row["event_key"])
        left, right = collector.get(key), site.get(key)
        if not left or not right:
            continue
        if any(left.get(field) != right.get(field)
               for field in set(left) | set(right) if field not in allowed_fields):
            continue
        left_ref, right_ref = left.get("historical_reference"), right.get("historical_reference")
        if not isinstance(left_ref, dict) or not isinstance(right_ref, dict):
            continue
        if ({k: v for k, v in left_ref.items() if k not in {"display_tier", "slide"}}
                != {k: v for k, v in right_ref.items() if k not in {"display_tier", "slide"}}):
            continue
        slide = right.get("historical_slide") or right_ref.get("slide")
        if (not isinstance(slide, dict) or left.get("historical_slide")
                or left_ref.get("slide")):
            continue
        if right.get("historical_slide") and right_ref.get("slide") != slide:
            continue
        end_date = parse_iso_date(slide.get("date_end") or slide.get("date"))
        if (not end_date or end_date >= today
                or right_ref.get("display_tier") != "historical_slide"
                or left_ref.get("display_tier") != "historical_reference"):
            continue
        if any(
            (left.get(field) not in (None, "historical_reference")
             or right.get(field) not in (None, "historical_slide"))
            for field in ("display_tier", "historical_display_tier", "date_certainty_tier")
        ):
            continue
        verified.add(key)
    return verified


def apply_reviewed_exact_approvals(
    collector_rows, site_rows, payload, *, ended_transition_event_keys=None,
    expired_slide_event_keys=None,
):
    """Apply exact approvals to a private comparison copy.

    v1 uses a legacy name/venue alias only while it is unique on both sides.
    An approval with ``occurrence_id`` is v2 and binds that exact occurrence
    with a full-row hash, so it cannot cross a year or a same-name occurrence.
    """
    approved_site_rows = copy.deepcopy(site_rows)
    results, seen_ids = [], set()
    schema = payload.get("schema") if isinstance(payload, dict) else None
    approvals = payload.get("approvals") if isinstance(payload, dict) else None
    if schema != REVIEWED_APPROVALS_SCHEMA or not isinstance(approvals, list):
        return {"site_rows": approved_site_rows, "summary": {"schema": schema, "status": "block", "approval_count": 0, "status_counts": {"invalid_manifest": 1}, "failure_count": 1, "results": [{"id": "manifest", "kind": "manifest", "status": "invalid_manifest"}]}}

    def maps():
        return _comparison_positions(collector_rows, approved_site_rows)

    for approval in approvals:
        approval_id = str(approval.get("id") or "") if isinstance(approval, dict) else ""
        kind = approval.get("kind") if isinstance(approval, dict) else None
        result = {"id": approval_id, "kind": kind}
        if not approval_id or approval_id in seen_ids or kind not in {"same_key_update", "key_replacement", "removal", "addition"}:
            result["status"] = "invalid_approval"; results.append(result); continue
        seen_ids.add(approval_id)
        try:
            collector, positions = maps()
        except ValueError:
            result["status"] = "invalid_approval"; results.append(result); continue
        v2 = _approval_is_occurrence_scoped(approval)
        try:
            if kind in {"addition", "removal", "same_key_update"}:
                selector = _approval_key(approval, "event_key")
                result["event_key"] = approval.get("event_key") if not v2 else selector
                if selector is None:
                    raise ValueError("missing selector")
                if not v2:
                    # v1 is only safe for an actual pair, except old all-legacy
                    # addition/removal fixtures where the selected one side has no ID.
                    ckey = _legacy_unique_key(collector_rows, selector)
                    skey = _legacy_unique_key(approved_site_rows, selector)
                    if ckey and skey and ckey != skey:
                        # paired_indexes only aliases a unique ID-to-legacy
                        # migration. Existing differing IDs never share this
                        # comparison key.
                        if ckey in collector and ckey in positions:
                            key = ckey
                        else:
                            raise ValueError("legacy selector spans identities")
                    else:
                        key = ckey or skey
                    if ckey and skey and ckey == skey and ckey.startswith("occurrence:"):
                        collector_match = next(row for row in collector_rows if identity_key(row) == ckey)
                        site_match = next(row for row in approved_site_rows if identity_key(row) == skey)
                        if event_year(collector_match) != event_year(site_match):
                            raise ValueError("v1 approval cannot change event_year for an identified occurrence")
                    if key is None:
                        if kind in {"addition", "removal"}:
                            result["status"] = "inactive"; results.append(result); continue
                        raise ValueError("ambiguous legacy selector")
                    if (ckey or skey).startswith("occurrence:") and not (ckey and skey):
                        raise ValueError("v1 selector cannot approve identified one-sided row")
                else:
                    key = selector
                collector_event = collector.get(key)
                site_index = positions.get(key)
                site_event = approved_site_rows[site_index] if site_index is not None else None
                if v2 and collector_event is None and site_event is None:
                    # A stable-ID approval must name an extant occurrence; an
                    # unknown ID is never treated as harmless legacy history.
                    result["status"] = "hash_mismatch"
                elif kind == "addition":
                    if collector_event is None:
                        result["status"] = "inactive"
                    elif site_event is not None:
                        ch, sh = _approval_hash(collector_event, approval), _approval_hash(site_event, approval)
                        result.update(actual_collector_sha256=ch, actual_site_sha256=sh)
                        result["status"] = "already_synced" if ch == sh else "already_applied"
                    else:
                        ch = _approval_hash(collector_event, approval); result["actual_collector_sha256"] = ch
                        if ch == approval.get("collector_sha256"):
                            approved_site_rows.append(copy.deepcopy(collector_event)); result["status"] = "applied"
                        else: result["status"] = "hash_mismatch"
                elif kind == "removal":
                    if collector_event is not None: result["status"] = "hash_mismatch"
                    elif site_event is None: result["status"] = "inactive"
                    else:
                        sh = _approval_hash(site_event, approval); result["actual_site_sha256"] = sh
                        if sh == approval.get("site_sha256"):
                            del approved_site_rows[site_index]; result["status"] = "applied"
                        else: result["status"] = "hash_mismatch"
                else:  # same_key_update
                    if collector_event is None and site_event is None: result["status"] = "inactive"
                    elif collector_event is None or site_event is None: result["status"] = "hash_mismatch"
                    else:
                        ch, sh = _approval_hash(collector_event, approval), _approval_hash(site_event, approval)
                        result.update(actual_collector_sha256=ch, actual_site_sha256=sh)
                        if ch == sh: result["status"] = "already_synced"
                        elif sh == approval.get("site_sha256") and ch == approval.get("collector_sha256"):
                            approved_site_rows[site_index] = copy.deepcopy(collector_event); result["status"] = "applied"
                        elif sh == approval.get("collector_sha256"): result["status"] = "consumed_at_site"
                        else: result["status"] = "hash_mismatch"
            else:
                if v2:
                    site_key = _approval_key(approval, "site_event_key", "site_occurrence_id")
                    collector_key = _approval_key(approval, "collector_event_key", "collector_occurrence_id")
                else:
                    site_alias, collector_alias = approval.get("site_event_key"), approval.get("collector_event_key")
                    if not isinstance(site_alias, str) or not isinstance(collector_alias, str): raise ValueError("missing selector")
                    # A v1 rename may already have removed the old alias.  The
                    # arrival alias must still uniquely identify the current row.
                    collector_key = _legacy_unique_key(collector_rows, collector_alias)
                    site_key = _legacy_unique_key(approved_site_rows, site_alias)
                    if collector_key is None: raise ValueError("ambiguous collector selector")
                if not collector_key: raise ValueError("ambiguous selector")
                result.update(site_event_key=site_key or approval.get("site_event_key"), collector_event_key=collector_key)
                collector_event = collector.get(collector_key)
                old_index, new_index = positions.get(site_key), positions.get(collector_key)
                old_event = approved_site_rows[old_index] if old_index is not None else None
                new_event = approved_site_rows[new_index] if new_index is not None else None
                if collector_event is None and old_event is None and new_event is None:
                    result["status"] = "hash_mismatch" if v2 else "inactive"
                elif collector_event is not None and old_event is None and new_event is not None:
                    ch, sh = _approval_hash(collector_event, approval), _approval_hash(new_event, approval); result.update(actual_collector_sha256=ch, actual_site_sha256=sh)
                    result["status"] = "already_synced" if ch == sh else ("consumed_at_site" if sh == approval.get("collector_sha256") else "hash_mismatch")
                elif collector_event is not None and old_event is not None and new_event is None:
                    ch, sh = _approval_hash(collector_event, approval), _approval_hash(old_event, approval); result.update(actual_collector_sha256=ch, actual_site_sha256=sh)
                    if sh == approval.get("site_sha256") and ch == approval.get("collector_sha256"):
                        approved_site_rows[old_index] = copy.deepcopy(collector_event); result["status"] = "applied"
                    else: result["status"] = "hash_mismatch"
                else: result["status"] = "hash_mismatch"
        except (TypeError, ValueError):
            result["status"] = "invalid_approval"
        results.append(result)

    mark_superseded_same_key_approvals(results, approvals)
    mark_retired_temporal_approvals(results, approvals, ended_transition_event_keys, expired_slide_event_keys)
    mark_superseded_same_key_approvals(results, approvals)
    status_counts = dict(Counter(result["status"] for result in results))
    failure_count = sum(count for status, count in status_counts.items() if status in {"invalid_approval", "hash_mismatch"})
    return {"site_rows": approved_site_rows, "summary": {"schema": schema, "status": "pass" if failure_count == 0 else "block", "approval_count": len(approvals), "status_counts": status_counts, "failure_count": failure_count, "results": results}}


def file_mtime(path):
    path = Path(path)
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def flow_artifact_warnings(master_db, publication_gap_review, collector_events):
    """Warn when the public-event flow appears to have skipped a review step."""
    warnings = []
    master_mtime = file_mtime(master_db)
    gap_mtime = file_mtime(publication_gap_review)
    collector_mtime = file_mtime(collector_events)

    if master_mtime is None:
        warnings.append("missing_master_rdb")
        return warnings
    if gap_mtime is None:
        warnings.append("missing_publication_gap_review")
    elif gap_mtime < master_mtime:
        warnings.append("master_rdb_newer_than_publication_gap_review")

    if collector_mtime is None:
        warnings.append("missing_collector_public_events")
    elif collector_mtime < master_mtime:
        warnings.append("master_rdb_newer_than_public_export")
    return warnings


def classify_rows(collector_rows, site_rows, today=None):
    try:
        collector, site = paired_indexes(collector_rows, site_rows)
    except ValueError:
        # Preserve a report and close the guard when malformed identities are
        # supplied; never select one duplicate by dict overwrite.
        return {"summary": {"collector_event_count": len(collector_rows), "site_event_count": len(site_rows),
            "collector_only_count": len(collector_rows), "site_only_count": len(site_rows),
            "high_risk_diff_record_count": 0, "high_risk_event_count": 0,
            "records_by_family": {}, "records_by_action": {}, "events_by_action": {}},
            "event_rows": [], "records": []}
    records = []
    for key in sorted(set(collector) & set(site)):
        left, right = collector[key], site[key]
        for field in changed_fields(left, right):
            if field not in HIGH_RISK_FIELDS:
                continue
            # A site snapshot that predates public identity metadata is a
            # permitted one-to-one migration, not a content approval.
            if field in {"occurrence_id", "event_year"} and (occurrence_id(left) is None) != (occurrence_id(right) is None):
                continue
            records.append({"event_key": event_key(left), "identity_key": key,
                "event_name": left.get("name") or right.get("name") or "", "venue": left.get("venue") or right.get("venue") or "",
                "field": field, "family": field_family(field), "side": value_side(left.get(field), right.get(field)),
                "recommended_action": classify_diff(field, left.get(field), right.get(field)),
                "collector_value": compact_value(left.get(field)), "site_value": compact_value(right.get(field))})
    grouped = defaultdict(lambda: {"fields": [], "families": set(), "actions": Counter(), "records": []})
    for record in records:
        item = grouped[record["identity_key"]]; item["fields"].append(record["field"]); item["families"].add(record["family"]); item["actions"][record["recommended_action"]] += 1; item["records"].append(record)
    event_rows = []
    for key, item in grouped.items():
        sample = item["records"][0]
        action = recommended_event_action(item["actions"], item["records"], collector[key], site[key], today)
        event_rows.append({"event_key": sample["event_key"], "identity_key": key, "event_name": sample["event_name"], "venue": sample["venue"],
            "recommended_action": action, "families": sorted(item["families"]), "field_count": len(item["fields"]), "fields": sorted(item["fields"]), "actions": dict(item["actions"]),
            "ended_transition_end_date": (collector[key].get("date_end") or collector[key].get("date")) if action == "ended_transition_downgrade" else None})
    return {"summary": {"collector_event_count": len(collector_rows), "site_event_count": len(site_rows),
        "collector_only_count": len(set(collector) - set(site)), "site_only_count": len(set(site) - set(collector)),
        "high_risk_diff_record_count": len(records), "high_risk_event_count": len(event_rows),
        "records_by_family": dict(Counter(record["family"] for record in records)), "records_by_action": dict(Counter(record["recommended_action"] for record in records)),
        "events_by_action": dict(Counter(row["recommended_action"] for row in event_rows))},
        "event_rows": sorted(event_rows, key=lambda row: (row["recommended_action"], row["event_name"], row["venue"], row["identity_key"])), "records": records}


def guard_decision(raw, classified, allow_individual_review, approval_summary=None,
                   *, collector_rows=None, site_rows=None, approval_payload=None):
    failures = []
    warnings = []
    song_warnings = []
    classified_summary = classified["summary"]
    if classified_summary["collector_event_count"] != classified_summary["site_event_count"]:
        failures.append("event_count_mismatch")
    if classified_summary["collector_only_count"] or classified_summary["site_only_count"]:
        failures.append("event_key_mismatch")

    actions = classified_summary.get("events_by_action") or {}
    restore_count = actions.get("restore_collector_from_site_or_reenable_export_postprocess", 0)
    individual_count = actions.get("individual_review", 0)
    site_update_count = actions.get("site_update_candidate_after_review", 0)
    if restore_count:
        failures.append("collector_restore_candidates_remain")
    if individual_count and not allow_individual_review:
        failures.append("individual_review_diffs_remain")
    if site_update_count and not allow_individual_review:
        failures.append("site_update_candidates_remain")
    if approval_summary and approval_summary.get("failure_count"):
        # Only mismatches individually proven against the original rows may
        # become warnings. Other events' normal transitions do not affect this
        # decision, and invalid approvals remain failures even with zero diffs.
        if collector_rows is not None and site_rows is not None:
            song_warnings = song_only_stale_approval_warnings(
                collector_rows, site_rows, approval_payload,
                approval_summary.get("results", []),
            )
        if song_warnings:
            warnings.append("stale_reviewed_approval_hashes_songs_only")
        if approval_summary["failure_count"] != len(song_warnings):
            failures.append("reviewed_exact_approval_mismatch")

    status = "pass" if not failures else "block"
    deploy_note = (
        "Guard pass only means no blocking public sync diffs remain. "
        "Public deploy still requires separate operator approval."
    )
    return {
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "song_only_approval_warnings": song_warnings,
        "safe_to_wholesale_sync": status == "pass",
        "public_deploy_requires_separate_approval": True,
        "deploy_approval_note": deploy_note,
    }


def build(args):
    collector_events = load_json(args.collector_events, [])
    site_events = load_json(args.site_events, [])
    today = parse_iso_date(args.today)
    if not today:
        raise SystemExit(f"invalid --today: {args.today}")

    raw = classify_rows(collector_events, site_events, today=today)
    reviewed_approvals_payload = load_json(args.reviewed_approvals, {})
    reviewed = apply_reviewed_exact_approvals(
        collector_events,
        site_events,
        reviewed_approvals_payload,
        ended_transition_event_keys={
            row.get("identity_key", row["event_key"])
            for row in raw["event_rows"]
            if row["recommended_action"] == "ended_transition_downgrade"
        },
        expired_slide_event_keys=(
            verified_expired_slide_keys(collector_events, site_events, raw, today)
            if raw["event_rows"] else set()
        ),
    )
    approved = classify_rows(collector_events, reviewed["site_rows"], today=today)
    decision = guard_decision(
        raw,
        approved,
        args.allow_individual_review,
        approval_summary=reviewed["summary"],
        collector_rows=collector_events,
        site_rows=site_events,
        approval_payload=reviewed_approvals_payload,
    )
    procedure_warnings = flow_artifact_warnings(
        args.master_db,
        args.publication_gap_review,
        args.collector_events,
    )
    decision["warnings"] = [*decision["warnings"], *procedure_warnings]

    data = {
        "generated_by": "guard_public_events_sync.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_public_sync_guard_no_writes",
        "sources": {
            "collector_events": str(args.collector_events),
            "site_events": str(args.site_events),
            "deprecated_ignored_fixed_date_rules": str(args.fixed_date_rules),
            "master_db": str(args.master_db),
            "publication_gap_review": str(args.publication_gap_review),
            "reviewed_approvals": str(args.reviewed_approvals),
        },
        "parameters": {
            "target_year": args.target_year,
            "today": args.today,
            "allow_individual_review": bool(args.allow_individual_review),
            "deprecated_fixed_date_rules_ignored": True,
        },
        "decision": decision,
        "procedure_warnings": procedure_warnings,
        "raw_classification": raw["summary"],
        # Kept for report consumers during the R2 transition. It is exactly
        # the raw classification because this guard no longer postprocesses.
        "postprocessed_classification": raw["summary"],
        "postprocessed_classification_deprecated": True,
        "reviewed_exact_approvals": reviewed["summary"],
        "approved_classification": approved["summary"],
        "ended_transition_downgrades": [
            {
                "event_name": row["event_name"],
                "venue": row["venue"],
                "ended_on": row["ended_transition_end_date"],
            }
            for row in approved["event_rows"]
            if row["recommended_action"] == "ended_transition_downgrade"
        ],
        "blocking_examples": [
            row
            for row in approved["event_rows"]
            if row["recommended_action"]
            in {
                "individual_review",
                "site_update_candidate_after_review",
                "restore_collector_from_site_or_reenable_export_postprocess",
            }
        ][:40],
    }
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")
    return data


def render_markdown(data):
    lines = [
        "# Public events sync guard",
        "",
        "**Note**: This guard checks for blocking diffs only. Guard status `pass` means no blocking issues remain, but is NOT a deploy approval. Deploy decisions require explicit confirmation from the operator.",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- scope: {data['scope']}",
        f"- status: {data['decision']['status']}",
        f"- safe_to_wholesale_sync: {data['decision']['safe_to_wholesale_sync']}",
        f"- public_deploy_requires_separate_approval: {data['decision']['public_deploy_requires_separate_approval']}",
        f"- deploy_approval_note: {data['decision']['deploy_approval_note']}",
        f"- failures: {data['decision']['failures']}",
        f"- warnings: {data['decision']['warnings']}",
        f"- procedure_warnings: {data['procedure_warnings']}",
        "",
        "## Procedure Warnings",
        "",
        "These warnings mean the public-event publication flow may have skipped a review step. They do not automatically approve or reject deploys; they should be resolved or consciously accepted before syncing/deploying.",
        "",
    ]
    if data["procedure_warnings"]:
        for warning in data["procedure_warnings"]:
            lines.append(f"- {warning}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Raw Collector vs Site",
            "",
        ]
    )
    for key, value in data["raw_classification"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Deprecated Postprocessor Compatibility View", ""])
    lines.append("- This is the raw collector classification. No historical, season, or display-tier postprocessor runs in this guard.")
    for key, value in data["postprocessed_classification"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Reviewed Exact Approvals", ""])
    approval_summary = data["reviewed_exact_approvals"]
    for key in ["schema", "status", "approval_count", "status_counts", "failure_count"]:
        lines.append(f"- {key}: {approval_summary.get(key)}")
    song_warnings = data["decision"]["song_only_approval_warnings"]
    lines.append(f"- current_songs_only_warning_count: {len(song_warnings)}")
    for warning in song_warnings:
        lines.append(f"  - {warning['id']}: {warning['event_key']} ({warning['reason']})")
    lines.extend(["", "## After Reviewed Exact Approvals", ""])
    for key, value in data["approved_classification"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Automatically Allowed Ended Transitions", ""])
    ended_transitions = data["ended_transition_downgrades"]
    lines.append(f"- count: {len(ended_transitions)}")
    if ended_transitions:
        lines.extend(["", "| event | venue | ended on |", "| --- | --- | --- |"])
        for row in ended_transitions:
            lines.append(f"| {row['event_name']} | {row['venue']} | {row['ended_on']} |")
    lines.extend(
        [
            "",
            "## Blocking Examples",
            "",
            "| action | event | venue | families | fields |",
            "| --- | --- | --- | --- | ---: |",
        ]
    )
    for row in data["blocking_examples"]:
        lines.append(
            f"| {row['recommended_action']} | {row['event_name']} | {row['venue']} | "
            f"{', '.join(row['families'])} | {row['field_count']} |"
        )
    lines.append("")
    return "\n".join(lines)


def append_github_summary(markdown_path, explicit_path=None):
    target = explicit_path or os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return None
    markdown_path = Path(markdown_path)
    if not markdown_path.exists():
        return None
    summary_path = Path(target)
    with summary_path.open("a", encoding="utf-8") as handle:
        handle.write("\n\n")
        handle.write(markdown_path.read_text(encoding="utf-8"))
        handle.write("\n")
    return str(summary_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector-events", default=str(COLLECTOR_EVENTS))
    parser.add_argument("--site-events", default=str(SITE_EVENTS))
    parser.add_argument(
        "--fixed-date-rules",
        default=str(FIXED_DATE_RULES),
        help="deprecated compatibility option; ignored because the guard compares raw collector JSON",
    )
    parser.add_argument("--master-db", default=str(MASTER_DB))
    parser.add_argument("--publication-gap-review", default=str(PUBLICATION_GAP_REVIEW))
    parser.add_argument("--reviewed-approvals", default=str(REVIEWED_APPROVALS))
    parser.add_argument("--target-year", type=int, required=True)
    parser.add_argument("--today", required=True)
    parser.add_argument("--allow-individual-review", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    parser.add_argument("--append-github-summary", action="store_true")
    parser.add_argument("--github-summary")
    args = parser.parse_args()
    try:
        source_rows = load_json(args.collector_events, [])
        identity_index_events(source_rows, require_identity=True)
    except (TypeError, ValueError) as error:
        parser.error(f"invalid production occurrence identity: {error}")
    data = build(args)
    summary_path = None
    if args.append_github_summary or args.github_summary:
        summary_path = append_github_summary(args.out_md, args.github_summary)
    print(
        "public events sync guard: "
        f"status={data['decision']['status']} "
        f"failures={data['decision']['failures']} "
        f"warnings={data['decision']['warnings']} "
        f"approved_actions={data['approved_classification']['events_by_action']}"
    )
    if summary_path:
        print(f"github_summary={summary_path}")
    if data["decision"]["status"] != "pass" and not args.report_only:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
