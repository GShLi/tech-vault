import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import LoginView from './LoginView.vue'

const apiMocks = vi.hoisted(() => ({
  login: vi.fn(),
  me: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      login: apiMocks.login,
      me: apiMocks.me,
    },
    getAccessToken: vi.fn().mockReturnValue(null),
    setAccessToken: vi.fn(),
    clearAccessToken: vi.fn(),
  }
})

describe('LoginView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    apiMocks.login.mockResolvedValue({
      access_token: 'token',
      token_type: 'bearer',
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

  it('submits credentials and navigates to team selection', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/login', component: LoginView },
        { path: '/teams', component: { template: '<div>teams</div>' } },
      ],
    })
    await router.push('/login')
    await router.isReady()

    const wrapper = mount(LoginView, {
      global: {
        plugins: [router],
        stubs: { RouterLink: true },
      },
    })

    await wrapper.find('[data-testid="login-email"]').setValue('member@example.com')
    await wrapper.find('[data-testid="login-password"]').setValue('password-123')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiMocks.login).toHaveBeenCalledWith({
      email: 'member@example.com',
      password: 'password-123',
    })
    expect(router.currentRoute.value.path).toBe('/teams')
  })
})
