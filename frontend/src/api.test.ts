import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, slotLabel } from './api'

describe('slotLabel', () => {
  it('turns Battle.net slot types into readable labels', () => {
    expect(slotLabel('MAIN_HAND')).toBe('Main Hand')
    expect(slotLabel('FINGER_1')).toBe('Finger 1')
    expect(slotLabel('HEAD')).toBe('Head')
  })
})

describe('api', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('surfaces FastAPI error details', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: 'Not logged in' }), {
          status: 401,
          statusText: 'Unauthorized',
        }),
      ),
    )

    const error = await api.sync().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(401)
    expect((error as ApiError).message).toBe('Not logged in')
  })
})
