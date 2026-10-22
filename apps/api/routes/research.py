import asyncio
import json
import re
from time import monotonic

from fastapi import APIRouter,Request,Response,Query,Header
from fastapi.responses import JSONResponse,PlainTextResponse,StreamingResponse

from deepdive.orchestration.state_machine import TERMINAL
from deepdive.orchestration.pricing import price_profile
from apps.api.schemas.agent import ErrorResponse
from apps.api.schemas.research import ResearchRequest,TaskResponse,MaterialResponse

router=APIRouter(prefix='/api/research',responses={status:{'model':ErrorResponse} for status in (404,409,422,503)})


def error(request,status,code,message):
    return JSONResponse(status_code=status,content={'request_id':request.state.request_id,'error':{'code':code,'message':message}})


@router.post('',response_model=TaskResponse,status_code=202)
def create(payload:ResearchRequest,request:Request):
    if request.app.state.model_service is None or request.app.state.source_collector is None:
        return error(request,503,'research_not_configured','请检查模型与搜索配置。')
    if payload.settings.max_budget_usd is not None and price_profile(request.app.state.model_service,request.app.state.source_collector) is None:
        return error(request,422,'pricing_unavailable','当前 Provider/模型没有已核实的单价快照，不能启用美元预算；可使用请求及 token 上限。')
    return request.app.state.research_repository.create(payload.question,payload.settings)


@router.get('',response_model=list[TaskResponse])
def list_tasks(request:Request,response:Response,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),status:str=Query('all',pattern='^(all|running|completed|stopped)$')):
    groups={'all':None,'running':['CREATED','PLANNING','RESEARCHING','VERIFYING','NEEDS_MORE_RESEARCH','WRITING'],'completed':['COMPLETED'],'stopped':['FAILED','CANCELLED','BUDGET_EXCEEDED','TIMED_OUT']}
    repository=request.app.state.research_repository
    response.headers['X-Total-Count']=str(repository.count(groups[status]))
    return repository.list(limit,offset,groups[status])


@router.get('/summary')
def summary(request:Request) -> dict[str,int]:
    return request.app.state.research_repository.counts()


@router.get('/{task_id}',response_model=TaskResponse)
def get_task(task_id:str,request:Request):
    task=request.app.state.research_repository.get(task_id)
    return task if task else error(request,404,'task_not_found','研究任务不存在。')


@router.post('/{task_id}/cancel',response_model=TaskResponse)
def cancel(task_id:str,request:Request):
    task=request.app.state.research_repository.cancel(task_id)
    return task if task else error(request,404,'task_not_found','研究任务不存在。')


@router.get('/{task_id}/report')
def report(task_id:str,request:Request,download:bool=False):
    repository=request.app.state.research_repository
    if not repository.get(task_id):
        return error(request,404,'task_not_found','研究任务不存在。')
    markdown=repository.report(task_id)
    if markdown is None:
        return error(request,409,'report_not_ready','研究报告尚未生成。')
    headers={'Content-Disposition':'attachment; filename="deepdive-'+task_id+'.md"'} if download else {}
    return PlainTextResponse(markdown,media_type='text/markdown',headers=headers)


@router.get('/{task_id}/evidence',response_model=MaterialResponse)
def evidence(task_id:str,request:Request):
    repository=request.app.state.research_repository
    if not repository.get(task_id):
        return error(request,404,'task_not_found','研究任务不存在。')
    material=repository.materials(task_id)
    material['sources']=[{key:value for key,value in source.items() if key!='extracted_text'}|{'excerpt':source['extracted_text'][:1000]} for source in material['sources']]
    return material


async def research_events(repository,task_id,request,cursor):
    heartbeat=monotonic()
    while not await request.is_disconnected():
        events=await asyncio.to_thread(repository.events_after,task_id,cursor,100)
        for event in events:
            cursor=event['id']
            name=event['type'] if re.fullmatch(r'[a-z._]+',event['type']) else 'research.event'
            yield 'id: '+str(cursor)+'\nevent: '+name+'\ndata: '+json.dumps(event,ensure_ascii=False)+'\n\n'
        if len(events)==100:
            continue
        task=await asyncio.to_thread(repository.get,task_id)
        if task['status'] in TERMINAL:
            yield 'event: stream.end\ndata: '+json.dumps({'status':task['status'],'cursor':cursor})+'\n\n'
            return
        if monotonic()-heartbeat>=10:
            yield ': heartbeat\n\n'
            heartbeat=monotonic()
        await asyncio.sleep(0.5)


@router.get('/{task_id}/events',response_class=StreamingResponse,responses={200:{'description':'Durable research events and terminal stream.end','content':{'text/event-stream':{'schema':{'type':'string'}}}}})
async def events(task_id:str,request:Request,after:int=Query(0,ge=0,le=9223372036854775807),last_event_id:str|None=Header(default=None)):
    repository=request.app.state.research_repository
    if not repository.get(task_id):
        return error(request,404,'task_not_found','研究任务不存在。')
    if last_event_id is not None:
        if not last_event_id.isascii() or not last_event_id.isdecimal() or len(last_event_id)>19 or int(last_event_id)>9223372036854775807:
            return error(request,422,'invalid_event_cursor','事件游标不合法。')
        after=max(after,int(last_event_id))
    return StreamingResponse(research_events(repository,task_id,request,after),media_type='text/event-stream',
                             headers={'Cache-Control':'no-cache, no-transform','X-Accel-Buffering':'no'})
