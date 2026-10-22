<script setup lang="ts">
import {
  ApiRequestError,
  api,
  loadAllPages,
  normalizeApiError,
} from '@/api/client'
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

import { onMounted, ref } from 'vue'
import { Save, Server, ShieldCheck } from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import type { ModelPolicy, ModelProvider } from '@/types/api'
import { statusLabel } from '@/utils/format'
import { providerTypeLabel } from '@/utils/providers'

const policy = ref<ModelPolicy | null>(null)
const providers = ref<ModelProvider[]>([])
const mode = ref('local_only')
const maxClassification = ref('internal')
const allowedProviderIds = ref<string[]>([])
const allowChatHistory = ref(false)
const allowDocumentMetadata = ref(false)
const loading = ref(false)
const saving = ref(false)
const error = ref<ApiRequestError | null>(null)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [policyView, providerRows] = await Promise.all([
      api.getAdminPolicy(),
      loadAllPages((cursor) => api.listAdminProviders(cursor, 100)),
    ])
    policy.value = policyView
    providers.value = providerRows
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

function toggleProvider(providerId: string): void {
  allowedProviderIds.value = allowedProviderIds.value.includes(providerId)
    ? allowedProviderIds.value.filter((id) => id !== providerId)
    : [...allowedProviderIds.value, providerId]
}

async function save(): Promise<void> {
  saving.value = true
  error.value = null
  try {
    policy.value = await api.updateAdminPolicy({
      mode: mode.value,
      max_data_classification: maxClassification.value,
      allowed_provider_ids: [...allowedProviderIds.value],
      allow_chat_history: allowChatHistory.value,
      allow_document_metadata: allowDocumentMetadata.value,
    })
    allowedProviderIds.value = [...policy.value.allowed_provider_ids]
    allowChatHistory.value = policy.value.allow_chat_history
    allowDocumentMetadata.value = policy.value.allow_document_metadata
    Message.success('系统级模型策略已更新')
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>系统级模型策略</h2>
        <p>系统级模型调用上限，团队策略只能在其范围内收紧。</p>
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
      <span>正在加载平台策略</span>
    </div>
    <div v-else class="split-grid">
      <a-card class="page-card">
        <div class="detail-heading">
          <div class="detail-icon"><ShieldCheck :size="20" /></div>
          <div>
            <h3>策略默认值</h3>
            <p>当前模式：{{ statusLabel(policy?.mode) }}</p>
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
            <template #label>平台模式</template>
            <a-select v-model="mode">
              <a-option value="local_only">仅本地模型</a-option>
              <a-option value="external_allowed">允许外部模型</a-option>
              <a-option value="external_required">仅外部模型</a-option>
            </a-select>
          </a-form-item>
          <a-form-item field="maxClassification">
            <template #label>允许的最大数据分类</template>
            <a-select v-model="maxClassification">
              <a-option value="public">公开</a-option>
              <a-option value="internal">内部</a-option>
              <a-option value="private">私有</a-option>
              <a-option value="restricted">受限</a-option>
            </a-select>
          </a-form-item>
          <a-checkbox
            class="check-field"
            v-model="allowChatHistory"
            data-testid="admin-allow-chat-history"
          >
            <span>允许向模型发送会话历史</span>
          </a-checkbox>
          <a-checkbox
            class="check-field"
            v-model="allowDocumentMetadata"
            data-testid="admin-allow-document-metadata"
          >
            <span>允许向模型发送文档元数据</span>
          </a-checkbox>
          <a-button :disabled="saving" type="primary" html-type="submit">
            <Save :size="16" />
            {{ saving ? '保存中' : '保存系统级策略' }}
          </a-button>
        </a-form>
      </a-card>
      <a-card class="page-card">
        <div class="section-heading">
          <div><h3>供应商准入</h3></div>
          <span class="muted-text">
            {{ allowedProviderIds.length }} 个已允许
          </span>
        </div>
        <div v-if="providers.length" class="stack-list">
          <a-checkbox
            v-for="provider in providers"
            :key="provider.id"
            class="check-card"
            :data-testid="`provider-admission-${provider.id}`"
            @change="toggleProvider(provider.id)"
            :model-value="allowedProviderIds.includes(provider.id)"
          >
            <div class="provider-admission-copy">
              <div class="provider-admission-heading">
                <strong>{{ provider.name }}</strong>
                <a-tag :color="statusColor(provider.status)">
                  {{ statusLabel(provider.status) }}
                </a-tag>
              </div>
              <span class="cell-subtitle">
                {{ providerTypeLabel(provider.provider_type) }}
              </span>
              <div class="tag-list">
                <a-tag v-for="model in provider.model_ids || []" :key="model">
                  {{ model }}
                </a-tag>
                <span
                  v-if="!(provider.model_ids || []).length"
                  class="muted-text"
                >
                  未配置模型
                </span>
              </div>
              <span class="cell-subtitle credential-fact">
                <template v-if="provider.has_api_key">
                  API Key 可用
                  <span v-if="provider.api_key_masked">
                    · {{ provider.api_key_masked }}
                  </span>
                </template>
                <template v-else>API Key 不可用</template>
              </span>
            </div>
          </a-checkbox>
        </div>
        <a-empty v-else class="page-empty">
          <template #image><Server :size="22" /></template>
          <span>暂无系统级供应商</span>
          <RouterLink
            to="/admin/model-providers"
            custom
            v-slot="{ href, navigate }"
          >
            <a-button type="secondary" :href="href" @click="navigate">
              前往供应商管理
            </a-button>
          </RouterLink>
        </a-empty>
        <a-alert v-if="mode === 'local_only'" type="info" class="page-alert">
          <strong>仅本地模型模式</strong>
          <span>
            外部模型调用当前已禁用；供应商勾选仍可编辑并保存，在允许外部模型后生效。
          </span>
        </a-alert>
      </a-card>
    </div>
  </div>
</template>

<style scoped>
.provider-admission-copy {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 8px;
}

.provider-admission-heading {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
}

.provider-admission-heading strong,
.credential-fact {
  min-width: 0;
  overflow-wrap: anywhere;
}

.provider-admission-empty {
  justify-items: start;
}
</style>
