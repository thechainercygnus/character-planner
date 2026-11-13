// Frontend coverage as a Markdown table, for the CI job summary (#55).
// Reads coverage/coverage-summary.json from `npm run coverage` and prints the totals.
import { readFileSync } from 'node:fs'

const { total } = JSON.parse(readFileSync('coverage/coverage-summary.json', 'utf8'))
const rows = ['statements', 'branches', 'functions', 'lines'].map((kind) => {
  const { covered, total: count, pct } = total[kind]
  return `| ${kind[0].toUpperCase()}${kind.slice(1)} | ${pct.toFixed(1)}% | ${covered} / ${count} |`
})
console.log(['### Frontend coverage', '', '| | Covered | |', '| --- | ---: | ---: |', ...rows].join('\n'))
