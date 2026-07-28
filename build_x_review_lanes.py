#!/usr/bin/env python3
"""Split the bounded X gap queue into the three operational lanes.

Lane 1 is deliberately conservative: only a registered official source,
an already known occurrence, a missing-date gap, and an extracted date are
eligible.  It emits a *plan* rather than mutating the RDB; the existing
change-request apply safeguards remain the sole writer.
"""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA=Path('data'); INPUT=DATA/'x_gap_candidates.json'; OUT=DATA/'x_review_lanes.json'

def lane_for(row:dict[str,Any])->str:
    official=(row.get('source_officiality') or {}).get('classification')=='registered_official_social'
    known=bool(row.get('matched_occurrence'))
    # P1 only emits missing_date where the occurrence date is empty.  Recheck
    # this explicit kind so lane 1 can never create a new event or overwrite.
    safe=official and known and row.get('candidate_kind')=='missing_date' and bool(row.get('date_hints'))
    if safe: return 'lane1_auto_plan'
    uncertain=(row.get('candidate_kind')=='schedule_change' or not known or not official)
    return 'lane3_user_review' if uncertain else 'lane2_operator_review'

def build(payload:dict[str,Any])->dict[str,Any]:
    rows=payload.get('candidates') or []
    if not isinstance(rows,list) or len(rows)>30: raise ValueError('candidate input must contain at most 30 rows')
    lanes={'lane1_auto_plan':[],'lane2_operator_review':[],'lane3_user_review':[]}
    for raw in rows:
        if not isinstance(raw,dict): continue
        row=dict(raw); row['lane']=lane_for(row); lanes[row['lane']].append(row)
    # The user-facing lane is capped independently even if upstream selection
    # changes in the future.
    lanes['lane3_user_review'].sort(key=lambda r:(-float(r.get('priority_score') or 0),str(r.get('source_key') or '')))
    overflow=lanes['lane3_user_review'][3:]; lanes['lane3_user_review']=lanes['lane3_user_review'][:3]
    lanes['lane2_operator_review'].extend(overflow)
    return {'generated_by':'build_x_review_lanes.py','generated_at':datetime.now(timezone.utc).isoformat(),
      'contract':{'daily_input_max':30,'lane3_user_review_max':3,'lane1_no_new_event':True,'lane1_no_overwrite':True},'lanes':lanes}

def main()->None:
 p=argparse.ArgumentParser();p.add_argument('--input',type=Path,default=INPUT);p.add_argument('--out',type=Path,default=OUT);a=p.parse_args();data=build(json.loads(a.input.read_text(encoding='utf-8')));a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print('x review lanes:',{k:len(v) for k,v in data['lanes'].items()})
if __name__=='__main__':main()
