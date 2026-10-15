import { defineStore } from 'pinia'
import { api } from '../api/client'

export interface RuntimeState { mode: 'demo' | 'live'; live_execution_enabled: boolean; model_configured: boolean; provider: string; model: string }

export const useRuntimeStore = defineStore('runtime', {
  state: () => ({ mode: 'demo' as 'demo' | 'live', live_execution_enabled: false, model_configured: false, provider: '', model: '', loaded: false, switching: false }),
  getters: {
    isLive: state => state.mode === 'live',
    modeLabel: state => state.mode === 'live' ? '真实环境' : '安全沙盒',
    modeCaption: state => state.mode === 'live' ? '真实模型 · 可能产生费用' : '安全沙盒 · 不调用真实模型',
  },
  actions: {
    apply(payload: RuntimeState) { this.mode = payload.mode; this.live_execution_enabled = payload.live_execution_enabled; this.model_configured = payload.model_configured; this.provider = payload.provider; this.model = payload.model; this.loaded = true },
    async load() { const { data } = await api.get<RuntimeState>('/system/runtime'); this.apply(data) },
    async setMode(mode: 'demo' | 'live') { this.switching = true; try { const { data } = await api.put<RuntimeState>('/system/runtime/mode', { mode }); this.apply(data) } finally { this.switching = false } },
  },
})
