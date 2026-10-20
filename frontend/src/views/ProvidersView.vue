<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { Activity, RefreshCw, Server, TestTube2 } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
import ProviderCreateForm from '@/components/ProviderCreateForm.vue'
import StatusPill from '@/components/StatusPill.vue'
import { useTeamStore } from '@/stores/team'
import type { ModelCall, ModelProvider } from '@/types/api'
import { formatDate } from '@/utils/format'
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

async function loadMoreCalls(): Promise<void> {
  if (!team.selectedTeamId || !callsNextCursor.value) return
  loadingMoreCalls.value = true
  try {
    const page = await api.listModelCalls(team.selectedTeamId, callsNextCursor.value)
    calls.value = [...calls.value, ...page.data]
    callsNextCursor.value = page.meta.next_cursor
    callsHasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
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
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

onMounted(load)
watch(() => team.selectedTeamId, load)
</script>

<template>
  <div>
    <div class="page-header"><div><h2>模型供应商</h2><p>查看团队可用供应商、模型列表和最近调用记录。</p></div><button class="secondary-button" type="button" :disabled="loading" @click="load"><RefreshCw :size="16" />刷新</button></div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span></div>
    <div class="split-grid">
      <section class="panel detail-panel">
        <div class="section-heading"><h3>可用供应商</h3><span class="muted-text">{{ providers.length }} 个</span></div>
        <div v-if="providers.length" class="stack-list">
          <article v-for="provider in providers" :key="provider.id" class="list-card">
            <div class="list-card-heading"><div><strong>{{ provider.name }}</strong><span class="cell-subtitle">{{ providerTypeLabel(provider.provider_type) }} · {{ provider.base_url || '使用默认地址' }}</span></div><StatusPill :status="provider.status" /></div>
            <span v-if="provider.api_key_masked" class="cell-subtitle">API Key {{ provider.api_key_masked }}</span>
            <div class="tag-list"><span v-for="model in provider.model_ids || []" :key="model" class="tag">{{ model }}</span><span v-if="!(provider.model_ids || []).length" class="muted-text">未配置模型</span></div>
            <div class="row-actions" v-if="team.canManage"><button class="ghost-button" type="button" @click="testProvider(provider)"><TestTube2 :size="14" />测试连接</button></div>
          </article>
        </div>
        <div v-else class="empty-state compact"><Server :size="22" /><span>暂无可用供应商</span></div>
        <div v-if="providersHasMore" class="load-more">
          <button class="secondary-button" type="button" :disabled="loadingMoreProviders" @click="loadMoreProviders">
            {{ loadingMoreProviders ? '加载中' : '加载更多供应商' }}
          </button>
        </div>
      </section>
      <section class="panel detail-panel">
        <ProviderCreateForm
          :team-id="team.selectedTeamId"
          :can-manage="team.canManage"
          @created="load"
        />
      </section>
    </div>

    <section class="panel detail-panel">
      <div class="section-heading"><h3>最近模型调用</h3><Activity :size="16" /></div>
      <div v-if="calls.length" class="table-wrap"><table><thead><tr><th>模型</th><th>用途</th><th>分类</th><th>外部调用</th><th>耗时</th><th>成本</th><th>时间</th></tr></thead><tbody><tr v-for="call in calls" :key="call.id"><td>{{ call.model_id }}</td><td>{{ call.purpose }}</td><td>{{ call.classification }}</td><td>{{ call.external ? '是' : '否' }}</td><td>{{ call.latency_ms }} ms</td><td>{{ call.cost_micros }} µs</td><td>{{ formatDate(call.created_at) }}</td></tr></tbody></table></div>
      <div v-else class="empty-state compact"><Activity :size="22" /><span>暂无模型调用记录</span></div>
      <div v-if="callsHasMore" class="load-more">
        <button class="secondary-button" type="button" :disabled="loadingMoreCalls" @click="loadMoreCalls">
          {{ loadingMoreCalls ? '加载中' : '加载更多调用记录' }}
        </button>
      </div>
    </section>
  </div>
</template>
