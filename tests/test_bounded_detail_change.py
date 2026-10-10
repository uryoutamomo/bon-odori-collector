import copy
import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
import yaml

from scripts.run_bounded_detail_change import (
    ALLOWED, bounded_public_rows, inspect_master, validate_control,
    validate_requests, verify_db_scope, SUMMARY_URL, FOURTH_URL, execute,
)

ROOT = Path(__file__).resolve().parents[1]


def control():
    return json.loads((ROOT / 'data/change_requests/ebara_official_20261010_cloud_control.json').read_text())


def payload():
    return {'request_type': 'rdb_change_requests', 'requests': [
        {'request_id': 'ebara_official_20261010_' + key,
         'change_type': 'confirm_current_year_date', 'occurrence_id': key,
         'event_year': 2026, 'date_start': ALLOWED[key][0], 'confidence': 'confirmed',
         **values, 'source': {'kind': 'official_current_year', 'platform': 'web',
             'url': FOURTH_URL if key == 'occ_400f1f551ca689a7' else SUMMARY_URL},
         'dry_run_only': True}
        for key, values in control()['scope'].items()]}


def test_control_rejects_apply_without_review_and_expansion():
    c = control()
    validate_control(c)
    for changes in ({'stage': 'apply'}, {'request_ref': 'main'}, {'scope': {}}, {'request_path': '../../other.json'}):
        with pytest.raises(ValueError):
            validate_control(dict(c, **changes))


def test_requests_are_pinned_and_no_new_venue_or_date_changes(tmp_path):
    p = payload()
    path = tmp_path / 'request.json'
    c = control()
    for edit in ('valid', 'scope', 'venue', 'date', 'detail', 'source'):
        changed = copy.deepcopy(p)
        request = changed['requests'][0]
        if edit == 'scope':
            request['occurrence_id'] = 'unapproved'
        if edit == 'venue':
            request['venue'] = {'name': '別会場'}
        if edit == 'date':
            request['date_start'] = '2026-10-12'
        if edit == 'detail':
            request['detail_replacement'] = '未承認の文面'
        if edit == 'source':
            request['source']['url'] = 'https://example.com/'
        path.write_text(json.dumps(changed))
        c['request_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        if edit == 'valid':
            validate_requests(c, path)
        else:
            with pytest.raises(ValueError):
                validate_requests(c, path)
    c['request_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='snapshot'):
        validate_requests(c, path)


def test_whole_database_guard_detects_unrelated_mutation_and_deletion(tmp_path):
    before, after = tmp_path / 'before.db', tmp_path / 'after.db'
    for db in (before, after):
        with sqlite3.connect(db) as conn:
            conn.executescript('CREATE TABLE event_occurrences (occurrence_id TEXT, detail TEXT); CREATE TABLE songs (id TEXT, name TEXT);')
            conn.executemany('INSERT INTO event_occurrences VALUES (?,?)', [(k, 'old') for k in ALLOWED] + [('other', 'old')])
            conn.execute("INSERT INTO songs VALUES ('song', 'old')")
    requests = payload()['requests']
    with sqlite3.connect(after) as conn:
        conn.execute('UPDATE event_occurrences SET detail=? WHERE occurrence_id=?', ('new', next(iter(ALLOWED))))
    assert verify_db_scope(before, after, requests) == {'event_occurrences': 1}
    with sqlite3.connect(after) as conn:
        conn.execute("DELETE FROM event_occurrences WHERE occurrence_id='other'")
    with pytest.raises(ValueError, match='out-of-scope'):
        verify_db_scope(before, after, requests)
    with sqlite3.connect(after) as conn:
        conn.execute("INSERT INTO event_occurrences VALUES ('other','old')")
        conn.execute("UPDATE songs SET name='changed'")
    with pytest.raises(ValueError, match='songs'):
        verify_db_scope(before, after, requests)


def test_projection_guard_preserves_membership_and_rejects_unrelated_fields():
    requests = payload()['requests']
    current = json.loads((ROOT / 'data/public/events_public.json').read_text())
    proposed = copy.deepcopy(current)
    indexed = {row['occurrence_id']: row for row in proposed}
    for request in requests:
        indexed[request['occurrence_id']]['detail'] = request['detail_replacement']
    rows = bounded_public_rows(current, proposed, current, requests)
    assert len(rows) == 3
    scoped = indexed[requests[0]['occurrence_id']]
    scoped['venue'] = '別会場'
    with pytest.raises(ValueError, match='projection'):
        bounded_public_rows(current, proposed, current, requests)
    scoped['venue'] = ALLOWED[scoped['occurrence_id']][1]
    other = next(row for row in proposed if row['occurrence_id'] not in ALLOWED)
    other['detail'] = 'unrelated'
    with pytest.raises(ValueError, match='projection'):
        bounded_public_rows(current, proposed, current, requests)
    with pytest.raises(ValueError, match='membership'):
        bounded_public_rows(current, proposed[1:], current, requests)


def test_master_snapshot_requires_old_hash_and_verified_venue(tmp_path):
    db = tmp_path / 'master.db'
    requests = payload()['requests']
    public = {r['occurrence_id']: r for r in json.loads((ROOT / 'data/public/events_public.json').read_text())}
    with sqlite3.connect(db) as conn:
        conn.executescript('CREATE TABLE venues (venue_id TEXT, canonical_name TEXT); CREATE TABLE event_occurrences (occurrence_id TEXT, venue_id TEXT, date_start TEXT, date_end TEXT, detail TEXT, event_year INTEGER);')
        for request in requests:
            key = request['occurrence_id']
            conn.execute('INSERT INTO venues VALUES (?,?)', (key, ALLOWED[key][1]))
            conn.execute('INSERT INTO event_occurrences VALUES (?,?,?,?,?,2026)', (key, key, ALLOWED[key][0], None, public[key]['detail']))
    inspect_master(db, requests)
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE event_occurrences SET detail=? WHERE occurrence_id=?', ('changed', requests[0]['occurrence_id']))
    with pytest.raises(ValueError, match='hash mismatch'):
        inspect_master(db, requests)


def test_dedicated_workflow_has_only_existing_permissions_and_main_triggers():
    text = (ROOT / '.github/workflows/bounded-detail-change.yml').read_text()
    # BaseLoader keeps the YAML 1.2 GitHub "on" key as a string.
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert workflow['permissions'] == {'contents': 'read', 'id-token': 'write'}
    assert workflow['on']['push']['branches'] == ['main']
    assert 'pull_request' not in workflow['on']
    assert workflow['concurrency'] == {'group': 'bon-odori-master-rdb', 'cancel-in-progress': 'false'}
    assert text.index('Run full tests before production access') < text.index('Configure existing AWS role')
    artifact = workflow['jobs']['correction']['steps'][-1]['with']['path']
    assert '.sqlite' not in artifact
    assert 'collect.py' not in text and 'send_mail' not in text


def integration_fixture(tmp_path, monkeypatch, stage):
    from master_rdb.master_db import SCHEMA
    import report_apply.apply_change_requests as apply_module
    import scripts.run_bounded_detail_change as module
    from scripts.promote_change_requests_for_review import promote_payload
    root = tmp_path / 'repo'
    (root / 'data/public').mkdir(parents=True)
    published = [r for r in json.loads((ROOT / 'data/public/events_public.json').read_text()) if r['occurrence_id'] in ALLOWED]
    public_path = root / 'data/public/events_public.json'
    public_path.write_text(json.dumps(published, ensure_ascii=False))
    db = root / 'data/master.sqlite'
    with sqlite3.connect(db) as conn:
        conn.executescript(SCHEMA)
        for row in published:
            key = row['occurrence_id']
            conn.execute("INSERT INTO venues (venue_id,canonical_name,normalized_name,area,address,review_status,created_at,updated_at) VALUES (?,?,?,?,?,'active','now','now')", (key,row['venue'],row['venue'],'品川区',row['address']))
            conn.execute("INSERT INTO event_series (series_id,series_key,canonical_name,normalized_name,status,created_at,updated_at) VALUES (?,?,?,?,'active','now','now')", (key,key,row['name'],row['name']))
            conn.execute("INSERT INTO event_occurrences (occurrence_id,series_id,venue_id,event_year,display_name,date_start,date_end,date_status,lifecycle_status,current_event_state,date_certainty_tier,confidence,detail,created_at,updated_at) VALUES (?,?,?,2026,?,?,?,'confirmed','published','confirmed','confirmed','confirmed',?,'now','now')", (key,key,key,row['name'],row['date'],row['date'],row['detail']))
            conn.execute("INSERT INTO occurrence_dates (occurrence_date_id,occurrence_id,date_start,date_end,date_type,confidence,basis,created_at) VALUES (?,?,?,?,'confirmed','confirmed','old','now')", (key,key,row['date'],row['date']))
    p = payload()
    c = control()
    c['stage'] = stage
    c['collector_public_sha256'] = hashlib.sha256(public_path.read_bytes()).hexdigest()
    if stage == 'apply':
        p, _ = promote_payload(p, reviewed_by='おと（Codex）', review_note='Reviewed integration dry-run')
        c.update(request_path='data/change_requests/ebara_official_20261010_reviewed.json',
            expected_remote_checksum=hashlib.sha256(db.read_bytes()).hexdigest(),
            reviewed_run_id=123, reviewed_by='おと（Codex）', review_note='Reviewed dry-run 123')
    request_file = tmp_path / 'requests.json'
    request_file.write_text(json.dumps(p, ensure_ascii=False))
    c['request_sha256'] = hashlib.sha256(request_file.read_bytes()).hexdigest()
    control_file = tmp_path / 'control.json'
    control_file.write_text(json.dumps(c, ensure_ascii=False))
    monkeypatch.setattr(module, 'ROOT', root)
    monkeypatch.setattr(apply_module, 'PREFLIGHT_DB', tmp_path / 'preflight.sqlite')
    monkeypatch.setattr(apply_module, 'BACKUP_DIR', tmp_path / 'backups')
    refresh = apply_module.refresh_manifest_database_state
    monkeypatch.setattr(apply_module, 'refresh_manifest_database_state', lambda path, updated_at: refresh(path, manifest_path=tmp_path / 'manifest.json', updated_at=updated_at))
    def projected(path, today):
        result = copy.deepcopy(published)
        with sqlite3.connect(path) as conn:
            for row in result:
                row['detail'] = conn.execute('SELECT detail FROM event_occurrences WHERE occurrence_id=?', (row['occurrence_id'],)).fetchone()[0]
        return result
    monkeypatch.setattr(module, 'project', projected)
    calls = []
    remote = tmp_path / 'remote.sqlite'
    shutil.copy2(db, remote)
    def cloud(command, **kwargs):
        calls.append(command)
        if 'publish' in command:
            assert command[command.index('--expect-remote-checksum') + 1] == hashlib.sha256(remote.read_bytes()).hexdigest()
            shutil.copy2(db, remote)
        else:
            shutil.copy2(remote, db)
    monkeypatch.setattr(module.subprocess, 'run', cloud)
    args = argparse.Namespace(control=control_file, requests=request_file, master_db=db,
        output=tmp_path / 'output', today='2026-10-10', snapshot_id='bounded-detail-test-1', validate_only=False)
    return args, calls, remote


def test_cloud_dry_run_does_not_publish_or_mutate_master(tmp_path, monkeypatch):
    args, calls, _ = integration_fixture(tmp_path, monkeypatch, 'dry_run')
    original = args.master_db.read_bytes()
    receipt = execute(args)
    assert args.master_db.read_bytes() == original
    assert calls == [] and len(receipt['public_rows']) == 3
    assert set(receipt['db_changes']) <= {'event_occurrences','occurrence_dates','evidence_items','occurrence_evidence_links'}


def test_cloud_apply_uses_cas_and_refetch_without_collection(tmp_path, monkeypatch):
    args, calls, remote = integration_fixture(tmp_path, monkeypatch, 'apply')
    receipt = execute(args)
    assert len(calls) == 2 and 'publish' in calls[0] and 'fetch' in calls[1]
    assert '--force' not in calls[0]
    assert receipt['published_checksum'] == hashlib.sha256(remote.read_bytes()).hexdigest()
    assert len(receipt['public_rows']) == 3


def test_cloud_apply_rejects_remote_change_since_manual_review(tmp_path, monkeypatch):
    args, calls, _ = integration_fixture(tmp_path, monkeypatch, 'apply')
    with sqlite3.connect(args.master_db) as conn:
        conn.execute("UPDATE event_series SET public_intro='another operation'")
    with pytest.raises(ValueError, match='master changed'):
        execute(args)
    assert calls == []
