"""Stage 4 local research workspace, API, and durable event streams."""
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse

from fastapi.staticfiles import StaticFiles
from deepdive.config import ROOT
from deepdive.storage.worker_status import worker_running
from apps.api.routes.research import router as research_router
from deepdive.storage.database import ResearchRepository
from apps.api.schemas.sources import SourceRequest, SourceResponse
from deepdive.providers.registry import create_source_collector
from deepdive.tools.search.collect import summarize
from deepdive.tools.search.models import ToolFailure
from apps.api.middleware import RequestBodyLimit
from apps.api.schemas.agent import AgentRequest, AgentResponse, ErrorResponse
from deepdive.config import ConfigurationError, ModelConfig
from deepdive.observability.logging import configure_logging
from deepdive.providers.llm import ModelFailure, ModelService

logger = configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.model_service = ModelService(ModelConfig.from_env())
        logger.info("", extra={"event": "startup", "status": "configured"})
    except ConfigurationError:
        app.state.model_service = None
        logger.error("", extra={"event": "startup", "status": "degraded", "error_code": "model_not_configured"})
    try:
        app.state.source_collector = create_source_collector()
        logger.info("", extra={"event": "search.startup", "status": "configured"})
    except ConfigurationError:
        app.state.source_collector = None
        logger.warning("", extra={"event": "search.startup", "status": "degraded", "error_code": "search_not_configured"})
    app.state.research_repository = ResearchRepository()
    yield


app = FastAPI(title="DeepDive", version="0.4.0", lifespan=lifespan, docs_url=None, redoc_url=None)

app.add_middleware(RequestBodyLimit)


@app.middleware("http")
async def identify_request(request: Request, call_next):
    request.state.request_id = uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    if response.headers.get('content-type','').startswith('text/html'):
        response.headers['Cache-Control']='no-cache'

    return response


def error_response(request: Request, status: int, code: str, message: str):
    logger.warning("", extra={"event": "request.failed", "request_id": request.state.request_id, "error_code": code, "status": status})
    return JSONResponse(status_code=status, content={"request_id": request.state.request_id, "error": {"code": code, "message": message}})


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    return error_response(request, 422, "invalid_request", "输入字段、类型或长度不合法，请检查接口参数。")


@app.get("/", include_in_schema=False)
def root():
    page=ROOT/'apps/web/out/index.html'
    if not page.exists():
        return HTMLResponse('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>DeepDive</title><h1>前端尚未构建</h1><p>请在项目目录运行 npm ci 和 npm run build:web。</p></html>',status_code=503)
    return FileResponse(page,media_type='text/html')


@app.get("/api/health")
def health(request: Request) -> dict:
    return {"status": "ok", "stage": "4", "scope": "process", "model_configured": getattr(request.app.state, "model_service", None) is not None, "search_configured": getattr(request.app.state, "source_collector", None) is not None, "worker_running": worker_running(request.app.state.research_repository.directory) if hasattr(request.app.state,"research_repository") else False}


@app.post("/api/agent", response_model=AgentResponse, responses={status: {"model": ErrorResponse} for status in (413, 422, 502, 503, 504)})
async def run_agent(payload: AgentRequest, request: Request):
    service = getattr(request.app.state, "model_service", None)
    if service is None:
        return error_response(request, 503, "model_not_configured", "请在本地配置 DeepSeek 密钥、模型及服务地址后重启。")
    logger.info("", extra={"event": "agent.started", "request_id": request.state.request_id})
    try:
        result = await service.run(payload.prompt)
    except ModelFailure as exc:
        return error_response(request, exc.http_status, exc.code, exc.message)
    logger.info("", extra={"event": "agent.completed", "request_id": request.state.request_id, "duration_ms": result["duration_ms"], **result["usage"]})
    return {"request_id": request.state.request_id, **result}


@app.post("/api/sources", response_model=SourceResponse, responses={status: {"model": ErrorResponse} for status in (413, 422, 502, 503, 504)})
async def collect_sources(payload: SourceRequest, request: Request):
    collector = getattr(request.app.state, "source_collector", None)
    if collector is None:
        return error_response(request, 503, "search_not_configured", "请检查本地 SEARCH_PROVIDER 和对应密钥配置后重启服务。")
    logger.info("", extra={"event": "sources.started", "request_id": request.state.request_id})
    try:
        collection = await collector.collect(payload.question, payload.max_results)
    except ToolFailure as exc:
        return error_response(request, exc.http_status, exc.code, exc.message)
    logger.info("", extra={"event": "sources.completed", "request_id": request.state.request_id, "status": collection["status"]})
    return {"request_id": request.state.request_id, **summarize(collection)}


app.include_router(research_router)

app.mount("/",StaticFiles(directory=ROOT/"apps/web/out",html=True,check_dir=False),name="web")
