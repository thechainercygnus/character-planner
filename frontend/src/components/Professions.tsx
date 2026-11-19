import { useState } from 'react'
import type { ProfessionBook, ProfessionsView, RecipeBook, RecipeCategory } from '../api'
import { ItemLink } from './ItemLink'
import { ProfessionMilestones } from './ProfessionMilestones'

function Category({ category }: { category: RecipeCategory }) {
  const known = category.recipes.filter((recipe) => recipe.known).length
  return (
    <details className="recipe-category">
      <summary>
        {category.name.toLowerCase() === 'season of discovery' ? 'Season of Discovery' : category.name}{' '}
        <span className="muted">
          {known} of {category.recipes.length} known
        </span>
      </summary>
      <ul className="recipes">
        {category.recipes.map((recipe) => (
          <li key={recipe.recipe_id}>
            <ItemLink href={recipe.wowhead}>{recipe.name}</ItemLink>
            {recipe.known && <span className="tag done">known</span>}
          </li>
        ))}
      </ul>
    </details>
  )
}

function Recipes({ profession, showSod }: { profession: ProfessionBook; showSod: boolean }) {
  const categories = profession.categories.filter((category) => showSod || !category.season_of_discovery)
  return (
    <section className="profession-recipes" aria-label={`${profession.name} recipes`}>
      <h3>{profession.name}</h3>
      <p className="muted">
        {profession.known} known
        {profession.listed
          ? ` · ${profession.unlearned} not learned yet`
          : ' · the recipes not learned yet appear after the next sync loads the full list'}
      </p>
      {categories.map((category) => (
        <Category key={category.name} category={category} />
      ))}
    </section>
  )
}

/**
 * The Professions tab (#226): each profession's rank, then its recipes by category, the
 * known ones marked. Blizzard's data gives no recipe's skill requirement, so nothing says
 * "learnable now"; each recipe links to Wowhead, which says who teaches it or where it drops.
 */
export function Professions({ professions, book }: { professions: ProfessionsView; book: RecipeBook }) {
  const [showSod, setShowSod] = useState(false)
  const sod = book.professions.reduce((sum, profession) => sum + profession.season_of_discovery, 0)
  if (book.professions.length === 0) {
    return <p className="muted">No professions yet: sync the character to see its professions and recipes.</p>
  }
  return (
    <>
      <ProfessionMilestones data={professions} />
      <section>
        <h2>Recipes</h2>
        <p className="muted">
          Battle.net doesn't say what skill each recipe needs, so they aren't sorted by when you can learn them. Each
          links to Wowhead, which says who teaches it or where it drops.
        </p>
        {book.details_pending > 0 && (
          <p className="muted">
            Looking up {book.details_pending} recipe{book.details_pending === 1 ? '' : 's'} on Battle.net: until then,
            their links search Wowhead.
          </p>
        )}
        {sod > 0 && (
          <label className="sod-toggle">
            <input type="checkbox" checked={showSod} onChange={(event) => setShowSod(event.target.checked)} /> Show
            Season of Discovery recipes ({sod}), which Forever players likely can't learn
          </label>
        )}
        {book.professions.map((profession) => (
          <Recipes key={profession.name} profession={profession} showSod={showSod} />
        ))}
      </section>
    </>
  )
}
