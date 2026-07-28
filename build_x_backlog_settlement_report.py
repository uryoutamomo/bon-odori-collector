#!/usr/bin/env python3
"""Produce a no-write inventory before settling legacy X backlogs.

This is deliberately a dry-run only tool: a reviewer must approve its exact
counts and criteria before a separate, explicitly confirmed mutation is run.
"""
from __future__ import annotations
import argparse, json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA=Path('data')

def load(path:Path, default:Any)->Any:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

def rows(payload:Any, *keys:str)->list[dict]:
    if isinstance(payload,list): return [x for x in payload if isinstance(x,dict)]
    if isinstance(payload,dict):
        for key in keys:
            if isinstance(payload.get(key),list): return [x for x in payload[key] if isinstance(x,dict)]
    return []

def build(event_queue:Any, inbox:Any, posters:Any)->dict:
    events=rows(event_queue,'items','candidates','queue'); pending=rows(inbox,'items'); poster_rows=rows(posters,'items','queue')
    high=[r for r in events if float(r.get('score') or r.get('priority_score') or 0)>=50]
    return {'generated_by':'build_x_backlog_settlement_report.py','generated_at':datetime.now(timezone.utc).isoformat(),
      'mode':'dry_run_no_mutation','queues':{
        'event_candidate_queue':{'total':len(events),'re_evaluate':len(high),'archive_after_review':max(0,len(events)-len(high)),'criterion':'score >= 50 is retained for P1 gap-driven re-evaluation; all others are proposed for archive, not deletion'},
        'review_inbox':{'total':len(pending),'pending':sum(1 for r in pending if r.get('status','pending')=='pending'),'by_time_scope':dict(Counter(str(r.get('time_scope') or 'reference') for r in pending))},
        'poster_ocr_queue':{'total':len(poster_rows),'retain_daily_cap':min(30,len(poster_rows)),'archive_not_proposed':True,'criterion':'do not bulk-close posters; regenerate a 30/day gap-prioritized queue'}},
      'next_action':'Reviewer must confirm this report before any archive/close mutation.'}

def main()->None:
 p=argparse.ArgumentParser(); p.add_argument('--event-queue',type=Path,default=DATA/'event_candidate_queue.json'); p.add_argument('--inbox',type=Path,default=DATA/'review_inbox.json'); p.add_argument('--posters',type=Path,default=DATA/'event_poster_ocr_queue.json'); p.add_argument('--out',type=Path,required=True); a=p.parse_args(); payload=build(load(a.event_queue,{}),load(a.inbox,{}),load(a.posters,{})); a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(payload['queues'],ensure_ascii=False))
if __name__=='__main__': main()
