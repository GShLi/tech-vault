<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Users } from 'lucide-vue-next'

import { api, ApiRequestError } from '@/api/client'
import { useTeamStore } from '@/stores/team'

const team = useTeamStore()
const members = ref<Array<Record<string, string>>>([])
const error = ref<ApiRequestError | null>(null)

const roleLabels: Record<string, string> = {
  admin: '平台管理员', leader: '团队管理员', member: '成员', viewer: '只读成员',
}

async function load(): Promise<void> {
  if (!team.selectedTeamId) return
  try { const page = await api.listMembers(team.selectedTeamId); members.value = page.data }
  catch (caught) { error.value = caught instanceof ApiRequestError ? caught : null }
}

async function changeRole(userId: string, role: string): Promise<void> {
  if (!team.selectedTeamId) return
  try { await api.updateMember(team.selectedTeamId, userId, { role }); await load() }
  catch (caught) { error.value = caught instanceof ApiRequestError ? caught : null }
}

async function remove(userId: string): Promise<void> {
  if (!team.selectedTeamId) return
  try { await api.removeMember(team.selectedTeamId, userId); await load() }
  catch (caught) { error.value = caught instanceof ApiRequestError ? caught : null }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-header"><div><h2>成员管理</h2><p>当前团队成员与角色。</p></div></div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong></div>
    <div class="panel">
      <div class="table-wrap">
        <table>
          <thead><tr><th>成员</th><th>角色</th><th>状态</th><th v-if="team.canManage">操作</th></tr></thead>
          <tbody>
            <tr v-for="m in members" :key="m.user_id">
              <td><strong>{{ m.display_name }}</strong><span class="cell-subtitle">{{ m.email }}</span></td>
              <td>
                <select :value="m.role" :disabled="!team.canManage" @change="changeRole(m.user_id, ($event.target as HTMLSelectElement).value)" style="height:32px;border:1px solid #cbd5df;border-radius:6px;padding:0 6px">
                  <option value="leader">{{ roleLabels.leader }}</option>
                  <option value="member">{{ roleLabels.member }}</option>
                  <option value="viewer">{{ roleLabels.viewer }}</option>
                </select>
              </td>
              <td><a-tag :color="m.status === 'active' ? 'green' : 'gray'">{{ m.status === 'active' ? '活跃' : '已移除' }}</a-tag></td>
              <td v-if="team.canManage">
                <button v-if="m.status === 'active'" class="ghost-button" type="button" @click="remove(m.user_id)">移除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!members.length" class="empty-state"><Users :size="24" /><span>暂无成员</span></div>
    </div>
  </div>
</template>
