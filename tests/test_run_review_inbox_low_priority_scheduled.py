import hashlib, json, sqlite3, tempfile
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
from master_db import init_db
from review_inbox import inbox_rows
from review_inbox_source_writer import ArtifactState, CasConflictError, SourceWriterError
from run_review_inbox_low_priority_scheduled import CONFIRM, run_scheduled

JST=ZoneInfo("Asia/Tokyo")
ENV={"REVIEW_INBOX_LOW_PRIORITY_SCHEDULED_ENABLED":"true","REVIEW_INBOX_DUAL_WRITE_MODE":"bulk","REVIEW_INBOX_CAS_PUBLISH_ENABLED":"true","REVIEW_INBOX_READER_MODE":"legacy","REVIEW_INBOX_LEGACY_WRITER_ENABLED":"true"}
CUTOVER_ENV={**ENV,"REVIEW_INBOX_READER_MODE":"inbox","REVIEW_INBOX_LEGACY_WRITER_ENABLED":"false"}

class Store:
    def __init__(self,path): self.data=Path(path).read_bytes(); self.snapshot_id="R1"; self.calls=0
    def status(self): return ArtifactState(hashlib.sha256(self.data).hexdigest(),self.snapshot_id)
    def fetch(self,destination): Path(destination).write_bytes(self.data)
    def publish(self,source,*,expected_remote_checksum):
        if self.status().checksum != expected_remote_checksum: raise CasConflictError("conflict")
        self.data=Path(source).read_bytes(); self.calls+=1; self.snapshot_id=f"R{self.calls+1}"; return self.status()

def setup(tmp):
    root=Path(tmp); payloads={
      "daily_song_candidate":{"rows":[{"term":"曲","canonical_song_name":"曲"}]},
      "daily_term_candidate":{"rows":[{"term":"用語","category":"用語","type":"語"}]},
      "accepted_venue_song_missing_venue":{"rows":[{"suggested_venue":"会場"}]},
      "historical_reference_quality":{"review":[{"quality_review_id":"q","event_name":"祭り","issue_codes":["historical_songs_missing"]}]},
      "publication_gap":{"rows":[{"gap_id":"g","term":"差分","recommended_action":"needs_research"}]},
    }
    sources=[]
    for source,payload in payloads.items():
        path=root/f"{source}.json"; path.write_text(json.dumps(payload),encoding="utf-8"); sources.append(f"{source}={path}")
    return Namespace(source=sources,evidence_dir=root/"evidence",observation_id="obs",public_today="2026-07-20",bucket="",prefix="",work_dir=root/"work",execute=True,confirm=CONFIRM)

def digest(_db,*,today): return hashlib.sha256(today.encode()).hexdigest()

def test_all_five_sources_publish_with_audited_evidence():
    with tempfile.TemporaryDirectory() as tmp:
        args=setup(tmp); db=Path(tmp)/"db.sqlite"; conn=init_db(db); conn.commit(); conn.close(); store=Store(db)
        summary=run_scheduled(args,environ=ENV,now=datetime(2026,7,20,15,13,tzinfo=JST),store_factory=lambda _:store,digest_function=digest)
        check=Path(tmp)/"check.sqlite"; check.write_bytes(store.data)
        with sqlite3.connect(check) as conn: rows=inbox_rows(conn,status=None)
        files=list(Path(args.evidence_dir).glob("*-report.json"))
    assert summary["source_count"] == summary["published_count"] == store.calls == 5
    assert summary["unmapped_count"] == 0 and len(rows) == 5 and len(files) == 5

def test_default_off_and_incomplete_source_set_stop_before_store():
    with tempfile.TemporaryDirectory() as tmp:
        args=setup(tmp)
        with pytest.raises(SourceWriterError,match="execution is off"): run_scheduled(Namespace(**{**vars(args),"execute":False,"confirm":""}),environ={},store_factory=lambda _:pytest.fail("store"))
        with pytest.raises(SourceWriterError,match="requires all B4 sources"): run_scheduled(Namespace(**{**vars(args),"source":args.source[:-1]}),environ=ENV,store_factory=lambda _:pytest.fail("store"))

def test_cutover_pair_is_recorded_in_every_source_report():
    with tempfile.TemporaryDirectory() as tmp:
        args=setup(tmp); db=Path(tmp)/"db.sqlite"; conn=init_db(db); conn.commit(); conn.close(); store=Store(db)
        run_scheduled(args,environ=CUTOVER_ENV,now=datetime(2026,7,20,15,13,tzinfo=JST),store_factory=lambda _:store,digest_function=digest)
        entrypoints=[json.loads(path.read_text())["entrypoint"] for path in Path(args.evidence_dir).glob("*-report.json")]
    assert len(entrypoints) == 5
    assert all(value["reader_mode"] == "inbox" for value in entrypoints)
    assert all(value["legacy_writer_retained"] is False for value in entrypoints)

def test_malformed_later_source_stops_before_remote_artifact_access():
    with tempfile.TemporaryDirectory() as tmp:
        args=setup(tmp)
        gap=Path(next(value.split("=",1)[1] for value in args.source if value.startswith("publication_gap=")))
        gap.write_text(json.dumps({"rows":[{"gap_id":"g","recommended_action":"publish"}]}))
        with pytest.raises(SourceWriterError,match="unsupported publication gap action"):
            run_scheduled(args,environ=ENV,store_factory=lambda _:pytest.fail("store"))

def test_cron_window_stops_before_store():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(SourceWriterError,match="17:20-18:00"): run_scheduled(setup(tmp),environ=ENV,now=datetime(2026,7,20,17,30,tzinfo=JST),store_factory=lambda _:pytest.fail("store"))
