import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { useAuthStore } from '@/stores/auth'
import SettingsView from './SettingsView.vue'

const apiMocks = vi.hoisted(() => ({
  changePassword: vi.fn(),
  me: vi.fn(),
  updateProfile: vi.fn(),
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

const me = {
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
      role: 'leader' as const,
      status: 'active',
    },
  ],
}

function makePinia() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.token = 'token'
  auth.me = structuredClone(me)
  return pinia
}

function mountPage() {
  return mount(SettingsView, {
    global: {
      plugins: [makePinia()],
      stubs: {
        RouterLink: {
          props: ['to'],
          template: '<a :href="String(to)"><slot /></a>',
        },
      },
    },
  })
}

describe('SettingsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.updateProfile.mockResolvedValue({
      ...me.user,
      display_name: 'New Leader',
    })
    apiMocks.me.mockResolvedValue({
      ...structuredClone(me),
      user: { ...me.user, display_name: 'New Leader' },
    })
  })

  it('updates the current display name and refreshes the current user', async () => {
    const wrapper = mountPage()
    const auth = useAuthStore()

    await wrapper.get('[data-testid="profile-display-name"]').setValue('  New Leader  ')
    await wrapper.get('[data-testid="profile-form"]').trigger('submit')
    await flushPromises()

    expect(apiMocks.updateProfile).toHaveBeenCalledWith('New Leader')
    expect(apiMocks.me).toHaveBeenCalledOnce()
    expect(auth.me?.user.display_name).toBe('New Leader')
  })

  it('links members to the settings route', () => {
    const wrapper = mountPage()

    expect(wrapper.find('a[href="/settings/members"]').exists()).toBe(true)
    expect(wrapper.find('a[href="/members"]').exists()).toBe(false)
  })
})
