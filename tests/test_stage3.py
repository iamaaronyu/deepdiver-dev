import asyncio
import json
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from deepdive.agents import researcher,verifier,writer
from deepdive.evidence.sources import Source
from deepdive.orchestration.controller import ResearchController
from deepdive.orchestration.models import ResearchSettings
from deepdive.orchestration.state_machine import validate_transition,TERMINAL
from deepdive.providers.llm import ModelFailure
from deepdive.storage.database import ResearchRepository

QUOTE='Task groups provide a reliable structured concurrency mechanism for waiting on related tasks.'


def source(url='https://docs.python.org/3/library/asyncio-task.html'):
    result=Source.pending(url,'Actual source')
    result.canonical_url=url
    result.extracted_text=QUOTE+' '+('Additional actual page context. '*10)
    result.content_hash='hash-'+url
    result.fetch_status='FETCHED'
    return asdict(result)


class Collector:
    def __init__(self):
        self.calls=0
        self.sources=[source()]
    async def collect(self,question,max_results):
        self.calls+=1
        return {'id':'local-test','sources':self.sources,'valid_sources':1,'search_requests':1,'provider_usage':{'fetch_requests':1,'fetch_request_count_complete':True},'status':'COMPLETED'}


class Model:
    def __init__(self,collector,*,importance=2,bad_quote=False,conflict=False):
        self.calls=0
        self.collector=collector
        self.importance=importance
        self.bad_quote=bad_quote
        self.conflict=conflict
    async def run(self,prompt,*,instructions,max_tokens,json_mode=False,timeout_seconds=None):
        self.calls+=1
        data=json.loads(prompt)
        if 'output_schema' in data:
            answer={'subquestions':[{'question':'Python TaskGroup documentation','objective':'Understand task groups','priority':1,'evidence_type':'official documentation'}],'time_sensitive':False}
        elif 'untrusted_source_data' in data:
            answer={'claims':[{'text':QUOTE,'importance':self.importance,'citations':[{'source_id':item['source_id'],'excerpt':'Invented nonexistent quotation that must not be accepted.' if self.bad_quote else QUOTE} for item in data['untrusted_source_data']]}]}
        elif 'draft_analysis_points' in data:
            answer={'approved_point_ids':[p['point_id'] for p in data['draft_analysis_points']]}
        elif 'evidence_claims' in data:
            point={'text':'Task groups coordinate related work; failure behavior still requires focused evidence.','claim_ids':[data['evidence_claims'][0]['claim_id']]}
            answer={'overview':[point],'sections':[{'title':'Mechanism and boundaries','points':[point]}],'implications':[],'open_questions':['How does cancellation behave?']}
        else:
            answer={'verdicts':[{'claim_id':item['claim_id'],'evidence_id':item['evidence_id'],'relation':'contradicts' if self.conflict else 'supports','reason':'Fixture evidence relationship.'} for item in data['pairs']]}
        return {'answer':json.dumps(answer),'usage':{'requests':1,'input_tokens':100,'output_tokens':50},'duration_ms':1}


@pytest.fixture
def repository(tmp_path):
    return ResearchRepository(tmp_path)


def execute(repository,*,settings=None,model_kwargs=None):
    collector=Collector()
    model=Model(collector,**(model_kwargs or {}))
    task=repository.create('How do TaskGroup tasks behave?',settings or ResearchSettings(max_rounds=1))
    asyncio.run(ResearchController(repository,model,collector).run(task['id']))
    return repository.get(task['id']),collector,model


def test_complete_evidence_loop_persists_and_report_urls(repository):
    task,collector,model=execute(repository)
    assert task['status']=='COMPLETED'
    assert model.calls==5 and collector.calls==1
    material=repository.materials(task['id'])
    assert material['claims'][0]['verification_status']=='SUPPORTED'
    evidence=material['evidence'][0]
    assert evidence['quote_or_excerpt'] in material['sources'][0]['extracted_text']
    assert evidence['relation']=='supports'
    report=repository.report(task['id'])
    assert material['sources'][0]['url'] in report
    assert '## 局限性' in report and '## 来源清单' in report
    assert '（Asia/Shanghai）' in report and '+08:00' in report
    reopened=ResearchRepository(repository.directory)
    assert reopened.get(task['id'])['status']=='COMPLETED'
    assert reopened.report(task['id'])==report
    states=[e['data']['status'] for e in repository.events(task['id']) if e['type']=='task.status']
    assert states==['CREATED','PLANNING','RESEARCHING','VERIFYING','WRITING','COMPLETED']


def test_fake_quote_never_becomes_verified_or_cited(repository):
    task,_,_=execute(repository,model_kwargs={'bad_quote':True})
    material=repository.materials(task['id'])
    assert material['claims'][0]['verification_status']=='UNVERIFIED'
    assert material['evidence']==[]
    assert 'Invented nonexistent quotation' not in repository.report(task['id'])


def test_important_single_domain_claim_is_partial_and_research_is_bounded(repository):
    task,collector,_=execute(repository,settings=ResearchSettings(max_rounds=2),model_kwargs={'importance':1})
    assert task['status']=='COMPLETED'
    assert collector.calls==2
    assert task['usage']['rounds']==2
    assert repository.materials(task['id'])['claims'][0]['verification_status']=='PARTIALLY_SUPPORTED'
    assert '达到最大研究轮数' in repository.report(task['id'])
    states=[e['data']['status'] for e in repository.events(task['id']) if e['type']=='task.status']
    assert 'NEEDS_MORE_RESEARCH' in states


def test_cross_domain_support_and_conflicts(repository):
    collector=Collector()
    collector.sources.append(source('https://independent.example.org/guide'))
    model=Model(collector,importance=1)
    task=repository.create('question',ResearchSettings(max_rounds=1))
    asyncio.run(ResearchController(repository,model,collector).run(task['id']))
    assert repository.materials(task['id'])['claims'][0]['verification_status']=='SUPPORTED'
    task2,_,_=execute(repository,model_kwargs={'conflict':True})
    assert repository.materials(task2['id'])['claims'][0]['verification_status']=='CONTRADICTED'


def test_search_budget_stops_before_call_and_keeps_partial_report(repository):
    task,collector,_=execute(repository,settings=ResearchSettings(max_search_requests=1))
    assert task['status']=='BUDGET_EXCEEDED'
    assert collector.calls==0
    assert repository.report(task['id'])


def test_token_budget_stops_before_model(repository):
    task,_,model=execute(repository,settings=ResearchSettings(max_total_tokens=1000))
    assert task['status']=='BUDGET_EXCEEDED'
    assert model.calls==0


def test_failed_model_saves_terminal_state_without_secret(repository):
    class Failure:
        async def run(self,*args,**kwargs):
            raise ModelFailure('provider_authentication_failed','safe',502)
    task=repository.create('question',ResearchSettings())
    asyncio.run(ResearchController(repository,Failure(),Collector()).run(task['id']))
    saved=repository.get(task['id'])
    assert saved['status']=='FAILED'
    assert saved['error_message']=='provider_authentication_failed'
    assert saved['usage']['model_usage_complete'] is False
    assert repository.report(task['id'])


def test_invalid_json_fails_explicitly(repository):
    class Invalid:
        async def run(self,*args,**kwargs):
            return {'answer':'not JSON','usage':{'requests':1,'input_tokens':1,'output_tokens':1}}
    task=repository.create('question',ResearchSettings())
    asyncio.run(ResearchController(repository,Invalid(),Collector()).run(task['id']))
    assert repository.get(task['id'])['status']=='FAILED'
    assert repository.get(task['id'])['error_message']=='invalid_model_output'


def test_deadline_stops_model_and_writes_partial(repository):
    class Slow:
        async def run(self,*args,**kwargs):
            await asyncio.sleep(10)
    task=repository.create('question',ResearchSettings(timeout_seconds=1))
    asyncio.run(ResearchController(repository,Slow(),Collector()).run(task['id']))
    assert repository.get(task['id'])['status']=='TIMED_OUT'
    assert repository.report(task['id'])


def test_cancel_queued_and_running_tasks(repository):
    task=repository.create('question',ResearchSettings())
    repository.cancel(task['id'])
    asyncio.run(ResearchController(repository,None,None).run(task['id']))
    assert repository.get(task['id'])['status']=='CANCELLED'
    class Slow:
        async def run(self,*args,**kwargs):
            await asyncio.sleep(10)
    task2=repository.create('question2',ResearchSettings())
    async def scenario():
        running=asyncio.create_task(ResearchController(repository,Slow(),Collector()).run(task2['id']))
        await asyncio.sleep(0.01)
        repository.cancel(task2['id'])
        await running
    asyncio.run(scenario())
    assert repository.get(task2['id'])['status']=='CANCELLED'


def test_restart_marks_abandoned_work_failed_and_preserves_queue(repository):
    task=repository.create('in-flight',ResearchSettings())
    repository.transition(task['id'],'PLANNING')
    queued=repository.create('queued',ResearchSettings())
    ResearchRepository(repository.directory).recover()
    assert repository.get(task['id'])['status']=='FAILED'
    assert repository.get(task['id'])['error_message']=='worker_restarted'
    assert repository.get(queued['id'])['status']=='CREATED'


def test_state_machine_rejects_invalid_and_terminal_transitions():
    with pytest.raises(ValueError):
        validate_transition('CREATED','COMPLETED')
    with pytest.raises(ValueError):
        validate_transition('COMPLETED','RESEARCHING')


def test_unmatched_verdict_cannot_validate_claim(repository):
    task=repository.create('question',ResearchSettings())
    s=source()
    repository.add_sources(task['id'],[s])
    claim=repository.add_claim(task['id'],QUOTE,2)
    repository.add_evidence(task['id'],claim,s['id'],QUOTE,'test')
    async def bad_reviewer(*args):
        return json.dumps({'verdicts':[{'claim_id':'fake','evidence_id':'fake','relation':'supports','reason':'fake'}]})
    asyncio.run(verifier.verify(repository,task['id'],bad_reviewer))
    assert repository.materials(task['id'])['claims'][0]['verification_status']=='UNVERIFIED'


def test_outdated_risk_not_hidden(repository):
    assert verifier.outdated([{'published_at':None}],True)
    assert verifier.outdated([{'published_at':'2000-01-01'}],True)
    assert not verifier.outdated([{'published_at':None}],False)


def test_research_api_submission_requires_configuration(monkeypatch):
    with TestClient(app) as client:
        assert client.post('/api/research',json={'question':'question'}).status_code==503
        app.state.model_service=object()
        app.state.source_collector=object()
        response=client.post('/api/research',json={'question':'question','settings':{'max_rounds':1}})
        assert response.status_code==202
        task=response.json()
        assert task['status']=='CREATED'
        task_id=task['id']
        assert client.get('/api/research/'+task_id).json()['id']==task_id
        assert client.get('/api/research/'+task_id+'/report').status_code==409
        assert client.post('/api/research/'+task_id+'/cancel').json()['cancel_requested'] is True
        assert client.get('/api/research').json()[0]['id']==task_id
        assert client.get('/api/research/missing').status_code==404
        assert client.get('/api/research/missing/evidence').status_code==404
        assert client.post('/api/research',json={'question':'question','settings':{'max_rounds':4}}).status_code==422


def test_monetary_cap_rejects_reservation_before_spend(repository):
    from deepdive.orchestration.budget import Budget,BudgetExceeded
    settings=ResearchSettings(max_budget_usd=0.00001)
    task=repository.create('question',settings)
    prices={'model_input_per_million':0.3,'model_output_per_million':1.2,'search_per_request':0.00075,'fetch_per_request':0.00075}
    budget=Budget(settings,repository,task['id'],prices)
    with pytest.raises(BudgetExceeded):
        budget.reserve_tools(5)
    assert budget.used['search_requests']==0
    assert budget.used['cost_reserved_upper_usd']==0


def test_repository_rejects_cross_task_and_invented_evidence(repository):
    task=repository.create('question',ResearchSettings())
    other=repository.create('other',ResearchSettings())
    s=source()
    repository.add_sources(task['id'],[s])
    claim=repository.add_claim(other['id'],QUOTE,2)
    with pytest.raises(ValueError):
        repository.add_evidence(other['id'],claim,s['id'],QUOTE,'invalid cross-task link')
    claim2=repository.add_claim(task['id'],QUOTE,2)
    with pytest.raises(ValueError):
        repository.add_evidence(task['id'],claim2,s['id'],'invented excerpt','invalid excerpt')


def test_simultaneous_database_initialization_is_safe(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as executor:
        repositories=list(executor.map(lambda _:ResearchRepository(tmp_path),range(4)))
    for repo in repositories:
        assert repo.list()==[]


def test_preselected_excerpt_ids_attach_only_original_text(repository):
    task=repository.create('Task groups mechanism',ResearchSettings())
    s=source()
    repository.add_sources(task['id'],[s])
    async def select_id(prompt,*args):
        payload=json.loads(prompt)
        excerpt=payload['untrusted_source_data'][0]['excerpts'][0]
        assert excerpt['text'] in s['extracted_text']
        return json.dumps({'claims':[{'text':'Task groups provide structured concurrency.','importance':2,'citations':[{'excerpt_id':excerpt['excerpt_id']},{'excerpt_id':'fake-id'}]}]})
    asyncio.run(researcher.findings(repository,task['id'],'Task groups mechanism',select_id))
    material=repository.materials(task['id'])
    assert len(material['evidence'])==1
    assert material['evidence'][0]['quote_or_excerpt'] in s['extracted_text']
    assert any(event['type']=='evidence.rejected' for event in repository.events(task['id']))


def test_supplementary_research_merges_evidence_for_existing_claim(repository):
    task=repository.create('question',ResearchSettings())
    first=source()
    second=source('https://independent.example.org/guide')
    repository.add_sources(task['id'],[first])
    async def cite_first(*args):
        return json.dumps({'claims':[{'text':QUOTE,'importance':1,'citations':[{'source_id':first['id'],'excerpt':QUOTE}]}]})
    asyncio.run(researcher.findings(repository,task['id'],'question',cite_first))
    repository.add_sources(task['id'],[second])
    async def cite_second(*args):
        return json.dumps({'claims':[{'text':QUOTE,'importance':1,'citations':[{'source_id':second['id'],'excerpt':QUOTE}]}]})
    asyncio.run(researcher.findings(repository,task['id'],'question',cite_second))
    material=repository.materials(task['id'])
    assert len(material['claims'])==1
    assert len(material['evidence'])==2


def test_excerpts_select_relevant_window_in_long_single_paragraph():
    text=('Navigation and Python introduction. '*50)+' TaskGroup gather exception child '+('Detailed task failure semantics. '*15)
    excerpts=researcher.select_excerpts(text,'How do TaskGroup and gather handle child exceptions?')
    assert excerpts
    assert 'TaskGroup gather exception child' in excerpts[0]
    assert excerpts[0] in text
    assert len(excerpts[0])<=600


def test_second_worker_cannot_recover_another_workers_task(repository):
    import fcntl
    from deepdive.worker import main
    task=repository.create('active',ResearchSettings())
    repository.transition(task['id'],'PLANNING')
    with (repository.directory/'worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert main()==1
    assert repository.get(task['id'])['status']=='PLANNING'
