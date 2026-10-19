<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { Archive, BookOpen, Pencil, Plus } from 'lucide-vue-next'
import { Message, Modal } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import type { KnowledgeBase } from '@/types/api'

const team = useTeamStore()

const items = ref<KnowledgeBase[]>([])
const loading = ref(false)
const error = ref<ApiRequestError | null>(null)
const nextCursor = ref<string | null>(null)
const hasMore = ref(false)
const modalVisible = ref(false)
const editing = ref<KnowledgeBase | null>(null)
const name = ref('')
const description = ref('')
const saving = ref(false)

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function policyLabel(value: string): string {
  const labels: Record<string, string> = {
    local_only: '仅本地模型',
    external_allowed: '允许外部模型',
    external_required: '仅外部模型',
  }
  return labels[value] ?? value
}

async function load(reset = true): Promise<void> {
  const teamId = team.selectedTeamId
  if (!teamId) {
    items.value = []
    return
  }

  loading.value = true
  error.value = null
  try {
    const page = await api.listKbs(
      teamId,
      reset ? null : nextCursor.value,
    )
    items.value = reset ? page.data : [...items.value, ...page.data]
    nextCursor.value = page.meta.next_cursor
    hasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  editing.value = null
  name.value = ''
  description.value = ''
  modalVisible.value = true
}

function openEdit(kb: KnowledgeBase): void {
  editing.value = kb
  name.value = kb.name
  description.value = kb.description ?? ''
  modalVisible.value = true
}

async function save(): Promise<void> {
  const teamId = team.selectedTeamId
  if (!teamId) {
    return
  }

  saving.value = true
  error.value = null
  try {
    if (editing.value) {
      await api.updateKb(
        {
          team_id: teamId,
          kb_id: editing.value.id,
          name: name.value.trim(),
          description: description.value.trim() || null,
        },
        editing.value.version,
      )
      Message.success('知识库已更新')
    } else {
      await api.createKb({
        team_id: teamId,
        name: name.value.trim(),
        description: description.value.trim() || null,
      })
      Message.success('知识库已创建')
    }
    modalVisible.value = false
    await load(true)
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    saving.value = false
  }
}

function archive(kb: KnowledgeBase): void {
  const teamId = team.selectedTeamId
  if (!teamId) {
    return
  }

  Modal.confirm({
    title: '归档知识库',
    content: `确认归档「${kb.name}」？归档后将不再出现在可用列表中。`,
    okText: '归档',
    cancelText: '取消',
    onOk: async () => {
      try {
        await api.archiveKb(
          { team_id: teamId, kb_id: kb.id },
          kb.version,
        )
        Message.success('知识库已归档')
        await load(true)
      } catch (caught) {
        error.value = caught instanceof ApiRequestError ? caught : null
      }
    },
  })
}

onMounted(() => load(true))
watch(() => team.selectedTeamId, () => load(true))
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <p>团队共享资料与文档集合。</p>
      </div>
      <button
        v-if="team.canManage"
        class="primary-button"
        data-testid="kb-create-open"
        type="button"
        @click="openCreate"
      >
        <Plus :size="16" />
        新建知识库
      </button>
    </div>

    <div v-if="error" class="error-banner" role="alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
      <button class="inline-link" type="button" @click="load(true)">重试</button>
    </div>

    <div v-if="loading && !items.length" class="panel loading-state">
      <a-spin />
      <span>正在加载知识库</span>
    </div>

    <div v-else-if="!items.length" class="panel empty-state">
      <BookOpen :size="28" />
      <h3>暂无知识库</h3>
      <p v-if="team.canManage">创建第一个知识库，开始整理团队资料。</p>
      <p v-else>当前团队还没有可用知识库。</p>
      <button
        v-if="team.canManage"
        class="primary-button"
        type="button"
        @click="openCreate"
      >
        <Plus :size="16" />
        新建知识库
      </button>
    </div>

    <div v-else class="panel">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>名称</th>
              <th>描述</th>
              <th>文档数</th>
              <th>状态</th>
              <th>更新时间</th>
              <th v-if="team.canManage" class="actions-column">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="kb in items" :key="kb.id">
              <td data-label="名称">
                <RouterLink :to="`/knowledge-bases/${kb.id}`">
                  <strong data-testid="kb-row-name">{{ kb.name }}</strong>
                </RouterLink>
                <span class="cell-subtitle">{{ policyLabel(kb.default_model_policy_mode) }}</span>
              </td>
              <td class="muted-text" data-label="描述">{{ kb.description || '—' }}</td>
              <td data-label="文档数">{{ kb.document_count }}</td>
              <td data-label="状态">
                <a-tag :color="kb.status === 'active' ? 'green' : 'gray'">
                  {{ kb.status === 'active' ? '使用中' : '已归档' }}
                </a-tag>
              </td>
              <td class="muted-text" data-label="更新时间">{{ formatDate(kb.updated_at) }}</td>
              <td v-if="team.canManage" class="actions-column" data-label="操作">
                <RouterLink class="icon-button" :to="`/knowledge-bases/${kb.id}`" title="查看详情">
                  <BookOpen :size="16" />
                </RouterLink>
                <button class="icon-button" type="button" title="编辑" @click="openEdit(kb)">
                  <Pencil :size="16" />
                </button>
                <button class="icon-button danger-icon" type="button" title="归档" @click="archive(kb)">
                  <Archive :size="16" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="hasMore" class="load-more">
        <button class="ghost-button" type="button" :disabled="loading" @click="load(false)">
          {{ loading ? '加载中' : '加载更多' }}
        </button>
      </div>
    </div>

    <a-modal
      v-model:visible="modalVisible"
      :title="editing ? '编辑知识库' : '新建知识库'"
      :footer="false"
      width="480px"
    >
      <form class="form-stack" @submit.prevent="save">
        <label class="field">
          <span>名称</span>
          <input
            v-model="name"
            data-testid="kb-name-input"
            type="text"
            required
            placeholder="例如：Spring 技术资料"
          />
        </label>
        <label class="field">
          <span>描述</span>
          <textarea v-model="description" rows="3" placeholder="知识库内容范围" />
        </label>
        <div class="modal-actions">
          <button class="ghost-button" type="button" @click="modalVisible = false">
            取消
          </button>
          <button
            class="primary-button"
            data-testid="kb-save"
            type="submit"
            :disabled="saving"
          >
            {{ saving ? '保存中' : '保存' }}
          </button>
        </div>
      </form>
    </a-modal>
  </div>
</template>
