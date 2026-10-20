import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import DocumentUploadView from './DocumentUploadView.vue'

const apiMocks = vi.hoisted(() => ({
  listKbs: vi.fn(),
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
  })

  it('loads every knowledge base page into the member upload selector', async () => {
    apiMocks.listKbs
      .mockResolvedValueOnce(page([knowledgeBase('kb-1', 'Java 资料')], 'cursor-1'))
      .mockResolvedValueOnce(page([knowledgeBase('kb-2', 'Spring 资料')]))

    const wrapper = await mountPage()

    expect(apiMocks.listKbs).toHaveBeenNthCalledWith(1, 'team-1', null, 100)
    expect(apiMocks.listKbs).toHaveBeenNthCalledWith(2, 'team-1', 'cursor-1', 100)
    expect(wrapper.text()).toContain('Java 资料')
    expect(wrapper.text()).toContain('Spring 资料')
    expect(wrapper.findAll('button').some((button) => button.text().includes('上传文件'))).toBe(true)
  })

  it('submits product and version metadata with the upload form', async () => {
    apiMocks.listKbs.mockResolvedValue(page([knowledgeBase('kb-1', 'Java 资料')]))
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountPage()

    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      value: [new File(['# Guide'], 'guide.md', { type: 'text/markdown' })],
    })
    await input.trigger('change')
    await wrapper.get('[data-testid="upload-product"]').setValue('TechVault')
    await wrapper.get('[data-testid="upload-versions"]').setValue('1.0, 2.0')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    const body = fetchMock.mock.calls[0][1].body as FormData
    expect(body.get('product')).toBe('TechVault')
    expect(body.getAll('version_values')).toEqual(['1.0', '2.0'])
    vi.unstubAllGlobals()
  })
})
