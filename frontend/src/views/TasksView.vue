<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { cancelTask, createTask, deleteTask, getTaskRuns, getTasks, updateTask } from '../api/tasks'
import type { Run, Task } from '../types'
import { ArrowRight, Delete, Edit, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRuntimeStore } from '../stores/runtime'

const route = useRoute()
const router = useRouter()
const runtime = useRuntimeStore()
const rows = ref<Task[]>([])
const total = ref(0)
const page = ref(1)
const q = ref('')
const status = ref('')
const mode = ref('demo')
const loading = ref(false)
const dialog = ref(false)
const editing = ref<Task | null>(null)
const title = ref('')
const description = ref('')
const detailsOpen = ref(false)
const selectedTask = ref<Task | null>(null)
const taskRuns = ref<Run[]>([])
const detailsLoading = ref(false)
let refreshTimer: number | undefined

async function load() {
  loading.value = true
  try {
    const result = await getTasks({ q: q.value, status: status.value || undefined, mode: mode.value || undefined, page: page.value, page_size: 10 })
    rows.value = result.items
    total.value = result.total
  } catch { ElMessage.error('任务列表加载失败') }
  finally { loading.value = false }
}

function openCreate() {
  editing.value = null
  title.value = ''
  description.value = ''
  dialog.value = true
}

function openEdit(task: Task) {
  editing.value = task
  title.value = task.title
  description.value = task.description
  dialog.value = true
}

async function submit() {
  if (!title.value.trim()) return
  try {
    if (editing.value) {
      await updateTask(editing.value.id, { title: title.value.trim(), description: description.value })
      ElMessage.success('任务已更新')
    } else {
      await createTask({ title: title.value.trim(), description: description.value, mode: runtime.mode })
      ElMessage.success(`任务已创建并在${runtime.modeLabel}中运行`)
    }
    dialog.value = false
    await load()
  } catch { ElMessage.error(editing.value ? '任务更新失败' : '任务创建失败') }
}

async function cancel(task: Task) {
  try {
    await ElMessageBox.confirm(`确认取消任务“${task.title}”？`, '取消任务', { confirmButtonText: '确认取消', cancelButtonText: '返回', type: 'warning' })
    await cancelTask(task.id)
    ElMessage.success('任务已取消')
    await load()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error('取消任务失败')
  }
}

async function remove(task: Task) {
  try {
    await ElMessageBox.confirm(`删除“${task.title}”及其运行记录？此操作不可撤销。`, '删除任务', { confirmButtonText: '删除', cancelButtonText: '返回', type: 'warning' })
    await deleteTask(task.id)
    ElMessage.success('任务及关联运行记录已删除')
    await load()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error('删除失败，活动中的任务不能删除')
  }
}

async function openDetails(task: Task) {
  selectedTask.value = task
  detailsOpen.value = true
  detailsLoading.value = true
  try { taskRuns.value = await getTaskRuns(task.id) }
  catch { taskRuns.value = []; ElMessage.error('运行记录加载失败') }
  finally { detailsLoading.value = false }
}

const stateLabels: Record<string, string> = { queued: '排队中', running: '执行中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }
const formatDate = (value: string) => new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
watch([q, status, mode], () => { page.value = 1; load() })
watch(() => runtime.mode, value => { mode.value = value })
onMounted(() => { mode.value = runtime.mode; load(); refreshTimer = window.setInterval(() => { if (rows.value.some(task => ['queued', 'running'].includes(task.status))) load() }, 2000); if (route.query.create === '1') openCreate() })
onBeforeUnmount(() => { if (refreshTimer) window.clearInterval(refreshTimer) })
</script>

<template>
  <div class="content-page">
    <div class="page-header">
      <div><div class="eyebrow">WORKSPACE / TASKS</div><h1>任务中心</h1><p>集中管理任务、跟踪执行状态并查看独立运行记录。</p></div>
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新建任务</el-button>
    </div>
    <section class="panel task-list-panel">
      <div class="list-toolbar">
        <el-input v-model="q" clearable placeholder="搜索任务名称…" class="search-input"><template #prefix><el-icon><Search /></el-icon></template></el-input>
        <el-select v-model="status" clearable placeholder="全部状态" class="status-select">
          <el-option v-for="(label, value) in stateLabels" :key="value" :label="label" :value="value" />
        </el-select>
        <el-select v-model="mode" clearable placeholder="全部环境" class="mode-select"><el-option label="安全沙盒" value="demo"/><el-option label="真实环境" value="live"/></el-select>
        <el-button text circle aria-label="刷新" @click="load"><el-icon><Refresh /></el-icon></el-button>
        <span class="result-count">共 {{ total }} 个任务</span>
      </div>
      <el-table :data="rows" v-loading="loading" style="width:100%" empty-text="暂无匹配任务">
        <el-table-column label="任务" min-width="260"><template #default="{ row }"><div class="table-task"><span class="task-mini-icon">✦</span><div><strong>{{ row.title }}</strong><small>{{ row.id }}</small></div></div></template></el-table-column>
        <el-table-column prop="workflow" label="工作流" min-width="145" />
        <el-table-column label="状态" width="110"><template #default="{ row }"><span class="status-pill" :class="row.status"><i></i>{{ stateLabels[row.status] }}</span></template></el-table-column>
        <el-table-column label="模式" width="100"><template #default="{ row }"><el-tag size="small" effect="plain" class="demo-tag">{{ row.mode.toUpperCase() }}</el-tag></template></el-table-column>
        <el-table-column label="创建时间" min-width="145"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
        <el-table-column label="操作" width="190" fixed="right"><template #default="{ row }">
          <el-button text @click="openDetails(row)">运行记录</el-button>
          <el-dropdown trigger="click"><el-button text>更多</el-button><template #dropdown><el-dropdown-menu>
            <el-dropdown-item :icon="Edit" :disabled="['queued','running'].includes(row.status)" @click="openEdit(row)">编辑任务</el-dropdown-item>
            <el-dropdown-item v-if="['queued','running'].includes(row.status)" @click="cancel(row)">取消运行</el-dropdown-item>
            <el-dropdown-item :icon="Delete" divided @click="remove(row)">删除任务</el-dropdown-item>
          </el-dropdown-menu></template></el-dropdown>
        </template></el-table-column>
      </el-table>
      <div class="pagination"><el-pagination v-model:current-page="page" :page-size="10" :total="total" layout="total, prev, pager, next" @current-change="load" /></div>
    </section>

    <el-dialog v-model="dialog" :title="editing ? '编辑任务' : '创建任务'" width="540px">
      <p class="dialog-copy">{{ editing ? '更新任务描述。执行中的任务不能编辑。' : `任务将使用全局环境：${runtime.modeLabel}。` }}</p>
      <el-form label-position="top"><el-form-item label="任务目标"><el-input v-model="title" maxlength="500" show-word-limit placeholder="例如：汇总本周产品反馈并整理成报告" /></el-form-item><el-form-item label="补充说明"><el-input v-model="description" type="textarea" :rows="3" maxlength="5000" show-word-limit placeholder="可选：补充范围、格式或验收要求" /></el-form-item></el-form>
      <template #footer><el-button @click="dialog = false">取消</el-button><el-button type="primary" @click="submit">{{ editing ? '保存修改' : '创建并运行' }}</el-button></template>
    </el-dialog>

    <el-drawer v-model="detailsOpen" title="任务与运行记录" size="min(620px, 92vw)">
      <div v-if="selectedTask">
        <div class="run-detail-head"><span class="eyebrow">{{ selectedTask.id }}</span><h2>{{ selectedTask.title }}</h2><p>{{ selectedTask.description || '暂无补充说明' }}</p><div class="run-detail-tags"><el-tag effect="plain">{{ selectedTask.mode.toUpperCase() }}</el-tag><el-tag :type="selectedTask.status === 'failed' ? 'danger' : selectedTask.status === 'succeeded' ? 'success' : 'info'">{{ stateLabels[selectedTask.status] }}</el-tag></div></div>
        <el-divider />
        <div v-loading="detailsLoading" class="run-history">
          <div class="run-history-heading"><h3>运行历史</h3><span>{{ taskRuns.length }} 次运行</span></div>
          <el-empty v-if="!detailsLoading && !taskRuns.length" description="暂无运行记录" :image-size="56" />
          <article v-for="run in taskRuns" :key="run.id" class="run-history-card">
            <div class="run-history-top"><strong>{{ run.workflow }}</strong><span class="status-pill" :class="run.status"><i></i>{{ stateLabels[run.status] }}</span></div>
            <div class="run-history-meta"><span>运行 {{ run.id }}</span><span>{{ formatDate(run.created_at) }}</span><span v-if="run.duration_ms">{{ (run.duration_ms / 1000).toFixed(2) }} 秒</span></div>
            <p v-if="run.output_text" class="run-output">{{ run.output_text }}</p><p v-if="run.error_message" class="run-error">{{ run.error_message }}</p>
            <div class="snapshot-meta">工作流版本 {{ run.workflow_version }} · {{ run.mode.toUpperCase() }} · Token {{ run.tokens ?? '未知' }}</div>
          </article>
        </div>
      </div>
      <template #footer><el-button @click="router.push('/runs'); detailsOpen = false">打开运行追踪 <el-icon><ArrowRight /></el-icon></el-button></template>
    </el-drawer>
  </div>
</template>
