<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LogIn, ShieldCheck } from 'lucide-vue-next'

import { ApiRequestError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'

const auth = useAuthStore()
const team = useTeamStore()
const router = useRouter()
const route = useRoute()

const email = ref('')
const password = ref('')
const error = ref<ApiRequestError | null>(null)
const submitting = ref(false)

async function submit(): Promise<void> {
  error.value = null
  submitting.value = true
  try {
    await auth.login(email.value.trim(), password.value)
    team.restore()
    const redirect =
      typeof route.query.redirect === 'string' ? route.query.redirect : null
    router.push(redirect ?? (team.selectedTeamId ? '/knowledge-bases' : '/teams'))
  } catch (caught) {
    error.value =
      caught instanceof ApiRequestError ? caught : auth.error
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-panel">
      <div class="auth-brand">
        <div class="brand-mark"><ShieldCheck :size="22" /></div>
        <div>
          <strong>TechVault 典阁</strong>
          <span>团队技术知识库</span>
        </div>
      </div>

      <h1>登录工作台</h1>

      <form class="form-stack" @submit.prevent="submit">
        <label class="field">
          <span>邮箱</span>
          <input
            v-model="email"
            data-testid="login-email"
            type="email"
            autocomplete="email"
            required
            placeholder="name@company.com"
          />
        </label>
        <label class="field">
          <span>密码</span>
          <input
            v-model="password"
            data-testid="login-password"
            type="password"
            autocomplete="current-password"
            required
            placeholder="输入密码"
          />
        </label>

        <div v-if="error" class="error-banner" role="alert">
          <strong>{{ error.message }}</strong>
          <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
        </div>

        <button
          class="primary-button"
          data-testid="login-submit"
          type="submit"
          :disabled="submitting"
        >
          <LogIn :size="17" />
          {{ submitting ? '登录中' : '登录' }}
        </button>
      </form>

      <p class="auth-link">账号由平台管理员统一创建。</p>
    </div>
  </div>
</template>
