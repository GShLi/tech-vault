<script setup lang="ts">
import { ApiRequestError, api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Checkbox as ACheckbox,
  Empty as AEmpty,
  Form as AForm,
  FormItem as AFormItem,
  Message,
  Option as AOption,
  Select as ASelect,
  Spin as ASpin,
  Tag as ATag,
} from '@arco-design/web-vue'

import { statusLabel } from '@/utils/format'
import { onMounted, ref, watch } from 'vue'
import { Save, ShieldCheck } from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import { useTeamStore } from '@/stores/team'
import type { ModelPolicy, ModelProvider } from '@/types/api'

const team = useTeamStore()
const policy = ref<ModelPolicy | null>(null)
const providers = ref<ModelProvider[]>([])
const loading = ref(false)
const loadingMoreProviders = ref(false)
const providersNextCursor = ref<string | null>(null)
const providersHasMore = ref(false)
const saving = ref(false)
const error = ref<ApiRequestError | null>(null)
const mode = ref('local_only')
const maxClassification = ref('internal')
const allowedProviderIds = ref<string[]>([])
const allowChatHistory = ref(false)
const allowDocumentMetadata = ref(false)

async function load(): Promise<void> {
  if (!team.selectedTeamId) return
  loading.value = true
  error.value = null
  try {
    const [policyView, providerPage] = await Promise.all([
      api.getPolicy(team.selectedTeamId),
      api.listProviders(team.selectedTeamId),
    ])
    policy.value = policyView
    providers.value = providerPage.data
    providersNextCursor.value = providerPage.meta.next_cursor
    providersHasMore.value = providerPage.meta.has_more
    mode.value = policyView.mode
    maxClassification.value = policyView.max_data_classification
    allowedProviderIds.value = [...policyView.allowed_provider_ids]
    allowChatHistory.value = policyView.allow_chat_history
    allowDocumentMetadata.value = policyView.allow_document_metadata
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    loading.value = false
  }
}

async function loadMoreProviders(): Promise<void> {
  if (!team.selectedTeamId || !providersNextCursor.value) return
  loadingMoreProviders.value = true
  try {
    const page = await api.listProviders(
      team.selectedTeamId,
      providersNextCursor.value,
    )
    providers.value = [...providers.value, ...page.data]
    providersNextCursor.value = page.meta.next_cursor
    providersHasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    loadingMoreProviders.value = false
  }
}

function toggleProvider(providerId: string): void {
  allowedProviderIds.value = allowedProviderIds.value.includes(providerId)
    ? allowedProviderIds.value.filter((item) => item !== providerId)
    : [...allowedProviderIds.value, providerId]
}

async function save(): Promise<void> {
  if (!team.selectedTeamId) return
  saving.value = true
  error.value = null
  try {
    policy.value = await api.updatePolicy({
      team_id: team.selectedTeamId,
      mode: mode.value,
      max_data_classification: maxClassification.value,
      allowed_provider_ids: allowedProviderIds.value,
      allow_chat_history: allowChatHistory.value,
      allow_document_metadata: allowDocumentMetadata.value,
    })
    Message.success('团队模型策略已更新')
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    saving.value = false
  }
}

onMounted(load)
watch(() => team.selectedTeamId, load)
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>团队模型策略</h2>
        <p>控制数据分类、外部供应商和对话上下文的使用边界。</p>
      </div>
      <a-tag v-if="policy" :color="statusColor(policy.mode)">
        {{ statusLabel(policy.mode) }}
      </a-tag>
    </div>
    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </a-alert>
    <div v-if="loading && !policy" class="panel loading-state">
      <a-spin />
      <span>正在加载模型策略</span>
    </div>
    <div v-else class="split-grid">
      <a-card class="page-card">
        <div class="detail-heading">
          <div class="detail-icon"><ShieldCheck :size="20" /></div>
          <div>
            <h3>调用边界</h3>
            <p>策略版本 v{{ policy?.version || 1 }}</p>
          </div>
        </div>
        <a-form
          class="form-stack"
          :model="{
            mode,
            maxClassification,
            allowChatHistory,
            allowDocumentMetadata,
          }"
          layout="vertical"
          @submit-success="save"
        >
          <a-form-item field="mode">
            <template #label>模型模式</template>
            <a-select v-model="mode" :disabled="!team.canManage">
              <a-option value="local_only">仅本地模型</a-option>
              <a-option value="external_allowed">允许外部模型</a-option>
              <a-option value="external_required">仅外部模型</a-option>
            </a-select>
          </a-form-item>
          <a-form-item field="maxClassification">
            <template #label>允许发送的最大数据分类</template>
            <a-select v-model="maxClassification" :disabled="!team.canManage">
              <a-option value="public">公开</a-option>
              <a-option value="internal">内部</a-option>
              <a-option value="private">私有</a-option>
              <a-option value="restricted">受限</a-option>
            </a-select>
          </a-form-item>
          <a-checkbox
            class="check-field"
            v-model="allowChatHistory"
            :disabled="!team.canManage"
          >
            <span>允许向模型发送会话历史</span>
          </a-checkbox>
          <a-checkbox
            class="check-field"
            v-model="allowDocumentMetadata"
            :disabled="!team.canManage"
          >
            <span>允许向模型发送文档元数据</span>
          </a-checkbox>
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
        <div class="section-heading">
          <h3>允许的供应商</h3>
          <span class="muted-text">{{ allowedProviderIds.length }} 个</span>
        </div>
        <div v-if="providers.length" class="stack-list">
          <a-checkbox
            v-for="provider in providers"
            :key="provider.id"
            class="check-card"
            :disabled="!team.canManage || mode === 'local_only'"
            @change="toggleProvider(provider.id)"
            :model-value="allowedProviderIds.includes(provider.id)"
          >
            <div>
              <strong>{{ provider.name }}</strong>
              <span class="cell-subtitle">
                {{ provider.provider_type }} · {{ provider.status }}
              </span>
            </div>
          </a-checkbox>
        </div>
        <a-empty v-else class="page-empty">
          <template #image><ShieldCheck :size="22" /></template>
          <span>暂无可选供应商，请先在供应商页面添加。</span>
        </a-empty>
        <div v-if="providersHasMore" class="load-more">
          <a-button
            :disabled="loadingMoreProviders"
            @click="loadMoreProviders"
            type="secondary"
            html-type="button"
          >
            {{ loadingMoreProviders ? '加载中' : '加载更多供应商' }}
          </a-button>
        </div>
        <a-alert type="info" class="page-alert">
          <strong>本地模型模式</strong>
          <span>
            `local_only` 模式下不会向外部供应商发送任何内容，供应商勾选不生效。
          </span>
        </a-alert>
      </a-card>
    </div>
  </div>
</template>
