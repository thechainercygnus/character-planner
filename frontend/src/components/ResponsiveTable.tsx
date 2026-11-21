import { useId, type ReactNode } from 'react'

export function ResponsiveTable({
  caption,
  className,
  children,
}: {
  caption: string
  className?: string
  children: ReactNode
}) {
  const captionId = useId()
  return (
    <div className="gear-scroll" role="region" aria-labelledby={captionId} tabIndex={0}>
      <table className={className ? `gear ${className}` : 'gear'}>
        <caption id={captionId} className="visually-hidden">
          {caption}
        </caption>
        {children}
      </table>
    </div>
  )
}
