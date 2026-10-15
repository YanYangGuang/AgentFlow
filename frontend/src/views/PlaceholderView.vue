<script setup lang="ts">
import { useRoute } from 'vue-router'
import { ArrowRight, Connection } from '@element-plus/icons-vue'
const route = useRoute()
</script>
<template>
  <div class="content-page"><div class="page-header"><div><div class="eyebrow">AGENTFLOW WORKSPACE</div><h1>{{ route.meta.title }}</h1><p>此模块将按 AgentFlow V1.0 里程碑逐步接入可追踪的后端能力。</p></div></div><section class="panel placeholder-card"><div class="placeholder-icon"><el-icon><Connection /></el-icon></div><h2>{{ route.meta.title }}模块正在建设中</h2><p>当前阶段先交付工作台、任务中心与流程编排。此页面尚未连接实际数据或执行能力。</p><el-button type="primary" plain @click="$router.push('/dashboard')">返回工作台 <el-icon><ArrowRight /></el-icon></el-button></section></div>
</template>
