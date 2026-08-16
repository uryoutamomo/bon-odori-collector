import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone, date
from pathlib import Path

from apply_x_extraction_results import apply
from build_x_extraction_packets import build, machine_dates


def voice(tweet_id, text, **extra):
    # 既定は「テストの now（2026-08-16）から見て対象になる日付」。voices.json は累積なので
    # build() は既定で前日以降しか拾わない（古い日付を試したいテストは posted_at を明示する）。
    return {"source": "x", "tweet_id": tweet_id, "url": f"https://x.example/{tweet_id}", "account": "@person", "posted_at": "2026-08-16T00:00:00+00:00", "text": text, **extra}


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

    def test_one_bad_event_does_not_discard_a_second_valid_event(self):
        text="8月1日に一丁目公園で一丁目盆踊り、8月20日に二丁目公園で二丁目盆踊りを開催"
        packet={"batch_id":"x","packets":[{"no":1,"tweet_id":"a","url":"https://x/a","text":text,"machine_extracted_dates":["2026-08-01","2026-08-20"]}]}
        good={"event_name":"二丁目盆踊り","date_start":"2026-08-20","venue_name":"二丁目公園","quote":"8月20日に二丁目公園で二丁目盆踊りを開催"}
        past={"event_name":"一丁目盆踊り","date_start":"2026-08-01","venue_name":"一丁目公園","quote":"8月1日に一丁目公園で一丁目盆踊り"}
        bad={"event_name":"捏造","date_start":"2026-08-20","venue_name":"ない公園","quote":"8月20日に二丁目公園で二丁目盆踊りを開催"}
        for rejected, issue in ((past,"date_in_past"),(bad,"venue_not_in_text")):
            with self.subTest(issue=issue), tempfile.TemporaryDirectory() as temp:
                state={"tweets":{}}; result=apply(packet,{"batch_id":"x","results":[{"no":1,"s":5,"events":[rejected,good]}]},state,Path(temp),today=date(2026,8,16))
                self.assertEqual(result["report_count"],1)
                self.assertIn(issue,[row["issue_type"] for row in result["issues"]])
                self.assertEqual(state["tweets"]["a"]["outcome"],"report")

    # --- 受け入れ条件1・4：処理済みは出ない／--reissue は発行済み抑止だけを外す ---
    def test_applied_post_is_never_reissued_even_with_reissue_flag(self):
        now=datetime(2026,8,16,tzinfo=timezone.utc)
        done={"tweets":{"a":{"issued_at":"2026-08-15T00:00:00+00:00","batch_id":"old","applied_at":"2026-08-15T01:00:00+00:00","outcome":"report"}}}
        self.assertEqual(build([voice("a","処理済みの投稿")],done,now=now),[])
        self.assertEqual(build([voice("a","処理済みの投稿")],done,now=now,reissue=True),[],
                         "--reissue は未処理の再発行のためのもので、処理済みを掘り返してはいけない")
        waiting={"tweets":{"b":{"issued_at":"2026-08-16T00:00:00+00:00","batch_id":"old","applied_at":None}}}
        self.assertEqual(build([voice("b","回答待ちの投稿")],waiting,now=now),[])
        self.assertEqual(len(build([voice("b","回答待ちの投稿")],waiting,now=now,reissue=True)[0]["packets"]),1)

    # --- 流量：累積voicesを初回に全部読ませない／上限超過は捨てずに残す ---
    def test_since_defaults_to_yesterday_and_max_batches_defers_the_rest(self):
        now=datetime(2026,8,16,12,tzinfo=timezone.utc)
        old=[voice(f"old{i}",f"古い投稿{i}",posted_at="2026-07-01T00:00:00+00:00") for i in range(3)]
        fresh=[voice(f"new{i}",f"新しい投稿{i}",posted_at="2026-08-16T00:00:00+00:00") for i in range(3)]
        packets=build(old+fresh,{"tweets":{}},batch_size=10,now=now)
        ids={item["tweet_id"] for packet in packets for item in packet["packets"]}
        self.assertEqual(ids,{"new0","new1","new2"},"既定では前日以降だけを対象にする")
        packets=build(old+fresh,{"tweets":{}},batch_size=10,now=now,since=date(2026,6,1))
        self.assertEqual(len({item["tweet_id"] for packet in packets for item in packet["packets"]}),6,
                         "--since を遡らせれば過去分も読める")
        # 上限を超えた分は state に issued が付かないので、次回そのまま出てくる
        capped=build(fresh,{"tweets":{}},batch_size=1,now=now,max_batches=2)
        self.assertEqual(len(capped),2)
        self.assertEqual(sum(len(p["packets"]) for p in capped),2,"上限を超えたバッチは出さない")

    # --- 受け入れ条件10・11：本文に無い日付／逆転した範囲 ---
    def test_dates_outside_the_text_and_reversed_ranges_are_rejected(self):
        packet={"batch_id":"x","packets":[{"no":1,"tweet_id":"a","url":"https://x/a","text":"8月20日と8月25日に公園で開催","machine_extracted_dates":["2026-08-20","2026-08-25"]}]}
        base={"event_name":"試験","venue_name":"公園","quote":"8月20日と8月25日に公園で開催"}
        cases=(({"date_start":"2026-09-09"},"date_not_in_text"),
               ({"date_start":"2026-08-25","date_end":"2026-08-20"},"date_range_invalid"))
        for extra, issue in cases:
            with self.subTest(issue=issue), tempfile.TemporaryDirectory() as temp:
                state={"tweets":{}}
                result=apply(packet,{"batch_id":"x","results":[{"no":1,"s":5,"events":[{**base,**extra}]}]},state,Path(temp),today=date(2026,8,16))
                self.assertEqual(result["report_count"],0)
                self.assertIn(issue,[row["issue_type"] for row in result["issues"]])

    # --- 部分回答：答えの無い投稿を処理済みにしない（INV-XPE-007） ---
    def test_partial_answer_leaves_unanswered_posts_for_the_next_packet(self):
        packet={"batch_id":"x","packets":[
          {"no":1,"tweet_id":"a","url":"https://x/a","text":"盆踊りの話","machine_extracted_dates":[]},
          {"no":2,"tweet_id":"b","url":"https://x/b","text":"別の投稿","machine_extracted_dates":[]}]}
        # 判定は1ターンで終わらないことがある。1件だけ答えて残りを次回へ回せる必要がある。
        answer={"batch_id":"x","results":[{"no":1,"s":3,"n":"内容あり"}]}
        with tempfile.TemporaryDirectory() as temp:
            state={"tweets":{"a":{"issued_at":"2026-08-16T00:00:00+00:00","batch_id":"x","applied_at":None},
                             "b":{"issued_at":"2026-08-16T00:00:00+00:00","batch_id":"x","applied_at":None}}}
            result=apply(packet,answer,state,Path(temp),today=date(2026,8,16))
            self.assertIn("missing_result",[row["issue_type"] for row in result["issues"]])
            self.assertIsNotNone(state["tweets"]["a"]["applied_at"],"答えたものは処理済みになる")
            self.assertIsNone(state["tweets"]["b"]["applied_at"],
                              "答えの無いものを処理済みにすると二度と読まれない")
            # 24時間後のbuildで b だけが戻ってくる
            packets=build([voice("a","盆踊りの話"),voice("b","別の投稿")],state,
                          now=datetime(2026,8,17,12,tzinfo=timezone.utc),batch_size=10)
            self.assertEqual({item["tweet_id"] for p in packets for item in p["packets"]},{"b"})

    # --- 受け入れ条件13・14：不明なno／4点以下は採点だけ残る ---
    def test_unknown_no_is_flagged_and_low_scores_keep_only_the_score(self):
        packet={"batch_id":"x","packets":[{"no":1,"tweet_id":"a","url":"https://x/a","text":"盆踊りの思い出話","machine_extracted_dates":[]}]}
        answer={"batch_id":"x","results":[{"no":1,"s":3,"n":"曲名が出ている"},{"no":99,"s":5}]}
        with tempfile.TemporaryDirectory() as temp:
            state={"tweets":{}}; result=apply(packet,answer,state,Path(temp),today=date(2026,8,16))
            self.assertEqual(result["report_count"],0)
            self.assertIn("unknown_packet",[row["issue_type"] for row in result["issues"]])
            self.assertEqual([(row["score"],row["note"]) for row in result["scores"]],[(3,"曲名が出ている")])
            self.assertEqual(state["tweets"]["a"]["outcome"],"scored_only")

    # --- 受け入れ条件18・19・21：束ねても代表は動かず、URLも重複しない ---
    def test_bundle_keeps_first_representative_and_never_rewrites_events(self):
        text="8月20日に試験公園で試験盆踊りを開催"
        first={"no":1,"tweet_id":"a","url":"https://x/first","account":"@a","text":text,"machine_extracted_dates":["2026-08-20","2026-08-21"]}
        # 後続の投稿は本文も date_end も違う。投稿順に関係なく代表が動かないことを見る
        # （実装は posted_at を見ずに「既にレポートがあるか」だけで判断するので、これがより強い検査になる）。
        later={"no":1,"tweet_id":"b","url":"https://x/later","account":"@b","text":text+"（21日まで）","machine_extracted_dates":["2026-08-20","2026-08-21"]}
        event={"event_name":"試験盆踊り","date_start":"2026-08-20","venue_name":"試験公園","quote":text}
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp); state={"tweets":{}}
            apply({"batch_id":"x","packets":[first]},{"batch_id":"x","results":[{"no":1,"s":5,"events":[event]}]},state,out,today=date(2026,8,16))
            apply({"batch_id":"y","packets":[later]},{"batch_id":"y","results":[{"no":1,"s":5,"events":[{**event,"date_end":"2026-08-21"}]}]},state,out,today=date(2026,8,16))
            # 同じ回答をもう一度取り込んでも増えない（受け入れ条件21・27）
            apply({"batch_id":"z","packets":[later]},{"batch_id":"z","results":[{"no":1,"s":5,"events":[{**event,"date_end":"2026-08-21"}]}]},state,out,today=date(2026,8,16))
            paths=list(out.glob("*.json")); self.assertEqual(len(paths),1)
            report=json.loads(paths[0].read_text(encoding="utf-8"))
            self.assertEqual(report["source"]["url"],"https://x/first","代表は初回で固定される")
            self.assertEqual(report["source"]["raw_text"],text,"後続投稿の本文で置き換わらない")
            self.assertEqual(report["events"][0]["date_end"],"2026-08-20",
                             "後から判明した date_end で events を書き換えない")
            detail=report["events"][0]["detail_addendum"]
            self.assertEqual(detail.count("https://x/later"),1,"同じURLを二度足さない")

    # --- 受け入れ条件（§7 出典）：URLの無い投稿からはレポートを作らない ---
    def test_post_without_url_never_becomes_a_report(self):
        packet={"batch_id":"x","packets":[{"no":1,"tweet_id":"a","url":"","text":"8月20日に試験公園で試験盆踊りを開催","machine_extracted_dates":["2026-08-20"]}]}
        event={"event_name":"試験盆踊り","date_start":"2026-08-20","venue_name":"試験公園","quote":"8月20日に試験公園で試験盆踊りを開催"}
        with tempfile.TemporaryDirectory() as temp:
            state={"tweets":{}}
            result=apply(packet,{"batch_id":"x","results":[{"no":1,"s":5,"events":[event]}]},state,Path(temp),today=date(2026,8,16))
            self.assertEqual(result["report_count"],0,"出典なしで正本factの材料を作らない")
            self.assertIn("missing_source_url",[row["issue_type"] for row in result["issues"]])

    # --- 受け入れ条件24＋note：公式は名前を出し、回答の n を詳細へ運ぶ ---
    def test_official_source_shows_its_name_and_carries_the_note(self):
        packet={"batch_id":"x","packets":[{"no":1,"tweet_id":"a","url":"https://x/a","account":"@city","account_name":"◯◯区役所",
                 "officiality":"registered_official_social","text":"8月20日に試験公園で試験盆踊りを開催","machine_extracted_dates":["2026-08-20"]}]}
        event={"event_name":"試験盆踊り","date_start":"2026-08-20","venue_name":"試験公園","quote":"8月20日に試験公園で試験盆踊りを開催"}
        with tempfile.TemporaryDirectory() as temp:
            state={"tweets":{}}
            apply(packet,{"batch_id":"x","results":[{"no":1,"s":5,"n":"町会の公式告知","events":[event]}]},state,Path(temp),today=date(2026,8,16))
            detail=json.loads(next(Path(temp).glob("*.json")).read_text(encoding="utf-8"))["events"][0]["detail_addendum"]
            self.assertIn("◯◯区役所",detail)
            self.assertIn("町会の公式告知",detail,"回答の n（resultレベル）を詳細へ運ぶ")

    # --- 受け入れ条件25・26：住所は入れない／年は機械が決める ---
    def test_report_omits_address_and_derives_year_from_date(self):
        packet={"batch_id":"x","packets":[{"no":1,"tweet_id":"a","url":"https://x/a","text":"1月10日に試験公園で新年盆踊りを開催","machine_extracted_dates":["2027-01-10"]}]}
        event={"event_name":"新年盆踊り","date_start":"2027-01-10","venue_name":"試験公園","ward":"足立区",
               "quote":"1月10日に試験公園で新年盆踊りを開催","event_year":1999}
        with tempfile.TemporaryDirectory() as temp:
            state={"tweets":{}}
            apply(packet,{"batch_id":"x","results":[{"no":1,"s":5,"events":[event]}]},state,Path(temp),today=date(2026,8,16))
            entry=json.loads(next(Path(temp).glob("*.json")).read_text(encoding="utf-8"))["events"][0]
            self.assertNotIn("address",entry["venue"],"住所は投稿から読めないので入れない")
            self.assertEqual(entry["event_year"],2027,"LLMが書いた年ではなく date_start から決める")

    # --- 受け入れ条件28：生成レポートがE0でevent_create候補になる ---
    def test_generated_report_becomes_an_e0_event_create_candidate(self):
        from event_model.local_judgment_migration import migrate_event_inbox_candidate, migrate_local_judgment_contract
        from master_rdb.master_db import init_db
        from review_inbox_adapters.build_event_inbox_candidates import run as e0_run
        packet={"batch_id":"x","packets":[{"no":1,"tweet_id":"a","url":"https://x/a","account":"@city","account_name":"◯◯区役所",
                 "officiality":"registered_official_social","text":"8月20日に試験公園で試験盆踊りを開催。曲目は東京音頭です","machine_extracted_dates":["2099-08-20"]}]}
        event={"event_name":"試験盆踊り","date_start":"2099-08-20","venue_name":"試験公園","ward":"足立区",
               "quote":"8月20日に試験公園で試験盆踊りを開催",
               "song_claims":[{"song_name":"東京音頭","claim_type":"announced","evidence_quote":"曲目は東京音頭です"}]}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); reports=root/"x_post_reports"; state={"tweets":{}}; songs={"observations":[]}
            result=apply(packet,{"batch_id":"x","results":[{"no":1,"s":5,"events":[event]}]},state,reports,
                         song_ledger=songs,today=date(2026,8,16))
            self.assertEqual(result["report_count"],1)
            db=root/"master.sqlite"; conn=init_db(db); migrate_local_judgment_contract(conn); migrate_event_inbox_candidate(conn); conn.commit(); conn.close()
            args=type("Args",(),{"report":[],"report_dir":[reports],"db":db,"out_db":root/"dry.sqlite","out_json":root/"e0.json",
                                 "out_md":root/"e0.md","max_candidates":200,"apply":False,"confirm":"","no_auto_migrate":False,"include_expired":False})()
            e0=e0_run(args)
            self.assertEqual(e0["summary"]["created"],1,f"E0が候補にできなかった: {e0['issues']}")
            dry=sqlite3.connect(root/"dry.sqlite")
            row=dry.execute("SELECT contract_domain, contract_lane, status, source_url, revision_family_key FROM review_inbox_items").fetchone()
            dry.close()
            self.assertEqual(row[:4],("event","event_create","candidate","https://x/a"))
            self.assertEqual(row[4],songs["observations"][0]["event_dependency_key"],
                             "曲claimのdependencyはE0が実際に作るfamily keyと一致する")

    def test_reused_legacy_report_keeps_its_existing_e0_family(self):
        from event_model.local_judgment_migration import migrate_event_inbox_candidate, migrate_local_judgment_contract
        from master_rdb.master_db import init_db
        from review_inbox_adapters.build_event_inbox_candidates import (
            EVENT_INBOX_CANDIDATE_CONFIRMATION,
            run as e0_run,
        )

        text = "8月20日に試験公園で試験盆踊りを開催。曲目は東京音頭です"
        event = {
            "event_name": "試験盆踊り", "date_start": "2099-08-20", "venue_name": "試験公園",
            "quote": "8月20日に試験公園で試験盆踊りを開催",
            "song_claims": [{
                "song_name": "東京音頭", "claim_type": "announced", "evidence_quote": "曲目は東京音頭です",
            }],
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); reports = root / "reports"
            first = {"no": 1, "tweet_id": "a", "url": "https://x/a", "text": text,
                     "machine_extracted_dates": ["2099-08-20"]}
            apply({"batch_id": "x", "packets": [first]},
                  {"batch_id": "x", "results": [{"no": 1, "s": 5, "events": [event]}]},
                  {"tweets": {}}, reports, today=date(2026, 8, 16))
            report_path = next(reports.glob("*.json"))
            legacy_report = json.loads(report_path.read_text(encoding="utf-8"))
            legacy_report["events"][0].pop("entry_id")
            report_path.write_text(json.dumps(legacy_report, ensure_ascii=False), encoding="utf-8")

            db = root / "master.sqlite"
            conn = init_db(db); migrate_local_judgment_contract(conn); migrate_event_inbox_candidate(conn)
            conn.commit(); conn.close()
            args = type("Args", (), {
                "report": [report_path], "report_dir": [], "db": db, "out_db": root / "unused.sqlite",
                "out_json": root / "e0.json", "out_md": root / "e0.md", "max_candidates": 20,
                "apply": True, "confirm": EVENT_INBOX_CANDIDATE_CONFIRMATION,
                "no_auto_migrate": True, "include_expired": False,
            })()
            first_e0 = e0_run(args)
            self.assertEqual(first_e0["summary"]["created"], 1)
            conn = sqlite3.connect(db)
            initial_family = conn.execute("SELECT revision_family_key FROM review_inbox_items").fetchone()[0]
            conn.close()

            second = {"no": 1, "tweet_id": "b", "url": "https://x/b", "text": text,
                      "machine_extracted_dates": ["2099-08-20"]}
            songs = {"observations": []}
            apply({"batch_id": "y", "packets": [second]},
                  {"batch_id": "y", "results": [{"no": 1, "s": 5, "events": [event]}]},
                  {"tweets": {}}, reports, song_ledger=songs, today=date(2026, 8, 16))
            second_e0 = e0_run(args)
            self.assertEqual(second_e0["summary"]["created"], 0)
            conn = sqlite3.connect(db)
            families = conn.execute("SELECT revision_family_key FROM review_inbox_items").fetchall()
            conn.close()
            self.assertEqual(families, [(initial_family,)])
            self.assertEqual(songs["observations"][0]["event_dependency_key"], initial_family)
