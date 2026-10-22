import { control, setControlValue } from '@/test/arco'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import DocumentUploadView from './DocumentUploadView.vue'

const apiMocks = vi.hoisted(() => ({
  getKb: vi.fn(),
  uploadLimits: vi.fn(),
  createUploadBatch: vi.fn(),
  uploadDocument: vi.fn(),
  sealUploadBatch: vi.fn(),
  getUploadBatch: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      ...apiMocks,
    },
  }
})

function knowledgeBase(id: string, name: string) {
  return {
    id,
    team_id: 'team-1',
    name,
    description: null,
    status: 'active',
    default_model_policy_mode: 'local_only',
    document_count: 0,
    version: 1,
    created_at: '2026-10-19T12:00:00+00:00',
    updated_at: '2026-10-19T12:00:00+00:00',
  }
}

function page<T>(data: T[], nextCursor: string | null = null) {
  return {
    data,
    meta: {
      next_cursor: nextCursor,
      has_more: nextCursor !== null,
      request_id: 'req-upload',
    },
  }
}

async function mountPage() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.token = 'token'
  auth.me = {
    user: {
      id: 'user-2',
      email: 'member@example.com',
      display_name: 'Member',
      status: 'active',
      is_super_admin: false,
      is_builtin: false,
      created_at: '2026-10-19T12:00:00+00:00',
    },
    memberships: [
      {
        team_id: 'team-1',
        team_name: 'Platform',
        role: 'member',
        status: 'active',
      },
    ],
  }
  useTeamStore().selectTeam('team-1')
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/knowledge-bases/:kbId/upload', component: DocumentUploadView },
      { path: '/knowledge-bases', component: { template: '<div />' } },
      { path: '/tasks/:runId', component: { template: '<div />' } },
      { path: '/upload-batches/:batchId', component: { template: '<div />' } },
    ],
  })
  await router.push('/knowledge-bases/kb-1/upload')
  await router.isReady()

  const wrapper = mount(DocumentUploadView, {
    global: { plugins: [pinia, router] },
  })
  await flushPromises()
  return wrapper
}

describe('DocumentUploadView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.getKb.mockResolvedValue(knowledgeBase('kb-1', 'Java 资料'))
    apiMocks.uploadLimits.mockResolvedValue({ max_files: 200, max_total_bytes: 2147483648, max_file_bytes: 52428800, upload_concurrency: 3 })
    apiMocks.createUploadBatch.mockResolvedValue({ id: 'batch-1' })
    apiMocks.uploadDocument.mockResolvedValue({ ingestion_run_id: 'run-1', document: { id: 'doc-1' } })
    apiMocks.sealUploadBatch.mockResolvedValue({ id: 'batch-1' })
  })

  it('locks the upload target to the knowledge base in the route', async () => {
    const wrapper = await mountPage()
    expect(apiMocks.getKb).toHaveBeenCalledWith('team-1', 'kb-1')
    expect(wrapper.get('[data-testid="upload-target"]').text()).toBe('Java 资料')
    expect(wrapper.get('input[type="file"]').attributes()).toHaveProperty('multiple')
    expect(wrapper.text()).toContain('200')
    wrapper.unmount()
  })

  it('submits shared metadata, seals the batch and lets the user continue uploading', async () => {
    const wrapper = await mountPage()
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [
      new File(['# Guide'], 'guide.md', { type: 'text/markdown' }),
      new File(['# Records'], 'records.md', { type: 'text/markdown' }),
    ] })
    await input.trigger('change')
    await setControlValue(control(wrapper, '[data-testid="upload-product"]'), 'TechVault')
    await setControlValue(control(wrapper, '[data-testid="upload-versions"]'), '1.0, 2.0')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(apiMocks.createUploadBatch).toHaveBeenCalledWith(expect.objectContaining({ team_id: 'team-1', kb_id: 'kb-1', product: 'TechVault', version_values: ['1.0', '2.0'] }))
    expect(apiMocks.createUploadBatch.mock.calls[0][0].files).toHaveLength(2)
    expect(apiMocks.uploadDocument).toHaveBeenCalledTimes(2)
    const form = apiMocks.uploadDocument.mock.calls[0][0] as FormData
    expect(form.get('batch_id')).toBe('batch-1')
    expect(form.get('kb_id')).toBe('kb-1')
    expect(apiMocks.sealUploadBatch).toHaveBeenCalledWith('team-1', 'batch-1')
    expect(wrapper.text()).toContain('查看处理进度')
    const button = wrapper.findAll('button').find((button) => button.text() === '继续上传')!
    await button.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已选 0 个文件')
    wrapper.unmount()
  })
  it.each([[1, '/tasks/run-1'], [2, '/upload-batches/batch-1']] as const)(
    'routes %i uploaded files to the matching task or batch', async (count, path) => {
      const wrapper = await mountPage()
      const input = wrapper.get('input[type="file"]')
      Object.defineProperty(input.element, 'files', { value: Array.from({ length: count }, (_, index) => new File(['Java'], `${index}.md`)) })
      await input.trigger('change')
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      await wrapper.findAll('button').find((button) => button.text() === '查看处理进度')!.trigger('click')
      await flushPromises()
      expect(wrapper.vm.$router.currentRoute.value.path).toBe(path)
      wrapper.unmount()
    },
  )

})
