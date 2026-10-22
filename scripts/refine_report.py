"""Explicit paid refinement of stored evidence; preserves previous report versions and budgets."""
import argparse
import asyncio
import json
from time import monotonic

from deepdive.agents import synthesizer,writer
from deepdive.config import ModelConfig
from deepdive.orchestration.budget import Budget
from deepdive.orchestration.models import ResearchSettings
from deepdive.providers.llm import ModelService
from deepdive.storage.database import ResearchRepository


async def refine(task_id):
    repository=ResearchRepository()
    task=repository.get(task_id)
    if not task or task['status']!='COMPLETED':
        raise SystemExit('Only a completed research task can be refined.')
    settings=ResearchSettings.model_validate(task['config'])
    budget=Budget(settings,repository,task_id,task['usage'].get('price_profile'))
    budget.used.update(task['usage'])
    budget.started=monotonic()-task['usage'].get('duration_seconds',0)
    service=ModelService(ModelConfig.from_env())
    async def model(prompt,instructions,max_tokens):
        budget.reserve_model(prompt,instructions,max_tokens)
        try:
            result=await service.run(prompt,instructions=instructions,max_tokens=max_tokens,json_mode=True,timeout_seconds=min(180,settings.timeout_seconds))
        except BaseException:
            budget.used['model_usage_complete']=False
            budget.save()
            raise
        usage=result['usage']
        for key in ('input_tokens','output_tokens'):
            budget.used[key]+=usage[key]
        budget.used['model_requests']+=usage['requests']
        budget.save()
        return result['answer']
    repository.event(task_id,'report.progress',{'stage':'refining_stored_evidence'})
    remaining=settings.timeout_seconds-budget.used.get('duration_seconds',0)
    if remaining<=0:
        raise SystemExit('The original task time budget is exhausted.')
    async with asyncio.timeout(remaining):
        analysis=await synthesizer.synthesize(repository,task_id,model)
    budget.save()
    markdown=writer.write(repository,task_id,'基于已存材料重新综合与独立审查；未重新检索，未解决的证据缺口仍保留。',analysis)
    repository.save_report(task_id,markdown)
    print(json.dumps({'task_id':task_id,'analysis':analysis is not None,'sections':len(analysis.sections) if analysis else 0,'usage':budget.used},ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task_id')
    args=parser.parse_args()
    asyncio.run(refine(args.task_id))


if __name__=='__main__':
    main()
