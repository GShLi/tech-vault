import { reactive } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'

import AdminAuditView from './AdminAuditView.vue'

const routeState = reactive({ params: { auditId: '' } })

const apiMocks = vi.hoisted(() => ({
  getAdminAudit: vi.fn(),
  listAdminAudit: vi.fn(),
}))

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRoute: () => routeState,
  }
})

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

const firstEntry = {
  id: 'audit-1',
  team_id: 'team-1',
  actor_id: 'user-1',
  action: 'user.created',
  resource_type: 'user',
  resource_id: 'user-2',
  details: { email: 'member@example.com' },
  created_at: '2026-10-19T12:00:00+00:00',
}

const secondEntry = {
  ...firstEntry,
  id: 'audit-2',
  action: 'document.deleted',
  resource_type: 'document',
  resource_id: 'doc-1',
}

function page(data: unknown[], cursor: string | null = null) {
  return {
    data,
    meta: {
      next_cursor: cursor,
      has_more: Boolean(cursor),
      request_id: 'req-audit',
    },
  }
}

function mountPage() {
  return mount(AdminAuditView, {
    global: {
      stubs: {
        RouterLink: { template: '<a><slot /></a>' },
        'a-spin': true,
      },
    },
  })
}

describe('AdminAuditView', () => {
  beforeEach(() => {
    routeState.params.auditId = ''
    vi.clearAllMocks()
    apiMocks.listAdminAudit.mockResolvedValue(page([firstEntry]))
    apiMocks.getAdminAudit.mockResolvedValue(firstEntry)
  })

  it('loads global audit pages without dropping earlier entries', async () => {
    apiMocks.listAdminAudit
      .mockResolvedValueOnce(page([firstEntry], 'cursor-2'))
      .mockResolvedValueOnce(page([secondEntry]))
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('user.created')
    await wrapper.get('.load-more button').trigger('click')
    await flushPromises()

    expect(apiMocks.listAdminAudit).toHaveBeenLastCalledWith('cursor-2')
    expect(wrapper.text()).toContain('user.created')
    expect(wrapper.text()).toContain('document.deleted')
  })

  it('loads an audit detail from the route parameter', async () => {
    routeState.params.auditId = 'audit-1'
    const wrapper = mountPage()
    await flushPromises()

    expect(apiMocks.getAdminAudit).toHaveBeenCalledWith('audit-1')
    expect(wrapper.text()).toContain('member@example.com')
    expect(wrapper.text()).toContain('user.created')
  })
})
