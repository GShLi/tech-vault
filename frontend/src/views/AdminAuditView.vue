<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, ClipboardList, RefreshCw, Search, ShieldCheck } from 'lucide-vue-next'

import { api, ApiRequestError } from '@/api/client'
import type { AuditLogView } from '@/types/api'
import { formatDate, shortId } from '@/utils/format'

const route = useRoute()
const items = ref<AuditLogView[]>([])
const selected = ref<AuditLogView | null>(null)
const loading = ref(false)
const error = ref<ApiRequestError | null>(null)
const nextCursor = ref<string | null>(null)
const hasMore = ref(false)
const query = ref('')

const auditId = computed(() => String(route.params.auditId ?? ''))
const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return items.value
  return items.value.filter((item) =>
    [item.action, item.resource_type, item.resource_id, item.actor_id, item.team_id]
      .join(' ')
      .toLowerCase()
      .includes(keyword),
  )
})

async function load(reset = true): Promise<void> {
  return auditId.value ? loadDetail() : loadList(reset)
}

async function loadList(reset: boolean): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const page = await api.listAdminAudit(reset ? null : nextCursor.value)
    items.value = reset ? page.data : [...items.value, ...page.data]
    nextCursor.value = page.meta.next_cursor
    hasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

async function loadDetail(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    selected.value = await api.getAdminAudit(auditId.value)
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => route.params.auditId, () => void load())
</script>

<template>
  <div>
    <div class="page-header">
      <div class="heading-with-back">
        <RouterLink v-if="auditId" class="icon-button" to="/admin/audit" title="返回全局审计">
          <ArrowLeft :size="18" />
        </RouterLink>
        <div>
          <h2>{{ auditId ? '审计详情' : '全局审计' }}</h2>
          <p>{{ auditId ? shortId(auditId) : '跨团队的账户、知识库、文档与索引治理记录。' }}</p>
        </div>
      </div>
      <button v-if="!auditId" class="secondary-button" type="button" :disabled="loading" @click="loadList(true)">
        <RefreshCw :size="16" />刷新
      </button>
    </div>

    <div v-if="error" class="error-banner" role="alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
      <button class="inline-link" type="button" @click="load()">重试</button>
    </div>

    <template v-if="auditId">
      <div v-if="loading && !selected" class="panel loading-state"><a-spin /><span>正在加载审计详情</span></div>
      <section v-else-if="selected" class="panel detail-panel">
        <div class="detail-heading">
          <div class="detail-icon"><ShieldCheck :size="20" /></div>
          <div><h3>{{ selected.action }}</h3><p>{{ formatDate(selected.created_at) }}</p></div>
        </div>
        <dl class="detail-grid">
          <div><dt>团队 ID</dt><dd>{{ selected.team_id }}</dd></div>
          <div><dt>操作人</dt><dd>{{ selected.actor_id }}</dd></div>
          <div><dt>资源类型</dt><dd>{{ selected.resource_type }}</dd></div>
          <div><dt>资源 ID</dt><dd>{{ selected.resource_id }}</dd></div>
        </dl>
        <pre class="json-block">{{ JSON.stringify(selected.details, null, 2) }}</pre>
      </section>
    </template>

    <template v-else>
      <section class="panel toolbar-panel">
        <label class="search-field"><Search :size="16" /><input v-model="query" type="search" placeholder="筛选动作、资源、操作人或团队" /></label>
        <span class="muted-text">当前已加载 {{ filtered.length }} 条</span>
      </section>
      <div v-if="loading && !items.length" class="panel loading-state"><a-spin /><span>正在加载全局审计</span></div>
      <div v-else-if="!filtered.length" class="panel empty-state"><ClipboardList :size="28" /><h3>暂无审计记录</h3><p>平台或团队治理操作会产生审计事件。</p></div>
      <div v-else class="panel">
        <div class="table-wrap">
          <table>
            <thead><tr><th>动作</th><th>团队</th><th>资源</th><th>操作人</th><th>时间</th><th class="actions-column">操作</th></tr></thead>
            <tbody>
              <tr v-for="item in filtered" :key="item.id">
                <td data-label="动作"><strong>{{ item.action }}</strong><span class="cell-subtitle">{{ item.id }}</span></td>
                <td data-label="团队">{{ shortId(item.team_id) }}</td>
                <td data-label="资源">{{ item.resource_type }} · {{ shortId(item.resource_id) }}</td>
                <td data-label="操作人">{{ shortId(item.actor_id) }}</td>
                <td data-label="时间">{{ formatDate(item.created_at) }}</td>
                <td data-label="操作"><RouterLink class="ghost-button" :to="`/admin/audit/${item.id}`">详情</RouterLink></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="hasMore" class="load-more"><button class="secondary-button" type="button" :disabled="loading" @click="loadList(false)">加载更多</button></div>
      </div>
    </template>
  </div>
</template>
