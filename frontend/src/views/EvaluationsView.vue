<script setup lang="ts">
import { ApiRequestError, api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Empty as AEmpty,
  Form as AForm,
  FormItem as AFormItem,
  Input as AInput,
  Message,
  Modal as AModal,
  Spin as ASpin,
  Table as ATable,
  TableColumn as ATableColumn,
  Textarea as ATextarea,
} from '@arco-design/web-vue'

import { onMounted, ref, watch } from 'vue'
import { BarChart3, Plus, RefreshCw } from 'lucide-vue-next'

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
    error.value = normalizeApiError(caught)
  } finally {
    loading.value = false
  }
}

async function loadMore(): Promise<void> {
  if (!team.selectedTeamId || !nextCursor.value) return
  loadingMore.value = true
  try {
    const page = await api.listEvalDatasets(
      team.selectedTeamId,
      nextCursor.value,
    )
    datasets.value = [...datasets.value, ...page.data]
    nextCursor.value = page.meta.next_cursor
    hasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
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
      <a-button
        v-if="team.canManage"
        data-testid="eval-create-open"
        @click="showCreate = true"
        type="primary"
        html-type="button"
      >
        <Plus :size="16" />
        新建黄金集
      </a-button>
    </div>

    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
      <a-button @click="load" type="text" html-type="button">重试</a-button>
    </a-alert>

    <div v-if="loading && !datasets.length" class="panel loading-state">
      <a-spin />
      <span>正在加载黄金集</span>
    </div>
    <a-empty v-else-if="!datasets.length" class="page-empty">
      <template #image><BarChart3 :size="28" /></template>
      <h3>暂无黄金集</h3>
      <p>创建黄金集并加入查询样本后即可开始评测。</p>
    </a-empty>
    <div v-else class="panel">
      <div class="table-wrap">
        <a-table
          :data="datasets"
          :pagination="false"
          row-key="id"
          :bordered="false"
          :scroll="{ x: 960 }"
        >
          <template #columns>
            <a-table-column title="名称" :width="240">
              <template #cell="{ record: dataset }">
                <RouterLink :to="`/evaluations/${dataset.id}`">
                  <strong>{{ dataset.name }}</strong>
                </RouterLink>
                <span class="cell-subtitle">
                  {{ dataset.description || '暂无描述' }}
                </span>
              </template>
            </a-table-column>
            <a-table-column title="样本数">
              <template #cell="{ record: dataset }">
                {{ dataset.case_count }}
              </template>
            </a-table-column>
            <a-table-column title="版本" :width="90">
              <template #cell="{ record: dataset }">
                v{{ dataset.version }}
              </template>
            </a-table-column>
            <a-table-column title="创建时间" :width="180">
              <template #cell="{ record: dataset }">
                {{ formatDate(dataset.created_at) }}
              </template>
            </a-table-column>
            <a-table-column title="操作" :width="180">
              <template #cell="{ record: dataset }">
                <RouterLink
                  :to="`/evaluations/${dataset.id}`"
                  custom
                  v-slot="{ href, navigate }"
                >
                  <a-button type="text" :href="href" @click="navigate">
                    查看详情
                  </a-button>
                </RouterLink>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </div>
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
    </div>

    <a-modal
      v-if="showCreate"
      :visible="true"
      :footer="false"
      unmount-on-close
      @cancel="showCreate = false"
      width="520px"
    >
      <template #title>新建黄金集</template>
      <a-form
        class="form-stack"
        :model="{ name, description }"
        layout="vertical"
        @submit-success="createDataset"
      >
        <a-form-item
          field="name"
          :rules="[{ required: true, message: '请填写名称' }]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>名称</template>
          <a-input
            v-model="name"
            data-testid="eval-name"
            type="text"
            :input-attrs="{ required: true }"
          ></a-input>
        </a-form-item>
        <a-form-item field="description">
          <template #label>描述</template>
          <a-textarea
            v-model="description"
            :textarea-attrs="{ rows: '3' }"
          ></a-textarea>
        </a-form-item>
        <div class="modal-actions">
          <a-button @click="showCreate = false" type="text" html-type="button">
            取消
          </a-button>
          <a-button
            data-testid="eval-create-submit"
            :disabled="saving"
            type="primary"
            html-type="submit"
          >
            <RefreshCw v-if="saving" :size="16" />
            {{ saving ? '创建中' : '创建' }}
          </a-button>
        </div>
      </a-form>
    </a-modal>
  </div>
</template>
