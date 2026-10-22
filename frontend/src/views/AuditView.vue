<script setup lang="ts">
import { useCursorList } from '@/composables/useCursorList'
import { api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Descriptions as ADescriptions,
  DescriptionsItem as ADescriptionsItem,
  Empty as AEmpty,
  FormItem as AFormItem,
  Input as AInput,
  Modal as AModal,
  Spin as ASpin,
  Table as ATable,
  TableColumn as ATableColumn,
} from '@arco-design/web-vue'

import { computed, ref, watch } from 'vue'
import { ClipboardList, RefreshCw, Search, ShieldCheck } from 'lucide-vue-next'

import { useTeamStore } from '@/stores/team'
import type { AuditLogView } from '@/types/api'
import { formatDate, shortId } from '@/utils/format'

const team = useTeamStore()
const {
  items: items,
  loading,
  error,
  hasMore,
  load,
} = useCursorList<AuditLogView>(
  () => team.selectedTeamId,
  (teamId, cursor) => api.listAudit(teamId, cursor),
)
const query = ref('')
const selected = ref<AuditLogView | null>(null)
watch(
  () => team.selectedTeamId,
  () => {
    selected.value = null
  },
  { flush: 'sync' },
)

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

async function showDetail(item: AuditLogView): Promise<void> {
  if (!team.selectedTeamId) return
  try {
    const teamId = team.selectedTeamId
    const detail = await api.getAudit(teamId, item.id)
    if (teamId === team.selectedTeamId) selected.value = detail
  } catch (caught) {
    error.value = normalizeApiError(caught)
  }
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>审计日志</h2>
        <p>追踪团队内的管理操作、索引变更和敏感动作。</p>
      </div>
      <a-button
        :disabled="loading"
        @click="load()"
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
    <section class="panel toolbar-panel">
      <a-form-item class="search-field">
        <Search :size="16" />
        <a-input
          v-model="query"
          placeholder="筛选动作、资源或操作人"
          type="text"
        ></a-input>
      </a-form-item>
      <span class="muted-text">共 {{ filtered.length }} 条当前记录</span>
    </section>
    <div v-if="loading && !items.length" class="panel loading-state">
      <a-spin />
      <span>正在加载审计日志</span>
    </div>
    <a-empty v-else-if="!filtered.length" class="page-empty">
      <template #image><ClipboardList :size="28" /></template>
      <h3>暂无审计记录</h3>
      <p>团队管理操作会产生审计事件。</p>
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
                <a-button
                  @click="showDetail(item)"
                  type="text"
                  html-type="button"
                >
                  详情
                </a-button>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </div>
      <div v-if="hasMore" class="load-more">
        <a-button
          :disabled="loading"
          @click="load(false)"
          type="secondary"
          html-type="button"
        >
          加载更多
        </a-button>
      </div>
    </div>

    <a-modal
      v-if="selected"
      :visible="true"
      :footer="false"
      unmount-on-close
      @cancel="selected = null"
      width="760px"
    >
      <template #title>
        <ShieldCheck :size="18" />
        <h3>审计详情</h3>
      </template>
      <a-descriptions
        :column="{ xs: 1, sm: 2, lg: 3 }"
        bordered
        class="detail-descriptions"
      >
        <a-descriptions-item label="动作">
          {{ selected.action }}
        </a-descriptions-item>
        <a-descriptions-item label="资源类型">
          {{ selected.resource_type }}
        </a-descriptions-item>
        <a-descriptions-item label="资源 ID">
          {{ selected.resource_id }}
        </a-descriptions-item>
        <a-descriptions-item label="操作人">
          {{ selected.actor_id }}
        </a-descriptions-item>
        <a-descriptions-item label="时间">
          {{ formatDate(selected.created_at) }}
        </a-descriptions-item>
      </a-descriptions>
      <pre class="json-block">{{
        JSON.stringify(selected.details, null, 2)
      }}</pre>
    </a-modal>
  </div>
</template>
