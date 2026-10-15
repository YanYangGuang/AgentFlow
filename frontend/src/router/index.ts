import { createRouter, createWebHistory } from 'vue-router'
const router = createRouter({ history: createWebHistory(), routes: [
  { path: '/', redirect: '/dashboard' }, { path: '/dashboard', component: () => import('../views/DashboardView.vue'), meta: { title: '工作台' } },
  { path: '/tasks', component: () => import('../views/TasksView.vue'), meta: { title: '任务中心' } },
  { path: '/runs', component: () => import('../views/RunsView.vue'), meta: { title: '运行追踪' } },
  { path: '/workflows', component: () => import('../views/WorkflowView.vue'), meta: { title: '流程编排' } },
  { path: '/settings/models', component: () => import('../views/ModelsSettingsView.vue'), meta: { title: '模型设置' } },
  { path: '/evaluations', component: () => import('../views/EvaluationsView.vue'), meta: { title: '评测中心' } },
  ...[['tools','工具管理'],['knowledge','知识库'],['settings','系统设置']].map(([path,title]) => ({ path: `/${path}`, component: () => import('../views/PlaceholderView.vue'), meta: { title } })),
] })
export default router
