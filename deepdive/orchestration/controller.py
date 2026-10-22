import asyncio
import json
import logging
from contextlib import suppress

from pydantic import ValidationError

from deepdive.agents import planner,researcher,verifier,writer,synthesizer
from deepdive.orchestration.budget import Budget,BudgetExceeded
from deepdive.orchestration.pricing import price_profile
from deepdive.orchestration.models import ResearchSettings
from deepdive.orchestration.state_machine import TERMINAL
from deepdive.providers.llm import ModelFailure
from deepdive.tools.search.models import ToolFailure

logger=logging.getLogger('deepdive')


class ResearchController:
    def __init__(self,repository,model,collector):
        self.repository,self.model,self.collector=repository,model,collector

    async def run(self,task_id):
        task=self.repository.get(task_id)
        if not task or task['status']!='CREATED':
            return
        settings=ResearchSettings.model_validate(task['config'])
        budget=Budget(settings,self.repository,task_id,price_profile(self.model,self.collector))
        pipeline=None
        watcher=None
        try:
            if task['cancel_requested']:
                raise asyncio.CancelledError()
            self.repository.transition(task_id,'PLANNING')
            pipeline=asyncio.create_task(self._pipeline(task_id,task['question'],settings,budget))
            watcher=asyncio.create_task(self._watch_cancel(task_id,pipeline))
            async with asyncio.timeout(settings.timeout_seconds):
                await pipeline
        except TimeoutError:
            self._finish(task_id,budget,'TIMED_OUT','task_deadline_exceeded')
        except asyncio.CancelledError:
            self._finish(task_id,budget,'CANCELLED','cancel_requested_or_worker_stopped')
        except BudgetExceeded:
            self._finish(task_id,budget,'BUDGET_EXCEEDED','request_or_token_budget_exceeded')
        except (ModelFailure,ToolFailure) as exc:
            self._finish(task_id,budget,'FAILED',exc.code)
        except planner.StructuredOutputError as exc:
            self.repository.event(task_id,'model.output_rejected',{'reason':exc.reason,'issue_types':exc.issue_types,'issue_paths':exc.issue_paths})
            self._finish(task_id,budget,'FAILED','invalid_model_output')
        except (ValueError,ValidationError,json.JSONDecodeError):
            self._finish(task_id,budget,'FAILED','invalid_model_output')
        except Exception:
            self._finish(task_id,budget,'FAILED','research_execution_failed')
        finally:
            for child in (watcher,pipeline):
                if child and not child.done():
                    child.cancel()
                    with suppress(asyncio.CancelledError):
                        await child
            budget.save()

    async def _watch_cancel(self,task_id,pipeline):
        while not pipeline.done():
            await asyncio.sleep(0.2)
            if self.repository.get(task_id)['cancel_requested']:
                pipeline.cancel()
                return

    def _finish(self,task_id,budget,status,reason):
        task=self.repository.get(task_id)
        if task['status'] in TERMINAL:
            return
        budget.save()
        # Writing a partial report is local and never spends more provider budget.
        try:
            self.repository.save_report(task_id,writer.write(self.repository,task_id,reason))
        except OSError:
            reason=reason+':partial_report_file_unavailable'
        self.repository.transition(task_id,status,reason)
        self.repository.event(task_id,'task.failed' if status=='FAILED' else 'task.stopped',{'status':status,'reason':reason})
        logger.warning('',extra={'event':'research.stopped','status':status,'error_code':reason})

    async def _pipeline(self,task_id,question,settings,budget):
        async def model(prompt,instructions,max_tokens):
            budget.reserve_model(prompt,instructions,max_tokens)
            try:
                options={'timeout_seconds':min(180,settings.timeout_seconds)} if settings.depth=='deep' else {}
                result=await self.model.run(prompt,instructions=instructions,max_tokens=max_tokens,json_mode=True,**options)
            except BaseException:
                budget.used['model_usage_complete']=False
                budget.save()
                raise
            usage=result['usage']
            budget.used['model_requests']+=usage['requests']
            budget.used['input_tokens']+=usage['input_tokens']
            budget.used['output_tokens']+=usage['output_tokens']
            budget.save()
            if budget.used['input_tokens']+budget.used['output_tokens']>settings.max_total_tokens:
                raise BudgetExceeded()
            return result['answer']

        plan=await planner.plan(question,model,depth=settings.depth)
        self.repository.add_subtasks(task_id,plan)
        self.repository.event(task_id,'plan.created',plan.model_dump())
        queries=[item.question for item in sorted(plan.subquestions,key=lambda item:item.priority)]
        self.repository.transition(task_id,'RESEARCHING')
        partial_reason=None
        for round_index in range(settings.max_rounds):
            budget.used['rounds']=round_index+1
            budget.save()
            self.repository.event(task_id,'research.iteration',{'round':round_index+1})
            for query in queries:
                budget.reserve_tools(settings.max_sources_per_query)
                self.repository.event(task_id,'search.started',{'query':query})
                self.repository.subtask_status(task_id,query,'RESEARCHING')
                try:
                    collection=await self.collector.collect(query,settings.max_sources_per_query)
                except ToolFailure as exc:
                    budget.used['search_requests']+=exc.requests
                    budget.used['tool_usage_complete']=False
                    budget.save()
                    raise
                except BaseException:
                    budget.used['tool_usage_complete']=False
                    budget.save()
                    raise
                budget.used['search_requests']+=collection['search_requests']
                budget.used['fetch_requests']+=collection['provider_usage'].get('fetch_requests',0)
                budget.used['tool_usage_complete'] &= collection['provider_usage'].get('fetch_request_count_complete',True)
                budget.save()
                self.repository.add_sources(task_id,collection['sources'])
                self.repository.subtask_status(task_id,query,collection['status'])
                self.repository.event(task_id,'source.discovered',{'valid_sources':collection['valid_sources'],'collection_id':collection['id']})
                if collection['status']=='TIMED_OUT':
                    raise ToolFailure('collection_timeout','来源采集超时。',504)
            await researcher.findings(self.repository,task_id,question,model)
            self.repository.transition(task_id,'VERIFYING')
            needs_more=await verifier.verify(self.repository,task_id,model,plan.time_sensitive)
            material=self.repository.materials(task_id)
            has_sources=any(source['fetch_status']=='FETCHED' for source in material['sources'])
            needs_more=needs_more or not has_sources or not material['claims']
            self.repository.event(task_id,'verification.updated',{'needs_more_research':needs_more,'claims':len(material['claims'])})
            # Deep research explicitly tests a second perspective instead of stopping
            # merely because a few initial claims passed evidence checks.
            broaden=settings.depth=='deep' and round_index==0 and settings.max_rounds>1
            if not needs_more and not broaden:
                break
            if round_index+1==settings.max_rounds:
                partial_reason='达到最大研究轮数；仍有证据缺口，以下保留不确定性。'
                break
            # Do not spend all model calls on another collection round and leave
            # no capacity for evidence-based writing and its independent audit.
            review_batches=max(1,(min(48,len(material['evidence'])+24)+17)//18)
            next_round_and_analysis=2+review_batches+2
            if material['claims'] and budget.used['model_call_attempts']+next_round_and_analysis>settings.max_model_calls:
                partial_reason='为保留分析成文与独立审查的调用预算，停止继续扩展；仍有证据缺口。'
                self.repository.event(task_id,'research.expansion_stopped',{'reason':'reserve_analysis_calls'})
                break
            # Only the orchestrator expands research, within fixed limits and existing objectives.
            self.repository.transition(task_id,'NEEDS_MORE_RESEARCH')
            gaps=[{'claim':claim['claim_text'],'status':claim['verification_status'],'limitation':claim['limitation_note']} for claim in material['claims'] if claim['verification_status']!='SUPPORTED'][:6]
            if settings.depth=='deep':
                gaps.append({'objective':'Find counterevidence, boundary conditions and unanswered comparisons for the ORIGINAL question. Seek an independent perspective, not another introductory page.',
                             'previous_queries':queries,'covered_claims':[c['claim_text'] for c in material['claims']]})
            if not gaps:
                gaps=[{'limitation':'Retrieved pages did not yield evidence answering the original question.'}]
            try:
                followup=await planner.plan(question,model,gaps,depth=settings.depth)
            except planner.StructuredOutputError as exc:
                self.repository.event(task_id,'plan.expansion_rejected',{'reason':exc.reason,'issue_types':exc.issue_types,'issue_paths':exc.issue_paths})
                partial_reason='补充研究计划未通过结构校验，已停止扩展；以下分析仅基于已核验材料。'
                break
            self.repository.add_subtasks(task_id,followup)
            self.repository.event(task_id,'plan.updated',followup.model_dump())
            queries=[item.question for item in sorted(followup.subquestions,key=lambda item:item.priority)[:2]]
            self.repository.transition(task_id,'RESEARCHING')
        self.repository.transition(task_id,'WRITING')
        budget.save()
        self.repository.event(task_id,'report.progress',{'stage':'synthesizing_analysis'})
        analysis=None
        try:
            analysis=await synthesizer.synthesize(self.repository,task_id,model)
        except planner.StructuredOutputError as exc:
            self.repository.event(task_id,'report.analysis_fallback',{'reason':exc.reason,'issue_types':exc.issue_types,'issue_paths':exc.issue_paths})
            partial_reason=(partial_reason+' ' if partial_reason else '')+'分析成文未通过结构或引用校验，以下保留证据报告。'
        budget.save()
        self.repository.save_report(task_id,writer.write(self.repository,task_id,partial_reason,analysis))
        self.repository.transition(task_id,'COMPLETED')
        self.repository.event(task_id,'task.completed',{'partial':partial_reason is not None})
        logger.info('',extra={'event':'research.completed','status':'COMPLETED'})
