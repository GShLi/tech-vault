import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import AdminPolicyView from '@/views/AdminPolicyView.vue'
import AdminProvidersView from '@/views/AdminProvidersView.vue'
import AdminAuditView from '@/views/AdminAuditView.vue'
import AdminSystemView from '@/views/AdminSystemView.vue'
import AdminUsersView from '@/views/AdminUsersView.vue'
import AppShell from '@/views/AppShell.vue'
import AuditView from '@/views/AuditView.vue'
import ChatHistoryView from '@/views/ChatHistoryView.vue'
import ChatPage from '@/views/ChatPage.vue'
import ChunkDetailView from '@/views/ChunkDetailView.vue'
import ChunksView from '@/views/ChunksView.vue'
import DocumentDetailPage from '@/views/DocumentDetailPage.vue'
import DocumentUploadView from '@/views/DocumentUploadView.vue'
import DocumentVersionView from '@/views/DocumentVersionView.vue'
import EvaluationDetailView from '@/views/EvaluationDetailView.vue'
import EvaluationRunView from '@/views/EvaluationRunView.vue'
import EvaluationsView from '@/views/EvaluationsView.vue'
import GithubSourceView from '@/views/GithubSourceView.vue'
import IndexGenerationsView from '@/views/IndexGenerationsView.vue'
import InviteView from '@/views/InviteView.vue'
import KnowledgeBaseDetailView from '@/views/KnowledgeBaseDetailView.vue'
import KnowledgeBasePolicyView from '@/views/KnowledgeBasePolicyView.vue'
import KnowledgeBasesView from '@/views/KnowledgeBasesView.vue'
import LoginView from '@/views/LoginView.vue'
import MembersView from '@/views/MembersView.vue'
import ModelPolicyView from '@/views/ModelPolicyView.vue'
import ProvidersView from '@/views/ProvidersView.vue'
import SettingsView from '@/views/SettingsView.vue'
import TaskDetailView from '@/views/TaskDetailView.vue'
import TasksView from '@/views/TasksView.vue'
import TeamSettingsView from '@/views/TeamSettingsView.vue'
import TeamsView from '@/views/TeamsView.vue'
import TraceDetailView from '@/views/TraceDetailView.vue'
import TracesView from '@/views/TracesView.vue'

export const appRoutes: RouteRecordRaw[] = [
  {
    path: '/',
    component: AppShell,
    children: [
      { path: '', redirect: '/knowledge-bases' },
      { path: 'chat', name: 'chat', component: ChatPage, meta: { title: '问答' } },
      { path: 'chat/:chatId', name: 'chat-detail', component: ChatPage, meta: { title: '问答' } },
      { path: 'chats', name: 'chat-history', component: ChatHistoryView, meta: { title: '会话历史' } },
      { path: 'knowledge-bases', name: 'knowledge-bases', component: KnowledgeBasesView, meta: { title: '知识库' } },
      { path: 'knowledge-bases/:kbId', name: 'knowledge-base-detail', component: KnowledgeBaseDetailView, meta: { title: '知识库详情' } },
      { path: 'knowledge-bases/:kbId/settings', name: 'knowledge-base-policy', component: KnowledgeBasePolicyView, meta: { title: '知识库策略', managerOnly: true } },
      { path: 'knowledge-bases/:kbId/sources/github', name: 'github-source', component: GithubSourceView, meta: { title: 'GitHub 来源' } },
      { path: 'knowledge-bases/:kbId/upload', name: 'document-upload', component: DocumentUploadView, meta: { title: '上传文档' } },
      { path: 'documents/:documentId', name: 'document-detail', component: DocumentDetailPage, meta: { title: '文档详情' } },
      { path: 'documents/:documentId/versions/:versionId', name: 'document-version', component: DocumentVersionView, meta: { title: '文档版本' } },
      { path: 'tasks', name: 'tasks', component: TasksView, meta: { title: '任务中心' } },
      { path: 'tasks/:runId', name: 'task-detail', component: TaskDetailView, meta: { title: '任务详情' } },
      { path: 'chunks', name: 'chunks', component: ChunksView, meta: { title: 'Chunk 管理' } },
      { path: 'chunks/:chunkId', name: 'chunk-detail', component: ChunkDetailView, meta: { title: 'Chunk 详情' } },
      { path: 'traces', name: 'traces', component: TracesView, meta: { title: '检索调试', managerOnly: true } },
      { path: 'traces/:traceId', name: 'trace-detail', component: TraceDetailView, meta: { title: 'Trace 详情', managerOnly: true } },
      { path: 'evaluations', name: 'evaluations', component: EvaluationsView, meta: { title: '评测', managerOnly: true } },
      { path: 'evaluations/runs/:runId', name: 'evaluation-run', component: EvaluationRunView, meta: { title: '评测报告', managerOnly: true } },
      { path: 'evaluations/:datasetId', name: 'evaluation-detail', component: EvaluationDetailView, meta: { title: '黄金集详情', managerOnly: true } },
      { path: 'settings', name: 'settings', component: SettingsView, meta: { title: '设置' } },
      { path: 'settings/team', name: 'team-settings', component: TeamSettingsView, meta: { title: '团队资料' } },
      { path: 'settings/model-policy', name: 'model-policy', component: ModelPolicyView, meta: { title: '模型策略', managerOnly: true } },
      { path: 'settings/providers', name: 'providers', component: ProvidersView, meta: { title: '模型供应商', managerOnly: true } },
      { path: 'settings/audit', name: 'audit', component: AuditView, meta: { title: '审计日志', managerOnly: true } },
      { path: 'settings/members', name: 'members', component: MembersView, meta: { title: '成员管理' } },
      { path: 'settings/index-generations', name: 'index-generations', component: IndexGenerationsView, meta: { title: '索引管理', managerOnly: true } },
      { path: 'admin/users', name: 'admin-users', component: AdminUsersView, meta: { title: '用户管理', adminOnly: true } },
      { path: 'admin/audit', name: 'admin-audit', component: AdminAuditView, meta: { title: '全局审计', adminOnly: true } },
      { path: 'admin/audit/:auditId', name: 'admin-audit-detail', component: AdminAuditView, meta: { title: '审计详情', adminOnly: true } },
      { path: 'admin/model-policy', name: 'admin-model-policy', component: AdminPolicyView, meta: { title: '全局模型策略', adminOnly: true } },
      { path: 'admin/model-providers', name: 'admin-model-providers', component: AdminProvidersView, meta: { title: '供应商准入', adminOnly: true } },
      { path: 'admin/system', name: 'admin-system', component: AdminSystemView, meta: { title: '系统状态', adminOnly: true } },
      { path: 'members', name: 'members-legacy', component: MembersView, meta: { title: '成员管理' } },
      { path: 'teams', name: 'teams', component: TeamsView, meta: { title: '选择团队' } },
    ],
  },
  { path: '/login', name: 'login', component: LoginView, meta: { public: true, title: '登录' } },
  { path: '/invite/:token', name: 'invite', component: InviteView, meta: { public: true, title: '团队邀请' } },
  { path: '/:pathMatch(.*)*', redirect: '/knowledge-bases' },
]

const router = createRouter({
  history: createWebHistory(),
  routes: appRoutes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  const team = useTeamStore()

  if (to.meta.public) {
    if (auth.token) {
      try {
        await auth.loadMe()
        if (to.name === 'login') {
          return team.restore() ? '/knowledge-bases' : '/teams'
        }
      } catch {
        auth.logout()
      }
    }
    return true
  }

  if (!auth.token) return { path: '/login', query: { redirect: to.fullPath } }

  if (!auth.me) {
    try {
      await auth.loadMe()
    } catch {
      auth.logout()
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }

  team.restore()
  if (to.meta.adminOnly && !auth.me?.user.is_super_admin) return '/knowledge-bases'
  if (!team.selectedTeamId && to.path !== '/teams' && !to.meta.adminOnly) return '/teams'
  if (to.meta.managerOnly && !team.canManage) return '/knowledge-bases'
  return true
})

export default router
