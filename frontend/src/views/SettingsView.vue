<script setup lang="ts">
import { ref, watch } from 'vue'
import { DatabaseZap, KeyRound, Shield, ShieldCheck, Users, Wrench } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'

const auth = useAuthStore()
const team = useTeamStore()
const error = ref<ApiRequestError | null>(null)
const displayName = ref('')
const savingProfile = ref(false)
const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const changingPassword = ref(false)

const links = [
  { to: '/settings/team', title: '团队资料', description: '名称、描述与成员入口', icon: Users },
  { to: '/settings/model-policy', title: '模型策略', description: '供应商范围与数据分类', icon: ShieldCheck, managerOnly: true },
  { to: '/settings/providers', title: '模型供应商', description: '团队供应商与调用记录', icon: KeyRound, managerOnly: true },
  { to: '/settings/audit', title: '审计日志', description: '管理操作与索引变更', icon: Shield, managerOnly: true },
  { to: '/settings/index-generations', title: '索引 Generation', description: '验证、激活与回滚', icon: DatabaseZap, managerOnly: true },
]

watch(
  () => auth.me?.user.display_name,
  (value) => {
    if (value !== undefined) displayName.value = value
  },
  { immediate: true },
)

async function saveProfile(): Promise<void> {
  const nextDisplayName = displayName.value.trim()
  if (!nextDisplayName) return

  error.value = null
  savingProfile.value = true
  try {
    await api.updateProfile(nextDisplayName)
    await auth.loadMe()
    Message.success('个人资料已更新')
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    savingProfile.value = false
  }
}

async function changePassword(): Promise<void> {
  error.value = null
  if (newPassword.value !== confirmPassword.value) {
    error.value = new ApiRequestError('两次输入的新密码不一致。', 'VALIDATION_FAILED')
    return
  }
  changingPassword.value = true
  try {
    await api.changePassword({ old_password: oldPassword.value, new_password: newPassword.value })
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
    <div class="page-header"><div><h2>设置</h2><p>团队治理、模型边界、索引与账号安全。</p></div></div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span></div>

    <div class="settings-grid">
      <RouterLink v-for="link in links.filter((item) => !item.managerOnly || team.canManage)" :key="link.to" class="settings-card" :to="link.to">
        <div class="detail-icon"><component :is="link.icon" :size="20" /></div>
        <div><strong>{{ link.title }}</strong><span>{{ link.description }}</span></div>
      </RouterLink>
      <RouterLink class="settings-card" to="/settings/members"><div class="detail-icon"><Wrench :size="20" /></div><div><strong>成员与邀请</strong><span>角色分配与成员移除</span></div></RouterLink>
    </div>

    <section class="panel detail-panel narrow-panel">
      <div class="detail-heading"><div class="detail-icon"><Users :size="20" /></div><div><h3>个人资料</h3><p>更新当前账号显示名称</p></div></div>
      <form data-testid="profile-form" class="form-stack" @submit.prevent="saveProfile">
        <label class="field"><span>显示名称</span><input v-model="displayName" data-testid="profile-display-name" type="text" required /></label>
        <button class="primary-button" data-testid="profile-save" type="submit" :disabled="savingProfile">{{ savingProfile ? '保存中' : '保存资料' }}</button>
      </form>
    </section>

    <section class="panel detail-panel narrow-panel">
      <div class="detail-heading"><div class="detail-icon"><Shield :size="20" /></div><div><h3>修改密码</h3><p>修改当前账号登录密码</p></div></div>
      <form class="form-stack" @submit.prevent="changePassword">
        <label class="field"><span>当前密码</span><input v-model="oldPassword" data-testid="old-password" type="password" required /></label>
        <label class="field"><span>新密码</span><input v-model="newPassword" data-testid="new-password" type="password" minlength="8" required /></label>
        <label class="field"><span>确认新密码</span><input v-model="confirmPassword" data-testid="confirm-password" type="password" minlength="8" required /></label>
        <button class="primary-button" data-testid="change-password-submit" type="submit" :disabled="changingPassword">{{ changingPassword ? '保存中' : '修改密码' }}</button>
      </form>
    </section>
  </div>
</template>
