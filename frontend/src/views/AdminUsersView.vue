<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { Ban, RefreshCw, ShieldCheck, UserPlus } from 'lucide-vue-next'

import { api, ApiRequestError } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import type { AdminUser, Membership, Team } from '@/types/api'
import { formatDate, shortId } from '@/utils/format'

type TeamRole = 'leader' | 'member' | 'viewer'

const teams = ref<Team[]>([])
const users = ref<AdminUser[]>([])
const usersNextCursor = ref<string | null>(null)
const usersHasMore = ref(false)
const membershipRoles = ref<Record<string, TeamRole>>({})
const teamId = ref('')
const role = ref<TeamRole>('member')
const email = ref('')
const displayName = ref('')
const password = ref('')
const error = ref<ApiRequestError | null>(null)
const loadingUsers = ref(false)
const loadingMoreUsers = ref(false)
const saving = ref(false)
const actionKey = ref('')

function toApiError(caught: unknown): ApiRequestError {
  return caught instanceof ApiRequestError
    ? caught
    : new ApiRequestError(caught instanceof Error ? caught.message : '请求失败')
}

function membershipKey(userId: string, teamIdValue: string): string {
  return `${userId}:${teamIdValue}`
}

function setMembershipRoles(rows: AdminUser[]): void {
  rows.forEach((user) => {
    user.memberships.forEach((membership) => {
      membershipRoles.value[membershipKey(user.id, membership.team_id)] =
        membership.role as TeamRole
    })
  })
}

async function loadTeams(): Promise<void> {
  try {
    const page = await api.listTeams()
    teams.value = page.data
    if (!teamId.value && page.data.length) teamId.value = page.data[0].id
  } catch (caught) {
    error.value = toApiError(caught)
  }
}

async function loadUsers(reset = true): Promise<void> {
  if (reset) loadingUsers.value = true
  else loadingMoreUsers.value = true
  error.value = null
  try {
    const page = await api.listUsers(reset ? null : usersNextCursor.value)
    const rows = reset
      ? page.data
      : page.data.filter((item) => !users.value.some((user) => user.id === item.id))
    users.value = reset ? rows : [...users.value, ...rows]
    usersNextCursor.value = page.meta.next_cursor
    usersHasMore.value = page.meta.has_more
    setMembershipRoles(rows)
  } catch (caught) {
    error.value = toApiError(caught)
  } finally {
    if (reset) loadingUsers.value = false
    else loadingMoreUsers.value = false
  }
}

async function createUser(): Promise<void> {
  error.value = null
  saving.value = true
  try {
    await api.createUser({
      email: email.value.trim(),
      display_name: displayName.value.trim(),
      password: password.value,
      team_id: teamId.value,
      role: role.value,
    })
    Message.success('用户已创建')
    email.value = ''
    displayName.value = ''
    password.value = ''
    await loadUsers(true)
  } catch (caught) {
    error.value = toApiError(caught)
  } finally {
    saving.value = false
  }
}

async function toggleStatus(user: AdminUser): Promise<void> {
  if (user.is_builtin) return
  const key = `status:${user.id}`
  actionKey.value = key
  error.value = null
  try {
    await api.updateUser({
      user_id: user.id,
      status: user.status === 'active' ? 'disabled' : 'active',
    })
    Message.success(user.status === 'active' ? '账号已停用' : '账号已启用')
    await loadUsers(true)
  } catch (caught) {
    error.value = toApiError(caught)
  } finally {
    actionKey.value = ''
  }
}

async function saveMembershipRole(
  user: AdminUser,
  membership: Membership,
): Promise<void> {
  const key = membershipKey(user.id, membership.team_id)
  const nextRole = membershipRoles.value[key]
  if (!nextRole || nextRole === membership.role) return
  actionKey.value = `role:${key}`
  error.value = null
  try {
    await api.updateUser({
      user_id: user.id,
      team_id: membership.team_id,
      role: nextRole,
    })
    Message.success('团队角色已更新')
    await loadUsers(true)
  } catch (caught) {
    membershipRoles.value[key] = membership.role as TeamRole
    error.value = toApiError(caught)
  } finally {
    actionKey.value = ''
  }
}

onMounted(async () => {
  await Promise.all([loadTeams(), loadUsers(true)])
})
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>用户管理</h2>
        <p>创建平台用户、调整账号状态并分配已有团队的成员角色。</p>
      </div>
      <button class="secondary-button" type="button" :disabled="loadingUsers" @click="loadUsers(true)">
        <RefreshCw :size="16" />
        刷新
      </button>
    </div>

    <div v-if="error" class="error-banner" role="alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </div>

    <section class="panel detail-panel">
      <div class="detail-heading">
        <div class="detail-icon"><UserPlus :size="20" /></div>
        <div><h3>创建用户</h3><p>外部注册已关闭，账号只能由平台管理员开通。</p></div>
      </div>
      <form class="form-grid" @submit.prevent="createUser">
        <label class="field">
          <span>所属团队</span>
          <select v-model="teamId" data-testid="admin-user-team" required>
            <option value="" disabled>选择团队</option>
            <option v-for="team in teams" :key="team.id" :value="team.id">
              {{ team.name }}
            </option>
          </select>
        </label>
        <label class="field">
          <span>团队角色</span>
          <select v-model="role" data-testid="admin-user-role">
            <option value="leader">团队管理员</option>
            <option value="member">成员</option>
            <option value="viewer">只读成员</option>
          </select>
        </label>
        <label class="field">
          <span>显示名</span>
          <input v-model="displayName" data-testid="admin-user-name" type="text" required />
        </label>
        <label class="field">
          <span>邮箱</span>
          <input v-model="email" data-testid="admin-user-email" type="email" required />
        </label>
        <label class="field">
          <span>初始密码</span>
          <input v-model="password" data-testid="admin-user-password" type="password" minlength="8" required />
        </label>
        <div class="form-actions">
          <button class="primary-button" data-testid="admin-user-submit" type="submit" :disabled="saving || !teamId">
            <UserPlus :size="16" />
            {{ saving ? '创建中' : '创建用户' }}
          </button>
        </div>
      </form>
    </section>

    <section class="panel detail-panel">
      <div class="section-heading">
        <div><h3>平台用户</h3><span class="muted-text">{{ users.length }} 个已加载账号</span></div>
      </div>

      <div v-if="loadingUsers && !users.length" class="loading-state">正在加载用户...</div>
      <div v-else-if="users.length" class="table-wrap">
        <table>
          <thead>
            <tr><th>用户</th><th>状态</th><th>团队与角色</th><th>创建时间</th><th class="actions-column">操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td data-label="用户">
                <strong>{{ user.display_name }}</strong>
                <span class="cell-subtitle">{{ user.email }}</span>
                <span v-if="user.is_builtin" class="inline-badge"><ShieldCheck :size="13" />内置管理员</span>
              </td>
              <td data-label="状态"><StatusPill :status="user.status" /></td>
              <td data-label="团队与角色">
                <div v-if="user.memberships.length" class="membership-editor-list">
                  <div v-for="membership in user.memberships" :key="membership.team_id" class="membership-editor">
                    <span><strong>{{ membership.team_name }}</strong><small>{{ shortId(membership.team_id) }}</small></span>
                    <template v-if="!user.is_builtin">
                      <select
                        v-model="membershipRoles[membershipKey(user.id, membership.team_id)]"
                        :data-testid="`admin-user-role-${user.id}-${membership.team_id}`"
                      >
                        <option value="leader">团队管理员</option>
                        <option value="member">成员</option>
                        <option value="viewer">只读成员</option>
                      </select>
                      <button
                        class="ghost-button"
                        type="button"
                        :data-testid="`admin-user-role-save-${user.id}-${membership.team_id}`"
                        :disabled="actionKey === `role:${membershipKey(user.id, membership.team_id)}`"
                        @click="saveMembershipRole(user, membership)"
                      >
                        保存
                      </button>
                    </template>
                    <span v-else class="muted-text">{{ membership.role }}</span>
                  </div>
                </div>
                <span v-else class="muted-text">无团队成员关系</span>
              </td>
              <td data-label="创建时间">{{ formatDate(user.created_at) }}</td>
              <td data-label="操作" class="actions-column">
                <button
                  v-if="!user.is_builtin"
                  class="ghost-button"
                  :class="{ 'danger-text': user.status === 'active' }"
                  type="button"
                  :data-testid="`admin-user-${user.status === 'active' ? 'disable' : 'enable'}-${user.id}`"
                  :disabled="actionKey === `status:${user.id}`"
                  @click="toggleStatus(user)"
                >
                  <Ban :size="14" />
                  {{ user.status === 'active' ? '停用' : '启用' }}
                </button>
                <span v-else class="muted-text">受保护</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-state"><UserPlus :size="24" /><span>暂无用户</span></div>

      <div v-if="usersHasMore" class="load-more" data-testid="admin-users-load-more">
        <button class="secondary-button" type="button" :disabled="loadingMoreUsers" @click="loadUsers(false)">
          {{ loadingMoreUsers ? '加载中' : '加载更多' }}
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.membership-editor-list {
  display: grid;
  gap: 8px;
  min-width: 280px;
}

.membership-editor {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) 120px auto;
  align-items: center;
  gap: 8px;
}

.membership-editor > span:first-child {
  display: grid;
  gap: 2px;
}

.membership-editor small {
  color: var(--color-text-3);
}

.inline-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 8px;
  color: var(--color-primary-6);
  font-size: 12px;
}

@media (max-width: 720px) {
  .membership-editor {
    grid-template-columns: 1fr;
  }
}
</style>
