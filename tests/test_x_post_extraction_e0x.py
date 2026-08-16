import tempfile
import unittest
from datetime import datetime, timezone, date
from pathlib import Path

from apply_x_extraction_results import apply
from build_x_extraction_packets import build, machine_dates


def voice(tweet_id, text, **extra):
    return {"source": "x", "tweet_id": tweet_id, "url": f"https://x.example/{tweet_id}", "account": "@person", "posted_at": "2026-08-10T00:00:00+00:00", "text": text, **extra}


class XPostExtractionE0XTest(unittest.TestCase):
    def test_build_keeps_non_bon_post_and_state_reissue_rules(self):
        now=datetime(2026,8,16,tzinfo=timezone.utc); voices=[voice("a","普通の投稿"),voice("b","普通の投稿")]
        packets=build(voices,{"tweets":{"a":{"issued_at":"2026-08-16T00:00:00+00:00","batch_id":"old","applied_at":None}}},now=now)
        self.assertEqual(packets,[],"same normalized text is one packet and issued one is held")
        packets=build(voices,{"tweets":{"a":{"issued_at":"2026-08-14T00:00:00+00:00","batch_id":"old","applied_at":None}}},now=now)
        self.assertEqual(len(packets[0]["packets"]),1)
        self.assertEqual(machine_dates("8/20 18時 1月10日", "2026-08-10T00:00:00+00:00"),["2026-08-20","2027-01-10"])

    def test_apply_fails_closed_and_bundles_without_replacing_source(self):
        packet={"batch_id":"x_extraction_20260816_01","packets":[
          {"no":1,"tweet_id":"a","url":"https://x/a","account":"@private","officiality":"unknown_or_personal_social","text":"8月20日に試験公園で試験盆踊りを開催","machine_extracted_dates":["2026-08-20"]},
          {"no":2,"tweet_id":"b","url":"https://x/b","account":"@private2","officiality":"unknown_or_personal_social","text":"8月20日に試験公園で試験盆踊りを開催","machine_extracted_dates":["2026-08-20"]}]}
        event={"event_name":"試験盆踊り","date_start":"2026-08-20","venue_name":"試験公園","ward":"足立区","quote":"8月20日に試験公園で試験盆踊りを開催"}
        answer={"batch_id":packet["batch_id"],"results":[{"no":1,"s":5,"events":[event]},{"no":2,"s":5,"events":[event]}]}
        with tempfile.TemporaryDirectory() as temp:
            state={"tweets":{}}; result=apply(packet,answer,state,Path(temp),today=date(2026,8,16))
            self.assertEqual(result["report_count"],1)
            report=next(Path(temp).glob("*.json")).read_text()
            self.assertIn("https://x/a",report); self.assertIn("https://x/b",report)
            self.assertNotIn("@private",__import__("json").loads(report)["events"][0]["detail_addendum"])
            self.assertEqual({row["outcome"] for row in state["tweets"].values()},{"report"})

    def test_invalid_quote_and_past_date_are_not_reports_but_are_applied(self):
        packet={"batch_id":"x","packets":[{"no":1,"tweet_id":"a","url":"https://x/a","text":"8月1日に公園で開催","machine_extracted_dates":["2026-08-01"]},{"no":2,"tweet_id":"b","url":"https://x/b","text":"8月20日に公園で開催","machine_extracted_dates":["2026-08-20"]}]}
        answer={"batch_id":"x","results":[{"no":1,"s":5,"events":[{"event_name":"x","date_start":"2026-08-01","venue_name":"公園","quote":"8月1日に公園で開催"}]},{"no":2,"s":5,"events":[{"event_name":"x","date_start":"2026-08-20","venue_name":"公園","quote":"存在しない"}]}]}
        with tempfile.TemporaryDirectory() as temp:
            state={"tweets":{}}; result=apply(packet,answer,state,Path(temp),today=date(2026,8,16))
            self.assertEqual(result["report_count"],0)
            self.assertIn("date_in_past",[x["issue_type"] for x in result["issues"]]); self.assertIn("quote_not_in_text",[x["issue_type"] for x in result["issues"]])
            self.assertEqual(state["tweets"]["a"]["outcome"],"scored_only"); self.assertEqual(state["tweets"]["b"]["outcome"],"issue")
