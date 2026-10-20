import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import {
  amountText,
  averageHolding,
  bySide,
  holdingText,
  minuteText,
  segments,
  type Dataset,
  type Trade,
} from '../../data/strategyRecords'
import { FEE_ASSUMED } from '../../data/strategyRuns'
import {
  TRADE_PAGE,
  CODE_FITS,
  Amount,
  countText,
  codeName,
  perfName,
  EmptyRange,
} from './StrategyAnalysisParts'

/* 손익비·Profit Factor·연속손실. 모두 거래 목록에서 냅니다. */
export function Detail({ trades }: { trades: Trade[] }) {
  const gains = trades.filter((trade) => trade.net > 0).map((trade) => trade.net)
  const losses = trades.filter((trade) => trade.net < 0).map((trade) => -trade.net)
  const sum = (list: number[]) => list.reduce((a, b) => a + b, 0)
  const avg = (list: number[]) => (list.length === 0 ? null : sum(list) / list.length)
  const avgGain = avg(gains)
  const avgLoss = avg(losses)
  const rr = avgGain !== null && avgLoss ? avgGain / avgLoss : null
  const pf = gains.length && sum(losses) ? sum(gains) / sum(losses) : null

  /* 시각 순으로 세는 값이라 목록 순서를 믿지 않고 다시 세웁니다. */
  let run = 0
  let worst = 0
  for (const trade of [...trades].sort((a, b) => (a.at ?? '').localeCompare(b.at ?? ''))) {
    run = trade.net < 0 ? run + 1 : 0
    if (run > worst) worst = run
  }

  const one = (value: number | null) => (value === null ? '—' : value.toFixed(2))

  return (
    <dl className="ana-sheet">
      <div className="ana-sheet-row">
        <dt>손익비</dt>
        <dd>{one(rr)}</dd>
      </div>
      <div className="ana-sheet-row">
        <dt>Profit Factor</dt>
        <dd>{one(pf)}</dd>
      </div>
      <div className="ana-sheet-row">
        <dt>최대 연속 손실</dt>
        <dd>{trades.length === 0 ? '—' : `${worst}건`}</dd>
      </div>
    </dl>
  )
}

/* 기간·방향 — 거래일별 손익과 매수·매도 갈라 보기. */
export function PeriodSide({
  data,
  total,
  empty,
}: {
  data: Dataset
  total: number[]
  empty: boolean
}) {
  if (empty) {
    return (
      <div className="card ana-pane">
        <EmptyRange />
      </div>
    )
  }
  const rows = segments(data.dates, total)
  const widest = Math.max(...rows.map((row) => Math.abs(row.delta)), 1)

  return (
    /* 이 탭은 두 칸이 같은 무게입니다 — 성과 요약처럼 한쪽이 곡선이 아니라,
       왼쪽 막대와 오른쪽 표가 둘 다 값을 세로로 쌓습니다. */
    <div className="ana-body ana-body-even">
      <div className="card ana-pane">
        <h3 className="ana-card-title">구간별 손익</h3>
        {/* 누적 곡선의 차이라 곡선과 같은 기준(답의 `curveBasis`)입니다. */}
        <ul className="ana-bars">
          {rows.map((row) => (
            <li key={row.label}>
              <span className="ana-bar-label">{row.label}</span>
              <span className="ana-bar-track">
                <span
                  className={`ana-bar ${row.delta >= 0 ? 'up' : 'down'}`}
                  style={{ width: `${(Math.abs(row.delta) / widest) * 100}%` }}
                />
              </span>
              <span className="ana-bar-value">
                <Amount value={row.delta} currency={data.currency} signed toned />
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="card ana-pane">
        <h3 className="ana-card-title">방향</h3>
        <table className="data-table rows-base ana-side-table">
          <thead>
            <tr>
              <th className="col-text" scope="col">방향</th>
              <th scope="col">거래 수</th>
              <th scope="col">승률</th>
              <th scope="col">순손익</th>
            </tr>
          </thead>
          <tbody>
            {(['buy', 'sell'] as const).map((side) => {
              const cut = bySide(data.trades, side)
              const pct = cut.closed === 0 ? null : Math.round((cut.wins / cut.closed) * 1000) / 10
              return (
                <tr key={side}>
                  {/* 방향은 값이라 색이 붙습니다. 색만으로 말하지 않도록
                      낱말을 함께 적습니다. */}
                  <td className={`col-text ${side === 'buy' ? 'up' : 'down'}`}>
                    {side === 'buy' ? '매수' : '매도'}
                  </td>
                  <td>{countText(cut.closed)}</td>
                  <td>{pct === null ? '—' : `${pct}%`}</td>
                  <td>
                    <Amount value={cut.net} currency={data.currency} signed toned />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* 비용·체결 품질 — 기준을 값과 함께 적습니다.
 *
 * **거래가 있으면 늘 표를 세웁니다.** 체결률·거절률·증거금 사용률은 서버가
 * 적은 글자를 그대로 씁니다(`QualityReply`). 빈 값은 세 갈래로 가릅니다:
 * - 이 기간 기록에 주문 결과가 하나도 없음(`quality` 가 `null`) → 「기록에 없음」
 * - 기록은 있는데 셀 것이 없음(분모 0 — 서버 글자가 「—」) → 「—」
 * - 잔고 기록이 생기기 전 기간(`counts.marginPeak` 가 `null`) → 그 줄만 「기록에 없음」
 * 「기록에 없음」은 「—」(값이 없음)와 다른 말입니다 — 기록이 쌓이면 설 값입니다. */
export function CostQuality({ data, fee, empty }: { data: Dataset; fee: number; empty: boolean }) {
  const quality = data.quality
  /* 평균 보유시간은 서버 값이 있으면 그것만, 없으면 거래 줄에서 셉니다 — 둘을
     함께 세우면 같은 값의 출처가 둘이 됩니다. */
  const served = quality && quality.holding !== '—' ? quality.holding : null
  const counted = served === null ? averageHolding(data.trades) : null
  const holding = served ?? (counted === null ? '—' : holdingText(counted))
  const marginKept = quality !== null && quality.counts.marginPeak !== null
  const unkept = <dd className="ana-unkept">기록에 없음</dd>
  const said = (text: string) => <dd className="ana-served">{text}</dd>
  return (
    <div className="card ana-pane">
      <h3 className="ana-card-title">비용 · 체결 품질</h3>
      {empty ? (
        <EmptyRange />
      ) : (
        <>
          <dl className="ana-sheet ana-sheet-wide">
            <div className="ana-sheet-row">
              <dt title={FEE_ASSUMED}>
                수수료<span className="fee-assumed"> (가정)</span>
              </dt>
              <dd>{amountText(fee, data.currency)}</dd>
            </div>
            <div className="ana-sheet-row">
              <dt>슬리피지</dt>
              <dd>체결가에 이미 반영 — 따로 빼지 않습니다</dd>
            </div>
            <div className="ana-sheet-row">
              <dt>평균 보유시간</dt>
              {/* 진입에서 종료까지를 거래마다 재어 평균합니다. 잘린 답이면 남은
                  거래의 평균입니다. */}
              {said(holding)}
            </div>
            <div className="ana-sheet-row">
              <dt>체결률</dt>
              {quality ? said(quality.fillRate) : unkept}
            </div>
            <div className="ana-sheet-row">
              <dt>거절률</dt>
              {quality ? said(quality.rejectRate) : unkept}
            </div>
            <div className="ana-sheet-row">
              <dt>최대 증거금 사용률</dt>
              {quality && marginKept ? said(quality.marginPeak) : unkept}
            </div>
          </dl>
          <p className="ana-unkept-note">
            {quality
              ? `체결률 = 체결 ÷ 접수되어 끝난 주문 · 거절률 = 거절·막힘 ÷ 낸 시도${
                  marginKept ? '' : ' · 증거금 사용률은 이 기간 잔고 기록에 없습니다'
                }`
              : '이 기간 기록에는 주문 결과가 남아 있지 않습니다'}
          </p>
        </>
      )}
    </div>
  )
}

/* 거래 내역 — 한 건이 「포지션 0 → 진입 → 다시 0」입니다. 최근 것이 위입니다. */
export function TradeList({ data, codeFilter }: { data: Dataset; codeFilter: string }) {
  const [limit, setLimit] = useState(TRADE_PAGE)
  /* 조건이 바뀌어 새 답이 오면 다시 처음 쪽부터입니다. */
  useEffect(() => setLimit(TRADE_PAGE), [data])

  /* 표는 **받은 거래 전부**를 세웁니다 — 순손익이나 수량을 모르는 거래도 한 줄이고, 그 칸만
     「—」입니다. 셈(합계·승률…)은 `data.trades` 가 따로 합니다. */
  const newest = useMemo(() => [...data.listed].reverse(), [data.listed])
  const visible = newest.slice(0, limit)
  const names = useMemo(() => new Map(data.strategies.map((perf) => [perf.id, perfName(perf)])), [data.strategies])
  const name = (id: string) => names.get(id) ?? id

  /* 종목 열은 종목을 거르지 않았고 답에 종목이 둘 이상일 때만 섭니다 — 한
     종목뿐이면 모든 줄에 같은 글자가 섭니다. */
  const manyCodes = useMemo(() => new Set(data.listed.map((trade) => trade.code)).size > 1, [data.listed])
  const boxRef = useRef<HTMLDivElement>(null)
  const [narrow, setNarrow] = useState(false)
  useLayoutEffect(() => {
    const box = boxRef.current
    if (!box) return
    const measure = () => {
      const style = getComputedStyle(box)
      const inner = box.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
      setNarrow(inner > 0 && inner < CODE_FITS)
    }
    measure()
    const watcher = new ResizeObserver(measure)
    watcher.observe(box)
    return () => watcher.disconnect()
  }, [])
  const codeColumn = codeFilter === '' && manyCodes && !narrow
  const codeInTitle = codeFilter === '' && manyCodes && narrow
  const columns = codeColumn ? 6 : 5

  const count = data.listed.length
  return (
    <div className="card ana-pane">
      {/* 표 위 머리 줄 — 왼쪽은 무엇의 값인지, 오른쪽은 몇 건을 세웠고 더 있는지.
          계좌 목록과 같은 자리·같은 모양입니다. */}
      <div className="list-head">
        <h3 className="ana-card-title">거래 내역</h3>
        <span className="list-head-state">
          {visible.length < count ? (
            <>
              최근 {visible.length.toLocaleString('ko-KR')}건 · 전체 {count.toLocaleString('ko-KR')}건
              <button type="button" className="btn btn-quiet" onClick={() => setLimit(limit + TRADE_PAGE)}>
                더 보기
              </button>
            </>
          ) : (
            `${count.toLocaleString('ko-KR')}건`
          )}
          {/* 셈에서 뺀 거래가 있으면 그렇다고 적습니다 — 표의 줄 수와 위 카드의
              건수가 다른 까닭입니다. */}
          {data.uncounted > 0 && (
            <span className="ana-uncounted">
              순손익이나 수량을 모르는 거래 {data.uncounted.toLocaleString('ko-KR')}건은 합계에서 뺐습니다
            </span>
          )}
        </span>
      </div>
      <div className="table-scroll" ref={boxRef}>
        <table className="data-table rows-base ana-trade-table">
          <colgroup>
            <col className="ana-col-at" />
            <col />
            {codeColumn && <col className="ana-col-code" />}
            <col className="ana-col-side" />
            <col className="ana-col-qty" />
            <col className="ana-col-net" />
          </colgroup>
          <thead>
            <tr>
              <th className="col-text" scope="col">종료 시각</th>
              <th className="col-text" scope="col">전략</th>
              {codeColumn && (
                <th className="col-text" scope="col">종목</th>
              )}
              <th className="col-text" scope="col">방향</th>
              <th scope="col">수량</th>
              <th scope="col">순손익</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((trade) => (
              <tr key={trade.id}>
                <td className="col-text num">{minuteText(trade.at)}</td>
                <td
                  className="col-text"
                  title={codeInTitle ? `${name(trade.strategyId)} · ${codeName(trade.code)}` : name(trade.strategyId)}
                >
                  {name(trade.strategyId)}
                </td>
                {codeColumn && (
                  <td className="col-text" title={codeName(trade.code)}>
                    {codeName(trade.code)}
                  </td>
                )}
                <td className={`col-text ${trade.side === 'buy' ? 'up' : 'down'}`}>
                  {trade.side === 'buy' ? '매수' : '매도'}
                </td>
                <td>{trade.qty === null ? <span className="dead">—</span> : trade.qty}</td>
                <td>
                  {trade.net === null ? (
                    <span className="dead">—</span>
                  ) : (
                    <Amount value={trade.net} currency={data.currency} signed toned />
                  )}
                </td>
              </tr>
            ))}
            {count === 0 && (
              <tr>
                <td className="ana-empty-row" colSpan={columns}>
                  이 기간에 종료된 거래가 없습니다
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
