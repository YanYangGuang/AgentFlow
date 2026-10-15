<script setup lang="ts">
import { Handle, Position, type NodeProps } from '@vue-flow/core'

interface AgentNodeData { kind: string; label: string; config: Record<string, unknown>; status?: string }
defineProps<NodeProps<AgentNodeData>>()
const nodeNames: Record<string, string> = { input: '输入', llm: 'LLM', tool: '工具', output: '输出' }
const nodeSymbols: Record<string, string> = { input: 'IN', llm: 'AI', tool: 'FX', output: 'OUT' }
</script>

<template>
  <div class="workflow-node" :class="[`kind-${data.kind}`, `state-${data.status || 'idle'}`]">
    <Handle v-if="data.kind !== 'input'" type="target" :position="Position.Left" />
    <div class="node-symbol">{{ nodeSymbols[data.kind] }}</div>
    <div class="node-copy"><small>{{ nodeNames[data.kind] }} 节点</small><strong>{{ data.label }}</strong></div>
    <span v-if="data.status && data.status !== 'idle'" class="node-state">{{ data.status }}</span>
    <Handle v-if="data.kind !== 'output'" type="source" :position="Position.Right" />
  </div>
</template>

<style scoped>
.workflow-node{position:relative;display:flex;align-items:center;gap:10px;width:205px;min-height:68px;padding:12px;border:1px solid var(--line);border-radius:11px;background:var(--panel);box-shadow:0 3px 12px rgba(24,36,62,.06);transition:border-color .16s,box-shadow .16s}.workflow-node:hover,.workflow-node.selected{border-color:var(--brand);box-shadow:0 0 0 2px rgba(82,103,245,.13)}.node-symbol{width:34px;height:34px;border-radius:9px;display:grid;place-items:center;background:rgba(82,103,245,.1);color:var(--brand);font-size:10px;font-weight:700;letter-spacing:.02em;flex:none}.kind-tool .node-symbol{color:#16866e;background:rgba(22,166,129,.1)}.kind-output .node-symbol{color:#9b6b1e;background:rgba(230,162,60,.13)}.node-copy{display:flex;min-width:0;flex-direction:column;line-height:1.4}.node-copy small{font-size:10px;color:var(--subtle)}.node-copy strong{font-size:12px;font-weight:600;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.node-state{font-size:9px;color:var(--subtle);margin-left:auto;text-transform:uppercase}.state-running{border-color:var(--brand)}.state-success{border-color:var(--success)}.state-failed{border-color:var(--danger)}:deep(.vue-flow__handle){width:9px;height:9px;background:var(--brand);border:2px solid var(--panel)}
</style>
