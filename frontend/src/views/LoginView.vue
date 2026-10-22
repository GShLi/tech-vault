<script setup lang="ts">
import {
  Alert as AAlert,
  Button as AButton,
  Form as AForm,
  FormItem as AFormItem,
  Input as AInput,
  InputPassword as AInputPassword,
} from '@arco-design/web-vue'
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
    router.push(
      redirect ?? (team.selectedTeamId ? '/knowledge-bases' : '/teams'),
    )
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
        <div class="brand-mark"><ShieldCheck :size="22" /></div>
        <div>
          <strong>TechVault 典阁</strong>
          <span>团队技术知识库</span>
        </div>
      </div>

      <h1>登录工作台</h1>

      <a-form
        class="form-stack"
        :model="{ email, password }"
        layout="vertical"
        @submit-success="submit"
      >
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
            data-testid="login-email"
            placeholder="name@company.com"
            type="text"
            :input-attrs="{ required: true, autocomplete: 'email' }"
          ></a-input>
        </a-form-item>
        <a-form-item
          field="password"
          :rules="[{ required: true, message: '请填写密码' }]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>密码</template>
          <a-input-password
            v-model="password"
            data-testid="login-password"
            placeholder="输入密码"
            :input-attrs="{ required: true, autocomplete: 'current-password' }"
          ></a-input-password>
        </a-form-item>
        <a-alert v-if="error" type="error" class="page-alert">
          <strong>{{ error.message }}</strong>
          <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
        </a-alert>
        <a-button
          data-testid="login-submit"
          :disabled="submitting"
          type="primary"
          html-type="submit"
        >
          <LogIn :size="17" />
          {{ submitting ? '登录中' : '登录' }}
        </a-button>
      </a-form>

      <p class="auth-link">账号由平台管理员统一创建。</p>
    </div>
  </div>
</template>
