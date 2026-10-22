"""Deterministic measurements. Text matches are coverage hints, never accuracy scores."""
import re
from urllib.parse import urlsplit

ELIGIBLE={'SUPPORTED','PARTIALLY_SUPPORTED'}


def ratio(numerator,denominator):
    return numerator/denominator if denominator else None


def narrative(markdown):
    # Do not count raw quotations, source lists, or unanswered questions as answers.
    body=re.split(r'^## (?:证据附录|分主题分析与证据引用|仍待回答的问题|来源冲突与不确定性|局限性|来源清单)',markdown,flags=re.M)[0]
    answer=re.search(r'^## (?:核心判断|关键结论)\s*$',body,re.M)
    return body[answer.start():] if answer else ''


def measure(task,material,markdown,case):
    sources={s['id']:s for s in material['sources']}
    claims={c['id']:c for c in material['claims']}
    valid=[]
    for e in material['evidence']:
        s=sources.get(e['source_id'])
        valid.append(bool(s and e['claim_id'] in claims and s['fetch_status']=='FETCHED' and e['quote_or_excerpt'] and
                          e['quote_or_excerpt'] in s['extracted_text'] and urlsplit(s['canonical_url'] or s['url']).scheme in {'http','https'} and
                          s.get('task_id',task['id'])==task['id'] and e.get('task_id',task['id'])==task['id'] and
                          claims[e['claim_id']].get('task_id',task['id'])==task['id']))
    important=[c for c in claims.values() if c['importance']==1]
    body=narrative(markdown)
    aspect_hits={a['id']:all(re.search(p,body,re.I) for p in a['patterns']) for a in case['aspects']}
    references=[int(n) for n in re.findall(r'\]\(#evidence-(\d+)\)',body)]
    ordered=material['claims']
    good_refs=sum(1<=n<=len(ordered) and ordered[n-1]['verification_status'] in ELIGIBLE for n in references)
    return {'task_status':task['status'],'completed':task['status']=='COMPLETED',
        'valid_sources':sum(s['fetch_status']=='FETCHED' for s in sources.values()),'claims':len(claims),'evidence_links':len(valid),
        'literal_citation_valid_count':sum(valid),'literal_citation_validity':ratio(sum(valid),len(valid)),
        'automatic_supported_claim_rate':ratio(sum(c['verification_status']=='SUPPORTED' for c in claims.values()),len(claims)),
        'automatic_important_supported_rate':ratio(sum(c['verification_status']=='SUPPORTED' for c in important),len(important)),
        'analysis_reference_count':len(references),'analysis_reference_validity':ratio(good_refs,len(references)),
        'has_analysis':'## 核心判断' in body,'narrative_characters':len(body),
        'coverage_keyword_hint':ratio(sum(aspect_hits.values()),len(aspect_hits)),'coverage_aspect_hints':aspect_hits,
        'reference_audited_fact_error_rate':None,'reference_audited_coverage':None,'review_status':'pending',
        'usage':task['usage'],'error_code':task.get('error_message')}


def audit_metrics(review,case,task_id):
    if review.get('task_id')!=task_id:
        raise ValueError('Review belongs to a different task')
    expected={a['id'] for a in case['aspects']}
    aspects=review.get('aspects',{})
    if set(aspects)!=expected or any(v not in {0,.5,1} for v in aspects.values()):
        raise ValueError('Every aspect requires an explicit 0, 0.5 or 1 judgment')
    facts=review.get('facts',[])
    allowed={'correct','incorrect','unclear'}
    if not facts or any(f.get('verdict') not in allowed or not f.get('statement') or not f.get('basis') for f in facts):
        raise ValueError('Fact reviews require a statement, verdict and reference basis')
    correct=sum(f['verdict']=='correct' for f in facts)
    incorrect=sum(f['verdict']=='incorrect' for f in facts)
    return {'review_status':'reference_audited','reviewer':review['reviewer'],
        'reference_audited_fact_error_rate':ratio(incorrect,correct+incorrect),
        'reviewed_facts':len(facts),'determinate_reviewed_facts':correct+incorrect,
        'unclear_facts':len(facts)-correct-incorrect,
        'reference_audited_coverage':sum(aspects.values())/len(aspects)}
