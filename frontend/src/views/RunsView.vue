<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getRun, getRunEvents, getRunNodes, getRuns } from '../api/tasks'
import type { NodeRun, Run, RunEvent } from '../types'
import { ArrowRight, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useRuntimeStore } from '../stores/runtime'

const router = useRouter()
const route = useRoute()
const runtime = useRuntimeStore()
const rows = ref<Run[]>([])
const total = ref(0)
const page = ref(1)
const status = ref('')
const mode = ref('demo')
const loading = ref(false)
const detailOpen = ref(false)
const selected = ref<Run | null>(null)
const selectedNodes = ref<NodeRun[]>([])
const selectedEvents = ref<RunEvent[]>([])
const detailsLoading = ref(false)
let refreshTimer: number | undefined
const stateLabels: Record<string, string> = { queued: '排队中', running: '执行中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }
const formatDate = (value: string) => new Date(value).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })

async function load() {
  loading.value = true
  try {
    const result = await getRuns({ status: status.value || undefined, mode: mode.value || undefined, page: page.value, page_size: 10 })
    rows.value = result.items
    total.value = result.total
  } catch { ElMessage.error('运行记录加载失败') }
  finally { loading.value = false }
}

async function showDetails(run: Run) {
  selected.value = run
  detailOpen.value = true
  detailsLoading.value = true
  try { [selectedNodes.value, selectedEvents.value] = await Promise.all([getRunNodes(run.id), getRunEvents(run.id)]) }
  catch { ElMessage.error('节点执行详情加载失败') }
  finally { detailsLoading.value = false }
}
watch([status, mode], () => { page.value = 1; load() })
watch(() => runtime.mode, value => { if (!route.query.mode) mode.value = value })
onMounted(async () => {
  mode.value = runtime.mode
  if (route.query.mode === 'live' || route.query.mode === 'demo') mode.value = String(route.query.mode)
  await load()
  if (typeof route.query.run === 'string') {
    try { await showDetails(await getRun(route.query.run)) } catch { ElMessage.error('无法打开对应运行记录。') }
  }
  refreshTimer = window.setInterval(() => { if (rows.value.some(run => ['queued', 'running'].includes(run.status))) load() }, 2000)
})
onBeforeUnmount(() => { if (refreshTimer) window.clearInterval(refreshTimer) })
</script>

<template>
  <div class="content-page">
    <div class="page-header"><div><div class="eyebrow">OBSERVABILITY / RUNS</div><h1>运行追踪</h1><p>每次执行独立留档，查看状态、耗时、输出和所用工作流快照。</p></div></div>
    <section class="panel task-list-panel">
      <div class="list-toolbar">
        <el-select v-model="status" clearable placeholder="全部状态" class="status-select"><el-option label="排队中" value="queued"/><el-option label="执行中" value="running"/><el-option label="已完成" value="succeeded"/><el-option label="失败" value="failed"/><el-option label="已取消" value="cancelled"/></el-select>
        <el-select v-model="mode" clearable placeholder="全部环境" class="mode-select"><el-option label="安全沙盒" value="demo"/><el-option label="真实环境" value="live"/></el-select>
        <el-button text circle aria-label="刷新" @click="load"><el-icon><Refresh /></el-icon></el-button><span class="result-count">共 {{ total }} 次运行</span>
      </div>
      <el-table :data="rows" v-loading="loading" style="width:100%" empty-text="暂无运行记录">
        <el-table-column label="运行 / 任务" min-width="285"><template #default="{ row }"><div class="table-task"><span class="run-status-icon" :class="row.status">{{ row.status === 'failed' ? '!' : '↗' }}</span><div><strong>{{ row.task_title }}</strong><small>{{ row.id }} · {{ row.workflow }}</small></div></div></template></el-table-column>
        <el-table-column label="状态" width="115"><template #default="{ row }"><span class="status-pill" :class="row.status"><i></i>{{ stateLabels[row.status] }}</span></template></el-table-column>
        <el-table-column label="耗时" width="105"><template #default="{ row }">{{ row.duration_ms == null ? '—' : `${(row.duration_ms / 1000).toFixed(2)} 秒` }}</template></el-table-column>
        <el-table-column label="Token" width="100"><template #default="{ row }">{{ row.tokens ?? '未知' }}</template></el-table-column>
        <el-table-column label="运行时间" min-width="185"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
        <el-table-column label="模式" width="100"><template #default="{ row }"><el-tag size="small" effect="plain" class="demo-tag">{{ row.mode.toUpperCase() }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="100" fixed="right"><template #default="{ row }"><el-button text @click="showDetails(row)">详情 <el-icon><ArrowRight /></el-icon></el-button></template></el-table-column>
      </el-table>
      <div class="pagination"><el-pagination v-model:current-page="page" :page-size="10" :total="total" layout="total, prev, pager, next" @current-change="load" /></div>
    </section>
    <el-drawer v-model="detailOpen" title="运行详情" size="min(620px, 92vw)">
      <div v-if="selected" v-loading="detailsLoading">
        <div class="run-detail-head"><span class="eyebrow">{{ selected.id }}</span><h2>{{ selected.task_title }}</h2><p>{{ selected.workflow }} · 版本 {{ selected.workflow_version }} · {{ selected.mode.toUpperCase() }}</p><div class="run-detail-tags"><el-tag :type="selected.status === 'failed' ? 'danger' : selected.status === 'succeeded' ? 'success' : 'info'">{{ stateLabels[selected.status] }}</el-tag><el-tag effect="plain">{{ selected.duration_ms == null ? '耗时未知' : `${(selected.duration_ms / 1000).toFixed(2)} 秒` }}</el-tag><el-tag effect="plain">Token {{ selected.tokens ?? '未知' }}</el-tag></div></div>
        <el-divider />
        <div class="run-timeline"><div><span>创建</span><strong>{{ formatDate(selected.created_at) }}</strong></div><div><span>开始</span><strong>{{ selected.started_at ? formatDate(selected.started_at) : '尚未开始' }}</strong></div><div><span>结束</span><strong>{{ selected.finished_at ? formatDate(selected.finished_at) : '尚未结束' }}</strong></div></div>
        <section v-if="selected.output_text" class="run-output-block"><h3>运行输出</h3><p>{{ selected.output_text }}</p></section>
        <section v-if="selected.error_message" class="run-error-block"><h3>错误信息</h3><p>{{ selected.error_message }}</p></section>
        <section v-if="selectedNodes.length" class="node-execution-list"><h3>节点执行</h3><article v-for="node in selectedNodes" :key="node.id" class="node-execution-card"><div><strong>{{ node.label }}</strong><span class="status-pill" :class="node.status"><i></i>{{ node.status }}</span></div><p v-if="node.duration_ms != null">耗时 {{ node.duration_ms }} ms</p><p v-if="node.error_message" class="run-error">{{ node.error_message }}</p><details v-if="node.output_json"><summary>查看节点输出</summary><pre>{{ JSON.stringify(JSON.parse(node.output_json), null, 2) }}</pre></details></article></section>
        <section v-if="selectedEvents.length" class="run-event-list"><h3>事件时间线</h3><div v-for="event in selectedEvents" :key="event.id" class="run-event-item"><i :class="event.status"></i><time>{{ new Date(event.created_at).toLocaleTimeString('zh-CN') }}</time><strong>{{ event.event }}</strong><span>{{ event.message }}</span></div></section>
        <section class="snapshot-block"><h3>工作流快照</h3><pre>{{ JSON.stringify(JSON.parse(selected.workflow_snapshot || '{}'), null, 2) }}</pre></section>
      </div>
      <template #footer><el-button @click="router.push('/tasks')">查看所属任务 <el-icon><ArrowRight /></el-icon></el-button></template>
    </el-drawer>
  </div>
</template>
