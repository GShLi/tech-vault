import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import AppShell from '@/views/AppShell.vue'
import ChatView from '@/views/ChatView.vue'
import KnowledgeBasesView from '@/views/KnowledgeBasesView.vue'
import LoginView from '@/views/LoginView.vue'
import RegisterView from '@/views/RegisterView.vue'
import TeamsView from '@/views/TeamsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: LoginView,
      meta: { public: true, title: '登录' },
    },
    {
      path: '/register',
      name: 'register',
      component: RegisterView,
      meta: { public: true, title: '注册' },
    },
    {
      path: '/',
      component: AppShell,
      children: [
        {
          path: '',
          redirect: '/knowledge-bases',
        },
        {
          path: 'chat',
          name: 'chat',
          component: ChatView,
          meta: { title: '知识库问答' },
        },
        {
          path: 'knowledge-bases',
          name: 'knowledge-bases',
          component: KnowledgeBasesView,
          meta: { title: '知识库' },
        },
        {
          path: 'teams',
          name: 'teams',
          component: TeamsView,
          meta: { title: '选择团队' },
        },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/knowledge-bases',
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  const team = useTeamStore()

  if (to.meta.public) {
    if (auth.token) {
      try {
        await auth.loadMe()
        return team.restore() ? '/knowledge-bases' : '/teams'
      } catch {
        auth.logout()
      }
    }
    return true
  }

  if (!auth.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (!auth.me) {
    try {
      await auth.loadMe()
    } catch {
      auth.logout()
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }

  team.restore()
  if (!team.selectedTeamId && to.path !== '/teams') {
    return '/teams'
  }
  return true
})

export default router
