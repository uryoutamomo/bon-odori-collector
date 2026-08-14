"""Transactional persistence for validated local judgments."""
from __future__ import annotations

from datetime import datetime, timezone
from master_rdb.master_db import stable_id
from review_inbox_adapters.local_judgment_contract import canonical_json, build_hold_ledger_entry


def _now(): return datetime.now(timezone.utc).isoformat()

def write_decision(conn, decision, *, candidate_ids=None):
    """Write only decision ledgers; domain tables and inbox status stay untouched."""
    # 冪等判定に packet_sha256 は使わない。契約の canonicalize_raw_judgment は decided_at
    # （取り込み時刻）込みでハッシュを作るので、同じ result の再取り込みでも必ず変わる。
    # 比べるのは「同じ判断か」＝ action / actor_id / payload（仕様 v1.3 §5.3）。
    existing = conn.execute("SELECT action, actor_id, payload_json FROM canonical_decision_ledger WHERE decision_id=?", (decision["decision_id"],)).fetchone()
    if existing:
        if tuple(existing) == (decision["action"], decision["actor_id"], canonical_json(decision["payload"])):
            conn.execute("DELETE FROM review_claim_ledger WHERE inbox_id=?", (decision["inbox_id"],))
            return "noop"
        raise ValueError("decision_id_conflict")
    cols = ("decision_id schema_version packet_id packet_sha256 inbox_id domain lane source_id source_key source_payload_hash action queue_state_before queue_state_after reason_code hold_mode next_eligible_at hold_packet_json payload_json actor_type actor_id decision_channel decided_at prior_agent_attempt_id open_hold_id adjudication_batch_id created_at").split()
    def value(column):
        if column == "hold_packet_json":
            return canonical_json(decision["hold_packet"]) if decision.get("hold_packet") is not None else None
        if column == "payload_json":
            return canonical_json(decision["payload"])
        return decision.get(column)
    values = [value(column) for column in cols[:-1]] + [_now()]
    conn.execute(f"INSERT INTO canonical_decision_ledger ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", values)
    conn.execute("INSERT INTO review_queue_state_ledger(inbox_id,domain,lane,queue_state,decision_id,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(inbox_id) DO UPDATE SET domain=excluded.domain,lane=excluded.lane,queue_state=excluded.queue_state,decision_id=excluded.decision_id,updated_at=excluded.updated_at", (decision["inbox_id"],decision["domain"],decision["lane"],decision["queue_state_after"],decision["decision_id"],_now()))
    if decision["action"] == "hold":
        hold = build_hold_ledger_entry(decision, hold_id=stable_id("hold",decision["decision_id"]), reason_detail=decision["payload"].get("reason_detail"), candidate_ids=candidate_ids)
        hcols = list(hold); hvals = [canonical_json(hold[k]) if k in {"allowed_actions","candidate_ids","hold_packet_json"} and hold[k] is not None else hold[k] for k in hcols]
        conn.execute(f"INSERT INTO review_hold_ledger ({','.join(hcols)}) VALUES ({','.join('?' for _ in hcols)})",hvals)
    conn.execute("DELETE FROM review_claim_ledger WHERE inbox_id=?",(decision["inbox_id"],))
    return "written"
