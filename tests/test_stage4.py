import asyncio
import fcntl
import json

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes.research import research_events
from deepdive.orchestration.models import ResearchSettings
from deepdive.storage.database import ResearchRepository
from deepdive.storage.worker_status import worker_running


def terminal_task(repository):
    task=repository.create('Test event replay',ResearchSettings())
    repository.event(task['id'],'plan.created',{'note':'中文\nnewline remains data'})
    repository.transition(task['id'],'CANCELLED','test_cancelled')
    return task


def parse_frames(text):
    frames=[]
    for block in text.strip().split('\n\n'):
        rows=dict(line.split(': ',1) for line in block.splitlines() if ': ' in line)
        if 'data' in rows:
            rows['data']=json.loads(rows['data'])
            frames.append(rows)
    return frames


def test_sse_replays_real_events_and_ends_for_terminal_task():
    with TestClient(app) as client:
        repo=app.state.research_repository
        task=terminal_task(repo)
        response=client.get('/api/research/'+task['id']+'/events')
        assert response.status_code==200
        assert response.headers['content-type'].startswith('text/event-stream')
        assert response.headers['cache-control']=='no-cache, no-transform'
        frames=parse_frames(response.text)
        persisted=repo.events_after(task['id'])
        assert [int(frame['id']) for frame in frames if 'id' in frame]==[event['id'] for event in persisted]
        assert frames[1]['data']['data']['note']=='中文\nnewline remains data'
        assert frames[-1]['event']=='stream.end'
        assert frames[-1]['data']['status']=='CANCELLED'


def test_sse_last_event_id_reconnect_and_task_isolation():
    with TestClient(app) as client:
        repo=app.state.research_repository
        first=terminal_task(repo)
        second=terminal_task(repo)
        cursor=repo.events_after(first['id'])[1]['id']
        response=client.get('/api/research/'+first['id']+'/events',headers={'Last-Event-ID':str(cursor)})
        frames=parse_frames(response.text)
        assert [frame['data']['type'] for frame in frames if 'id' in frame]==['task.status']
        assert all(frame['data']['id']>cursor for frame in frames if 'id' in frame)
        assert second['id'] not in response.text
        assert 'plan.created' not in response.text


@pytest.mark.parametrize('cursor',['-1','garbage','1.2','9999999999999999999999','１２'])
def test_sse_rejects_invalid_cursor(cursor):
    with TestClient(app) as client:
        task=terminal_task(app.state.research_repository)
        # ASGI can represent arbitrary header bytes; httpx restricts outgoing Unicode headers.
        if not cursor.isascii():
            cursor='invalid'
        response=client.get('/api/research/'+task['id']+'/events',headers={'Last-Event-ID':cursor})
        assert response.status_code==422
        assert response.json()['error']['code']=='invalid_event_cursor'


def test_sse_missing_task_returns_json_error():
    with TestClient(app) as client:
        response=client.get('/api/research/missing/events')
        assert response.status_code==404
        assert response.json()['error']['code']=='task_not_found'


def test_cancel_event_is_durable_and_idempotent():
    with TestClient(app) as client:
        repo=app.state.research_repository
        task=repo.create('question',ResearchSettings())
        for _ in range(2):
            assert client.post('/api/research/'+task['id']+'/cancel').json()['cancel_requested']
        assert sum(event['type']=='task.cancel_requested' for event in repo.events_after(task['id']))==1


def test_real_counts_filtered_history_and_download():
    with TestClient(app) as client:
        repo=app.state.research_repository
        queued=repo.create('queued',ResearchSettings())
        cancelled=terminal_task(repo)
        completed=repo.create('done',ResearchSettings())
        for status in ('PLANNING','RESEARCHING','VERIFYING','WRITING','COMPLETED'):
            repo.transition(completed['id'],status)
        repo.save_report(completed['id'],'# Real stored report')
        assert client.get('/api/research/summary').json()=={'total':3,'running':1,'completed':1,'stopped':1}
        response=client.get('/api/research?status=running&limit=1')
        assert response.headers['x-total-count']=='1'
        assert [task['id'] for task in response.json()]==[queued['id']]
        assert client.get('/api/research?status=completed').json()[0]['id']==completed['id']
        assert client.get('/api/research?status=stopped').json()[0]['id']==cancelled['id']
        assert client.get('/api/research?status=invalid').status_code==422
        report=client.get('/api/research/'+completed['id']+'/report?download=true')
        assert report.status_code==200
        assert report.headers['content-disposition']=='attachment; filename="deepdive-'+completed['id']+'.md"'
        assert report.text=='# Real stored report'


def test_worker_health_checks_lock_without_creating_it(tmp_path):
    assert not worker_running(tmp_path)
    assert not (tmp_path/'worker.lock').exists()
    with (tmp_path/'worker.lock').open('a') as handle:
        assert not worker_running(tmp_path)
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert worker_running(tmp_path)
    assert not worker_running(tmp_path)


def test_sse_disconnect_stops_generator(tmp_path):
    repo=ResearchRepository(tmp_path)
    task=repo.create('question',ResearchSettings())
    class Disconnected:
        checks=0
        async def is_disconnected(self):
            self.checks+=1
            return self.checks>1
    async def scenario():
        stream=research_events(repo,task['id'],Disconnected(),0)
        assert 'event: task.status' in await anext(stream)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    asyncio.run(scenario())
