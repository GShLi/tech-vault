<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { Save, Users } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
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
    error.value = caught instanceof ApiRequestError ? caught : null
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
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    saving.value = false
  }
}

onMounted(load)
watch(() => teamStore.selectedTeamId, load)
</script>

<template>
  <div>
    <div class="page-header"><div><h2>团队资料</h2><p>维护当前团队名称、描述与版本信息。</p></div><RouterLink class="secondary-button" to="/settings/members"><Users :size="16" />成员管理</RouterLink></div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span></div>
    <div v-if="loading && !team" class="panel loading-state"><a-spin /><span>正在加载团队</span></div>
    <section v-else-if="team" class="panel detail-panel narrow-panel">
      <div class="detail-heading"><div class="detail-icon"><Users :size="20" /></div><div><h3>{{ team.name }}</h3><p>创建于 {{ formatDate(team.created_at) }} · v{{ team.version }}</p></div></div>
      <form class="form-stack" @submit.prevent="save">
        <label class="field"><span>团队名称</span><input v-model="name" type="text" :disabled="!teamStore.canManage" required /></label>
        <label class="field"><span>描述</span><textarea v-model="description" rows="4" :disabled="!teamStore.canManage" /></label>
        <button v-if="teamStore.canManage" class="primary-button" type="submit" :disabled="saving"><Save :size="16" />{{ saving ? '保存中' : '保存团队资料' }}</button>
      </form>
    </section>
  </div>
</template>
