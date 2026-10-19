<script setup lang="ts">
import { ref } from 'vue'
import { Shield, Server } from 'lucide-vue-next'

import { api, ApiRequestError } from '@/api/client'
import { useTeamStore } from '@/stores/team'

const team = useTeamStore()
const policy = ref<Record<string, unknown>>({})
const error = ref<ApiRequestError | null>(null)

async function loadPolicy(): Promise<void> {
  if (!team.selectedTeamId) return
  try { policy.value = await api.getPolicy(team.selectedTeamId) } catch (caught) { error.value = caught instanceof ApiRequestError ? caught : null }
}

async function updateMode(mode: string): Promise<void> {
  if (!team.selectedTeamId) return
  try { await api.updatePolicy(team.selectedTeamId, mode); await loadPolicy() } catch (caught) { error.value = caught instanceof ApiRequestError ? caught : null }
}
</script>

<template>
  <div>
    <div class="page-header"><div><h2>设置</h2><p>团队模型策略与安全配置。</p></div></div>

    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong></div>

    <div class="panel" style="padding:22px;max-width:640px">
      <div class="form-stack">
        <div style="display:flex;align-items:center;gap:12px"><Shield :size="18" /><h3 style="margin:0">模型策略</h3></div>
        <p class="muted-text">当前模式：{{ policy.mode || 'local_only' }}</p>
        <select @change="updateMode(($event.target as HTMLSelectElement).value)" style="width:100%;height:38px;border:1px solid #cbd5df;border-radius:6px;padding:0 8px">
          <option value="local_only">仅本地模型</option>
          <option value="external_allowed">允许外部模型</option>
        </select>
        <div style="display:flex;align-items:center;gap:12px;margin-top:20px"><Server :size="18" /><h3 style="margin:0">组件状态</h3></div>
        <a-tag color="green">API 运行中</a-tag>
        <a-tag color="green">数据库可用</a-tag>
        <a-tag color="orange">检索引擎未接入</a-tag>
      </div>
    </div>
  </div>
</template>
