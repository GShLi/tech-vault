<script setup lang="ts">
import {
  ApiRequestError,
  api,
  normalizeApiError as toApiError,
} from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Empty as AEmpty,
  Form as AForm,
  FormItem as AFormItem,
  Input as AInput,
  InputPassword as AInputPassword,
  Message,
  Option as AOption,
  Select as ASelect,
  Table as ATable,
  TableColumn as ATableColumn,
  Tag as ATag,
} from '@arco-design/web-vue'

import { onMounted, ref } from 'vue'

import { Ban, RefreshCw, ShieldCheck, UserPlus } from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import type { AdminUser, Membership, Team } from '@/types/api'
import { formatDate, shortId, statusLabel } from '@/utils/format'

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
      : page.data.filter(
          (item) => !users.value.some((user) => user.id === item.id),
        )
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
      <a-button
        :disabled="loadingUsers"
        @click="loadUsers(true)"
        type="secondary"
        html-type="button"
      >
        <RefreshCw :size="16" />
        刷新
      </a-button>
    </div>

    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </a-alert>

    <a-card class="page-card">
      <div class="detail-heading">
        <div class="detail-icon"><UserPlus :size="20" /></div>
        <div>
          <h3>创建用户</h3>
          <p>外部注册已关闭，账号只能由平台管理员开通。</p>
        </div>
      </div>
      <a-form
        class="form-grid"
        :model="{ teamId, role, displayName, email, password }"
        layout="vertical"
        @submit-success="createUser"
      >
        <a-form-item
          field="teamId"
          :rules="[{ required: true, message: '请填写所属团队' }]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>所属团队</template>
          <a-select v-model="teamId" data-testid="admin-user-team">
            <a-option value="" disabled>选择团队</a-option>
            <a-option v-for="team in teams" :key="team.id" :value="team.id">
              {{ team.name }}
            </a-option>
          </a-select>
        </a-form-item>
        <a-form-item field="role">
          <template #label>团队角色</template>
          <a-select v-model="role" data-testid="admin-user-role">
            <a-option value="leader">团队管理员</a-option>
            <a-option value="member">成员</a-option>
            <a-option value="viewer">只读成员</a-option>
          </a-select>
        </a-form-item>
        <a-form-item
          field="displayName"
          :rules="[{ required: true, message: '请填写显示名' }]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>显示名</template>
          <a-input
            v-model="displayName"
            data-testid="admin-user-name"
            type="text"
            :input-attrs="{ required: true }"
          ></a-input>
        </a-form-item>
        <a-form-item
          field="email"
          :rules="[
            { required: true, message: '请填写邮箱' },
            { type: 'email', message: '请输入有效的邮箱地址' },
          ]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>邮箱</template>
          <a-input
            v-model="email"
            data-testid="admin-user-email"
            type="text"
            :input-attrs="{ required: true }"
          ></a-input>
        </a-form-item>
        <a-form-item
          field="password"
          :rules="[
            { required: true, message: '请填写初始密码' },
            { minLength: 8, message: '至少输入 8 个字符' },
          ]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>初始密码</template>
          <a-input-password
            v-model="password"
            data-testid="admin-user-password"
            :input-attrs="{ required: true, minlength: '8' }"
          ></a-input-password>
        </a-form-item>
        <div class="form-actions">
          <a-button
            data-testid="admin-user-submit"
            :disabled="saving || !teamId"
            type="primary"
            html-type="submit"
          >
            <UserPlus :size="16" />
            {{ saving ? '创建中' : '创建用户' }}
          </a-button>
        </div>
      </a-form>
    </a-card>

    <a-card class="page-card">
      <div class="section-heading">
        <div>
          <h3>平台用户</h3>
          <span class="muted-text">{{ users.length }} 个已加载账号</span>
        </div>
      </div>
      <div v-if="loadingUsers && !users.length" class="loading-state">
        正在加载用户...
      </div>
      <div v-else-if="users.length" class="table-wrap">
        <a-table
          :data="users"
          :pagination="false"
          row-key="id"
          :bordered="false"
          :scroll="{ x: 960 }"
        >
          <template #columns>
            <a-table-column title="用户">
              <template #cell="{ record: user }">
                <strong>{{ user.display_name }}</strong>
                <span class="cell-subtitle">{{ user.email }}</span>
                <span v-if="user.is_builtin" class="inline-badge">
                  <ShieldCheck :size="13" />
                  内置管理员
                </span>
              </template>
            </a-table-column>
            <a-table-column title="状态" :width="100">
              <template #cell="{ record: user }">
                <a-tag :color="statusColor(user.status)">
                  {{ statusLabel(user.status) }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column title="团队与角色">
              <template #cell="{ record: user }">
                <div
                  v-if="user.memberships.length"
                  class="membership-editor-list"
                >
                  <div
                    v-for="membership in user.memberships"
                    :key="membership.team_id"
                    class="membership-editor"
                  >
                    <span>
                      <strong>{{ membership.team_name }}</strong>
                      <small>{{ shortId(membership.team_id) }}</small>
                    </span>
                    <template v-if="!user.is_builtin">
                      <a-select
                        v-model="
                          membershipRoles[
                            membershipKey(user.id, membership.team_id)
                          ]
                        "
                        :data-testid="`admin-user-role-${user.id}-${membership.team_id}`"
                      >
                        <a-option value="leader">团队管理员</a-option>
                        <a-option value="member">成员</a-option>
                        <a-option value="viewer">只读成员</a-option>
                      </a-select>
                      <a-button
                        :data-testid="`admin-user-role-save-${user.id}-${membership.team_id}`"
                        :disabled="
                          actionKey ===
                          `role:${membershipKey(user.id, membership.team_id)}`
                        "
                        @click="saveMembershipRole(user, membership)"
                        type="text"
                        html-type="button"
                      >
                        保存
                      </a-button>
                    </template>
                    <span v-else class="muted-text">{{ membership.role }}</span>
                  </div>
                </div>
                <span v-else class="muted-text">无团队成员关系</span>
              </template>
            </a-table-column>
            <a-table-column title="创建时间" :width="180">
              <template #cell="{ record: user }">
                {{ formatDate(user.created_at) }}
              </template>
            </a-table-column>
            <a-table-column title="操作" :width="180">
              <template #cell="{ record: user }">
                <a-button
                  v-if="!user.is_builtin"
                  :class="{ 'danger-text': user.status === 'active' }"
                  :data-testid="`admin-user-${user.status === 'active' ? 'disable' : 'enable'}-${user.id}`"
                  :disabled="actionKey === `status:${user.id}`"
                  @click="toggleStatus(user)"
                  type="text"
                  html-type="button"
                >
                  <Ban :size="14" />
                  {{ user.status === 'active' ? '停用' : '启用' }}
                </a-button>
                <span v-else class="muted-text">受保护</span>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </div>
      <a-empty v-else class="page-empty">
        <template #image><UserPlus :size="24" /></template>
        <span>暂无用户</span>
      </a-empty>
      <div
        v-if="usersHasMore"
        class="load-more"
        data-testid="admin-users-load-more"
      >
        <a-button
          :disabled="loadingMoreUsers"
          @click="loadUsers(false)"
          type="secondary"
          html-type="button"
        >
          {{ loadingMoreUsers ? '加载中' : '加载更多' }}
        </a-button>
      </div>
    </a-card>
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
