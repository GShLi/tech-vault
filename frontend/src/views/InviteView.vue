<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, LogIn, ShieldCheck, Users } from 'lucide-vue-next'

import { api, ApiRequestError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import type { InvitationView } from '@/types/api'
import { formatDate } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const team = useTeamStore()

const invitation = ref<InvitationView | null>(null)
const loading = ref(true)
const accepting = ref(false)
const accepted = ref(false)
const error = ref<ApiRequestError | null>(null)

const token = computed(() =>
  typeof route.params.token === 'string' ? route.params.token : '',
)
const roleLabels: Record<string, string> = {
  leader: '团队管理员',
  member: '普通成员',
  viewer: '只读成员',
}
const canAccept = computed(
  () =>
    Boolean(auth.token) &&
    invitation.value?.status === 'pending' &&
    auth.me?.user.email.toLowerCase() === invitation.value?.email.toLowerCase() &&
    !accepted.value,
)
const emailMismatch = computed(
  () =>
    Boolean(auth.me) &&
    invitation.value?.status === 'pending' &&
    auth.me?.user.email.toLowerCase() !== invitation.value?.email.toLowerCase(),
)

function toApiError(caught: unknown): ApiRequestError {
  return caught instanceof ApiRequestError
    ? caught
    : new ApiRequestError('邀请操作失败，请稍后重试。', 'UNKNOWN_ERROR')
}

async function loadInvitation(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    invitation.value = await api.getInvitation(token.value)
  } catch (caught) {
    error.value = toApiError(caught)
  } finally {
    loading.value = false
  }
}

function loginToAccept(): void {
  router.push({ path: '/login', query: { redirect: `/invite/${token.value}` } })
}

async function acceptInvitation(): Promise<void> {
  if (!canAccept.value) return
  accepting.value = true
  error.value = null
  try {
    const membership = await api.acceptInvitation(token.value)
    await auth.loadMe()
    team.selectTeam(membership.team_id)
    accepted.value = true
    await loadInvitation()
    await router.push('/knowledge-bases')
  } catch (caught) {
    error.value = toApiError(caught)
  } finally {
    accepting.value = false
  }
}

onMounted(loadInvitation)
</script>

<template>
  <div class="auth-page">
    <div class="auth-panel invite-panel">
      <div class="auth-brand">
        <div class="brand-mark"><ShieldCheck :size="22" /></div>
        <div>
          <strong>TechVault 典阁</strong>
          <span>团队技术知识库</span>
        </div>
      </div>

      <div v-if="loading" class="loading-state">正在读取邀请信息...</div>
      <div v-else-if="error && !invitation" class="error-banner" role="alert">
        <strong>{{ error.message }}</strong>
        <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
      </div>
      <template v-else-if="invitation">
        <div class="invite-heading">
          <Users :size="28" />
          <div>
            <p>{{ accepted ? '已加入团队' : '团队邀请' }}</p>
            <h1>{{ invitation.team_name }}</h1>
          </div>
        </div>

        <dl class="invite-facts">
          <div><dt>受邀邮箱</dt><dd>{{ invitation.email }}</dd></div>
          <div><dt>分配角色</dt><dd>{{ roleLabels[invitation.role] ?? invitation.role }}</dd></div>
          <div><dt>邀请状态</dt><dd>{{ invitation.status }}</dd></div>
          <div><dt>有效期至</dt><dd>{{ formatDate(invitation.expires_at) }}</dd></div>
        </dl>

        <div v-if="error" class="error-banner" role="alert">
          <strong>{{ error.message }}</strong>
          <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
        </div>

        <div v-if="accepted" class="success-banner">
          <strong>邀请已接受</strong>
          <span>你已加入 {{ invitation.team_name }}。</span>
        </div>
        <button
          v-if="accepted"
          class="primary-button"
          type="button"
          @click="router.push('/knowledge-bases')"
        >
          进入知识库
          <ArrowRight :size="17" />
        </button>

        <div v-else-if="invitation.status !== 'pending'" class="notice-banner">
          该邀请当前状态为 {{ invitation.status }}，无法再次接受。
        </div>
        <div v-else-if="!auth.token" class="invite-actions">
          <p class="muted-text">请使用受邀邮箱对应的账号登录后接受邀请。</p>
          <button class="primary-button" type="button" @click="loginToAccept">
            <LogIn :size="17" />
            登录并继续
          </button>
        </div>
        <div v-else-if="emailMismatch" class="error-banner" role="alert">
          <strong>当前账号与受邀邮箱不一致</strong>
          <span>请退出后使用 {{ invitation.email }} 登录。</span>
        </div>
        <button
          v-else
          class="primary-button"
          data-testid="invite-accept"
          type="button"
          :disabled="accepting"
          @click="acceptInvitation"
        >
          {{ accepting ? '正在加入' : '接受邀请' }}
          <ArrowRight :size="17" />
        </button>
      </template>

      <RouterLink class="auth-link" to="/login">返回登录</RouterLink>
    </div>
  </div>
</template>
