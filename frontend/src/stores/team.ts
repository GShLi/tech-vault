import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { useAuthStore } from '@/stores/auth'
import type { Membership } from '@/types/api'

export const TEAM_STORAGE_KEY = 'techvault.team_id'

export const useTeamStore = defineStore('team', () => {
  const auth = useAuthStore()
  const beforeChange = ref<(() => Promise<boolean>) | null>(null)
  const selectedTeamId = ref<string | null>(
    window.localStorage.getItem(TEAM_STORAGE_KEY),
  )

  const memberships = computed<Membership[]>(
    () => auth.me?.memberships.filter((item) => item.status === 'active') ?? [],
  )

  const currentMembership = computed<Membership | null>(
    () =>
      memberships.value.find(
        (item) => item.team_id === selectedTeamId.value,
      ) ?? null,
  )

  const canManage = computed(
    () => currentMembership.value?.role === 'leader',
  )

  function selectTeam(teamId: string): void {
    selectedTeamId.value = teamId
    window.localStorage.setItem(TEAM_STORAGE_KEY, teamId)
  }

  function clearTeam(): void {
    selectedTeamId.value = null
    window.localStorage.removeItem(TEAM_STORAGE_KEY)
  }

  function restore(): string | null {
    const available = memberships.value.map((item) => item.team_id)
    if (selectedTeamId.value && available.includes(selectedTeamId.value)) {
      return selectedTeamId.value
    }
    if (available.length === 1) {
      selectTeam(available[0])
      return available[0]
    }
    clearTeam()
    return null
  }

  return {
    beforeChange,
    selectedTeamId,
    memberships,
    currentMembership,
    canManage,
    selectTeam,
    clearTeam,
    restore,
  }
})
