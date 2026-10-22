"""Submit one real bounded research task to the API and wait for its worker."""
import argparse
import json
import time
import urllib.request
import urllib.error
from collections import Counter

from deepdive.orchestration.state_machine import TERMINAL


def execute():
    parser=argparse.ArgumentParser()
    parser.add_argument('question',nargs='?',default='What is Python asyncio and what kinds of applications use it? Prefer official documentation.')
    args=parser.parse_args()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(30):
        try:
            with opener.open('http://127.0.0.1:8000/api/health',timeout=1) as ready:
                assert json.load(ready)['stage']=='4'
            break
        except urllib.error.URLError:
            if attempt==29:
                raise
            time.sleep(0.2)
    payload={'question':args.question,'settings':{'max_rounds':1,'max_search_requests':6,'max_fetch_requests':60,
             'timeout_seconds':180,'max_sources_per_query':10,'max_model_calls':6,'max_total_tokens':64000,'max_budget_usd':0.25}}
    request=urllib.request.Request('http://127.0.0.1:8000/api/research',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    with opener.open(request,timeout=10) as response:
        assert response.status==202
        task=json.load(response)
    task_id=task['id']
    print(json.dumps({'task_id':task_id,'status':task['status']}),flush=True)
    previous=task['status']
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        with opener.open('http://127.0.0.1:8000/api/research/'+task_id,timeout=10) as response:
            task=json.load(response)
        if task['status']!=previous:
            print(json.dumps({'task_id':task_id,'status':task['status']}),flush=True)
            previous=task['status']
        if task['status'] in TERMINAL:
            with opener.open('http://127.0.0.1:8000/api/research/'+task_id+'/evidence',timeout=10) as response:
                material=json.load(response)
            print(json.dumps({'task_id':task_id,'status':task['status'],'error_code':task['error_message'],
                'valid_sources':sum(s['fetch_status']=='FETCHED' for s in material['sources']),
                'claims':len(material['claims']),'evidence':len(material['evidence']),
                'verification':dict(Counter(c['verification_status'] for c in material['claims'])),'usage':task['usage']},ensure_ascii=False),flush=True)
            return 0 if task['status']=='COMPLETED' and material['evidence'] else 1
        time.sleep(1)
    print(json.dumps({'task_id':task_id,'status':'probe_wait_timeout','message':'Task remains persisted; inspect API state.'}),flush=True)
    return 1


def main():
    try:
        return execute()
    except (urllib.error.URLError,TimeoutError,ValueError) as error:
        print(json.dumps({'status':'probe_failed','error_type':type(error).__name__,'message':'Check local API/worker and the saved task state; no automatic resubmission.'}))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
