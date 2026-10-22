<script setup lang="ts">
import { ApiRequestError, api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Empty as AEmpty,
  Message,
  Tag as ATag,
} from '@arco-design/web-vue'

import { statusLabel } from '@/utils/format'
import { onMounted, ref } from 'vue'
import { RefreshCw, Server } from 'lucide-vue-next'

import ProviderCreateForm from '@/components/ProviderCreateForm.vue'
import { statusColor } from '@/utils/status'
import type { ModelProvider } from '@/types/api'
import { providerTypeLabel } from '@/utils/providers'

const providers = ref<ModelProvider[]>([])
const loading = ref(false)
const loadingMore = ref(false)
const nextCursor = ref<string | null>(null)
const hasMore = ref(false)
const error = ref<ApiRequestError | null>(null)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const page = await api.listAdminProviders()
    providers.value = page.data
    nextCursor.value = page.meta.next_cursor
    hasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
  } finally {
    loadingMore.value = false
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
    error.value = normalizeApiError(caught)
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>供应商准入</h2>
        <p>管理所有团队可继承的平台模型供应商。</p>
      </div>
      <a-button
        :disabled="loading"
        @click="load"
        type="secondary"
        html-type="button"
      >
        <RefreshCw :size="16" />
        刷新
      </a-button>
    </div>
    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </a-alert>
    <div class="split-grid">
      <a-card class="page-card">
        <div class="section-heading">
          <h3>平台供应商</h3>
          <span class="muted-text">{{ providers.length }} 个</span>
        </div>
        <div v-if="providers.length" class="stack-list">
          <article
            v-for="provider in providers"
            :key="provider.id"
            class="list-card"
          >
            <div class="list-card-heading">
              <div>
                <strong>{{ provider.name }}</strong>
                <span class="cell-subtitle">
                  {{ providerTypeLabel(provider.provider_type) }}
                  <template v-if="provider.api_key_masked">
                    · API Key {{ provider.api_key_masked }}
                  </template>
                </span>
                <span v-if="provider.base_url" class="cell-subtitle">
                  {{ provider.base_url }}
                </span>
              </div>
              <a-tag :color="statusColor(provider.status)">
                {{ statusLabel(provider.status) }}
              </a-tag>
            </div>
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
            <a-button
              @click="toggleStatus(provider)"
              type="secondary"
              html-type="button"
            >
              {{ provider.status === 'active' ? '停用' : '启用' }}
            </a-button>
          </article>
        </div>
        <a-empty v-else class="page-empty">
          <template #image><Server :size="22" /></template>
          <span>暂无平台供应商</span>
        </a-empty>
        <div v-if="hasMore" class="load-more">
          <a-button
            :disabled="loadingMore"
            @click="loadMore"
            type="secondary"
            html-type="button"
          >
            {{ loadingMore ? '加载中' : '加载更多' }}
          </a-button>
        </div>
      </a-card>
      <a-card class="page-card">
        <ProviderCreateForm admin @created="load" />
      </a-card>
    </div>
  </div>
</template>
