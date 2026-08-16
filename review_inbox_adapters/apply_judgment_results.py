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
from review_inbox_adapters.local_judgment_contract import ContractError,IDENTITY_LANES,IDENTITY_MATCH_NONE,IDENTITY_PAYLOAD_FIELDS
from review_inbox_adapters.build_event_inbox_candidates import search_targets
from review_inbox_adapters.build_judgment_packets import candidate_set_hash
from review_inbox_adapters.judgment_ledger_writer import write_decision
JUDGMENT_RESULT_CONFIRMATION='APPLY JUDGMENT RESULTS'
IDENTITY_FIELDS=('occurrence_match','series_match','venue_match')
NEW_SERIES_REASON='new_series_requires_confirmation'
NEW_VENUE_REASON='new_venue_requires_confirmation'
NO_MATERIAL_REASON='insufficient_evidence'
def _identity_problem(packet,payload):
 """同一性の答えを機械が検算する。LLMには候補から選ぶ以上のことをさせない。"""
 targets=packet.get('targets') or {}
 occurrences={x['occurrence_id']:x for x in targets.get('occurrence_candidates',[]) if x.get('occurrence_id')}
 series={x.get('series_id') for x in occurrences.values() if x.get('series_id')}
 venues={x['venue_id'] for x in targets.get('venue_candidates',[]) if x.get('venue_id')}
 for field in IDENTITY_FIELDS:
  if not isinstance(payload.get(field),str) or not payload[field]: return f'{field}_missing'
 if payload['occurrence_match']!=IDENTITY_MATCH_NONE and payload['occurrence_match'] not in occurrences: return 'occurrence_match_not_a_candidate'
 if payload['series_match']!=IDENTITY_MATCH_NONE and payload['series_match'] not in series: return 'series_match_not_a_candidate'
 if payload['venue_match']!=IDENTITY_MATCH_NONE and payload['venue_match'] not in venues: return 'venue_match_not_a_candidate'
 if payload['occurrence_match']!=IDENTITY_MATCH_NONE and payload['series_match']!=occurrences[payload['occurrence_match']].get('series_id'): return 'series_match_conflicts_with_occurrence'
 return None
def _identity_hold_reason(payload,proposal):
 """新しい系列・会場が生まれる答えは人の確認へ回す。統合の仕組みが無く取り消せないため。

 ただし「新規です」と言えるのは、作る材料（名前・会場名）が揃っているときだけ。無いものを
 新規確認として出すと、名前も会場も空の項目が裁定画面に並び、人は何も判断できない
 （2026-08-15 に56件すべてがこれだった）。材料が無いなら理由は「証拠不足」が正しい。

 保留にするのは機械側の運用ポリシーで、LLMの判断そのものは payload にそのまま残る。
 統合が実装されたらこの関数を外すだけでよく、LLMへの指示は変えずに済む。
 """
 if payload['series_match']==IDENTITY_MATCH_NONE:
  return NEW_SERIES_REASON if (proposal or {}).get('event_name_hint') else NO_MATERIAL_REASON
 if payload['venue_match']==IDENTITY_MATCH_NONE:
  return NEW_VENUE_REASON if ((proposal or {}).get('venue') or {}).get('name') else NO_MATERIAL_REASON
 return None
def _migrate(c):migrate_local_judgment_contract(c);migrate_event_inbox_candidate(c);migrate_review_claim_ledger(c)
def _packets(directory):
 out={}
 for p in Path(directory).glob('batch_*.json'):
  for x in json.loads(p.read_text()).get('packets',[]):out[x['packet_id']]=x
 return out
def _markdown(report):
 lines=['# Judgment results report','']
 for key in ('accepted','rejected','held_for_user','deferred_for_retry','noop','rejected_result'):
  lines.append(f'- {key}: {report[key]}')
 lines.extend(['','## Entries',''])
 for entry in report['entries']:
  lines.append(f"- {entry['inbox_id']} | {entry['decision_id']} | {entry['action']} | {entry['reason_code']}")
 lines.extend(['','## Issues',''])
 for issue in report['issues']: lines.append(f"- {json.dumps(issue,ensure_ascii=False,sort_keys=True)}")
 return '\n'.join(lines)+'\n'
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
   row=c.execute('SELECT source_payload_hash,status,contract_lane,payload_json FROM review_inbox_items WHERE inbox_id=?',(packet['inbox_id'],)).fetchone()
   if not row or row['source_payload_hash']!=packet['source_payload_hash']:
    report['rejected_result']+=1;report['issues'].append({'severity':'medium','issue_type':'packet_stale','packet_id':packet['packet_id']});continue
   # 提案の中身が同じでも、候補集合は日次収集で入れ替わる。判定者が見た集合と今の集合が
   # 違えば、その判断はもう別の問いへの答えなので通さない。
   if packet.get('candidate_set_sha256') is not None:
    current=candidate_set_hash(search_targets(c,json.loads(row['payload_json'])['proposal'],row['contract_lane'],datetime.now(timezone.utc)))
    if current!=packet['candidate_set_sha256']:
     report['rejected_result']+=1;report['issues'].append({'severity':'medium','issue_type':'candidate_set_changed','packet_id':packet['packet_id']});continue
   requested=result['requested_action']; raw=dict(result); policy=None
   if requested=='accept' and (packet['domain'],packet['lane']) in IDENTITY_LANES:
    problem=_identity_problem(packet,raw.get('payload') or {})
    if problem:
     report['rejected_result']+=1;report['issues'].append({'severity':'medium','issue_type':problem,'packet_id':packet['packet_id']});continue
    policy=_identity_hold_reason(raw['payload'],packet.get('proposal'))
    if policy: requested='hold_for_user'
   raw['requested_action']='hold' if requested in {'defer_for_retry','hold_for_user'} else requested
   trusted={'actor_type':'agent','actor_id':args.actor_id,'decision_channel':'llm','decided_at':datetime.now(timezone.utc).isoformat()}
   try:
    normalized=canonicalize_raw_judgment(raw,trusted_actor=trusted)
    if requested in {'defer_for_retry','hold_for_user'}:
     code=policy or result.get('reason_code'); mode=REASON_CODE_HOLD_MODE.get(code)
     expected_mode='deferred_retry' if requested=='defer_for_retry' else 'awaiting_user'
     if mode!=expected_mode:raise ValueError('hold_mode_mismatch')
     decision=build_canonical_hold(normalized,reason_code=code,retry_candidates=packet['retry_candidates'],selected_candidate_id=result.get('selected_retry_candidate_id'))
     # 新規確認の保留は「どれを選ぶか」ではないので候補集合を凍結しない。空にすると裁定画面が
     # 対象IDを要求せず、同じ理由の保留をまとめて裁ける（何を見て none と答えたかは packet に残る）。
     candidate_ids=[] if policy else ([x['occurrence_id'] for x in packet['targets'].get('occurrence_candidates',[])] if mode=='awaiting_user' else None)
    else: decision=build_agent_terminal_decision(normalized);candidate_ids=None
    c.execute('BEGIN'); outcome=write_decision(c,decision,candidate_ids=candidate_ids);c.commit()
    key={'accept':'accepted','reject':'rejected','hold_for_user':'held_for_user','defer_for_retry':'deferred_for_retry'}[requested] if outcome=='written' else 'noop';report[key]+=1;report['entries'].append({'inbox_id':decision['inbox_id'],'decision_id':decision['decision_id'],'action':decision['action'],'reason_code':decision['reason_code']})
   except (ContractError, ValueError) as exc:
    c.rollback()
    if str(exc)=='decision_id_conflict':raise
    report['rejected_result']+=1;report['issues'].append({'severity':'medium','issue_type':'invalid_result','detail':str(exc),'packet_id':packet['packet_id']})
 args.report_json.parent.mkdir(parents=True,exist_ok=True)
 args.report_json.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
 args.report_md.parent.mkdir(parents=True,exist_ok=True)
 args.report_md.write_text(_markdown(report))
 return report
def main():
 p=argparse.ArgumentParser();p.add_argument('--db',type=Path,default=MASTER_DB);p.add_argument('--out-db',type=Path,default=Path('data/judgment_results_dry_run.sqlite'));p.add_argument('--results',type=Path,action='append',required=True);p.add_argument('--packets-dir',type=Path,default=Path('data/judgment_packets'));p.add_argument('--report-json',type=Path,default=Path('data/judgment_results_report.json'));p.add_argument('--report-md',type=Path,default=Path('data/judgment_results_report.md'));p.add_argument('--actor-id');p.add_argument('--apply',action='store_true');p.add_argument('--confirm',default='');p.add_argument('--no-auto-migrate',action='store_true');a=p.parse_args();print(json.dumps(run(a),ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
