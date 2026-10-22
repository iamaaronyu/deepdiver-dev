import json

import pytest

from deepdive.evaluation.metrics import measure,audit_metrics
from deepdive.evaluation.suite import load_suite,PROFILES


def case():
    return {'id':'example','aspects':[{'id':'a1','patterns':['checkpoint']},{'id':'a2','patterns':['single writer']} ]}


def data():
    task={'id':'t','status':'COMPLETED','usage':{}}
    material={'sources':[{'id':'s','fetch_status':'FETCHED','canonical_url':'https://sqlite.org/wal.html','extracted_text':'WAL has a single writer and checkpoint process.'}],
        'claims':[{'id':'c','importance':1,'verification_status':'SUPPORTED'}],
        'evidence':[{'source_id':'s','claim_id':'c','task_id':'t','quote_or_excerpt':'a single writer'}]}
    return task,material


def test_suite_has_ten_fixed_cases_and_five_categories():
    suite,checksum=load_suite()
    assert len(suite['cases'])>=10
    assert len(checksum)==64
    assert {c['category'] for c in suite['cases']}=={'fact','comparison','current','conflict','insufficient'}
    assert PROFILES['standard'].max_rounds==1 and PROFILES['deep'].max_rounds==2
    assert sum(p.max_budget_usd for p in PROFILES.values())*10==2


def test_no_evidence_is_not_one_hundred_percent_citation_success():
    task,material=data();material['evidence']=[];material['claims']=[]
    result=measure(task,material,'',case())
    assert result['literal_citation_validity'] is None
    assert result['automatic_supported_claim_rate'] is None
    assert result['reference_audited_fact_error_rate'] is None
    assert result['analysis_reference_validity'] is None


def test_literal_citation_and_reference_ranges_are_checked():
    task,material=data()
    result=measure(task,material,'## 核心判断\n\nSingle writer with checkpoint [e](#evidence-1) [bad](#evidence-2)',case())
    assert result['literal_citation_validity']==1
    assert result['analysis_reference_validity']==.5
    assert result['coverage_keyword_hint']==1
    assert result['reference_audited_fact_error_rate'] is None


def test_invented_quote_and_cross_task_link_fail():
    task,material=data()
    material['evidence'][0]['quote_or_excerpt']='invented'
    assert measure(task,material,'',case())['literal_citation_validity']==0
    material['evidence'][0]['quote_or_excerpt']='a single writer'
    material['evidence'][0]['task_id']='another'
    assert measure(task,material,'',case())['literal_citation_validity']==0


def test_appendix_and_open_questions_cannot_inflate_coverage():
    task,material=data()
    report='## 核心判断\n\nNo answer\n\n## 仍待回答的问题\ncheckpoint? single writer?\n\n## 证据附录\ncheckpoint single writer'
    assert measure(task,material,report,case())['coverage_keyword_hint']==0


def test_review_requires_task_identity_and_every_aspect():
    review={'task_id':'t','reviewer':'reference-audit','aspects':{'a1':1,'a2':.5},'facts':[{'statement':'A claim','verdict':'incorrect','basis':'Official reference and direct quote'}]}
    result=audit_metrics(review,case(),'t')
    assert result['reference_audited_fact_error_rate']==1
    assert result['reference_audited_coverage']==.75
    with pytest.raises(ValueError):audit_metrics(review,case(),'other')
    review['aspects'].pop('a2')
    with pytest.raises(ValueError):audit_metrics(review,case(),'t')


def test_unknown_fact_assessment_cannot_be_zero_error_rate():
    review={'task_id':'t','reviewer':'reference-audit','aspects':{'a1':0,'a2':0},'facts':[{'statement':'No independently checked claim','verdict':'unclear','basis':'Evidence unavailable'}]}
    result=audit_metrics(review,case(),'t')
    assert result['reference_audited_fact_error_rate'] is None
    assert result['unclear_facts']==1


def test_failed_tasks_remain_in_results():
    task,material=data();task['status']='FAILED';task['error_message']='model_timeout'
    result=measure(task,material,'',case())
    assert not result['completed']
    assert result['error_code']=='model_timeout'


def test_question_header_cannot_count_as_answer_coverage():
    task,material=data()
    report='# Report\n\n**研究问题**：single writer checkpoint\n\n## 执行摘要\nGot some sources\n\n## 关键结论\n证据不足。\n'
    assert measure(task,material,report,case())['coverage_keyword_hint']==0


def test_cross_task_claim_invalidates_citation():
    task,material=data();material['claims'][0]['task_id']='foreign'
    assert measure(task,material,'',case())['literal_citation_validity']==0


def test_report_aggregation_keeps_unknown_cost_and_failed_attempts():
    from scripts.report_evaluation import summarize
    task,material=data()
    good=measure(task,material,'## 核心判断\ncheckpoint single writer',case())
    bad={**good,'completed':False,'task_status':'FAILED','usage':{'cost_estimate_usd':None}}
    good['usage']={'cost_estimate_usd':.01}
    result=summarize([good,bad])
    assert result['completion_rate']==.5
    assert result['unknown_cost_attempts']==1
    assert result['cost_estimate_known_subtotal_usd']==.01
    assert result['reference_audited_fact_error_rate'] is None
