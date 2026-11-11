import { nextTick } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'

const routerBase = window.__BACMAP_ROUTER_BASE__ || '/console/'

const router = createRouter({
  history: createWebHistory(routerBase),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('./views/DashboardView.vue'),
      meta: { title: '仪表盘' },
    },
    {
      path: '/tasks',
      name: 'tasks',
      component: () => import('./views/TasksView.vue'),
      meta: { title: '任务' },
    },
    {
      path: '/tasks/:id',
      name: 'task-detail',
      component: () => import('./views/TaskDetailView.vue'),
      meta: { title: '任务详情' },
    },
    {
      path: '/plans',
      name: 'plans',
      component: () => import('./views/PlansView.vue'),
      meta: { title: '计划' },
    },
    {
      path: '/plans/:id',
      name: 'plan-detail',
      component: () => import('./views/PlanDetailView.vue'),
      meta: { title: '计划详情' },
    },
    {
      path: '/samples',
      name: 'samples',
      component: () => import('./views/SamplesView.vue'),
      meta: { title: '样本' },
    },
    {
      path: '/samples/:id',
      name: 'sample-detail',
      component: () => import('./views/SampleDetailView.vue'),
      meta: { title: '样本详情' },
    },
    {
      path: '/gom',
      name: 'gom',
      component: () => import('./views/GomView.vue'),
      meta: { title: 'GOM' },
    },
    {
      path: '/gom/:id',
      name: 'gom-detail',
      component: () => import('./views/GomDetailView.vue'),
      meta: { title: 'GOM 对象' },
    },
    {
      path: '/research',
      name: 'research',
      component: () => import('./views/ResearchView.vue'),
      meta: { title: '研究' },
    },
    {
      // v1.10.20：旧 Jinja 研究工具纳入控制台外壳（嵌入而非跳出）。
      path: '/research/workbench',
      name: 'research-workbench',
      component: () => import('./views/LegacyEmbedView.vue'),
      meta: {
        title: '高级研究工作台',
        hint: 'Study / Cohort / Claim 表单工作流（队列冻结、断言评审等）',
        legacyPath: '/research',
      },
    },
    {
      path: '/research/phylo',
      name: 'research-phylo',
      component: () => import('./views/LegacyEmbedView.vue'),
      meta: {
        title: '系统发育（BEAST 规格）',
        hint: 'alignment / 日期 / 分区 → BEAST XML 与验证',
        legacyPath: '/research/phylo',
      },
    },
    {
      path: '/research/stats',
      name: 'research-stats',
      component: () => import('./views/LegacyEmbedView.vue'),
      meta: {
        title: 'Logistic 关联分析',
        hint: 'P1 薄链路：本地 logistic（OR / CI / p 值）',
        legacyPath: '/research/stats',
      },
    },
    {
      path: '/research/studies/:id/package',
      name: 'research-study-package',
      component: () => import('./views/LegacyEmbedView.vue'),
      meta: {
        title: 'Study 打包',
        hint: '投稿包裹构建与下载',
        legacyPath: '/research/studies/:id/package',
      },
    },
    {
      path: '/research/studies/:id/workbench',
      name: 'research-study-workbench',
      component: () => import('./views/LegacyEmbedView.vue'),
      meta: {
        title: 'Study 操作台',
        hint: '队列 / 计划 / 断言 / 实验表单（服务端渲染工具）',
        legacyPath: '/research/studies/:id',
      },
    },
    {
      path: '/research/sessions/:id',
      name: 'research-session',
      component: () => import('./views/ResearchSessionView.vue'),
      meta: { title: '研究会话' },
    },
    {
      path: '/research/studies/:id',
      name: 'research-study',
      component: () => import('./views/ResearchStudyView.vue'),
      meta: { title: 'Study' },
    },
    {
      path: '/runs',
      name: 'runs',
      component: () => import('./views/RunsView.vue'),
      meta: { title: '运行记录' },
    },
    {
      path: '/runs/:id',
      name: 'run-detail',
      component: () => import('./views/RunDetailView.vue'),
      meta: { title: '运行详情' },
    },
    {
      path: '/records',
      name: 'records',
      component: () => import('./views/RecordsView.vue'),
      meta: { title: '数据记录' },
    },
    {
      path: '/overview',
      name: 'overview',
      component: () => import('./views/OverviewView.vue'),
      meta: { title: '系统概览' },
    },
    {
      path: '/search',
      name: 'search',
      component: () => import('./views/SearchView.vue'),
      meta: { title: '样本检索' },
    },
    {
      path: '/agent/:idx',
      name: 'agent-embed',
      component: () => import('./views/AgentEmbedView.vue'),
      meta: { title: '智能体对话' },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('./views/NotFoundView.vue'),
      meta: { title: '未找到' },
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  const title = (to.meta.title as string | undefined) ?? '控制台'
  document.title = `${title} · bacmap`
  void nextTick(() => {
    document.getElementById('main')?.focus({ preventScroll: true })
  })
})

export default router
