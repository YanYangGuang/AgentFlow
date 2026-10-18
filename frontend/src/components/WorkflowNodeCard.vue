<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position, type NodeProps } from '@vue-flow/core'

interface AgentNodeData { kind: string; label: string; config: Record<string, unknown>; status?: string }
const props = defineProps<NodeProps<AgentNodeData>>()
const nodeNames: Record<string, string> = { input: '输入', llm: 'LLM', tool: '工具', output: '输出' }
const nodeSymbols: Record<string, string> = { input: 'IN', llm: 'AI', tool: 'FX', output: 'OUT' }
const stateNames: Record<string, string> = { idle: '待运行', queued: '排队中', running: '运行中', success: '已完成', succeeded: '已完成', failed: '失败', skipped: '已跳过' }
const stateClass = computed(() => props.data.status === 'succeeded' ? 'success' : props.data.status || 'idle')
const stateLabel = computed(() => stateNames[props.data.status || 'idle'] || props.data.status || '待运行')
</script>

<template>
  <div class="workflow-node" :class="[`kind-${data.kind}`, `state-${stateClass}`]">
    <Handle v-if="data.kind !== 'input'" type="target" :position="Position.Left" />
    <div class="node-symbol">{{ nodeSymbols[data.kind] }}</div>
    <div class="node-copy"><small>{{ nodeNames[data.kind] }} 节点</small><strong>{{ data.label }}</strong></div>
    <span class="node-state" :class="`state-label-${stateClass}`"><i />{{ stateLabel }}</span>
    <Handle v-if="data.kind !== 'output'" type="source" :position="Position.Right" />
  </div>
</template>

<style scoped>
.workflow-node{position:relative;display:flex;align-items:center;gap:10px;width:218px;min-height:72px;padding:12px;border:1px solid var(--line);border-radius:12px;background:var(--panel-raised);box-shadow:var(--shadow-node);transition:border-color var(--motion-fast) var(--ease-standard),box-shadow var(--motion-fast) var(--ease-standard),transform var(--motion-fast) var(--ease-standard)}.workflow-node:hover,.workflow-node.selected{border-color:var(--brand);box-shadow:0 0 0 2px var(--accent-soft),var(--shadow-node)}.workflow-node.selected{transform:translateY(-1px)}.node-symbol{width:35px;height:35px;border-radius:9px;display:grid;place-items:center;background:var(--accent-soft);color:var(--brand);font-size:10px;font-weight:700;letter-spacing:.02em;flex:none}.kind-tool .node-symbol{color:#16866e;background:color-mix(in srgb,#16866e 11%,transparent)}.kind-output .node-symbol{color:#b97a1b;background:color-mix(in srgb,#b97a1b 12%,transparent)}.node-copy{display:flex;min-width:0;flex:1;flex-direction:column;line-height:1.4}.node-copy small{font-size:9px;color:var(--subtle)}.node-copy strong{font-size:11px;font-weight:600;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.node-state{display:flex;align-items:center;gap:4px;margin-left:auto;font-size:8px;color:var(--subtle);white-space:nowrap}.node-state i{width:5px;height:5px;border-radius:50%;background:currentColor}.state-running{border-color:var(--brand)}.state-running .node-state{color:var(--brand)}.state-running .node-state i{animation:state-pulse 1.2s ease-in-out infinite}.state-success{border-color:color-mix(in srgb,var(--success) 60%,var(--line))}.state-success .node-state,.state-label-success{color:var(--success)}.state-failed{border-color:color-mix(in srgb,var(--danger) 65%,var(--line))}.state-failed .node-state,.state-label-failed{color:var(--danger)}.state-queued .node-state{color:var(--warning)}.state-skipped .node-state{color:var(--subtle)}:deep(.vue-flow__handle){width:9px;height:9px;background:var(--brand);border:2px solid var(--panel-raised)}@keyframes state-pulse{50%{opacity:.38}}:global(:root[data-motion=off]) .state-running .node-state i{animation:none!important}@media(prefers-reduced-motion:reduce){.state-running .node-state i{animation:none!important}}
</style>
