#!/usr/bin/env python3
"""Validate untrusted X extraction answers and emit E0 official_notice reports."""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

from build_x_extraction_packets import normalized_text
from master_rdb.master_db import normalize_text, stable_id


def load(path: Path, default):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return default


def _issue(issues, kind, **extra): issues.append({"issue_type": kind, **extra})


def _add_url(detail: str, url: str) -> str:
    line = f"- 出典URL: {url}"
    return detail if line in detail else detail.rstrip() + "\n" + line


def _detail(event: dict, packet: dict) -> str:
    note = str(event.get("n") or "").strip()
    if packet.get("officiality") == "registered_official_social":
        who = packet.get("account_name") or packet.get("account") or "公式アカウント"
        prefix = f"出典：{who}のX投稿。"
    else:
        prefix = "現地の告知投稿で開催を確認。"
    return _add_url((prefix + (note if note else "")).strip(), packet.get("url") or "")


def apply(packet: dict, answer: dict, state: dict, reports_dir: Path, *, today: date | None = None) -> dict:
    today = today or date.today(); issues=[]; reports=[]; scores=[]
    if "tweets" not in state:
        state["tweets"] = {key: value for key, value in state.items() if isinstance(value, dict)}
    rows = state["tweets"]
    by_no={item["no"]: item for item in packet.get("packets", [])}; answers={}
    if answer.get("batch_id") != packet.get("batch_id"):
        _issue(issues, "batch_id_mismatch")
    for result in answer.get("results", []):
        no=result.get("no")
        if no not in by_no: _issue(issues,"unknown_packet",no=no); continue
        if no not in answers: answers[no]=result
    reports_dir.mkdir(parents=True, exist_ok=True)
    for no, item in by_no.items():
        result=answers.get(no); outcome="issue"
        if not isinstance(result, dict): _issue(issues,"missing_result",no=no)
        else:
            score=result.get("s")
            if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
                _issue(issues,"invalid_score",no=no); score=None
            if score is not None: scores.append({"batch_id":packet.get("batch_id"),"no":no,"tweet_id":item["tweet_id"],"score":score,"note":result.get("n")})
            if score is not None and score < 5: outcome="scored_only"
            elif score == 5:
                events=result.get("events")
                if not isinstance(events, list) or not events: _issue(issues,"missing_events",no=no)
                else:
                    event_ok=True; past=False
                    for event in events:
                        quote, venue = str(event.get("quote") or ""), str(event.get("venue_name") or "")
                        dates=[event.get("date_start"), event.get("date_end") or event.get("date_start")]
                        if not quote or normalized_text(quote) not in normalized_text(item.get("text", "")): _issue(issues,"quote_not_in_text",no=no); event_ok=False
                        if not venue or normalized_text(venue) not in normalized_text(item.get("text", "")): _issue(issues,"venue_not_in_text",no=no); event_ok=False
                        if not item.get("url"): _issue(issues,"missing_source_url",no=no); event_ok=False
                        if any(value not in item.get("machine_extracted_dates", []) for value in dates): _issue(issues,"date_not_in_text",no=no); event_ok=False; continue
                        if dates[1] < dates[0]: _issue(issues,"date_range_invalid",no=no); event_ok=False; continue
                        if date.fromisoformat(dates[1]) < today: past=True
                    if past: _issue(issues,"date_in_past",no=no); outcome="scored_only"
                    elif event_ok:
                        outcome="report"
                        for event in events:
                            report_id="x_event_"+stable_id("xevent", normalize_text(event.get("event_name") or ""), event["date_start"], normalize_text(event.get("venue_name") or ""))
                            path=reports_dir/f"{report_id}.json"
                            if path.exists():
                                report=load(path,{})
                                existing=report.get("events", [{}])[0]
                                existing["detail_addendum"]=_add_url(existing.get("detail_addendum", ""), item["url"])
                            else:
                                report={"report_type":"official_notice","reported_at":datetime.now(timezone.utc).isoformat(),"source":{"report_id":report_id,"title":f"{event.get('event_name')}（X投稿より）","account_key":item.get("account") or "","url":item.get("url"),"notice_kind":"x_post","raw_text":item.get("text") or ""},"events":[{"action":"register_new","event_name_hint":event.get("event_name"),"event_year":int(event["date_start"][:4]),"date_start":event["date_start"],"date_end":event.get("date_end") or event["date_start"],"venue":{"name":event.get("venue_name"),"area":event.get("ward") or ""},"detail_addendum":_detail(event,item)}]}
                            path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); reports.append(report_id)
        rows[item["tweet_id"]]={"issued_at":(rows.get(item["tweet_id"],{}).get("issued_at")),"batch_id":packet.get("batch_id"),"applied_at":datetime.now(timezone.utc).isoformat(),"outcome":outcome}
    return {"batch_id":packet.get("batch_id"),"score_count":len(scores),"report_count":len(set(reports)),"bundled_count":len(reports)-len(set(reports)),"issues":issues,"scores":scores,"reports":sorted(set(reports))}


def main():
    p=argparse.ArgumentParser(); p.add_argument("--packet",type=Path,required=True); p.add_argument("--results",type=Path,required=True); p.add_argument("--state",type=Path,default=Path("data/x_extraction_state.json")); p.add_argument("--reports-dir",type=Path,default=Path("data/x_post_reports")); p.add_argument("--scores",type=Path,default=Path("data/x_post_scores.json")); p.add_argument("--out",type=Path,default=Path("data/x_post_extraction_apply_report.json")); a=p.parse_args()
    state=load(a.state,{"tweets":{}}); result=apply(load(a.packet,{}),load(a.results,{}),state,a.reports_dir)
    old=load(a.scores,[]); a.scores.parent.mkdir(parents=True,exist_ok=True); a.scores.write_text(json.dumps(old+result["scores"],ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); a.state.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"reports":result["report_count"],"issues":len(result["issues"])},ensure_ascii=False))


if __name__ == "__main__": main()
