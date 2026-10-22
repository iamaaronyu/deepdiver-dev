"""Bounded live evaluation with immutable artifacts and no automatic resubmission."""
import argparse
import asyncio
from dataclasses import replace
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from deepdive.config import ROOT,ModelConfig
from deepdive.evaluation.suite import load_suite,PROFILES
from deepdive.evaluation.metrics import measure
from deepdive.evidence.repository import SourceRepository
from deepdive.observability.logging import configure_logging
from deepdive.orchestration.controller import ResearchController
from deepdive.orchestration.pricing import price_profile
from deepdive.providers.llm import ModelService
from deepdive.providers.registry import create_source_collector
from deepdive.storage.database import ResearchRepository


def save(path,value):
    with path.open('x',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)
    path.chmod(0o600)


def source_hash():
    files=sorted((ROOT/'deepdive').rglob('*.py'))
    return hashlib.sha256(b''.join(str(p.relative_to(ROOT)).encode()+p.read_bytes() for p in files)).hexdigest()


async def run(args):
    suite,suite_hash=load_suite()
    if not args.live:
        raise SystemExit('Use --live explicitly to authorize real provider calls; no calls made.')
    cases=[c for c in suite['cases'] if not args.case or c['id'] in args.case]
    if not cases or (args.case and len(cases)!=len(set(args.case))):
        raise SystemExit('Unknown or duplicated case selection')
    profiles=[p for p in PROFILES if not args.profile or p in args.profile]
    if not profiles:
        raise SystemExit('No profiles selected')
    reserved=sum(PROFILES[p].max_budget_usd for p in profiles)*len(cases)
    if reserved>args.total_budget+.000001:
        raise SystemExit('Declared aggregate budget is too small; no calls made.')
    folder=ROOT/'data/evaluations'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:6])
    folder.mkdir(parents=True,mode=0o700)
    repo=ResearchRepository(folder/'research')
    config=replace(ModelConfig.from_env(),timeout_seconds=90)
    fingerprint=source_hash()
    collector=create_source_collector()
    if price_profile(ModelService(config),collector) is None:
        raise SystemExit('No verified price profile; no live calls made.')
    manifest={'version':1,'mode':'live','created_at':datetime.now(timezone.utc).isoformat(),'suite_hash':suite_hash,
        'source_hash':fingerprint,'model':config.model,'protocol':'chat_completions','model_timeout_seconds':90,
        'profiles':{p:PROFILES[p].model_dump() for p in profiles},'cases':[c['id'] for c in cases],
        'concurrency':args.concurrency,'max_aggregate_reserved_usd':reserved,'declared_total_budget_usd':args.total_budget,
        'price_profile':price_profile(ModelService(config),collector),
        'billing_note':'Conservative dated reservation, not actual account invoice. Unknown provider usage stays null.'}
    save(folder/'manifest.json',manifest);save(folder/'suite.json',suite)
    print(json.dumps({'run_dir':str(folder),'tasks':len(cases)*len(profiles),'aggregate_reserved_cap_usd':reserved}),flush=True)
    semaphore=asyncio.Semaphore(args.concurrency)
    results=[]
    async def one(case,profile):
        async with semaphore:
            if source_hash()!=fingerprint:
                raise RuntimeError('Source changed during run; unstarted tasks will not be submitted')
            task=repo.create(case['question'],PROFILES[profile])
            model=ModelService(config)
            tools=create_source_collector();tools.repository=SourceRepository(folder/'sources')
            await ResearchController(repo,model,tools).run(task['id'])
            task=repo.get(task['id']);material=repo.materials(task['id']);report=repo.report(task['id']) or ''
            name=case['id']+'--'+profile
            save(folder/(name+'.task.json'),{'task':task,'material':material})
            (folder/(name+'.md')).write_text(report,encoding='utf-8')
            row={'case_id':case['id'],'category':case['category'],'profile':profile,'task_id':task['id'],
                 'source_hash':fingerprint,**measure(task,material,report,case)}
            save(folder/(name+'.metrics.json'),row)
            review={'task_id':task['id'],'reviewer':'pending','aspects':{a['id']:None for a in case['aspects']},
                'facts':[],'notes':'Review narrative against primary references and actual excerpts. Do not grade source appendix as answered content.'}
            save(folder/(name+'.review-template.json'),review)
            results.append(row)
            with (folder/'progress.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            print(json.dumps({'finished':len(results),'case':case['id'],'profile':profile,'status':task['status'],
                              'claims':len(material['claims']),'analysis':row['has_analysis'],'error':task['error_message']}),flush=True)
    await asyncio.gather(*(one(c,p) for c in cases for p in profiles))
    save(folder/'results.json',sorted(results,key=lambda r:(r['case_id'],r['profile'])))
    save(folder/'complete.json',{'completed_tasks':len(results),'source_unchanged':source_hash()==fingerprint})
    print(json.dumps({'complete':True,'run_dir':str(folder)}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--case',action='append')
    parser.add_argument('--profile',action='append',choices=list(PROFILES))
    parser.add_argument('--total-budget',type=float,default=2)
    parser.add_argument('--concurrency',type=int,choices=[1,2],default=2)
    args=parser.parse_args()
    if not 0<args.total_budget<=2:parser.error('Aggregate budget must be >0 and <=2 USD')
    configure_logging()
    asyncio.run(run(args))


if __name__=='__main__':main()
