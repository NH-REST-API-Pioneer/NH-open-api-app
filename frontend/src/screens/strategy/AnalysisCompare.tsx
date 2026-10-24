import { useMemo } from 'react'
import {
  amountText,
  netOf,
  tradesOf,
  winRate,
  type Dataset,
  type StrategyPerf,
} from '../../data/strategyRecords'
import { Amount, countText, drawdownTitle, perfName } from './StrategyAnalysisParts'

/** 비교표의 한 줄. 버전이 둘 이상인 전략은 그 위에 묶음 줄이 섭니다. */
type CompareLine =
  | { kind: 'group'; key: string; name: string; members: StrategyPerf[] }
  | { kind: 'version'; perf: StrategyPerf; sub: boolean }

/** 같은 전략의 버전끼리 잇습니다. 묶음은 처음 나온 차례, 묶음 안은 버전 글자
 *  차례입니다. 묶음을 모르는 버전(지워진 것)은 혼자 섭니다. */
function compareLines(strategies: StrategyPerf[]): CompareLine[] {
  const order: string[] = []
  const members = new Map<string, StrategyPerf[]>()
  for (const perf of strategies) {
    const key = perf.groupId ?? `version:${perf.id}`
    const held = members.get(key)
    if (held) held.push(perf)
    else {
      members.set(key, [perf])
      order.push(key)
    }
  }
  return order.flatMap((key): CompareLine[] => {
    const list = [...(members.get(key) ?? [])].sort((a, b) =>
      a.version.localeCompare(b.version, 'ko', { numeric: true }),
    )
    if (list.length < 2) return list.map((perf) => ({ kind: 'version', perf, sub: false }))
    return [
      { kind: 'group', key, name: list[0].name, members: list },
      ...list.map((perf): CompareLine => ({ kind: 'version', perf, sub: true })),
    ]
  })
}

export function Compare({
  data,
  pickedId,
  shownId,
  onPick,
  net,
  rate,
  mdd,
}: {
  data: Dataset
  pickedId: string | null
  shownId: string | null
  /** 곡선에 올릴 전략. `null` 이면 합계만입니다. */
  onPick: (id: string | null) => void
  net: number
  rate: number | null
  mdd: number | null
}) {
  const currency = data.currency
  const lines = useMemo(() => compareLines(data.strategies), [data.strategies])
  const empty = data.strategies.length === 0
  const pct = (value: number | null) => (value === null ? '—' : `${value}%`)
  return (
    <div className="card ana-table">
      <table className="data-table rows-base">
        <thead>
          <tr>
            <th className="ana-col-pick" scope="col" aria-label="곡선" />
            <th className="col-text" scope="col">전략</th>
            <th scope="col">거래 수</th>
            <th scope="col">승률</th>
            <th scope="col">순손익</th>
            <th scope="col">낙폭</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => {
            if (line.kind === 'group') {
              /* 묶음 줄. 곡선은 버전 단위라 고르는 칸이 없습니다. 낙폭은 서버가
                 묶음 버전들의 거래를 합쳐 센 값을 씁니다. 그 값이 없으면 「—」입니다
                 — 버전 낙폭을 더하면 어느 시점에도 없던 수가 됩니다.
                 묶음 낙폭을 싣지 않는 서버면 버전 줄을 가리키고, 실었는데 값이
                 없으면(이 기간에 순손익을 아는 종료 거래가 없음) 그 까닭을 적습니다.
                 이때는 버전 줄도 모두 「—」입니다. */
              const list = line.members.flatMap((perf) => tradesOf(data, perf.id))
              const entry = data.groups.find((one) => one.groupId === line.key)
              const low = entry?.maxDrawdown ?? null
              const lowTitle =
                low !== null
                  ? drawdownTitle(data.drawdownBasis)
                  : entry
                    ? '묶음 낙폭을 셀 수 없습니다 — 이 기간에 순손익을 아는 종료 거래가 없습니다'
                    : '버전마다의 낙폭은 아래 줄에'
              return (
                <tr key={`group:${line.key}`} className="ana-group">
                  <td className="ana-col-pick" />
                  <td className="col-text">{line.name}</td>
                  <td>{countText(list.length)}</td>
                  <td>{pct(winRate(list))}</td>
                  <td>
                    <Amount
                      value={line.members.reduce((sum, perf) => sum + netOf(perf), 0)}
                      currency={currency}
                      signed
                      toned
                    />
                  </td>
                  <td title={lowTitle}>
                    {low === null ? '—' : amountText(low, currency)}
                  </td>
                </tr>
              )
            }
            const { perf } = line
            const list = tradesOf(data, perf.id)
            const on = pickedId === perf.id
            return (
              <tr key={perf.id} aria-selected={on}>
                <td className="ana-col-pick">
                  <input
                    className="ana-pick"
                    type="radio"
                    name="ana-curve-pick"
                    checked={on}
                    aria-label={`${perfName(perf)} 곡선에 올리기`}
                    onChange={() => onPick(perf.id)}
                  />
                </td>
                <td className={`col-text${line.sub ? ' ana-sub' : ''}`} title={perfName(perf)}>
                  {/* 색 점이 아니라 선 모양 조각입니다 — 곡선에서 이 전략이
                      어떤 선인지를 같은 모양으로 말합니다. */}
                  {shownId === perf.id && <span className="ana-pick-mark" aria-hidden="true" />}
                  {/* 묶음 줄 아래의 버전은 이름을 되풀이하지 않습니다. 지운 버전(버전
                      글자 없음)의 이름은 `perfName` 이 가립니다. */}
                  {!line.sub && (perf.version ? perf.name : perfName(perf))}
                  {!line.sub && perf.version && ' '}
                  {perf.version && <span className="ana-ver">{perf.version}</span>}
                </td>
                <td>{countText(list.length)}</td>
                <td>{pct(winRate(list))}</td>
                <td>
                  <Amount value={netOf(perf)} currency={currency} signed toned />
                </td>
                <td title={perf.maxDrawdown === null ? undefined : drawdownTitle(data.drawdownBasis)}>
                  {perf.maxDrawdown === null ? '—' : amountText(perf.maxDrawdown, currency)}
                </td>
              </tr>
            )
          })}
          {empty && (
            <tr>
              <td className="ana-empty-row" colSpan={6}>
                이 기간에 종료된 거래가 없습니다
              </td>
            </tr>
          )}
        </tbody>
        {!empty && (
          <tfoot>
            {/* 합계를 고르면 전략 줄과 같은 강조가 이 줄에 섭니다. */}
            <tr aria-selected={pickedId === null}>
              {/* 합계만 그리는 고르개. 합계 선은 늘 그려지므로 그 선 모양 조각도
                  늘 섭니다 — 고른 전략의 조각과 같은 자리(이름 앞)라, 고르는 칸의
                  라디오가 위 줄들과 한 세로줄에 섭니다. */}
              <td className="ana-col-pick">
                <input
                  className="ana-pick"
                  type="radio"
                  name="ana-curve-pick"
                  checked={pickedId === null}
                  aria-label={`${data.totalLabel}만 곡선에 올리기`}
                  onChange={() => onPick(null)}
                />
              </td>
              <td className="col-text">
                <span className="ana-solid" aria-hidden="true" />
                {data.totalLabel}
              </td>
              <td>{countText(data.trades.length)}</td>
              <td>{pct(rate)}</td>
              <td>
                <Amount value={net} currency={currency} signed toned />
              </td>
              <td title={mdd === null ? undefined : drawdownTitle(data.drawdownBasis)}>
                {mdd === null ? '—' : amountText(mdd, currency)}
              </td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  )
}
