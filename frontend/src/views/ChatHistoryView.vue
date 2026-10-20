<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { MessageSquare, Pencil, Search, Trash2, X } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
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
    if (selectedKbId.value && !chat.knowledge_base_ids.includes(selectedKbId.value)) {
      return false
    }
    if (cutoff !== null && new Date(chat.updated_at).getTime() < cutoff) return false
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
    error.value = caught instanceof ApiRequestError ? caught : null
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
    error.value = caught instanceof ApiRequestError ? caught : null
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
    error.value = caught instanceof ApiRequestError ? caught : null
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
      <RouterLink class="primary-button" to="/chat">新建对话</RouterLink>
    </div>

    <div v-if="error" class="error-banner" role="alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
      <button class="inline-link" type="button" @click="load()">重试</button>
    </div>

    <section class="panel toolbar-panel">
      <label class="search-field">
        <Search :size="16" />
        <input v-model="query" type="search" placeholder="搜索会话标题" />
      </label>
      <label class="filter-field">
        <span>知识库</span>
        <select v-model="selectedKbId" data-testid="chat-history-kb-filter">
          <option value="">全部知识库</option>
          <option v-for="kb in knowledgeBases" :key="kb.id" :value="kb.id">
            {{ kb.name }}
          </option>
        </select>
      </label>
      <label class="filter-field">
        <span>时间范围</span>
        <select v-model="timeRange">
          <option value="all">全部时间</option>
          <option value="7d">最近 7 天</option>
          <option value="30d">最近 30 天</option>
          <option value="90d">最近 90 天</option>
        </select>
      </label>
      <span class="muted-text">{{ filtered.length }} 个会话</span>
    </section>

    <div v-if="loading && !chats.length" class="panel loading-state">
      <a-spin />
      <span>正在加载会话</span>
    </div>
    <div v-else-if="!filtered.length" class="panel empty-state">
      <MessageSquare :size="28" />
      <h3>{{ hasMore ? '当前筛选下暂无会话' : '暂无会话' }}</h3>
      <p>
        {{ hasMore ? '可以继续加载后续会话记录。' : '在问答工作台创建对话后会显示在这里。' }}
      </p>
      <button
        v-if="hasMore"
        class="secondary-button"
        type="button"
        data-testid="chat-history-load-more"
        :disabled="loadingMore"
        @click="loadMore"
      >
        {{ loadingMore ? '正在加载' : '加载更多' }}
      </button>
    </div>
    <div v-else class="panel">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>标题</th>
              <th>知识库范围</th>
              <th>最近更新</th>
              <th class="actions-column">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="chat in filtered" :key="chat.id">
              <td data-label="标题">
                <RouterLink :to="`/chat/${chat.id}`"><strong>{{ chat.title }}</strong></RouterLink>
              </td>
              <td data-label="知识库范围">{{ knowledgeBaseLabel(chat) }}</td>
              <td data-label="最近更新">{{ formatDate(chat.updated_at) }}</td>
              <td data-label="操作">
                <div class="row-actions">
                  <RouterLink class="ghost-button" :to="`/chat/${chat.id}`">继续</RouterLink>
                  <button class="ghost-button" type="button" @click="openRename(chat)">
                    <Pencil :size="14" />重命名
                  </button>
                  <button
                    class="ghost-button danger-text"
                    type="button"
                    :data-testid="`chat-history-delete-${chat.id}`"
                    @click="openDelete(chat)"
                  >
                    <Trash2 :size="14" />删除
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="hasMore" class="pagination-actions">
        <button
          class="secondary-button"
          type="button"
          data-testid="chat-history-load-more"
          :disabled="loadingMore"
          @click="loadMore"
        >
          {{ loadingMore ? '正在加载' : '加载更多' }}
        </button>
      </div>
    </div>

    <div v-if="editing" class="modal-backdrop" @click.self="editing = null">
      <div class="modal-panel">
        <div class="modal-heading">
          <h3>重命名会话</h3>
          <button class="icon-button" type="button" @click="editing = null">×</button>
        </div>
        <form class="form-stack" @submit.prevent="rename">
          <label class="field">
            <span>标题</span>
            <input v-model="title" type="text" required />
          </label>
          <div class="modal-actions">
            <button class="ghost-button" type="button" @click="editing = null">取消</button>
            <button class="primary-button" type="submit" :disabled="saving">保存</button>
          </div>
        </form>
      </div>
    </div>

    <div v-if="deleteCandidate" class="modal-backdrop" @click.self="deleteCandidate = null">
      <div class="modal-panel">
        <div class="modal-heading">
          <h3>确认删除</h3>
          <button class="icon-button" type="button" @click="deleteCandidate = null">
            <X :size="16" />
          </button>
        </div>
        <p>删除后该会话及其消息不可恢复，是否继续？</p>
        <div class="modal-actions">
          <button class="ghost-button" type="button" @click="deleteCandidate = null">取消</button>
          <button
            class="danger-button"
            type="button"
            data-testid="chat-history-delete-confirm"
            :disabled="deleting"
            @click="confirmDelete"
          >
            删除
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
