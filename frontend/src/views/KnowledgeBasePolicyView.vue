<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, Save, ShieldCheck } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import { useTeamStore } from '@/stores/team'
import type { KnowledgeBase, ModelPolicy } from '@/types/api'
import { statusLabel } from '@/utils/format'

const route = useRoute()
const team = useTeamStore()
const kb = ref<KnowledgeBase | null>(null)
const kbPolicy = ref<{ kb_id: string; mode: string; version: number } | null>(null)
const teamPolicy = ref<ModelPolicy | null>(null)
const mode = ref('local_only')
const loading = ref(false)
const saving = ref(false)
const error = ref<ApiRequestError | null>(null)

function kbId(): string {
  return String(route.params.kbId ?? '')
}

async function load(): Promise<void> {
  if (!team.selectedTeamId || !kbId()) return
  loading.value = true
  error.value = null
  try {
    const [kbView, policyView, parentPolicy] = await Promise.all([
      api.getKb(team.selectedTeamId, kbId()),
      api.getKbPolicy(team.selectedTeamId, kbId()),
      api.getPolicy(team.selectedTeamId),
    ])
    kb.value = kbView
    kbPolicy.value = policyView
    teamPolicy.value = parentPolicy
    mode.value = policyView.mode
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (!team.selectedTeamId) return
  saving.value = true
  error.value = null
  try {
    kbPolicy.value = await api.updateKbPolicy(
      { team_id: team.selectedTeamId, kb_id: kbId(), mode: mode.value },
      kbPolicy.value?.version ?? 1,
    )
    Message.success('知识库策略已更新')
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    saving.value = false
  }
}

onMounted(load)
watch(() => route.params.kbId, load)
</script>

<template>
  <div>
    <div class="page-header">
      <div class="heading-with-back"><RouterLink class="icon-button" :to="`/knowledge-bases/${kbId()}`" title="返回知识库"><ArrowLeft :size="18" /></RouterLink><div><h2>知识库策略</h2><p>{{ kb?.name || '模型调用与数据边界' }}</p></div></div>
    </div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span></div>
    <div v-if="loading && !kbPolicy" class="panel loading-state"><a-spin /><span>正在加载策略</span></div>
    <div v-else class="split-grid">
      <section class="panel detail-panel">
        <div class="detail-heading"><div class="detail-icon"><ShieldCheck :size="20" /></div><div><h3>知识库上限</h3><p>只能在团队策略允许范围内收紧。</p></div><StatusPill :status="mode" /></div>
        <form class="form-stack" @submit.prevent="save">
          <label class="field"><span>模型调用模式</span><select v-model="mode" :disabled="!team.canManage"><option value="local_only">仅本地模型</option><option value="external_allowed">允许外部模型</option><option value="external_required">仅外部模型</option></select></label>
          <div class="notice-box"><strong>继承规则</strong><span>团队策略：{{ statusLabel(teamPolicy?.mode) }}；知识库不得放宽数据分类或供应商范围。</span></div>
          <button v-if="team.canManage" class="primary-button" type="submit" :disabled="saving"><Save :size="16" />{{ saving ? '保存中' : '保存策略' }}</button>
        </form>
      </section>
      <section class="panel detail-panel">
        <div class="section-heading"><h3>当前生效值</h3></div>
        <dl class="detail-grid single-column"><div><dt>知识库模式</dt><dd>{{ statusLabel(kbPolicy?.mode) }}</dd></div><div><dt>团队模式</dt><dd>{{ statusLabel(teamPolicy?.mode) }}</dd></div><div><dt>最大数据分类</dt><dd>{{ teamPolicy?.max_data_classification || '—' }}</dd></div><div><dt>允许供应商</dt><dd>{{ teamPolicy?.allowed_provider_ids.length || 0 }} 个</dd></div><div><dt>策略版本</dt><dd>v{{ kbPolicy?.version || 1 }}</dd></div></dl>
      </section>
    </div>
  </div>
</template>
