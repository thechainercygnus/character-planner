import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, selectCharacter, selectedCharacter, slotLabel } from './api'

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
      vi.fn(
        async () =>
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

describe('a remembered character that is gone', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    selectCharacter(null)
  })

  function serve(unknownHeader: boolean) {
    const sent: (string | null)[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) => {
        const character = new Headers(init?.headers).get('X-Character-Id')
        sent.push(character)
        if (character === null) return Response.json({ level: 19 })
        return Response.json(
          { detail: `No character ${character}` },
          { status: 404, headers: unknownHeader ? { 'X-Character-Unknown': 'true' } : {} },
        )
      }),
    )
    return sent
  }

  it('is forgotten, and the request asked again for the default', async () => {
    selectCharacter(3) // e.g. from before a fresh database
    const sent = serve(true)
    expect(await api.character()).toEqual({ level: 19 })
    expect(sent).toEqual(['3', null])
    expect(selectedCharacter()).toBeNull()
  })

  it('only on the marked 404: other errors still surface', async () => {
    selectCharacter(3)
    const sent = serve(false)
    await expect(api.character()).rejects.toEqual(new ApiError(404, 'No character 3'))
    expect(sent).toEqual(['3'])
    expect(selectedCharacter()).toBe(3)
  })

  it('never loops: without a selection there is nothing to forget', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        Response.json({ detail: 'No character 9' }, { status: 404, headers: { 'X-Character-Unknown': 'true' } }),
      ),
    )
    await expect(api.character()).rejects.toBeInstanceOf(ApiError)
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1)
  })
})

describe('sync', () => {
  afterEach(() => vi.unstubAllGlobals())

  function serve(...answers: Response[]) {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? 'GET'} ${url}`)
        return answers.shift() ?? Response.json({})
      }),
    )
    return calls
  }
  const noWait = async () => {}
  const state = (s: string, extra: object = {}) => Response.json({ state: s, result: null, error: null, ...extra })

  it('passes a direct answer through, as without a job queue', async () => {
    serve(Response.json({ profile: 200 }))
    expect(await api.sync(noWait)).toEqual({ profile: 200 })
  })

  it('follows a queued sync until it finishes (#17)', async () => {
    const calls = serve(
      Response.json({ state: 'queued', result: null, error: null }, { status: 202 }),
      state('queued'),
      state('started'),
      state('finished', { result: { profile: 200, equipment: 404 } }),
    )
    expect(await api.sync(noWait)).toEqual({ profile: 200, equipment: 404 })
    expect(calls).toEqual(['POST /api/sync', 'GET /api/sync', 'GET /api/sync', 'GET /api/sync'])
  })

  it('says why a queued sync failed', async () => {
    serve(
      Response.json({ state: 'queued', result: null, error: null }, { status: 202 }),
      state('failed', { error: 'LookupError: No character 1: it was deleted' }),
    )
    await expect(api.sync(noWait)).rejects.toThrow('No character 1: it was deleted')
  })
})
