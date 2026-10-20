import { AxiosError } from 'axios'

import { ApiRequestError, clearAccessToken, http, normalizeApiError, setAccessToken } from './client'

describe('normalizeApiError', () => {
  it('maps the backend error envelope and request id', () => {
    const normalized = normalizeApiError({
      isAxiosError: true,
      message: 'Request failed',
      response: {
        status: 403,
        headers: { 'x-request-id': 'req-header' },
        data: {
          error: {
            code: 'PERMISSION_DENIED',
            message: 'Access denied.',
            request_id: 'req-body',
            details: { resource: 'team' },
          },
        },
      },
    })

    expect(normalized).toBeInstanceOf(ApiRequestError)
    expect(normalized.code).toBe('PERMISSION_DENIED')
    expect(normalized.requestId).toBe('req-body')
    expect(normalized.status).toBe(403)
    expect(normalized.details).toEqual({ resource: 'team' })
  })

  it('falls back to a generic error for non-axios failures', () => {
    const normalized = normalizeApiError(new Error('network down'))

    expect(normalized.code).toBe('UNKNOWN_ERROR')
    expect(normalized.message).toBe('network down')
  })
})

describe('authenticated HTTP client', () => {
  afterEach(() => {
    clearAccessToken()
    http.defaults.adapter = undefined
  })

  it('refreshes once after a 401 and retries the original request', async () => {
    setAccessToken('expired-access-token')
    let resourceCalls = 0
    let refreshCalls = 0

    http.defaults.adapter = async (config) => {
      if (config.url === '/auth/refresh') {
        refreshCalls += 1
        expect(config.headers.get('Authorization')).toBeUndefined()
        return {
          data: {
            data: { access_token: 'fresh-access-token', token_type: 'bearer' },
          },
          status: 200,
          statusText: 'OK',
          headers: {},
          config,
        }
      }

      resourceCalls += 1
      if (resourceCalls === 1) {
        throw new AxiosError('Expired.', 'ERR_BAD_REQUEST', config, undefined, {
          data: {
            error: {
              code: 'UNAUTHENTICATED',
              message: 'Expired.',
              details: {},
              request_id: 'req-expired',
            },
          },
          status: 401,
          statusText: 'Unauthorized',
          headers: {},
          config,
        })
      }

      expect(config.headers.get('Authorization')).toBe('Bearer fresh-access-token')
      return {
        data: { data: { ok: true } },
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      }
    }

    const response = await http.get('/resource')

    expect(refreshCalls).toBe(1)
    expect(resourceCalls).toBe(2)
    expect(response.data.data).toEqual({ ok: true })
  })
})
