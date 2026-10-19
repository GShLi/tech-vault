<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Plus, Users } from 'lucide-vue-next'

import { api, ApiRequestError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'

const auth = useAuthStore()
const team = useTeamStore()
const router = useRouter()

const showCreate = ref(false)
const name = ref('')
const description = ref('')
const creating = ref(false)
const error = ref<ApiRequestError | null>(null)

const memberships = computed(() => auth.me?.memberships ?? [])
const roleLabels: Record<string, string> = {
  admin: '平台管理员',
  leader: '团队管理员',
  member: '成员',
  viewer: '只读成员',
}

function enterTeam(teamId: string): void {
  team.selectTeam(teamId)
  router.push('/knowledge-bases')
}

async function createTeam(): Promise<void> {
  error.value = null
  creating.value = true
  try {
    const created = await api.createTeam({
      name: name.value.trim(),
      description: description.value.trim() || null,
    })
    await auth.loadMe()
    team.selectTeam(created.id)
    name.value = ''
    description.value = ''
    showCreate.value = false
    router.push('/knowledge-bases')
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <p>当前账号可访问的团队与角色。</p>
      </div>
      <button
        v-if="auth.me?.user.is_super_admin"
        class="secondary-button"
        data-testid="team-create-open"
        type="button"
        @click="showCreate = true"
      >
        <Plus :size="16" />
        创建团队
      </button>
    </div>

    <div v-if="error" class="error-banner" role="alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </div>

    <div v-if="memberships.length" class="team-grid">
      <article
        v-for="membership in memberships"
        :key="membership.team_id"
        class="team-card"
      >
        <div class="team-card-heading">
          <div class="team-icon"><Users :size="18" /></div>
          <div>
            <h3>{{ membership.team_name }}</h3>
            <span class="muted-text">{{ roleLabels[membership.role] ?? membership.role }}</span>
          </div>
        </div>
        <button
          class="ghost-button"
          type="button"
          data-testid="team-card-enter"
          @click="enterTeam(membership.team_id)"
        >
          进入团队
          <ArrowRight :size="16" />
        </button>
      </article>
    </div>
    <div v-else class="panel empty-state">
      <Users :size="28" />
      <h3>还没有加入团队</h3>
      <p>
        {{ auth.me?.user.is_super_admin ? '创建一个团队后即可开始管理知识库。' : '请联系平台管理员创建团队。' }}
      </p>
    </div>

    <div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false">
      <div class="modal-panel">
        <div class="modal-heading">
          <h3>创建团队</h3>
          <button class="icon-button" type="button" title="关闭" @click="showCreate = false">
            ×
          </button>
        </div>
        <form class="form-stack" @submit.prevent="createTeam">
          <label class="field">
            <span>团队名称</span>
            <input
              v-model="name"
              data-testid="team-name-input"
              type="text"
              required
              placeholder="例如：平台工程"
            />
          </label>
          <label class="field">
            <span>描述</span>
            <textarea v-model="description" rows="3" placeholder="团队技术资料范围" />
          </label>
          <div class="modal-actions">
            <button class="ghost-button" type="button" @click="showCreate = false">
              取消
            </button>
            <button
              class="primary-button"
              data-testid="team-create-submit"
              type="submit"
              :disabled="creating"
            >
              {{ creating ? '创建中' : '创建团队' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
