import { flushPromises, mount } from '@vue/test-utils'

import AdminUsersView from './AdminUsersView.vue'

const apiMocks = vi.hoisted(() => ({
  createUser: vi.fn(),
  listTeams: vi.fn(),
  listUsers: vi.fn(),
  updateUser: vi.fn(),
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

const builtinUser = {
  id: 'admin-1',
  email: 'admin@techvault.local',
  display_name: 'Admin',
  status: 'active',
  is_super_admin: true,
  is_builtin: true,
  created_at: '2026-10-19T12:00:00+00:00',
  memberships: [],
}

const memberUser = {
  id: 'user-2',
  email: 'member@example.com',
  display_name: 'Member',
  status: 'active',
  is_super_admin: false,
  is_builtin: false,
  created_at: '2026-10-19T11:00:00+00:00',
  memberships: [
    {
      team_id: 'team-1',
      team_name: 'Platform',
      role: 'member',
      status: 'active',
    },
  ],
}

function page(data: unknown[], nextCursor: string | null = null) {
  return {
    data,
    meta: {
      next_cursor: nextCursor,
      has_more: Boolean(nextCursor),
      request_id: 'req-users',
    },
  }
}

async function mountPage() {
  const wrapper = mount(AdminUsersView)
  await flushPromises()
  return wrapper
}

describe('AdminUsersView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.listTeams.mockResolvedValue({
      data: [{ id: 'team-1', name: 'Platform' }],
      meta: { next_cursor: null, has_more: false, request_id: 'req-teams' },
    })
    apiMocks.listUsers.mockResolvedValue(page([builtinUser, memberUser]))
    apiMocks.createUser.mockResolvedValue({})
    apiMocks.updateUser.mockImplementation(async (body) => ({
      ...memberUser,
      status: body.status ?? memberUser.status,
      membership: body.team_id
        ? { ...memberUser.memberships[0], role: body.role }
        : undefined,
    }))
  })

  it('lists users and protects the built-in administrator', async () => {
    const wrapper = await mountPage()

    expect(wrapper.text()).toContain('member@example.com')
    expect(wrapper.text()).toContain('Platform')
    expect(wrapper.find('[data-testid="admin-user-disable-admin-1"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="admin-user-role-user-2-team-1"]').exists()).toBe(true)
  })

  it('updates account status and membership role through typed bodies', async () => {
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="admin-user-disable-user-2"]').trigger('click')
    await flushPromises()
    expect(apiMocks.updateUser).toHaveBeenCalledWith({
      user_id: 'user-2',
      status: 'disabled',
    })

    await wrapper.get('[data-testid="admin-user-role-user-2-team-1"]').setValue('leader')
    await wrapper.get('[data-testid="admin-user-role-save-user-2-team-1"]').trigger('click')
    await flushPromises()
    expect(apiMocks.updateUser).toHaveBeenCalledWith({
      user_id: 'user-2',
      team_id: 'team-1',
      role: 'leader',
    })
  })

  it('loads the next user page without losing existing rows', async () => {
    apiMocks.listUsers
      .mockResolvedValueOnce(page([builtinUser], 'cursor-2'))
      .mockResolvedValueOnce(page([memberUser]))
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="admin-users-load-more"] button').trigger('click')
    await flushPromises()

    expect(apiMocks.listUsers).toHaveBeenLastCalledWith('cursor-2')
    expect(wrapper.text()).toContain('admin@techvault.local')
    expect(wrapper.text()).toContain('member@example.com')
  })
})
