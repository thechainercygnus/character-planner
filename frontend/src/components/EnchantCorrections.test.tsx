import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { EnchantAdvice, EnchantCorrectionsView, EnchantOption } from '../api'
import { enchantAdvice } from '../test/fixtures'
import { Enchants } from './Enchants'

const view: EnchantCorrectionsView = {
  corrections: { reagent_levels: {}, crafted_effects: {}, per_slot: null },
  shipped: { reagent_levels: { '10940': 1 }, crafted_effects: { '4405': { 'Weapon Damage': 1 } }, per_slot: 3 },
  effect_names: ['Strength', 'Agility', 'Stamina', 'Armor', 'Weapon Damage'],
}

// Minor Striking's real materials: Strange Dust (shipped 1), Lesser Magic Essence (corrected
// to 12) and Small Glimmering Shard (shipped 11).
const striking: EnchantOption = {
  ...enchantAdvice.rows[0].picks[0].option,
  recipe_id: 4367,
  name: 'Enchant Weapon - Minor Striking',
  slots: ['MAIN_HAND'],
  effects: { 'Weapon Damage': 1 },
  estimated_level: 12,
  reagents: [
    { item_id: 10940, name: 'Strange Dust', quantity: 2, level: 1, level_source: 'shipped' },
    { item_id: 10938, name: 'Lesser Magic Essence', quantity: 1, level: 12, level_source: 'corrected' },
    { item_id: 10978, name: 'Small Glimmering Shard', quantity: 1, level: 11, level_source: 'shipped' },
  ],
}
// Crude Scope: its effect is on the crafted item, 4405.
const scope: EnchantOption = {
  ...striking,
  recipe_id: 2421,
  name: 'Crude Scope',
  profession: 'Engineering',
  slots: ['RANGED'],
  crafted_item_id: 4405,
  effects: { 'Weapon Damage': 1 },
  effects_source: 'curated',
  reagents: [{ item_id: 4371, name: 'Bronze Tube', quantity: 1, level: null, level_source: null }],
}

const advice: EnchantAdvice = {
  ...enchantAdvice,
  per_slot: 2,
  per_slot_corrected: true,
  missing_effects: [{ item_id: 6043, recipe: 'Iron Counterweight', slots: ['MAIN_HAND'] }],
  rows: [
    {
      slot: 'MAIN_HAND',
      item: 'Thelsamar Axe',
      current: null,
      current_is_weaker: false,
      picks: [{ option: striking, score: 2, score_gain: 2, usable_now: true, can_make: false }],
    },
    {
      slot: 'RANGED',
      item: 'Rough Boomstick',
      current: null,
      current_is_weaker: false,
      picks: [{ option: scope, score: 1, score_gain: 1, usable_now: true, can_make: true }],
    },
  ],
}

function renderEnchants(data: EnchantAdvice = advice) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <Enchants data={data} />
    </QueryClientProvider>,
  )
}

describe('Enchant corrections', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    fetchMock = vi.fn(async () => Response.json(view))
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows each material with its level and where it comes from', () => {
    renderEnchants()

    const dust = screen.getByLabelText('Level of Strange Dust') as HTMLInputElement
    expect(dust.value).toBe('1')
    const essence = screen.getByLabelText('Level of Lesser Magic Essence').closest('li')!
    expect(within(essence).getByText('corrected').className).toBe('tag')
    expect(within(essence).getByRole('button', { name: 'Reset' })).toBeTruthy()
    const tube = screen.getByLabelText('Level of Bronze Tube') as HTMLInputElement
    expect(tube.value).toBe('')
  })

  it('saves a material level, and resets a corrected one', async () => {
    renderEnchants()

    fireEvent.change(screen.getByLabelText('Level of Strange Dust'), { target: { value: '5' } })
    fireEvent.click(within(screen.getByLabelText('Level of Strange Dust').closest('li')!).getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/enchants/corrections/materials/10940', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ level: 5 }),
      }),
    )

    const essence = screen.getByLabelText('Level of Lesser Magic Essence').closest('li')!
    fireEvent.click(within(essence).getByRole('button', { name: 'Reset' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/enchants/corrections/materials/10938', { method: 'DELETE' }),
    )
  })

  it('refuses a level outside 1 to 60', () => {
    renderEnchants()
    fireEvent.change(screen.getByLabelText('Level of Strange Dust'), { target: { value: '61' } })
    const save = within(screen.getByLabelText('Level of Strange Dust').closest('li')!).getByRole('button', {
      name: 'Save',
    }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
  })

  it('fixes a crafted enchant’s effect', async () => {
    renderEnchants()
    const editor = screen.getByLabelText('Effect of Crude Scope')
    fireEvent.change(within(editor).getByLabelText('Value'), { target: { value: '2' } })
    fireEvent.click(within(editor).getByRole('button', { name: 'Save effect' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/enchants/corrections/crafted/4405', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ effects: { 'Weapon Damage': 2 } }),
      }),
    )
  })

  it('lists crafted enchants without an effect, to fill in', async () => {
    renderEnchants()
    const editor = screen.getByLabelText('Effect of Iron Counterweight')
    await waitFor(() => expect(within(editor).getAllByRole('option').length).toBeGreaterThan(1))
    fireEvent.change(within(editor).getByLabelText('Effect'), { target: { value: 'Armor' } })
    fireEvent.change(within(editor).getByLabelText('Value'), { target: { value: '20' } })
    fireEvent.click(within(editor).getByRole('button', { name: 'Save effect' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/enchants/corrections/crafted/6043',
        expect.objectContaining({ body: JSON.stringify({ effects: { Armor: 20 } }) }),
      ),
    )
  })

  it('changes and resets how many enchants a slot lists', async () => {
    renderEnchants()
    fireEvent.change(screen.getByRole('combobox', { name: /per slot/ }), { target: { value: '4' } })
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/enchants/corrections/per-slot',
        expect.objectContaining({ method: 'PUT', body: JSON.stringify({ per_slot: 4 }) }),
      ),
    )
    const control = screen.getByRole('combobox', { name: /per slot/ }).closest('label')!
    fireEvent.click(within(control).getByRole('button', { name: 'Reset' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/enchants/corrections/per-slot', { method: 'DELETE' }),
    )
  })
})
