<script setup lang="ts">
import { ApiRequestError, api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Form as AForm,
  FormItem as AFormItem,
  Input as AInput,
  InputPassword as AInputPassword,
  Message,
} from '@arco-design/web-vue'

import { ref, watch } from 'vue'
import {
  DatabaseZap,
  KeyRound,
  Shield,
  ShieldCheck,
  Users,
  Wrench,
} from 'lucide-vue-next'

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
  {
    to: '/settings/team',
    title: '团队资料',
    description: '名称、描述与成员入口',
    icon: Users,
  },
  {
    to: '/settings/model-policy',
    title: '模型策略',
    description: '供应商范围与数据分类',
    icon: ShieldCheck,
    managerOnly: true,
  },
  {
    to: '/settings/providers',
    title: '模型供应商',
    description: '团队供应商与调用记录',
    icon: KeyRound,
    managerOnly: true,
  },
  {
    to: '/settings/audit',
    title: '审计日志',
    description: '管理操作与索引变更',
    icon: Shield,
    managerOnly: true,
  },
  {
    to: '/settings/index-generations',
    title: '索引 Generation',
    description: '验证、激活与回滚',
    icon: DatabaseZap,
    managerOnly: true,
  },
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
    error.value = normalizeApiError(caught)
  } finally {
    savingProfile.value = false
  }
}

async function changePassword(): Promise<void> {
  error.value = null
  if (newPassword.value !== confirmPassword.value) {
    error.value = new ApiRequestError(
      '两次输入的新密码不一致。',
      'VALIDATION_FAILED',
    )
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
    error.value = normalizeApiError(caught)
  } finally {
    changingPassword.value = false
  }
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>设置</h2>
        <p>团队治理、模型边界、索引与账号安全。</p>
      </div>
    </div>
    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </a-alert>

    <div class="settings-grid">
      <RouterLink
        v-for="link in links.filter(
          (item) => !item.managerOnly || team.canManage,
        )"
        :key="link.to"
        class="settings-card"
        :to="link.to"
      >
        <div class="detail-icon"><component :is="link.icon" :size="20" /></div>
        <div>
          <strong>{{ link.title }}</strong>
          <span>{{ link.description }}</span>
        </div>
      </RouterLink>
      <RouterLink class="settings-card" to="/settings/members">
        <div class="detail-icon"><Wrench :size="20" /></div>
        <div>
          <strong>成员与邀请</strong>
          <span>角色分配与成员移除</span>
        </div>
      </RouterLink>
    </div>

    <a-card class="page-card narrow-panel">
      <div class="detail-heading">
        <div class="detail-icon"><Users :size="20" /></div>
        <div>
          <h3>个人资料</h3>
          <p>更新当前账号显示名称</p>
        </div>
      </div>
      <a-form
        data-testid="profile-form"
        class="form-stack"
        :model="{ displayName }"
        layout="vertical"
        @submit-success="saveProfile"
      >
        <a-form-item
          field="displayName"
          :rules="[{ required: true, message: '请填写显示名称' }]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>显示名称</template>
          <a-input
            v-model="displayName"
            data-testid="profile-display-name"
            type="text"
            :input-attrs="{ required: true }"
          ></a-input>
        </a-form-item>
        <a-button
          data-testid="profile-save"
          :disabled="savingProfile"
          type="primary"
          html-type="submit"
        >
          {{ savingProfile ? '保存中' : '保存资料' }}
        </a-button>
      </a-form>
    </a-card>

    <a-card class="page-card narrow-panel">
      <div class="detail-heading">
        <div class="detail-icon"><Shield :size="20" /></div>
        <div>
          <h3>修改密码</h3>
          <p>修改当前账号登录密码</p>
        </div>
      </div>
      <a-form
        class="form-stack"
        :model="{ oldPassword, newPassword, confirmPassword }"
        layout="vertical"
        @submit-success="changePassword"
      >
        <a-form-item
          field="oldPassword"
          :rules="[{ required: true, message: '请填写当前密码' }]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>当前密码</template>
          <a-input-password
            v-model="oldPassword"
            data-testid="old-password"
            :input-attrs="{ required: true }"
          ></a-input-password>
        </a-form-item>
        <a-form-item
          field="newPassword"
          :rules="[
            { required: true, message: '请填写新密码' },
            { minLength: 8, message: '至少输入 8 个字符' },
          ]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>新密码</template>
          <a-input-password
            v-model="newPassword"
            data-testid="new-password"
            :input-attrs="{ required: true, minlength: '8' }"
          ></a-input-password>
        </a-form-item>
        <a-form-item
          field="confirmPassword"
          :rules="[
            { required: true, message: '请填写确认新密码' },
            { minLength: 8, message: '至少输入 8 个字符' },
          ]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>确认新密码</template>
          <a-input-password
            v-model="confirmPassword"
            data-testid="confirm-password"
            :input-attrs="{ required: true, minlength: '8' }"
          ></a-input-password>
        </a-form-item>
        <a-button
          data-testid="change-password-submit"
          :disabled="changingPassword"
          type="primary"
          html-type="submit"
        >
          {{ changingPassword ? '保存中' : '修改密码' }}
        </a-button>
      </a-form>
    </a-card>
  </div>
</template>
