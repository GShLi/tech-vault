<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Alert as AAlert, Button as AButton, Dropdown as ADropdown, Doption as ADoption,
  Empty as AEmpty, Form as AForm, FormItem as AFormItem, Input as AInput, Message,
  Modal, Modal as AModal, Spin as ASpin, Table as ATable, TableColumn as ATableColumn,
  Tag as ATag, Textarea as ATextarea } from '@arco-design/web-vue'
import { BookOpen, MoreHorizontal, Plus } from 'lucide-vue-next'
import { api, normalizeApiError, type ApiRequestError } from '@/api/client'
import { useCursorList } from '@/composables/useCursorList'
import { useUnsavedChanges } from '@/composables/useUnsavedChanges'
import { useTeamStore } from '@/stores/team'
import { formatDate, statusLabel as policyLabel } from '@/utils/format'
import type { KnowledgeBase } from '@/types/api'

const team = useTeamStore()
const router = useRouter()
const { items, loading, error, hasMore, load } = useCursorList<KnowledgeBase>(
  () => team.selectedTeamId, (teamId, cursor) => api.listKbs(teamId, cursor),
)
const modalVisible = ref(false)
const name = ref('')
const description = ref('')
const saving = ref(false)
const formError = ref<ApiRequestError | null>(null)
const discardDraft = useUnsavedChanges(
  () => modalVisible.value && Boolean(name.value.trim() || description.value.trim()),
  () => { modalVisible.value = false },
)
watch(() => team.selectedTeamId, () => { modalVisible.value = false; formError.value = null })
function openCreate() {
  name.value = ''; description.value = ''; formError.value = null; modalVisible.value = true
}
async function closeCreate() {
  if (saving.value) return
  if (await discardDraft()) modalVisible.value = false
}
async function save() {
  const teamId = team.selectedTeamId
  if (!teamId || saving.value) return
  if (!name.value.trim() || name.value.trim().length > 120 || description.value.length > 2000) {
    formError.value = normalizeApiError(new Error('名称需为 1–120 字符，描述最多 2000 字符。'))
    return
  }
  saving.value = true; formError.value = null
  try {
    const created = await api.createKb({ team_id: teamId, name: name.value.trim(), description: description.value.trim() || null })
    if (teamId !== team.selectedTeamId) return
    modalVisible.value = false
    Message.success('知识库已创建，可以开始上传文档')
    await router.push(`/knowledge-bases/${created.id}`)
  } catch (caught) { if (teamId === team.selectedTeamId) formError.value = normalizeApiError(caught) }
  finally { saving.value = false }
}
function archive(kb: KnowledgeBase) {
  const teamId = team.selectedTeamId
  if (!teamId) return
  Modal.confirm({
    title: '归档知识库',
    content: `归档「${kb.name}」后，成员将无法继续访问或向该库上传文档，该库也不再参与检索。当前页面没有恢复入口，请确认后操作。`,
    okText: '归档', cancelText: '取消',
    onOk: async () => {
      try {
        await api.archiveKb({ team_id: teamId, kb_id: kb.id }, kb.version)
        Message.success('知识库已归档')
        if (teamId === team.selectedTeamId) await load()
      } catch (caught) { if (teamId === team.selectedTeamId) error.value = normalizeApiError(caught) }
    },
  })
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <p>团队共享资料与文档集合。</p>
      </div>
      <a-button
        v-if="team.canManage"
        data-testid="kb-create-open"
        @click="openCreate"
        type="primary"
        html-type="button"
      >
        <Plus :size="16" />
        新建知识库
      </a-button>
    </div>

    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
      <a-button @click="load(true)" type="text" html-type="button">
        重试
      </a-button>
    </a-alert>

    <div v-if="loading && !items.length" class="panel loading-state">
      <a-spin />
      <span>正在加载知识库</span>
    </div>

    <a-empty v-else-if="!items.length" class="page-empty">
      <template #image><BookOpen :size="28" /></template>
      <h3>暂无知识库</h3>
      <p v-if="team.canManage">创建第一个知识库，开始整理团队资料。</p>
      <p v-else>当前团队还没有可用知识库。</p>
      <a-button
        v-if="team.canManage"
        @click="openCreate"
        type="primary"
        html-type="button"
      >
        <Plus :size="16" />
        新建知识库
      </a-button>
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
            <a-table-column title="名称" :width="240">
              <template #cell="{ record: kb }">
                <RouterLink :to="`/knowledge-bases/${kb.id}`">
                  <strong data-testid="kb-row-name">{{ kb.name }}</strong>
                </RouterLink>
                <span class="cell-subtitle">
                  {{ policyLabel(kb.default_model_policy_mode) }}
                </span>
              </template>
            </a-table-column>
            <a-table-column title="描述" :width="300">
              <template #cell="{ record: kb }">
                {{ kb.description || '—' }}
              </template>
            </a-table-column>
            <a-table-column title="文档数" :width="80">
              <template #cell="{ record: kb }">
                {{ kb.document_count }}
              </template>
            </a-table-column>
            <a-table-column title="状态" :width="100">
              <template #cell="{ record: kb }">
                <a-tag :color="kb.status === 'active' ? 'green' : 'gray'">
                  {{ kb.status === 'active' ? '使用中' : '已归档' }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column title="更新时间" :width="180">
              <template #cell="{ record: kb }">
                {{ formatDate(kb.updated_at) }}
              </template>
            </a-table-column>
            <a-table-column v-if="team.canManage" title="操作" :width="180">
              <template #cell="{ record: kb }">
                <RouterLink
                  :to="`/knowledge-bases/${kb.id}`"
                  custom
                  v-slot="{ href, navigate }"
                >
                  <a-button
                    type="text"
                    :href="href"
                    @click="navigate"
                    title="查看详情"
                  >
                    <BookOpen :size="16" />
                  </a-button>
                </RouterLink>
                <a-dropdown trigger="click">
                  <a-button type="text" aria-label="更多操作"><MoreHorizontal :size="16" /></a-button>
                  <template #content>
                    <a-doption @click="archive(kb)">归档知识库</a-doption>
                  </template>
                </a-dropdown>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </div>
      <div v-if="hasMore" class="load-more">
        <a-button
          :disabled="loading"
          @click="load(false)"
          type="text"
          html-type="button"
        >
          {{ loading ? '加载中' : '加载更多' }}
        </a-button>
      </div>
    </div>

    <a-modal
      v-model:visible="modalVisible"
      title="新建知识库"
      :mask-closable="false"
      :on-before-cancel="() => { void closeCreate(); return false }"
      :footer="false"
      width="480px"
    >
      <a-alert v-if="formError" type="error" class="page-alert">{{ formError.message }}</a-alert>
      <a-alert type="info" class="page-alert">新库默认允许外部模型，实际调用仍受团队策略与数据分类限制。创建后可管理成员访问范围。</a-alert>
      <a-form
        class="form-stack"
        :model="{ name, description }"
        layout="vertical"
        @submit-success="save"
      >
        <a-form-item
          field="name"
          :rules="[{ required: true, message: '请填写名称' }]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>名称</template>
          <a-input
            v-model="name"
            data-testid="kb-name-input"
            placeholder="例如：Spring 技术资料"
            type="text"
            :max-length="120"
            show-word-limit
          ></a-input>
        </a-form-item>
        <a-form-item field="description">
          <template #label>描述</template>
          <a-textarea
            v-model="description"
            placeholder="知识库内容范围"
            :max-length="2000"
            :textarea-attrs="{ rows: '3' }"
          ></a-textarea>
        </a-form-item>
        <div class="modal-actions">
          <a-button
            @click="closeCreate"
            type="text"
            html-type="button"
          >
            取消
          </a-button>
          <a-button
            data-testid="kb-save"
            :disabled="saving"
            type="primary"
            html-type="submit"
          >
            {{ saving ? '保存中' : '保存' }}
          </a-button>
        </div>
      </a-form>
    </a-modal>
  </div>
</template>
