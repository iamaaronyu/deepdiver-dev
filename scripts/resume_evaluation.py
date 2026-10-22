"""Resume only never-submitted pairs; interrupted attempts remain failures, never paid retries."""
import argparse
import asyncio
from dataclasses import replace
from datetime import datetime,timezone
import fcntl
import json
from pathlib import Path
from uuid import uuid4

from deepdive.agents import writer
from deepdive.config import ROOT,ModelConfig
from deepdive.evaluation.metrics import measure
from deepdive.evaluation.runner import source_hash,save
from deepdive.evidence.repository import SourceRepository
from deepdive.orchestration.controller import ResearchController
from deepdive.orchestration.models import ResearchSettings
from deepdive.orchestration.state_machine import TERMINAL
from deepdive.providers.llm import ModelService
from deepdive.providers.registry import create_source_collector
from deepdive.storage.database import ResearchRepository


async def resume(folder):
    manifest=json.loads((folder/'manifest.json').read_text())
    suite=json.loads((folder/'suite.json').read_text())
    if source_hash()!=manifest['source_hash']:
        raise SystemExit('Research/evaluator source changed; create a new comparable run instead.')
    repo=ResearchRepository(folder/'research')
    existing={(t['question'],t['config']['depth']):t for t in repo.list(100)}
    pairs=[(c,p) for c in suite['cases'] if c['id'] in manifest['cases'] for p in manifest['profiles']]
    def capture(case,profile,task):
        name=case['id']+'--'+profile
        if (folder/(name+'.metrics.json')).exists():return
        material=repo.materials(task['id']);report=repo.report(task['id']) or ''
        save(folder/(name+'.task.json'),{'task':task,'material':material})
        (folder/(name+'.md')).write_text(report)
        row={'case_id':case['id'],'category':case['category'],'profile':profile,'task_id':task['id'],'source_hash':manifest['source_hash'],**measure(task,material,report,case)}
        save(folder/(name+'.metrics.json'),row)
        save(folder/(name+'.review-template.json'),{'task_id':task['id'],'reviewer':'pending','aspects':{a['id']:None for a in case['aspects']},'facts':[],'notes':'Independent reference review required.'})
        with (folder/'progress.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        print(json.dumps({'case':case['id'],'profile':profile,'status':task['status'],'analysis':row['has_analysis'],'error':task['error_message']}),flush=True)
    interrupted=[]
    for case,profile in pairs:
        task=existing.get((case['question'],manifest['profiles'][profile]['depth']))
        if not task:continue
        if task['status'] not in TERMINAL:
            usage=task['usage'];usage.update(model_usage_complete=False,tool_usage_complete=False,cost_estimate_usd=None,interrupted=True,cost_note='评测进程被中断，用量不完整；仅保留已记录数据与预留上限，不估算账单。')
            repo.usage(task['id'],usage)
            repo.save_report(task['id'],writer.write(repo,task['id'],'评测进程中断；保留已有材料，不自动重试。'))
            repo.transition(task['id'],'FAILED','evaluation_process_interrupted')
            interrupted.append(task['id'])
        capture(case,profile,repo.get(task['id']))
    pending=[(c,p) for c,p in pairs if (c['question'],manifest['profiles'][p]['depth']) not in existing]
    save(folder/('resume-'+uuid4().hex[:8]+'.json'),{'created_at':datetime.now(timezone.utc).isoformat(),'interrupted_tasks':interrupted,'never_started_pairs':len(pending),'source_hash':source_hash(),'original_aggregate_cap_usd':manifest['max_aggregate_reserved_usd'],'retries':0})
    print(json.dumps({'resume':str(folder),'pending':len(pending),'interrupted':len(interrupted),'paid_retries':0}),flush=True)
    config=replace(ModelConfig.from_env(),timeout_seconds=manifest['model_timeout_seconds'])
    semaphore=asyncio.Semaphore(manifest['concurrency'])
    async def one(case,profile):
        async with semaphore:
            if source_hash()!=manifest['source_hash']:raise RuntimeError('Source changed during evaluation')
            task=repo.create(case['question'],ResearchSettings.model_validate(manifest['profiles'][profile]))
            tools=create_source_collector();tools.repository=SourceRepository(folder/'sources')
            await ResearchController(repo,ModelService(config),tools).run(task['id'])
            capture(case,profile,repo.get(task['id']))
    await asyncio.gather(*(one(c,p) for c,p in pending))
    results=[json.loads((folder/(c['id']+'--'+p+'.metrics.json')).read_text()) for c,p in pairs]
    if not (folder/'results.json').exists():save(folder/'results.json',results)
    if not (folder/'complete.json').exists():save(folder/'complete.json',{'completed_attempts':len(results),'source_unchanged':source_hash()==manifest['source_hash'],'interrupted_attempts_preserved':sum(r['error_code']=='evaluation_process_interrupted' for r in results)})
    print(json.dumps({'complete':True,'attempts':len(results),'run_dir':str(folder)}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run_dir');parser.add_argument('--confirmed-stopped',action='store_true',required=True)
    args=parser.parse_args();folder=Path(args.run_dir).resolve()
    if not folder.is_relative_to((ROOT/'data/evaluations').resolve()):parser.error('Run must be under project data/evaluations')
    with (folder/'resume.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        asyncio.run(resume(folder))


if __name__=='__main__':main()
