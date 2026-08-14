"""Build deterministic, claimed judgment packets from E0 event candidates."""
from __future__ import annotations
import argparse,json,sqlite3
from datetime import datetime,timedelta,timezone
from pathlib import Path
from event_model.local_judgment_migration import migrate_local_judgment_contract,migrate_event_inbox_candidate,migrate_review_claim_ledger
from master_rdb.master_db import MASTER_DB,connect_existing,stable_id
from operation_safety.manual_apply_guards import require_confirmation
from report_apply.rdb_apply_support import copy_db
from review_inbox_adapters.local_judgment_contract import ACTION_REGISTRY,REASON_CODE_HOLD_MODE,sha256_hex

PACKET_CALCULATION_VERSION="judgment-packet/v1"
JUDGMENT_PACKET_CONFIRMATION="APPLY JUDGMENT PACKETS"
def now(): return datetime.now(timezone.utc)
def _migrate(c):
    migrate_local_judgment_contract(c);migrate_event_inbox_candidate(c);migrate_review_claim_ledger(c)
def allowed(domain,lane):
    out=[a for (d,l,a),v in ACTION_REGISTRY.items() if (d,l)==(domain,lane) and "agent" in v["allowed_actor_types"]]
    return [x for x in out if x!="hold"]+["defer_for_retry","hold_for_user"]
def make_packet(row,when):
    p=json.loads(row["payload_json"]); pid=stable_id("packet",row["inbox_id"],row["source_payload_hash"],PACKET_CALCULATION_VERSION)
    occ=[x["occurrence_id"] for x in p.get("targets",{}).get("occurrence_candidates",[])][:8]; ev=p.get("evidence_ids",[])
    end=min(when+timedelta(days=30),datetime.fromisoformat(row["expires_at"])) if row["expires_at"] else when+timedelta(days=30)
    start=when+timedelta(days=7); reason=None
    if not occ: reason="no_occurrence_candidates"
    elif not ev: reason="no_evidence"
    elif end < start: reason="retry_window_shorter_than_minimum"
    retry=[] if reason else [{"candidate_id":stable_id("retry",row["inbox_id"],"v1"),"next_eligible_at":min(when+timedelta(days=14),end).isoformat(),"window_start":start.isoformat(),"window_end":end.isoformat(),"occurrence_ids":occ,"evidence_ids":ev,"retrieved_at":when.isoformat(),"calculation_version":"retry-window/v1","input_hash":sha256_hex({"inbox_id":row["inbox_id"],"occurrence_ids":occ,"evidence_ids":ev})}]
    return {"packet_version":1,"packet_id":pid,"inbox_id":row["inbox_id"],"domain":row["contract_domain"],"lane":row["contract_lane"],"source_id":row["source_id"],"source_key":row["source_key"],"source_payload_hash":row["source_payload_hash"],"generated_at":when.isoformat(),"expires_at":row["expires_at"],"proposal":p["proposal"],"targets":p["targets"],"resolved_target":p.get("resolved_target"),"evidence":[{"evidence_id":x,"source_url":row["source_url"],"excerpt":p.get("raw_excerpt",""),"retrieved_at":p["targets"]["retrieved_at"]} for x in ev],"retry_candidates":retry,"retry_unavailable_reason":reason,"allowed_actions":allowed(row["contract_domain"],row["contract_lane"]),"reason_codes":REASON_CODE_HOLD_MODE}
def run(args):
    if not args.actor_id: raise ValueError("actor_id is required")
    if args.apply: require_confirmation(True,args.confirm,JUDGMENT_PACKET_CONFIRMATION,"build_judgment_packets.py --apply")
    db=Path(args.db); target=db if args.apply else Path(args.out_db)
    if not args.apply:
        if target.resolve()==db.resolve(): raise ValueError("dry-run target must differ from --db")
        copy_db(db,target)
    with connect_existing(target) as c:
        c.row_factory=sqlite3.Row
        if not args.apply and not args.no_auto_migrate:_migrate(c); migrations=["local_judgment_contract_v1","event_inbox_candidate_v1","review_claim_ledger_v1"]
        else:migrations=[]
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "review_claim_ledger" not in tables: raise ValueError("review_claim_ledger_missing")
        t=now(); rows=c.execute("SELECT i.*,q.queue_state,q.decision_id,cl.claimed_by,cl.expires_at claim_expires FROM review_inbox_items i LEFT JOIN review_queue_state_ledger q ON q.inbox_id=i.inbox_id LEFT JOIN review_claim_ledger cl ON cl.inbox_id=i.inbox_id WHERE i.kind='event_candidate' AND i.status='candidate' AND i.contract_domain=? ORDER BY i.expires_at,i.first_eligible_at",(args.domain,)).fetchall(); packets=[]; excluded=[]
        for r in rows:
            reason=None
            if r["superseded_by_inbox_id"]:reason="superseded"
            elif r["expires_at"] and datetime.fromisoformat(r["expires_at"])<t:reason="expired"
            elif r["first_eligible_at"] and datetime.fromisoformat(r["first_eligible_at"])>t or r["queue_state"] not in (None,"eligible"):reason="not_eligible"
            elif r["claimed_by"] and datetime.fromisoformat(r["claim_expires"])>t and r["claimed_by"]!=args.actor_id and not args.force_claim:reason="claimed_by_other"
            if reason: excluded.append({"inbox_id":r["inbox_id"],"reason":reason});continue
            if len(packets)>=args.max_packets: continue
            packet=make_packet(r,t); c.execute("INSERT INTO review_claim_ledger VALUES (?,?,?,?,?,?) ON CONFLICT(inbox_id) DO UPDATE SET claimed_by=excluded.claimed_by,claim_kind=excluded.claim_kind,claimed_at=excluded.claimed_at,expires_at=excluded.expires_at,batch_id=excluded.batch_id",(r["inbox_id"],args.actor_id,"agent",t.isoformat(),(t+timedelta(minutes=args.lease_minutes)).isoformat(),"pending"));packets.append(packet)
        c.commit()
    args.out_dir.mkdir(parents=True,exist_ok=True); batches=[]
    for n in range(0,len(packets),args.batch_size):
        path=args.out_dir/f"batch_{t.strftime('%Y%m%d')}_{n//args.batch_size+1:02d}.json"; data={"batch_id":path.stem,"packets":packets[n:n+args.batch_size]};path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n");batches.append(str(path))
    return {"generated":len(packets),"batches":batches,"excluded":excluded,"waiting_count":max(0,len(rows)-len(packets)-len(excluded)),"migrations_applied":migrations,"claim_scope":"production" if args.apply else "dry_run_copy"}
def main():
 p=argparse.ArgumentParser();p.add_argument('--db',type=Path,default=MASTER_DB);p.add_argument('--out-db',type=Path,default=Path('data/judgment_packets_dry_run.sqlite'));p.add_argument('--out-dir',type=Path,default=Path('data/judgment_packets'));p.add_argument('--actor-id');p.add_argument('--batch-size',type=int,default=20);p.add_argument('--max-packets',type=int,default=100);p.add_argument('--lease-minutes',type=int,default=30);p.add_argument('--force-claim',action='store_true');p.add_argument('--domain',default='event');p.add_argument('--apply',action='store_true');p.add_argument('--confirm',default='');p.add_argument('--no-auto-migrate',action='store_true');a=p.parse_args();print(json.dumps(run(a),ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
