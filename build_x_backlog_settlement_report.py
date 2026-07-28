#!/usr/bin/env python3
"""Produce a no-write inventory before settling legacy X backlogs.

This is deliberately a dry-run only tool: a reviewer must approve its exact
counts and criteria before a separate, explicitly confirmed mutation is run.
"""
from __future__ import annotations
import argparse, json, re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from build_x_gap_candidates import catalog, discriminative_alias
from master_rdb.master_db import MASTER_DB

DATA=Path('data')

def load(path:Path, default:Any)->Any:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

def rows(payload:Any, *keys:str)->list[dict]:
    if isinstance(payload,list): return [x for x in payload if isinstance(x,dict)]
    if isinstance(payload,dict):
        for key in keys:
            if isinstance(payload.get(key),list): return [x for x in payload[key] if isinstance(x,dict)]
    return []

def score_band(row:dict)->str:
    score=float(row.get('confidence_score') or 0)
    lower=int(score//10)*10
    return f'{lower}-{lower + 9}'

def first_seen_period(row:dict)->str:
    value=str(row.get('first_seen_at') or '')
    return value[:7] if len(value)>=7 else 'unknown'

def processed(row:dict)->bool:
    return bool(row.get('notion_page_id') or row.get('notion_synced'))

def strict_norm(value:Any)->str:
    return re.sub(r'[\s\-‐‑–—・（）()「」『』【】]', '', str(value or '')).casefold()

def gap_matches(row:dict, gaps:list[dict])->list[dict]:
    """Match a queued candidate to a date gap without generic partial hits."""
    # Do not search raw evidence prose: it often contains a different event
    # mentioned in passing.  Candidate title/estimated fields are the only
    # stable identity claims available at this backlog stage.
    text=' '.join(str(row.get(k) or '') for k in ('title','estimated_event'))
    normalized=strict_norm(text)
    matched=[]
    for gap in gaps:
        # RDB aliases include historical broad labels.  For an archive hold,
        # false retention is costly, so use the occurrence display name only.
        names=[name for name in [gap.get('event_name')] if discriminative_alias(name)]
        name_hits=[name for name in names if strict_norm(name) in normalized]
        venue=strict_norm(gap.get('venue') or '')
        # Venue matching must be exact-token-ish and at least 5 chars: this
        # avoids e.g. one shrine word binding unrelated ward events.
        # Do not trust estimated_venue by itself: the legacy extractor can
        # attach a venue mentioned as unrelated context.  The stable candidate
        # title/event claim must itself name the venue.
        venue_hit=bool(venue and len(venue)>=5 and venue in normalized)
        if name_hits or venue_hit:
            matched.append({'occurrence_id':gap['occurrence_id'],'event_name':gap['event_name'],'venue':gap.get('venue') or '', 'match_basis':'event_name' if name_hits else 'venue', 'matched_names':name_hits})
    return matched

def build(event_queue:Any, inbox:Any, posters:Any, *, master_db:Path=MASTER_DB, year:int=2026)->dict:
    events=rows(event_queue,'items','candidates','queue'); pending=rows(inbox,'items'); poster_rows=rows(posters,'items','queue')
    high=[r for r in events if float(r.get('confidence_score') or 0)>=50]
    score_retained=[r for r in high if not processed(r)]
    processed_rows=[r for r in events if processed(r)]
    gaps=[gap for gap in catalog(Path(master_db),year) if not gap.get('date_start')]
    gap_retained=[]
    for row in events:
        if processed(row) or float(row.get('confidence_score') or 0)>=50: continue
        matches=gap_matches(row,gaps)
        if matches:
            gap_retained.append({'candidate_key':row.get('candidate_key'),'title':row.get('title'),'confidence_score':row.get('confidence_score',0),'first_seen_at':row.get('first_seen_at',''),'matches':matches})
    gap_keys={row['candidate_key'] for row in gap_retained}
    retained=score_retained + [row for row in events if row.get('candidate_key') in gap_keys]
    archive=[r for r in events if not processed(r) and float(r.get('confidence_score') or 0)<50 and r.get('candidate_key') not in gap_keys]
    return {'generated_by':'build_x_backlog_settlement_report.py','generated_at':datetime.now(timezone.utc).isoformat(),
      'mode':'dry_run_no_mutation','queues':{
        'event_candidate_queue':{
          'total':len(events),'high_confidence_total':len(high),'processed_total':len(processed_rows),
          're_evaluate':len(retained),'score_retained':len(score_retained),'gap_retained':len(gap_retained),'gap_retained_items':gap_retained,'archive_after_review':len(archive),
          'criterion':'retain unprocessed confidence_score >= 50 OR an unprocessed row with discriminative event-name/exact venue match to a current-year occurrence missing date; archive (never delete) remaining low-score rows. Processed rows are excluded from both.',
          'archive_breakdown':{'confidence_score_band':dict(sorted(Counter(score_band(r) for r in archive).items())),'candidate_type':dict(sorted(Counter(str(r.get('candidate_type') or 'unknown') for r in archive).items())),'first_seen_month':dict(sorted(Counter(first_seen_period(r) for r in archive).items()))},
          'restore':'A future archive plan records candidate_key and prior status. Restore by conditional DynamoDB update of status to that prior value; no TTL or delete is used.'},
        'review_inbox':{'total':len(pending),'pending':sum(1 for r in pending if r.get('status','pending')=='pending'),'by_time_scope':dict(Counter(str(r.get('time_scope') or 'reference') for r in pending))},
        'poster_ocr_queue':{'total':len(poster_rows),'retain_daily_cap':min(30,len(poster_rows)),'archive_not_proposed':True,'criterion':'do not bulk-close posters; regenerate a 30/day gap-prioritized queue'}},
      'next_action':'Reviewer must confirm this report before any archive/close mutation.'}

def main()->None:
 p=argparse.ArgumentParser(); p.add_argument('--event-queue',type=Path,default=DATA/'event_candidate_queue.json'); p.add_argument('--inbox',type=Path,default=DATA/'review_inbox.json'); p.add_argument('--posters',type=Path,default=DATA/'event_poster_ocr_queue.json'); p.add_argument('--master-db',type=Path,default=MASTER_DB); p.add_argument('--year',type=int,default=2026); p.add_argument('--out',type=Path,required=True); a=p.parse_args(); payload=build(load(a.event_queue,{}),load(a.inbox,{}),load(a.posters,{}),master_db=a.master_db,year=a.year); a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(payload['queues'],ensure_ascii=False))
if __name__=='__main__': main()
