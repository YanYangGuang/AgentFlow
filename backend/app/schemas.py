from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

TaskState = Literal["queued", "running", "succeeded", "failed", "cancelled"]
RunState = Literal["queued", "running", "succeeded", "failed", "cancelled"]

class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    mode: Literal["demo", "live"] | None = None
    workflow_id: str | None = None

    @field_validator("title")
    @classmethod
    def title_must_have_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("任务目标不能为空。")
        return value

class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("title")
    @classmethod
    def update_title_must_have_content(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("任务目标不能为空。")
        return value

    @model_validator(mode="after")
    def require_update_fields(self):
        if not self.model_fields_set:
            raise ValueError("请至少提供一个需要更新的字段。")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("更新字段不能为 null。")
        return self

class TaskOut(BaseModel):
    id: str
    title: str
    description: str
    status: str
    mode: str
    workflow: str
    created_at: datetime
    duration_ms: int | None = None
    tokens: int | None = None
    model_config = {"from_attributes": True}

class TaskPage(BaseModel):
    items: list[TaskOut]
    total: int
    page: int
    page_size: int

class RunOut(BaseModel):
    id: str
    task_id: str
    task_title: str
    mode: str
    status: str
    workflow: str
    workflow_id: str | None = None
    workflow_version: int
    workflow_snapshot: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    tokens: int | None = None
    estimated_cost: float | None = None
    output_text: str | None = None
    error_message: str | None = None
    model_config = {"from_attributes": True}

class RunPage(BaseModel):
    items: list[RunOut]
    total: int
    page: int
    page_size: int

class NodePosition(BaseModel):
    x: float
    y: float

class WorkflowNode(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    type: Literal["input", "llm", "tool", "output"]
    label: str = Field(min_length=1, max_length=120)
    position: NodePosition
    config: dict[str, Any] = Field(default_factory=dict)

class WorkflowEdge(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)
    source_handle: str | None = None
    target_handle: str | None = None

class WorkflowGraph(BaseModel):
    nodes: list[WorkflowNode] = Field(max_length=100)
    edges: list[WorkflowEdge] = Field(max_length=300)

class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    nodes: list[WorkflowNode] = Field(default_factory=list, max_length=100)
    edges: list[WorkflowEdge] = Field(default_factory=list, max_length=300)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("流程名称不能为空。")
        return value

class WorkflowUpdate(WorkflowCreate):
    pass

class WorkflowOut(BaseModel):
    id: str
    name: str
    description: str
    version: int
    is_default: bool = False
    is_archived: bool = False
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    created_at: datetime
    updated_at: datetime

class WorkflowVersionOut(BaseModel):
    workflow_id: str
    version: int
    snapshot_json: str
    created_at: datetime
    model_config = {"from_attributes": True}

class WorkflowRunCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    mode: Literal["demo", "live"] | None = None

    @field_validator("title")
    @classmethod
    def clean_task_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("任务目标不能为空。")
        return value

class ModelSettingsOut(BaseModel):
    provider: str
    base_url: str
    model: str
    configured: bool
    live_enabled: bool
    key_hint: str

class ModelTestOut(BaseModel):
    ok: bool
    model: str
    tokens: int | None = None

class ProviderConfigUpdate(BaseModel):
    api_base_url: str = Field(max_length=500)
    default_model_id: str = Field(default="", max_length=240)
    api_key: str | None = Field(default=None, max_length=4096)
    is_enabled: bool = True

class ProviderTestRequest(BaseModel):
    api_base_url: str | None = Field(default=None, max_length=500)
    default_model_id: str | None = Field(default=None, max_length=240)
    api_key: str | None = Field(default=None, max_length=4096)

class ProviderCatalogItem(BaseModel):
    code: str
    name: str
    default_base_url: str
    protocol: str
    enabled: bool
    configured: bool
    credential_saved: bool
    base_url: str
    default_model_id: str
    key_hint: str
    last_test_status: str
    last_test_at: datetime | None = None
    last_test_message: str
    is_default: bool
    config_version: int
    updated_at: datetime | None = None
    live_enabled: bool

class ProviderTestResult(BaseModel):
    ok: bool
    status: Literal["connected", "connection_failed"]
    message: str
    tested_at: datetime
    persisted: bool
    models_available: int | None = None

class ProviderModelItem(BaseModel):
    id: str
    name: str
    context_length: int | None = None
    source: str = "provider"

class WorkflowValidationResult(BaseModel):
    valid: bool
    errors: list[str]
    node_order: list[str]
    node_count: int
    edge_count: int

class NodeRunOut(BaseModel):
    id: str
    run_id: str
    node_id: str
    node_type: str
    label: str
    status: str
    input_json: str
    output_json: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    model_config = {"from_attributes": True}

class RunEventOut(BaseModel):
    id: str
    run_id: str
    node_id: str | None = None
    event: str
    status: str
    message: str
    data_json: str
    created_at: datetime
    model_config = {"from_attributes": True}

class DashboardSummary(BaseModel):
    mode: Literal["demo", "live"]
    today_tasks: int
    success_rate: float | None
    average_duration_ms: int | None
    tokens_today: int | None
    recent_tasks: list[TaskOut]
    weekly_task_counts: list[int]
    source: Literal["demo", "live"]


class RuntimeModeUpdate(BaseModel):
    mode: Literal["demo", "live"]


class RuntimeModeOut(BaseModel):
    mode: Literal["demo", "live"]
    live_execution_enabled: bool
    model_configured: bool
    provider: str
    model: str


class EvaluationCaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    input: str = Field(min_length=1, max_length=5000)
    expected_contains: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("title", "input")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("评测用例标题和输入内容不能为空。")
        return value


class EvaluationDatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    cases: list[EvaluationCaseCreate] = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_dataset_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("评测集名称不能为空。")
        return value


class EvaluationDatasetOut(BaseModel):
    id: str
    name: str
    description: str
    cases: list[EvaluationCaseCreate]
    created_at: datetime
    updated_at: datetime


class EvaluationStart(BaseModel):
    workflow_id: str
    mode: Literal["demo", "live"] | None = None


class EvaluationCaseResultOut(BaseModel):
    id: str
    case_index: int
    title: str
    input_text: str
    expected_contains: list[str]
    run_id: str | None = None
    status: str
    passed: bool | None = None
    output_text: str | None = None
    error_message: str | None = None
    duration_ms: int | None = None


class EvaluationRunOut(BaseModel):
    id: str
    dataset_id: str
    dataset_name: str
    workflow_id: str
    workflow_name: str
    workflow_version: int
    mode: str
    model_name: str
    status: str
    case_count: int
    passed_count: int
    score: float | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    results: list[EvaluationCaseResultOut] = Field(default_factory=list)
