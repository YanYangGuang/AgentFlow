export type TaskStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export interface Task { id: string; title: string; description: string; status: TaskStatus; mode: 'demo' | 'live'; workflow: string; created_at: string; duration_ms?: number; tokens?: number }
export interface Run { id: string; task_id: string; task_title: string; mode: 'demo' | 'live'; status: TaskStatus; workflow: string; workflow_version: number; workflow_snapshot: string; created_at: string; started_at?: string | null; finished_at?: string | null; duration_ms?: number | null; tokens?: number | null; estimated_cost?: number | null; output_text?: string | null; error_message?: string | null }
export type WorkflowNodeType = 'input' | 'llm' | 'tool' | 'output'
export interface WorkflowNode { id: string; type: WorkflowNodeType; label: string; position: { x: number; y: number }; config: Record<string, string | boolean> }
export interface WorkflowEdge { id: string; source: string; target: string; source_handle?: string | null; target_handle?: string | null }
export interface Workflow { id: string; name: string; description: string; version: number; is_default: boolean; is_archived: boolean; nodes: WorkflowNode[]; edges: WorkflowEdge[]; created_at: string; updated_at: string }
export interface WorkflowValidation { valid: boolean; errors: string[]; node_order: string[]; node_count: number; edge_count: number }
export interface NodeRun { id: string; run_id: string; node_id: string; node_type: WorkflowNodeType; label: string; status: string; input_json: string; output_json?: string | null; error_message?: string | null; started_at?: string | null; finished_at?: string | null; duration_ms?: number | null }
export interface RunEvent { id: string; run_id: string; node_id?: string | null; event: string; status: string; message: string; data_json: string; created_at: string }
export interface PageResult<T> { items: T[]; total: number; page: number; page_size: number }
export interface DashboardSummary { mode: 'demo' | 'live'; today_tasks: number; success_rate: number | null; average_duration_ms: number | null; tokens_today: number | null; recent_tasks: Task[]; weekly_task_counts: number[]; source: 'demo' | 'live' }
export interface RuntimeState { mode: 'demo' | 'live'; live_execution_enabled: boolean; model_configured: boolean; provider: string; model: string }
export interface ModelSettings { provider: string; base_url: string; model: string; configured: boolean; live_enabled: boolean; key_hint: string }
export type ProviderTestStatus = 'unconfigured' | 'not_tested' | 'testing' | 'connected' | 'connection_failed'
export interface ModelProvider {
  code: string; name: string; default_base_url: string; protocol: string; enabled: boolean; configured: boolean; credential_saved: boolean
  base_url: string; default_model_id: string; key_hint: string; last_test_status: ProviderTestStatus
  last_test_at: string | null; last_test_message: string; is_default: boolean; config_version: number
  updated_at: string | null; live_enabled: boolean
}
export interface ProviderModel { id: string; name: string; context_length: number | null; source: string }
export interface ProviderTestResult { ok: boolean; status: 'connected' | 'connection_failed'; message: string; tested_at: string; persisted: boolean; models_available: number | null }
export interface EvaluationCase { title: string; input: string; expected_contains: string[] }
export interface EvaluationDataset { id: string; name: string; description: string; cases: EvaluationCase[]; created_at: string; updated_at: string }
export interface EvaluationCaseResult { id: string; case_index: number; title: string; input_text: string; expected_contains: string[]; run_id: string | null; status: string; passed: boolean | null; output_text: string | null; error_message: string | null; duration_ms: number | null }
export interface EvaluationRun { id: string; dataset_id: string; dataset_name: string; workflow_id: string; workflow_name: string; workflow_version: number; mode: string; model_name: string; status: string; case_count: number; passed_count: number; score: number | null; started_at: string | null; finished_at: string | null; error_message: string | null; results: EvaluationCaseResult[] }
