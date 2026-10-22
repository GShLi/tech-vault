import { computed, onBeforeUnmount, ref } from 'vue'
import { api, normalizeApiError, type ApiRequestError } from '@/api/client'
import type { UploadBatch, UploadBatchInput, UploadLimits } from '@/types/api'

export interface UploadEntry {
  id: string
  file: File
  batchId?: string
  runId?: string
  status: 'pending' | 'uploading' | 'uploaded' | 'failed'
  progress: number
  error?: string
}

export function useUploadQueue() {
  const entries = ref<UploadEntry[]>([])
  const uploading = ref(false)
  const error = ref<ApiRequestError | null>(null)
  const finished = ref(false)
  const selectionErrors = ref<string[]>([])
  const submittedBatchIds = ref<string[]>([])
  let controller: AbortController | null = null
  let manifestId = crypto.randomUUID()
  const successful = computed(() => entries.value.filter((entry) => entry.status === 'uploaded'))
  const failed = computed(() => entries.value.filter((entry) => entry.status === 'failed'))

  function add(files: File[], limits: UploadLimits, resume?: UploadBatch | null) {
    selectionErrors.value = []
    for (const file of files) {
      if (!/\.(md|txt|pdf|docx)$/i.test(file.name)) selectionErrors.value.push(`${file.name}：不支持的文件类型`)
      else if (file.size === 0 || file.size > limits.max_file_bytes) selectionErrors.value.push(`${file.name}：文件为空或超过单文件大小限制`)
      else if (entries.value.length >= limits.max_files) selectionErrors.value.push(`${file.name}：超过本批文件数量限制`)
      else if (entries.value.reduce((total, item) => total + item.file.size, 0) + file.size > limits.max_total_bytes) selectionErrors.value.push(`${file.name}：超过本批总大小限制`)
      else if (resume) {
        const match = resume.files.find((item) => !item.run_id && item.file_name === file.name && item.size_bytes === file.size && !entries.value.some((entry) => entry.id === item.client_id))
        if (match) entries.value.push({ id: match.client_id, file, batchId: resume.id, status: 'pending', progress: 0 })
        else selectionErrors.value.push(`${file.name}：不属于该批次待补传文件，或已经上传`)
      } else entries.value.push({ id: crypto.randomUUID(), file, status: 'pending', progress: 0 })
    }
  }
  function reset() {
    controller?.abort()
    entries.value = []; uploading.value = false; finished.value = false
    error.value = null; selectionErrors.value = []; submittedBatchIds.value = []
    manifestId = crypto.randomUUID()
  }
  function continueUploading() {
    entries.value = entries.value.filter((entry) => entry.status !== 'uploaded')
    finished.value = false; error.value = null; selectionErrors.value = []
  }
  async function start(input: Omit<UploadBatchInput, 'files' | 'client_id'>, concurrency = 3) {
    if (uploading.value || !entries.value.some((entry) => entry.status !== 'uploaded')) return
    const active = new AbortController()
    controller = active; uploading.value = true; error.value = null; finished.value = false
    try {
      const fresh = entries.value.filter((entry) => !entry.batchId)
      if (fresh.length) {
        const batch = await api.createUploadBatch({ ...input, client_id: manifestId,
          files: fresh.map((entry) => ({ client_id: entry.id, file_name: entry.file.name, size_bytes: entry.file.size })),
        })
        if (active.signal.aborted) return
        fresh.forEach((entry) => { entry.batchId = batch.id })
        manifestId = crypto.randomUUID()
      }
      const pending = entries.value.filter((entry) => entry.status !== 'uploaded')
      submittedBatchIds.value = [...new Set(pending.map((entry) => entry.batchId!))]
      let cursor = 0
      async function worker() {
        while (cursor < pending.length && !active.signal.aborted) {
          const entry = pending[cursor++]
          entry.status = 'uploading'; entry.progress = 0; entry.error = undefined
          const form = new FormData()
          form.append('team_id', input.team_id); form.append('kb_id', input.kb_id)
          form.append('batch_id', entry.batchId!); form.append('batch_file_id', entry.id)
          form.append('file', entry.file)
          try {
            const uploaded = await api.uploadDocument(form, (percent) => { if (!active.signal.aborted) entry.progress = percent }, active.signal)
            if (active.signal.aborted) return
            entry.runId = uploaded.ingestion_run_id; entry.status = 'uploaded'; entry.progress = 100
          } catch (caught) {
            if (active.signal.aborted) return
            // A lost response can follow a committed upload. Reconcile before retrying.
            const batch = await api.getUploadBatch(input.team_id, entry.batchId!).catch(() => null)
            if (active.signal.aborted) return
            const saved = batch?.files.find((file) => file.client_id === entry.id && file.run_id)
            if (saved?.run_id) { entry.runId = saved.run_id; entry.status = 'uploaded'; entry.progress = 100 }
            else { entry.status = 'failed'; entry.error = normalizeApiError(caught, '上传失败，请重试').message }
          }
        }
      }
      await Promise.all(Array.from({ length: Math.min(concurrency, pending.length) }, worker))
      if (active.signal.aborted) return
      const results = await Promise.allSettled(submittedBatchIds.value.map((id) => api.sealUploadBatch(input.team_id, id)))
      if (active.signal.aborted) return
      const dispatchFailure = results.find((result) => result.status === 'rejected')
      if (dispatchFailure?.status === 'rejected') error.value = normalizeApiError(dispatchFailure.reason, '文件已保存，启动处理失败。请到批次进度页重试。')
      finished.value = successful.value.length > 0
    } catch (caught) { if (!active.signal.aborted) error.value = normalizeApiError(caught, '无法创建上传批次') }
    finally { if (controller === active) uploading.value = false }
  }
  onBeforeUnmount(() => controller?.abort())
  return { entries, uploading, error, finished, selectionErrors, submittedBatchIds, successful, failed, add, start, reset, continueUploading }
}
