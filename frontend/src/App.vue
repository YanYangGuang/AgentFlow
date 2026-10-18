<script setup lang="ts">
import './styles/app.css'
import { computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useUiStore } from './stores/ui'
import { Menu, House, List, Connection, Tools, Collection, Clock, DataAnalysis, Setting, Moon, Sunny, Plus, Bell } from '@element-plus/icons-vue'
import { useRuntimeStore } from './stores/runtime'
import { ElMessage, ElMessageBox } from 'element-plus'
const ui = useUiStore(); const runtime = useRuntimeStore(); const route = useRoute(); const title = computed(() => String(route.meta.title || '工作台'))
const groups = [[{label:'工作台',path:'/dashboard',icon:House},{label:'任务中心',path:'/tasks',icon:List}], [{label:'流程编排',path:'/workflows',icon:Connection},{label:'工具管理',path:'/tools',icon:Tools},{label:'知识库',path:'/knowledge',icon:Collection}], [{label:'运行追踪',path:'/runs',icon:Clock},{label:'评测中心',path:'/evaluations',icon:DataAnalysis}], [{label:'模型设置',path:'/settings/models',icon:Setting},{label:'系统设置',path:'/settings',icon:Setting}]]
onMounted(async () => { document.documentElement.dataset.theme = ui.theme; document.documentElement.dataset.motion = ui.ambientMotion ? 'on' : 'off'; try { await runtime.load() } catch { ElMessage.error('运行环境状态读取失败，请确认后端服务已启动。') } })
watch(() => ui.theme, value => { document.documentElement.dataset.theme = value })
watch(() => ui.ambientMotion, value => { document.documentElement.dataset.motion = value ? 'on' : 'off' })
async function changeRuntimeMode(value: string | number | boolean) {
  const next = value ? 'live' : 'demo'
  if (next === runtime.mode) return
  if (next === 'live') {
    try { await ElMessageBox.confirm(`真实环境会调用 ${runtime.provider || '已配置'} 的模型，并可能产生费用。确认切换？`, '切换到真实环境', { confirmButtonText: '确认切换', cancelButtonText: '继续使用安全沙盒', type: 'warning' }) }
    catch { return }
  }
  try { await runtime.setMode(next); ElMessage.success(`已切换到${runtime.modeLabel}`) }
  catch (error: any) { ElMessage.error(error?.response?.data?.error?.message || '环境切换失败，后端未接受本次切换。') }
}
</script>
<template>
  <div class="app-shell" :class="{ 'is-collapsed': ui.collapsed }">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark">A</div><div v-if="!ui.collapsed" class="brand-copy"><strong>AgentFlow</strong><span>AI Agent Workspace</span></div><el-button class="collapse-btn" text circle aria-label="收起导航" @click="ui.toggleSidebar"><el-icon><Menu /></el-icon></el-button></div>
      <div class="nav-caption" v-if="!ui.collapsed">工作空间</div>
      <nav class="nav-groups"><div v-for="(group, index) in groups" :key="index" class="nav-group"><router-link v-for="item in group" :key="item.path" :to="item.path" class="nav-link" :class="{active: route.path === item.path}" :title="ui.collapsed ? item.label : undefined"><el-icon><component :is="item.icon" /></el-icon><span v-if="!ui.collapsed">{{ item.label }}</span></router-link></div></nav>
      <div class="sidebar-bottom"><div class="mode-card" v-if="!ui.collapsed"><span class="mode-dot" :class="runtime.mode"></span><div><strong>{{ runtime.modeLabel }}</strong><small>{{ runtime.modeCaption }}</small></div><el-switch :model-value="runtime.isLive" inline-prompt active-text="LIVE" inactive-text="沙盒" :disabled="runtime.switching || (!runtime.isLive && (!runtime.live_execution_enabled || !runtime.model_configured))" aria-label="全局执行环境切换" @change="changeRuntimeMode"/></div><el-button class="profile" text><el-avatar :size="32">A</el-avatar><span v-if="!ui.collapsed" class="profile-name">AgentFlow 用户</span><el-icon v-if="!ui.collapsed"><Setting /></el-icon></el-button></div>
    </aside>
    <section class="main-shell"><header class="topbar"><div class="breadcrumb"><span>工作空间</span><span class="crumb-sep">/</span><strong>{{ title }}</strong></div><div class="top-actions"><button class="environment" :class="runtime.mode" type="button" :aria-label="`当前${runtime.modeLabel}，点击切换执行环境`" @click="changeRuntimeMode(!runtime.isLive)"><span class="mode-dot" :class="runtime.mode"></span>{{ runtime.modeLabel }}</button><el-button text class="motion-toggle" :aria-pressed="ui.ambientMotion" :aria-label="`动态氛围${ui.ambientMotion ? '已开启' : '已关闭'}，点击切换`" @click="ui.toggleMotion">氛围 {{ ui.ambientMotion ? '开' : '关' }}</el-button><el-button text circle aria-label="切换主题" @click="ui.toggleTheme"><el-icon><Sunny v-if="ui.theme === 'dark'"/><Moon v-else/></el-icon></el-button><el-button text circle aria-label="通知"><el-icon><Bell /></el-icon></el-button><el-button type="primary" class="create-top" @click="$router.push('/tasks?create=1')"><el-icon><Plus /></el-icon>新建任务</el-button></div></header><main class="page-area"><router-view /></main></section>
  </div>
</template>

<style scoped>
.mode-card{align-items:center;gap:8px}.mode-card>div{min-width:0;flex:1}.mode-card small{display:block;line-height:1.35}.mode-card .el-switch{transform:scale(.86);transform-origin:right center}.environment{font:inherit;background:transparent;border:0;cursor:pointer}.environment.live{color:#d94e4e}.environment.demo{color:#bb822e}.motion-toggle{font-size:11px;color:var(--subtle)}
</style>

