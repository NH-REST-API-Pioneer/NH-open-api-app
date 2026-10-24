import {
  ANALYSIS_KINDS,
  RECORD_PARAM,
  SPANS,
  amountText,
  pickRecordMarket,
  netOf,
  setRecordFilters,
  wins,
  type AnalysisKind,
  type Dataset,
  type RecordsState,
  type Span,
  type Trade,
} from '../../data/strategyRecords'
import { RunKindBadge } from './runKind'
import { FEE_ASSUMED } from '../../data/strategyRuns'
import {
  isKrw,
  man,
  Amount,
  countText,
  Dash,
  codeName,
  drawdownTitle,
  Busy,
  Notes,
  Metric,
} from './StrategyAnalysisParts'
import { shortRange, RangePicker } from './AnalysisPickers'

/** 필터 줄. 기록·시장·통화·기간 칸과 전략·종목 고르개. */
export function renderAnalysisHead({
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
}: {
  filters: RecordsState['filters']
  data: Dataset | null
  currencyChoices: string[]
  spanId: string
  pickSpan: (span: Span) => void
  records: RecordsState
  groupTitle: string
  pickGroup: (group: string) => void
  groups: [string, { name: string; versions: string[] }][]
  groupGone: boolean
  codeTitle: string
  codeChoices: string[]
}) {
  return (
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
  )
}

/** 지표 카드 넷. 순실현손익·평가손익·승률·최대 낙폭. */
export function renderAnalysisCards({
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
}: {
  perLines: (pick: (one: Dataset) => React.ReactNode) => React.ReactNode
  data: Dataset | null
  net: number
  currency: string
  multi: Dataset[] | null
  empty: boolean
  gross: number
  fee: number
  rate: number | null
  allTrades: Trade[]
  mdd: number | null
  ddTitle: string | undefined
}) {
  return (
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
          /* 수준값이라 본문색이고 **빼기 부호도 없습니다**. 낙폭은
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
  )
}
