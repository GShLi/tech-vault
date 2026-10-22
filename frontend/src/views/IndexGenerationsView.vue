<script setup lang="ts">
import { ApiRequestError, api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Descriptions as ADescriptions,
  DescriptionsItem as ADescriptionsItem,
  Empty as AEmpty,
  Message,
  Modal as AModal,
  Spin as ASpin,
  Table as ATable,
  TableColumn as ATableColumn,
  Tag as ATag,
} from '@arco-design/web-vue'

import { onMounted, ref, watch } from 'vue'
import {
  CheckCircle2,
  DatabaseZap,
  Play,
  RefreshCcw,
  RotateCcw,
  ShieldCheck,
} from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import { useTeamStore } from '@/stores/team'
import type {
  GenerationReindexResult,
  GenerationValidation,
  IndexGeneration,
} from '@/types/api'
import { formatDate, shortId, statusLabel } from '@/utils/format'

const team = useTeamStore()
const items = ref<IndexGeneration[]>([])
const loading = ref(false)
const actionId = ref('')
const error = ref<ApiRequestError | null>(null)
const nextCursor = ref<string | null>(null)
const hasMore = ref(false)
const validation = ref<GenerationValidation | null>(null)
const validationGeneration = ref('')
const reindexResult = ref<GenerationReindexResult | null>(null)

async function load(reset = true): Promise<void> {
  if (!team.selectedTeamId) return
  loading.value = true
  error.value = null
  try {
    const page = await api.listGenerations(
      team.selectedTeamId,
      reset ? null : nextCursor.value,
    )
    items.value = reset ? page.data : [...items.value, ...page.data]
    nextCursor.value = page.meta.next_cursor
    hasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    loading.value = false
  }
}

async function runAction(
  action: 'validate' | 'activate',
  item: IndexGeneration,
): Promise<void> {
  if (!team.selectedTeamId) return
  actionId.value = item.id
  error.value = null
  try {
    if (action === 'validate') {
      const result = await api.validateGeneration(team.selectedTeamId, item.id)
      validation.value = result
      validationGeneration.value = item.id
      if (result.passed) Message.success('Generation 校验通过')
      else Message.error('Generation 校验失败')
    } else {
      await api.activateGeneration(team.selectedTeamId, item.id)
      Message.success('Generation 已激活')
    }
    await load()
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    actionId.value = ''
  }
}

async function rollback(): Promise<void> {
  if (!team.selectedTeamId) return
  actionId.value = 'rollback'
  error.value = null
  try {
    await api.rollbackGeneration(team.selectedTeamId)
    Message.success('已回滚到上一个已验证 Generation')
    await load()
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    actionId.value = ''
  }
}

async function startReindex(): Promise<void> {
  if (!team.selectedTeamId) return
  actionId.value = 'reindex'
  error.value = null
  try {
    const result = await api.reindexGeneration(team.selectedTeamId)
    reindexResult.value = result
    if (result.run.status === 'queued') Message.success('全量重建任务已排队')
    else if (result.run.status === 'failed') Message.error('全量重建失败')
    else Message.success('全量重建已完成')
    await load()
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    actionId.value = ''
  }
}

async function showValidation(item: IndexGeneration): Promise<void> {
  if (!team.selectedTeamId) return
  try {
    validation.value = await api.getGenerationValidation(
      team.selectedTeamId,
      item.id,
    )
    validationGeneration.value = item.id
  } catch (caught) {
    error.value = normalizeApiError(caught)
  }
}

onMounted(load)
watch(
  () => team.selectedTeamId,
  () => load(),
)
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>索引 Generation</h2>
        <p>全量重建、验证、激活和回滚团队检索索引版本。</p>
      </div>
      <div class="row-actions">
        <a-button
          :disabled="loading"
          @click="load()"
          type="secondary"
          html-type="button"
        >
          <RefreshCcw :size="16" />
          刷新
        </a-button>
        <a-button
          v-if="team.canManage"
          data-testid="generation-reindex"
          :disabled="loading || actionId === 'reindex'"
          @click="startReindex"
          type="secondary"
          html-type="button"
        >
          <Play :size="16" />
          全量重建
        </a-button>
        <a-button
          v-if="team.canManage"
          :disabled="actionId === 'rollback'"
          @click="rollback"
          type="secondary"
          html-type="button"
        >
          <RotateCcw :size="16" />
          回滚
        </a-button>
      </div>
    </div>
    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
      <a-button @click="load()" type="text" html-type="button">重试</a-button>
    </a-alert>
    <a-alert
      v-if="reindexResult"
      data-testid="generation-reindex-status"
      type="info"
      class="page-alert"
    >
      <strong>Generation {{ shortId(reindexResult.generation.id) }}</strong>
      <span>
        运行状态：{{ reindexResult.run.status }} ·
        {{ reindexResult.run.execution_mode }} · 检查 Chunk
        {{ reindexResult.run.checked_chunks }}
      </span>
    </a-alert>
    <div v-if="loading && !items.length" class="panel loading-state">
      <a-spin />
      <span>正在加载索引版本</span>
    </div>
    <a-empty v-else-if="!items.length" class="page-empty">
      <template #image><DatabaseZap :size="28" /></template>
      <h3>暂无索引 Generation</h3>
      <p>文档入库后会创建可验证的索引版本。</p>
    </a-empty>
    <div v-else class="panel">
      <div class="table-wrap">
        <a-table
          :data="items"
          :pagination="false"
          row-key="id"
          :bordered="false"
          :scroll="{ x: 960 }"
        >
          <template #columns>
            <a-table-column title="Generation">
              <template #cell="{ record: item }">
                <strong>{{ shortId(item.id) }}</strong>
                <span class="cell-subtitle">
                  {{ formatDate(item.created_at) }}
                </span>
              </template>
            </a-table-column>
            <a-table-column title="状态" :width="100">
              <template #cell="{ record: item }">
                <a-tag :color="statusColor(item.status)">
                  {{ statusLabel(item.status) }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column title="Chunk" :width="180">
              <template #cell="{ record: item }">
                {{ item.chunk_count }}
              </template>
            </a-table-column>
            <a-table-column title="Embedding 模型">
              <template #cell="{ record: item }">
                {{ item.embedding_model }}
              </template>
            </a-table-column>
            <a-table-column title="校验/激活时间">
              <template #cell="{ record: item }">
                {{ formatDate(item.activated_at || item.validated_at) }}
              </template>
            </a-table-column>
            <a-table-column title="操作" :width="180">
              <template #cell="{ record: item }">
                <div class="row-actions">
                  <a-button
                    @click="showValidation(item)"
                    type="text"
                    html-type="button"
                  >
                    <ShieldCheck :size="14" />
                    校验结果
                  </a-button>
                  <a-button
                    v-if="team.canManage && item.status !== 'active'"
                    :disabled="actionId === item.id"
                    @click="
                      runAction(
                        item.status === 'validated' ? 'activate' : 'validate',
                        item,
                      )
                    "
                    type="text"
                    html-type="button"
                  >
                    <CheckCircle2 :size="14" />
                    {{ item.status === 'validated' ? '激活' : '验证' }}
                  </a-button>
                </div>
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
      v-if="validation"
      :visible="true"
      :footer="false"
      unmount-on-close
      @cancel="validation = null"
      width="520px"
    >
      <template #title>
        <h3>Generation 校验</h3>
        <span class="cell-subtitle">{{ validationGeneration }}</span>
      </template>
      <a-descriptions
        :column="{ xs: 1, sm: 2, lg: 3 }"
        bordered
        class="detail-descriptions"
      >
        <a-descriptions-item label="结果">
          {{ validation.passed ? '通过' : '失败' }}
        </a-descriptions-item>
        <a-descriptions-item label="检查 Chunk">
          {{ validation.checked_chunks }}
        </a-descriptions-item>
        <a-descriptions-item label="校验时间">
          {{ formatDate(validation.validated_at) }}
        </a-descriptions-item>
      </a-descriptions>
      <a-alert v-if="validation.errors.length" type="error" class="page-alert">
        <strong>校验错误</strong>
        <span v-for="item in validation.errors" :key="item">{{ item }}</span>
      </a-alert>
      <a-alert v-else type="info" class="page-alert">
        <strong>所有检查已通过</strong>
        <span>该索引可以激活。</span>
      </a-alert>
    </a-modal>
  </div>
</template>
