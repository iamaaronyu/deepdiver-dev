import asyncio
import json

import pytest

from deepdive.agents import synthesizer,writer
from deepdive.agents.planner import StructuredOutputError
from deepdive.orchestration.models import ResearchSettings
from deepdive.storage.database import ResearchRepository
from test_stage3 import execute,source,QUOTE,Model,Collector
from deepdive.orchestration.controller import ResearchController


@pytest.fixture
def repository(tmp_path):
    return ResearchRepository(tmp_path)


def test_deep_research_checks_second_perspective_even_when_initial_claim_supported(repository):
    task,collector,model=execute(repository,settings=ResearchSettings(depth='deep',max_rounds=2))
    assert task['status']=='COMPLETED'
    assert collector.calls==2
    assert task['usage']['rounds']==2
    assert model.calls==8  # plan/findings/review twice, then analysis and its audit
    assert '## 核心判断' in repository.report(task['id'])
    assert '## 仍待回答的问题' in repository.report(task['id'])
    assert '](#evidence-1)' in repository.report(task['id'])


def test_standard_research_can_finish_without_mandatory_second_round(repository):
    task,collector,model=execute(repository,settings=ResearchSettings(max_rounds=3))
    assert collector.calls==1
    assert model.calls==5
    assert task['status']=='COMPLETED'


def test_no_verified_claims_cannot_produce_synthesis(repository):
    task=repository.create('question',ResearchSettings())
    async def never(*args):
        pytest.fail('No synthesis call should be made without eligible evidence')
    assert asyncio.run(synthesizer.synthesize(repository,task['id'],never)) is None


def test_analysis_cannot_reference_unknown_or_unverified_claim(repository):
    task,_,_=execute(repository)
    async def invented(*args):
        point={'text':'Unsupported invented conclusion','claim_ids':['foreign-claim']}
        return json.dumps({'overview':[point],'sections':[{'title':'Analysis','points':[point]}],'implications':[],'open_questions':[]})
    with pytest.raises(StructuredOutputError,match='Structured model output rejected'):
        asyncio.run(synthesizer.synthesize(repository,task['id'],invented))


def test_deep_mode_still_respects_explicit_one_round_cap(repository):
    task,collector,_=execute(repository,settings=ResearchSettings(depth='deep',max_rounds=1))
    assert task['status']=='COMPLETED'
    assert collector.calls==1
    assert task['usage']['rounds']==1


def test_unverified_material_not_promoted_into_analysis(repository):
    task=repository.create('question',ResearchSettings())
    original=source()
    repository.add_sources(task['id'],[original])
    claim=repository.add_claim(task['id'],QUOTE,1)
    repository.add_evidence(task['id'],claim,original['id'],QUOTE,'offset 0')
    async def never(*args):
        pytest.fail('Unverified evidence must not be offered as analysis support')
    assert asyncio.run(synthesizer.synthesize(repository,task['id'],never)) is None


def test_invalid_analysis_falls_back_without_publishing_invented_text(repository):
    class InvalidAnalysis(Model):
        async def run(self,prompt,**kwargs):
            if 'evidence_claims' in json.loads(prompt):
                self.calls+=1
                point={'text':'Invented analysis must not be published','claim_ids':['foreign-id']}
                return {'answer':json.dumps({'overview':[point],'sections':[{'title':'Fake','points':[point]}],'implications':[],'open_questions':[]}),
                        'usage':{'requests':1,'input_tokens':10,'output_tokens':10}}
            return await super().run(prompt,**kwargs)
    collector=Collector()
    task=repository.create('question',ResearchSettings(max_rounds=1))
    asyncio.run(ResearchController(repository,InvalidAnalysis(collector),collector).run(task['id']))
    assert repository.get(task['id'])['status']=='COMPLETED'
    assert 'Invented analysis' not in repository.report(task['id'])
    assert '分析成文未通过结构或引用校验' in repository.report(task['id'])
    assert any(event['type']=='report.analysis_fallback' for event in repository.events(task['id']))


def test_deep_call_timeout_is_bounded_by_task_deadline(repository):
    timeouts=[]
    class TimedModel(Model):
        async def run(self,prompt,**kwargs):
            timeouts.append(kwargs.get('timeout_seconds'))
            return await super().run(prompt,**kwargs)
    collector=Collector()
    task=repository.create('question',ResearchSettings(depth='deep',max_rounds=1,timeout_seconds=50))
    asyncio.run(ResearchController(repository,TimedModel(collector),collector).run(task['id']))
    assert timeouts==[50]*5


def test_legacy_versioned_docs_do_not_establish_current_behavior(repository):
    from deepdive.agents.verifier import legacy_source_ids,verify
    task=repository.create('TaskGroup current behavior',ResearchSettings())
    old=source('https://docs.python.org/3.7/library/asyncio.html')
    new=source('https://docs.python.org/3.14/library/asyncio.html')
    repository.add_sources(task['id'],[old,new])
    claim=repository.add_claim(task['id'],QUOTE,2)
    evidence=repository.add_evidence(task['id'],claim,old['id'],QUOTE,'offset 0')
    async def approve(*args):
        return json.dumps({'verdicts':[{'claim_id':claim,'evidence_id':evidence,'relation':'supports','reason':'Literal but old'}]})
    asyncio.run(verify(repository,task['id'],approve))
    assert repository.materials(task['id'])['claims'][0]['verification_status']=='OUTDATED_RISK'
    assert old['id'] in legacy_source_ids([old,new],'current behavior')
    assert old['id'] not in legacy_source_ids([old,new],'compare 3.7 and 3.14')


def test_independent_analysis_audit_can_reject_every_draft_point(repository):
    task,_,_=execute(repository)
    calls=0
    async def reject(prompt,*args):
        nonlocal calls
        calls+=1
        data=json.loads(prompt)
        if 'draft_analysis_points' in data:
            return json.dumps({'approved_point_ids':[]})
        point={'text':'Unsupported overreach','claim_ids':[data['evidence_claims'][0]['claim_id']]}
        return json.dumps({'overview':[point],'sections':[{'title':'Draft','points':[point]}],'implications':[],'open_questions':[]})
    with pytest.raises(StructuredOutputError):
        asyncio.run(synthesizer.synthesize(repository,task['id'],reject))
    assert calls==2
    event=[e for e in repository.events(task['id']) if e['type']=='report.analysis_reviewed'][-1]
    assert event['data']=={'accepted_points':0,'rejected_points':2}


def test_expansion_preserves_calls_for_analysis_and_independent_review(repository):
    task,collector,model=execute(repository,settings=ResearchSettings(depth='deep',max_rounds=3,max_model_calls=7),model_kwargs={'importance':1})
    assert task['status']=='COMPLETED'
    assert collector.calls==1
    assert model.calls==5
    assert '## 核心判断' in repository.report(task['id'])
    assert '为保留分析成文与独立审查' in repository.report(task['id'])


def test_rejected_followup_preserves_first_round_and_produces_partial_analysis(repository):
    class BadFollowup(Model):
        plans=0
        async def run(self,prompt,**kwargs):
            if 'output_schema' in json.loads(prompt):
                self.plans+=1
                if self.plans==2:
                    self.calls+=1
                    return {'answer':'{"subquestions": []}', 'usage':{'requests':1,'input_tokens':10,'output_tokens':10}}
            return await super().run(prompt,**kwargs)
    collector=Collector();model=BadFollowup(collector)
    task=repository.create('TaskGroup behavior',ResearchSettings(depth='deep',max_rounds=2))
    asyncio.run(ResearchController(repository,model,collector).run(task['id']))
    assert repository.get(task['id'])['status']=='COMPLETED'
    assert model.plans==2 and collector.calls==1  # No paid retry or extra search.
    assert '补充研究计划未通过结构校验' in repository.report(task['id'])
    assert '## 核心判断' in repository.report(task['id'])
    event=next(e for e in repository.events(task['id']) if e['type']=='plan.expansion_rejected')
    assert 'time_sensitive' in event['data']['issue_paths']


def test_validation_diagnostics_never_persist_unknown_field_values_or_names():
    from deepdive.agents.planner import parse_json
    from deepdive.orchestration.models import Plan
    with pytest.raises(StructuredOutputError) as caught:
        parse_json('{"subquestions":[],"time_sensitive":false,"secret-model-value":"private"}',Plan)
    assert '[unknown_field]' in caught.value.issue_paths
    assert 'secret-model-value' not in repr(caught.value.issue_paths)


def test_official_price_table_keeps_header_units_and_all_prices():
    from deepdive.agents.researcher import select_excerpts
    table='MODEL | example-flash | pro\n---|---|---\nMODEL VERSION | flash-2026 | pro-2026\n\n'
    table+='CONTEXT | 1M | 1M\n'+'FEATURE | enabled | enabled\n'*10
    table+='PRICING | 1M INPUT TOKENS (CACHE HIT) | $0.006\nCACHE MISS | $0.3\nOUTPUT | $1.2\n'
    text='Model pricing introduction. '*15+'\n\n'+table+'\n\nModel notes and other details. '*15
    selected=select_excerpts(text,'核查 example-flash 的峰时输入、输出和缓存命中价格与计价单位',4)
    assert any('MODEL | example-flash' in e and '$0.006' in e and '$0.3' in e and '$1.2' in e for e in selected)
    assert all(e in text for e in selected)


def test_long_verifier_annotation_does_not_discard_strict_verdict():
    from deepdive.agents.verifier import parse_verification
    payload={'verdicts':[{'claim_id':'c','evidence_id':'e','relation':'unverified','reason':'原因'*200}]}
    result=parse_verification(json.dumps(payload))
    assert result.verdicts[0].relation=='unverified'
    assert len(result.verdicts[0].reason)<=300
    assert '已截短' in result.verdicts[0].reason
    payload['verdicts'][0]['relation']='invented'
    with pytest.raises(StructuredOutputError):parse_verification(json.dumps(payload))
