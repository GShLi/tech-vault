<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Activity,
  BarChart3,
  BookOpen,
  Boxes,
  ClipboardList,
  DatabaseZap,
  KeyRound,
  LogOut,
  MessageSquare,
  Search,
  Server,
  Settings,
  ScrollText,
  ShieldCheck,
  UserPlus,
  Users,
} from 'lucide-vue-next'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'

interface NavItem {
  to: string
  label: string
  icon: Component
  managerOnly?: boolean
  adminOnly?: boolean
}

const auth = useAuthStore()
const team = useTeamStore()
const route = useRoute()
const router = useRouter()

const roleLabels: Record<string, string> = {
  admin: '平台管理员',
  leader: '团队管理员',
  member: '成员',
  viewer: '只读成员',
}

const workspaceItems: NavItem[] = [
  { to: '/knowledge-bases', label: '知识库', icon: BookOpen },
  { to: '/chat', label: '问答', icon: MessageSquare },
  { to: '/chats', label: '会话历史', icon: ClipboardList },
  { to: '/tasks', label: '任务中心', icon: Activity },
  { to: '/chunks', label: 'Chunk 管理', icon: Boxes },
]

const governanceItems: NavItem[] = [
  { to: '/traces', label: '检索调试', icon: Search, managerOnly: true },
  { to: '/evaluations', label: '评测', icon: BarChart3, managerOnly: true },
  { to: '/settings', label: '设置', icon: Settings },
]

const adminItems: NavItem[] = [
  { to: '/admin/users', label: '用户管理', icon: UserPlus, adminOnly: true },
  { to: '/admin/audit', label: '全局审计', icon: ScrollText, adminOnly: true },
  { to: '/admin/model-policy', label: '全局模型策略', icon: ShieldCheck, adminOnly: true },
  { to: '/admin/model-providers', label: '供应商准入', icon: KeyRound, adminOnly: true },
  { to: '/admin/system', label: '系统状态', icon: Server, adminOnly: true },
]

function visible(item: NavItem): boolean {
  if (item.adminOnly && !auth.me?.user.is_super_admin) return false
  if (item.managerOnly && !team.canManage) return false
  return true
}

const pageTitle = computed(() => String(route.meta.title ?? 'TechVault'))

function onTeamChange(event: Event): void {
  const teamId = (event.target as HTMLSelectElement).value
  if (!teamId) return
  team.selectTeam(teamId)
  if (route.path === '/teams') router.push('/knowledge-bases')
}

function logout(): void {
  void auth.logout()
  team.clearTeam()
  router.push('/login')
}

function handleSessionExpired(): void {
  logout()
}

onMounted(async () => {
  window.addEventListener('techvault:session-expired', handleSessionExpired)
  if (auth.token && !auth.me) {
    try {
      await auth.loadMe()
      team.restore()
    } catch {
      auth.logout()
      router.push('/login')
    }
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('techvault:session-expired', handleSessionExpired)
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark"><BookOpen :size="20" /></div>
        <div class="brand-copy"><strong>TechVault</strong><span>典阁</span></div>
      </div>

      <div v-if="team.memberships.length" class="team-control">
        <label for="team-selector">当前团队</label>
        <select id="team-selector" data-testid="team-selector" :value="team.selectedTeamId ?? ''" @change="onTeamChange">
          <option value="" disabled>选择团队</option>
          <option v-for="membership in team.memberships" :key="membership.team_id" :value="membership.team_id">{{ membership.team_name }}</option>
        </select>
        <span v-if="team.currentMembership" class="team-role">{{ roleLabels[team.currentMembership.role] ?? team.currentMembership.role }}</span>
      </div>

      <nav class="nav" aria-label="主导航">
        <span class="nav-section-label">工作区</span>
        <RouterLink v-for="item in workspaceItems.filter(visible)" :key="item.to" :to="item.to" class="nav-link"><component :is="item.icon" :size="18" /><span>{{ item.label }}</span></RouterLink>
        <span class="nav-section-label">治理</span>
        <RouterLink v-for="item in governanceItems.filter(visible)" :key="item.to" :to="item.to" class="nav-link"><component :is="item.icon" :size="18" /><span>{{ item.label }}</span></RouterLink>
        <template v-if="auth.me?.user.is_super_admin">
          <span class="nav-section-label">平台管理</span>
          <RouterLink v-for="item in adminItems.filter(visible)" :key="item.to" :to="item.to" class="nav-link"><component :is="item.icon" :size="18" /><span>{{ item.label }}</span></RouterLink>
        </template>
        <span class="nav-section-label">团队</span>
        <RouterLink to="/teams" class="nav-link"><Users :size="18" /><span>团队选择</span></RouterLink>
      </nav>

      <div class="sidebar-footer">
        <div class="user-block"><span class="user-name">{{ auth.me?.user.display_name ?? '正在加载' }}</span><span class="user-email">{{ auth.me?.user.email ?? '' }}</span></div>
        <button class="icon-button sidebar-logout" data-testid="logout-button" type="button" title="退出登录" @click="logout"><LogOut :size="18" /></button>
      </div>
    </aside>

    <main class="main-panel">
      <header class="topbar">
        <div><h1>{{ pageTitle }}</h1><p v-if="team.currentMembership">{{ team.currentMembership.team_name }}</p></div>
        <div class="topbar-actions"><span v-if="team.canManage" class="role-pill">团队管理员</span><RouterLink v-if="team.canManage" class="icon-button" to="/settings/index-generations" title="索引管理"><DatabaseZap :size="18" /></RouterLink></div>
      </header>
      <section class="content"><router-view /></section>
    </main>
  </div>
</template>
