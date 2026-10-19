import { createPinia, setActivePinia } from 'pinia'

import { useAuthStore } from './auth'

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  register: vi.fn(),
  me: vi.fn(),
  getToken: vi.fn(),
  setToken: vi.fn(),
  clearToken: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      login: mocks.login,
      register: mocks.register,
      me: mocks.me,
    },
    getAccessToken: mocks.getToken,
    setAccessToken: mocks.setToken,
    clearAccessToken: mocks.clearToken,
  }
})

const me = {
  user: {
    id: 'user-1',
    email: 'member@example.com',
    display_name: 'Member',
    status: 'active',
    created_at: '2026-10-19T12:00:00+00:00',
  },
  memberships: [],
}

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mocks.getToken.mockReturnValue(null)
  })

  it('stores the token and loads the current user after login', async () => {
    mocks.login.mockResolvedValue({
      access_token: 'access-token',
      token_type: 'bearer',
    })
    mocks.me.mockResolvedValue(me)

    const auth = useAuthStore()
    await auth.login('member@example.com', 'password-123')

    expect(mocks.login).toHaveBeenCalledWith({
      email: 'member@example.com',
      password: 'password-123',
    })
    expect(mocks.setToken).toHaveBeenCalledWith('access-token')
    expect(auth.token).toBe('access-token')
    expect(auth.me?.user.display_name).toBe('Member')
    expect(auth.isAuthenticated).toBe(true)
  })

  it('clears token and user state on logout', () => {
    const auth = useAuthStore()
    auth.token = 'access-token'
    auth.me = me

    auth.logout()

    expect(mocks.clearToken).toHaveBeenCalled()
    expect(auth.token).toBeNull()
    expect(auth.me).toBeNull()
  })
})
