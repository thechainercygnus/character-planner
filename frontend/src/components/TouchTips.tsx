import { useEffect, useState } from 'react'
import { EDGE, TIP_MS, TIP_WIDTH, tipFor } from '../touchTip'

interface Tip {
  text: string
  left: number
  top: number
}

/**
 * Touch screens never show `title` tooltips (#153). On a tap, show the tapped element's
 * tooltip text beside it for a few seconds: talent descriptions, enchant effects, what a
 * badge means. Mouse users keep the browser's own tooltips.
 */
export function TouchTips() {
  const [tip, setTip] = useState<Tip | null>(null)

  useEffect(() => {
    const onTap = (event: PointerEvent) => {
      if (event.pointerType !== 'touch') return
      const found = tipFor(event.target)
      if (!found) {
        setTip(null)
        return
      }
      const box = found.anchor.getBoundingClientRect()
      const width = Math.min(TIP_WIDTH, window.innerWidth - 2 * EDGE)
      const centred = box.left + box.width / 2 - width / 2
      setTip({
        text: found.text,
        left: Math.max(EDGE, Math.min(centred, window.innerWidth - width - EDGE)),
        top: box.bottom + 6,
      })
    }
    document.addEventListener('pointerup', onTap)
    return () => document.removeEventListener('pointerup', onTap)
  }, [])

  useEffect(() => {
    if (!tip) return
    const timer = setTimeout(() => setTip(null), TIP_MS)
    return () => clearTimeout(timer)
  }, [tip])

  if (!tip) return null
  return (
    <div className="touch-tip" role="status" style={{ left: tip.left, top: tip.top, maxWidth: TIP_WIDTH }}>
      {tip.text}
    </div>
  )
}
