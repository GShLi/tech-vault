<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { Save, ShieldCheck } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
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
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

async function loadMoreProviders(): Promise<void> {
  if (!team.selectedTeamId || !providersNextCursor.value) return
  loadingMoreProviders.value = true
  try {
    const page = await api.listProviders(team.selectedTeamId, providersNextCursor.value)
    providers.value = [...providers.value, ...page.data]
    providersNextCursor.value = page.meta.next_cursor
    providersHasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
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
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    saving.value = false
  }
}

onMounted(load)
watch(() => team.selectedTeamId, load)
</script>

<template>
  <div>
    <div class="page-header"><div><h2>团队模型策略</h2><p>控制数据分类、外部供应商和对话上下文的使用边界。</p></div><StatusPill v-if="policy" :status="policy.mode" /></div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span></div>
    <div v-if="loading && !policy" class="panel loading-state"><a-spin /><span>正在加载模型策略</span></div>
    <div v-else class="split-grid">
      <section class="panel detail-panel">
        <div class="detail-heading"><div class="detail-icon"><ShieldCheck :size="20" /></div><div><h3>调用边界</h3><p>策略版本 v{{ policy?.version || 1 }}</p></div></div>
        <form class="form-stack" @submit.prevent="save">
          <label class="field"><span>模型模式</span><select v-model="mode" :disabled="!team.canManage"><option value="local_only">仅本地模型</option><option value="external_allowed">允许外部模型</option><option value="external_required">仅外部模型</option></select></label>
          <label class="field"><span>允许发送的最大数据分类</span><select v-model="maxClassification" :disabled="!team.canManage"><option value="public">公开</option><option value="internal">内部</option><option value="private">私有</option><option value="restricted">受限</option></select></label>
          <label class="check-field"><input v-model="allowChatHistory" type="checkbox" :disabled="!team.canManage" /><span>允许向模型发送会话历史</span></label>
          <label class="check-field"><input v-model="allowDocumentMetadata" type="checkbox" :disabled="!team.canManage" /><span>允许向模型发送文档元数据</span></label>
          <button v-if="team.canManage" class="primary-button" type="submit" :disabled="saving"><Save :size="16" />{{ saving ? '保存中' : '保存策略' }}</button>
        </form>
      </section>
      <section class="panel detail-panel">
        <div class="section-heading"><h3>允许的供应商</h3><span class="muted-text">{{ allowedProviderIds.length }} 个</span></div>
        <div v-if="providers.length" class="stack-list">
          <label v-for="provider in providers" :key="provider.id" class="check-card">
            <input type="checkbox" :checked="allowedProviderIds.includes(provider.id)" :disabled="!team.canManage || mode === 'local_only'" @change="toggleProvider(provider.id)" />
            <div><strong>{{ provider.name }}</strong><span class="cell-subtitle">{{ provider.provider_type }} · {{ provider.status }}</span></div>
          </label>
        </div>
        <div v-else class="empty-state compact"><ShieldCheck :size="22" /><span>暂无可选供应商，请先在供应商页面添加。</span></div>
        <div v-if="providersHasMore" class="load-more">
          <button class="secondary-button" type="button" :disabled="loadingMoreProviders" @click="loadMoreProviders">
            {{ loadingMoreProviders ? '加载中' : '加载更多供应商' }}
          </button>
        </div>
        <div class="notice-box"><strong>本地模型模式</strong><span>`local_only` 模式下不会向外部供应商发送任何内容，供应商勾选不生效。</span></div>
      </section>
    </div>
  </div>
</template>
