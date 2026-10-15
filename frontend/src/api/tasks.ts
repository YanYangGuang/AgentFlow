import { api } from './client'
import type { DashboardSummary, EvaluationDataset, EvaluationRun, ModelProvider, ModelSettings, NodeRun, PageResult, ProviderModel, ProviderTestResult, Run, RunEvent, RuntimeState, Task, Workflow, WorkflowEdge, WorkflowNode, WorkflowValidation } from '../types'
export async function getSummary(timezoneOffsetMinutes = new Date().getTimezoneOffset()) { return (await api.get<DashboardSummary>('/dashboard/summary', { params: { timezone_offset_minutes: timezoneOffsetMinutes } })).data }
export async function getRuntimeState() { return (await api.get<RuntimeState>('/system/runtime')).data }
export async function setRuntimeMode(mode: 'demo' | 'live') { return (await api.put<RuntimeState>('/system/runtime/mode', { mode })).data }
export async function getHealth() { return (await api.get<{ status: string; database: string; mode: string }>('/health')).data }
export async function getModelSettings() { return (await api.get<ModelSettings>('/models')).data }
export async function testModelSettings() { return (await api.post<{ ok: boolean; model: string; tokens: number | null }>('/models/test')).data }
export async function getModelProviders() { return (await api.get<ModelProvider[]>('/models/providers')).data }
export async function saveModelProvider(code: string, payload: { api_base_url: string; default_model_id: string; api_key?: string; is_enabled?: boolean }) { return (await api.put<ModelProvider>(`/models/providers/${encodeURIComponent(code)}`, payload)).data }
export async function testModelProvider(code: string, payload: { api_base_url?: string; default_model_id?: string; api_key?: string }) { return (await api.post<ProviderTestResult>(`/models/providers/${encodeURIComponent(code)}/test`, payload)).data }
export async function getProviderModels(code: string) { return (await api.get<ProviderModel[]>(`/models/providers/${encodeURIComponent(code)}/models`)).data }
export async function deleteProviderCredential(code: string) { return (await api.delete<ModelProvider>(`/models/providers/${encodeURIComponent(code)}/credential`)).data }
export async function getTasks(params: { q?: string; status?: string; mode?: string; page?: number; page_size?: number } = {}) { return (await api.get<PageResult<Task>>('/tasks', { params })).data }
export async function createTask(payload: { title: string; description?: string; mode: 'demo' | 'live' }) { return (await api.post<Task>('/tasks', payload)).data }
export async function cancelTask(id: string) { return (await api.post<Task>(`/tasks/${id}/cancel`)).data }
export async function updateTask(id: string, payload: { title?: string; description?: string }) { return (await api.patch<Task>(`/tasks/${id}`, payload)).data }
export async function deleteTask(id: string) { await api.delete(`/tasks/${id}`) }
export async function getTaskRuns(id: string) { return (await api.get<Run[]>(`/tasks/${id}/runs`)).data }
export async function getRuns(params: { status?: string; mode?: string; page?: number; page_size?: number } = {}) { return (await api.get<PageResult<Run>>('/runs', { params })).data }
export async function getWorkflows() { return (await api.get<Workflow[]>('/workflows')).data }
export async function getWorkflow(id: string) { return (await api.get<Workflow>(`/workflows/${id}`)).data }
export async function saveWorkflow(id: string, payload: Pick<Workflow, 'name' | 'description' | 'nodes' | 'edges'>) { return (await api.put<Workflow>(`/workflows/${id}`, payload)).data }
export async function validateWorkflow(id: string, nodes: WorkflowNode[], edges: WorkflowEdge[]) { return (await api.post<WorkflowValidation>(`/workflows/${id}/validate`, { nodes, edges })).data }
export async function runWorkflow(id: string, payload: { title: string; description?: string; mode: 'demo' | 'live' }) { return (await api.post<Run>(`/workflows/${id}/runs`, payload)).data }
export async function getRunNodes(id: string) { return (await api.get<NodeRun[]>(`/runs/${id}/nodes`)).data }
export async function getRunEvents(id: string) { return (await api.get<RunEvent[]>(`/runs/${id}/events`)).data }
export async function getRun(id: string) { return (await api.get<Run>(`/runs/${id}`)).data }
export async function createWorkflow(payload: Pick<Workflow, 'name' | 'description' | 'nodes' | 'edges'>) { return (await api.post<Workflow>('/workflows', payload)).data }
export async function setDefaultWorkflow(id: string) { return (await api.put<Workflow>(`/workflows/${encodeURIComponent(id)}/default`)).data }
export async function deleteWorkflow(id: string) { await api.delete(`/workflows/${encodeURIComponent(id)}`) }
export async function getEvaluationDatasets() { return (await api.get<EvaluationDataset[]>('/evaluations/datasets')).data }
export async function createEvaluationDataset(payload: Pick<EvaluationDataset, 'name' | 'description' | 'cases'>) { return (await api.post<EvaluationDataset>('/evaluations/datasets', payload)).data }
export async function getEvaluations() { return (await api.get<EvaluationRun[]>('/evaluations')).data }
export async function startEvaluation(datasetId: string, workflowId: string, mode: 'demo' | 'live') { return (await api.post<EvaluationRun>(`/evaluations/datasets/${encodeURIComponent(datasetId)}/runs`, { workflow_id: workflowId, mode })).data }
