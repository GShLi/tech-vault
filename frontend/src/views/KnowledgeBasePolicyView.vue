<script setup lang="ts">
import { ApiRequestError, api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Descriptions as ADescriptions,
  DescriptionsItem as ADescriptionsItem,
  Form as AForm,
  FormItem as AFormItem,
  Message,
  Option as AOption,
  Select as ASelect,
  Spin as ASpin,
  Tag as ATag,
} from '@arco-design/web-vue'

import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, Save, ShieldCheck } from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import { useTeamStore } from '@/stores/team'
import type { KnowledgeBase, ModelPolicy } from '@/types/api'
import { statusLabel } from '@/utils/format'

const route = useRoute()
const team = useTeamStore()
const kb = ref<KnowledgeBase | null>(null)
const kbPolicy = ref<{ kb_id: string; mode: string; version: number } | null>(
  null,
)
const teamPolicy = ref<ModelPolicy | null>(null)
const mode = ref('local_only')
const loading = ref(false)
const saving = ref(false)
const error = ref<ApiRequestError | null>(null)

function kbId(): string {
  return String(route.params.kbId ?? '')
}

async function load(): Promise<void> {
  if (!team.selectedTeamId || !kbId()) return
  loading.value = true
  error.value = null
  try {
    const [kbView, policyView, parentPolicy] = await Promise.all([
      api.getKb(team.selectedTeamId, kbId()),
      api.getKbPolicy(team.selectedTeamId, kbId()),
      api.getPolicy(team.selectedTeamId),
    ])
    kb.value = kbView
    kbPolicy.value = policyView
    teamPolicy.value = parentPolicy
    mode.value = policyView.mode
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (!team.selectedTeamId) return
  saving.value = true
  error.value = null
  try {
    kbPolicy.value = await api.updateKbPolicy(
      { team_id: team.selectedTeamId, kb_id: kbId(), mode: mode.value },
      kbPolicy.value?.version ?? 1,
    )
    Message.success('知识库策略已更新')
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    saving.value = false
  }
}

onMounted(load)
watch(() => route.params.kbId, load)
</script>

<template>
  <div>
    <div class="page-header">
      <div class="heading-with-back">
        <RouterLink
          :to="`/knowledge-bases/${kbId()}`"
          custom
          v-slot="{ href, navigate }"
        >
          <a-button
            type="text"
            :href="href"
            @click="navigate"
            title="返回知识库"
          >
            <ArrowLeft :size="18" />
          </a-button>
        </RouterLink>
        <div>
          <h2>知识库策略</h2>
          <p>{{ kb?.name || '模型调用与数据边界' }}</p>
        </div>
      </div>
    </div>
    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </a-alert>
    <div v-if="loading && !kbPolicy" class="panel loading-state">
      <a-spin />
      <span>正在加载策略</span>
    </div>
    <div v-else class="split-grid">
      <a-card class="page-card">
        <div class="detail-heading">
          <div class="detail-icon"><ShieldCheck :size="20" /></div>
          <div>
            <h3>知识库上限</h3>
            <p>只能在团队策略允许范围内收紧。</p>
          </div>
          <a-tag :color="statusColor(mode)">{{ statusLabel(mode) }}</a-tag>
        </div>
        <a-form
          class="form-stack"
          :model="{ mode }"
          layout="vertical"
          @submit-success="save"
        >
          <a-form-item field="mode">
            <template #label>模型调用模式</template>
            <a-select v-model="mode" :disabled="!team.canManage">
              <a-option value="local_only">仅本地模型</a-option>
              <a-option value="external_allowed">允许外部模型</a-option>
              <a-option value="external_required">仅外部模型</a-option>
            </a-select>
          </a-form-item>
          <a-alert type="info" class="page-alert">
            <strong>继承规则</strong>
            <span>
              团队策略：{{
                statusLabel(teamPolicy?.mode)
              }}；知识库不得放宽数据分类或供应商范围。
            </span>
          </a-alert>
          <a-button
            v-if="team.canManage"
            :disabled="saving"
            type="primary"
            html-type="submit"
          >
            <Save :size="16" />
            {{ saving ? '保存中' : '保存策略' }}
          </a-button>
        </a-form>
      </a-card>
      <a-card class="page-card">
        <div class="section-heading"><h3>当前生效值</h3></div>
        <a-descriptions :column="1" bordered class="detail-descriptions">
          <a-descriptions-item label="知识库模式">
            {{ statusLabel(kbPolicy?.mode) }}
          </a-descriptions-item>
          <a-descriptions-item label="团队模式">
            {{ statusLabel(teamPolicy?.mode) }}
          </a-descriptions-item>
          <a-descriptions-item label="最大数据分类">
            {{ teamPolicy?.max_data_classification || '—' }}
          </a-descriptions-item>
          <a-descriptions-item label="允许供应商">
            {{ teamPolicy?.allowed_provider_ids.length || 0 }} 个
          </a-descriptions-item>
          <a-descriptions-item label="策略版本">
            v{{ kbPolicy?.version || 1 }}
          </a-descriptions-item>
        </a-descriptions>
      </a-card>
    </div>
  </div>
</template>
