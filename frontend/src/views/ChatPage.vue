<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { MessageSquare, Plus, Trash2 } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import type { ChatView, MessageView } from '@/api/client'

const team = useTeamStore()
const route = useRoute()

const chats = ref<ChatView[]>([])
const currentChat = ref<ChatView | null>(null)
const messages = ref<MessageView[]>([])
const title = ref('')
const selectedKbIds = ref<string[]>([])
const error = ref<ApiRequestError | null>(null)
const loading = ref(false)

async function loadChats(): Promise<void> {
  if (!team.selectedTeamId) return
  try {
    const page = await api.listChats(team.selectedTeamId)
    chats.value = page.data
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

async function selectChat(chat: ChatView): Promise<void> {
  currentChat.value = chat
  if (!team.selectedTeamId) return
  try {
    messages.value = await api.listMessages(team.selectedTeamId, chat.id)
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

async function createChat(): Promise<void> {
  if (!team.selectedTeamId) return
  try {
    const chat = await api.createChat(team.selectedTeamId, title.value.trim() || undefined)
    Message.success('对话已创建')
    title.value = ''
    await loadChats()
    currentChat.value = chat
    messages.value = []
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

async function deleteChat(chat: ChatView): Promise<void> {
  if (!team.selectedTeamId) return
  try {
    await api.deleteChat(team.selectedTeamId, chat.id)
    if (currentChat.value?.id === chat.id) {
      currentChat.value = null
      messages.value = []
    }
    await loadChats()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

onMounted(loadChats)
watch(() => team.selectedTeamId, () => { currentChat.value = null; loadChats() })
</script>

<template>
  <div class="chat-layout">
    <aside class="chat-sidebar panel">
      <div class="chat-sidebar-head">
        <h3>对话</h3>
        <form @submit.prevent="createChat" style="display:flex;gap:6px;margin-top:8px">
          <input v-model="title" placeholder="新对话标题" class="field-input" style="flex:1;height:34px;border:1px solid #cbd5df;border-radius:6px;padding:0 8px;font-size:13px" />
          <button class="primary-button" type="submit" style="height:34px;padding:0 10px">
            <Plus :size="14" />
          </button>
        </form>
      </div>
      <div v-if="chats.length" class="chat-list">
        <div
          v-for="chat in chats" :key="chat.id"
          class="chat-list-item"
          :class="{ active: currentChat?.id === chat.id }"
          @click="selectChat(chat)"
        >
          <MessageSquare :size="15" />
          <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ chat.title }}</span>
          <button class="icon-button" type="button" title="删除" @click.stop="deleteChat(chat)">
            <Trash2 :size="14" />
          </button>
        </div>
      </div>
      <div v-else class="empty-state" style="padding:20px">
        <MessageSquare :size="22" />
        <span>暂无对话</span>
      </div>
    </aside>

    <section class="chat-main panel">
      <div v-if="error" class="error-banner" role="alert">
        <strong>{{ error.message }}</strong>
      </div>

      <div v-if="currentChat" class="chat-header">
        <h3>{{ currentChat.title }}</h3>
      </div>

      <div class="chat-body">
        <div v-if="messages.length">
          <div v-for="msg in messages" :key="msg.id" class="message-bubble" :class="msg.role">
            <div class="message-content">{{ msg.content }}</div>
            <div class="message-meta muted-text">
              <span>{{ msg.role === 'user' ? '你' : '助手' }}</span>
              <span>{{ msg.status }}</span>
            </div>
          </div>
        </div>

        <div v-else-if="currentChat" class="empty-state">
          <MessageSquare :size="24" />
          <span>消息列表为空。SSE 问答功能尚未接入。</span>
        </div>

        <div v-else class="empty-state">
          <MessageSquare :size="24" />
          <span>选择或创建对话开始使用。</span>
        </div>
      </div>

      <div class="composer">
        <textarea rows="2" disabled placeholder="问答接口尚未接入" />
        <button class="primary-button" type="button" disabled>发送</button>
      </div>
    </section>
  </div>
</template>
