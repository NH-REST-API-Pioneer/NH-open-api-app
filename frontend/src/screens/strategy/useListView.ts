import { useEffect, useMemo } from 'react'
import { useStrategyCurrency, recentOf, recordShows, type StrategyVersion } from '../../data/strategyList'
import { loadRuns, useStrategyState } from '../../data/strategyStore'
import { versionStatusOf } from '../../data/strategyList'
import type { MARKETS, RECORDS, STATUSES } from './strategyListParts'

/** 필터를 거친 줄과 고른 줄, 실행 목록 받기. */
export function useListView({
  rows,
  query,
  market,
  status,
  record,
  runningOnly,
  selectedId,
  onSelect,
}: {
  rows: StrategyVersion[]
  query: string
  market: (typeof MARKETS)[number]
  status: (typeof STATUSES)[number]
  record: (typeof RECORDS)[number]
  runningOnly: boolean
  selectedId: string | null
  onSelect: (id: string | null) => void
}) {
  /* 실행 목록은 검증·진행과 한 벌입니다. 상태 필터와 「실행 중만 보기」가 이것으로
     셉니다(`versionStatusOf`) — 돌고 있는지는 저장된 상태에 없습니다. */
  const store = useStrategyState()
  const verify = store.verify

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return rows.filter((row) => {
      if (needle && !row.name.toLowerCase().includes(needle)) return false
      if (market !== '전체' && row.market !== (market === '국내' ? 'domestic' : 'overseas')) return false
      if (status !== '전체' && versionStatusOf(row, verify.runs) !== status) return false
      if (!recordShows(row, record)) return false
      if (runningOnly && versionStatusOf(row, verify.runs) !== '실행 중') return false
      return true
    })
  }, [rows, query, market, status, record, runningOnly, verify.runs])

  /* 고른 줄이 걸러져 사라지면 상세가 표에 없는 것을 말하게 됩니다. 화면에
     서 있는 것 중 첫 줄로 옮깁니다 — 목록과 상세가 늘 같은 것을 가리킵니다. */
  useEffect(() => {
    if (shown.length === 0) {
      if (selectedId !== null) onSelect(null)
      return
    }
    if (!shown.some((row) => row.id === selectedId)) onSelect(shown[0].id)
  }, [shown, selectedId, onSelect])

  const selected = shown.find((row) => row.id === selectedId) ?? null
  /* 상세 금액의 통화. 해외인데 담긴 코드가 없으면 품목정보의 통화입니다. */
  const selectedCurrency = useStrategyCurrency(selected)
  /* 상세의 최근 성과도 표와 같은 기록 유형의 값입니다. */
  const recent = selected ? recentOf(selected, record) : null
  /* 상세 「연결 계좌」는 **그 버전의 끝나지 않은 계좌 실행이 붙은 계좌**입니다.
     실행 목록은 검증·진행과 한 벌이라 저장소에서 읽고, 아직 안 받았으면 이 화면이
     열릴 때 한 번 받습니다. */
  /* 어느 버전이든 저장하는 중이면 복제를 잠급니다 — 빨리 두 번 누르면 사본이 둘
     저장되고, 같은 밀리초면 사본의 id 가 겹칩니다. */
  const saving = store.saving !== null
  useEffect(() => {
    if (verify.status !== 'ready') void loadRuns()
    // 열릴 때 한 번만 — 그 뒤로는 허브가 채웁니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { verify, shown, selected, selectedCurrency, recent, saving }
}
