import { shallowRef, ref, watch, onScopeDispose } from 'vue'
import { normalizeApiError, type ApiRequestError } from '@/api/client'
import type { PageEnvelope } from '@/types/api'

/** Team-scoped cursor state. Ignore responses after a team change or a newer reload. */
export function useCursorList<T extends { id: string }>(
  scope: () => string | null,
  fetchPage: (
    scopeId: string,
    cursor: string | null,
  ) => Promise<PageEnvelope<T>>,
) {
  const items = shallowRef<T[]>([])
  const loading = ref(false)
  const error = shallowRef<ApiRequestError | null>(null)
  const nextCursor = ref<string | null>(null)
  const hasMore = ref(false)
  let generation = 0

  async function load(reset = true): Promise<void> {
    if (!reset && (loading.value || !hasMore.value)) return
    const scopeId = scope()
    const request = ++generation
    if (!scopeId) {
      items.value = []
      nextCursor.value = null
      hasMore.value = false
      loading.value = false
      error.value = null
      return
    }
    loading.value = true
    error.value = null
    try {
      const page = await fetchPage(scopeId, reset ? null : nextCursor.value)
      if (request !== generation || scopeId !== scope()) return
      // Stable order, latest value wins if adjacent pages overlap after a mutation.
      items.value = [
        ...new Map(
          [...(reset ? [] : items.value), ...page.data].map((item) => [
            item.id,
            item,
          ]),
        ).values(),
      ]
      nextCursor.value = page.meta.next_cursor
      hasMore.value = page.meta.has_more
    } catch (caught) {
      if (request === generation && scopeId === scope())
        error.value = normalizeApiError(caught)
    } finally {
      if (request === generation) loading.value = false
    }
  }

  watch(
    scope,
    () => {
      items.value = []
      nextCursor.value = null
      hasMore.value = false
      void load()
    },
    { immediate: true, flush: 'sync' },
  )
  onScopeDispose(() => {
    generation += 1
  })

  return { items, loading, error, nextCursor, hasMore, load }
}
