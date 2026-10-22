<script setup lang="ts">
import { ApiRequestError, api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Form as AForm,
  FormItem as AFormItem,
  Input as AInput,
  Message,
  Spin as ASpin,
  Textarea as ATextarea,
} from '@arco-design/web-vue'

import { onMounted, ref, watch } from 'vue'
import { Save, Users } from 'lucide-vue-next'

import { useTeamStore } from '@/stores/team'
import type { Team } from '@/types/api'
import { formatDate } from '@/utils/format'

const teamStore = useTeamStore()
const team = ref<Team | null>(null)
const name = ref('')
const description = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref<ApiRequestError | null>(null)

async function load(): Promise<void> {
  if (!teamStore.selectedTeamId) return
  loading.value = true
  error.value = null
  try {
    team.value = await api.getTeam(teamStore.selectedTeamId)
    name.value = team.value.name
    description.value = team.value.description ?? ''
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (!teamStore.selectedTeamId || !team.value) return
  saving.value = true
  error.value = null
  try {
    team.value = await api.updateTeam(
      {
        team_id: teamStore.selectedTeamId,
        name: name.value.trim(),
        description: description.value.trim() || null,
      },
      team.value.version,
    )
    Message.success('团队资料已更新')
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    saving.value = false
  }
}

onMounted(load)
watch(() => teamStore.selectedTeamId, load)
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>团队资料</h2>
        <p>维护当前团队名称、描述与版本信息。</p>
      </div>
      <RouterLink to="/settings/members" custom v-slot="{ href, navigate }">
        <a-button type="secondary" :href="href" @click="navigate">
          <Users :size="16" />
          成员管理
        </a-button>
      </RouterLink>
    </div>
    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </a-alert>
    <div v-if="loading && !team" class="panel loading-state">
      <a-spin />
      <span>正在加载团队</span>
    </div>
    <a-card v-else-if="team" class="page-card narrow-panel">
      <div class="detail-heading">
        <div class="detail-icon"><Users :size="20" /></div>
        <div>
          <h3>{{ team.name }}</h3>
          <p>创建于 {{ formatDate(team.created_at) }} · v{{ team.version }}</p>
        </div>
      </div>
      <a-form
        class="form-stack"
        :model="{ name, description }"
        layout="vertical"
        @submit-success="save"
      >
        <a-form-item
          field="name"
          :rules="[{ required: true, message: '请填写团队名称' }]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>团队名称</template>
          <a-input
            v-model="name"
            :disabled="!teamStore.canManage"
            type="text"
            :input-attrs="{ required: true }"
          ></a-input>
        </a-form-item>
        <a-form-item field="description">
          <template #label>描述</template>
          <a-textarea
            v-model="description"
            :disabled="!teamStore.canManage"
            :textarea-attrs="{ rows: '4' }"
          ></a-textarea>
        </a-form-item>
        <a-button
          v-if="teamStore.canManage"
          :disabled="saving"
          type="primary"
          html-type="submit"
        >
          <Save :size="16" />
          {{ saving ? '保存中' : '保存团队资料' }}
        </a-button>
      </a-form>
    </a-card>
  </div>
</template>
