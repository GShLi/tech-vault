<script setup lang="ts">
import { ApiRequestError, api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Descriptions as ADescriptions,
  DescriptionsItem as ADescriptionsItem,
  Empty as AEmpty,
  FormItem as AFormItem,
  Input as AInput,
  Spin as ASpin,
  Table as ATable,
  TableColumn as ATableColumn,
} from '@arco-design/web-vue'

import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  ArrowLeft,
  ClipboardList,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-vue-next'

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
    [
      item.action,
      item.resource_type,
      item.resource_id,
      item.actor_id,
      item.team_id,
    ]
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
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(
  () => route.params.auditId,
  () => void load(),
)
</script>

<template>
  <div>
    <div class="page-header">
      <div class="heading-with-back">
        <RouterLink
          v-if="auditId"
          to="/admin/audit"
          custom
          v-slot="{ href, navigate }"
        >
          <a-button
            type="text"
            :href="href"
            @click="navigate"
            title="返回全局审计"
          >
            <ArrowLeft :size="18" />
          </a-button>
        </RouterLink>
        <div>
          <h2>{{ auditId ? '审计详情' : '全局审计' }}</h2>
          <p>
            {{
              auditId
                ? shortId(auditId)
                : '跨团队的账户、知识库、文档与索引治理记录。'
            }}
          </p>
        </div>
      </div>
      <a-button
        v-if="!auditId"
        :disabled="loading"
        @click="loadList(true)"
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
      <a-button @click="load()" type="text" html-type="button">重试</a-button>
    </a-alert>

    <template v-if="auditId">
      <div v-if="loading && !selected" class="panel loading-state">
        <a-spin />
        <span>正在加载审计详情</span>
      </div>
      <a-card v-else-if="selected" class="page-card">
        <div class="detail-heading">
          <div class="detail-icon"><ShieldCheck :size="20" /></div>
          <div>
            <h3>{{ selected.action }}</h3>
            <p>{{ formatDate(selected.created_at) }}</p>
          </div>
        </div>
        <a-descriptions
          :column="{ xs: 1, sm: 2, lg: 3 }"
          bordered
          class="detail-descriptions"
        >
          <a-descriptions-item label="团队 ID">
            {{ selected.team_id }}
          </a-descriptions-item>
          <a-descriptions-item label="操作人">
            {{ selected.actor_id }}
          </a-descriptions-item>
          <a-descriptions-item label="资源类型">
            {{ selected.resource_type }}
          </a-descriptions-item>
          <a-descriptions-item label="资源 ID">
            {{ selected.resource_id }}
          </a-descriptions-item>
        </a-descriptions>
        <pre class="json-block">{{
          JSON.stringify(selected.details, null, 2)
        }}</pre>
      </a-card>
    </template>

    <template v-else>
      <section class="panel toolbar-panel">
        <a-form-item class="search-field">
          <Search :size="16" />
          <a-input
            v-model="query"
            placeholder="筛选动作、资源、操作人或团队"
            type="text"
          ></a-input>
        </a-form-item>
        <span class="muted-text">当前已加载 {{ filtered.length }} 条</span>
      </section>
      <div v-if="loading && !items.length" class="panel loading-state">
        <a-spin />
        <span>正在加载全局审计</span>
      </div>
      <a-empty v-else-if="!filtered.length" class="page-empty">
        <template #image><ClipboardList :size="28" /></template>
        <h3>暂无审计记录</h3>
        <p>平台或团队治理操作会产生审计事件。</p>
      </a-empty>
      <div v-else class="panel">
        <div class="table-wrap">
          <a-table
            :data="filtered"
            :pagination="false"
            row-key="id"
            :bordered="false"
            :scroll="{ x: 960 }"
          >
            <template #columns>
              <a-table-column title="动作">
                <template #cell="{ record: item }">
                  <strong>{{ item.action }}</strong>
                  <span class="cell-subtitle">{{ item.id }}</span>
                </template>
              </a-table-column>
              <a-table-column title="团队">
                <template #cell="{ record: item }">
                  {{ shortId(item.team_id) }}
                </template>
              </a-table-column>
              <a-table-column title="资源">
                <template #cell="{ record: item }">
                  {{ item.resource_type }} · {{ shortId(item.resource_id) }}
                </template>
              </a-table-column>
              <a-table-column title="操作人">
                <template #cell="{ record: item }">
                  {{ shortId(item.actor_id) }}
                </template>
              </a-table-column>
              <a-table-column title="时间" :width="180">
                <template #cell="{ record: item }">
                  {{ formatDate(item.created_at) }}
                </template>
              </a-table-column>
              <a-table-column title="操作" :width="180">
                <template #cell="{ record: item }">
                  <RouterLink
                    :to="`/admin/audit/${item.id}`"
                    custom
                    v-slot="{ href, navigate }"
                  >
                    <a-button type="text" :href="href" @click="navigate">
                      详情
                    </a-button>
                  </RouterLink>
                </template>
              </a-table-column>
            </template>
          </a-table>
        </div>
        <div v-if="hasMore" class="load-more">
          <a-button
            :disabled="loading"
            @click="loadList(false)"
            type="secondary"
            html-type="button"
          >
            加载更多
          </a-button>
        </div>
      </div>
    </template>
  </div>
</template>
