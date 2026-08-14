"""Validate LLM results against frozen packets and write judgment ledgers."""
from __future__ import annotations
import argparse,json,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from event_model.local_judgment_migration import migrate_local_judgment_contract,migrate_event_inbox_candidate,migrate_review_claim_ledger
from master_rdb.master_db import MASTER_DB,connect_existing,stable_id
from operation_safety.manual_apply_guards import require_confirmation
from report_apply.rdb_apply_support import copy_db
from review_inbox_adapters.local_judgment_contract import canonicalize_raw_judgment,build_agent_terminal_decision,build_canonical_hold,REASON_CODE_HOLD_MODE
from review_inbox_adapters.local_judgment_contract import ContractError
from review_inbox_adapters.judgment_ledger_writer import write_decision
JUDGMENT_RESULT_CONFIRMATION='APPLY JUDGMENT RESULTS'
def _migrate(c):migrate_local_judgment_contract(c);migrate_event_inbox_candidate(c);migrate_review_claim_ledger(c)
def _packets(directory):
 out={}
 for p in Path(directory).glob('batch_*.json'):
  for x in json.loads(p.read_text()).get('packets',[]):out[x['packet_id']]=x
 return out
def run(args):
 if not args.actor_id: raise ValueError('actor_id is required')
 if args.apply: require_confirmation(True,args.confirm,JUDGMENT_RESULT_CONFIRMATION,'apply_judgment_results.py --apply')
 db=Path(args.db);target=db if args.apply else Path(args.out_db)
 if not args.apply:
  if target.resolve()==db.resolve():raise ValueError('dry-run target must differ from --db')
  copy_db(db,target)
 packets=_packets(args.packets_dir)
 results=[r for path in args.results for r in json.loads(Path(path).read_text()).get('results',[])]
 report={'accepted':0,'rejected':0,'held_for_user':0,'deferred_for_retry':0,'noop':0,'rejected_result':0,'issues':[],'entries':[],'migrations_applied':[],'claim_scope':'production' if args.apply else 'dry_run_copy'}
 with connect_existing(target) as c:
  c.row_factory=sqlite3.Row
  if not args.apply and not args.no_auto_migrate:_migrate(c);report['migrations_applied']=['local_judgment_contract_v1','event_inbox_candidate_v1','review_claim_ledger_v1']
  c.commit()
  tables={x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if not {'canonical_decision_ledger','review_queue_state_ledger','review_hold_ledger','review_claim_ledger'}<=tables:raise ValueError('judgment_ledger_missing')
  for result in results:
   packet=packets.get(result.get('packet_id'))
   if not packet: raise ValueError('packet_missing')
   fields=('inbox_id','domain','lane','source_id','source_key','source_payload_hash')
   expected=stable_id('packet',packet['inbox_id'],packet['source_payload_hash'],'judgment-packet/v1')
   if packet['packet_id']!=expected or any(result.get(k)!=packet.get(k) for k in fields) or result.get('requested_action') not in packet['allowed_actions']:
    report['rejected_result']+=1;report['issues'].append({'severity':'medium','issue_type':'packet_mismatch','packet_id':packet['packet_id']});continue
   row=c.execute('SELECT source_payload_hash,status FROM review_inbox_items WHERE inbox_id=?',(packet['inbox_id'],)).fetchone()
   if not row or row['source_payload_hash']!=packet['source_payload_hash']:
    report['rejected_result']+=1;report['issues'].append({'severity':'medium','issue_type':'packet_stale','packet_id':packet['packet_id']});continue
   requested=result['requested_action']; raw=dict(result); raw['requested_action']='hold' if requested in {'defer_for_retry','hold_for_user'} else requested
   trusted={'actor_type':'agent','actor_id':args.actor_id,'decision_channel':'llm','decided_at':datetime.now(timezone.utc).isoformat()}
   try:
    normalized=canonicalize_raw_judgment(raw,trusted_actor=trusted)
    if requested in {'defer_for_retry','hold_for_user'}:
     code=result.get('reason_code'); mode=REASON_CODE_HOLD_MODE.get(code)
     expected_mode='deferred_retry' if requested=='defer_for_retry' else 'awaiting_user'
     if mode!=expected_mode:raise ValueError('hold_mode_mismatch')
     decision=build_canonical_hold(normalized,reason_code=code,retry_candidates=packet['retry_candidates'],selected_candidate_id=result.get('selected_retry_candidate_id'))
     candidate_ids=[x['occurrence_id'] for x in packet['targets'].get('occurrence_candidates',[])] if mode=='awaiting_user' else None
    else: decision=build_agent_terminal_decision(normalized);candidate_ids=None
    c.execute('BEGIN'); outcome=write_decision(c,decision,candidate_ids=candidate_ids);c.commit()
    key={'accept':'accepted','reject':'rejected','hold_for_user':'held_for_user','defer_for_retry':'deferred_for_retry'}[requested] if outcome=='written' else 'noop';report[key]+=1;report['entries'].append({'inbox_id':decision['inbox_id'],'decision_id':decision['decision_id'],'action':decision['action'],'reason_code':decision['reason_code']})
   except (ContractError, ValueError) as exc:
    c.rollback()
    if str(exc)=='decision_id_conflict':raise
    report['rejected_result']+=1;report['issues'].append({'severity':'medium','issue_type':'invalid_result','detail':str(exc),'packet_id':packet['packet_id']})
 return report
def main():
 p=argparse.ArgumentParser();p.add_argument('--db',type=Path,default=MASTER_DB);p.add_argument('--out-db',type=Path,default=Path('data/judgment_results_dry_run.sqlite'));p.add_argument('--results',type=Path,action='append',required=True);p.add_argument('--packets-dir',type=Path,default=Path('data/judgment_packets'));p.add_argument('--actor-id');p.add_argument('--apply',action='store_true');p.add_argument('--confirm',default='');p.add_argument('--no-auto-migrate',action='store_true');a=p.parse_args();print(json.dumps(run(a),ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
