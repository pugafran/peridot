import json
import time

import pytest

fastapi = pytest.importorskip('fastapi')
TestClient = pytest.importorskip('fastapi.testclient').TestClient

import peridot_gui


def test_meta_includes_runtime_and_presets():
    app = peridot_gui.create_app()
    c = TestClient(app)
    r = c.get('/api/meta')
    assert r.status_code == 200
    j = r.json()
    assert 'runtime' in j
    assert isinstance(j['runtime'], dict)
    assert 'os_name' in j['runtime']
    assert 'sys_platform' in j['runtime']
    assert 'presets' in j
    assert isinstance(j['presets'], list)


def test_pack_scan_validates_and_returns_shape():
    app = peridot_gui.create_app()
    c = TestClient(app)

    # Bad payloads
    r = c.post('/api/pack/scan', json={'paths': 'nope'})
    assert r.status_code == 400

    # Empty scan is allowed (returns 0 files, etc.)
    r = c.post('/api/pack/scan', json={'paths': []})
    assert r.status_code == 200
    j = r.json()
    assert j['files'] == 0
    assert j['bytes'] == 0
    assert isinstance(j.get('sensitive'), list)


def test_settings_endpoint_returns_path_and_settings_dict():
    app = peridot_gui.create_app()
    c = TestClient(app)
    r = c.get('/api/settings')
    assert r.status_code == 200
    j = r.json()
    assert 'settings_path' in j
    assert isinstance(j.get('settings'), dict)


def test_pack_endpoint_creates_job_and_job_status_is_queryable(monkeypatch):
    # Avoid actually spawning the peridot CLI during tests.
    def fake_launch_job(job, peridot_args):
        job.status = 'done'
        job.started_ts = time.time()
        job.finished_ts = time.time()
        job.result = {
            'ok': True,
            'output': 'C:/tmp/example.peridot',
            'output_bytes': 123,
        }

    monkeypatch.setattr(peridot_gui, '_launch_job', fake_launch_job)

    app = peridot_gui.create_app()
    c = TestClient(app)

    r = c.post('/api/pack', json={'name': 'test', 'paths': []})
    assert r.status_code == 200
    jid = r.json()['job_id']

    r = c.get(f'/api/jobs/{jid}')
    assert r.status_code == 200
    j = r.json()
    assert j['status'] in {'queued', 'running', 'done'}

    # cleanup
    peridot_gui._JOBS.pop(jid, None)


def test_sse_events_stream_yields_json_messages():
    # Build a fake job and ensure we can stream at least one message.
    jid = 'test-job-1'
    job = peridot_gui.Job(
        id=jid,
        kind='pack',
        status='running',
        created_ts=time.time(),
        started_ts=time.time(),
        result={'progress': {'type': 'scan_progress', 'files': 3}},
    )
    peridot_gui._JOBS[jid] = job

    app = peridot_gui.create_app()
    c = TestClient(app)

    with c.stream('GET', f'/api/jobs/{jid}/events') as r:
        assert r.status_code == 200
        assert r.headers['content-type'].startswith('text/event-stream')

        # Read a few chunks until we see a data: line.
        buf = ''
        for chunk in r.iter_text():
            buf += chunk
            if '\n\n' in buf and 'data:' in buf:
                break

    # Extract the first data payload and ensure it's valid JSON.
    data_lines = [ln for ln in buf.splitlines() if ln.startswith('data: ')]
    assert data_lines, buf
    payload = json.loads(data_lines[0].split('data: ', 1)[1])
    assert payload['id'] == jid
    assert payload['status'] == 'running'

    # cleanup
    peridot_gui._JOBS.pop(jid, None)
