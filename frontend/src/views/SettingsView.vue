<script setup lang="ts">
import { ref } from 'vue'
import { Shield, Server } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
import { useTeamStore } from '@/stores/team'

const team = useTeamStore()
const policy = ref<Record<string, unknown>>({})
const error = ref<ApiRequestError | null>(null)
const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const changingPassword = ref(false)

async function loadPolicy(): Promise<void> {
  if (!team.selectedTeamId) return
  try { policy.value = await api.getPolicy(team.selectedTeamId) } catch (caught) { error.value = caught instanceof ApiRequestError ? caught : null }
}

async function updateMode(mode: string): Promise<void> {
  if (!team.selectedTeamId) return
  try { await api.updatePolicy(team.selectedTeamId, mode); await loadPolicy() } catch (caught) { error.value = caught instanceof ApiRequestError ? caught : null }
}

async function changePassword(): Promise<void> {
  error.value = null
  if (newPassword.value !== confirmPassword.value) {
    error.value = new ApiRequestError('两次输入的新密码不一致。', 'VALIDATION_FAILED')
    return
  }
  changingPassword.value = true
  try {
    await api.changePassword({
      old_password: oldPassword.value,
      new_password: newPassword.value,
    })
    oldPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    Message.success('密码已修改')
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    changingPassword.value = false
  }
}
</script>

<template>
  <div>
    <div class="page-header"><div><h2>设置</h2><p>团队模型策略与安全配置。</p></div></div>

    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong></div>

    <div class="panel" style="padding:22px;max-width:640px">
      <div class="form-stack">
        <div style="display:flex;align-items:center;gap:12px"><Shield :size="18" /><h3 style="margin:0">模型策略</h3></div>
        <p class="muted-text">当前模式：{{ policy.mode || 'local_only' }}</p>
        <select @change="updateMode(($event.target as HTMLSelectElement).value)" style="width:100%;height:38px;border:1px solid #cbd5df;border-radius:6px;padding:0 8px">
          <option value="local_only">仅本地模型</option>
          <option value="external_allowed">允许外部模型</option>
        </select>
        <div style="display:flex;align-items:center;gap:12px;margin-top:20px"><Server :size="18" /><h3 style="margin:0">组件状态</h3></div>
        <a-tag color="green">API 运行中</a-tag>
        <a-tag color="green">数据库可用</a-tag>
        <a-tag color="green">ES / Qdrant 已接入</a-tag>
      </div>
    </div>

    <div class="panel" style="padding:22px;max-width:640px;margin-top:16px">
      <form class="form-stack" @submit.prevent="changePassword">
        <div style="display:flex;align-items:center;gap:12px"><Shield :size="18" /><h3 style="margin:0">修改密码</h3></div>
        <label class="field">
          <span>当前密码</span>
          <input v-model="oldPassword" data-testid="old-password" type="password" required />
        </label>
        <label class="field">
          <span>新密码</span>
          <input v-model="newPassword" data-testid="new-password" type="password" minlength="8" required />
        </label>
        <label class="field">
          <span>确认新密码</span>
          <input v-model="confirmPassword" data-testid="confirm-password" type="password" minlength="8" required />
        </label>
        <button class="primary-button" data-testid="change-password-submit" type="submit" :disabled="changingPassword">
          {{ changingPassword ? '保存中' : '修改密码' }}
        </button>
      </form>
    </div>
  </div>
</template>
