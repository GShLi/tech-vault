import { effectScope, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { useCursorList } from './useCursorList'
import type { PageEnvelope } from '@/types/api'

const page = (ids: string[], more = false): PageEnvelope<{ id: string }> => ({
  data: ids.map((id) => ({ id })),
  meta: {
    next_cursor: more ? 'next' : null,
    has_more: more,
    request_id: 'test',
  },
})

it('ignores an old team response and clears data when the team is removed', async () => {
  const team = ref<string | null>('a')
  let finish!: (value: PageEnvelope<{ id: string }>) => void
  const fetchPage = vi.fn((id: string) =>
    id === 'a'
      ? new Promise<PageEnvelope<{ id: string }>>((resolve) => {
          finish = resolve
        })
      : Promise.resolve(page(['b'])),
  )
  const scope = effectScope()
  const list = scope.run(() => useCursorList(() => team.value, fetchPage))!
  team.value = 'b'
  await flushPromises()
  finish(page(['a']))
  await flushPromises()
  expect(list.items.value).toEqual([{ id: 'b' }])
  team.value = null
  expect(list.items.value).toEqual([])
  expect(list.loading.value).toBe(false)
  scope.stop()
})

it('deduplicates overlapping pages and reports unexpected errors', async () => {
  const fetchPage = vi
    .fn()
    .mockResolvedValueOnce(page(['a'], true))
    .mockResolvedValueOnce(page(['a', 'b']))
    .mockRejectedValueOnce(new Error('offline'))
  const scope = effectScope()
  const list = scope.run(() => useCursorList(() => 'team', fetchPage))!
  await flushPromises()
  await list.load(false)
  expect(list.items.value).toEqual([{ id: 'a' }, { id: 'b' }])
  expect(fetchPage).toHaveBeenLastCalledWith('team', 'next')
  await list.load()
  expect(list.error.value?.message).toBe('offline')
  scope.stop()
})

it('ignores results after disposal', async () => {
  let finish!: (value: PageEnvelope<{ id: string }>) => void
  const scope = effectScope()
  const list = scope.run(() =>
    useCursorList(
      () => 'team',
      () =>
        new Promise<PageEnvelope<{ id: string }>>((resolve) => {
          finish = resolve
        }),
    ),
  )!
  scope.stop()
  finish(page(['late']))
  await flushPromises()
  expect(list.items.value).toEqual([])
})
