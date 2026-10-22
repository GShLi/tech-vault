import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { api } from '@/api/client'
import { useUploadQueue } from './useUploadQueue'

vi.mock('@/api/client', () => ({
  api: { createUploadBatch: vi.fn(), uploadDocument: vi.fn(), getUploadBatch: vi.fn(), sealUploadBatch: vi.fn() },
  normalizeApiError: (error: Error) => ({ message: error.message }),
}))
const limits = { max_files: 200, max_file_bytes: 50 * 1024 * 1024, max_total_bytes: 2 * 1024 ** 3, upload_concurrency: 3 }
const input = { team_id: 'team', kb_id: 'kb', product: 'Java', version_values: [], visibility: 'team_shared', data_classification: 'internal' }
function setup(count = 5) {
  let queue!: ReturnType<typeof useUploadQueue>
  const wrapper = mount(defineComponent({ setup() { queue = useUploadQueue(); return () => null } }))
  queue.add(Array.from({ length: count }, (_, i) => new File(['Java records'], `${i}.md`)), limits)
  return { queue, wrapper }
}
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.createUploadBatch).mockResolvedValue({ id: 'batch' } as never)
  vi.mocked(api.sealUploadBatch).mockResolvedValue({} as never)
  vi.mocked(api.getUploadBatch).mockResolvedValue({ files: [] } as never)
})
it('limits uploads to three and seals only after every response', async () => {
  const { queue, wrapper } = setup()
  const release: Array<() => void> = []
  let active = 0, peak = 0
  vi.mocked(api.uploadDocument).mockImplementation(() => new Promise((resolve) => {
    active++; peak = Math.max(peak, active)
    release.push(() => { active--; resolve({ ingestion_run_id: 'run' } as never) })
  }))
  const task = queue.start(input)
  await flushPromises()
  expect(api.uploadDocument).toHaveBeenCalledTimes(3)
  expect(api.sealUploadBatch).not.toHaveBeenCalled()
  release[0](); release[1](); release[2]()
  await flushPromises()
  expect(api.uploadDocument).toHaveBeenCalledTimes(5)
  release[3](); release[4]()
  await task
  expect(peak).toBe(3)
  expect(queue.successful.value).toHaveLength(5)
  expect(api.sealUploadBatch).toHaveBeenCalledWith('team', 'batch')
  expect(queue.finished.value).toBe(true)
  wrapper.unmount()
})
it('reconciles a lost response and retries only the failed file with its original identifier', async () => {
  const { queue, wrapper } = setup(3)
  const ids = queue.entries.value.map((entry) => entry.id)
  vi.mocked(api.uploadDocument).mockResolvedValueOnce({ ingestion_run_id: 'first' } as never)
    .mockRejectedValueOnce(new Error('lost response')).mockRejectedValueOnce(new Error('offline'))
  vi.mocked(api.getUploadBatch).mockResolvedValue({ files: [{ client_id: ids[1], run_id: 'saved' }] } as never)
  await queue.start(input)
  expect(queue.successful.value).toHaveLength(2)
  expect(queue.failed.value).toHaveLength(1)
  queue.continueUploading()
  expect(queue.entries.value.map((entry) => entry.id)).toEqual([ids[2]])
  vi.mocked(api.uploadDocument).mockResolvedValue({ ingestion_run_id: 'retry' } as never)
  await queue.start(input)
  expect(api.createUploadBatch).toHaveBeenCalledTimes(1)
  expect(api.uploadDocument).toHaveBeenCalledTimes(4)
  const form = vi.mocked(api.uploadDocument).mock.calls[3][0]
  expect(form.get('batch_file_id')).toBe(ids[2])
  expect(form.get('batch_id')).toBe('batch')
  expect(queue.failed.value).toHaveLength(0)
  wrapper.unmount()
})
it('rejects unsupported, empty and excess files and ignores results after navigation', async () => {
  const { queue, wrapper } = setup(0)
  queue.add([new File(['x'], 'bad.exe'), new File([], 'empty.md')], limits)
  expect(queue.entries.value).toHaveLength(0)
  expect(queue.selectionErrors.value).toHaveLength(2)
  queue.add(Array.from({ length: 201 }, (_, i) => new File(['x'], `${i}.md`)), limits)
  expect(queue.entries.value).toHaveLength(200)
  expect(queue.selectionErrors.value).toHaveLength(1)
  let complete!: (value: never) => void
  vi.mocked(api.createUploadBatch).mockImplementation(() => new Promise((resolve) => { complete = resolve }))
  const task = queue.start(input)
  wrapper.unmount()
  complete({ id: 'late' } as never)
  await task
  expect(api.uploadDocument).not.toHaveBeenCalled()
  expect(queue.finished.value).toBe(false)
})
