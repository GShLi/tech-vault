<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ClipboardList, RefreshCw, Search, ShieldCheck } from 'lucide-vue-next'

import { api, ApiRequestError } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import type { AuditLogView } from '@/types/api'
import { formatDate, shortId } from '@/utils/format'

const team = useTeamStore()
const items = ref<AuditLogView[]>([])
const loading = ref(false)
const error = ref<ApiRequestError | null>(null)
const nextCursor = ref<string | null>(null)
const hasMore = ref(false)
const query = ref('')
const selected = ref<AuditLogView | null>(null)

const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return items.value
  return items.value.filter((item) =>
    [item.action, item.resource_type, item.resource_id, item.actor_id]
      .join(' ')
      .toLowerCase()
      .includes(keyword),
  )
})

async function load(reset = true): Promise<void> {
  if (!team.selectedTeamId) return
  loading.value = true
  error.value = null
  try {
    const page = await api.listAudit(team.selectedTeamId, reset ? null : nextCursor.value)
    items.value = reset ? page.data : [...items.value, ...page.data]
    nextCursor.value = page.meta.next_cursor
    hasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

async function showDetail(item: AuditLogView): Promise<void> {
  if (!team.selectedTeamId) return
  try {
    selected.value = await api.getAudit(team.selectedTeamId, item.id)
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

onMounted(load)
watch(() => team.selectedTeamId, () => load())
</script>

<template>
  <div>
    <div class="page-header"><div><h2>审计日志</h2><p>追踪团队内的管理操作、索引变更和敏感动作。</p></div><button class="secondary-button" type="button" :disabled="loading" @click="load()"><RefreshCw :size="16" />刷新</button></div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span><button class="inline-link" type="button" @click="load()">重试</button></div>
    <section class="panel toolbar-panel"><label class="search-field"><Search :size="16" /><input v-model="query" type="search" placeholder="筛选动作、资源或操作人" /></label><span class="muted-text">共 {{ filtered.length }} 条当前记录</span></section>
    <div v-if="loading && !items.length" class="panel loading-state"><a-spin /><span>正在加载审计日志</span></div>
    <div v-else-if="!filtered.length" class="panel empty-state"><ClipboardList :size="28" /><h3>暂无审计记录</h3><p>团队管理操作会产生审计事件。</p></div>
    <div v-else class="panel">
      <div class="table-wrap"><table><thead><tr><th>动作</th><th>资源</th><th>操作人</th><th>时间</th><th class="actions-column">操作</th></tr></thead><tbody><tr v-for="item in filtered" :key="item.id"><td data-label="动作"><strong>{{ item.action }}</strong><span class="cell-subtitle">{{ item.id }}</span></td><td data-label="资源">{{ item.resource_type }} · {{ shortId(item.resource_id) }}</td><td data-label="操作人">{{ shortId(item.actor_id) }}</td><td data-label="时间">{{ formatDate(item.created_at) }}</td><td data-label="操作"><button class="ghost-button" type="button" @click="showDetail(item)">详情</button></td></tr></tbody></table></div>
      <div v-if="hasMore" class="load-more"><button class="secondary-button" type="button" :disabled="loading" @click="load(false)">加载更多</button></div>
    </div>

    <div v-if="selected" class="modal-backdrop" @click.self="selected = null">
      <div class="modal-panel wide-modal">
        <div class="modal-heading"><div class="section-heading"><ShieldCheck :size="18" /><h3>审计详情</h3></div><button class="icon-button" type="button" @click="selected = null">×</button></div>
        <dl class="detail-grid"><div><dt>动作</dt><dd>{{ selected.action }}</dd></div><div><dt>资源类型</dt><dd>{{ selected.resource_type }}</dd></div><div><dt>资源 ID</dt><dd>{{ selected.resource_id }}</dd></div><div><dt>操作人</dt><dd>{{ selected.actor_id }}</dd></div><div><dt>时间</dt><dd>{{ formatDate(selected.created_at) }}</dd></div></dl>
        <pre class="json-block">{{ JSON.stringify(selected.details, null, 2) }}</pre>
      </div>
    </div>
  </div>
</template>
