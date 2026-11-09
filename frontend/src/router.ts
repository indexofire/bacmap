import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory('/console/'),
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
})

export default router
