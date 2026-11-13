import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type ClassQuestChecklist, type ClassQuestRow, type ClassQuestStatus } from '../api'

const GROUPS: { status: ClassQuestStatus; title: string }[] = [
  { status: 'missed', title: 'Missed' },
  { status: 'now', title: 'Available now' },
  { status: 'soon', title: 'Coming soon' },
  { status: 'later', title: 'Later' },
  { status: 'done', title: 'Done' },
]

function QuestRow({ row, onToggle, pending }: { row: ClassQuestRow; onToggle: () => void; pending: boolean }) {
  const where = [row.giver, row.location].filter(Boolean).join(', ')
  return (
    <li className={`class-quest status-${row.status}`}>
      <label>
        <input type="checkbox" checked={row.done} disabled={pending} onChange={onToggle} />
        <span className="class-quest-level">{row.level}</span>
        <span>
          <strong>{row.name}</strong>
          {row.essential && <span className={row.status === 'missed' ? 'tag warn' : 'tag'}>essential</span>}
          {row.reward && <small>{row.reward}</small>}
          {where && <small className="muted">{where}</small>}
        </span>
      </label>
    </li>
  )
}

/**
 * The class quest checklist (#8): quests that unlock class abilities, grouped by when they
 * can be done. Done marks are set by hand. An essential quest at or below the
 * character's level that isn't done is "missed".
 */
export function ClassQuests({ data }: { data: ClassQuestChecklist }) {
  const queryClient = useQueryClient()
  const toggle = useMutation({
    mutationFn: api.setClassQuestDone,
    onSuccess: (checklist) => {
      queryClient.setQueryData(['class-quests'], checklist)
      return queryClient.invalidateQueries({ queryKey: ['look-ahead'] })
    },
  })
  const missed = data.rows.filter((row) => row.status === 'missed').length

  return (
    <section className="class-quests">
      <div className="section-heading">
        <h2>
          Class quests {data.class_name && <span className="muted">{data.class_name}</span>}
        </h2>
      </div>
      {data.listed === 0 ? (
        <p className="muted">No class quests loaded yet: they come with the next item pool refresh.</p>
      ) : data.rows.length === 0 ? (
        <p className="muted">Forever Companion lists no class quests for your class yet.</p>
      ) : (
        <>
          <p className={missed > 0 ? 'warn' : 'muted'}>
            {missed > 0
              ? `${missed} essential quest${missed === 1 ? '' : 's'} at or below your level not done yet.`
              : `Nothing essential missed. Coming soon looks ${data.soon_levels} levels ahead.`}{' '}
            Tick a quest once you've done it.
          </p>
          {toggle.isError && <p className="error">Couldn't save: {toggle.error.message}</p>}
          {GROUPS.map(({ status, title }) => {
            const rows = data.rows.filter((row) => row.status === status)
            if (rows.length === 0) return null
            return (
              <div key={status} className="class-quest-group">
                <h3>{title}</h3>
                <ul aria-label={title}>
                  {rows.map((row) => (
                    <QuestRow
                      key={row.id}
                      row={row}
                      pending={toggle.isPending}
                      onToggle={() => toggle.mutate({ id: row.id, done: !row.done })}
                    />
                  ))}
                </ul>
              </div>
            )
          })}
        </>
      )}
    </section>
  )
}
