#!/usr/bin/env python3
"""Apply console-recorded user adjudications through the J0 ledger writer only."""
from __future__ import annotations
import argparse, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

from event_model.local_judgment_migration import migrate_event_inbox_candidate, migrate_local_judgment_contract, migrate_review_claim_ledger
from master_rdb.master_db import MASTER_DB, connect_existing
from operation_safety.manual_apply_guards import require_confirmation
from report_apply.rdb_apply_support import copy_db
from review_console.data import ADJUDICATIONS_PATH, load_adjudications, write_json_atomic
from review_inbox_adapters.judgment_ledger_writer import write_decision
from review_inbox_adapters.local_judgment_contract import ContractError, build_user_decision, canonicalize_raw_judgment

APPLY_USER_ADJUDICATIONS_CONFIRMATION = "APPLY USER ADJUDICATIONS"
REQUIRED = {"canonical_decision_ledger", "review_queue_state_ledger", "review_hold_ledger", "review_claim_ledger"}
MIGRATIONS = ["local_judgment_contract_v1", "event_inbox_candidate_v1", "review_claim_ledger_v1"]

def _now(): return datetime.now(timezone.utc).isoformat()
def _json(value, default):
    try: return json.loads(value) if value else default
    except (TypeError, ValueError): return default

def _migrate(conn):
    migrate_local_judgment_contract(conn); migrate_event_inbox_candidate(conn); migrate_review_claim_ledger(conn)

def _invalidate(row, reason):
    row.update(status="invalidated", invalidated_at=_now(), invalid_reason=reason)

def _validate(hold, entry):
    """Return the failing reason code, or None. Order follows spec v1.2 §5.3."""
    if not hold or hold["status"] != "open" or hold["hold_mode"] != "awaiting_user": return "hold_not_open"
    if hold["inbox_id"] != entry.get("inbox_id"): return "inbox_mismatch"
    if hold["candidate_set_sha256"] != entry.get("candidate_set_sha256"): return "candidate_set_changed"
    if entry.get("action") not in _json(hold["allowed_actions"], []): return "action_not_allowed"
    if hold["expires_at"] and datetime.fromisoformat(hold["expires_at"].replace("Z", "+00:00")) <= datetime.now(timezone.utc): return "hold_expired"
    # 対象IDは凍結された候補集合の中からしか選べない。空集合の hold に対象IDが付いていたら、
    # 画面の外で作られた対象なので通さない（仕様 v1.2 §5.3-6）。
    candidates = _json(hold["candidate_ids"], []) or []
    target = entry.get("target_id")
    if entry.get("action") == "accept" and candidates and not target: return "missing_target_id"
    if target and target not in candidates: return "target_not_in_candidate_set"
    return None

def run(args):
    if not args.actor_id: raise ValueError("actor_id is required")
    if args.apply: require_confirmation(True, args.confirm, APPLY_USER_ADJUDICATIONS_CONFIRMATION, "apply_user_adjudications.py --apply")
    db=Path(args.db); target=db if args.apply else Path(args.out_db)
    if not args.apply:
        if target.resolve()==db.resolve(): raise ValueError("dry-run target must differ from --db")
        copy_db(db,target)
    payload=load_adjudications(Path(args.adjudications)); rows=payload["adjudications"]
    report={"applied":0,"noop":0,"invalidated":0,"issues":[],"entries":[],"migrations_applied":[],"claim_scope":"production" if args.apply else "dry_run_copy"}
    with connect_existing(target) as conn:
        conn.row_factory=sqlite3.Row
        # dry-run のコピーにだけ migration を当てる。本番DBにはJ0の台帳がまだ無いので、
        # ここを省くと実データでの dry-run が一度もできない（仕様 v1.2 §5.4）。
        if not args.apply and not args.no_auto_migrate:
            _migrate(conn); conn.commit(); report["migrations_applied"]=list(MIGRATIONS)
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED <= tables: raise ValueError("judgment_ledger_missing")
        for entry in rows:
            if entry.get("status") != "pending": continue
            hold=conn.execute("SELECT * FROM review_hold_ledger WHERE hold_id=?", (entry.get("hold_id"),)).fetchone()
            reason=_validate(hold, entry)
            if reason:
                _invalidate(entry,reason); report["invalidated"]+=1; report["issues"].append({"severity":"medium","issue_type":reason,"hold_id":entry.get("hold_id")}); continue
            prior=conn.execute("SELECT * FROM canonical_decision_ledger WHERE decision_id=?", (hold["prior_agent_attempt_id"],)).fetchone()
            if not prior:
                _invalidate(entry,"hold_not_open"); report["invalidated"]+=1; report["issues"].append({"severity":"medium","issue_type":"prior_attempt_missing","hold_id":entry.get("hold_id")}); continue
            raw={key: prior[key] for key in ("packet_id","inbox_id","domain","lane","source_id","source_key","source_payload_hash")}
            raw.update(requested_action=entry["action"], payload={"target_id":entry.get("target_id"),"reason_detail":entry.get("reason_detail","")})
            raw["payload"]={k:v for k,v in raw["payload"].items() if v not in (None,"")}
            try:
                normalized=canonicalize_raw_judgment(raw, trusted_actor={"actor_type":"user","actor_id":args.actor_id,"decision_channel":"console","decided_at":_now()})
                decision=build_user_decision(normalized,open_hold=dict(hold),adjudication_batch_id=entry.get("batch_id"))
                conn.execute("BEGIN")
                outcome=write_decision(conn,decision)
                conn.execute("UPDATE review_hold_ledger SET status='resolved', closed_at=?, resolved_by_decision_id=? WHERE hold_id=?", (_now(),decision["decision_id"],hold["hold_id"]))
                conn.commit()
                entry.update(status="applied",applied_at=_now(),decision_id=decision["decision_id"])
                report["noop" if outcome=="noop" else "applied"]+=1; report["entries"].append({"hold_id":hold["hold_id"],"decision_id":decision["decision_id"],"outcome":outcome})
            except (ContractError, ValueError, sqlite3.Error) as exc:
                conn.rollback()
                # 同じ decision_id で中身が違う＝台帳の履歴が壊れている合図なので、
                # 1件の invalidated で流さずバッチ全体を止める（J0-read と同じ扱い）。
                if str(exc)=="decision_id_conflict": raise
                _invalidate(entry,"invalid_decision"); report["invalidated"]+=1; report["issues"].append({"severity":"medium","issue_type":"invalid_decision","detail":str(exc),"hold_id":entry.get("hold_id")})
    write_json_atomic(Path(args.adjudications),payload)
    Path(args.report_json).parent.mkdir(parents=True,exist_ok=True); Path(args.report_json).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    return report

def main():
    p=argparse.ArgumentParser(); p.add_argument("--db",type=Path,default=MASTER_DB); p.add_argument("--out-db",type=Path,default=Path("data/user_adjudications_dry_run.sqlite")); p.add_argument("--adjudications",type=Path,default=ADJUDICATIONS_PATH); p.add_argument("--report-json",type=Path,default=Path("data/user_adjudications_report.json")); p.add_argument("--actor-id"); p.add_argument("--apply",action="store_true"); p.add_argument("--confirm",default=""); p.add_argument("--no-auto-migrate",action="store_true")
    print(json.dumps(run(p.parse_args()),ensure_ascii=False)); return 0
if __name__ == "__main__": raise SystemExit(main())
