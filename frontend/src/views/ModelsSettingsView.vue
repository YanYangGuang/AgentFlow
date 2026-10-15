<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, MoreFilled, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { deleteProviderCredential, getModelProviders, getProviderModels, saveModelProvider, testModelProvider } from '../api/tasks'
import type { ModelProvider, ProviderModel, ProviderTestResult } from '../types'

type ProviderDraft = { api_base_url: string; default_model_id: string; api_key: string }
const providers = ref<ModelProvider[]>([])
const drafts = reactive<Record<string, ProviderDraft>>({})
const catalogs = reactive<Record<string, ProviderModel[]>>({})
const catalogLoading = ref(false)
const catalogError = ref('')
const loading = ref(true)
const testing = ref(false)
const selectedCode = ref('openrouter')
const temporaryTest = ref<ProviderTestResult | null>(null)
const activeTab = ref<'catalog' | 'providers' | 'default'>('catalog')
const modelSearch = ref('')
const providerFilter = ref('all')
const statusFilter = ref('all')
const page = ref(1)
const pageSize = 20
const modelsLoading = ref(false)
const catalogErrors = reactive<Record<string, string>>({})
const selected = computed(() => providers.value.find((item) => item.code === selectedCode.value) ?? null)
const draft = computed(() => drafts[selectedCode.value])
const catalog = computed(() => catalogs[selectedCode.value] ?? [])
const configuredProviders = computed(() => providers.value.filter((item) => item.configured))
const defaultProvider = computed(() => providers.value.find((item) => item.is_default) ?? null)
const allModels = computed(() => Object.entries(catalogs).flatMap(([code, items]) => {
  const provider = providers.value.find((item) => item.code === code)
  return provider ? items.map((model) => ({ ...model, providerCode: code, providerName: provider.name, connected: provider.last_test_status === 'connected' })) : []
}))
const filteredModels = computed(() => {
  const query = modelSearch.value.trim().toLowerCase()
  return allModels.value.filter((model) => {
    const matchesQuery = !query || `${model.name} ${model.id} ${model.providerName}`.toLowerCase().includes(query)
    const matchesProvider = providerFilter.value === 'all' || model.providerCode === providerFilter.value
    const provider = providers.value.find((item) => item.code === model.providerCode)
    const matchesStatus = statusFilter.value === 'all' || (statusFilter.value === 'connected' ? model.connected : statusFilter.value === 'failed' ? provider?.last_test_status === 'connection_failed' : !model.connected && provider?.last_test_status !== 'connection_failed')
    return matchesQuery && matchesProvider && matchesStatus
  })
})
const pageModels = computed(() => filteredModels.value.slice((page.value - 1) * pageSize, page.value * pageSize))
watch([modelSearch, providerFilter, statusFilter], () => { page.value = 1 })
function formatContext(context: number | null) { return context ? context >= 1_000_000 ? `${context / 1_000_000}M` : `${Math.round(context / 1000)}K` : '—' }
const isDirty = computed(() => {
  const item = selected.value, value = draft.value
  return !!item && !!value && (value.api_base_url !== item.base_url || value.default_model_id !== item.default_model_id || !!value.api_key)
})
const connectionLabel = computed(() => {
  if (testing.value) return '正在测试'
  if (isDirty.value) return '配置已修改'
  const status = selected.value?.last_test_status
  if (status === 'connected') return '已连接'
  if (status === 'connection_failed') return '连接失败'
  if (status === 'unconfigured' || !selected.value?.configured) return '未配置'
  return '待测试'
})

async function refresh() {
  loading.value = true
  try {
    const previousCode = selectedCode.value
    const hadProviders = providers.value.length > 0
    providers.value = await getModelProviders()
    for (const item of providers.value) {
      const old = drafts[item.code]
      drafts[item.code] = { api_base_url: old?.api_base_url ?? item.base_url, default_model_id: old?.default_model_id ?? item.default_model_id, api_key: old?.api_key ?? '' }
    }
    selectedCode.value = hadProviders && providers.value.some((item) => item.code === previousCode)
      ? previousCode
      : providers.value.find((item) => item.is_default)?.code ?? providers.value[0]?.code ?? 'openrouter'
  }
  catch { ElMessage.error('无法读取后端模型配置状态') }
  finally { loading.value = false }
}

function switchProvider(code: string) {
  selectedCode.value = code
  temporaryTest.value = null
  catalogError.value = ''
}

function errorMessage(error: unknown, fallback: string) {
  return (error as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error?.message || fallback
}

async function save() {
  if (!draft.value) return
  try {
    const payload: { api_base_url: string; default_model_id: string; api_key?: string } = {
      api_base_url: draft.value.api_base_url,
      default_model_id: draft.value.default_model_id.trim(),
    }
    if (draft.value.api_key.trim()) payload.api_key = draft.value.api_key.trim()
    const updated = await saveModelProvider(selectedCode.value, payload)
    providers.value = providers.value.map((item) => item.code === updated.code ? updated : { ...item, is_default: false })
    draft.value.api_base_url = updated.base_url
    draft.value.default_model_id = updated.default_model_id
    draft.value.api_key = ''
    temporaryTest.value = null
    ElMessage.success('供应商配置已安全保存')
  } catch (error: unknown) { ElMessage.error(errorMessage(error, '保存配置失败')) }
}

async function test() {
  if (!draft.value) return
  testing.value = true
  try {
    const payload: { api_base_url: string; default_model_id: string; api_key?: string } = { api_base_url: draft.value.api_base_url, default_model_id: draft.value.default_model_id }
    if (draft.value.api_key.trim()) payload.api_key = draft.value.api_key.trim()
    const result = await testModelProvider(selectedCode.value, payload)
    temporaryTest.value = result
    if (result.persisted) await refresh()
    ElMessage[result.ok ? 'success' : 'error'](result.message)
  } catch (error: unknown) {
    const message = errorMessage(error, '连接测试失败，请检查后端配置和服务状态。')
    temporaryTest.value = { ok: false, status: 'connection_failed', tested_at: new Date().toISOString(), message, persisted: false, models_available: null }
    ElMessage.error(message)
  } finally { testing.value = false }
}

async function refreshCatalog() {
  if (!selected.value) return
  catalogLoading.value = true
  catalogError.value = ''
  try { catalogs[selectedCode.value] = await getProviderModels(selectedCode.value) }
  catch (error: unknown) { catalogError.value = errorMessage(error, '模型目录加载失败；仍可手动输入模型 ID。') }
  finally { catalogLoading.value = false }
}

async function refreshAllCatalogs() {
  modelsLoading.value = true
  for (const key of Object.keys(catalogErrors)) delete catalogErrors[key]
  const targets = configuredProviders.value
  const results = await Promise.allSettled(targets.map(async (provider) => ({ code: provider.code, models: await getProviderModels(provider.code) })))
  results.forEach((result, index) => {
    const code = targets[index].code
    if (result.status === 'fulfilled') catalogs[code] = result.value.models
    else catalogErrors[code] = errorMessage(result.reason, '目录读取失败；可检查凭据、权限和网络。')
  })
  modelsLoading.value = false
  if (results.some((item) => item.status === 'fulfilled')) ElMessage.success(`已刷新 ${results.filter((item) => item.status === 'fulfilled').length} 个供应商的真实模型目录`)
  else if (targets.length) ElMessage.warning('模型目录未能加载；仍可在供应商连接页手动填写模型 ID。')
}

async function setDefaultFromModel(model: (typeof allModels.value)[number]) {
  selectedCode.value = model.providerCode
  if (drafts[model.providerCode]) drafts[model.providerCode].default_model_id = model.id
  activeTab.value = 'providers'
  await save()
}

async function removeCredential() {
  if (!selected.value?.configured) return
  try {
    await ElMessageBox.confirm(`确认删除 ${selected.value.name} 的已保存凭据？`, '删除凭据', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    const updated = await deleteProviderCredential(selectedCode.value)
    providers.value = providers.value.map((item) => item.code === updated.code ? updated : item)
    temporaryTest.value = null
    ElMessage.success('凭据已删除')
  } catch (error: unknown) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error, '删除凭据失败'))
  }
}
onMounted(async () => { await refresh() })
</script>

<template>
  <div class="content-page provider-console">
    <header class="model-service-header">
      <div><div class="model-service-kicker">AGENTFLOW / MODEL GATEWAY <span v-if="loading" class="provider-loading-hint">· 正在同步配置</span></div><h1>模型服务</h1><p>统一管理模型、供应商连接与默认模型</p></div>
      <div class="model-service-actions"><el-popover placement="bottom-end" :width="320" trigger="click"><template #reference><el-button>安全说明</el-button></template><div class="security-popover-copy"><p>供应商状态与配置从后端读取并持久化。真实执行开关仅控制是否允许模型请求，不代表连接已验证。</p><p>页面保存的凭据在服务端加密存储。模型目录刷新和连接测试会调用真实供应商接口；安全沙盒不会自动发起这些请求。</p></div></el-popover><el-button type="primary" @click="activeTab = 'providers'; selectedCode = providers.find((item) => !item.configured)?.code || providers[0]?.code || 'openrouter'"><el-icon><Plus /></el-icon>添加供应商</el-button></div>
    </header>
    <nav class="model-service-tabs" aria-label="模型服务页面导航">
      <button type="button" :class="{ active: activeTab === 'catalog' }" @click="activeTab = 'catalog'">模型目录</button>
      <button type="button" :class="{ active: activeTab === 'providers' }" @click="activeTab = 'providers'">供应商连接</button>
      <button type="button" :class="{ active: activeTab === 'default' }" @click="activeTab = 'default'">默认模型</button>
    </nav>

    <div v-show="activeTab === 'catalog'" class="catalog-tab-panel">
      <div class="catalog-toolbar panel">
        <el-input v-model="modelSearch" clearable class="model-search" placeholder="搜索模型名称、模型 ID 或供应商"><template #prefix><el-icon><Search /></el-icon></template></el-input>
        <el-select v-model="providerFilter" class="catalog-filter" aria-label="按供应商筛选"><el-option label="所有供应商" value="all"/><el-option v-for="provider in providers" :key="provider.code" :label="provider.name" :value="provider.code"/></el-select>
        <el-select class="catalog-filter capability-filter" disabled placeholder="能力信息未由目录提供" aria-label="能力筛选不可用"><el-option label="能力信息未由目录提供" value="unavailable"/></el-select>
        <el-select v-model="statusFilter" class="catalog-filter" aria-label="按连接状态筛选"><el-option label="全部状态" value="all"/><el-option label="已验证连接" value="connected"/><el-option label="待验证" value="pending"/><el-option label="验证失败" value="failed"/></el-select>
        <el-button :loading="modelsLoading" @click="refreshAllCatalogs"><el-icon><Refresh /></el-icon>刷新目录</el-button>
      </div>
      <div class="catalog-summary"><span><strong>{{ allModels.length }}</strong> 个已加载模型</span><span><strong>{{ providers.length }}</strong> 个供应商</span><span><strong>{{ configuredProviders.length }}</strong> 个已配置</span><span class="catalog-summary-note">目录数据由供应商接口实时返回；未加载和失败不会显示为可用模型。</span></div>
      <section class="panel model-catalog-panel">
          <div class="catalog-table-head"><span>模型</span><span>供应商</span><span>能力</span><span>上下文</span><span>连接状态</span><span>操作</span></div>
          <div v-if="filteredModels.length" class="catalog-table-body">
            <div v-for="model in pageModels" :key="`${model.providerCode}:${model.id}`" class="catalog-row">
              <div class="catalog-model-cell"><strong>{{ model.name }}</strong><code>{{ model.id }}</code></div>
              <div class="catalog-provider-cell"><span class="catalog-provider-mark">{{ model.providerName.slice(0, 2).toUpperCase() }}</span>{{ model.providerName }}</div>
              <div class="catalog-unknown">—</div>
              <div class="catalog-context">{{ formatContext(model.context_length) }}</div>
              <div><span class="catalog-status" :class="model.connected ? 'connected' : 'pending'"><i></i>{{ model.connected ? '已验证' : '待验证' }}</span></div>
              <div><el-dropdown v-if="!defaultProvider || defaultProvider.code !== model.providerCode || defaultProvider.default_model_id !== model.id" trigger="click"><el-button link :aria-label="`模型 ${model.id} 的操作`"><el-icon><MoreFilled /></el-icon></el-button><template #dropdown><el-dropdown-menu><el-dropdown-item @click="setDefaultFromModel(model)">设为默认模型</el-dropdown-item></el-dropdown-menu></template></el-dropdown><span v-else class="default-mark"><el-icon><Check /></el-icon>默认</span></div>
            </div>
          </div>
          <div v-else-if="modelsLoading" class="catalog-empty">正在从已配置供应商读取模型目录…</div>
          <div v-else class="catalog-empty"><strong>{{ allModels.length ? '没有匹配的模型' : '尚未加载模型目录' }}</strong><span>{{ allModels.length ? '调整搜索或筛选条件。' : '点击“刷新目录”读取真实供应商数据。未配置凭据的供应商不会返回目录。' }}</span><el-button v-if="!allModels.length" type="primary" plain @click="refreshAllCatalogs">刷新模型目录</el-button></div>
          <div v-if="Object.keys(catalogErrors).length" class="catalog-errors"><div v-for="(message, code) in catalogErrors" :key="code"><strong>{{ providers.find((item) => item.code === code)?.name || code }}</strong><span>{{ message }}</span></div></div>
          <div v-if="filteredModels.length > pageSize" class="catalog-pagination"><span>共 {{ filteredModels.length }} 个模型</span><el-pagination v-model:current-page="page" :page-size="pageSize" :total="filteredModels.length" layout="prev, pager, next" background small /></div>
          <footer class="catalog-table-footer">模型能力字段和上下文长度仅在供应商接口提供时展示；“已验证”来自持久化连接测试状态。</footer>
      </section>
    </div>

    <div v-show="activeTab === 'providers'" class="provider-content-layout">
      <aside class="panel provider-nav" aria-label="模型供应商">
        <div class="provider-nav-heading"><strong>供应商</strong><small>已配置 {{ providers.filter((item) => item.configured).length }}</small></div>
        <button v-for="provider in providers" :key="provider.code" class="provider-nav-item" :class="{ active: selectedCode === provider.code }" @click="switchProvider(provider.code)">
          <span class="provider-nav-mark">{{ provider.name === 'OpenRouter' ? 'OR' : provider.name === 'OpenAI' ? 'OA' : provider.name === 'DeepSeek' ? 'DS' : provider.name === 'Google Gemini' ? 'G' : provider.name === 'Anthropic Claude' ? 'A' : 'API' }}</span>
          <span class="provider-nav-copy"><strong>{{ provider.name }}</strong><small>{{ provider.is_default ? '默认供应商' : provider.configured ? '已配置' : '未配置' }}</small></span>
          <span class="provider-nav-state" :class="provider.last_test_status">{{ provider.last_test_status === 'connected' ? '已连接' : provider.last_test_status === 'connection_failed' ? '失败' : provider.configured ? '待测' : '' }}</span>
        </button>
      </aside>

    <section class="panel provider-workspace">
      <header class="provider-workspace-header">
        <div class="provider-heading-main"><span class="provider-mark provider-mark-large">✳</span><div><h1>模型服务配置</h1><p>AI Model Providers · {{ selected?.name || '统一模型接入' }}</p></div></div>
        <el-tag class="provider-connection-state" :type="connectionLabel === '已连接' ? 'success' : connectionLabel === '连接失败' ? 'danger' : connectionLabel === '正在测试' ? 'warning' : 'info'">{{ connectionLabel }}</el-tag>
      </header>

      <template v-if="selected && draft">
        <div class="provider-form-field">
          <label>API Base URL</label>
          <el-input v-model="draft.api_base_url" placeholder="https://api.example.com/v1" />
          <p class="provider-field-hint">请求由后端供应商适配器处理。请使用服务商 API 根地址。</p>
        </div>

        <div class="provider-form-field">
          <label>API Key</label>
          <div class="credential-input-row"><el-input v-model="draft.api_key" type="password" show-password autocomplete="new-password" :placeholder="selected.configured ? `${selected.key_hint}（输入新 Key 可替换）` : '请输入 API Key'" /><el-button v-if="selected.credential_saved" plain type="danger" @click="removeCredential">删除凭据</el-button></div>
          <p class="provider-field-hint credential-hint"><span class="secure-check">✓</span> {{ selected.credential_saved ? `凭据已加密保存 · ${selected.key_hint}` : selected.configured ? '凭据由后端环境变量提供 ·••••' : '尚未配置凭据' }}；密钥不会返回前端或写入日志。</p>
        </div>

        <div class="provider-form-field model-field">
          <div class="field-label-row"><label>默认模型</label><el-button link type="primary" :loading="catalogLoading" @click="refreshCatalog">刷新模型目录</el-button></div>
          <el-select v-model="draft.default_model_id" filterable allow-create default-first-option clearable class="provider-select" placeholder="选择目录模型，或输入模型 ID">
            <el-option v-for="model in catalog" :key="model.id" :label="model.name === model.id ? model.id : `${model.name} · ${model.id}`" :value="model.id"><span>{{ model.name }}</span><small class="catalog-model-id">{{ model.id }}</small></el-option>
          </el-select>
          <p v-if="catalogError" class="provider-field-hint catalog-error">{{ catalogError }}</p>
          <p v-else-if="catalog.length" class="provider-field-hint">已从供应商实时加载 {{ catalog.length }} 个模型；目录刷新不会覆盖当前选择。</p>
          <p v-else class="provider-field-hint">模型目录尚未加载；可以直接手动输入模型 ID 后保存。</p>
        </div>
      </template>

      <footer class="provider-form-footer">
        <div class="provider-footer-status"><span class="live-status-dot" :class="{ disabled: !selected?.live_enabled }"></span><span>{{ selected?.live_enabled ? '真实执行已启用' : '真实执行已关闭' }}</span><small v-if="selected?.last_test_at">· 上次测试 {{ new Date(selected.last_test_at).toLocaleString() }}</small></div>
        <div class="provider-footer-actions">
          <el-button class="test-connection-button" :disabled="!selected?.live_enabled" :loading="testing" @click="test">测试连接</el-button>
          <el-button class="save-config-button" type="primary" :disabled="!draft || !draft.default_model_id.trim()" @click="save">保存配置</el-button>
        </div>
      </footer>
      <div v-if="temporaryTest" class="provider-test-result" :class="{ failed: !temporaryTest.ok }"><strong>{{ temporaryTest.ok ? '真实请求成功' : '真实请求失败' }}<template v-if="!temporaryTest.persisted"> · 尚未保存配置</template></strong><span>{{ temporaryTest.message }}</span></div>
    </section>
    </div>
    <section v-show="activeTab === 'default'" class="panel default-model-workspace">
      <div class="default-model-intro"><span class="provider-mark">✳</span><div><h2>默认模型</h2><p>设置工作流与评测在真实环境中读取的供应商和模型。</p></div></div>
      <div class="provider-form-field"><label>默认供应商</label><el-select v-model="selectedCode" class="provider-select" @change="temporaryTest = null"><el-option v-for="provider in configuredProviders" :key="provider.code" :label="provider.name" :value="provider.code"><span>{{ provider.name }}</span><small class="catalog-model-id">{{ provider.last_test_status === 'connected' ? '已验证' : '待验证' }}</small></el-option></el-select><p class="provider-field-hint">仅可从已配置供应商中选择默认项；未配置供应商请先在“供应商连接”中完成接入。</p></div>
      <div v-if="draft" class="provider-form-field"><label>默认模型 ID</label><el-select v-model="draft.default_model_id" filterable allow-create default-first-option class="provider-select" placeholder="选择已加载模型，或输入模型 ID"><el-option v-for="model in catalog" :key="model.id" :label="model.id" :value="model.id" /></el-select><div class="default-model-actions"><el-button :loading="catalogLoading" @click="refreshCatalog">刷新该供应商目录</el-button><el-button type="primary" :disabled="!draft.default_model_id.trim()" @click="save">保存默认模型</el-button></div><p v-if="catalogError" class="provider-field-hint catalog-error">{{ catalogError }}</p><p v-else class="provider-field-hint">保存沿用现有供应商配置接口，其他 AI 调用继续读取同一份后端默认设置。</p></div>
    </section>
  </div>
</template>

<style scoped>
.provider-console { max-width: 1440px; margin: 0 auto; }
.model-service-header { display:flex; align-items:center; justify-content:space-between; gap:20px; }
.model-service-kicker { color:var(--subtle); font:600 10px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace; letter-spacing:.1em; }
.provider-loading-hint { color:var(--subtle); font-family:inherit; font-size:10px; font-weight:400; letter-spacing:0; }
.model-service-header h1 { margin:5px 0 2px; color:var(--text); font-size:24px; line-height:1.3; font-weight:650; }
.model-service-header p { color:var(--subtle); font-size:13px; }
.model-service-actions { display:flex; gap:8px; }
.model-service-actions .el-button { height:38px; border-radius:8px; }
.model-service-tabs { display:flex; gap:26px; border-bottom:1px solid var(--line); margin-top:1px; }
.model-service-tabs button { position:relative; padding:11px 1px 12px; border:0; background:transparent; color:var(--subtle); font-family:inherit; font-size:13px; font-weight:500; cursor:pointer; }
.model-service-tabs button.active { color:var(--brand); font-weight:600; }
.model-service-tabs button.active::after { position:absolute; right:0; bottom:-1px; left:0; height:2px; background:var(--brand); content:''; }
.catalog-toolbar { display:flex; align-items:center; gap:9px; padding:12px; }
.model-search { min-width:220px; flex:1; }
.catalog-toolbar :deep(.el-input__wrapper),.catalog-toolbar :deep(.el-select__wrapper) { min-height:38px; border-radius:8px; box-shadow:0 0 0 1px var(--line) inset; }
.catalog-filter { width:145px; flex:none; }
.capability-filter { width:180px; }
.catalog-toolbar>.el-button { height:38px; border-radius:8px; }
.catalog-summary { display:flex; align-items:center; gap:18px; color:var(--subtle); font-size:12px; }
.catalog-summary strong { color:var(--text); font-size:13px; font-weight:600; }
.catalog-summary-note { margin-left:auto; font-size:11px; }
.model-catalog-panel { overflow:hidden; }
.catalog-table-head,.catalog-row { display:grid; grid-template-columns:minmax(200px,2.4fr) minmax(118px,1.2fr) 70px 82px 100px 84px; align-items:center; gap:10px; padding:0 15px; }
.catalog-table-head { min-height:40px; border-bottom:1px solid var(--line); background:var(--soft); color:var(--subtle); font-size:11px; font-weight:600; }
.catalog-row { min-height:70px; border-bottom:1px solid var(--line); color:var(--text); font-size:12px; }
.catalog-row:last-child { border-bottom:0; }
.catalog-model-cell { min-width:0; display:flex; flex-direction:column; gap:4px; }
.catalog-model-cell strong { overflow:hidden; color:var(--text); font-size:13px; font-weight:600; text-overflow:ellipsis; white-space:nowrap; }
.catalog-model-cell code { overflow:hidden; color:var(--subtle); font:11px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace; text-overflow:ellipsis; white-space:nowrap; }
.catalog-provider-cell { display:flex; align-items:center; gap:7px; min-width:0; color:var(--text); white-space:nowrap; }
.catalog-provider-mark { width:24px; height:24px; display:grid; place-items:center; flex:none; border:1px solid var(--line); border-radius:6px; background:var(--soft); color:var(--subtle); font-size:9px; font-weight:700; }
.catalog-unknown,.catalog-context { color:var(--subtle); font-variant-numeric:tabular-nums; }
.catalog-status { display:inline-flex; align-items:center; gap:6px; color:var(--subtle); font-size:11px; white-space:nowrap; }
.catalog-status i { width:7px; height:7px; border-radius:50%; background:#94a3b8; }
.catalog-status.connected { color:var(--success); }.catalog-status.connected i { background:var(--success); }
.catalog-status.failed { color:var(--danger); }.catalog-status.failed i { background:var(--danger); }
.catalog-status.pending { color:var(--subtle); }
.default-mark { display:inline-flex; align-items:center; gap:4px; color:var(--success); font-size:11px; }
.catalog-empty { min-height:230px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:8px; padding:24px; color:var(--subtle); text-align:center; font-size:12px; }
.catalog-empty strong { color:var(--text); font-size:14px; }
.catalog-empty .el-button { margin-top:5px; }
.catalog-errors { display:flex; flex-direction:column; gap:6px; padding:0 15px 10px; }
.catalog-errors div { display:flex; gap:8px; color:var(--danger); font-size:11px; }
.catalog-errors strong { flex:none; }
.catalog-pagination { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:9px 14px; border-top:1px solid var(--line); color:var(--subtle); font-size:11px; }
.catalog-pagination :deep(.el-pagination) { --el-pagination-button-bg-color:var(--panel); --el-pagination-hover-color:var(--brand); }
.catalog-table-footer { padding:10px 15px; border-top:1px solid var(--line); color:var(--subtle); font-size:11px; }
.security-popover-copy { color:var(--subtle); font-size:12px; line-height:1.65; }
.security-popover-copy p+p { margin-top:8px; }
.default-model-workspace { max-width:760px; margin:0 auto; padding:22px 8px 24px; }
.default-model-intro { display:flex; align-items:center; gap:12px; padding:0 17px 18px; border-bottom:1px solid var(--line); }
.default-model-intro h2 { color:var(--text); font-size:16px; }
.default-model-intro p { margin-top:3px; color:var(--subtle); font-size:12px; }
.default-model-actions { display:flex; gap:8px; margin-top:12px; }
.provider-content-layout { display: grid; grid-template-columns: 190px minmax(0,1fr); gap: 14px; align-items: start; justify-content: stretch; }
.provider-nav { padding: 10px; }
.provider-nav-heading { display: flex; align-items: center; justify-content: space-between; padding: 7px 6px 10px; color: var(--text); font-size: 13px; }
.provider-nav-heading small { color: var(--subtle); font-size: 11px; }
.provider-nav-item { width: 100%; min-height: 44px; display: flex; align-items: center; gap: 8px; padding: 5px 7px; border: 1px solid transparent; border-radius: 8px; background: transparent; color: var(--text); text-align: left; cursor: pointer; }
.provider-nav-item:hover { background: var(--soft); }
.provider-nav-item.active { background: color-mix(in srgb,var(--brand) 7%,var(--panel)); border-color: color-mix(in srgb,var(--brand) 22%,var(--line)); }
.provider-nav-mark { width: 28px; height: 28px; flex: 0 0 28px; display: grid; place-items: center; border: 1px solid var(--line); border-radius: 8px; background: var(--soft); color: var(--subtle); font-size: 9px; font-weight: 700; }
.provider-nav-item.active .provider-nav-mark { color: var(--brand); border-color: color-mix(in srgb,var(--brand) 24%,var(--line)); }
.provider-nav-copy { min-width: 0; flex: 1; display: flex; flex-direction: column; }
.provider-nav-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; font-weight: 600; }
.provider-nav-copy small { margin-top: 1px; color: var(--subtle); font-size: 10px; }
.provider-nav-state { color: var(--subtle); font-size: 9px; white-space: nowrap; }
.provider-nav-state.connected { color: var(--success); }
.provider-nav-state.connection_failed { color: var(--danger); }
.provider-workspace { width: 100%; margin: 6px 0 0; overflow: hidden; }
.provider-workspace-header { min-height: 90px; padding: 18px 20px; display: flex; align-items: center; justify-content: space-between; gap: 14px; border-bottom: 1px solid var(--line); }
.provider-heading-main { display: flex; align-items: center; gap: 11px; }
.provider-mark { width: 40px; height: 40px; display: inline-flex; align-items: center; justify-content: center; border: 1px solid var(--line); border-radius: 10px; background: var(--soft); color: var(--text); font-size: 20px; }
.provider-heading-main h1 { margin: 0; font-size: 21px; line-height: 1.35; font-weight: 650; color: var(--text); }
.provider-heading-main p { margin: 2px 0 0; color: var(--subtle); font-size: 13px; }
.provider-connection-state { flex: none; }
.provider-form-field { padding: 16px 17px 0; }
.provider-form-field label { display: block; margin-bottom: 6px; color: var(--subtle); font-size: 13px; font-weight: 600; }
.provider-form-field :deep(.el-input__wrapper),.provider-form-field :deep(.el-select__wrapper) { min-height: 40px; border-radius: 22px!important; padding-left: 14px; padding-right: 14px; }
.provider-form-field :deep(.el-input.is-disabled .el-input__wrapper) { background: var(--panel)!important; box-shadow: 0 0 0 1px var(--line) inset!important; cursor: default; }
.provider-form-field :deep(.el-input.is-disabled .el-input__inner) { -webkit-text-fill-color: var(--text); color: var(--text)!important; }
.provider-select { width: 100%; }
.provider-field-hint { margin: 4px 0 0; color: var(--subtle); font-size: 12px; line-height: 1.5; }
.option-unavailable { float: right; margin-left: 20px; color: var(--subtle); font-size: 12px; }
.credential-input-row { display: flex; align-items: center; gap: 8px; }
.credential-input-row .el-input { min-width: 0; flex: 1; }
.credential-input-row :deep(.el-input__wrapper) { border-radius: 22px 8px 8px 22px!important; }
.credential-input-row>.el-button { height: 40px; border-radius: 21px; }
.credential-hint { display: flex; align-items: center; gap: 5px; }
.secure-check { color: var(--success); font-weight: 700; }
.field-label-row { display: flex; align-items: center; justify-content: space-between; }
.field-label-row label { margin-bottom: 6px; }
.field-label-row .el-button { margin: 0 0 5px; font-size: 12px; }
.provider-form-footer { margin: 18px 17px 16px; padding-top: 14px; border-top: 1px solid var(--line); display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.provider-footer-status { display: flex; align-items: center; gap: 7px; color: var(--subtle); font-size: 12px; }
.provider-footer-status small { color: var(--subtle); font-size: 12px; }
.live-status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--success); }
.live-status-dot.disabled { background: var(--warning); }
.provider-footer-actions { display: flex; gap: 8px; }
.provider-footer-actions .el-button { min-width: 148px; height: 38px; border-radius: 20px; font-weight: 600; }
.provider-footer-actions .save-config-button { --el-button-bg-color: #1b1d21; --el-button-border-color: #1b1d21; --el-button-text-color: #fff; --el-button-disabled-bg-color: #777b84; --el-button-disabled-border-color: #777b84; }
:global(:root[data-theme='dark']) .provider-footer-actions .save-config-button { --el-button-bg-color: #e7ebf5; --el-button-border-color: #e7ebf5; --el-button-text-color: #171c2a; --el-button-disabled-bg-color: #42495a; --el-button-disabled-border-color: #42495a; }
.provider-test-result { display: flex; align-items: baseline; gap: 10px; margin: 0 17px 16px; padding: 10px 12px; color: var(--success); background: color-mix(in srgb,var(--success) 8%,var(--panel)); border-radius: 8px; font-size: 12px; }
.provider-test-result.failed { color: var(--danger); background: color-mix(in srgb,var(--danger) 8%,var(--panel)); }
.provider-test-result span { overflow-wrap: anywhere; }
.provider-unsupported { display: flex; flex-direction: column; gap: 4px; margin: 16px 17px 0; padding: 13px 14px; border: 1px solid var(--line); border-radius: 9px; background: var(--soft); color: var(--text); font-size: 13px; }
.provider-unsupported span { color: var(--subtle); font-size: 12px; }
.catalog-model-id { float: right; margin-left: 12px; color: var(--subtle); font-size: 11px; }
.catalog-error { color: var(--danger); }
@media(max-width: 1050px) { .catalog-table-head,.catalog-row { grid-template-columns:minmax(170px,2fr) minmax(100px,1fr) 45px 65px 88px 75px; gap:6px; padding:0 10px; } .capability-filter { display:none; } }
@media(max-width: 820px) { .provider-content-layout { grid-template-columns: 1fr; gap: 10px; } .provider-nav { display: flex; gap: 5px; align-items: center; overflow-x: auto; padding: 8px; } .provider-nav-heading { display: none; } .provider-nav-item { width: auto; min-width: 132px; flex: 0 0 auto; } }
@media(max-width: 640px) { .model-service-header { align-items:flex-start; flex-direction:column; gap:12px; }.model-service-actions { width:100%; }.model-service-actions .el-button { flex:1; }.model-service-tabs { gap:20px; }.catalog-toolbar { flex-wrap:wrap; }.model-search { flex:1 1 100%; }.catalog-filter { width:calc(50% - 5px); }.catalog-summary { flex-wrap:wrap; gap:7px 14px; }.catalog-summary-note { flex:1 1 100%; margin-left:0; }.catalog-table-head,.catalog-row { grid-template-columns:minmax(150px,2fr) minmax(90px,1fr) 68px; }.catalog-table-head span:nth-child(3),.catalog-table-head span:nth-child(4),.catalog-row>.catalog-unknown,.catalog-row>.catalog-context { display:none; }.catalog-table-head span:nth-child(5),.catalog-row>div:nth-child(5) { display:none; }.catalog-table-head span:nth-child(6),.catalog-row>div:nth-child(6) { text-align:right; }.provider-workspace { margin-top: 0; } .provider-workspace-header { min-height: 78px; padding: 14px; } .provider-heading-main h1 { font-size: 19px; } .provider-heading-main p { font-size: 12px; } .provider-form-field { padding: 14px 14px 0; } .provider-form-footer { margin: 16px 14px 14px; align-items: flex-start; flex-direction: column; } .provider-footer-actions { width: 100%; } .provider-footer-actions .el-button { min-width: 0; flex: 1; } .provider-test-result { margin: 0 14px 14px; flex-direction: column; gap: 2px; } }
</style>
