import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import InviteView from './InviteView.vue'

const apiMocks = vi.hoisted(() => ({
  acceptInvitation: vi.fn(),
  getInvitation: vi.fn(),
  me: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      ...apiMocks,
    },
    getAccessToken: vi.fn().mockReturnValue('access-token'),
  }
})

describe('InviteView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.getInvitation.mockResolvedValue({
      id: 'invitation-1',
      team_id: 'team-1',
      team_name: 'Platform',
      email: 'member@example.com',
      role: 'member',
      status: 'pending',
      expires_at: '2026-10-26T12:00:00+00:00',
      created_at: '2026-10-19T12:00:00+00:00',
      accepted_at: null,
    })
    apiMocks.acceptInvitation.mockResolvedValue({
      team_id: 'team-1',
      user_id: 'user-1',
      role: 'member',
      status: 'active',
    })
    apiMocks.me.mockResolvedValue({
      user: {
        id: 'user-1',
        email: 'member@example.com',
        display_name: 'Member',
        status: 'active',
        is_super_admin: false,
        is_builtin: false,
        created_at: '2026-10-19T12:00:00+00:00',
      },
      memberships: [],
    })
  })

  it('loads an invitation and accepts it for the matching account', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.token = 'access-token'
    auth.me = await apiMocks.me()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/invite/:token', component: InviteView },
        {
          path: '/knowledge-bases',
          component: { template: '<div>knowledge bases</div>' },
        },
        { path: '/login', component: { template: '<div>login</div>' } },
      ],
    })
    await router.push('/invite/invite-token')
    await router.isReady()

    const wrapper = mount(InviteView, {
      global: { plugins: [pinia, router] },
    })
    await flushPromises()

    expect(apiMocks.getInvitation).toHaveBeenCalledWith('invite-token')
    expect(wrapper.text()).toContain('Platform')
    expect(wrapper.text()).toContain('member@example.com')

    await wrapper.get('[data-testid="invite-accept"]').trigger('click')
    await flushPromises()

    expect(apiMocks.acceptInvitation).toHaveBeenCalledWith('invite-token')
    expect(router.currentRoute.value.path).toBe('/knowledge-bases')
  })
})
