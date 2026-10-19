import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import AppShell from '@/views/AppShell.vue'
import ChatPage from '@/views/ChatPage.vue'
import DocumentDetailPage from '@/views/DocumentDetailPage.vue'
import DocumentUploadView from '@/views/DocumentUploadView.vue'
import MembersView from '@/views/MembersView.vue'
import KnowledgeBasesView from '@/views/KnowledgeBasesView.vue'
import LoginView from '@/views/LoginView.vue'
import RegisterView from '@/views/RegisterView.vue'
import SettingsView from '@/views/SettingsView.vue'
import TeamsView from '@/views/TeamsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView, meta: { public: true, title: '登录' } },
    { path: '/register', name: 'register', component: RegisterView, meta: { public: true, title: '注册' } },
    {
      path: '/',
      component: AppShell,
      children: [
        { path: '', redirect: '/knowledge-bases' },
        { path: 'chat', name: 'chat', component: ChatPage, meta: { title: '对话' } },
        { path: 'knowledge-bases', name: 'knowledge-bases', component: KnowledgeBasesView, meta: { title: '知识库' } },
        { path: 'knowledge-bases/:kbId/upload', name: 'document-upload', component: DocumentUploadView, meta: { title: '上传文档' } },
        { path: 'documents/:documentId', name: 'document-detail', component: DocumentDetailPage, meta: { title: '文档详情' } },
        { path: 'settings', name: 'settings', component: SettingsView, meta: { title: '设置' } },
        { path: 'members', name: 'members', component: MembersView, meta: { title: '成员管理' } },
        { path: 'teams', name: 'teams', component: TeamsView, meta: { title: '选择团队' } },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/knowledge-bases' },
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

  if (!auth.token) return { path: '/login', query: { redirect: to.fullPath } }

  if (!auth.me) {
    try { await auth.loadMe() } catch { auth.logout(); return { path: '/login', query: { redirect: to.fullPath } } }
  }

  team.restore()
  if (!team.selectedTeamId && to.path !== '/teams') return '/teams'
  return true
})

export default router
