#!/usr/bin/env python3
"""Archive only reviewed low-priority DynamoDB event-candidate rows."""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
from build_x_backlog_settlement_report import build, load
from master_rdb.master_db import MASTER_DB

CONFIRM='ARCHIVE REVIEWED EVENT CANDIDATE BACKLOG'

def main():
 p=argparse.ArgumentParser();p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--table',required=True);p.add_argument('--plan',type=Path,required=True);p.add_argument('--report',type=Path,required=True);p.add_argument('--master-db',type=Path,default=MASTER_DB);p.add_argument('--year',type=int,default=2026);p.add_argument('--apply',action='store_true');p.add_argument('--confirm',default='');a=p.parse_args()
 if a.apply and not a.master_db.exists():
  raise SystemExit(f'--apply requires an existing master DB: {a.master_db}')
 result=build(load(a.snapshot,{}),{}, {},master_db=a.master_db,year=a.year)
 events=load(a.snapshot,{}).get('items') or []
 kept={x['candidate_key'] for x in result['queues']['event_candidate_queue']['gap_retained_items']}
 targets=[r for r in events if not (r.get('notion_page_id') or r.get('notion_synced')) and float(r.get('confidence_score') or 0)<50 and r.get('candidate_key') not in kept]
 plan={'generated_at':datetime.now(timezone.utc).isoformat(),'source_snapshot':str(a.snapshot),'table':a.table,'restore_instruction':'Run conditional updates setting status to each prior_status; no rows were deleted.','items':[{'candidate_key':r['candidate_key'],'prior_status':r.get('status','未確認')} for r in targets]}
 a.plan.parent.mkdir(parents=True,exist_ok=True);a.plan.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 report={'mode':'dry_run','target_count':len(targets),'plan':str(a.plan),'updated':0,'skipped_conflict':0}
 if a.apply:
  if a.confirm!=CONFIRM: raise SystemExit('confirmation mismatch')
  import boto3
  table=boto3.resource('dynamodb').Table(a.table); now=datetime.now(timezone.utc).isoformat()
  report['mode']='applied'
  for item in plan['items']:
   try:
    table.update_item(Key={'candidate_key':item['candidate_key']},UpdateExpression='SET #s=:arch, archived_at=:now, archive_reason=:reason',ConditionExpression='attribute_exists(candidate_key) AND #s=:prior',ExpressionAttributeNames={'#s':'status'},ExpressionAttributeValues={':arch':'archived',':prior':item['prior_status'],':now':now,':reason':'P4 reviewed low-priority backlog'})
    report['updated']+=1
   except Exception as exc:
    if 'ConditionalCheckFailed' in str(exc): report['skipped_conflict']+=1
    else: raise
 a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
