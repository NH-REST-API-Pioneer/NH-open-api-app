import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'

import {
  ANALYSIS_KINDS,
  RECORD_PARAM,
  SPANS,
  amountText,
  averageHolding,
  bySide,
  holdingText,
  loadRecords,
  openRecords,
  pickRecordMarket,
  minuteText,
  netOf,
  segments,
  setRecordFilters,
  totalCurve,
  tradesOf,
  useRecordsState,
  winRate,
  wins,
  type AnalysisKind,
  type Dataset,
  type RecordsState,
  type Span,
  type StrategyPerf,
  type Trade,
} from '../../data/strategyRecords'
import { resolve } from '../../data/instruments'
import { loadRuns, strategyState, useStrategyState } from '../../data/strategyStore'
import { MINUS, Num, currencyCode, toneOf } from '../../lib/number'
import { PnlCurve } from './PnlCurve'
import { DELETED } from './runStats'
import { RunKindBadge } from './runKind'
import { FEE_ASSUMED } from '../../data/strategyRuns'
import { useResizableWidth } from '../../lib/useResizableWidth'

/* 전략 분석 — 여러 전략을 견주고 비용을 갈라 보는 화면.
 *
 * **보는 화면입니다.** 여기서 나가는 주문이 없으므로 채운 단추를 두지
 * 않습니다 — 이 앱에서 채운 초록은 「눌러도 되는 주요 작업」의 자리입니다.
 *
 * 값은 전략 기록 파일에서 서버가 모은 것입니다(`data/strategyRecords.ts`).
 * 한 번에 한 기록 유형·한 시장을 봅니다.
 */

const INNER = ['성과 요약', '기간·방향', '비용·체결 품질', '거래 내역'] as const
type InnerTab = (typeof INNER)[number]

/** 거래 내역 표가 한 번에 더 세우는 줄 수. 5,000건을 한 번에 그리면 탭을 여는
 *  순간이 멈칫합니다. */
const TRADE_PAGE = 200

/** 거래 내역 표에 종목 열까지 설 수 있는 안쪽 폭. 이보다 좁으면 종목 열을
 *  접고 종목은 전략 칸에 올렸을 때 보입니다. 값 열 넷(종료 시각 140·방향 80·
 *  수량 80·순손익 150)과 종목 열(224)의 폭에, 전략 이름이 말줄임 없이 설
 *  최소 폭(160)을 더한 값입니다. 열 폭은 `strategy.css` 의 `.ana-col-*` 와
 *  같이 고칩니다. */
const CODE_FITS = 834

const isKrw = (currency: string) => currencyCode(currency) === 'KRW'

/** 만 단위로 줄인 금액. 좁은 카드의 보조줄에서만 쓰고, **원에만** 씁니다. */
const man = (value: number) => {
  const unit = Math.abs(value) / 10_000
  const text = unit.toLocaleString('ko-KR', { maximumFractionDigits: 1 })
  return `${value < 0 ? MINUS : ''}${text}만`
}

/** 표와 카드의 금액. 자릿수를 세로로 맞추는 자리에 씁니다. 원은 정수, 그 밖의
 *  통화는 소수 둘째 자리까지입니다. */
function Amount({
  value,
  currency,
  signed,
  toned,
}: {
  value: number
  currency: string
  signed?: boolean
  toned?: boolean
}) {
  if (isKrw(currency)) return <Num value={value} decimals={0} signed={signed} toned={toned} suffix="원" />
  /* 원이 아닌 통화는 글자로 적습니다. 자릿수 맞춤 부품은 소수부 뒤 칸을 좁게
     잡아 두어, 「 USD」처럼 긴 단위가 붙으면 칸을 넘어 잘리거나 줄이 갈립니다. */
  const tone = toned ? toneOf(value) : ''
  return (
    <span className={`num${tone ? ` ${tone}` : ''}`}>
      {signed && value > 0 ? '+' : ''}
      {amountText(value, currency)}
    </span>
  )
}

/** 건수. 천 단위를 끊습니다. */
const countText = (value: number) => value.toLocaleString('ko-KR')

const Dash = () => <span className="ana-none">—</span>

/** 종목 이름. 마스터에 없으면(만기가 지난 월물 등) 코드를 그대로 적습니다. */
const codeName = (code: string) => resolve(code)?.name ?? code

/** 곡선을 끌어 줄일 수 있는 바닥. `.ana-curve` 의 min-height 와 같습니다 */
const CURVE_MIN = 150
/** 곡선을 끌어 늘릴 수 있는 끝 */
const CURVE_MAX = 600

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
      <div className="card ana-head">
        <label className="ana-chip">
          <span className="control-label">기록</span>
          <select
            className="control"
            value={filters.kind}
            onChange={(event) => setRecordFilters({ kind: event.target.value as AnalysisKind })}
          >
            {ANALYSIS_KINDS.map((one) => (
              <option key={one} value={one}>
                {one}
              </option>
            ))}
          </select>
          {/* 고른 기록 유형의 갈래 배지. 선택지는 낱말만이고, 고른 뒤에 어느
              장부의 수인지 배지로 남깁니다 — 진행·검증 화면과 같은 얼굴입니다. */}
          <RunKindBadge kind={RECORD_PARAM[filters.kind]} />
        </label>

        {/* 계좌 화면과 같은 낱말·같은 모양입니다. */}
        <div className="ana-chip ana-chip-seg">
          <span className="control-label">시장</span>
          <div className="seg seg-even">
            {(['domestic', 'overseas'] as const).map((market) => (
              <button
                key={market}
                type="button"
                className="seg-item"
                aria-pressed={filters.market === market}
                onClick={() => pickRecordMarket(market)}
              >
                {market === 'domestic' ? '국내' : '해외'}
              </button>
            ))}
          </div>
        </div>

        {/* 해외 기록의 통화 — 그 기간 기록에 있는 통화만 섭니다. 「전체」는 통화마다 따로
            세웁니다(더하지 않습니다). 국내는 원 하나라 고르개가 없습니다. */}
        {filters.market === 'overseas' && data && data.currencies.length > 0 && (
          <label className="ana-chip">
            <span className="control-label">통화</span>
            <select
              className="control"
              value={filters.currency}
              onChange={(event) => setRecordFilters({ currency: event.target.value })}
            >
              <option value="">전체</option>
              {currencyChoices.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </select>
          </label>
        )}

        <div className="ana-period">
          {/* 범위 단추까지 한 label 에 넣으면 단추를 눌러도 셀렉트가 열리므로 칩은
              div 이고, 이름만 셀렉트를 가리키는 label 입니다. */}
          <div className="ana-chip">
            <label className="control-label" htmlFor={spanId}>
              기간
            </label>
            <select
              id={spanId}
              className="control"
              value={filters.span}
              onChange={(event) => pickSpan(event.target.value as Span)}
            >
              {SPANS.map((span) => (
                <option key={span} value={span}>
                  {span}
                </option>
              ))}
            </select>
            {filters.span === '직접' ? (
              <RangePicker
                from={filters.from || (data?.from ?? '')}
                to={filters.to || (data?.to ?? '')}
                fromValue={filters.from}
                toValue={filters.to}
              />
            ) : (
              <b className="ana-value" title={data?.period}>
                {data ? shortRange(data.from, data.to) : ''}
              </b>
            )}
          </div>
          {/* 서버가 조건을 물린 까닭. 앞 답은 그대로 두고 그 까닭만 기간 아래에
              적습니다 — 물린 것은 기간 칸이 대부분이라 고칠 자리 곁에 섭니다. */}
          {records.refused && <p className="ana-refused">{records.refused}</p>}
        </div>

        <Busy records={records} />

        <div className="ana-scope">
          <label className="ana-chip" title={groupTitle}>
            <span className="control-label">전략</span>
            <select
              className="control ana-select"
              value={filters.group}
              onChange={(event) => pickGroup(event.target.value)}
            >
              <option value="">전체 전략</option>
              {groups.map(([id, group]) => (
                <option key={id} value={id}>
                  {group.name}
                </option>
              ))}
              {groupGone && (
                <option value={filters.group} disabled>
                  지금 목록에 없는 전략
                </option>
              )}
            </select>
          </label>

          <label className="ana-chip" title={codeTitle}>
            <span className="control-label">종목</span>
            <select
              className="control ana-select"
              value={filters.code}
              onChange={(event) => setRecordFilters({ code: event.target.value })}
            >
              <option value="">전체 종목</option>
              {codeChoices.map((code) => (
                <option key={code} value={code}>
                  {codeName(code)}
                </option>
              ))}
            </select>
          </label>
        </div>

        <Notes records={records} />
      </div>

      {/* 지표 넷. 아이콘을 붙이지 않습니다 — 아이콘은 값을 말하지 못하는데
          색까지 지니면, 뜻을 가진 색(빨강 매수·파랑 매도·초록 주요 작업)이
          뜻 없는 색 넷에 묻힙니다. 넷을 가르는 것은 제목입니다. */}
      <div className="ana-cards">
        <Metric
          title="순실현손익"
          hint={FEE_ASSUMED}
          value={
            perLines((one) => (
              <Amount
                value={one.strategies.reduce((sum, perf) => sum + netOf(perf), 0)}
                currency={one.currency}
                signed
                toned
              />
            )) ?? (data ? <Amount value={net} currency={currency} signed toned /> : <Dash />)
          }
          /* 카드 넷이 한 줄을 나눠 쓰는 자리라 원은 만 단위로 줄입니다. 원 단위
             전액과 뺄셈은 바로 아래 비용 요약이 그대로 보여 줍니다.
             여기서 빼기 기호를 쓰지 않는 것은, 총실현이 음수인 자료에서
             「−29.6만 − 2.4만」처럼 부호와 연산이 같은 모양이 되기 때문입니다. */
          note={
            !data
              ? ''
              : multi
                ? '통화마다 따로 셉니다'
                : empty
                ? '종료된 거래가 없습니다'
                : (
                    <>
                      총실현 {isKrw(currency) ? man(gross) : amountText(gross, currency)} ·{' '}
                      <span title={FEE_ASSUMED}>
                        수수료<span className="fee-assumed"> (가정)</span>{' '}
                        {isKrw(currency) ? man(fee) : amountText(fee, currency)}
                      </span>
                    </>
                  )
          }
        />
        <Metric
          title="평가손익"
          /* 기간 말의 평가손익은 기간이 오늘에 닿을 때만 지금 도는 실행의
             값으로 압니다. 모르는 값을 0 으로 적으면 「보유 없음」으로 읽힙니다.
             아는 0 은 0 입니다. */
          value={
            perLines((one) =>
              one.openPlKnown ? <Amount value={one.openPl} currency={one.currency} signed toned /> : <Dash />,
            ) ?? (data?.openPlKnown ? <Amount value={data.openPl} currency={currency} signed toned /> : <Dash />)
          }
          note={!data ? '' : data.openPlKnown ? '지금 도는 실행' : '기간이 오늘까지가 아니라 알 수 없습니다'}
        />
        <Metric
          title="승률"
          value={rate === null ? <Dash /> : <span className="num">{rate}%</span>}
          note={
            !data
              ? ''
              : allTrades.length === 0
                ? '거래 없음'
                : `이익 ${countText(wins(allTrades))} / 종료 ${countText(allTrades.length)}건`
          }
        />
        <Metric
          title="최대 낙폭"
          /* 수준값이라 본문색이고 **빼기 부호도 없습니다**(규격 §9). 낙폭은
             크기이지 방향이 아니라, 부호를 붙이면 파랑·하락과 짝지어 읽힙니다.
             목록 상세의 낙폭과 같은 표기입니다. */
          value={
            perLines((one) => {
              const low = one.strategies.length > 0 ? one.maxDrawdown : null
              return low === null ? (
                <Dash />
              ) : (
                <span className="num" title={drawdownTitle(one.drawdownBasis)}>
                  {amountText(low, one.currency)}
                </span>
              )
            }) ??
            (mdd === null ? (
              <Dash />
            ) : (
              <span className="num" title={ddTitle}>
                {amountText(mdd, currency)}
              </span>
            ))
          }
          note="※ 전략별 값을 더하지 않습니다"
        />
      </div>

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

/** 기간 칩에 적는 짧은 날짜 범위(「09.13 – 10.12」). 두 끝의 해가 다르면 시작
 *  날짜에만 해 두 자리를 붙입니다(「25.10.13 – 10.12」) — 달·일만으로는 시작이
 *  어느 해인지 모르고, 끝까지 붙이면 필터 줄이 한 줄에 들지 않습니다. 전체 날짜는
 *  칩에 올리면 보입니다. 날짜를 모르면 빈 글자입니다. */
function shortRange(from: string, to: string): string {
  const parse = (date: string) => /^(\d{4})-(\d{2})-(\d{2})$/.exec(date)
  const start = parse(from)
  const end = parse(to)
  if (!start || !end) return ''
  const year = start[1] !== end[1] ? `${start[1].slice(2)}.` : ''
  return `${year}${start[2]}.${start[3]} – ${end[2]}.${end[3]}`
}

/** 「직접」 기간의 범위 단추. 날짜 칸 둘을 늘 세워 두면 필터 줄이 한 줄에 들지
 *  않으므로, 범위를 글자로 적은 단추 하나로 서고 누르면 날짜 칸 둘이 뜹니다.
 *
 *  - 단추를 누르면 열리고, 다시 누르기·Esc·바깥 클릭·초점이 둘 밖으로 나가면
 *    닫힙니다(곡선 읽는 법과 같은 규칙).
 *  - 날짜를 바꾸면 닫지 않고 바로 반영합니다 — 끝 날짜까지 이어서 고칠 수
 *    있습니다.
 *
 *  `from`·`to` 는 단추에 적을 범위(비었으면 서버가 정한 기간), `fromValue`·
 *  `toValue` 는 날짜 칸에 든 값입니다. */
function RangePicker({
  from,
  to,
  fromValue,
  toValue,
}: {
  from: string
  to: string
  fromValue: string
  toValue: string
}) {
  const popId = useId()
  const btnRef = useRef<HTMLButtonElement>(null)
  const boxRef = useRef<HTMLSpanElement>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const onDown = (event: PointerEvent) => {
      if (boxRef.current?.contains(event.target as Node)) return
      setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      /* 날짜 칸에서 닫으면 초점이 갈 곳을 잃으므로 단추로 돌려 둡니다. */
      if (boxRef.current?.contains(document.activeElement)) btnRef.current?.focus()
      setOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const range = shortRange(from, to)
  const full = from && to ? `${from} ~ ${to}` : ''
  return (
    <span
      ref={boxRef}
      className="ana-range-box"
      onBlur={(event) => {
        if (!boxRef.current?.contains(event.relatedTarget as Node | null)) setOpen(false)
      }}
    >
      <button
        ref={btnRef}
        type="button"
        className="ana-range"
        aria-expanded={open}
        aria-controls={popId}
        aria-label={full ? `기간 ${full}, 날짜 고치기` : '날짜 고르기'}
        title={full || undefined}
        onClick={() => setOpen((now) => !now)}
      >
        <i className="ana-cal" aria-hidden="true" />
        {range || '날짜 고르기'}
      </button>
      {/* 날짜 칸이 아닌 자리를 눌러도 초점이 빠지지 않게 합니다 — 빠지면 그 자리에서
          닫힙니다. */}
      <div
        className="ana-range-pop"
        id={popId}
        role="group"
        aria-label="직접 기간"
        hidden={!open}
        onMouseDown={(event) => {
          if (!(event.target instanceof HTMLInputElement)) event.preventDefault()
        }}
      >
        <input
          className="control ana-date"
          type="date"
          aria-label="시작 날짜"
          value={fromValue}
          onChange={(event) => setRecordFilters({ from: event.target.value })}
        />
        <span aria-hidden="true">~</span>
        <input
          className="control ana-date"
          type="date"
          aria-label="끝 날짜"
          value={toValue}
          onChange={(event) => setRecordFilters({ to: event.target.value })}
        />
      </div>
    </span>
  )
}

/** 포인터가 단추·글을 떠난 뒤 글을 닫기까지 기다리는 시간(ms). 둘 사이 틈을
 *  지나가는 동안 닫히지 않을 만큼입니다. */
const HELP_LEAVE_MS = 150

/** 곡선 읽는 법. 곡선 오른쪽 아래, 날짜 축 줄 높이의 빈 바닥에 단추 하나로 서고
 *  글은 단추를 가리키거나 초점을 주면 곡선 위에 뜹니다. 글을 카드 흐름에 두지
 *  않아 곡선이 그만큼 높게 섭니다.
 *
 *  - 무엇을 쌓았는지는 단추 앞 꼬리표로 늘 보입니다(「실현 기준」·「평가 포함」).
 *    모르는 기준이면 꼬리표도, 그 문장도 지어 말하지 않습니다.
 *  - 마우스로 연 글은 포인터가 단추나 글 위에 있는 동안 열려 있고, 둘 다 벗어나면
 *    닫힙니다.
 *  - 클릭하면 열린 채로 남고, 다시 클릭·Esc·바깥 클릭·초점 이탈로 닫힙니다. */
function CurveHelp({ totalLabel, basis, drawdown }: { totalLabel: string; basis: string; drawdown: boolean }) {
  const popId = useId()
  const btnRef = useRef<HTMLButtonElement>(null)
  const popRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [pinned, setPinned] = useState(false)
  /* 단추와 글 사이에는 틈이 있어, 단추를 떠나 글로 옮겨 가는 동안 바로 닫지 않고
     잠깐 기다립니다. 그 사이 단추나 글에 들어오면 닫기를 거둡니다. */
  const leaveTimer = useRef<number | undefined>(undefined)
  const stayOpen = () => {
    window.clearTimeout(leaveTimer.current)
    setOpen(true)
  }
  const leave = () => {
    if (pinned) return
    window.clearTimeout(leaveTimer.current)
    leaveTimer.current = window.setTimeout(() => setOpen(false), HELP_LEAVE_MS)
  }
  const close = () => {
    window.clearTimeout(leaveTimer.current)
    setPinned(false)
    setOpen(false)
  }

  useEffect(() => () => window.clearTimeout(leaveTimer.current), [])

  useEffect(() => {
    if (!open) return
    const onDown = (event: PointerEvent) => {
      const target = event.target as Node
      if (btnRef.current?.contains(target) || popRef.current?.contains(target)) return
      setPinned(false)
      setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setPinned(false)
      setOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const note = curveNote(basis)
  const tag = basis === 'realized' ? '실현 기준' : basis === 'equity' ? '평가 포함' : null
  return (
    <>
      <div className="ana-help">
        {tag && <span className="ana-help-tag">{tag}</span>}
        <button
          ref={btnRef}
          type="button"
          className="ana-help-btn"
          aria-expanded={open}
          aria-controls={popId}
          aria-describedby={open ? popId : undefined}
          onMouseEnter={stayOpen}
          onMouseLeave={leave}
          onFocus={stayOpen}
          onBlur={close}
          onClick={() => {
            window.clearTimeout(leaveTimer.current)
            const next = !pinned
            setPinned(next)
            setOpen(next)
          }}
        >
          <i className="ana-help-glyph" aria-hidden="true">
            i
          </i>
          곡선 읽는 법
        </button>
      </div>
      {/* 글 위를 눌러도 단추의 초점이 빠지지 않게 합니다 — 빠지면 그 자리에서 닫힙니다. */}
      <div
        ref={popRef}
        className="ana-help-pop"
        id={popId}
        role="tooltip"
        hidden={!open}
        onMouseEnter={stayOpen}
        onMouseLeave={leave}
        onMouseDown={(event) => event.preventDefault()}
      >
        <p className="ana-help-pop-title">곡선 읽는 법</p>
        <p className="ana-foot">곡선은 {totalLabel} 위에 고른 전략 하나만 올립니다</p>
        {note && <p className="ana-foot">{note}</p>}
        {drawdown && <p className="ana-foot">낙폭은 거래 차례로 셉니다</p>}
      </div>
    </>
  )
}

/** 곡선에 무엇을 쌓았는지 말하는 한 줄. 모르는 기준이면 `null` 이고, 지어
 *  말하지 않습니다. */
function curveNote(basis: string): string | null {
  if (basis === 'realized') {
    return '곡선은 거래일마다 그날까지 닫힌 거래의 순손익(실현 − 수수료) 누적입니다 — 평가손익은 들지 않습니다'
  }
  if (basis === 'equity') {
    return '곡선은 거래일마다 그날 끝의 실현 − 수수료 + 평가손익이고, 기간 앞 값에서 달라진 만큼입니다 — 기간 앞뒤에 보유가 있으면 카드·표의 순손익과 끝점이 다릅니다'
  }
  return null
}

/** 서버 낙폭 기준의 설명. 청산 거래 차례 기준일 때만 섭니다 — 다른 기준이면 그
 *  기준을 지어 말하지 않습니다. */
function drawdownTitle(basis: string | undefined): string | undefined {
  return basis === 'trades-realized'
    ? '실현 거래 차례 기준 — 청산 시각 차례의 누적 손익에서 고점 대비 최대 감소'
    : undefined
}

/** 전략 줄의 이름. 버전이 지워졌으면 서버가 이름 자리에 「알 수 없음」을 적고
 *  버전 글자를 비워 보냅니다. 그 줄은 전략 목록으로 가립니다 — 목록을 받았는데
 *  없으면 「지운 전략」, 아직 못 받았으면 「—」입니다(받기 전에 「지운」이라 하면
 *  목록이 늦게 온 것만으로 멀쩡한 전략이 지운 것으로 읽힙니다). */
function perfName(perf: StrategyPerf): string {
  if (perf.version) return `${perf.name} ${perf.version}`
  const { rows, status } = strategyState()
  if (rows.some((row) => row.id === perf.id)) return perf.name
  return status === 'ready' ? DELETED : '—'
}

/** 필터 줄 빈자리의 「받는 중」. 조건을 바꿀 때마다 잠깐 서는 글이라 남는 폭만
 *  씁니다 — 이 글 때문에 필터 줄이 감기면 그때마다 아래 화면이 들썩입니다.
 *  남는 폭이 글보다 좁으면 글 대신 점 하나가 서고, 올리면 「받는 중」이 보입니다. */
function Busy({ records }: { records: RecordsState }) {
  const { data, status } = records
  if (status !== 'loading' || data === null) return null
  return (
    <div className="ana-busy" role="status" aria-label="받는 중" title="받는 중">
      <span className="ana-busy-text" aria-hidden="true">
        받는 중
      </span>
      <span className="ana-busy-dot" aria-hidden="true" />
    </div>
  )
}

/** 필터 줄 아래의 안내. 잘린 답과 읽는 사이 바뀐 파일 — 이 둘만 섭니다. 잘린
 *  것이 먼저입니다: 화면의 모든 수가 그 범위의 값입니다. 드물게 서는 경고라
 *  줄여 적지 않고 제 줄에 온전히 세웁니다. */
function Notes({ records }: { records: RecordsState }) {
  const { data } = records
  if (!data?.truncated && !data?.incomplete) return null
  return (
    <div className="ana-notes">
      {data.truncated && (
        <p className="ana-note">
          최근 {data.listed.length.toLocaleString('ko-KR')}건만 셉니다 — {minuteText(data.earliestAt)} 이후
          거래입니다
        </p>
      )}
      {data.incomplete && (
        <p className="ana-note">
          기록을 읽는 사이 파일이 바뀌어 일부가 빠졌을 수 있습니다
          <button type="button" className="btn btn-quiet" onClick={() => void loadRecords()}>
            다시 받기
          </button>
        </p>
      )}
    </div>
  )
}

function Metric({
  title,
  value,
  note,
  hint,
}: {
  title: string
  value: React.ReactNode
  note: React.ReactNode
  /** 제목에 마우스를 올리면 뜨는 설명. 값이 어떻게 셈한 것인지 말할 때 씁니다. */
  hint?: string
}) {
  return (
    <div className="card ana-metric">
      <h3 className="ana-metric-title" title={hint}>
        {title}
      </h3>
      <p className="ana-metric-value">{value}</p>
      <p className="ana-metric-note">{note}</p>
    </div>
  )
}

/** 아직 답이 없는 자리. **「거래가 없다」와 가릅니다** — 받는 중이거나 못 받은
 *  것을 빈 기록으로 적으면 사용자는 거래가 없었다고 믿습니다. */
function Waiting({ status }: { status: RecordsState['status'] }) {
  if (status === 'loading') {
    return (
      <div className="notice">
        <p className="notice-title">기록을 받는 중입니다</p>
      </div>
    )
  }
  return (
    <div className="notice">
      <p className="notice-title">기록을 받지 못했습니다</p>
      {/* 조건을 물린 답(기간 아래에 까닭이 섬)은 다시 받아도 같아 단추를
          세우지 않습니다. */}
      {status === 'failed' && (
        <button type="button" className="btn btn-quiet notice-action" onClick={() => void loadRecords()}>
          다시 받기
        </button>
      )}
    </div>
  )
}

function EmptyRange() {
  return (
    <div className="notice">
      <p className="notice-title">이 기간에 종료된 거래가 없습니다</p>
      <p className="notice-reason">기록 유형이나 기간을 바꿔 보세요</p>
    </div>
  )
}

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

function Compare({
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

/* 손익비·Profit Factor·연속손실. 모두 거래 목록에서 냅니다(원본 §10). */
function Detail({ trades }: { trades: Trade[] }) {
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
function PeriodSide({
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

/* 비용·체결 품질 — 기준을 값과 함께 적습니다(원본 §10).
 *
 * **거래가 있으면 늘 표를 세웁니다.** 체결률·거절률·증거금 사용률은 서버가
 * 적은 글자를 그대로 씁니다(`QualityReply`). 빈 값은 세 갈래로 가릅니다:
 * - 이 기간 기록에 주문 결과가 하나도 없음(`quality` 가 `null`) → 「기록에 없음」
 * - 기록은 있는데 셀 것이 없음(분모 0 — 서버 글자가 「—」) → 「—」
 * - 잔고 기록이 생기기 전 기간(`counts.marginPeak` 가 `null`) → 그 줄만 「기록에 없음」
 * 「기록에 없음」은 「—」(값이 없음)와 다른 말입니다 — 기록이 쌓이면 설 값입니다. */
function CostQuality({ data, fee, empty }: { data: Dataset; fee: number; empty: boolean }) {
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
function TradeList({ data, codeFilter }: { data: Dataset; codeFilter: string }) {
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
