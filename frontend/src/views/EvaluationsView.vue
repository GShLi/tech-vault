<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { BarChart3, Plus, RefreshCw } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import type { EvaluationDataset } from '@/types/api'
import { formatDate } from '@/utils/format'

const team = useTeamStore()
const datasets = ref<EvaluationDataset[]>([])
const loading = ref(false)
const loadingMore = ref(false)
const nextCursor = ref<string | null>(null)
const hasMore = ref(false)
const error = ref<ApiRequestError | null>(null)
const showCreate = ref(false)
const name = ref('')
const description = ref('')
const saving = ref(false)

async function load(): Promise<void> {
  if (!team.selectedTeamId) return
  loading.value = true
  error.value = null
  try {
    const page = await api.listEvalDatasets(team.selectedTeamId)
    datasets.value = page.data
    nextCursor.value = page.meta.next_cursor
    hasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

async function loadMore(): Promise<void> {
  if (!team.selectedTeamId || !nextCursor.value) return
  loadingMore.value = true
  try {
    const page = await api.listEvalDatasets(team.selectedTeamId, nextCursor.value)
    datasets.value = [...datasets.value, ...page.data]
    nextCursor.value = page.meta.next_cursor
    hasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loadingMore.value = false
  }
}

async function createDataset(): Promise<void> {
  if (!team.selectedTeamId) return
  saving.value = true
  error.value = null
  try {
    await api.createEvalDataset({
      team_id: team.selectedTeamId,
      name: name.value.trim(),
      description: description.value.trim() || null,
    })
    Message.success('黄金集已创建')
    showCreate.value = false
    name.value = ''
    description.value = ''
    await load()
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
    <div class="page-header">
      <div>
        <h2>评测与黄金集</h2>
        <p>维护可复用查询集，运行 Recall、MRR、nDCG 等检索评测。</p>
      </div>
      <button
        v-if="team.canManage"
        class="primary-button"
        data-testid="eval-create-open"
        type="button"
        @click="showCreate = true"
      >
        <Plus :size="16" />
        新建黄金集
      </button>
    </div>

    <div v-if="error" class="error-banner" role="alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
      <button class="inline-link" type="button" @click="load">重试</button>
    </div>

    <div v-if="loading && !datasets.length" class="panel loading-state">
      <a-spin />
      <span>正在加载黄金集</span>
    </div>
    <div v-else-if="!datasets.length" class="panel empty-state">
      <BarChart3 :size="28" />
      <h3>暂无黄金集</h3>
      <p>创建黄金集并加入查询样本后即可开始评测。</p>
    </div>
    <div v-else class="panel">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>名称</th>
              <th>样本数</th>
              <th>版本</th>
              <th>创建时间</th>
              <th class="actions-column">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="dataset in datasets" :key="dataset.id">
              <td data-label="名称">
                <RouterLink :to="`/evaluations/${dataset.id}`"><strong>{{ dataset.name }}</strong></RouterLink>
                <span class="cell-subtitle">{{ dataset.description || '暂无描述' }}</span>
              </td>
              <td data-label="样本数">{{ dataset.case_count }}</td>
              <td data-label="版本">v{{ dataset.version }}</td>
              <td data-label="创建时间">{{ formatDate(dataset.created_at) }}</td>
              <td data-label="操作">
                <RouterLink class="ghost-button" :to="`/evaluations/${dataset.id}`">
                  查看详情
                </RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="hasMore" class="load-more">
        <button class="secondary-button" type="button" :disabled="loadingMore" @click="loadMore">
          {{ loadingMore ? '加载中' : '加载更多' }}
        </button>
      </div>
    </div>

    <div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false">
      <div class="modal-panel">
        <div class="modal-heading">
          <h3>新建黄金集</h3>
          <button class="icon-button" type="button" title="关闭" @click="showCreate = false">×</button>
        </div>
        <form class="form-stack" @submit.prevent="createDataset">
          <label class="field">
            <span>名称</span>
            <input v-model="name" data-testid="eval-name" type="text" required />
          </label>
          <label class="field">
            <span>描述</span>
            <textarea v-model="description" rows="3" />
          </label>
          <div class="modal-actions">
            <button class="ghost-button" type="button" @click="showCreate = false">取消</button>
            <button class="primary-button" data-testid="eval-create-submit" type="submit" :disabled="saving">
              <RefreshCw v-if="saving" :size="16" />
              {{ saving ? '创建中' : '创建' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
