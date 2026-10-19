<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { Upload } from 'lucide-vue-next'

import { api, ApiRequestError } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import type { KnowledgeBase } from '@/types/api'

const team = useTeamStore()
const router = useRouter()

const kbs = ref<KnowledgeBase[]>([])
const selectedKbId = ref('')
const file = ref<File | null>(null)
const visibility = ref('team_shared')
const dataClassification = ref('internal')
const error = ref<ApiRequestError | null>(null)
const uploading = ref(false)

async function loadKbs(): Promise<void> {
  if (!team.selectedTeamId) return
  const page = await api.listKbs(team.selectedTeamId)
  kbs.value = page.data
  if (!selectedKbId.value && page.data.length) {
    selectedKbId.value = page.data[0].id
  }
}

function onFileChange(event: Event): void {
  const input = event.target as HTMLInputElement
  file.value = input.files?.[0] ?? null
}

async function upload(): Promise<void> {
  if (!file.value || !selectedKbId.value || !team.selectedTeamId) return
  error.value = null
  uploading.value = true
  try {
    const form = new FormData()
    form.append('team_id', team.selectedTeamId)
    form.append('kb_id', selectedKbId.value)
    form.append('file', file.value)
    form.append('visibility', visibility.value)
    form.append('data_classification', dataClassification.value)

    const token = window.sessionStorage.getItem('techvault.access_token')
    const res = await fetch('/api/v1/docs/upload', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    })
    if (!res.ok) {
      const body = await res.json().catch(() => null)
      throw new ApiRequestError(
        body?.error?.message ?? 'Upload failed',
        body?.error?.code ?? 'UPLOAD_ERROR',
        body?.error?.request_id ?? '',
        res.status,
      )
    }
    Message.success('上传成功')
    router.push('/knowledge-bases')
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    uploading.value = false
  }
}

watch(() => team.selectedTeamId, loadKbs, { immediate: true })
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>上传文档</h2>
        <p>上传 Markdown、TXT、PDF 或 DOCX 文件到当前知识库。</p>
      </div>
    </div>

    <div v-if="error" class="error-banner" role="alert">
      <strong>{{ error.message }}</strong>
    </div>

    <div class="panel" style="max-width:640px; padding:24px">
      <form class="form-stack" @submit.prevent="upload">
        <label class="field">
          <span>目标知识库</span>
          <select v-model="selectedKbId">
            <option value="" disabled>选择知识库</option>
            <option v-for="kb in kbs" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
          </select>
        </label>

        <label class="field">
          <span>可见性</span>
          <select v-model="visibility">
            <option value="team_shared">团队共享</option>
            <option value="private">私有</option>
          </select>
        </label>

        <label class="field">
          <span>数据分类</span>
          <select v-model="dataClassification">
            <option value="internal">内部</option>
            <option value="private">私有</option>
            <option value="public">公开</option>
          </select>
        </label>

        <label class="field">
          <span>选择文件</span>
          <input type="file" accept=".md,.txt,.pdf,.docx" @change="onFileChange" />
        </label>

        <div v-if="file" class="file-summary">
          已选择：{{ file.name }} ({{ (file.size / 1024).toFixed(0) }} KB)
        </div>

        <button
          class="primary-button"
          type="submit"
          :disabled="!file || uploading"
        >
          <Upload :size="16" />
          {{ uploading ? '上传中' : '上传文件' }}
        </button>
      </form>
    </div>
  </div>
</template>
