<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { UserPlus } from 'lucide-vue-next'

import { api, ApiRequestError } from '@/api/client'
import type { Team } from '@/types/api'

const teams = ref<Team[]>([])
const teamId = ref('')
const role = ref<'leader' | 'member' | 'viewer'>('member')
const email = ref('')
const displayName = ref('')
const password = ref('')
const error = ref<ApiRequestError | null>(null)
const saving = ref(false)

async function loadTeams(): Promise<void> {
  try {
    const page = await api.listTeams()
    teams.value = page.data
    if (!teamId.value && page.data.length) {
      teamId.value = page.data[0].id
    }
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
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
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    saving.value = false
  }
}

onMounted(loadTeams)
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>用户管理</h2>
        <p>创建平台用户并分配团队角色。</p>
      </div>
    </div>

    <div v-if="error" class="error-banner" role="alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </div>

    <div class="panel" style="padding: 24px; max-width: 640px">
      <form class="form-stack" @submit.prevent="createUser">
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
          <input
            v-model="password"
            data-testid="admin-user-password"
            type="password"
            minlength="8"
            required
          />
        </label>
        <button class="primary-button" data-testid="admin-user-submit" type="submit" :disabled="saving">
          <UserPlus :size="16" />
          {{ saving ? '创建中' : '创建用户' }}
        </button>
      </form>
    </div>
  </div>
</template>
