<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Plus, RefreshCw, Server } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import type { ModelProvider } from '@/types/api'
import { parseLines } from '@/utils/format'

const providers = ref<ModelProvider[]>([])
const loading = ref(false)
const loadingMore = ref(false)
const nextCursor = ref<string | null>(null)
const hasMore = ref(false)
const saving = ref(false)
const error = ref<ApiRequestError | null>(null)
const name = ref('')
const providerType = ref('openai_compatible')
const baseUrl = ref('')
const modelIds = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const page = await api.listAdminProviders()
    providers.value = page.data
    nextCursor.value = page.meta.next_cursor
    hasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

async function loadMore(): Promise<void> {
  if (!nextCursor.value) return
  loadingMore.value = true
  try {
    const page = await api.listAdminProviders(nextCursor.value)
    providers.value = [...providers.value, ...page.data]
    nextCursor.value = page.meta.next_cursor
    hasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loadingMore.value = false
  }
}

async function createProvider(): Promise<void> {
  saving.value = true
  error.value = null
  try {
    await api.createAdminProvider({
      name: name.value.trim(),
      provider_type: providerType.value,
      base_url: baseUrl.value.trim(),
      model_ids: parseLines(modelIds.value),
    })
    Message.success('平台供应商已创建')
    name.value = ''
    baseUrl.value = ''
    modelIds.value = ''
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    saving.value = false
  }
}

async function toggleStatus(provider: ModelProvider): Promise<void> {
  try {
    await api.updateAdminProvider({
      provider_id: provider.id,
      status: provider.status === 'active' ? 'disabled' : 'active',
    })
    Message.success('供应商状态已更新')
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-header"><div><h2>供应商准入</h2><p>管理所有团队可继承的平台模型供应商。</p></div><button class="secondary-button" type="button" :disabled="loading" @click="load"><RefreshCw :size="16" />刷新</button></div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span></div>
    <div class="split-grid">
      <section class="panel detail-panel">
        <div class="section-heading"><h3>平台供应商</h3><span class="muted-text">{{ providers.length }} 个</span></div>
        <div v-if="providers.length" class="stack-list"><article v-for="provider in providers" :key="provider.id" class="list-card"><div class="list-card-heading"><div><strong>{{ provider.name }}</strong><span class="cell-subtitle">{{ provider.provider_type }}</span></div><StatusPill :status="provider.status" /></div><button class="secondary-button" type="button" @click="toggleStatus(provider)">{{ provider.status === 'active' ? '停用' : '启用' }}</button></article></div>
        <div v-else class="empty-state compact"><Server :size="22" /><span>暂无平台供应商</span></div>
        <div v-if="hasMore" class="load-more">
          <button class="secondary-button" type="button" :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? '加载中' : '加载更多' }}
          </button>
        </div>
      </section>
      <section class="panel detail-panel">
        <div class="section-heading"><h3>新增平台供应商</h3><Plus :size="16" /></div>
        <form class="form-stack" @submit.prevent="createProvider"><label class="field"><span>名称</span><input v-model="name" type="text" required /></label><label class="field"><span>类型</span><select v-model="providerType"><option value="openai_compatible">OpenAI Compatible</option><option value="ollama">Ollama</option><option value="internal">内部模型</option></select></label><label class="field"><span>Base URL</span><input v-model="baseUrl" type="url" required /></label><label class="field"><span>模型 ID（逗号或换行）</span><textarea v-model="modelIds" rows="3" required /></label><button class="primary-button" type="submit" :disabled="saving"><Plus :size="16" />创建供应商</button></form>
      </section>
    </div>
  </div>
</template>
