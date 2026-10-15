<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MarkerType, VueFlow, type Connection, type Edge, type Node } from '@vue-flow/core'
import { Check, CirclePlus, Connection as WorkflowIcon, Delete as Trash2, DocumentChecked as Save, VideoPlay as Play, Star } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import WorkflowNodeCard from '../components/WorkflowNodeCard.vue'
import { createWorkflow, deleteWorkflow, getRun, getRunEvents, getRunNodes, getWorkflow, getWorkflows, runWorkflow, saveWorkflow, setDefaultWorkflow, validateWorkflow } from '../api/tasks'
import type { NodeRun, Run, RunEvent, Workflow, WorkflowEdge, WorkflowNode, WorkflowNodeType, WorkflowValidation } from '../types'
import { useRuntimeStore } from '../stores/runtime'
import { useUiStore } from '../stores/ui'

type CanvasData = { kind: WorkflowNodeType; label: string; config: Record<string, string | boolean>; status?: string }
type SelectedFlowNode = { id: string; data: CanvasData }
const workflows = ref<Workflow[]>([])
const workflowId = ref('')
const workflow = ref<Workflow | null>(null)
const name = ref('')
const description = ref('')
const nodes = shallowRef<Node[]>([])
const edges = shallowRef<Edge[]>([])
const selectedNodeId = ref('')
const loading = ref(true)
const saving = ref(false)
const validation = ref<WorkflowValidation | null>(null)
const currentRun = ref<Run | null>(null)
const nodeRuns = ref<NodeRun[]>([])
const runEvents = ref<RunEvent[]>([])
const runTitle = ref('')
const runDescription = ref('')
const runtime = useRuntimeStore()
const ui = useUiStore()
const runDialog = ref(false)
const nodePalette: { type: WorkflowNodeType; label: string; description: string }[] = [
  { type: 'input', label: '输入节点', description: '接收任务目标' },
  { type: 'llm', label: 'LLM 节点', description: '模型处理，可选真实调用' },
  { type: 'tool', label: '工具节点', description: '受控本地工具' },
  { type: 'output', label: '输出节点', description: '返回最终结果' },
]
let refreshTimer: number | undefined
let nodeSequence = 0
const viewport = ref({ x: 0, y: 0, zoom: 1 })

const selectedNode = computed<SelectedFlowNode | undefined>(() => {
  const node = nodes.value.find(item => item.id === selectedNodeId.value)
  return node ? { id: node.id, data: nodeData(node) } : undefined
})
const nodeData = (node: Node): CanvasData => node.data as CanvasData
const toWorkflowNodes = (): WorkflowNode[] => nodes.value.map(node => ({
  id: node.id,
  type: nodeData(node).kind,
  label: nodeData(node).label,
  position: { x: node.position.x, y: node.position.y },
  config: nodeData(node).config,
}))
const toWorkflowEdges = (): WorkflowEdge[] => edges.value.map(edge => ({
  id: edge.id,
  source: edge.source,
  target: edge.target,
  source_handle: edge.sourceHandle ?? null,
  target_handle: edge.targetHandle ?? null,
}))
const savedSignature = ref('')
const signature = computed(() => JSON.stringify({ name: name.value, description: description.value, nodes: toWorkflowNodes(), edges: toWorkflowEdges() }))
const dirty = computed(() => Boolean(workflow.value && signature.value !== savedSignature.value))
const statusLabel: Record<string, string> = { queued: '排队中', running: '执行中', succeeded: '已完成', failed: '失败', skipped: '已跳过' }
function apiErrorMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { error?: { message?: string }; detail?: string | { message?: string } } } })?.response?.data
  return response?.error?.message || (typeof response?.detail === 'string' ? response.detail : response?.detail?.message) || fallback
}

function mapWorkflow(record: Workflow) {
  workflow.value = record
  workflowId.value = record.id
  name.value = record.name
  description.value = record.description
  nodes.value = record.nodes.map(node => ({ id: node.id, type: 'agentNode', position: { ...node.position }, data: { kind: node.type, label: node.label, config: { ...node.config }, status: 'idle' } }))
  edges.value = record.edges.map(edge => ({ id: edge.id, source: edge.source, target: edge.target, sourceHandle: edge.source_handle ?? undefined, targetHandle: edge.target_handle ?? undefined, type: 'smoothstep', markerEnd: MarkerType.ArrowClosed }))
  selectedNodeId.value = ''
  validation.value = null
  savedSignature.value = signature.value
}

async function loadWorkflow(id?: string) {
  loading.value = true
  try {
    workflows.value = await getWorkflows()
    if (!workflows.value.length) { workflow.value = null; workflowId.value = ''; return }
    const targetId = id && workflows.value.some(item => item.id === id) ? id : workflow.value && workflows.value.some(item => item.id === workflow.value?.id) ? workflow.value.id : workflows.value.find(item => item.is_default)?.id || workflows.value[0].id
    const record = await getWorkflow(targetId)
    mapWorkflow(record)
  } catch { ElMessage.error('流程加载失败，请确认后端服务已启动') }
  finally { loading.value = false }
}

async function makeDefault() {
  if (!workflow.value || workflow.value.is_default) return
  try { const saved = await setDefaultWorkflow(workflow.value.id); workflows.value = workflows.value.map(item => ({ ...item, is_default: item.id === saved.id })); mapWorkflow(saved); ElMessage.success('已设为默认流程') }
  catch (error) { ElMessage.error(apiErrorMessage(error, '默认流程更新失败')) }
}

async function removeWorkflow() {
  if (!workflow.value || workflow.value.is_default) return
  try {
    await ElMessageBox.confirm(`移除流程“${workflow.value.name}”？历史运行记录会保留，流程将从可选列表中隐藏。`, '移除流程', { confirmButtonText: '移除流程', cancelButtonText: '取消', type: 'warning' })
    await deleteWorkflow(workflow.value.id)
    workflow.value = null
    await loadWorkflow()
    ElMessage.success('流程已从可选列表移除，历史运行快照仍保留。')
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(apiErrorMessage(error, '流程移除失败')) }
}

async function switchWorkflow(nextId: string) {
  if (!nextId || nextId === workflow.value?.id) return
  if (dirty.value) {
    try { await ElMessageBox.confirm('当前流程有未保存的修改，要放弃并切换吗？', '未保存修改', { confirmButtonText: '放弃修改', cancelButtonText: '留在当前流程', type: 'warning' }) }
    catch { workflowId.value = workflow.value?.id || ''; return }
  }
  await loadWorkflow(nextId)
}

async function createNewWorkflow() {
  try {
    const { value } = await ElMessageBox.prompt('为新流程填写名称。', '新建流程', { confirmButtonText: '创建', cancelButtonText: '取消', inputValue: '未命名流程', inputValidator: value => Boolean(value.trim()) || '流程名称不能为空。' })
    const nodes: WorkflowNode[] = [
      { id: `input_${Date.now()}`, type: 'input', label: '任务输入', position: { x: 100, y: 180 }, config: {} },
      { id: `output_${Date.now()}`, type: 'output', label: '最终输出', position: { x: 460, y: 180 }, config: {} },
    ]
    const edges: WorkflowEdge[] = [{ id: `edge_${Date.now()}`, source: nodes[0].id, target: nodes[1].id }]
    const record = await createWorkflow({ name: value.trim(), description: '', nodes, edges })
    await loadWorkflow(record.id)
    ElMessage.success('流程已创建')
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error('流程创建失败') }
}

function addNode(type: WorkflowNodeType, position?: { x: number; y: number }) {
  nodeSequence += 1
  const labels: Record<WorkflowNodeType, string> = { input: '任务输入', llm: '智能处理', tool: '文本摘要', output: '最终输出' }
  const config: CanvasData['config'] = type === 'llm' ? { prompt_template: '对输入目标进行结构化整理' } : type === 'tool' ? { tool_name: 'text_summary' } : {}
  const node: Node = { id: `${type}_${Date.now()}_${nodeSequence}`, type: 'agentNode', position: position || { x: 150 + (nodeSequence % 3) * 70, y: 100 + nodeSequence * 45 }, data: { kind: type, label: labels[type], config, status: 'idle' } }
  nodes.value = [...nodes.value, node]
  selectedNodeId.value = node.id
  validation.value = null
}

function startPaletteDrag(event: DragEvent, type: WorkflowNodeType) {
  event.dataTransfer?.setData('application/x-agentflow-node', type)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'copy'
}

function captureViewport(payload: { flowTransform: { x: number; y: number; zoom: number } }) {
  viewport.value = payload.flowTransform
}

function dropPaletteNode(event: DragEvent) {
  const type = event.dataTransfer?.getData('application/x-agentflow-node') as WorkflowNodeType | undefined
  if (!type || !nodePalette.some(item => item.type === type)) return
  const stage = event.currentTarget as HTMLElement
  const bounds = stage.getBoundingClientRect()
  const { x, y, zoom } = viewport.value
  addNode(type, { x: (event.clientX - bounds.left - x) / zoom, y: (event.clientY - bounds.top - y) / zoom })
}

function connect(connection: Connection) {
  if (!connection.source || !connection.target) return
  if (edges.value.some(edge => edge.source === connection.source && edge.target === connection.target)) return
  edges.value = [...edges.value, { id: `edge_${Date.now()}_${edges.value.length}`, source: connection.source, target: connection.target,
    sourceHandle: connection.sourceHandle || undefined, targetHandle: connection.targetHandle || undefined, type: 'smoothstep', markerEnd: MarkerType.ArrowClosed }]
  validation.value = null
}

function updateSelected(patch: Partial<CanvasData>) {
  if (!selectedNode.value) return
  nodes.value = nodes.value.map(node => node.id === selectedNodeId.value ? { ...node, data: { ...nodeData(node), ...patch } } : node)
}

function updateSelectedConfig(key: string, value: string | boolean) {
  if (!selectedNode.value) return
  updateSelected({ config: { ...selectedNode.value.data.config, [key]: value } })
}

function removeSelected() {
  if (!selectedNode.value) return
  const id = selectedNodeId.value
  nodes.value = nodes.value.filter(node => node.id !== id)
  edges.value = edges.value.filter(edge => edge.source !== id && edge.target !== id)
  selectedNodeId.value = ''
  validation.value = null
}

async function save(): Promise<boolean> {
  if (!workflow.value || !dirty.value) return true
  saving.value = true
  try {
    const saved = await saveWorkflow(workflow.value.id, { name: name.value.trim(), description: description.value, nodes: toWorkflowNodes(), edges: toWorkflowEdges() })
    workflows.value = workflows.value.map(item => item.id === saved.id ? saved : item)
    mapWorkflow(saved)
    ElMessage.success(`已保存为版本 ${saved.version}`)
    return true
  } catch { ElMessage.error('保存失败，请检查流程名称和节点数据') }
  finally { saving.value = false }
  return false
}

async function validate(): Promise<boolean> {
  if (!workflow.value) return false
  if (dirty.value && !(await save())) return false
  try {
    validation.value = await validateWorkflow(workflow.value.id, toWorkflowNodes(), toWorkflowEdges())
    if (validation.value.valid) ElMessage.success(`流程校验通过 · ${validation.value.node_count} 个节点`)
    else ElMessage.warning(validation.value.errors[0] || '流程校验未通过')
    return validation.value.valid
  } catch { ElMessage.error('流程校验请求失败'); return false }
}

async function requestRun() {
  if (!workflow.value) return
  if (!(await validate())) return
  runTitle.value = ''
  runDescription.value = ''
  runDialog.value = true
}

async function startRun() {
  if (!workflow.value || !runTitle.value.trim()) return
  try {
    if (dirty.value && !(await save())) return
    currentRun.value = await runWorkflow(workflow.value.id, { title: runTitle.value.trim(), description: runDescription.value, mode: runtime.mode })
    runDialog.value = false
    await loadRunProgress()
    if (currentRun.value.status === 'queued' || currentRun.value.status === 'running') refreshTimer = window.setInterval(loadRunProgress, 450)
    ElMessage.success(`${runtime.modeLabel}运行已启动`)
  } catch (error) { ElMessage.error(apiErrorMessage(error, '启动请求失败，请检查后端服务和运行日志。')) }
}

async function loadRunProgress() {
  if (!currentRun.value) return
  try {
    const [run, rows, events] = await Promise.all([getRun(currentRun.value.id), getRunNodes(currentRun.value.id), getRunEvents(currentRun.value.id)])
    currentRun.value = run
    nodeRuns.value = rows
    runEvents.value = events
    const byNode = new Map(rows.map(row => [row.node_id, row.status === 'succeeded' ? 'success' : row.status]))
    nodes.value = nodes.value.map(node => ({ ...node, data: { ...nodeData(node), status: byNode.get(node.id) || 'idle' } }))
    const completedNodes = new Set(rows.filter(row => row.status === 'succeeded').map(row => row.node_id))
    const runningNodes = new Set(rows.filter(row => row.status === 'running').map(row => row.node_id))
    edges.value = edges.value.map(edge => ({ ...edge, animated: ui.ambientMotion && completedNodes.has(edge.source) && runningNodes.has(edge.target) }))
    if (!['queued', 'running'].includes(run.status) && refreshTimer) { window.clearInterval(refreshTimer); refreshTimer = undefined }
  } catch (error) { if (refreshTimer) window.clearInterval(refreshTimer); ElMessage.error(apiErrorMessage(error, '读取运行状态失败，请稍后刷新运行记录。')) }
}

function selectNode(event: { node: Node }) { selectedNodeId.value = event.node.id }
function handleNodesChange() { validation.value = null }
onMounted(() => loadWorkflow())
onBeforeUnmount(() => { if (refreshTimer) window.clearInterval(refreshTimer) })
</script>

<template>
  <div class="workflow-page">
    <div class="workflow-header">
      <div class="workflow-title-group"><div class="workflow-title-mark"><el-icon><WorkflowIcon /></el-icon></div><div><div class="eyebrow">VISUAL WORKFLOW BUILDER</div><h1>流程编排</h1></div></div>
      <div class="workflow-toolbar">
        <el-select v-model="workflowId" class="workflow-picker" placeholder="选择流程" @change="switchWorkflow"><el-option v-for="item in workflows" :key="item.id" :label="item.name" :value="item.id" /></el-select>
        <span v-if="workflow" class="version-chip">v{{ workflow.version }}<i v-if="dirty"></i></span>
        <el-tag v-if="workflow?.is_default" size="small" effect="plain" type="warning">默认流程</el-tag>
        <el-button v-if="workflow && !workflow.is_default" @click="makeDefault"><el-icon><Star /></el-icon>设为默认</el-button>
        <el-button v-if="workflow && !workflow.is_default" plain type="danger" @click="removeWorkflow"><el-icon><Trash2 /></el-icon>移除</el-button>
        <el-button @click="createNewWorkflow"><el-icon><CirclePlus /></el-icon>新建流程</el-button>
        <el-button :disabled="!dirty" :loading="saving" @click="save"><el-icon><Save /></el-icon>保存</el-button>
        <el-button @click="validate"><el-icon><Check /></el-icon>校验</el-button>
        <el-button type="primary" @click="requestRun"><el-icon><Play /></el-icon>运行</el-button>
      </div>
    </div>
    <div v-if="workflow" class="workflow-subhead"><el-input v-model="name" class="workflow-name-input" maxlength="120" aria-label="流程名称"/><el-input v-model="description" class="workflow-description-input" maxlength="1000" placeholder="添加流程说明…" aria-label="流程说明"/><span class="workflow-mode-label" :class="runtime.mode"><i></i>{{ runtime.modeLabel }} · 新运行采用全局环境</span></div>
    <section v-if="!loading && !workflow" class="panel workflow-empty-state"><el-empty description="还没有流程，请创建一个流程后开始编排。"><el-button type="primary" @click="createNewWorkflow"><el-icon><CirclePlus /></el-icon>创建第一个流程</el-button></el-empty></section>
    <div v-loading="loading" class="workflow-editor-shell">
      <aside class="node-library">
        <div class="editor-section-title">节点组件</div><p class="editor-help">拖拽或点击节点添加至画布，再通过连接点连线。</p>
        <button v-for="item in nodePalette" :key="item.type" class="library-node" draggable="true" @dragstart="startPaletteDrag($event, item.type)" @click="addNode(item.type)"><span :class="`library-symbol ${item.type}`">{{ item.type === 'input' ? 'IN' : item.type === 'llm' ? 'AI' : item.type === 'tool' ? 'FX' : 'OUT' }}</span><span><strong>{{ item.label }}</strong><small>{{ item.description }}</small></span><el-icon class="library-add"><CirclePlus /></el-icon></button>
        <div class="library-note"><strong>{{ runtime.modeLabel }}</strong><p>{{ runtime.mode === 'demo' ? '安全沙盒只使用本地执行器，不会请求真实模型。' : '真实环境会调用已配置模型；工具仍受服务端白名单约束。' }}</p></div>
      </aside>
      <section class="canvas-region">
        <div class="canvas-topline"><span><i></i>画布</span><span>{{ nodes.length }} 个节点 · {{ edges.length }} 条连线</span></div>
        <div class="vue-flow-stage" @dragover.prevent @drop.prevent="dropPaletteNode">
          <VueFlow v-model:nodes="nodes" v-model:edges="edges" :node-types="{ agentNode: WorkflowNodeCard }" fit-view-on-init :min-zoom="0.25" :max-zoom="1.7" :default-edge-options="{ type: 'smoothstep', markerEnd: MarkerType.ArrowClosed }" @connect="connect" @node-click="selectNode" @nodes-change="handleNodesChange" @edges-change="handleNodesChange" @pane-click="selectedNodeId = ''" @move="captureViewport">
            <Background pattern-color="#cbd2e1" :gap="18" /><Controls position="bottom-left" />
          </VueFlow>
          <div v-if="!nodes.length" class="canvas-empty"><strong>从左侧添加节点开始搭建</strong><span>可添加多个输入、LLM、工具和输出节点，并连接成 DAG。</span></div>
        </div>
        <div class="validation-bar" :class="validation?.valid ? 'valid' : validation ? 'invalid' : ''"><template v-if="validation"><span class="validation-mark">{{ validation.valid ? '✓' : '!' }}</span><span>{{ validation.valid ? `结构校验通过 · 执行顺序：${validation.node_order.join(' → ')}` : validation.errors.join(' ') }}</span></template><template v-else><span class="validation-mark idle">i</span><span>保存后可校验结构；运行前会自动校验有向无环关系与节点连接。</span></template></div>
      </section>
      <aside class="node-inspector">
        <template v-if="selectedNode"><div class="inspector-heading"><div><div class="editor-section-title">节点配置</div><p>{{ selectedNode.data.kind }} 节点 · {{ selectedNode.id }}</p></div><el-button text circle type="danger" aria-label="删除节点" @click="removeSelected"><el-icon><Trash2 /></el-icon></el-button></div>
          <el-form label-position="top" class="inspector-form"><el-form-item label="节点名称"><el-input :model-value="selectedNode.data.label" maxlength="120" @update:model-value="(value: string) => updateSelected({ label: value })"/></el-form-item>
            <el-form-item v-if="selectedNode.data.kind === 'llm'" label="模型处理要求"><el-input :model-value="String(selectedNode.data.config.prompt_template || '')" type="textarea" :rows="4" @update:model-value="(value: string) => updateSelectedConfig('prompt_template', value)"/><div class="form-hint">真实环境会作为模型指令；安全沙盒仅使用本地演示输出。</div></el-form-item>
            <el-form-item v-if="selectedNode.data.kind === 'tool'" label="白名单工具"><el-select :model-value="String(selectedNode.data.config.tool_name || 'text_summary')" @update:model-value="(value: string) => updateSelectedConfig('tool_name', value)"><el-option label="文本摘要 · text_summary" value="text_summary"/><el-option label="JSON 校验 · json_validate" value="json_validate"/></el-select><div class="form-hint">工具执行限制在本地白名单内。</div></el-form-item>
            <el-form-item v-if="selectedNode.data.kind === 'llm' || selectedNode.data.kind === 'tool'" label="失败演示"><el-switch :model-value="Boolean(selectedNode.data.config.simulate_failure)" active-text="执行时模拟失败" @update:model-value="(value: boolean) => updateSelectedConfig('simulate_failure', value)"/></el-form-item>
            <div v-if="selectedNode.data.kind === 'input' || selectedNode.data.kind === 'output'" class="inspector-note">{{ selectedNode.data.kind === 'input' ? '此节点接收提交任务中的目标与补充说明。' : '此节点汇总上游结果作为本次运行输出。' }}</div>
          </el-form>
        </template>
        <div v-else class="inspector-empty"><div class="inspector-empty-icon">⌖</div><strong>选择一个节点</strong><span>查看并修改节点参数。</span></div>
      </aside>
    </div>
    <section v-if="currentRun" class="panel workflow-run-panel"><div class="run-panel-heading"><div><h2>最近运行</h2><p>{{ currentRun.task_title }} · {{ currentRun.id }}</p></div><el-tag :type="currentRun.status === 'failed' ? 'danger' : currentRun.status === 'succeeded' ? 'success' : 'info'">{{ statusLabel[currentRun.status] || currentRun.status }}</el-tag></div><div class="run-node-strip"><div v-for="node in nodeRuns" :key="node.id" class="run-node-chip" :class="node.status"><span>{{ node.status === 'succeeded' ? '✓' : node.status === 'failed' ? '!' : node.status === 'running' ? '…' : '·' }}</span>{{ node.label }}</div></div><div class="event-log"><div v-for="event in runEvents.slice(-8)" :key="event.id" class="event-log-row"><span>{{ new Date(event.created_at).toLocaleTimeString('zh-CN') }}</span><strong>{{ event.event }}</strong><span>{{ event.message }}</span></div></div><div v-if="currentRun.output_text" class="workflow-output"><strong>最终输出</strong><p>{{ currentRun.output_text }}</p></div><div v-if="currentRun.error_message" class="run-error">{{ currentRun.error_message }}</div></section>

    <el-dialog v-model="runDialog" title="运行工作流" width="520px"><p class="dialog-copy">本次执行将使用全局环境：<strong>{{ runtime.modeLabel }}</strong>。真实环境会调用已配置模型并可能产生费用。</p><el-form label-position="top"><el-form-item label="任务目标"><el-input v-model="runTitle" maxlength="500" placeholder="例如：整理本周客户反馈"/></el-form-item><el-form-item label="任务输入与补充说明"><el-input v-model="runDescription" type="textarea" :rows="5" maxlength="5000" placeholder="在这里填写完整业务材料、输入数据、输出要求和限制条件"/></el-form-item></el-form><template #footer><el-button @click="runDialog = false">取消</el-button><el-button type="primary" :disabled="!runTitle.trim()" @click="startRun">创建运行</el-button></template></el-dialog>
  </div>
</template>

<style scoped>
.workflow-empty-state{min-height:280px;display:grid;place-items:center}.workflow-mode-label.live i{background:var(--danger)}
</style>
