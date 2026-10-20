import { useMemo } from 'react'
import { currencyOf } from '../../data/strategyList'
import { useStrategyState } from '../../data/strategyStore'
import { runCurrencyOf } from '../../data/strategyRuns'
import { currencyCode, currencyDigits } from '../../lib/number'
import { useLimits, type LimitAxis } from '../../data/strategyLimits'
import type { useRunView } from './useRunView'
import { limitShown } from './strategyRunUtils'

type ViewValues = ReturnType<typeof useRunView>
type StoreState = ReturnType<typeof useStrategyState>

/** 머리의 계좌 손실 한도 줄 — 접속 환경의 축, 그 축의 한도와 통화, 줄 글. */
export function useRunLimits({
  environment,
  limits,
  all,
  store,
}: {
  environment: ViewValues['environment']
  limits: ReturnType<typeof useLimits>
  all: ViewValues['all']
  store: StoreState
}) {
  /* 머리 한도 줄이 보이고 고치는 축. **접속 환경이 정합니다** — 실전이면 실전
     계좌 쪽, 모의면 모의 쪽입니다. 환경을 모르면 `null` 이라 값을 세우지 않고
     「바꾸기」를 잠급니다: 다른 축의 값을 이 계좌의 것처럼 보이게 됩니다. */
  const axis: LimitAxis | null =
    environment.status === 'ready' && environment.active !== null
      ? environment.active === 'real'
        ? 'real'
        : 'paper'
      : null
  const axisLimits = axis === 'real' ? limits.real : axis === 'paper' ? limits.limits : null
  /* 이 축의 해외 통화 — 달러(늘)와, 한도를 걸었거나 이 축에 그 통화로 셈하는 실행이 있는
     통화. 걸지 않았고 실행도 없는 통화는 줄에 세우지 않습니다. */
  const axisCurrencies = useMemo(() => {
    const made = new Set<string>(['USD'])
    for (const [code, value] of Object.entries(axisLimits ?? {})) if (code !== 'KRW' && value !== null) made.add(code)
    for (const run of all) {
      if (run.mode === 'paper' || (axis === 'real') !== (run.mode === 'real')) continue
      const code = currencyCode(
        runCurrencyOf(run, currencyOf(run.market, store.rows.find((one) => one.id === run.version)?.currency)),
      )
      if (code && code !== 'KRW') made.add(code)
    }
    return ['USD', ...[...made].filter((code) => code !== 'USD').sort()]
    // 실행 목록·한도가 바뀔 때 다시 셉니다.
  }, [axisLimits, all, axis, store.rows])
  /* 머리의 한도 줄 — 「국내 1,000,000원 · 해외 USD 1,500.00 · HKD 걸지 않음」. 「해외」는
     첫 통화 앞에만 붙습니다. */
  const limitLine = axisLimits
    ? [
        `국내 ${limitShown(axisLimits.KRW ?? null, '원', currencyDigits('KRW'))}`,
        ...axisCurrencies.map(
          (code, index) =>
            `${index === 0 ? '해외 ' : ''}${code} ${limitShown(axisLimits[code] ?? null, '', currencyDigits(code))}`,
        ),
      ].join(' · ')
    : ''

  return {
    axis,
    axisLimits,
    axisCurrencies,
    limitLine,
  }
}
