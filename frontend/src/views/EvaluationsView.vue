<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleClose, Plus, Refresh, VideoPlay } from '@element-plus/icons-vue'
import { createEvaluationDataset, getEvaluations, getEvaluationDatasets, getWorkflows, startEvaluation } from '../api/tasks'
import type { EvaluationDataset, EvaluationRun, Workflow } from '../types'
import { useRuntimeStore } from '../stores/runtime'

const datasets = ref<EvaluationDataset[]>([])
const runs = ref<EvaluationRun[]>([])
const workflows = ref<Workflow[]>([])
const runtime = useRuntimeStore()
const loading = ref(false)
const createOpen = ref(false)
const detailOpen = ref(false)
const selectedRun = ref<EvaluationRun | null>(null)
const selectedDataset = ref('')
const selectedWorkflow = ref('')
const form = ref({ name: '', description: '', cases: [{ title: '', input: '', expected: '' }] })
const completedRuns = computed(() => runs.value.filter(item => item.status === 'completed'))
const averageScore = computed(() => completedRuns.value.length ? completedRuns.value.reduce((sum, item) => sum + (item.score || 0), 0) / completedRuns.value.length : null)
const comparisons = computed(() => {
  const groups = new Map<string, { dataset: string; model: string; mode: string; count: number; score: number }>()
  for (const item of completedRuns.value) {
    if (item.score == null) continue
    const key = `${item.dataset_id}|${item.model_name}|${item.mode}`
    const current = groups.get(key) || { dataset: item.dataset_name, model: item.model_name, mode: item.mode, count: 0, score: 0 }
    current.count += 1; current.score += item.score; groups.set(key, current)
  }
  return [...groups.values()].map(item => ({ ...item, score: item.score / item.count })).sort((a, b) => a.dataset.localeCompare(b.dataset) || b.score - a.score)
})
let timer: number | undefined
const statusLabel = (status: string) => ({ queued: '排队中', running: '评测中', completed: '已完成', failed: '失败' }[status] || status)

async function load() {
  loading.value = true
  try {
    const [data, history, flowList] = await Promise.all([getEvaluationDatasets(), getEvaluations(), getWorkflows()])
    datasets.value = data; runs.value = history; workflows.value = flowList
    if (detailOpen.value && selectedRun.value) selectedRun.value = history.find(item => item.id === selectedRun.value?.id) || selectedRun.value
    await runtime.load()
    if (!selectedDataset.value && data.length) selectedDataset.value = data[0].id
    if (!selectedWorkflow.value && flowList.length) selectedWorkflow.value = flowList[0].id
  } catch { ElMessage.error('评测数据加载失败，请确认后端服务可用。') }
  finally { loading.value = false }
}
function addCase() { form.value.cases.push({ title: '', input: '', expected: '' }) }
function removeCase(index: number) { if (form.value.cases.length > 1) form.value.cases.splice(index, 1) }
async function saveDataset() {
  if (!form.value.name.trim() || form.value.cases.some(item => !item.title.trim() || !item.input.trim())) { ElMessage.warning('请填写数据集名称，以及每条用例的标题和输入。'); return }
  try {
    const created = await createEvaluationDataset({ name: form.value.name.trim(), description: form.value.description.trim(), cases: form.value.cases.map(item => ({ title: item.title.trim(), input: item.input.trim(), expected_contains: item.expected.split(/[,，]/).map(value => value.trim()).filter(Boolean) })) })
    datasets.value.unshift(created); selectedDataset.value = created.id; createOpen.value = false
    form.value = { name: '', description: '', cases: [{ title: '', input: '', expected: '' }] }
    ElMessage.success('评测数据集已保存。')
  } catch { ElMessage.error('数据集保存失败。') }
}
async function runEvaluation() {
  if (!selectedDataset.value || !selectedWorkflow.value) { ElMessage.warning('请先选择评测集和工作流。'); return }
  if (runtime.mode === 'live' && (!runtime.live_execution_enabled || !runtime.model_configured)) { ElMessage.error('真实模式未启用或模型凭据未配置，请检查模型设置。'); return }
  try { const started = await startEvaluation(selectedDataset.value, selectedWorkflow.value, runtime.mode); runs.value.unshift(started); ElMessage.success('批量评测已提交，结果将逐条更新。'); await load() }
  catch (error: any) { ElMessage.error(error?.response?.data?.error?.message || error?.response?.data?.detail?.message || '评测启动失败。') }
}
async function openDetails(run: EvaluationRun) {
  selectedRun.value = run; detailOpen.value = true
  if (['queued', 'running'].includes(run.status)) { await load(); selectedRun.value = runs.value.find(item => item.id === run.id) || run }
}
onMounted(() => { load(); timer = window.setInterval(() => { if (runs.value.some(item => ['queued', 'running'].includes(item.status))) load() }, 1800) })
onBeforeUnmount(() => { if (timer) window.clearInterval(timer) })
</script>

<template>
  <div class="content-page evaluation-page">
    <div class="page-header"><div><div class="eyebrow">QUALITY / EVALUATIONS</div><h1>评测中心</h1><p>用固定评测集运行已保存工作流，按可检查的关键词标准记录结果与模型差异。</p></div><el-button @click="load" :loading="loading"><el-icon><Refresh /></el-icon>刷新</el-button></div>
    <div class="evaluation-metrics">
      <section class="panel eval-metric"><span>评测数据集</span><strong>{{ datasets.length }}</strong><small>数据库中已保存</small></section>
      <section class="panel eval-metric"><span>历史评测</span><strong>{{ runs.length }}</strong><small>安全沙盒与真实环境分别标记</small></section>
      <section class="panel eval-metric"><span>历史平均通过率</span><strong>{{ averageScore == null ? '暂无数据' : `${(averageScore * 100).toFixed(1)}%` }}</strong><small>仅统计已完成评测</small></section>
    </div>
    <section class="panel eval-launch">
      <div class="eval-section-heading"><div><h2>运行评测</h2><p>每条用例都会创建独立任务与运行记录，可在运行追踪中查看执行细节。</p></div><el-button type="primary" plain @click="createOpen = true"><el-icon><Plus /></el-icon>新建数据集</el-button></div>
      <div class="eval-controls">
        <label>评测数据集<el-select v-model="selectedDataset" placeholder="选择数据集"><el-option v-for="item in datasets" :key="item.id" :label="`${item.name} · ${item.cases.length} 条`" :value="item.id" /></el-select></label>
        <label>执行工作流<el-select v-model="selectedWorkflow" placeholder="选择工作流"><el-option v-for="item in workflows" :key="item.id" :label="`${item.name} · v${item.version}`" :value="item.id" /></el-select></label>
        <label>全局执行环境<el-input :model-value="runtime.modeLabel" readonly :title="runtime.modeCaption"/></label>
        <el-button type="primary" :disabled="!datasets.length || !workflows.length" @click="runEvaluation"><el-icon><VideoPlay /></el-icon>批量运行</el-button>
      </div>
      <div class="eval-note"><i></i>评分说明：填写期望关键词时，输出需包含全部关键词才通过；未填写关键词的用例以工作流执行成功作为通过条件。当前统一使用{{ runtime.modeLabel }}；请通过侧栏总开关切换环境。</div>
      <el-empty v-if="!datasets.length" description="还没有评测集。创建数据集后即可开始批量运行。" :image-size="64"><el-button type="primary" plain @click="createOpen = true">创建第一个数据集</el-button></el-empty>
    </section>
    <section class="panel eval-history">
      <div class="eval-section-heading"><div><h2>评测记录</h2><p>保留数据集、工作流版本、执行模式和每条用例的真实运行引用。</p></div><span class="result-count">{{ runs.length }} 条记录</span></div>
      <el-table :data="runs" v-loading="loading" empty-text="暂无评测记录">
        <el-table-column label="评测 / 数据集" min-width="230"><template #default="{row}"><div class="eval-run-name"><strong>{{ row.dataset_name }}</strong><small>{{ row.id }} · {{ row.workflow_name }} v{{ row.workflow_version }}</small></div></template></el-table-column>
        <el-table-column label="状态" width="110"><template #default="{row}"><span class="status-pill" :class="row.status"><i></i>{{ statusLabel(row.status) }}</span></template></el-table-column>
        <el-table-column label="通过率" width="135"><template #default="{row}"><strong v-if="row.score != null">{{ (row.score * 100).toFixed(1) }}%</strong><span v-else>—</span><small class="eval-fraction">{{ row.passed_count }} / {{ row.case_count }} 通过</small></template></el-table-column>
        <el-table-column label="模型 / 执行器" min-width="190"><template #default="{row}">{{ row.model_name }}</template></el-table-column>
        <el-table-column label="模式" width="105"><template #default="{row}"><el-tag size="small" effect="plain">{{ row.mode.toUpperCase() }}</el-tag></template></el-table-column>
        <el-table-column label="开始时间" min-width="170"><template #default="{row}">{{ row.started_at ? new Date(row.started_at).toLocaleString('zh-CN') : '待启动' }}</template></el-table-column>
        <el-table-column label="操作" width="100" fixed="right"><template #default="{row}"><el-button text @click="openDetails(row)">查看用例</el-button></template></el-table-column>
      </el-table>
    </section>
    <section class="panel eval-history">
      <div class="eval-section-heading"><div><h2>模型对比</h2><p>按相同数据集聚合已完成运行；模型名称记录评测启动时的后端配置。</p></div></div>
      <el-table :data="comparisons" empty-text="完成至少一次评测后显示可比较结果">
        <el-table-column prop="dataset" label="数据集" min-width="180"/><el-table-column prop="model" label="模型 / 执行器" min-width="220"/><el-table-column label="模式" width="110"><template #default="{row}"><el-tag size="small" effect="plain">{{ row.mode.toUpperCase() }}</el-tag></template></el-table-column><el-table-column label="平均通过率" width="145"><template #default="{row}">{{ (row.score * 100).toFixed(1) }}%</template></el-table-column><el-table-column label="完成次数" width="110"><template #default="{row}">{{ row.count }}</template></el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="createOpen" title="新建评测数据集" width="min(720px, 94vw)" destroy-on-close>
      <div class="eval-form"><el-form label-position="top"><el-form-item label="数据集名称"><el-input v-model="form.name" maxlength="160" placeholder="例如：摘要质量基准"/></el-form-item><el-form-item label="说明"><el-input v-model="form.description" maxlength="1000" placeholder="可选说明"/></el-form-item></el-form>
        <div class="eval-case-editor"><div class="eval-case-title"><strong>测试用例</strong><span>期望关键词用逗号分隔；留空表示只检查执行成功。</span></div><article v-for="(item,index) in form.cases" :key="index" class="eval-case-form"><div class="eval-case-row"><el-input v-model="item.title" placeholder="用例标题"/><el-input v-model="item.expected" placeholder="期望关键词（可选，逗号分隔）"/><el-button text type="danger" :disabled="form.cases.length === 1" @click="removeCase(index)"><el-icon><CircleClose /></el-icon></el-button></div><el-input v-model="item.input" type="textarea" :rows="2" placeholder="提交给工作流的输入内容"/></article><el-button text type="primary" @click="addCase"><el-icon><Plus /></el-icon>添加用例</el-button></div>
      </div>
      <template #footer><el-button @click="createOpen = false">取消</el-button><el-button type="primary" @click="saveDataset">保存数据集</el-button></template>
    </el-dialog>
    <el-drawer v-model="detailOpen" title="评测用例结果" size="min(700px, 94vw)">
      <template v-if="selectedRun"><div class="eval-detail-head"><div><div class="eyebrow">{{ selectedRun.id }}</div><h2>{{ selectedRun.dataset_name }}</h2><p>{{ selectedRun.workflow_name }} v{{ selectedRun.workflow_version }} · {{ selectedRun.mode.toUpperCase() }}</p></div><strong v-if="selectedRun.score != null" class="eval-score">{{ (selectedRun.score * 100).toFixed(1) }}%</strong></div>
        <el-alert v-if="selectedRun.status === 'running' || selectedRun.status === 'queued'" title="评测正在执行，页面会自动刷新用例状态。" type="info" :closable="false" show-icon/>
        <article v-for="item in selectedRun.results" :key="item.id" class="eval-result-card"><header><strong>{{ item.case_index + 1 }}. {{ item.title }}</strong><el-tag size="small" :type="item.passed ? 'success' : item.passed === false ? 'danger' : 'info'">{{ item.passed ? '通过' : item.passed === false ? '未通过' : statusLabel(item.status) }}</el-tag></header><p class="eval-case-input">{{ item.input_text }}</p><div v-if="item.expected_contains.length" class="eval-expect">关键词：{{ item.expected_contains.join('、') }}</div><p v-if="item.output_text" class="eval-output">{{ item.output_text }}</p><p v-if="item.error_message" class="eval-error">{{ item.error_message }}</p><footer><span>{{ item.duration_ms == null ? '耗时未知' : `${item.duration_ms} ms` }}</span><router-link v-if="item.run_id" :to="{ path: '/runs', query: { mode: selectedRun.mode, run: item.run_id } }" @click="detailOpen = false">打开运行详情</router-link></footer></article>
        <el-empty v-if="!selectedRun.results.length" description="正在准备评测用例" :image-size="56"/>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.evaluation-page{gap:16px}.evaluation-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.eval-metric{padding:15px 18px;display:grid;gap:3px}.eval-metric span,.eval-metric small{font-size:12px;color:var(--subtle)}.eval-metric strong{font-size:23px;line-height:1.25;font-weight:650}.eval-launch,.eval-history{padding:17px 18px}.eval-section-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.eval-section-heading h2{font-size:15px;font-weight:600}.eval-section-heading p{margin-top:3px;font-size:12px;color:var(--subtle)}.eval-controls{margin-top:18px;display:grid;grid-template-columns:1.2fr 1.2fr .9fr auto;align-items:end;gap:12px}.eval-controls label{display:grid;gap:6px;font-size:12px;color:var(--subtle)}.eval-controls .el-button{height:32px}.eval-note{margin-top:13px;padding:10px 12px;background:var(--soft);border-radius:8px;color:var(--subtle);font-size:12px}.eval-note i{display:inline-block;width:6px;height:6px;background:var(--brand);border-radius:50%;margin-right:7px;vertical-align:2px}.eval-history .eval-section-heading{margin-bottom:12px}.eval-run-name{display:grid;gap:2px}.eval-run-name strong{font-size:12px;font-weight:600}.eval-run-name small,.eval-fraction{display:block;font-size:11px;color:var(--subtle)}.eval-fraction{margin-top:2px}.eval-form{max-height:68vh;overflow:auto;padding-right:4px}.eval-case-editor{border-top:1px solid var(--line);padding-top:14px}.eval-case-title{display:flex;justify-content:space-between;gap:12px;margin-bottom:10px}.eval-case-title strong{font-size:13px}.eval-case-title span{font-size:11px;color:var(--subtle)}.eval-case-form{border:1px solid var(--line);border-radius:9px;padding:10px;margin-bottom:9px}.eval-case-row{display:grid;grid-template-columns:1fr 1.4fr auto;gap:8px;margin-bottom:8px}.eval-detail-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}.eval-detail-head h2{font-size:18px;margin:6px 0 3px}.eval-detail-head p{font-size:12px;color:var(--subtle)}.eval-score{font-size:22px;color:var(--brand)}.eval-result-card{border:1px solid var(--line);border-radius:10px;padding:13px;margin-top:12px}.eval-result-card header,.eval-result-card footer{display:flex;align-items:center;justify-content:space-between;gap:10px}.eval-result-card header strong{font-size:13px}.eval-case-input{margin-top:10px;color:var(--subtle);font-size:12px}.eval-expect{margin-top:8px;font-size:11px;color:var(--subtle)}.eval-output{margin-top:10px;padding:10px;background:var(--soft);border-radius:7px;white-space:pre-wrap;font-size:12px;max-height:260px;overflow:auto}.eval-error{margin-top:8px;color:var(--danger);font-size:12px}.eval-result-card footer{margin-top:10px;font-size:11px;color:var(--subtle)}.eval-result-card footer a{color:var(--brand);text-decoration:none}
@media(max-width:850px){.eval-controls{grid-template-columns:1fr 1fr}.eval-controls .el-button{width:100%}}
@media(max-width:600px){.evaluation-metrics{grid-template-columns:1fr}.eval-controls{grid-template-columns:1fr}.eval-section-heading{align-items:flex-start}.eval-section-heading p{max-width:250px}.eval-case-row{grid-template-columns:1fr auto}.eval-case-row :nth-child(2){grid-column:1}.eval-case-row :nth-child(3){grid-column:2;grid-row:1}}
</style>
