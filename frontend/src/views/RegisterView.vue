<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ShieldPlus } from 'lucide-vue-next'

import { ApiRequestError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'

const auth = useAuthStore()
const team = useTeamStore()
const router = useRouter()

const displayName = ref('')
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const error = ref<ApiRequestError | null>(null)
const validationError = ref('')
const submitting = ref(false)

async function submit(): Promise<void> {
  error.value = null
  validationError.value = ''

  if (password.value.length < 8) {
    validationError.value = '密码至少需要 8 个字符。'
    return
  }
  if (password.value !== confirmPassword.value) {
    validationError.value = '两次输入的密码不一致。'
    return
  }

  submitting.value = true
  try {
    await auth.register({
      display_name: displayName.value.trim(),
      email: email.value.trim(),
      password: password.value,
    })
    team.restore()
    router.push(team.selectedTeamId ? '/knowledge-bases' : '/teams')
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : auth.error
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-panel">
      <div class="auth-brand">
        <div class="brand-mark"><ShieldPlus :size="22" /></div>
        <div>
          <strong>TechVault 典阁</strong>
          <span>团队技术知识库</span>
        </div>
      </div>

      <h1>创建账号</h1>

      <form class="form-stack" @submit.prevent="submit">
        <label class="field">
          <span>显示名</span>
          <input
            v-model="displayName"
            data-testid="register-display-name"
            type="text"
            autocomplete="name"
            required
            placeholder="你的名字"
          />
        </label>
        <label class="field">
          <span>邮箱</span>
          <input
            v-model="email"
            data-testid="register-email"
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
            data-testid="register-password"
            type="password"
            autocomplete="new-password"
            required
            placeholder="至少 8 个字符"
          />
        </label>
        <label class="field">
          <span>确认密码</span>
          <input
            v-model="confirmPassword"
            data-testid="register-confirm-password"
            type="password"
            autocomplete="new-password"
            required
            placeholder="再次输入密码"
          />
        </label>

        <div v-if="validationError" class="error-banner" role="alert">
          <strong>{{ validationError }}</strong>
        </div>
        <div v-if="error" class="error-banner" role="alert">
          <strong>{{ error.message }}</strong>
          <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
        </div>

        <button
          class="primary-button"
          data-testid="register-submit"
          type="submit"
          :disabled="submitting"
        >
          <ShieldPlus :size="17" />
          {{ submitting ? '创建中' : '创建账号' }}
        </button>
      </form>

      <p class="auth-link">
        已有账号？<RouterLink to="/login">返回登录</RouterLink>
      </p>
    </div>
  </div>
</template>
