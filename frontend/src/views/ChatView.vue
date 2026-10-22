<script setup lang="ts">
import { ApiRequestError, api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Option as AOption,
  Select as ASelect,
  Textarea as ATextarea,
} from '@arco-design/web-vue'
import { onMounted, ref, watch } from 'vue'
import { MessageSquare, Send } from 'lucide-vue-next'

import { useTeamStore } from '@/stores/team'
import type { KnowledgeBase } from '@/types/api'

const team = useTeamStore()
const knowledgeBases = ref<KnowledgeBase[]>([])
const selectedKbId = ref('')
const error = ref<ApiRequestError | null>(null)

async function loadKnowledgeBases(): Promise<void> {
  if (!team.selectedTeamId) {
    knowledgeBases.value = []
    return
  }
  try {
    const page = await api.listKbs(team.selectedTeamId)
    knowledgeBases.value = page.data
    if (!selectedKbId.value && page.data.length) {
      selectedKbId.value = page.data[0].id
    }
  } catch (caught) {
    error.value = normalizeApiError(caught)
  }
}

onMounted(loadKnowledgeBases)
watch(
  () => team.selectedTeamId,
  () => {
    selectedKbId.value = ''
    loadKnowledgeBases()
  },
)
</script>

<template>
  <div class="chat-layout">
    <section class="chat-main panel">
      <div class="chat-toolbar">
        <div>
          <p>基于当前团队知识库检索并生成带引用的回答。</p>
        </div>
        <a-select v-model="selectedKbId" aria-label="知识库范围">
          <a-option value="" disabled>选择知识库</a-option>
          <a-option v-for="kb in knowledgeBases" :key="kb.id" :value="kb.id">
            {{ kb.name }}
          </a-option>
        </a-select>
      </div>

      <a-alert v-if="error" type="error" class="page-alert">
        <strong>{{ error.message }}</strong>
        <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
      </a-alert>

      <div class="chat-empty">
        <MessageSquare :size="30" />
        <h3>问答工作台</h3>
        <p>文档入库与问答接口接入后，可在此提问并查看引用。</p>
      </div>

      <div class="composer">
        <a-textarea
          disabled
          placeholder="问答接口尚未接入"
          :textarea-attrs="{ 'aria-label': '问题输入', rows: '3' }"
        ></a-textarea>
        <a-button disabled type="primary" html-type="button">
          <Send :size="16" />
          发送
        </a-button>
      </div>
    </section>
  </div>
</template>
