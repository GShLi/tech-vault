import { control, setControlValue } from '@/test/arco'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import DocumentDetailPage from './DocumentDetailPage.vue'

const apiMocks = vi.hoisted(() => ({
  getDoc: vi.fn(),
  listDocumentVersions: vi.fn(),
  listDocumentChunks: vi.fn(),
  getDocumentTasks: vi.fn(),
  deleteDocument: vi.fn(),
  restoreDocument: vi.fn(),
  rebuildDocument: vi.fn(),
  updateDoc: vi.fn(),
  listDocumentGrants: vi.fn(),
  createDocumentGrant: vi.fn(),
  revokeDocumentGrant: vi.fn(),
  listMembers: vi.fn(),
}))

const modalMocks = vi.hoisted(() => ({
  confirm: vi.fn((options: { onOk?: () => void }) => options.onOk?.()),
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

vi.mock('@arco-design/web-vue', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@arco-design/web-vue')>()
  return {
    ...actual,
    Modal: { confirm: modalMocks.confirm },
    Message: { success: vi.fn() },
  }
})

function documentView(status: 'active' | 'deleted', ownerUserId = 'user-1') {
  return {
    id: 'document-1',
    knowledge_base_id: 'kb-1',
    file_name: 'guide.md',
    source_type: 'upload',
    product: null,
    version_values: [],
    visibility: 'team_shared',
    data_classification: 'internal',
    doc_status: status,
    deleted_at: status === 'deleted' ? '2026-10-19T12:00:00+00:00' : null,
    purged_at: null,
    version: 1,
    created_at: '2026-10-19T12:00:00+00:00',
    updated_at: '2026-10-19T12:00:00+00:00',
    owner_user_id: ownerUserId,
    current_version_id: 'version-1',
    source_uri: null,
    version_family: null,
  }
}

function teamMember(
  userId: string,
  displayName: string,
  role: 'leader' | 'member' | 'viewer' = 'member',
) {
  return {
    team_id: 'team-1',
    user_id: userId,
    email: `${userId}@example.com`,
    display_name: displayName,
    role,
    status: 'active',
    joined_at: '2026-10-19T12:00:00+00:00',
  }
}

function grant(id: string, userId: string) {
  return {
    id,
    user_id: userId,
    granted_by: 'user-1',
    created_at: '2026-10-19T12:00:00+00:00',
  }
}

function pageEnvelope<T>(data: T[] = [], nextCursor: string | null = null) {
  return {
    data,
    meta: {
      next_cursor: nextCursor,
      has_more: nextCursor !== null,
      request_id: 'req-page',
    },
  }
}

async function mountPage(options: {
  status: 'active' | 'deleted'
  role?: 'leader' | 'member' | 'viewer'
  userId?: string
  ownerUserId?: string
}) {
  const {
    status,
    role = 'leader',
    userId = role === 'leader' ? 'user-1' : 'user-2',
    ownerUserId = 'user-1',
  } = options
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.token = 'token'
  auth.me = {
    user: {
      id: userId,
      email: `${role}@example.com`,
      display_name: role,
      status: 'active',
      is_super_admin: false,
      is_builtin: false,
      created_at: '2026-10-19T12:00:00+00:00',
    },
    memberships: [
      {
        team_id: 'team-1',
        team_name: 'Platform',
        role,
        status: 'active',
      },
    ],
  }
  useTeamStore().selectTeam('team-1')
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/documents/:documentId', component: DocumentDetailPage },
      { path: '/knowledge-bases/:kbId', component: { template: '<div />' } },
      { path: '/chunks', component: { template: '<div />' } },
      { path: '/tasks', component: { template: '<div />' } },
    ],
  })
  await router.push('/documents/document-1')
  await router.isReady()
  apiMocks.getDoc.mockResolvedValue(documentView(status, ownerUserId))
  apiMocks.listDocumentVersions.mockResolvedValue(pageEnvelope())
  apiMocks.listDocumentChunks.mockResolvedValue(pageEnvelope())
  apiMocks.getDocumentTasks.mockResolvedValue(pageEnvelope())
  apiMocks.listDocumentGrants.mockResolvedValue(pageEnvelope())
  apiMocks.listMembers.mockResolvedValue(
    pageEnvelope([
      teamMember('user-1', 'Owner', 'leader'),
      teamMember('user-2', 'Member'),
      teamMember('user-3', 'Reader'),
      teamMember('user-4', 'Writer'),
    ]),
  )
  apiMocks.updateDoc.mockImplementation(
    async (body: { file_name?: string; product?: string | null }) => ({
      ...documentView(status, ownerUserId),
      ...body,
      version: 2,
    }),
  )

  const wrapper = mount(DocumentDetailPage, {
    global: {
      plugins: [pinia, router],
      stubs: { ASpin: true },
    },
  })
  await flushPromises()
  return wrapper
}

describe('DocumentDetailPage lifecycle actions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.deleteDocument.mockResolvedValue(documentView('deleted'))
    apiMocks.restoreDocument.mockResolvedValue(documentView('active'))
    apiMocks.rebuildDocument.mockResolvedValue({
      document_id: 'document-1',
      ingestion_run_id: 'run-1',
      status: 'queued',
    })
    apiMocks.createDocumentGrant.mockResolvedValue({
      id: 'grant-3',
      user_id: 'user-3',
    })
    apiMocks.revokeDocumentGrant.mockResolvedValue({ revoked: 'grant-1' })
  })

  it('offers restore for a soft-deleted document', async () => {
    const wrapper = await mountPage({ status: 'deleted' })

    expect(
      wrapper.get('[data-testid="document-deleted-notice"]').text(),
    ).toContain('停止召回')
    const restore = wrapper
      .findAll('button')
      .find((button) => button.text().includes('恢复文档'))
    expect(restore).toBeDefined()
    await restore?.trigger('click')
    await flushPromises()

    expect(apiMocks.restoreDocument).toHaveBeenCalledWith(
      'team-1',
      'document-1',
    )
  })

  it('confirms and deletes an active document', async () => {
    const wrapper = await mountPage({ status: 'active' })

    const remove = wrapper
      .findAll('button')
      .find((button) => button.text().includes('删除文档'))
    expect(remove).toBeDefined()
    await remove?.trigger('click')
    await flushPromises()

    expect(modalMocks.confirm).toHaveBeenCalled()
    expect(apiMocks.deleteDocument).toHaveBeenCalledWith('team-1', 'document-1')
  })

  it('lets a non-owner member manage only their own document controls', async () => {
    const wrapper = await mountPage({
      status: 'active',
      role: 'member',
      userId: 'user-2',
      ownerUserId: 'user-1',
    })

    expect(wrapper.text()).not.toContain('编辑元数据')
    expect(wrapper.text()).not.toContain('重建索引')
    expect(wrapper.text()).not.toContain('删除文档')
    expect(wrapper.text()).not.toContain('文档授权')
    expect(apiMocks.listDocumentGrants).not.toHaveBeenCalled()
    expect(apiMocks.listMembers).not.toHaveBeenCalled()
  })

  it('lets the document owner edit metadata with the current version', async () => {
    const wrapper = await mountPage({
      status: 'active',
      role: 'member',
      userId: 'user-2',
      ownerUserId: 'user-2',
    })

    const edit = wrapper
      .findAll('button')
      .find((button) => button.text().includes('编辑元数据'))
    expect(edit).toBeDefined()
    await edit?.trigger('click')

    await setControlValue(
      control(wrapper, '[data-testid="document-metadata-file-name"]'),
      'guide-v2.md',
    )
    await setControlValue(
      control(wrapper, '[data-testid="document-metadata-product"]'),
      'TechVault',
    )
    await wrapper.get('form.metadata-editor').trigger('submit')
    await flushPromises()

    expect(apiMocks.updateDoc).toHaveBeenCalledWith(
      {
        team_id: 'team-1',
        document_id: 'document-1',
        file_name: 'guide-v2.md',
        product: 'TechVault',
        visibility: 'team_shared',
        data_classification: 'internal',
        version_values: [],
      },
      1,
    )
  })

  it('loads every grant page and lets a manager add and revoke grants', async () => {
    apiMocks.listDocumentGrants
      .mockResolvedValueOnce(
        pageEnvelope([grant('grant-1', 'user-2')], 'cursor-1'),
      )
      .mockResolvedValueOnce(pageEnvelope([grant('grant-2', 'user-3')]))

    const wrapper = await mountPage({ status: 'active' })
    apiMocks.listDocumentGrants.mockResolvedValue(
      pageEnvelope([grant('grant-1', 'user-2'), grant('grant-2', 'user-3')]),
    )

    expect(apiMocks.listDocumentGrants).toHaveBeenNthCalledWith(
      1,
      'team-1',
      'document-1',
      null,
      100,
    )
    expect(apiMocks.listDocumentGrants).toHaveBeenNthCalledWith(
      2,
      'team-1',
      'document-1',
      'cursor-1',
      100,
    )
    expect(wrapper.text()).toContain('Member')
    expect(wrapper.text()).toContain('Reader')

    await setControlValue(
      control(wrapper, '[data-testid="document-grant-user"]'),
      'user-4',
    )
    await wrapper.get('form.inline-form').trigger('submit')
    await flushPromises()

    expect(apiMocks.createDocumentGrant).toHaveBeenCalledWith(
      'team-1',
      'document-1',
      'user-4',
    )
    expect(apiMocks.listDocumentGrants).toHaveBeenCalledTimes(3)
    expect(wrapper.text()).toContain('Member')

    await wrapper
      .get('[data-testid="document-grant-revoke-grant-1"]')
      .trigger('click')
    await flushPromises()

    expect(apiMocks.revokeDocumentGrant).toHaveBeenCalledWith(
      'team-1',
      'grant-1',
    )
  })
})
