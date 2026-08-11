"""Narrow writer for E0 event candidates.

This deliberately does not share the legacy review inbox writer: its columns and
lifecycle rules must never be applied to non-E0 rows.
"""
from __future__ import annotations

import json


E0_COLUMNS = (
    "inbox_id", "kind", "domain", "contract_domain", "contract_lane", "time_scope",
    "priority_label", "priority_score", "title", "event_name", "venue", "event_year",
    "source_id", "source_key", "source_url", "recommended_action", "status",
    "source_payload_hash", "last_seen_at", "payload_json", "created_at", "updated_at",
    "first_eligible_at", "expires_at", "superseded_by_inbox_id", "depends_on_inbox_id",
    "revision_family_key", "revision",
)


def _values(item):
    if item.get("kind") != "event_candidate":
        raise ValueError("event inbox writer accepts only kind='event_candidate'")
    return [json.dumps(item[name], ensure_ascii=False, sort_keys=True, separators=(",", ":")) if name == "payload_json" and not isinstance(item[name], str) else item.get(name) for name in E0_COLUMNS]


def insert_candidate(conn, item):
    """Insert one new candidate, refusing collision with any legacy row."""
    existing = conn.execute("SELECT kind, status FROM review_inbox_items WHERE inbox_id = ?", (item["inbox_id"],)).fetchone()
    if existing:
        raise ValueError(f"inbox_id already exists: {item['inbox_id']}")
    marks = ", ".join("?" for _ in E0_COLUMNS)
    conn.execute(f"INSERT INTO review_inbox_items ({', '.join(E0_COLUMNS)}) VALUES ({marks})", _values(item))


def update_candidate(conn, item, *, last_seen_only=False):
    """Update an unjudged candidate, or only its observed timestamp on a no-op."""
    row = conn.execute("SELECT kind, status FROM review_inbox_items WHERE inbox_id = ?", (item["inbox_id"],)).fetchone()
    if not row or row[0] != "event_candidate" or row[1] != "candidate":
        raise ValueError(f"E0 candidate is not writable: {item['inbox_id']}")
    if last_seen_only:
        conn.execute("UPDATE review_inbox_items SET last_seen_at = ? WHERE inbox_id = ?", (item["last_seen_at"], item["inbox_id"]))
        return
    columns = [name for name in E0_COLUMNS if name not in {"inbox_id", "created_at", "revision_family_key", "revision"}]
    values = {name: value for name, value in zip(E0_COLUMNS, _values(item))}
    conn.execute(
        f"UPDATE review_inbox_items SET {', '.join(f'{name} = ?' for name in columns)} WHERE inbox_id = ?",
        [values[name] for name in columns] + [item["inbox_id"]],
    )


def supersede(conn, old_inbox_id, new_inbox_id):
    row = conn.execute("SELECT superseded_by_inbox_id FROM review_inbox_items WHERE inbox_id = ?", (old_inbox_id,)).fetchone()
    if not row or row[0]:
        raise ValueError(f"revision family is already superseded or missing: {old_inbox_id}")
    conn.execute("UPDATE review_inbox_items SET superseded_by_inbox_id = ? WHERE inbox_id = ?", (new_inbox_id, old_inbox_id))
