<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Save, Server, ShieldCheck } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError, loadAllPages } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
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
    error.value = caught instanceof ApiRequestError ? caught : null
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
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-header"><div><h2>系统级模型策略</h2><p>系统级模型调用上限，团队策略只能在其范围内收紧。</p></div><StatusPill v-if="policy" :status="policy.mode" /></div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span></div>
    <div v-if="loading && !policy" class="panel loading-state"><a-spin /><span>正在加载平台策略</span></div>
    <div v-else class="split-grid">
      <section class="panel detail-panel">
        <div class="detail-heading"><div class="detail-icon"><ShieldCheck :size="20" /></div><div><h3>策略默认值</h3><p>当前模式：{{ statusLabel(policy?.mode) }}</p></div></div>
        <form class="form-stack" @submit.prevent="save">
          <label class="field"><span>平台模式</span><select v-model="mode"><option value="local_only">仅本地模型</option><option value="external_allowed">允许外部模型</option><option value="external_required">仅外部模型</option></select></label>
          <label class="field"><span>允许的最大数据分类</span><select v-model="maxClassification"><option value="public">公开</option><option value="internal">内部</option><option value="private">私有</option><option value="restricted">受限</option></select></label>
          <label class="check-field">
            <input
              v-model="allowChatHistory"
              data-testid="admin-allow-chat-history"
              type="checkbox"
            />
            <span>允许向模型发送会话历史</span>
          </label>
          <label class="check-field">
            <input
              v-model="allowDocumentMetadata"
              data-testid="admin-allow-document-metadata"
              type="checkbox"
            />
            <span>允许向模型发送文档元数据</span>
          </label>
          <button class="primary-button" type="submit" :disabled="saving"><Save :size="16" />{{ saving ? '保存中' : '保存系统级策略' }}</button>
        </form>
      </section>
      <section class="panel detail-panel">
        <div class="section-heading"><div><h3>供应商准入</h3></div><span class="muted-text">{{ allowedProviderIds.length }} 个已允许</span></div>
        <div v-if="providers.length" class="stack-list">
          <label v-for="provider in providers" :key="provider.id" class="check-card" :data-testid="`provider-admission-${provider.id}`">
            <input type="checkbox" :checked="allowedProviderIds.includes(provider.id)" @change="toggleProvider(provider.id)" />
            <div class="provider-admission-copy">
              <div class="provider-admission-heading">
                <strong>{{ provider.name }}</strong>
                <StatusPill :status="provider.status" />
              </div>
              <span class="cell-subtitle">{{ providerTypeLabel(provider.provider_type) }}</span>
              <div class="tag-list">
                <span v-for="model in provider.model_ids || []" :key="model" class="tag">{{ model }}</span>
                <span v-if="!(provider.model_ids || []).length" class="muted-text">未配置模型</span>
              </div>
              <span class="cell-subtitle credential-fact">
                <template v-if="provider.has_api_key">API Key 可用<span v-if="provider.api_key_masked"> · {{ provider.api_key_masked }}</span></template>
                <template v-else>API Key 不可用</template>
              </span>
            </div>
          </label>
        </div>
        <div v-else class="empty-state compact provider-admission-empty">
          <Server :size="22" />
          <span>暂无系统级供应商</span>
          <RouterLink class="secondary-button" to="/admin/model-providers">前往供应商管理</RouterLink>
        </div>
        <div v-if="mode === 'local_only'" class="notice-box">
          <strong>仅本地模型模式</strong>
          <span>外部模型调用当前已禁用；供应商勾选仍可编辑并保存，在允许外部模型后生效。</span>
        </div>
      </section>
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

.provider-admission-copy .tag {
  max-width: 100%;
  overflow-wrap: anywhere;
}

.provider-admission-empty {
  justify-items: start;
}
</style>
