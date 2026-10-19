import { ApiRequestError, normalizeApiError } from './client'

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
