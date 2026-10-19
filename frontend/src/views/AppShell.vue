<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { BookOpen, LogOut, MessageSquare, UserPlus, Users } from 'lucide-vue-next'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'

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

const pageTitle = computed(() => String(route.meta.title ?? 'TechVault'))

function onTeamChange(event: Event): void {
  const teamId = (event.target as HTMLSelectElement).value
  if (!teamId) {
    return
  }
  team.selectTeam(teamId)
  if (route.path === '/teams') {
    router.push('/knowledge-bases')
  }
}

function logout(): void {
  auth.logout()
  team.clearTeam()
  router.push('/login')
}

onMounted(async () => {
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
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark"><BookOpen :size="20" /></div>
        <div class="brand-copy">
          <strong>TechVault</strong>
          <span>典阁</span>
        </div>
      </div>

      <div v-if="team.memberships.length" class="team-control">
        <label for="team-selector">当前团队</label>
        <select
          id="team-selector"
          data-testid="team-selector"
          :value="team.selectedTeamId ?? ''"
          @change="onTeamChange"
        >
          <option value="" disabled>选择团队</option>
          <option
            v-for="membership in team.memberships"
            :key="membership.team_id"
            :value="membership.team_id"
          >
            {{ membership.team_name }}
          </option>
        </select>
        <span v-if="team.currentMembership" class="team-role">
          {{ roleLabels[team.currentMembership.role] ?? team.currentMembership.role }}
        </span>
      </div>

      <nav class="nav" aria-label="主导航">
        <RouterLink to="/knowledge-bases" class="nav-link">
          <BookOpen :size="18" />
          <span>知识库</span>
        </RouterLink>
        <RouterLink to="/chat" class="nav-link">
          <MessageSquare :size="18" />
          <span>问答</span>
        </RouterLink>
        <RouterLink to="/teams" class="nav-link">
          <Users :size="18" />
          <span>团队</span>
        </RouterLink>
        <RouterLink
          v-if="auth.me?.user.is_super_admin"
          to="/admin/users"
          class="nav-link"
        >
          <UserPlus :size="18" />
          <span>用户管理</span>
        </RouterLink>
      </nav>

      <div class="sidebar-footer">
        <div class="user-block">
          <span class="user-name">{{ auth.me?.user.display_name ?? '正在加载' }}</span>
          <span class="user-email">{{ auth.me?.user.email ?? '' }}</span>
        </div>
        <button
          class="icon-button sidebar-logout"
          data-testid="logout-button"
          type="button"
          title="退出登录"
          @click="logout"
        >
          <LogOut :size="18" />
        </button>
      </div>
    </aside>

    <main class="main-panel">
      <header class="topbar">
        <div>
          <h1>{{ pageTitle }}</h1>
          <p v-if="team.currentMembership">{{ team.currentMembership.team_name }}</p>
        </div>
        <span v-if="team.canManage" class="role-pill">可管理</span>
      </header>
      <section class="content">
        <router-view />
      </section>
    </main>
  </div>
</template>
