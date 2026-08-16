import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import verify_detail_cleanup_repair as verifier


class VerifyDetailCleanupRepairTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name); self.before=root/'before.sqlite'; self.after=root/'after.sqlite'; self.report=root/'report.json'; self.apply=root/'apply.json'
        self.ids=[f'occ_{i:02}' for i in range(14)]; self.expected={key:f'new {key}' for key in self.ids}
        report = {'report_type':'detail_cleanup_repair','events':[{'occurrence_id':key,'detail_replacement':value} for key,value in self.expected.items()], 'expected_current_detail_sha256':{key:'a'*64 for key in self.ids}}
        report['report_sha256'] = verifier.hashlib.sha256(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
        self.report.write_text(json.dumps(report),encoding='utf-8')
        conn=sqlite3.connect(self.before); conn.executescript('CREATE TABLE event_occurrences(occurrence_id TEXT PRIMARY KEY, detail TEXT, updated_at TEXT, source_url TEXT); CREATE TABLE other(id TEXT PRIMARY KEY, value TEXT);')
        for key in self.ids: conn.execute('INSERT INTO event_occurrences VALUES (?, ?, ?, ?)',(key,'old','old','source'))
        conn.execute("INSERT INTO event_occurrences VALUES ('untouched','same','old','source')"); conn.execute("INSERT INTO other VALUES ('x','same')"); conn.commit(); conn.close()
        shutil.copyfile(self.before,self.after); conn=sqlite3.connect(self.after)
        for key,value in self.expected.items(): conn.execute('UPDATE event_occurrences SET detail=?, updated_at=? WHERE occurrence_id=?',(value,'new',key))
        conn.commit(); conn.close()
        self.apply.write_text(json.dumps({'summary':{'issues_count':0,'issues_by_severity':{}},'audit':{'issue_count':0,'issues_by_severity':{}},'applied':{'events_applied':[{}]*14,'events_unresolved':[]},'write_guard':{'db_committed':True,'rolled_back':False}}),encoding='utf-8')
        self.public_before=root/'public-before.json'; self.public_after=root/'public-after.json'; self.map_before=root/'map-before.json'; self.map_after=root/'map-after.json'
        before=[]; source_rows=[]
        for index,key in enumerate(self.ids):
            event={'name':f'event {index}','venue':f'venue {index}','date':'2026-08-01','date_end':'2026-08-01','detail':'old detail','url':f'https://example.test/{index}'}
            before.append(event); source_rows.append({'public_event_key':'|'.join(event[field] for field in ('name','venue','date','date_end')),'occurrence_id':key})
        untouched={'name':'untouched','venue':'venue','date':'2026-08-02','date_end':'2026-08-02','detail':'same','url':'https://example.test/untouched'}
        before.append(untouched); source_rows.append({'public_event_key':'|'.join(untouched[field] for field in ('name','venue','date','date_end')),'occurrence_id':'untouched'})
        after=json.loads(json.dumps(before))
        for index,key in enumerate(self.ids): after[index]['detail']=self.expected[key]
        self.public_before.write_text(json.dumps(before),encoding='utf-8'); self.public_after.write_text(json.dumps(after),encoding='utf-8')
        source_map={'rows':source_rows}; self.map_before.write_text(json.dumps(source_map),encoding='utf-8'); self.map_after.write_text(json.dumps(source_map),encoding='utf-8')
    def verify(self): return verifier.verify(self.before,self.after,self.report,self.apply)
    def test_accepts_exact_detail_changes(self): self.assertEqual(self.verify()['count'],14)
    def test_rejects_non_detail_change(self):
        c=sqlite3.connect(self.after); c.execute("UPDATE event_occurrences SET source_url='x' WHERE occurrence_id='occ_00'"); c.commit(); c.close()
        with self.assertRaisesRegex(ValueError,'non-detail'): self.verify()
    def test_rejects_other_table_change(self):
        c=sqlite3.connect(self.after); c.execute("UPDATE other SET value='x'"); c.commit(); c.close()
        with self.assertRaisesRegex(ValueError,'out-of-scope'): self.verify()
    def test_rejects_bad_apply_report(self):
        self.apply.write_text(json.dumps({'summary':{'issues_count':1},'audit':{'issue_count':0},'applied':{'events_applied':[{}]*14,'events_unresolved':[]},'write_guard':{'db_committed':True}}),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'issues'): self.verify()
    def test_rejects_tampered_report_digest(self):
        report = json.loads(self.report.read_text(encoding='utf-8')); report['events'][0]['detail_replacement'] = 'tampered'; self.report.write_text(json.dumps(report), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'digest'): self.verify()
    def verify_public(self): return verifier.verify_public(self.public_before,self.public_after,self.map_before,self.map_after,self.expected)
    def write_public_after(self, rows): self.public_after.write_text(json.dumps(rows),encoding='utf-8')
    def test_public_accepts_only_target_detail_changes(self): self.verify_public()
    def test_public_rejects_out_of_scope_detail_change(self):
        rows=json.loads(self.public_after.read_text(encoding='utf-8')); rows[-1]['detail']='changed'; self.write_public_after(rows)
        with self.assertRaisesRegex(ValueError,'unexpected public'): self.verify_public()
    def test_public_rejects_target_non_detail_change(self):
        rows=json.loads(self.public_after.read_text(encoding='utf-8')); rows[0]['url']='https://example.test/changed'; self.write_public_after(rows)
        with self.assertRaisesRegex(ValueError,'outside detail'): self.verify_public()
    def test_public_rejects_event_addition_or_deletion(self):
        rows=json.loads(self.public_after.read_text(encoding='utf-8'))
        for changed in (rows[:-1], rows + [dict(rows[-1], name='added')]):
            with self.subTest(event_count=len(changed)):
                self.write_public_after(changed)
                with self.assertRaisesRegex(ValueError,'(key/count|source map exactly)'): self.verify_public()
    def test_public_rejects_duplicate_source_occurrence_id(self):
        source=json.loads(self.map_after.read_text(encoding='utf-8')); source['rows'][-1]['occurrence_id']=self.ids[0]; self.map_after.write_text(json.dumps(source),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'unique'): self.verify_public()
    def test_cli_writes_result_json_without_passing_out_to_verify(self):
        out = Path(self.tmp.name) / 'cli-result.json'
        result = subprocess.run([sys.executable, 'scripts/verify_detail_cleanup_repair.py', '--before', str(self.before), '--after', str(self.after), '--report', str(self.report), '--apply-report', str(self.apply), '--out', str(out)], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['count'], 14)
if __name__=='__main__': unittest.main()
