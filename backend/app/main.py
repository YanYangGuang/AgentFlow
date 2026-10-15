import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from .db import Base, SessionLocal, engine, get_db, migrate_additive_schema
from .models import (AppSettingRecord, EvaluationCaseResultRecord, EvaluationDatasetRecord, EvaluationRunRecord,
                     ModelProviderConfigRecord, ModelProviderCredentialRecord, ModelProviderRecord, NodeRunRecord,
                     RunEventRecord, RunRecord, TaskRecord, WorkflowRecord, WorkflowVersionRecord, utcnow)
from .schemas import (DashboardSummary, ModelSettingsOut, ModelTestOut, NodeRunOut, ProviderCatalogItem, ProviderConfigUpdate,
                      ProviderModelItem, ProviderTestRequest, ProviderTestResult, RunEventOut, RunOut, RunPage, TaskCreate, TaskOut, TaskPage, TaskUpdate,
                      EvaluationDatasetCreate, EvaluationDatasetOut, EvaluationRunOut, EvaluationStart, RuntimeModeOut, RuntimeModeUpdate,
                      WorkflowCreate, WorkflowGraph, WorkflowOut, WorkflowRunCreate, WorkflowUpdate, WorkflowValidationResult, WorkflowVersionOut)
from .services.live_model import chat_completion, model_settings, test_connection
from .services.provider_config import (PROVIDERS, config_for, credential_for, decrypt_secret, encrypt_secret,
                                       ensure_provider_catalog, provider_code, provider_view, safe_base_url,
                                       seed_legacy_default, update_test_status)
from .services.provider_runtime import fetch_models, verify_provider
from .services.workflow_engine import run_node, validate_graph

DEMO_WORKFLOW_SNAPSHOT = json.dumps({"workflow_id": "workflow_demo_default", "version": 1, "nodes": [], "edges": []})
active_demo_tasks: set[asyncio.Task] = set()
logger = logging.getLogger("agentflow.execution")

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def workflow_snapshot(workflow_id: str, name: str, description: str, version: int, nodes: list[dict], edges: list[dict]) -> str:
    return json.dumps({"workflow_id": workflow_id, "name": name, "description": description, "version": version,
                       "nodes": nodes, "edges": edges}, ensure_ascii=False, separators=(",", ":"))

def workflow_response(record: WorkflowRecord) -> dict:
    return {"id": record.id, "name": record.name, "description": record.description, "version": record.version,
            "is_default": record.is_default, "is_archived": record.is_archived,
            "nodes": json.loads(record.nodes_json), "edges": json.loads(record.edges_json),
            "created_at": record.created_at, "updated_at": record.updated_at}

def runtime_mode(db: Session) -> str:
    setting = db.get(AppSettingRecord, "execution_mode")
    return setting.value if setting and setting.value in {"demo", "live"} else "demo"

def require_global_mode(db: Session, requested: str | None) -> str:
    active = runtime_mode(db)
    if requested and requested != active:
        if requested == "live" and not model_settings(db)["live_enabled"]:
            raise HTTPException(status_code=403, detail={"code": "LIVE_EXECUTION_DISABLED", "message": "后端真实执行开关未启用，无法运行真实任务。"})
        raise HTTPException(status_code=409, detail={"code": "RUNTIME_MODE_MISMATCH", "message": f"全局执行环境为{ '真实环境' if active == 'live' else '安全沙盒' }，请在侧栏切换后再运行。"})
    return active

DEFAULT_NODES = [
    {"id": "input_1", "type": "input", "label": "任务输入", "position": {"x": 80, "y": 180}, "config": {}},
    {"id": "llm_1", "type": "llm", "label": "智能整理", "position": {"x": 340, "y": 180}, "config": {"prompt_template": "对输入目标进行结构化整理"}},
    {"id": "tool_1", "type": "tool", "label": "文本摘要", "position": {"x": 600, "y": 180}, "config": {"tool_name": "text_summary"}},
    {"id": "output_1", "type": "output", "label": "最终输出", "position": {"x": 860, "y": 180}, "config": {}},
]
DEFAULT_EDGES = [{"id": f"edge_{source}_{target}", "source": source, "target": target} for source, target in [("input_1", "llm_1"), ("llm_1", "tool_1"), ("tool_1", "output_1")]]
LEGACY_DEMO_SEED_OUTPUTS = {
    "整理本周产品反馈": "演示结果：反馈主要集中在新手引导、搜索体验和导出能力。",
    "分析竞品定价页面": "演示失败案例：输入数据不满足示例校验条件。",
    "生成行业趋势简报": "演示结果：市场关注点集中在自动化、数据治理与可观测性。",
}

def remove_legacy_demo_seed_rows(db: Session) -> None:
    """Remove only the exact synthetic rows shipped by the first database bootstrap."""
    records = db.scalars(select(TaskRecord).options(selectinload(TaskRecord.runs)).where(
        TaskRecord.mode == "demo", TaskRecord.workflow == "默认工作流", TaskRecord.title.in_(LEGACY_DEMO_SEED_OUTPUTS))).all()
    for task in records:
        marker = LEGACY_DEMO_SEED_OUTPUTS[task.title]
        is_seed = any(run.workflow_snapshot == DEMO_WORKFLOW_SNAPSHOT and
                      (run.output_text == marker or run.error_message == marker) for run in task.runs)
        if is_seed:
            db.delete(task)
    db.commit()

async def execute_demo_run(run_id: str) -> None:
    """Local deterministic demo execution; never contacts models or external tools."""
    started = utcnow()
    with SessionLocal() as db:
        run = db.get(RunRecord, run_id)
        if not run or run.status != "queued":
            return
        run.status = "running"
        run.started_at = started
        task = db.get(TaskRecord, run.task_id)
        if task:
            task.status = "running"
        db.commit()

def record_event(db, run_id: str, event: str, status: str, message: str, node_id: str | None = None, data: dict | None = None) -> None:
    db.add(RunEventRecord(id=new_id("evt"), run_id=run_id, node_id=node_id, event=event, status=status,
                          message=message, data_json=json.dumps(data or {}, ensure_ascii=False)))

async def execute_workflow_run(run_id: str) -> None:
    task_title, task_description, run_mode = "", "", "demo"
    with SessionLocal() as db:
        run = db.get(RunRecord, run_id)
        if not run or run.status != "queued":
            return
        task = db.get(TaskRecord, run.task_id)
        task_title = task.title if task else ""
        task_description = task.description if task else ""
        run_mode = run.mode
        snapshot = json.loads(run.workflow_snapshot)
        nodes, edges = snapshot.get("nodes", []), snapshot.get("edges", [])
        order, errors = validate_graph(nodes, edges)
        if errors:
            run.status = "failed"; run.error_message = "；".join(errors); run.finished_at = utcnow()
            if task: task.status = "failed"
            record_event(db, run_id, "run.failed", "failed", run.error_message)
            db.commit()
            return
        run.status = "running"; run.started_at = utcnow()
        if task: task.status = "running"
        record_event(db, run_id, "run.started", "running", "工作流开始执行。", data={"workflow_version": run.workflow_version, "mode": run_mode})
        existing = {item.node_id: item for item in db.scalars(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id))}
        for node in nodes:
            item = existing.get(node["id"])
            if item is None:
                item = NodeRunRecord(id=new_id("node_run"), run_id=run_id, node_id=node["id"], node_type=node["type"], label=node["label"])
                db.add(item)
            item.node_type = node["type"]; item.label = node["label"]; item.status = "queued"
            item.input_json = "{}"; item.output_json = None; item.error_message = None
            item.started_at = None; item.finished_at = None; item.duration_ms = None
        db.commit()

    node_by_id = {node["id"]: node for node in nodes}
    incoming = {node["id"]: [edge["source"] for edge in edges if edge["target"] == node["id"]] for node in nodes}
    values: dict[str, object] = {}
    failed_node: str | None = None
    tokens_known = True
    for index, node_id in enumerate(order):
        node = node_by_id[node_id]
        upstream = [values[source] for source in incoming[node_id] if source in values]
        inputs = {"upstream": upstream}
        with SessionLocal() as db:
            parent_run = db.get(RunRecord, run_id)
            if not parent_run or parent_run.status != "running":
                return
            node_run = db.scalar(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id, NodeRunRecord.node_id == node_id))
            node_run.status = "running"; node_run.started_at = utcnow(); node_run.input_json = json.dumps(inputs, ensure_ascii=False)
            record_event(db, run_id, "node.started", "running", f"开始执行：{node['label']}", node_id)
            db.commit()
        try:
            usage: dict = {}
            if run_mode == "live" and node["type"] == "llm":
                config = node.get("config") or {}
                if config.get("simulate_failure"):
                    raise RuntimeError("节点配置为演示失败；请关闭失败演示后重试真实运行。")
                upstream_text = "\n".join(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False) for value in upstream)
                prompt = (f"任务目标：{task_title}\n补充说明：{task_description}\n处理要求：{config.get('prompt_template') or '对输入进行清晰、简洁的整理'}\n"
                          f"上游节点结果：\n{upstream_text[:10000]}\n请基于以上信息完成任务，并明确区分事实与推断。")
                usage = await chat_completion(prompt)
                output = {"text": usage["text"], "model": usage["model"]}
                if usage["tokens"] is None:
                    tokens_known = False
            else:
                output = run_node(node, upstream, task_title, task_description)
            if run_mode == "demo":
                await asyncio.sleep(0.25)
            values[node_id] = output
            with SessionLocal() as db:
                parent_run = db.get(RunRecord, run_id)
                if not parent_run or parent_run.status != "running":
                    return
                now = utcnow()
                node_run = db.scalar(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id, NodeRunRecord.node_id == node_id))
                node_started = node_run.started_at or now
                if node_started.tzinfo is None: node_started = node_started.replace(tzinfo=timezone.utc)
                node_run.status = "succeeded"; node_run.finished_at = now
                node_run.duration_ms = max(1, int((now - node_started).total_seconds() * 1000))
                node_run.output_json = json.dumps(output, ensure_ascii=False)
                event_data = {"duration_ms": node_run.duration_ms}
                if usage:
                    event_data.update({"model": usage["model"], "tokens": usage["tokens"]})
                    record = db.get(RunRecord, run_id)
                    if usage["tokens"] is not None:
                        record.tokens = (record.tokens or 0) + usage["tokens"]
                record_event(db, run_id, "node.completed", "succeeded", f"已完成：{node['label']}", node_id, event_data)
                db.commit()
        except Exception as exc:
            failed_node = node_id
            with SessionLocal() as db:
                parent_run = db.get(RunRecord, run_id)
                if not parent_run or parent_run.status != "running":
                    return
                now = utcnow()
                node_run = db.scalar(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id, NodeRunRecord.node_id == node_id))
                node_run.status = "failed"; node_run.finished_at = now; node_run.error_message = str(exc)
                record_event(db, run_id, "node.failed", "failed", f"{node['label']} 执行失败：{exc}", node_id)
                for skipped_id in order[index + 1:]:
                    skipped = db.scalar(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id, NodeRunRecord.node_id == skipped_id))
                    skipped.status = "skipped"; skipped.error_message = "上游节点失败，已跳过。"
                    record_event(db, run_id, "node.skipped", "skipped", f"跳过：{node_by_id[skipped_id]['label']}", skipped_id)
                db.commit()
            break

    with SessionLocal() as db:
        run = db.get(RunRecord, run_id)
        if not run or run.status != "running":
            return
        task = db.get(TaskRecord, run.task_id) if run else None
        now = utcnow()
        run_started = run.started_at or now
        if run_started.tzinfo is None: run_started = run_started.replace(tzinfo=timezone.utc)
        run.duration_ms = max(1, int((now - run_started).total_seconds() * 1000))
        run.finished_at = now
        if run_mode == "live" and not tokens_known:
            run.tokens = None
        if failed_node:
            run.status = "failed"
            failed_record = db.scalar(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id, NodeRunRecord.node_id == failed_node))
            run.error_message = failed_record.error_message if failed_record else "工作流节点执行失败。"
            if task: task.status = "failed"; task.duration_ms = run.duration_ms
            record_event(db, run_id, "run.failed", "failed", run.error_message, failed_node)
        else:
            output_node = next(node["id"] for node in nodes if node["type"] == "output")
            output = values.get(output_node, {})
            run.status = "succeeded"; run.output_text = str(output.get("result", output)) if isinstance(output, dict) else str(output)
            if task: task.status = "succeeded"; task.duration_ms = run.duration_ms
            record_event(db, run_id, "run.completed", "succeeded", "工作流执行完成。", data={"duration_ms": run.duration_ms})
        db.commit()

def schedule_demo_run(run_id: str) -> None:
    with SessionLocal() as db:
        run = db.get(RunRecord, run_id)
        is_workflow = bool(run and run.workflow_id)
    task = asyncio.create_task(execute_workflow_run(run_id) if is_workflow else execute_demo_run(run_id))
    active_demo_tasks.add(task)
    def on_done(completed: asyncio.Task) -> None:
        active_demo_tasks.discard(completed)
        error = None if completed.cancelled() else completed.exception()
        if error:
            logger.error("Workflow execution task raised an exception", exc_info=(type(error), error, error.__traceback__))
    task.add_done_callback(on_done)


def evaluation_response(record: EvaluationRunRecord) -> dict:
    return {
        "id": record.id, "dataset_id": record.dataset_id, "dataset_name": record.dataset_name,
        "workflow_id": record.workflow_id, "workflow_name": record.workflow_name,
        "workflow_version": record.workflow_version, "mode": record.mode, "status": record.status,
        "model_name": record.model_name,
        "case_count": record.case_count, "passed_count": record.passed_count, "score": record.score,
        "started_at": record.started_at, "finished_at": record.finished_at, "error_message": record.error_message,
        "results": [{"id": item.id, "case_index": item.case_index, "title": item.title, "input_text": item.input_text,
                     "expected_contains": json.loads(item.expected_contains_json), "run_id": item.run_id,
                     "status": item.status, "passed": item.passed, "output_text": item.output_text,
                     "error_message": item.error_message, "duration_ms": item.duration_ms} for item in record.results],
    }


async def execute_evaluation(evaluation_id: str) -> None:
    with SessionLocal() as db:
        evaluation = db.get(EvaluationRunRecord, evaluation_id)
        if not evaluation or evaluation.status != "queued":
            return
        evaluation.status = "running"
        evaluation.started_at = utcnow()
        db.commit()

    for result_id in _evaluation_result_ids(evaluation_id):
        with SessionLocal() as db:
            evaluation = db.get(EvaluationRunRecord, evaluation_id)
            result = db.get(EvaluationCaseResultRecord, result_id)
            if not evaluation or not result:
                continue
            task_id, run_id = new_id("task"), new_id("run")
            case_title = result.title
            task = TaskRecord(id=task_id, title=case_title, description=result.input_text, status="queued",
                              mode=evaluation.mode, workflow=evaluation.workflow_name, origin="evaluation")
            run = RunRecord(id=run_id, task_id=task_id, mode=evaluation.mode, status="queued",
                            workflow=evaluation.workflow_name, workflow_id=evaluation.workflow_id,
                            workflow_version=evaluation.workflow_version, workflow_snapshot=evaluation.workflow_snapshot)
            run.task = task
            db.add_all([task, run])
            result.run_id = run_id
            result.status = "running"
            db.commit()
        try:
            await execute_workflow_run(run_id)
            with SessionLocal() as db:
                run = db.get(RunRecord, run_id)
                result = db.get(EvaluationCaseResultRecord, result_id)
                if not run or not result:
                    continue
                result.status = run.status
                result.output_text = run.output_text
                result.error_message = run.error_message
                result.duration_ms = run.duration_ms
                expected = json.loads(result.expected_contains_json)
                output = (run.output_text or "").casefold()
                result.passed = run.status == "succeeded" and all(term.casefold() in output for term in expected)
                db.commit()
        except Exception as exc:
            logger.exception("Evaluation case execution failed evaluation_id=%s", evaluation_id)
            with SessionLocal() as db:
                result = db.get(EvaluationCaseResultRecord, result_id)
                if result:
                    result.status = "failed"
                    result.passed = False
                    result.error_message = "评测用例执行异常，请查看对应运行记录。"
                    db.commit()

    with SessionLocal() as db:
        evaluation = db.get(EvaluationRunRecord, evaluation_id)
        if not evaluation:
            return
        items = list(db.scalars(select(EvaluationCaseResultRecord).where(EvaluationCaseResultRecord.evaluation_run_id == evaluation_id)))
        evaluation.passed_count = sum(1 for item in items if item.passed is True)
        evaluation.case_count = len(items)
        evaluation.score = round(evaluation.passed_count / len(items), 4) if items else None
        evaluation.status = "completed"
        evaluation.finished_at = utcnow()
        db.commit()


def _evaluation_result_ids(evaluation_id: str) -> list[str]:
    with SessionLocal() as db:
        return list(db.scalars(select(EvaluationCaseResultRecord.id).where(
            EvaluationCaseResultRecord.evaluation_run_id == evaluation_id).order_by(EvaluationCaseResultRecord.case_index)))


def schedule_evaluation(evaluation_id: str) -> None:
    task = asyncio.create_task(execute_evaluation(evaluation_id))
    active_demo_tasks.add(task)
    def on_done(completed: asyncio.Task) -> None:
        active_demo_tasks.discard(completed)
        error = None if completed.cancelled() else completed.exception()
        if error:
            logger.error("Evaluation task raised an exception", exc_info=(type(error), error, error.__traceback__))
    task.add_done_callback(on_done)

async def seed_demo_workflows(db: Session) -> None:
    records = list(db.scalars(select(WorkflowRecord).where(WorkflowRecord.is_archived.is_(False)).order_by(WorkflowRecord.created_at)))
    if records:
        if not any(item.is_default for item in records):
            records[0].is_default = True
            db.commit()
        return
    workflow_id = "workflow_demo_default"
    snapshot = workflow_snapshot(workflow_id, "快速开始流程", "可编辑的输入、模型处理和输出起始模板。", 1, DEFAULT_NODES, DEFAULT_EDGES)
    record = WorkflowRecord(id=workflow_id, name="快速开始流程", description="可编辑的输入、模型处理和输出起始模板。", version=1, is_default=True,
                            nodes_json=json.dumps(DEFAULT_NODES, ensure_ascii=False), edges_json=json.dumps(DEFAULT_EDGES, ensure_ascii=False))
    db.add(record)
    db.add(WorkflowVersionRecord(workflow_id=workflow_id, version=1, snapshot_json=snapshot))
    db.commit()

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_additive_schema()
    with SessionLocal() as db:
        ensure_provider_catalog(db)
        seed_legacy_default(db)
        await seed_demo_workflows(db)
        remove_legacy_demo_seed_rows(db)
        stored_mode = db.get(AppSettingRecord, "execution_mode")
        current_model = model_settings(db)
        if stored_mode and stored_mode.value == "live" and (not current_model["live_enabled"] or not current_model["configured"]):
            stored_mode.value = "demo"; stored_mode.updated_at = utcnow()
        active_tasks = list(db.scalars(select(TaskRecord).options(selectinload(TaskRecord.runs)).where(TaskRecord.origin == "task", TaskRecord.status.in_(["queued", "running"]))))
        for task in active_tasks:
            active_runs = [run for run in task.runs if run.status in {"queued", "running"}]
            if not active_runs:
                db.add(RunRecord(id=new_id("run"), task_id=task.id, mode=task.mode, status="queued", workflow=task.workflow,
                    workflow_version=1, workflow_snapshot=DEMO_WORKFLOW_SNAPSHOT))
                task.status = "queued"
        pending = list(db.scalars(select(RunRecord).join(TaskRecord, RunRecord.task_id == TaskRecord.id).where(
            RunRecord.mode == "demo", TaskRecord.origin == "task", RunRecord.status.in_(["queued", "running"]))))
        interrupted_live = list(db.scalars(select(RunRecord).where(RunRecord.mode == "live", RunRecord.status.in_(["queued", "running"]))))
        for run in interrupted_live:
            run.status = "failed"
            run.finished_at = utcnow()
            run.error_message = "服务重启中断了真实模型运行；请检查账单状态后手动重新运行。"
            task = db.get(TaskRecord, run.task_id)
            if task:
                task.status = "failed"
            record_event(db, run.id, "run.failed", "failed", run.error_message)
        interrupted_evaluations = list(db.scalars(select(EvaluationRunRecord).options(selectinload(EvaluationRunRecord.results)).where(EvaluationRunRecord.status == "running")))
        for evaluation in interrupted_evaluations:
            evaluation.status = "failed"
            evaluation.finished_at = utcnow()
            evaluation.error_message = "服务重启中断了评测；请重新启动本次评测。"
            for result in evaluation.results:
                if result.status in {"queued", "running"}:
                    result.status = "failed"; result.passed = False
                    result.error_message = "服务重启中断了该评测用例。"
                    if result.run_id:
                        case_run = db.get(RunRecord, result.run_id)
                        if case_run and case_run.status in {"queued", "running"}:
                            case_run.status = "failed"; case_run.finished_at = utcnow()
                            case_run.error_message = result.error_message
                            case_task = db.get(TaskRecord, case_run.task_id)
                            if case_task: case_task.status = "failed"
        pending_evaluations = list(db.scalars(select(EvaluationRunRecord.id).where(EvaluationRunRecord.status == "queued")))
        for run in pending:
            run.status = "queued"
            run.started_at = None
            task = db.get(TaskRecord, run.task_id)
            if task:
                task.status = "queued"
        db.commit()
        pending_ids = [run.id for run in pending]
    for run_id in pending_ids:
        schedule_demo_run(run_id)
    for evaluation_id in pending_evaluations:
        schedule_evaluation(evaluation_id)
    try:
        yield
    finally:
        recovery = list(active_demo_tasks)
        for work in recovery:
            work.cancel()
        if recovery:
            await asyncio.gather(*recovery, return_exceptions=True)

app = FastAPI(title="AgentFlow API", version="0.2.0", description="AI Agent 工作流平台 API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "HTTP_ERROR", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": detail})

@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    # Pydantic v2 includes submitted values in validation errors; never echo credential inputs.
    details = [{key: value for key, value in item.items() if key not in {"input", "ctx", "url"}} for item in exc.errors()]
    payload = {"error": {"code": "VALIDATION_ERROR", "message": "请求参数无效。", "details": details}}
    return JSONResponse(status_code=422, content=jsonable_encoder(payload))

def not_found(resource: str):
    return HTTPException(status_code=404, detail={"code": f"{resource.upper()}_NOT_FOUND", "message": f"未找到该{resource}。"})

@app.get("/api/v1/health")
def health(db: Session = Depends(get_db)):
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "service": "agentflow-api", "database": "ok", "mode": runtime_mode(db)}

@app.get("/api/v1/system/runtime", response_model=RuntimeModeOut)
def get_runtime_settings(db: Session = Depends(get_db)):
    settings = model_settings(db)
    return {"mode": runtime_mode(db), "live_execution_enabled": settings["live_enabled"],
            "model_configured": settings["configured"], "provider": settings["provider"], "model": settings["model"]}

@app.put("/api/v1/system/runtime/mode", response_model=RuntimeModeOut)
def update_runtime_mode(payload: RuntimeModeUpdate, db: Session = Depends(get_db)):
    settings = model_settings(db)
    if payload.mode == "live":
        if not settings["live_enabled"]:
            raise HTTPException(status_code=403, detail={"code": "LIVE_EXECUTION_DISABLED", "message": "后端真实执行开关未启用，无法切换到真实环境。"})
        if not settings["configured"]:
            raise HTTPException(status_code=409, detail={"code": "MODEL_NOT_CONFIGURED", "message": "尚未配置默认模型凭据，无法切换到真实环境。"})
    setting = db.get(AppSettingRecord, "execution_mode")
    if setting:
        setting.value = payload.mode
        setting.updated_at = utcnow()
    else:
        db.add(AppSettingRecord(key="execution_mode", value=payload.mode))
    db.commit()
    return {"mode": payload.mode, "live_execution_enabled": settings["live_enabled"],
            "model_configured": settings["configured"], "provider": settings["provider"], "model": settings["model"]}

@app.get("/api/v1/models", response_model=ModelSettingsOut)
def get_model_settings(db: Session = Depends(get_db)):
    return model_settings(db)

@app.get("/api/v1/models/providers", response_model=list[ProviderCatalogItem])
def list_model_providers(db: Session = Depends(get_db)):
    ensure_provider_catalog(db)
    providers = list(db.scalars(select(ModelProviderRecord).where(ModelProviderRecord.enabled.is_(True)).order_by(ModelProviderRecord.sort_order)))
    return [provider_view(db, provider, config_for(db, provider.code)) for provider in providers]

@app.put("/api/v1/models/providers/{code}", response_model=ProviderCatalogItem)
def save_model_provider(code: str, payload: ProviderConfigUpdate, db: Session = Depends(get_db)):
    code = provider_code(code)
    provider = db.scalar(select(ModelProviderRecord).where(ModelProviderRecord.code == code, ModelProviderRecord.enabled.is_(True)))
    if not provider:
        raise not_found("model provider")
    try:
        base_url = safe_base_url(payload.api_base_url, provider.protocol)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_PROVIDER_URL", "message": str(exc)}) from exc
    if not payload.default_model_id.strip():
        raise HTTPException(status_code=422, detail={"code": "MODEL_ID_REQUIRED", "message": "请填写默认模型 ID；模型目录不可用时也可以手动输入。"})
    config = config_for(db, code)
    is_new = config is None
    if is_new:
        config = ModelProviderConfigRecord(id=new_id("model_config"), scope_id="local", provider_id=provider.id,
            api_base_url=base_url, default_model_id=payload.default_model_id.strip(), is_enabled=payload.is_enabled,
            is_default=False, last_test_status="unconfigured", last_test_message="", config_version=1)
        db.add(config)
    else:
        changed = config.api_base_url != base_url or config.default_model_id != payload.default_model_id.strip() or config.is_enabled != payload.is_enabled
        config.api_base_url = base_url
        config.default_model_id = payload.default_model_id.strip()
        config.is_enabled = payload.is_enabled
        config.config_version += 1 if changed else 0
        if changed:
            update_test_status(config, "not_tested", "配置已修改，请重新测试连接。")
    if payload.api_key is not None and payload.api_key.strip():
        try:
            encrypted, fingerprint = encrypt_secret(payload.api_key.strip())
        except RuntimeError as exc:
            db.rollback()
            raise HTTPException(status_code=503, detail={"code": "CREDENTIAL_ENCRYPTION_UNAVAILABLE", "message": str(exc)}) from exc
        credential = credential_for(db, config)
        if credential:
            credential.encrypted_secret = encrypted
            credential.key_fingerprint = fingerprint
            credential.encryption_key_version = "fernet-v1"
            credential.updated_at = utcnow()
        else:
            credential = ModelProviderCredentialRecord(id=new_id("credential"), scope_id="local", provider_id=provider.id,
                encrypted_secret=encrypted, encryption_key_version="fernet-v1", key_fingerprint=fingerprint)
            db.add(credential)
            db.flush()
            config.credential_id = credential.id
        config.config_version += 1
        update_test_status(config, "not_tested", "凭据已更新，请重新测试连接。")
    elif is_new and (config.credential_id or (code == "openrouter" and os.getenv("AGENTFLOW_LLM_API_KEY", "").strip())):
        update_test_status(config, "not_tested", "供应商已配置，请测试连接。")
    if not config.is_enabled and config.is_default:
        config.is_default = False
    elif config.is_enabled:
        for other in db.scalars(select(ModelProviderConfigRecord).where(ModelProviderConfigRecord.scope_id == "local", ModelProviderConfigRecord.id != config.id)):
            other.is_default = False
        config.is_default = True
    db.commit(); db.refresh(config)
    return provider_view(db, provider, config)

@app.post("/api/v1/models/providers/{code}/test", response_model=ProviderTestResult)
async def test_model_provider(code: str, payload: ProviderTestRequest, db: Session = Depends(get_db)):
    if not model_settings(db)["live_enabled"]:
        raise HTTPException(status_code=403, detail={"code": "LIVE_EXECUTION_DISABLED", "message": "真实模型执行默认关闭，当前不能测试供应商连接。"})
    code = provider_code(code)
    provider = db.scalar(select(ModelProviderRecord).where(ModelProviderRecord.code == code, ModelProviderRecord.enabled.is_(True)))
    if not provider:
        raise not_found("model provider")
    config = config_for(db, code)
    view = provider_view(db, provider, config)
    base_url = payload.api_base_url.strip().rstrip("/") if payload.api_base_url else view["base_url"]
    model_id = payload.default_model_id.strip() if payload.default_model_id is not None else view["default_model_id"]
    unsaved = bool(payload.api_key and payload.api_key.strip()) or base_url != view["base_url"] or model_id != view["default_model_id"]
    api_key = payload.api_key.strip() if payload.api_key and payload.api_key.strip() else None
    if not api_key and config:
        credential = credential_for(db, config)
        if credential:
            try: api_key = decrypt_secret(credential)
            except RuntimeError as exc: raise HTTPException(status_code=503, detail={"code": "CREDENTIAL_DECRYPTION_FAILED", "message": str(exc)}) from exc
    if not api_key and code == "openrouter":
        api_key = os.getenv("AGENTFLOW_LLM_API_KEY", "").strip() or None
    if not api_key:
        raise HTTPException(status_code=409, detail={"code": "MODEL_NOT_CONFIGURED", "message": "请先输入 API Key 并保存，或配置该供应商的后端凭据。"})
    try:
        base_url = safe_base_url(base_url, provider.protocol)
        result = await verify_provider(code, provider.protocol, base_url, api_key, model_id)
        status, message = "connected", result["message"]
    except (ValueError, RuntimeError) as exc:
        status, message = "connection_failed", str(exc)
        result = {"ok": False, "models_available": None}
    tested_at = utcnow()
    persisted = False
    if not unsaved and config:
        update_test_status(config, status, message)
        db.commit()
        persisted = True
    elif not unsaved and code == "openrouter" and config is None:
        config = ModelProviderConfigRecord(id=new_id("model_config"), scope_id="local", provider_id=provider.id,
            api_base_url=base_url, default_model_id=model_id, is_enabled=True, is_default=True,
            last_test_status=status, last_test_at=tested_at, last_test_message=message, config_version=1)
        db.add(config); db.commit(); persisted = True
    return {"ok": status == "connected", "status": status, "message": message, "tested_at": tested_at,
            "persisted": persisted, "models_available": result.get("models_available")}

@app.get("/api/v1/models/providers/{code}/models", response_model=list[ProviderModelItem])
async def list_provider_models(code: str, db: Session = Depends(get_db)):
    code = provider_code(code)
    provider = db.scalar(select(ModelProviderRecord).where(ModelProviderRecord.code == code, ModelProviderRecord.enabled.is_(True)))
    if not provider:
        raise not_found("model provider")
    config = config_for(db, code)
    view = provider_view(db, provider, config)
    api_key = None
    if config:
        credential = credential_for(db, config)
        if credential:
            try: api_key = decrypt_secret(credential)
            except RuntimeError as exc: raise HTTPException(status_code=503, detail={"code": "CREDENTIAL_DECRYPTION_FAILED", "message": str(exc)}) from exc
    if not api_key and code == "openrouter":
        api_key = os.getenv("AGENTFLOW_LLM_API_KEY", "").strip() or None
    if not api_key:
        raise HTTPException(status_code=409, detail={"code": "MODEL_NOT_CONFIGURED", "message": "尚未配置该供应商的 API Key；可以手动输入模型 ID。"})
    try:
        return await fetch_models(code, provider.protocol, view["base_url"], api_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail={"code": "MODEL_CATALOG_FAILED", "message": str(exc)}) from exc

@app.delete("/api/v1/models/providers/{code}/credential", response_model=ProviderCatalogItem)
def delete_model_provider_credential(code: str, db: Session = Depends(get_db)):
    code = provider_code(code)
    provider = db.scalar(select(ModelProviderRecord).where(ModelProviderRecord.code == code))
    config = config_for(db, code)
    if not provider or not config:
        raise not_found("model provider configuration")
    if code == "openrouter" and os.getenv("AGENTFLOW_LLM_API_KEY", "").strip():
        raise HTTPException(status_code=409, detail={"code": "ENV_MANAGED_CREDENTIAL", "message": "此凭据由后端环境变量管理；请在后端环境中移除，避免误删当前运行密钥。"})
    credential = credential_for(db, config)
    if credential:
        db.delete(credential)
    config.credential_id = None
    config.is_default = False
    update_test_status(config, "unconfigured", "凭据已删除。")
    db.commit()
    return provider_view(db, provider, config)

@app.post("/api/v1/models/test", response_model=ModelTestOut)
async def test_model_settings(db: Session = Depends(get_db)):
    if not model_settings(db)["live_enabled"]:
        raise HTTPException(status_code=403, detail={"code": "LIVE_EXECUTION_DISABLED", "message": "真实模型执行默认关闭。请在受信任的本地开发环境显式启用后再测试。"})
    if not model_settings(db)["configured"]:
        raise HTTPException(status_code=409, detail={"code": "MODEL_NOT_CONFIGURED", "message": "请先在后端环境变量中配置模型 API Key。"})
    try:
        result = await test_connection()
        config = db.scalar(select(ModelProviderConfigRecord).where(ModelProviderConfigRecord.scope_id == "local", ModelProviderConfigRecord.is_default.is_(True)))
        if config:
            update_test_status(config, "connected", f"真实连接成功：{result['model']}")
            db.commit()
        return result
    except RuntimeError as exc:
        config = db.scalar(select(ModelProviderConfigRecord).where(ModelProviderConfigRecord.scope_id == "local", ModelProviderConfigRecord.is_default.is_(True)))
        if config:
            update_test_status(config, "connection_failed", str(exc))
            db.commit()
        raise HTTPException(status_code=502, detail={"code": "MODEL_CONNECTION_FAILED", "message": str(exc)}) from exc

@app.get("/api/v1/workflows", response_model=list[WorkflowOut])
def list_workflows(db: Session = Depends(get_db)):
    records = list(db.scalars(select(WorkflowRecord).where(WorkflowRecord.is_archived.is_(False)).order_by(WorkflowRecord.updated_at.desc())))
    return [workflow_response(item) for item in records]

@app.post("/api/v1/workflows", response_model=WorkflowOut, status_code=201)
def create_workflow(payload: WorkflowCreate, db: Session = Depends(get_db)):
    workflow_id = new_id("workflow")
    nodes = [node.model_dump() for node in payload.nodes]
    edges = [edge.model_dump() for edge in payload.edges]
    snapshot = workflow_snapshot(workflow_id, payload.name, payload.description, 1, nodes, edges)
    has_default = db.scalar(select(func.count()).select_from(WorkflowRecord).where(WorkflowRecord.is_default.is_(True), WorkflowRecord.is_archived.is_(False))) or 0
    record = WorkflowRecord(id=workflow_id, name=payload.name, description=payload.description, version=1, is_default=not has_default,
                            nodes_json=json.dumps(nodes, ensure_ascii=False), edges_json=json.dumps(edges, ensure_ascii=False))
    db.add(record); db.add(WorkflowVersionRecord(workflow_id=workflow_id, version=1, snapshot_json=snapshot))
    db.commit(); db.refresh(record)
    return workflow_response(record)

@app.put("/api/v1/workflows/{workflow_id}/default", response_model=WorkflowOut)
def set_default_workflow(workflow_id: str, db: Session = Depends(get_db)):
    workflow = db.get(WorkflowRecord, workflow_id)
    if not workflow or workflow.is_archived: raise not_found("workflow")
    nodes, edges = json.loads(workflow.nodes_json), json.loads(workflow.edges_json)
    _, errors = validate_graph(nodes, edges)
    if errors:
        raise HTTPException(status_code=422, detail={"code": "WORKFLOW_INVALID", "message": "流程校验未通过，不能设为默认流程。", "errors": errors})
    if runtime_mode(db) == "live" and not any(node.get("type") == "llm" for node in nodes):
        raise HTTPException(status_code=422, detail={"code": "LLM_NODE_REQUIRED", "message": "真实环境的默认流程必须包含 LLM 节点。"})
    for item in db.scalars(select(WorkflowRecord).where(WorkflowRecord.is_archived.is_(False))):
        item.is_default = item.id == workflow_id
    db.commit(); db.refresh(workflow)
    return workflow_response(workflow)

@app.delete("/api/v1/workflows/{workflow_id}", status_code=204)
def archive_workflow(workflow_id: str, db: Session = Depends(get_db)):
    workflow = db.get(WorkflowRecord, workflow_id)
    if not workflow or workflow.is_archived: raise not_found("workflow")
    if workflow.is_default:
        raise HTTPException(status_code=409, detail={"code": "DEFAULT_WORKFLOW", "message": "默认流程不能移除；请先将其他流程设为默认。"})
    active_run = db.scalar(select(RunRecord.id).where(RunRecord.workflow_id == workflow_id, RunRecord.status.in_(["queued", "running"])).limit(1))
    if active_run:
        raise HTTPException(status_code=409, detail={"code": "WORKFLOW_ACTIVE", "message": "该流程仍有执行中的任务，完成后再移除。"})
    workflow.is_archived = True
    db.commit()

@app.get("/api/v1/workflows/{workflow_id}", response_model=WorkflowOut)
def get_workflow(workflow_id: str, db: Session = Depends(get_db)):
    record = db.get(WorkflowRecord, workflow_id)
    if not record or record.is_archived: raise not_found("workflow")
    return workflow_response(record)

@app.put("/api/v1/workflows/{workflow_id}", response_model=WorkflowOut)
def update_workflow(workflow_id: str, payload: WorkflowUpdate, db: Session = Depends(get_db)):
    record = db.get(WorkflowRecord, workflow_id)
    if not record or record.is_archived: raise not_found("workflow")
    nodes = [node.model_dump() for node in payload.nodes]
    edges = [edge.model_dump() for edge in payload.edges]
    next_version = record.version + 1
    snapshot = workflow_snapshot(workflow_id, payload.name, payload.description, next_version, nodes, edges)
    record.name = payload.name; record.description = payload.description; record.version = next_version
    record.nodes_json = json.dumps(nodes, ensure_ascii=False); record.edges_json = json.dumps(edges, ensure_ascii=False)
    db.add(WorkflowVersionRecord(workflow_id=workflow_id, version=next_version, snapshot_json=snapshot))
    db.commit(); db.refresh(record)
    return workflow_response(record)

@app.get("/api/v1/workflows/{workflow_id}/versions", response_model=list[WorkflowVersionOut])
def workflow_versions(workflow_id: str, db: Session = Depends(get_db)):
    if db.get(WorkflowRecord, workflow_id) is None: raise not_found("workflow")
    return list(db.scalars(select(WorkflowVersionRecord).where(WorkflowVersionRecord.workflow_id == workflow_id).order_by(WorkflowVersionRecord.version.desc())))

@app.post("/api/v1/workflows/{workflow_id}/validate", response_model=WorkflowValidationResult)
def validate_workflow(workflow_id: str, graph: WorkflowGraph, db: Session = Depends(get_db)):
    if db.get(WorkflowRecord, workflow_id) is None: raise not_found("workflow")
    nodes = [node.model_dump() for node in graph.nodes]
    edges = [edge.model_dump() for edge in graph.edges]
    order, errors = validate_graph(nodes, edges)
    return WorkflowValidationResult(valid=not errors, errors=errors, node_order=order, node_count=len(nodes), edge_count=len(edges))

@app.post("/api/v1/workflows/{workflow_id}/runs", response_model=RunOut, status_code=202)
async def run_workflow(workflow_id: str, payload: WorkflowRunCreate, db: Session = Depends(get_db)):
    workflow = db.get(WorkflowRecord, workflow_id)
    if not workflow or workflow.is_archived: raise not_found("workflow")
    execution_mode = require_global_mode(db, payload.mode)
    nodes, edges = json.loads(workflow.nodes_json), json.loads(workflow.edges_json)
    if execution_mode == "live":
        if not model_settings(db)["live_enabled"]:
            raise HTTPException(status_code=403, detail={"code": "LIVE_EXECUTION_DISABLED", "message": "真实模型执行当前已关闭；请先在受信任的本地开发环境中显式启用。"})
        if not model_settings(db)["configured"]:
            raise HTTPException(status_code=409, detail={"code": "MODEL_NOT_CONFIGURED", "message": "真实模式尚未配置模型凭据；不会回退到演示结果。"})
        if not any(node.get("type") == "llm" for node in nodes):
            raise HTTPException(status_code=422, detail={"code": "LLM_NODE_REQUIRED", "message": "真实模式流程至少需要一个 LLM 节点。"})
    _, errors = validate_graph(nodes, edges)
    if errors:
        raise HTTPException(status_code=422, detail={"code": "WORKFLOW_INVALID", "message": "流程校验未通过。", "errors": errors})
    task_id, run_id = new_id("task"), new_id("run")
    snapshot = workflow_snapshot(workflow.id, workflow.name, workflow.description, workflow.version, nodes, edges)
    task = TaskRecord(id=task_id, title=payload.title, description=payload.description, status="queued", mode=execution_mode, workflow=workflow.name)
    run = RunRecord(id=run_id, task_id=task_id, mode=execution_mode, status="queued", workflow=workflow.name, workflow_id=workflow.id,
                    workflow_version=workflow.version, workflow_snapshot=snapshot)
    run.task = task
    db.add_all([task, run]); db.commit(); db.refresh(run)
    schedule_demo_run(run_id)
    return run

@app.get("/api/v1/runs/{run_id}/nodes", response_model=list[NodeRunOut])
def run_nodes(run_id: str, db: Session = Depends(get_db)):
    if db.get(RunRecord, run_id) is None: raise not_found("run")
    return list(db.scalars(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id)))

@app.get("/api/v1/runs/{run_id}/events", response_model=list[RunEventOut])
def run_events(run_id: str, db: Session = Depends(get_db)):
    if db.get(RunRecord, run_id) is None: raise not_found("run")
    return list(db.scalars(select(RunEventRecord).where(RunEventRecord.run_id == run_id).order_by(RunEventRecord.created_at, RunEventRecord.id)))

@app.get("/api/v1/evaluations/datasets", response_model=list[EvaluationDatasetOut])
def list_evaluation_datasets(db: Session = Depends(get_db)):
    records = db.scalars(select(EvaluationDatasetRecord).order_by(EvaluationDatasetRecord.updated_at.desc()))
    return [{"id": item.id, "name": item.name, "description": item.description,
             "cases": json.loads(item.cases_json), "created_at": item.created_at, "updated_at": item.updated_at}
            for item in records]

@app.post("/api/v1/evaluations/datasets", response_model=EvaluationDatasetOut, status_code=201)
def create_evaluation_dataset(payload: EvaluationDatasetCreate, db: Session = Depends(get_db)):
    record = EvaluationDatasetRecord(id=new_id("eval_dataset"), name=payload.name, description=payload.description,
                                     cases_json=json.dumps([case.model_dump() for case in payload.cases], ensure_ascii=False))
    db.add(record); db.commit(); db.refresh(record)
    return {"id": record.id, "name": record.name, "description": record.description,
            "cases": json.loads(record.cases_json), "created_at": record.created_at, "updated_at": record.updated_at}

@app.get("/api/v1/evaluations", response_model=list[EvaluationRunOut])
def list_evaluations(db: Session = Depends(get_db)):
    records = db.scalars(select(EvaluationRunRecord).options(selectinload(EvaluationRunRecord.results)).order_by(EvaluationRunRecord.started_at.desc()))
    return [evaluation_response(item) for item in records]

@app.get("/api/v1/evaluations/{evaluation_id}", response_model=EvaluationRunOut)
def get_evaluation(evaluation_id: str, db: Session = Depends(get_db)):
    record = db.scalar(select(EvaluationRunRecord).options(selectinload(EvaluationRunRecord.results)).where(EvaluationRunRecord.id == evaluation_id))
    if not record:
        raise not_found("evaluation")
    return evaluation_response(record)

@app.post("/api/v1/evaluations/datasets/{dataset_id}/runs", response_model=EvaluationRunOut, status_code=202)
async def start_evaluation(dataset_id: str, payload: EvaluationStart, db: Session = Depends(get_db)):
    dataset = db.get(EvaluationDatasetRecord, dataset_id)
    if not dataset:
        raise not_found("evaluation dataset")
    workflow = db.get(WorkflowRecord, payload.workflow_id)
    if not workflow or workflow.is_archived:
        raise not_found("workflow")
    execution_mode = require_global_mode(db, payload.mode)
    nodes, edges = json.loads(workflow.nodes_json), json.loads(workflow.edges_json)
    _, errors = validate_graph(nodes, edges)
    if errors:
        raise HTTPException(status_code=422, detail={"code": "WORKFLOW_INVALID", "message": "流程校验未通过。", "errors": errors})
    if execution_mode == "live":
        if not model_settings(db)["live_enabled"]:
            raise HTTPException(status_code=403, detail={"code": "LIVE_EXECUTION_DISABLED", "message": "真实模型执行当前已关闭。"})
        if not model_settings(db)["configured"]:
            raise HTTPException(status_code=409, detail={"code": "MODEL_NOT_CONFIGURED", "message": "真实模式尚未配置模型凭据；不会回退到演示结果。"})
        if not any(node.get("type") == "llm" for node in nodes):
            raise HTTPException(status_code=422, detail={"code": "LLM_NODE_REQUIRED", "message": "真实模式评测的流程至少需要一个 LLM 节点。"})
    snapshot = workflow_snapshot(workflow.id, workflow.name, workflow.description, workflow.version, nodes, edges)
    cases = json.loads(dataset.cases_json)
    configured_model = model_settings(db)
    model_name = f"{configured_model['provider']} / {configured_model['model']}" if execution_mode == "live" else "安全沙盒执行器"
    evaluation = EvaluationRunRecord(id=new_id("evaluation"), dataset_id=dataset.id, dataset_name=dataset.name,
        workflow_id=workflow.id, workflow_name=workflow.name, workflow_version=workflow.version,
        workflow_snapshot=snapshot, mode=execution_mode, model_name=model_name, status="queued", case_count=len(cases))
    db.add(evaluation); db.flush()
    for index, case in enumerate(cases):
        db.add(EvaluationCaseResultRecord(id=new_id("eval_case"), evaluation_run_id=evaluation.id,
            case_index=index, title=case["title"], input_text=case["input"],
            expected_contains_json=json.dumps(case.get("expected_contains", []), ensure_ascii=False), status="queued"))
    db.commit(); db.refresh(evaluation)
    schedule_evaluation(evaluation.id)
    return evaluation_response(evaluation)

@app.get("/api/v1/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(timezone_offset_minutes: int = Query(0, ge=-840, le=840), db: Session = Depends(get_db)):
    mode = runtime_mode(db)
    now = datetime.now(timezone.utc)
    local_now = now - timedelta(minutes=timezone_offset_minutes)
    local_day = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = local_day + timedelta(minutes=timezone_offset_minutes)
    week_start = start - timedelta(days=6)
    date_modifier = f"{-timezone_offset_minutes} minutes"
    daily_rows = db.execute(select(func.date(TaskRecord.created_at, date_modifier), func.count()).where(
        TaskRecord.mode == mode, TaskRecord.origin == "task", TaskRecord.created_at >= week_start, TaskRecord.created_at <= now
    ).group_by(func.date(TaskRecord.created_at, date_modifier))).all()
    daily_counts = {day: count for day, count in daily_rows}
    weekly_counts = [(daily_counts.get((local_day.date() - timedelta(days=6 - offset)).isoformat(), 0)) for offset in range(7)]
    tasks = list(db.scalars(select(TaskRecord).where(TaskRecord.mode == mode, TaskRecord.origin == "task", TaskRecord.created_at >= start,
        TaskRecord.created_at <= now).order_by(TaskRecord.created_at.desc())))
    completed = [task for task in tasks if task.status in {"succeeded", "failed"}]
    durations = [task.duration_ms for task in completed if task.duration_ms is not None]
    recent = list(db.scalars(select(TaskRecord).where(TaskRecord.mode == mode, TaskRecord.origin == "task").order_by(TaskRecord.created_at.desc()).limit(8)))
    tokens = db.scalar(select(func.sum(RunRecord.tokens)).join(TaskRecord, RunRecord.task_id == TaskRecord.id).where(
        RunRecord.mode == mode, TaskRecord.origin == "task", RunRecord.created_at >= start, RunRecord.created_at <= now,
        RunRecord.tokens.is_not(None)))
    return DashboardSummary(mode=mode, today_tasks=len(tasks), success_rate=round(sum(task.status == "succeeded" for task in completed) / len(completed) * 100, 1) if completed else None,
        average_duration_ms=round(sum(durations) / len(durations)) if durations else None, tokens_today=int(tokens) if tokens is not None else None,
        recent_tasks=recent, weekly_task_counts=weekly_counts, source=mode)

@app.get("/api/v1/tasks", response_model=TaskPage)
def list_tasks(q: str = "", status: Literal["queued", "running", "succeeded", "failed", "cancelled"] | None = None,
               mode: Literal["demo", "live"] | None = "demo", page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100), db: Session = Depends(get_db)):
    stmt, count_stmt = select(TaskRecord).where(TaskRecord.origin == "task"), select(func.count()).select_from(TaskRecord).where(TaskRecord.origin == "task")
    if mode:
        stmt, count_stmt = stmt.where(TaskRecord.mode == mode), count_stmt.where(TaskRecord.mode == mode)
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt, count_stmt = stmt.where(TaskRecord.title.ilike(pattern)), count_stmt.where(TaskRecord.title.ilike(pattern))
    if status:
        stmt, count_stmt = stmt.where(TaskRecord.status == status), count_stmt.where(TaskRecord.status == status)
    items = list(db.scalars(stmt.order_by(TaskRecord.created_at.desc()).offset((page - 1) * page_size).limit(page_size)))
    return TaskPage(items=items, total=db.scalar(count_stmt) or 0, page=page, page_size=page_size)

@app.post("/api/v1/tasks", response_model=TaskOut, status_code=201)
async def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    execution_mode = require_global_mode(db, payload.mode)
    workflow = db.get(WorkflowRecord, payload.workflow_id) if payload.workflow_id else db.scalar(
        select(WorkflowRecord).where(WorkflowRecord.is_default.is_(True), WorkflowRecord.is_archived.is_(False)))
    if not workflow or workflow.is_archived:
        raise HTTPException(status_code=409, detail={"code": "DEFAULT_WORKFLOW_MISSING", "message": "请先在流程编排中设置一个可用的默认流程。"})
    nodes, edges = json.loads(workflow.nodes_json), json.loads(workflow.edges_json)
    _, errors = validate_graph(nodes, edges)
    if errors:
        raise HTTPException(status_code=422, detail={"code": "WORKFLOW_INVALID", "message": "默认流程校验未通过，请先修复流程。", "errors": errors})
    if execution_mode == "live":
        settings = model_settings(db)
        if not settings["live_enabled"]:
            raise HTTPException(status_code=403, detail={"code": "LIVE_EXECUTION_DISABLED", "message": "后端真实执行开关未启用。"})
        if not settings["configured"]:
            raise HTTPException(status_code=409, detail={"code": "MODEL_NOT_CONFIGURED", "message": "真实模式尚未配置模型凭据，不会回退到演示结果。"})
        if not any(node.get("type") == "llm" for node in nodes):
            raise HTTPException(status_code=422, detail={"code": "LLM_NODE_REQUIRED", "message": "真实环境的默认流程必须包含 LLM 节点。"})
    task_id, run_id = new_id("task"), new_id("run")
    snapshot = workflow_snapshot(workflow.id, workflow.name, workflow.description, workflow.version, nodes, edges)
    task = TaskRecord(id=task_id, title=payload.title, description=payload.description, status="queued", mode=execution_mode, workflow=workflow.name)
    run = RunRecord(id=run_id, task_id=task_id, mode=execution_mode, status="queued", workflow=workflow.name, workflow_id=workflow.id,
        workflow_version=workflow.version, workflow_snapshot=snapshot)
    db.add_all([task, run]); db.commit(); db.refresh(task)
    schedule_demo_run(run_id)
    return task

@app.get("/api/v1/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(TaskRecord, task_id)
    if task is None: raise not_found("task")
    return task

@app.patch("/api/v1/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: str, payload: TaskUpdate, db: Session = Depends(get_db)):
    task = db.get(TaskRecord, task_id)
    if task is None: raise not_found("task")
    if task.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail={"code": "TASK_LOCKED", "message": "任务执行期间不能编辑。"})
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    db.commit(); db.refresh(task); return task

@app.delete("/api/v1/tasks/{task_id}", status_code=204)
def delete_task(task_id: str, db: Session = Depends(get_db)):
    task = db.scalar(select(TaskRecord).options(selectinload(TaskRecord.runs)).where(TaskRecord.id == task_id))
    if task is None: raise not_found("task")
    if task.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail={"code": "TASK_ACTIVE", "message": "活动中的任务不能删除，请先取消或等待运行结束。"})
    db.delete(task); db.commit()

@app.post("/api/v1/tasks/{task_id}/cancel", response_model=TaskOut)
def cancel_task(task_id: str, db: Session = Depends(get_db)):
    task = db.scalar(select(TaskRecord).options(selectinload(TaskRecord.runs)).where(TaskRecord.id == task_id))
    if task is None: raise not_found("task")
    if task.status not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail={"code": "TASK_NOT_CANCELLABLE", "message": "只有活动中的任务可以取消。"})
    now = utcnow()
    task.status = "cancelled"
    for run in task.runs:
        if run.status in {"queued", "running"}:
            run.status = "cancelled"; run.finished_at = now; run.error_message = "用户取消了本次演示运行。"
            nodes = list(db.scalars(select(NodeRunRecord).where(NodeRunRecord.run_id == run.id, NodeRunRecord.status.in_(["queued", "running"]))))
            for node_run in nodes:
                node_run.status = "cancelled"; node_run.finished_at = now
                record_event(db, run.id, "node.cancelled", "cancelled", f"用户取消了节点：{node_run.label}", node_run.node_id)
            record_event(db, run.id, "run.cancelled", "cancelled", "用户取消了本次演示运行。")
    db.commit(); db.refresh(task); return task

@app.get("/api/v1/tasks/{task_id}/runs", response_model=list[RunOut])
def task_runs(task_id: str, db: Session = Depends(get_db)):
    if db.get(TaskRecord, task_id) is None: raise not_found("task")
    return list(db.scalars(select(RunRecord).where(RunRecord.task_id == task_id).order_by(RunRecord.created_at.desc())))

@app.get("/api/v1/runs", response_model=RunPage)
def list_runs(status: Literal["queued", "running", "succeeded", "failed", "cancelled"] | None = None,
              mode: Literal["demo", "live"] | None = "demo", page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100), db: Session = Depends(get_db)):
    stmt, count_stmt = select(RunRecord), select(func.count()).select_from(RunRecord)
    if mode:
        stmt, count_stmt = stmt.where(RunRecord.mode == mode), count_stmt.where(RunRecord.mode == mode)
    if status:
        stmt, count_stmt = stmt.where(RunRecord.status == status), count_stmt.where(RunRecord.status == status)
    items = list(db.scalars(stmt.order_by(RunRecord.created_at.desc()).offset((page - 1) * page_size).limit(page_size)))
    return RunPage(items=items, total=db.scalar(count_stmt) or 0, page=page, page_size=page_size)

@app.get("/api/v1/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(RunRecord, run_id)
    if run is None: raise not_found("run")
    return run
