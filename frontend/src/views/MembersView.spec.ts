import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import MembersView from './MembersView.vue'

const apiMocks = vi.hoisted(() => ({
  createInvitation: vi.fn(),
  listMembers: vi.fn(),
  removeMember: vi.fn(),
  transferDocuments: vi.fn(),
  updateMember: vi.fn(),
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

const members = [
  {
    team_id: 'team-1',
    user_id: 'user-1',
    email: 'leader@example.com',
    display_name: 'Leader',
    role: 'leader',
    status: 'active',
    joined_at: '2026-10-19T12:00:00+00:00',
  },
  {
    team_id: 'team-1',
    user_id: 'user-2',
    email: 'departing@example.com',
    display_name: 'Departing',
    role: 'member',
    status: 'active',
    joined_at: '2026-10-19T11:00:00+00:00',
  },
  {
    team_id: 'team-1',
    user_id: 'user-3',
    email: 'paused@example.com',
    display_name: 'Paused',
    role: 'viewer',
    status: 'disabled',
    joined_at: '2026-10-19T10:00:00+00:00',
  },
]

function makePinia() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.token = 'token'
  auth.me = {
    user: {
      id: 'user-1',
      email: 'leader@example.com',
      display_name: 'Leader',
      status: 'active',
      is_super_admin: false,
      is_builtin: false,
      created_at: '2026-10-19T12:00:00+00:00',
    },
    memberships: [
      {
        team_id: 'team-1',
        team_name: 'Platform',
        role: 'leader',
        status: 'active',
      },
    ],
  }
  useTeamStore().selectTeam('team-1')
  return pinia
}

async function mountPage() {
  const wrapper = mount(MembersView, {
    global: {
      plugins: [makePinia()],
      stubs: {
        ATag: { template: '<span><slot /></span>' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('MembersView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.listMembers.mockResolvedValue({
      data: members,
      meta: { next_cursor: null, has_more: false, request_id: 'req-members' },
    })
    apiMocks.updateMember.mockResolvedValue({
      team_id: 'team-1',
      user_id: 'user-2',
      role: 'member',
      status: 'disabled',
    })
    apiMocks.transferDocuments.mockResolvedValue({
      from_user_id: 'user-2',
      to_user_id: 'user-1',
      transferred_documents: 2,
      transferred_chunks: 7,
    })
    apiMocks.removeMember.mockResolvedValue({ removed: 'user-2' })
    apiMocks.createInvitation.mockResolvedValue({
      id: 'invitation-1',
      team_id: 'team-1',
      team_name: 'Platform',
      email: 'new@example.com',
      role: 'member',
      status: 'pending',
      expires_at: '2026-10-26T12:00:00+00:00',
      created_at: '2026-10-19T12:00:00+00:00',
      accepted_at: null,
      token: 'invite-token',
    })
  })

  it('creates invitations with ids and role in the request contract', async () => {
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="invite-email"]').setValue('new@example.com')
    await wrapper.get('[data-testid="invite-role"]').setValue('member')
    await wrapper.get('[data-testid="invite-submit"]').trigger('submit')
    await flushPromises()

    expect(apiMocks.createInvitation).toHaveBeenCalledWith({
      team_id: 'team-1',
      email: 'new@example.com',
      role: 'member',
    })
    expect(wrapper.get('[aria-label="邀请链接"]').element).toHaveProperty(
      'value',
      `${window.location.origin}/invite/invite-token`,
    )
  })

  it('disables and re-enables members through status updates', async () => {
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="member-disable-user-2"]').trigger('click')
    await flushPromises()

    expect(apiMocks.updateMember).toHaveBeenCalledWith('team-1', 'user-2', {
      status: 'disabled',
    })

    await wrapper.get('[data-testid="member-enable-user-3"]').trigger('click')
    await flushPromises()

    expect(apiMocks.updateMember).toHaveBeenCalledWith('team-1', 'user-3', {
      status: 'active',
    })
  })

  it('prompts for private document transfer before removal', async () => {
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="member-remove-user-2"]').trigger('click')

    expect(wrapper.text()).toContain('移除前请转移该成员的私有文档')
    expect(
      wrapper.get('[data-testid="transfer-target"]').findAll('option'),
    ).toHaveLength(1)

    await wrapper.get('[data-testid="transfer-submit"]').trigger('click')
    await flushPromises()

    expect(apiMocks.transferDocuments).toHaveBeenCalledWith({
      team_id: 'team-1',
      from_user_id: 'user-2',
      to_user_id: 'user-1',
    })

    await wrapper.get('[data-testid="remove-confirm"]').trigger('click')
    await flushPromises()

    expect(apiMocks.removeMember).toHaveBeenCalledWith('team-1', 'user-2')
  })

  it('appends the next cursor page without dropping existing members', async () => {
    apiMocks.listMembers
      .mockResolvedValueOnce({
        data: members.slice(0, 2),
        meta: { next_cursor: 'cursor-1', has_more: true, request_id: 'req-1' },
      })
      .mockResolvedValueOnce({
        data: [members[2]],
        meta: { next_cursor: null, has_more: false, request_id: 'req-2' },
      })

    const wrapper = await mountPage()
    await wrapper.get('.load-more button').trigger('click')
    await flushPromises()

    expect(apiMocks.listMembers).toHaveBeenNthCalledWith(1, 'team-1', null, 20)
    expect(apiMocks.listMembers).toHaveBeenNthCalledWith(2, 'team-1', 'cursor-1', 20)
    expect(wrapper.text()).toContain('Leader')
    expect(wrapper.text()).toContain('Paused')
  })

  it('loads every member page before offering private document transfer targets', async () => {
    const allMembers = [
      ...members,
      {
        team_id: 'team-1',
        user_id: 'user-4',
        email: 'later@example.com',
        display_name: 'Later Page Member',
        role: 'member',
        status: 'active',
        joined_at: '2026-10-19T09:00:00+00:00',
      },
    ]

    apiMocks.listMembers.mockImplementation(
      (_teamId: string, cursor: string | null, limit: number) => {
        if (limit === 100) {
          return Promise.resolve(
            cursor
              ? {
                  data: [allMembers[3]],
                  meta: { next_cursor: null, has_more: false, request_id: 'req-all-2' },
                }
              : {
                  data: allMembers.slice(0, 2),
                  meta: { next_cursor: 'all-cursor-1', has_more: true, request_id: 'req-all-1' },
                },
          )
        }
        return Promise.resolve({
          data: members,
          meta: { next_cursor: null, has_more: false, request_id: 'req-members' },
        })
      },
    )

    const wrapper = await mountPage()
    await wrapper.get('[data-testid="member-remove-user-2"]').trigger('click')
    await flushPromises()

    const options = wrapper.get('[data-testid="transfer-target"]').findAll('option')
    expect(options.map((option) => option.text()).join('\n')).toContain('Later Page Member')
    expect(apiMocks.listMembers).toHaveBeenCalledWith('team-1', null, 100)
    expect(apiMocks.listMembers).toHaveBeenCalledWith('team-1', 'all-cursor-1', 100)
  })
})
