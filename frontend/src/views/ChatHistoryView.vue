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
  Option as AOption,
  Select as ASelect,
  Spin as ASpin,
  Table as ATable,
  TableColumn as ATableColumn,
} from '@arco-design/web-vue'

import { computed, onMounted, ref, watch } from 'vue'
import { MessageSquare, Pencil, Search, Trash2, X } from 'lucide-vue-next'

import { useTeamStore } from '@/stores/team'
import type { ChatView, KnowledgeBase } from '@/types/api'
import { formatDate } from '@/utils/format'

const team = useTeamStore()
const chats = ref<ChatView[]>([])
const knowledgeBases = ref<KnowledgeBase[]>([])
const loading = ref(false)
const loadingMore = ref(false)
const error = ref<ApiRequestError | null>(null)
const nextCursor = ref<string | null>(null)
const hasMore = ref(false)
const query = ref('')
const selectedKbId = ref('')
const timeRange = ref<'all' | '7d' | '30d' | '90d'>('all')
const editing = ref<ChatView | null>(null)
const title = ref('')
const saving = ref(false)
const deleteCandidate = ref<ChatView | null>(null)
const deleting = ref(false)

const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  const cutoff =
    timeRange.value === 'all'
      ? null
      : Date.now() -
        Number(timeRange.value.replace('d', '')) * 24 * 60 * 60 * 1000
  return chats.value.filter((chat) => {
    if (keyword && !chat.title.toLowerCase().includes(keyword)) return false
    if (
      selectedKbId.value &&
      !chat.knowledge_base_ids.includes(selectedKbId.value)
    ) {
      return false
    }
    if (cutoff !== null && new Date(chat.updated_at).getTime() < cutoff)
      return false
    return true
  })
})

function knowledgeBaseLabel(chat: ChatView): string {
  if (!chat.knowledge_base_ids.length) return '全部知识库'
  return chat.knowledge_base_ids
    .map((id) => knowledgeBases.value.find((kb) => kb.id === id)?.name ?? id)
    .join('、')
}

async function load(reset = true): Promise<void> {
  if (!team.selectedTeamId) return
  if (reset) loading.value = true
  else loadingMore.value = true
  error.value = null
  try {
    const page = await api.listChats(
      team.selectedTeamId,
      reset ? null : nextCursor.value,
      20,
    )
    if (reset) {
      chats.value = page.data
    } else {
      const existingIds = new Set(chats.value.map((chat) => chat.id))
      chats.value = [
        ...chats.value,
        ...page.data.filter((chat) => !existingIds.has(chat.id)),
      ]
    }
    nextCursor.value = page.meta.has_more ? page.meta.next_cursor : null
    hasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    if (reset) loading.value = false
    else loadingMore.value = false
  }
}

async function loadKnowledgeBases(): Promise<void> {
  if (!team.selectedTeamId) {
    knowledgeBases.value = []
    return
  }
  try {
    const page = await api.listKbs(team.selectedTeamId, null, 100)
    knowledgeBases.value = page.data
  } catch {
    knowledgeBases.value = []
  }
}

function loadMore(): Promise<void> {
  return load(false)
}

function openRename(chat: ChatView): void {
  editing.value = chat
  title.value = chat.title
}

async function rename(): Promise<void> {
  if (!team.selectedTeamId || !editing.value) return
  saving.value = true
  error.value = null
  try {
    await api.updateChat(
      team.selectedTeamId,
      editing.value.id,
      title.value.trim(),
      editing.value.version,
    )
    Message.success('会话已重命名')
    editing.value = null
    await load()
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    saving.value = false
  }
}

function openDelete(chat: ChatView): void {
  deleteCandidate.value = chat
}

async function confirmDelete(): Promise<void> {
  if (!team.selectedTeamId || !deleteCandidate.value) return
  deleting.value = true
  error.value = null
  try {
    await api.deleteChat(team.selectedTeamId, deleteCandidate.value.id)
    Message.success('会话已删除')
    deleteCandidate.value = null
    await load()
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  void load()
  void loadKnowledgeBases()
})
watch(
  () => team.selectedTeamId,
  () => {
    query.value = ''
    selectedKbId.value = ''
    timeRange.value = 'all'
    void load()
    void loadKnowledgeBases()
  },
)
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>会话历史</h2>
        <p>查看、重命名、删除并继续历史问答会话。</p>
      </div>
      <RouterLink to="/chat" custom v-slot="{ href, navigate }">
        <a-button type="primary" :href="href" @click="navigate">
          新建对话
        </a-button>
      </RouterLink>
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
          placeholder="搜索会话标题"
          type="text"
        ></a-input>
      </a-form-item>
      <a-form-item class="filter-field">
        <template #label>知识库</template>
        <a-select v-model="selectedKbId" data-testid="chat-history-kb-filter">
          <a-option value="">全部知识库</a-option>
          <a-option v-for="kb in knowledgeBases" :key="kb.id" :value="kb.id">
            {{ kb.name }}
          </a-option>
        </a-select>
      </a-form-item>
      <a-form-item class="filter-field">
        <template #label>时间范围</template>
        <a-select v-model="timeRange">
          <a-option value="all">全部时间</a-option>
          <a-option value="7d">最近 7 天</a-option>
          <a-option value="30d">最近 30 天</a-option>
          <a-option value="90d">最近 90 天</a-option>
        </a-select>
      </a-form-item>
      <span class="muted-text">{{ filtered.length }} 个会话</span>
    </section>

    <div v-if="loading && !chats.length" class="panel loading-state">
      <a-spin />
      <span>正在加载会话</span>
    </div>
    <a-empty v-else-if="!filtered.length" class="page-empty">
      <template #image><MessageSquare :size="28" /></template>
      <h3>{{ hasMore ? '当前筛选下暂无会话' : '暂无会话' }}</h3>
      <p>
        {{
          hasMore
            ? '可以继续加载后续会话记录。'
            : '在问答工作台创建对话后会显示在这里。'
        }}
      </p>
      <a-button
        v-if="hasMore"
        data-testid="chat-history-load-more"
        :disabled="loadingMore"
        @click="loadMore"
        type="secondary"
        html-type="button"
      >
        {{ loadingMore ? '正在加载' : '加载更多' }}
      </a-button>
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
            <a-table-column title="标题" :width="240">
              <template #cell="{ record: chat }">
                <RouterLink :to="`/chat/${chat.id}`">
                  <strong>{{ chat.title }}</strong>
                </RouterLink>
              </template>
            </a-table-column>
            <a-table-column title="知识库范围">
              <template #cell="{ record: chat }">
                {{ knowledgeBaseLabel(chat) }}
              </template>
            </a-table-column>
            <a-table-column title="最近更新">
              <template #cell="{ record: chat }">
                {{ formatDate(chat.updated_at) }}
              </template>
            </a-table-column>
            <a-table-column title="操作" :width="180">
              <template #cell="{ record: chat }">
                <div class="row-actions">
                  <RouterLink
                    :to="`/chat/${chat.id}`"
                    custom
                    v-slot="{ href, navigate }"
                  >
                    <a-button type="text" :href="href" @click="navigate">
                      继续
                    </a-button>
                  </RouterLink>
                  <a-button
                    @click="openRename(chat)"
                    type="text"
                    html-type="button"
                  >
                    <Pencil :size="14" />
                    重命名
                  </a-button>
                  <a-button
                    :data-testid="`chat-history-delete-${chat.id}`"
                    @click="openDelete(chat)"
                    type="text"
                    html-type="button"
                    status="danger"
                  >
                    <Trash2 :size="14" />
                    删除
                  </a-button>
                </div>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </div>
      <div v-if="hasMore" class="pagination-actions">
        <a-button
          data-testid="chat-history-load-more"
          :disabled="loadingMore"
          @click="loadMore"
          type="secondary"
          html-type="button"
        >
          {{ loadingMore ? '正在加载' : '加载更多' }}
        </a-button>
      </div>
    </div>

    <a-modal
      v-if="editing"
      :visible="true"
      :footer="false"
      unmount-on-close
      @cancel="editing = null"
      width="520px"
    >
      <template #title>重命名会话</template>
      <a-form
        class="form-stack"
        :model="{ title }"
        layout="vertical"
        @submit-success="rename"
      >
        <a-form-item
          field="title"
          :rules="[{ required: true, message: '请填写标题' }]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>标题</template>
          <a-input
            v-model="title"
            type="text"
            :input-attrs="{ required: true }"
          ></a-input>
        </a-form-item>
        <div class="modal-actions">
          <a-button @click="editing = null" type="text" html-type="button">
            取消
          </a-button>
          <a-button :disabled="saving" type="primary" html-type="submit">
            保存
          </a-button>
        </div>
      </a-form>
    </a-modal>

    <a-modal
      v-if="deleteCandidate"
      :visible="true"
      :footer="false"
      unmount-on-close
      @cancel="deleteCandidate = null"
      width="520px"
    >
      <template #title>确认删除</template>
      <p>删除后该会话及其消息不可恢复，是否继续？</p>
      <div class="modal-actions">
        <a-button
          @click="deleteCandidate = null"
          type="text"
          html-type="button"
        >
          取消
        </a-button>
        <a-button
          data-testid="chat-history-delete-confirm"
          :disabled="deleting"
          @click="confirmDelete"
          type="primary"
          html-type="button"
          status="danger"
        >
          删除
        </a-button>
      </div>
    </a-modal>
  </div>
</template>
