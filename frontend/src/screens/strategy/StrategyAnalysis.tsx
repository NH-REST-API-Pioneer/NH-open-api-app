import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from 'react'
import {
  openRecords,
  netOf,
  setRecordFilters,
  totalCurve,
  useRecordsState,
  winRate,
  type Span,
} from '../../data/strategyRecords'
import { loadRuns, strategyState, useStrategyState } from '../../data/strategyStore'
import { PnlCurve } from './PnlCurve'
import { FEE_ASSUMED } from '../../data/strategyRuns'
import { useResizableWidth } from '../../lib/useResizableWidth'
import {
  INNER,
  Amount,
  Dash,
  codeName,
  CURVE_MIN,
  CURVE_MAX,
  drawdownTitle,
  perfName,
  Waiting,
  EmptyRange,
  type InnerTab,
} from './StrategyAnalysisParts'
import { CurveHelp } from './AnalysisPickers'
import { Compare } from './AnalysisCompare'
import { Detail, PeriodSide, CostQuality, TradeList } from './AnalysisDetail'
import { renderAnalysisHead, renderAnalysisCards } from './AnalysisHead'

/* 전략 분석 — 여러 전략을 견주고 비용을 갈라 보는 화면.
 *
 * **보는 화면입니다.** 여기서 나가는 주문이 없으므로 채운 단추를 두지
 * 않습니다 — 이 앱에서 채운 초록은 「눌러도 되는 주요 작업」의 자리입니다.
 *
 * 값은 전략 기록 파일에서 서버가 모은 것입니다(`data/strategyRecords.ts`).
 * 한 번에 한 기록 유형·한 시장을 봅니다.
 */

export function StrategyAnalysis() {
  const records = useRecordsState()
  const { filters, data, status } = records
  const { rows } = useStrategyState()
  const [tab, setTab] = useState<InnerTab>('성과 요약')
  const spanId = useId()
  /* 비교표에서 곡선에 올린 전략 하나. 비어 있으면 합계만 그립니다. 한 번에
     하나만 고릅니다 — 선을 여럿 겹치면 색으로 갈라야 하는데 이 앱에는 그럴
     색이 없고, 견주는 일은 표가 합니다. */
  const [pickedId, setPickedId] = useState<string | null>(null)
  /* 곡선 높이. 끌어 둔 적이 없으면 곡선 줄이 남는 세로를 채웁니다. 끌어 두면 그
     높이로 서고, 옆 비용 칸은 줄 높이 안에서 구릅니다. */
  const bodyRef = useRef<HTMLDivElement>(null)
  const curve = useResizableWidth({
    key: 'nh.anaCurveHeight',
    initial: null,
    min: CURVE_MIN,
    max: CURVE_MAX,
    axis: 'y',
    measure: () => bodyRef.current?.querySelector<HTMLElement>('.ana-curve') ?? null,
  })

  /* 탭을 열 때마다 다시 받습니다 — 다른 탭에서 도는 실행이 그 사이 거래를
     닫았을 수 있습니다. 받는 동안 앞 답은 그대로 섭니다. */
  useEffect(() => {
    /* 기본 시장은 **끝나지 않은 실행이 도는 시장**입니다(`openRecords`). 실행 목록을
       아직 안 받았으면 먼저 받습니다. */
    const open = () =>
      openRecords(strategyState().verify.runs.filter((run) => run.state !== 'ended').map((run) => run.market))
    if (strategyState().verify.status === 'ready') open()
    else void loadRuns().then(open)
  }, [])

  /* 고른 전략이 새 답에 없으면 합계로 돌아갑니다. 처음 여는 화면도 합계입니다 —
     전략 하나를 미리 골라 두면 그 전략이 계좌 전체인 것처럼 읽힙니다. */
  useEffect(() => {
    if (!data) return
    setPickedId((now) => (now !== null && data.strategies.some((perf) => perf.id === now) ? now : null))
  }, [data])

  /* 전략 고르개의 묶음들. 지금 보는 시장의 전략만이고, 이름은 그 묶음의 첫
     버전 것입니다. */
  const groups = useMemo(() => {
    const found = new Map<string, { name: string; versions: string[] }>()
    for (const row of rows) {
      if (row.market !== filters.market) continue
      const held = found.get(row.groupId)
      if (held) held.versions.push(row.id)
      else found.set(row.groupId, { name: row.name, versions: [row.id] })
    }
    return [...found.entries()]
  }, [rows, filters.market])

  const total = useMemo(
    () => (data ? totalCurve(data.strategies, data.dates.length) : []),
    [data],
  )

  const currency = data?.currency ?? ''
  const empty = data !== null && data.strategies.length === 0
  const net = data ? data.strategies.reduce((sum, perf) => sum + netOf(perf), 0) : 0
  const gross = data ? data.strategies.reduce((sum, perf) => sum + perf.gross, 0) : 0
  const fee = data ? data.strategies.reduce((sum, perf) => sum + perf.fee, 0) : 0
  const trades = data?.trades ?? []
  /* 해외 「전체」에서 통화가 여럿이면 통화마다 받은 답들입니다. 금액은 통화별 줄로
     세우고(더하지 않습니다), 승률만 거래 수로 하나를 셉니다. */
  const multi = records.perCurrency
  const allTrades = multi ? multi.flatMap((one) => one.trades) : trades
  const rate = winRate(allTrades)
  /* 최대 낙폭은 서버 값입니다 — 화면이 곡선에서 다시 세지 않습니다. 서버가 싣지
     않으면 「—」입니다. */
  const mdd = data && !empty ? data.maxDrawdown : null
  const ddTitle = drawdownTitle(data?.drawdownBasis)
  /* 통화마다의 금액 줄 — 「+12.50 USD」 다음 줄 「−30.00 HKD」. */
  const perLines = (pick: (one: NonNullable<typeof data>) => React.ReactNode) =>
    multi ? (
      <span className="ana-lines">
        {multi.map((one) => (
          <span className="ana-line" key={one.currency}>
            {pick(one)}
          </span>
        ))}
      </span>
    ) : null

  /* 곡선에 얹는 전략 하나. 전략이 하나뿐인 자료에서는 합계와 같은 선이라
     따로 그리지 않습니다 — 같은 자리에 이름표만 둘이 겹칩니다. */
  const strategies = data?.strategies ?? []
  const picked = strategies.find((perf) => perf.id === pickedId) ?? null
  const shown = strategies.length > 1 ? picked : null

  function pickSpan(span: Span) {
    /* 「직접」은 지금 보는 기간에서 출발합니다 — 빈 칸에서 시작하면 고르는
       순간 기간이 서버 기본으로 돌아가 보던 값이 바뀝니다. */
    if (span === '직접') setRecordFilters({ span, from: data?.from ?? '', to: data?.to ?? '' })
    else setRecordFilters({ span })
  }

  function pickGroup(group: string) {
    const found = groups.find(([id]) => id === group)
    setRecordFilters({ group, versions: found ? found[1].versions : [] })
  }

  /* 보고 있는 묶음이 목록에서 사라졌으면(지웠거나 다른 시장) 「전체」에서도
     고른 이름이 안 서므로 셀렉트에 그 값을 잠긴 선택지로 둡니다. */
  const groupGone = filters.group !== '' && !groups.some(([id]) => id === filters.group)
  const codeChoices = filters.code && !records.codes.includes(filters.code)
    ? [...records.codes, filters.code]
    : records.codes
  /* 고른 통화가 이번 답의 통화에 없어도(기간을 바꿔 그 통화 거래가 빠짐) 고른
     값은 그대로 섭니다 — 셀렉트가 엉뚱한 첫 선택지를 고른 것처럼 보이지 않게. */
  const currencyChoices = data
    ? filters.currency && !data.currencies.includes(filters.currency)
      ? [...data.currencies, filters.currency]
      : data.currencies
    : []
  /* 칩 안의 셀렉트는 폭을 묶어 두어 글자가 잘릴 수 있으므로, 고른 이름 전체를
     올렸을 때 보이게 합니다. */
  const groupTitle = filters.group === ''
    ? '전체 전략'
    : (groups.find(([id]) => id === filters.group)?.[1].name ?? '지금 목록에 없는 전략')
  const codeTitle = filters.code === '' ? '전체 종목' : codeName(filters.code)

  return (
    <div className="ana">
      {/* 필터 줄. 칸마다 이름을 칸 안 앞머리에 두고 고른 값을 굵게 적습니다 — 이름을
          칸 위나 옆에 따로 세우면 한 줄에 다 들어가지 않습니다. 무엇을 보는지(기록·
          시장·통화·기간)는 왼쪽에, 어디까지 좁히는지(전략·종목)는 오른쪽 끝에 섭니다. */}
      {renderAnalysisHead({
        filters,
        data,
        currencyChoices,
        spanId,
        pickSpan,
        records,
        groupTitle,
        pickGroup,
        groups,
        groupGone,
        codeTitle,
        codeChoices,
      })}

      {/* 지표 넷. 아이콘을 붙이지 않습니다 — 아이콘은 값을 말하지 못하는데
          색까지 지니면, 뜻을 가진 색(빨강 매수·파랑 매도·초록 주요 작업)이
          뜻 없는 색 넷에 묻힙니다. 넷을 가르는 것은 제목입니다. */}
      {renderAnalysisCards({
        perLines,
        data,
        net,
        currency,
        multi,
        empty,
        gross,
        fee,
        rate,
        allTrades,
        mdd,
        ddTitle,
      })}

      {/* 통화가 여럿인 「전체」는 카드만 섭니다 — 곡선·비교표·거래 내역은 한 통화의 것이라
          통화를 고르면 그 통화로 섭니다. */}
      {multi ? (
        <div className="card ana-pick-note">
          <p className="ana-foot">통화를 고르면 곡선·비교표·거래 내역이 그 통화로 섭니다</p>
        </div>
      ) : (
      <>
      <div className="tabs tabs-inline ana-tabs">
        {INNER.map((item) => (
          <button
            key={item}
            type="button"
            className="tab"
            aria-current={item === tab}
            onClick={() => setTab(item)}
          >
            {item}
          </button>
        ))}
      </div>

      {tab === '성과 요약' && (
        <>
          <div
            className={curve.size === null ? 'ana-body' : 'ana-body ana-body-sized'}
            ref={bodyRef}
            style={
              curve.size === null
                ? undefined
                : ({ '--ana-curve-h': `${curve.size}px` } as React.CSSProperties)
            }
          >
            <div className="card ana-chart">
              {!data ? (
                <Waiting status={status} />
              ) : empty ? (
                <EmptyRange />
              ) : (
                <>
                  <PnlCurve
                    dates={data.dates}
                    total={total}
                    totalLabel={data.totalLabel}
                    pick={shown ? shown.curve : null}
                    pickLabel={shown ? perfName(shown) : ''}
                    currency={currency}
                  />
                  <CurveHelp totalLabel={data.totalLabel} basis={data.curveBasis} drawdown={Boolean(ddTitle)} />
                </>
              )}
            </div>

            {/* 비용과 성과 상세는 **카드 한 장**입니다. 둘로 나누면 제목·여백이
                한 벌 더 들어가 세로에서 50 을 더 먹는데, 이 화면의 세로는
                곡선이 쓰는 자리입니다. */}
            <div className="ana-side">
              <div className="card ana-cost">
                <h3 className="ana-card-title">비용 요약</h3>
                <dl className="ana-sheet">
                  <div className="ana-sheet-row">
                    <dt>총실현손익</dt>
                    <dd>{data ? <Amount value={gross} currency={currency} signed toned /> : <Dash />}</dd>
                  </div>
                  <div className="ana-sheet-row">
                    <dt title={FEE_ASSUMED}>
                      수수료<span className="fee-assumed"> (가정)</span>
                    </dt>
                    <dd>{data ? <Amount value={-fee} currency={currency} signed toned /> : <Dash />}</dd>
                  </div>
                  <div className="ana-sheet-row ana-sheet-sum">
                    <dt title={FEE_ASSUMED}>순실현손익</dt>
                    <dd>{data ? <Amount value={net} currency={currency} signed toned /> : <Dash />}</dd>
                  </div>
                </dl>
                <p className="ana-foot">체결가에 반영된 비용을 다시 빼지 않습니다</p>
                <p className="ana-foot">슬리피지는 체결 품질에서 확인</p>

                <h3 className="ana-card-title ana-sub-title">성과 상세</h3>
                <Detail trades={trades} />
              </div>
            </div>
          </div>

          {/* 끌거나 화살표 키로 곡선 높이를 바꿉니다. 더블클릭·Enter 는 원래대로. */}
          <div
            className="split-handle split-handle-y"
            aria-label="곡선 높이"
            title="끌어서 곡선 높이 조절 · 더블클릭하면 원래대로"
            {...curve.handleProps}
          />

          {data && (
            <Compare
              data={data}
              pickedId={picked?.id ?? null}
              shownId={shown?.id ?? null}
              onPick={setPickedId}
              net={net}
              rate={rate}
              mdd={mdd}
            />
          )}
        </>
      )}

      {tab !== '성과 요약' && !data && (
        <div className="card ana-pane">
          <Waiting status={status} />
        </div>
      )}
      {tab === '기간·방향' && data && <PeriodSide data={data} total={total} empty={empty} />}
      {tab === '비용·체결 품질' && data && <CostQuality data={data} fee={fee} empty={empty} />}
      {tab === '거래 내역' && data && <TradeList data={data} codeFilter={filters.code} />}
      </>
      )}
    </div>
  )
}
