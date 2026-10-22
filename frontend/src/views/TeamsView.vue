<script setup lang="ts">
import { ApiRequestError, api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Empty as AEmpty,
  Form as AForm,
  FormItem as AFormItem,
  Input as AInput,
  Modal as AModal,
  Textarea as ATextarea,
} from '@arco-design/web-vue'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Plus, Users } from 'lucide-vue-next'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'

const auth = useAuthStore()
const team = useTeamStore()
const router = useRouter()

const showCreate = ref(false)
const name = ref('')
const description = ref('')
const creating = ref(false)
const error = ref<ApiRequestError | null>(null)

const memberships = computed(() => auth.me?.memberships ?? [])
const roleLabels: Record<string, string> = {
  admin: '平台管理员',
  leader: '团队管理员',
  member: '成员',
  viewer: '只读成员',
}

function enterTeam(teamId: string): void {
  team.selectTeam(teamId)
  router.push('/knowledge-bases')
}

async function createTeam(): Promise<void> {
  error.value = null
  creating.value = true
  try {
    const created = await api.createTeam({
      name: name.value.trim(),
      description: description.value.trim() || null,
    })
    await auth.loadMe()
    team.selectTeam(created.id)
    name.value = ''
    description.value = ''
    showCreate.value = false
    router.push('/knowledge-bases')
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <p>当前账号可访问的团队与角色。</p>
      </div>
      <a-button
        v-if="auth.me?.user.is_super_admin"
        data-testid="team-create-open"
        @click="showCreate = true"
        type="secondary"
        html-type="button"
      >
        <Plus :size="16" />
        创建团队
      </a-button>
    </div>

    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </a-alert>

    <div v-if="memberships.length" class="team-grid">
      <article
        v-for="membership in memberships"
        :key="membership.team_id"
        class="team-card"
      >
        <div class="team-card-heading">
          <div class="team-icon"><Users :size="18" /></div>
          <div>
            <h3>{{ membership.team_name }}</h3>
            <span class="muted-text">
              {{ roleLabels[membership.role] ?? membership.role }}
            </span>
          </div>
        </div>
        <a-button
          data-testid="team-card-enter"
          @click="enterTeam(membership.team_id)"
          type="text"
          html-type="button"
        >
          进入团队
          <ArrowRight :size="16" />
        </a-button>
      </article>
    </div>
    <a-empty v-else class="page-empty">
      <template #image><Users :size="28" /></template>
      <h3>还没有加入团队</h3>
      <p>
        {{
          auth.me?.user.is_super_admin
            ? '创建一个团队后即可开始管理知识库。'
            : '请联系平台管理员创建团队。'
        }}
      </p>
    </a-empty>

    <a-modal
      v-if="showCreate"
      :visible="true"
      :footer="false"
      unmount-on-close
      @cancel="showCreate = false"
      width="520px"
    >
      <template #title>创建团队</template>
      <a-form
        class="form-stack"
        :model="{ name, description }"
        layout="vertical"
        @submit-success="createTeam"
      >
        <a-form-item
          field="name"
          :rules="[{ required: true, message: '请填写团队名称' }]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>团队名称</template>
          <a-input
            v-model="name"
            data-testid="team-name-input"
            placeholder="例如：平台工程"
            type="text"
            :input-attrs="{ required: true }"
          ></a-input>
        </a-form-item>
        <a-form-item field="description">
          <template #label>描述</template>
          <a-textarea
            v-model="description"
            placeholder="团队技术资料范围"
            :textarea-attrs="{ rows: '3' }"
          ></a-textarea>
        </a-form-item>
        <div class="modal-actions">
          <a-button @click="showCreate = false" type="text" html-type="button">
            取消
          </a-button>
          <a-button
            data-testid="team-create-submit"
            :disabled="creating"
            type="primary"
            html-type="submit"
          >
            {{ creating ? '创建中' : '创建团队' }}
          </a-button>
        </div>
      </a-form>
    </a-modal>
  </div>
</template>
