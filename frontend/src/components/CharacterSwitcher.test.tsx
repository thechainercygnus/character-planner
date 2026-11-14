import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { selectCharacter, selectedCharacter, type AccountCharacter, type CharacterList } from '../api'
import { CharacterSwitcher } from './CharacterSwitcher'

const LIST: CharacterList = {
  default_id: 1,
  characters: [
    {
      id: 1,
      region: 'us',
      slug: 'brumboldt-doomlet',
      name: 'Brumboldt',
      surname: 'Doomlet',
      character_class: 'Warrior',
      race: 'Gnome',
      faction: 'ALLIANCE',
      level: 19,
    },
    {
      id: 2,
      region: 'eu',
      slug: 'thrall-goelson',
      name: 'Thrall',
      surname: 'Goelson',
      character_class: null,
      race: null,
      faction: null,
      level: null,
    },
  ],
}

interface Call {
  url: string
  method: string
  character: string | null
  body: unknown
}

const ACCOUNT: { characters: AccountCharacter[] } = {
  characters: [
    { ...LIST.characters[0]!, blizzard_id: 14060175, level: 18, tracked: true },
    {
      blizzard_id: 90000001,
      name: 'Testy',
      surname: 'Mcfixture',
      slug: 'testy-mcfixture',
      region: 'eu',
      character_class: 'Priest',
      race: 'Dwarf',
      faction: 'ALLIANCE',
      level: 6,
      tracked: false,
    },
  ],
}

function serve(list: CharacterList = LIST, signedIn = true) {
  const calls: Call[] = []
  let listed = list
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const headers = new Headers(init?.headers)
      calls.push({
        url,
        method: init?.method ?? 'GET',
        character: headers.get('X-Character-Id'),
        body: init?.body ? JSON.parse(String(init.body)) : null,
      })
      if (url === '/api/characters' && init?.method === 'POST') {
        const added = { ...LIST.characters[1]!, id: 3, slug: 'jaina-proudmoore', name: 'Jaina', surname: 'Proudmoore' }
        listed = { ...listed, characters: [...listed.characters, added] }
        return Response.json(added, { status: 201 })
      }
      if (url === '/api/characters') return Response.json(listed)
      if (url === '/api/account/characters') {
        return signedIn
          ? Response.json(ACCOUNT)
          : Response.json({ detail: 'Sign in with Battle.net to list your characters' }, { status: 401 })
      }
      return Response.json({})
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <CharacterSwitcher />
    </QueryClientProvider>,
  )
  return calls
}

describe('CharacterSwitcher', () => {
  beforeEach(() => selectCharacter(null))
  afterEach(() => {
    vi.unstubAllGlobals()
    selectCharacter(null)
  })

  it('lists the characters and sends the one chosen with every request', async () => {
    const calls = serve()
    const select = await screen.findByRole('combobox', { name: 'Character' })
    expect([...select.querySelectorAll('option')].map((o) => o.textContent)).toEqual([
      'Brumboldt Doomlet · level 19 · Warrior',
      'Thrall Goelson · not synced',
      'Add a character…',
    ])
    expect((select as HTMLSelectElement).value).toBe('1') // the default
    expect(calls[0]?.character).toBeNull()

    fireEvent.change(select, { target: { value: '2' } })
    expect(selectedCharacter()).toBe(2)
    await waitFor(() => expect(calls.at(-1)?.character).toBe('2')) // refetched as Thrall
  })

  it('adds a character, then selects and syncs it', async () => {
    const calls = serve()
    fireEvent.change(await screen.findByRole('combobox', { name: 'Character' }), { target: { value: 'add' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'First name' }), { target: { value: 'Jaina' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Surname' }), { target: { value: 'Proudmoore' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Region' }), { target: { value: 'eu' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add and sync' }))

    await waitFor(() => expect(calls.some((c) => c.url === '/api/sync')).toBe(true))
    expect(calls.find((c) => c.method === 'POST' && c.url === '/api/characters')?.body).toEqual({
      name: 'Jaina',
      surname: 'Proudmoore',
      region: 'eu',
    })
    expect(calls.find((c) => c.url === '/api/sync')?.character).toBe('3') // synced as the new one
    expect(selectedCharacter()).toBe(3)
    await waitFor(() => expect(screen.queryByRole('form', { name: 'Add a character' })).toBeNull())
  })

  it('lists the account characters not tracked yet and tracks one', async () => {
    const calls = serve()
    fireEvent.change(await screen.findByRole('combobox', { name: 'Character' }), { target: { value: 'add' } })
    const list = await screen.findByRole('list', { name: 'Your Battle.net characters' })
    expect(list.textContent).toBe('Testy Mcfixture · level 6 Priest Track') // Brumboldt is tracked
    fireEvent.click(screen.getByRole('button', { name: 'Track' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/sync')).toBe(true))
    expect(calls.find((c) => c.method === 'POST' && c.url === '/api/characters')?.body).toEqual({
      name: 'Testy',
      surname: 'Mcfixture',
      region: 'eu',
    })
  })

  it('offers the Battle.net sign-in when the account cannot be listed', async () => {
    serve(LIST, false)
    fireEvent.change(await screen.findByRole('combobox', { name: 'Character' }), { target: { value: 'add' } })
    const link = await screen.findByRole('link', { name: 'Sign in with Battle.net' })
    expect(link.getAttribute('href')).toBe('/auth/login')
    expect(screen.getByRole('textbox', { name: 'First name' })).toBeTruthy() // typing still works
  })

  it('goes back to the default when the remembered character is gone', async () => {
    selectCharacter(99)
    serve()
    await screen.findByRole('combobox', { name: 'Character' })
    await waitFor(() => expect(selectedCharacter()).toBeNull())
  })
})
