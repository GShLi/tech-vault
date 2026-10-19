<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { BookOpen, FileText } from 'lucide-vue-next'

import { api, ApiRequestError } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import type { DocumentView, ChunkView } from '@/api/client'

const route = useRoute()
const team = useTeamStore()

const document = ref<DocumentView | null>(null)
const chunks = ref<ChunkView[]>([])
const error = ref<ApiRequestError | null>(null)
const loading = ref(false)

const statusLabels: Record<string, string> = {
  active: '使用中',
  building: '构建中',
  deleting: '删除中',
  deleted: '已删除',
  failed: '失败',
}

async function load(): Promise<void> {
  const documentId = route.params.documentId as string
  if (!team.selectedTeamId || !documentId) return

  loading.value = true
  error.value = null
  try {
    document.value = await api.getDoc(team.selectedTeamId, documentId)
    const page = await api.listChunks(team.selectedTeamId, documentId)
    chunks.value = page.data
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

async function toggleChunk(chunk: ChunkView): Promise<void> {
  if (!team.selectedTeamId) return
  try {
    if (chunk.status === 'enabled') {
      await api.disableChunks(team.selectedTeamId, [chunk.id])
    } else {
      await api.enableChunks(team.selectedTeamId, [chunk.id])
    }
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

onMounted(load)
watch(() => route.params.documentId, load)
</script>

<template>
  <div>
    <div v-if="error" class="error-banner" role="alert">
      <strong>{{ error.message }}</strong>
    </div>

    <div v-if="loading && !document" class="panel loading-state">
      <a-spin />
      <span>正在加载文档</span>
    </div>

    <div v-else-if="document" class="panel" style="padding:22px">
      <div class="doc-meta">
        <FileText :size="20" />
        <h2>{{ document.file_name }}</h2>
        <a-tag :color="document.doc_status === 'active' ? 'green' : 'gray'">
          {{ statusLabels[document.doc_status] ?? document.doc_status }}
        </a-tag>
        <span class="muted-text">v{{ document.version }}</span>
        <span class="muted-text">{{ document.source_type }}</span>
      </div>

      <h3 style="margin-top:24px">Chunks</h3>
      <div v-if="chunks.length" class="table-wrap" style="margin-top:12px">
        <table>
          <thead>
            <tr>
              <th>内容</th>
              <th>结构路径</th>
              <th>状态</th>
              <th v-if="team.canManage">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="chunk in chunks" :key="chunk.id">
              <td>
                <div style="max-width:500px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                  {{ chunk.content.slice(0, 120) }}{{ chunk.content.length > 120 ? '…' : '' }}
                </div>
              </td>
              <td class="muted-text">{{ (chunk.heading_path || []).join(' / ') || '—' }}</td>
              <td>
                <a-tag :color="chunk.status === 'enabled' ? 'green' : 'red'">
                  {{ chunk.status === 'enabled' ? '启用' : '禁用' }}
                </a-tag>
              </td>
              <td v-if="team.canManage">
                <button class="ghost-button" type="button" @click="toggleChunk(chunk)">
                  {{ chunk.status === 'enabled' ? '禁用' : '启用' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-state">
        <BookOpen :size="22" />
        <span>暂无 Chunk 数据</span>
      </div>
    </div>
  </div>
</template>
