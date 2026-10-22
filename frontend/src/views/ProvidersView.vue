<script setup lang="ts">
import { ApiRequestError, api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Empty as AEmpty,
  Message,
  Table as ATable,
  TableColumn as ATableColumn,
  Tag as ATag,
} from '@arco-design/web-vue'

import { onMounted, ref, watch } from 'vue'
import { Activity, RefreshCw, Server, TestTube2 } from 'lucide-vue-next'

import ProviderCreateForm from '@/components/ProviderCreateForm.vue'
import { statusColor } from '@/utils/status'
import { useTeamStore } from '@/stores/team'
import type { ModelCall, ModelProvider } from '@/types/api'
import { formatDate, statusLabel } from '@/utils/format'
import { providerTypeLabel } from '@/utils/providers'

const team = useTeamStore()
const providers = ref<ModelProvider[]>([])
const calls = ref<ModelCall[]>([])
const loading = ref(false)
const loadingMoreProviders = ref(false)
const loadingMoreCalls = ref(false)
const providersNextCursor = ref<string | null>(null)
const callsNextCursor = ref<string | null>(null)
const providersHasMore = ref(false)
const callsHasMore = ref(false)
const error = ref<ApiRequestError | null>(null)

async function load(): Promise<void> {
  if (!team.selectedTeamId) return
  loading.value = true
  error.value = null
  try {
    const [providerPage, callPage] = await Promise.all([
      api.listProviders(team.selectedTeamId),
      api.listModelCalls(team.selectedTeamId),
    ])
    providers.value = providerPage.data
    calls.value = callPage.data
    providersNextCursor.value = providerPage.meta.next_cursor
    callsNextCursor.value = callPage.meta.next_cursor
    providersHasMore.value = providerPage.meta.has_more
    callsHasMore.value = callPage.meta.has_more
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

async function loadMoreCalls(): Promise<void> {
  if (!team.selectedTeamId || !callsNextCursor.value) return
  loadingMoreCalls.value = true
  try {
    const page = await api.listModelCalls(
      team.selectedTeamId,
      callsNextCursor.value,
    )
    calls.value = [...calls.value, ...page.data]
    callsNextCursor.value = page.meta.next_cursor
    callsHasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    loadingMoreCalls.value = false
  }
}

async function testProvider(provider: ModelProvider): Promise<void> {
  if (!team.selectedTeamId) return
  try {
    const result = await api.testProvider(team.selectedTeamId, provider.id)
    Message.success(`连接测试结果：${result.status}`)
  } catch (caught) {
    error.value = normalizeApiError(caught)
  }
}

onMounted(load)
watch(() => team.selectedTeamId, load)
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>模型供应商</h2>
        <p>查看团队可用供应商、模型列表和最近调用记录。</p>
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
          <h3>可用供应商</h3>
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
                  {{ providerTypeLabel(provider.provider_type) }} ·
                  {{ provider.base_url || '使用默认地址' }}
                </span>
              </div>
              <a-tag :color="statusColor(provider.status)">
                {{ statusLabel(provider.status) }}
              </a-tag>
            </div>
            <span v-if="provider.api_key_masked" class="cell-subtitle">
              API Key {{ provider.api_key_masked }}
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
            <div class="row-actions" v-if="team.canManage">
              <a-button
                @click="testProvider(provider)"
                type="text"
                html-type="button"
              >
                <TestTube2 :size="14" />
                测试连接
              </a-button>
            </div>
          </article>
        </div>
        <a-empty v-else class="page-empty">
          <template #image><Server :size="22" /></template>
          <span>暂无可用供应商</span>
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
      </a-card>
      <a-card class="page-card">
        <ProviderCreateForm
          :team-id="team.selectedTeamId"
          :can-manage="team.canManage"
          @created="load"
        />
      </a-card>
    </div>

    <a-card class="page-card">
      <div class="section-heading">
        <h3>最近模型调用</h3>
        <Activity :size="16" />
      </div>
      <div v-if="calls.length" class="table-wrap">
        <a-table
          :data="calls"
          :pagination="false"
          row-key="id"
          :bordered="false"
          :scroll="{ x: 960 }"
        >
          <template #columns>
            <a-table-column title="模型">
              <template #cell="{ record: call }">{{ call.model_id }}</template>
            </a-table-column>
            <a-table-column title="用途">
              <template #cell="{ record: call }">{{ call.purpose }}</template>
            </a-table-column>
            <a-table-column title="分类">
              <template #cell="{ record: call }">
                {{ call.classification }}
              </template>
            </a-table-column>
            <a-table-column title="外部调用">
              <template #cell="{ record: call }">
                {{ call.external ? '是' : '否' }}
              </template>
            </a-table-column>
            <a-table-column title="耗时">
              <template #cell="{ record: call }">
                {{ call.latency_ms }} ms
              </template>
            </a-table-column>
            <a-table-column title="成本">
              <template #cell="{ record: call }">
                {{ call.cost_micros }} µs
              </template>
            </a-table-column>
            <a-table-column title="时间" :width="180">
              <template #cell="{ record: call }">
                {{ formatDate(call.created_at) }}
              </template>
            </a-table-column>
          </template>
        </a-table>
      </div>
      <a-empty v-else class="page-empty">
        <template #image><Activity :size="22" /></template>
        <span>暂无模型调用记录</span>
      </a-empty>
      <div v-if="callsHasMore" class="load-more">
        <a-button
          :disabled="loadingMoreCalls"
          @click="loadMoreCalls"
          type="secondary"
          html-type="button"
        >
          {{ loadingMoreCalls ? '加载中' : '加载更多调用记录' }}
        </a-button>
      </div>
    </a-card>
  </div>
</template>
