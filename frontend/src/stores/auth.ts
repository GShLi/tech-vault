import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  api,
  ApiRequestError,
  clearAccessToken,
  getAccessToken,
  setAccessToken,
  normalizeApiError,
} from '@/api/client'
import type { Me } from '@/types/api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(getAccessToken())
  const me = ref<Me | null>(null)
  const loading = ref(false)
  const error = ref<ApiRequestError | null>(null)

  const isAuthenticated = computed(() => Boolean(token.value && me.value))

  async function login(email: string, password: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const response = await api.login({ email, password })
      setAccessToken(response.access_token)
      token.value = response.access_token
      await loadMe()
    } catch (caught) {
      error.value =
        caught instanceof ApiRequestError ? caught : normalizeApiError(caught)
      throw caught
    } finally {
      loading.value = false
    }
  }

  async function loadMe(): Promise<void> {
    if (!token.value) {
      me.value = null
      return
    }
    me.value = await api.me()
  }

  async function logout(): Promise<void> {
    const serverLogout = token.value ? api.logout().catch(() => undefined) : Promise.resolve()
    clearAccessToken()
    token.value = null
    me.value = null
    error.value = null
    await serverLogout
  }

  return {
    token,
    me,
    loading,
    error,
    isAuthenticated,
    login,
    loadMe,
    logout,
  }
})
