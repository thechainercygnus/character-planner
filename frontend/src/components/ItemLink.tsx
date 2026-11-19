import type { ReactNode } from 'react'

/**
 * An item's name linking to its Wowhead page (#225), in a new tab; plain text when the server
 * knows no page for it. The server builds every link (links.py), so this never makes one up.
 * A click doesn't reach the row or button around it.
 */
export function ItemLink({
  href,
  children,
  title,
  label,
}: {
  href: string | null | undefined
  children: ReactNode
  title?: string | undefined
  /** The link's name, when its text alone doesn't say which item. */
  label?: string
}) {
  if (!href) return title ? <span title={title}>{children}</span> : <>{children}</>
  return (
    <a
      className="item-link"
      href={href}
      target="_blank"
      rel="noreferrer"
      title={title}
      aria-label={label}
      onClick={(event) => event.stopPropagation()}
    >
      {children}
    </a>
  )
}
