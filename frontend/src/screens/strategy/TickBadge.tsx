import { kstClock } from '../../lib/kst'

/** 시각 칸 옆의 「틱」 표지. 봉이 끝나기 전에 규칙 판정으로 난 줄에만 섭니다
 *  (`tickBarOf`). 어느 봉이었는지는 마우스를 올리면 보입니다 — 봉 시작 시각을 모르면
 *  시각 없이 적습니다. */
export function TickBadge({ barTime }: { barTime: number | null }) {
  const bar = barTime !== null && Number.isFinite(barTime) ? `${kstClock(barTime)} 봉이` : '봉이'
  return (
    <span className="badge tick-badge" title={`틱 판정 — ${bar} 끝나기 전에 낸 신호`}>
      틱
    </span>
  )
}
