#!/usr/bin/env python3
"""Split the bounded X gap queue into the three operational lanes.

Lane 1 is deliberately conservative: only a registered official source,
an already known occurrence, a missing-date gap, and an extracted date are
eligible.  It emits a *plan* rather than mutating the RDB; the existing
change-request apply safeguards remain the sole writer.
"""
from __future__ import annotations
import argparse, json, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from master_rdb.master_db import normalize_text

DATA=Path('data'); INPUT=DATA/'x_gap_candidates.json'; OUT=DATA/'x_review_lanes.json'
TIME_RE=re.compile(r'(?<!\d)([0-2]?\d)[:：]([0-5]\d)')
NON_ASSERTED_CHANGE_RE=re.compile(
    r'(?:中止|延期|順延).{0,24}(?:場合|可能性|かも|かもしれ|と思|予報|心配)'
    r'|(?:荒天|雨天|天候).{0,16}(?:中止|延期|順延).{0,12}(?:場合|可能性|あり)'
)

def lane_for(row:dict[str,Any])->str:
    official=(row.get('source_officiality') or {}).get('classification')=='registered_official_social'
    known=bool(row.get('matched_occurrence'))
    # P1 only emits missing_date where the occurrence date is empty.  Recheck
    # this explicit kind so lane 1 can never create a new event or overwrite.
    safe=official and known and row.get('candidate_kind')=='missing_date' and bool(row.get('date_hints'))
    if safe: return 'lane1_auto_plan'
    uncertain=(row.get('candidate_kind')=='schedule_change' or not known or not official)
    return 'lane3_user_review' if uncertain else 'lane2_operator_review'

def time_values(text:str)->set[str]:
    return {f'{int(hour):02d}:{minute}' for hour,minute in TIME_RE.findall(str(text or ''))}

def venue_matches_source(venue:str, source_text:str)->bool:
    venue_norm=normalize_text(venue)
    source_norm=normalize_text(source_text)
    if not venue_norm: return False
    if venue_norm in source_norm: return True
    # Permit equivalent spellings such as 渋谷109前 / SHIBUYA109前 while
    # still requiring every distinctive word/number from the canonical venue.
    parts=re.findall(r'[a-zA-Z]+|\d+|[一-龥ぁ-んァ-ヶー]+',str(venue or ''))
    significant=[normalize_text(part) for part in parts if len(normalize_text(part))>=2]
    return bool(significant) and all(part in source_norm for part in significant)

def matches_existing_values(row:dict[str,Any])->bool:
    match=row.get('matched_occurrence') or {}
    observed=sorted(str(value) for value in (row.get('observed_dates') or []) if value)
    start=str(match.get('date_start') or '')
    end=str(match.get('date_end') or start)
    if not observed or not start or observed[0]!=start or observed[-1]!=end:
        return False
    source_text=str(row.get('source_text') or '')
    existing_times=time_values(str(match.get('detail') or ''))
    source_times=time_values(source_text)
    if not existing_times or not existing_times.issubset(source_times):
        return False
    return venue_matches_source(str(match.get('venue') or ''),source_text)

def archive_reason(row:dict[str,Any])->str:
    if row.get('candidate_kind')!='schedule_change': return ''
    if not NON_ASSERTED_CHANGE_RE.search(str(row.get('source_text') or '')): return ''
    if matches_existing_values(row): return 'existing_schedule_values_match'
    return 'non_asserted_schedule_change'

def build(payload:dict[str,Any])->dict[str,Any]:
    rows=payload.get('candidates') or []
    if not isinstance(rows,list) or len(rows)>30: raise ValueError('candidate input must contain at most 30 rows')
    lanes={'lane1_auto_plan':[],'lane2_operator_review':[],'lane3_user_review':[]}
    archived=[]
    for raw in rows:
        if not isinstance(raw,dict): continue
        row=dict(raw)
        reason=archive_reason(row)
        if reason:
            row['archive_reason']=reason; archived.append(row); continue
        row['lane']=lane_for(row); lanes[row['lane']].append(row)
    # The user-facing lane is capped independently even if upstream selection
    # changes in the future.
    lanes['lane3_user_review'].sort(key=lambda r:(-float(r.get('priority_score') or 0),str(r.get('source_key') or '')))
    overflow=lanes['lane3_user_review'][3:]; lanes['lane3_user_review']=lanes['lane3_user_review'][:3]
    lanes['lane2_operator_review'].extend(overflow)
    return {'generated_by':'build_x_review_lanes.py','generated_at':datetime.now(timezone.utc).isoformat(),
      'contract':{'daily_input_max':30,'lane3_user_review_max':3,'lane1_no_new_event':True,'lane1_no_overwrite':True,
                  'lane3_existing_value_matches_archived':True},'lanes':lanes,'archived_candidates':archived}

def main()->None:
 p=argparse.ArgumentParser();p.add_argument('--input',type=Path,default=INPUT);p.add_argument('--out',type=Path,default=OUT);a=p.parse_args();data=build(json.loads(a.input.read_text(encoding='utf-8')));a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print('x review lanes:',{k:len(v) for k,v in data['lanes'].items()})
if __name__=='__main__':main()
