<script setup lang="ts">
import {
  ApiRequestError,
  api,
  normalizeApiError as toApiError,
} from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Descriptions as ADescriptions,
  DescriptionsItem as ADescriptionsItem,
} from '@arco-design/web-vue'

import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, LogIn, ShieldCheck, Users } from 'lucide-vue-next'

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
    auth.me?.user.email.toLowerCase() ===
      invitation.value?.email.toLowerCase() &&
    !accepted.value,
)
const emailMismatch = computed(
  () =>
    Boolean(auth.me) &&
    invitation.value?.status === 'pending' &&
    auth.me?.user.email.toLowerCase() !== invitation.value?.email.toLowerCase(),
)

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
      <a-alert v-else-if="error && !invitation" type="error" class="page-alert">
        <strong>{{ error.message }}</strong>
        <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
      </a-alert>
      <template v-else-if="invitation">
        <div class="invite-heading">
          <Users :size="28" />
          <div>
            <p>{{ accepted ? '已加入团队' : '团队邀请' }}</p>
            <h1>{{ invitation.team_name }}</h1>
          </div>
        </div>

        <a-descriptions :column="2" bordered class="detail-descriptions">
          <a-descriptions-item>
            <template #label>受邀邮箱</template>
            {{ invitation.email }}
          </a-descriptions-item>
          <a-descriptions-item>
            <template #label>分配角色</template>
            {{ roleLabels[invitation.role] ?? invitation.role }}
          </a-descriptions-item>
          <a-descriptions-item>
            <template #label>邀请状态</template>
            {{ invitation.status }}
          </a-descriptions-item>
          <a-descriptions-item>
            <template #label>有效期至</template>
            {{ formatDate(invitation.expires_at) }}
          </a-descriptions-item>
        </a-descriptions>

        <a-alert v-if="error" type="error" class="page-alert">
          <strong>{{ error.message }}</strong>
          <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
        </a-alert>

        <a-alert v-if="accepted" type="success" class="page-alert">
          <strong>邀请已接受</strong>
          <span>你已加入 {{ invitation.team_name }}。</span>
        </a-alert>
        <a-button
          v-if="accepted"
          @click="router.push('/knowledge-bases')"
          type="primary"
          html-type="button"
        >
          进入知识库
          <ArrowRight :size="17" />
        </a-button>

        <a-alert
          v-else-if="invitation.status !== 'pending'"
          type="warning"
          class="page-alert"
        >
          该邀请当前状态为 {{ invitation.status }}，无法再次接受。
        </a-alert>
        <div v-else-if="!auth.token" class="invite-actions">
          <p class="muted-text">请使用受邀邮箱对应的账号登录后接受邀请。</p>
          <a-button @click="loginToAccept" type="primary" html-type="button">
            <LogIn :size="17" />
            登录并继续
          </a-button>
        </div>
        <a-alert v-else-if="emailMismatch" type="error" class="page-alert">
          <strong>当前账号与受邀邮箱不一致</strong>
          <span>请退出后使用 {{ invitation.email }} 登录。</span>
        </a-alert>
        <a-button
          v-else
          data-testid="invite-accept"
          :disabled="accepting"
          @click="acceptInvitation"
          type="primary"
          html-type="button"
        >
          {{ accepting ? '正在加入' : '接受邀请' }}
          <ArrowRight :size="17" />
        </a-button>
      </template>

      <RouterLink class="auth-link" to="/login">返回登录</RouterLink>
    </div>
  </div>
</template>
