import { distanceText, entryWindowText, resetLine } from '../../data/ruleSummary'
import { sessionWindows } from '../../data/session'
import { baseKind, clockMinutes, EXIT_FIELDS, windowOutsideWhy, whyTone } from '../../data/strategyChecks'
import type { StrategyVersion } from '../../data/strategyList'
import {
  BASE_BARS,
  EVAL_MODES,
  exitUnitOf,
  fillCondMismatch,
  fillCondsFor,
  MARKET_FILL_COND_WHY,
  needsStopFor,
  orderTypesFor,
  excludedOrderType,
  excludedOrderTypeWhy,
  PRICE_BASES,
  RULE_LABEL,
  sessionsFor,
  OPPOSITE_SIGNALS,
  oppositeSignalLabel,
  oppositeSignalNote,
  type RuleKey,
  type SettingsDraft,
} from '../../data/strategyRules'
import { SIDE_BASES, money, orderLine, usesLine } from './strategySettingsUtils'
import type { useSettingsChecks } from './useSettingsChecks'
import type { makeRuleEditing } from './ruleEditing'
import type { settingsFields } from './SettingsFields'

type CheckValues = ReturnType<typeof useSettingsChecks>
type EditingValues = ReturnType<typeof makeRuleEditing>
type FieldParts = ReturnType<typeof settingsFields>

type SummaryArgs = Pick<CheckValues, 'lines' | 'rule' | 'aux' | 'missing' | 'warnings'> &
  {
    draft: SettingsDraft
    ruleKey: RuleKey
  }

/** 요약 — 이 전략이 쓰는 규칙과, 저장될 수 있는 값으로 지은 문장. */
export function renderSummary({
  draft,
  lines,
  ruleKey,
  rule,
  aux,
  missing,
  warnings,
}: SummaryArgs) {
  return (
          <div className="set-summary">
            {/* 요약 첫머리 — 이 전략이 **어느 규칙을 쓰는지**. 탭마다의 문장은 지금 연
                규칙 하나의 것이라, 켜 둔 규칙 전체는 여기서만 보입니다. */}
            <p className="set-summary-line set-summary-uses">
              {usesLine(draft.rules)}
            </p>
            {lines.length === 0 ? (
              /* 빈 상태 문구는 **첫 문단 자리에만** 섭니다 — 조건이 없어도 보조
                 설정은 정해져 있어, 아래 문장까지 없는 것처럼 말하면 안 됩니다. */
              <p className="set-summary-empty">조건을 채우면 여기에 문장이 섭니다</p>
            ) : (
              lines.map((line, index) => {
                /* 무엇을 하는 규칙인지만 굵게 세웁니다. 색을 쓰면 「매수」의
                   빨강이 값의 방향색과 겹쳐, 문장 속 한 낱말이 값처럼 읽힙니다. */
                const mark = `${RULE_LABEL[ruleKey]}.`
                const at = line.endsWith(mark) ? line.length - mark.length : -1
                return (
                  <p className="set-summary-line" key={index}>
                    {at < 0 ? (
                      line
                    ) : (
                      <>
                        {line.slice(0, at)}
                        <strong>{RULE_LABEL[ruleKey]}</strong>.
                      </>
                    )}
                  </p>
                )
              })
            )}

            {/* 그 규칙의 시한. 규칙 문장 바로 다음 줄이고, 비었으면 안 섭니다. */}
            {resetLine(rule, lines) !== '' && (
              <p className="set-summary-line">{resetLine(rule, lines)}</p>
            )}

            {/* 이 전략이 주문을 어떻게 내는가. 규칙 문장 뒤에 그대로 이어집니다 —
                차례는 주문이 나가는 차례(주문 방식 → 청산·수량 → 실행 필터 →
                위험 한도)이고, 오른쪽 아코디언의 차례와 같습니다. */}
            {aux.lines.map((line, index) => (
              <p className="set-summary-line" key={`aux-${index}`}>
                {line}
              </p>
            ))}

            {/* 아직 안 정한 값은 **문장에서 빼고 여기 한 줄로** 모읍니다. 값 없는
                문장을 세우면 정하지 않은 것이 정한 것처럼 읽힙니다. */}
            {missing.length > 0 && (
              <p className="set-summary-missing">아직 정하지 않음 — {missing.join('·')}.</p>
            )}

            {/* 저장은 됐지만 **이대로는 안 도는** 설정. 경고색으로 문단 끝에
                섭니다 — 막는 말이 아니라 알려 주는 말이라 저장 단추 위에는
                두지 않습니다. */}
            {warnings.map((one, index) => (
              <p className="set-summary-warn" key={`warn-${index}`}>
                {one.message}
              </p>
            ))}
          </div>
  )
}

type EvaluateSectionArgs = Pick<EditingValues, 'patch'> &
  Pick<FieldParts, 'accordion' | 'field' | 'select'> &
  {
    draft: SettingsDraft
  }

/** 조건 평가 절. */
export function renderEvaluateSection({
  accordion,
  draft,
  field,
  select,
  patch,
}: EvaluateSectionArgs) {
  return (
          accordion(
            'evaluate',
            '조건 평가',
            `기준 ${draft.baseBar} · 평가 ${draft.evalMode}`,
            0,
            <>
              {field('기준 봉', select(draft.baseBar, BASE_BARS, (v) => patch({ baseBar: v }), '기준 봉'))}
              {field('평가 봉', select(draft.evalMode, EVAL_MODES, (v) => patch({ evalMode: v }), '평가 봉'))}
              {/* 고른 값이 언제 판정하는지 한 줄로 — 「틱」은 봉이 끝나기 전에도 신호를
                  낼 수 있다는 것이 고르는 사람에게 가장 큰 차이입니다. */}
              <p className="set-hint">
                {draft.evalMode === '틱'
                  ? '체결이 올 때마다 아직 안 끝난 봉까지 넣어 판정합니다 — 봉이 끝나기 전에 신호가 날 수 있습니다'
                  : '봉이 끝날 때 한 번 판정합니다'}
              </p>
            </>,
          )
  )
}

type OrderSectionArgs = Pick<CheckValues, 'problems'> &
  Pick<EditingValues, 'setOrderType' | 'setAux'> &
  Pick<FieldParts, 'accordion' | 'field' | 'select' | 'picked'> &
  {
    draft: SettingsDraft
    version: StrategyVersion
    needsPrice: boolean
    basisWhy: (name: 'priceBasis' | 'buyPriceBasis' | 'sellPriceBasis') => string | null
  }

/** 주문 방식 절. */
export function renderOrderSection({
  accordion,
  draft,
  problems,
  field,
  setOrderType,
  version,
  select,
  needsPrice,
  picked,
  setAux,
  basisWhy,
}: OrderSectionArgs) {
  return (
          accordion(
            'order',
            '주문 방식',
            /* 접힌 줄에도 **실제로 쓰이는 것**만 적습니다 — 시장가인데 값 기준을
               함께 적으면 그 기준이 주문에 실리는 것처럼 읽힙니다. */
            orderLine(draft.aux),
            problems.order,
            <>
              {/* 예전에 저장한 설정에 전략 주문에 쓰지 않는 유형이 남아 있으면 **그 값을
                  그대로** 보입니다 — 목록에 없는 값을 두면 첫 선택지가 대신 서서 고른
                  적 없는 값이 고른 것처럼 읽힙니다. 다른 유형을 고르면 사라집니다. */}
              {field(
                '주문 유형',
                excludedOrderType(draft.aux.orderType) ? (
                  <span className="set-bad">
                    <select
                      className="control is-bad"
                      value={draft.aux.orderType}
                      aria-label="주문 유형"
                      aria-invalid
                      aria-describedby="set-why-order-type"
                      onChange={(e) => setOrderType(e.target.value)}
                    >
                      <option value={draft.aux.orderType} disabled>
                        {draft.aux.orderType}
                      </option>
                      {orderTypesFor(version.market).map((item) => (
                        <option key={item} value={item}>
                          {item}
                        </option>
                      ))}
                    </select>
                    <span id="set-why-order-type" className={whyTone('wrong')}>
                      {excludedOrderTypeWhy(draft.aux.orderType)}
                    </span>
                  </span>
                ) : (
                  select(draft.aux.orderType, orderTypesFor(version.market), setOrderType, '주문 유형')
                ),
              )}
              {/* **시장가·STOP-M 은 값을 안 받습니다**(주문 화면과 같은 규칙).
                  칸을 지우지 않고 막아 두는 것은, 다시 지정가로 바꾸면 그 자리에
                  무엇이 있었는지 보여야 하기 때문입니다. 막은 이유는 옆에 적습니다. */}
              {field(
                '주문 가격',
                needsPrice ? (
                  picked(
                    select(draft.aux.priceBasis, PRICE_BASES, (v) => setAux({ priceBasis: v }), '주문 가격'),
                    'price-basis',
                    basisWhy('priceBasis'),
                    'aux.priceBasis',
                    baseKind(draft.aux, 'priceBasis'),
                  )
                ) : (
                  <span className="set-off">
                    <select
                      className="control"
                      value={draft.aux.priceBasis}
                      aria-label="주문 가격"
                      disabled
                      aria-describedby="set-price-off"
                      onChange={() => undefined}
                    >
                      <option value={draft.aux.priceBasis}>{draft.aux.priceBasis}</option>
                    </select>
                    <span id="set-price-off" className="set-off-why">
                      시장가로 나갑니다
                    </span>
                  </span>
                ),
              )}
              {/* 방향마다의 가격 기준. **값을 받는 주문유형일 때만** 섭니다 — 위
                  공용 칸과 같은 조건입니다. 첫 선택지 「공통 기준」(빈 값)이 비우면
                  위 칸을 따른다는 것을 말해, 곁 문장을 따로 두지 않습니다. */}
              {needsPrice &&
                SIDE_BASES.map((one) =>
                  field(
                    one.label,
                    picked(
                      <select
                        className="control"
                        value={draft.aux[one.key]}
                        aria-label={one.label}
                        onChange={(event) => setAux({ [one.key]: event.target.value })}
                      >
                        <option value="">공통 기준</option>
                        {PRICE_BASES.map((item) => (
                          <option key={item} value={item}>
                            {item}
                          </option>
                        ))}
                      </select>,
                      one.key,
                      basisWhy(one.key),
                      `aux.${one.key}`,
                      baseKind(draft.aux, one.key),
                    ),
                  ),
                )}
              {/* 스탑 주문은 스탑 가격을 함께 받습니다 — 그 주문유형일 때만 섭니다. */}
              {needsStopFor(draft.aux.orderType) &&
                field(
                  '스탑 가격',
                  select(draft.aux.stopBasis, PRICE_BASES, (v) => setAux({ stopBasis: v }), '스탑 가격'),
                )}
              {/* **체결조건은 국내 주문에만 있습니다.** 해외 주문에는 그런 칸이
                  없어 세우지 않습니다 — 비활성으로 두면 언젠가 켜지는 것처럼
                  읽히고, 값이 남아 있으면 주문에 실릴 것처럼 보입니다. */}
              {/* 선택지는 주문유형이 받는 것만 둡니다(시장가는 FAS 만). 이 규칙 전에 담아 둔
                  설정이 맞지 않는 값을 들고 있으면 **그 값을 그대로** 보이고 까닭을 답니다 —
                  첫 선택지가 대신 서면 고른 적 없는 값이 고른 것처럼 읽힙니다. */}
              {version.market === 'domestic' &&
                field(
                  '체결조건',
                  fillCondMismatch(draft.aux) ? (
                    <span className="set-bad">
                      <select
                        className="control is-bad"
                        value={draft.aux.fillCond}
                        aria-label="체결조건"
                        aria-invalid
                        aria-describedby="set-why-fill-cond"
                        onChange={(e) => setAux({ fillCond: e.target.value })}
                      >
                        <option value={draft.aux.fillCond} disabled>
                          {draft.aux.fillCond}
                        </option>
                        {fillCondsFor(draft.aux.orderType).map((item) => (
                          <option key={item} value={item}>
                            {item}
                          </option>
                        ))}
                      </select>
                      <span id="set-why-fill-cond" className={whyTone('wrong')}>
                        {MARKET_FILL_COND_WHY}
                      </span>
                    </span>
                  ) : (
                    select(draft.aux.fillCond, fillCondsFor(draft.aux.orderType), (v) => setAux({ fillCond: v }), '체결조건')
                  ),
                )}
            </>,
          )
  )
}

type ExitSectionArgs = Pick<CheckValues, 'problems'> &
  Pick<EditingValues, 'setAux'> &
  Pick<FieldParts, 'accordion' | 'field' | 'distance' | 'unit' | 'filterInput' | 'filterSaid'> &
  {
    draft: SettingsDraft
  }

/** 청산 · 수량 절. */
export function renderExitSection({
  accordion,
  draft,
  problems,
  field,
  distance,
  unit,
  setAux,
  filterInput,
  filterSaid,
}: ExitSectionArgs) {
  return (
          accordion(
            'exit',
            '청산 · 수량',
            /* 추적 청산은 **정했을 때만** 접힌 줄에 섭니다 — 비어 있으면 쓰지 않는
               것이라 적을 값이 없습니다. */
            [
              `손절 ${draft.aux.stopTicks.trim() ? distanceText(draft.aux.stopTicks, draft.aux.stopUnit) : '—'}`,
              `익절 ${draft.aux.takeTicks.trim() ? distanceText(draft.aux.takeTicks, draft.aux.takeUnit) : '—'}`,
              ...(draft.aux.trailTicks.trim()
                ? [`추적 ${distanceText(draft.aux.trailTicks, draft.aux.trailUnit)}`]
                : []),
              ...(draft.aux.sessionEndFlat && draft.aux.sessionEndMinutes.trim()
                ? [`끝 ${draft.aux.sessionEndMinutes.trim()}분 전 정리`]
                : []),
            ].join(' · '),
            problems.exit,
            <>
              {field('손절', distance('stop', 'stopTicks', 'stopUnit', '손절'))}
              {field('익절', distance('take', 'takeTicks', 'takeUnit', '익절', { placeholder: '쓰지 않음' }))}
              {field('추적 청산', distance('trail', 'trailTicks', 'trailUnit', '추적 청산', { placeholder: '쓰지 않음' }))}
              {field('주문당', unit('per-order', 'perOrder', '계약', '주문당 수량'))}
              {field('최대보유', unit('max-hold', 'maxHold', '계약', '최대 보유'))}
              {/* 세션 끝 정리 — 끝 시각은 서버 시간표가 정합니다(조기 마감·야간 자정 넘김). */}
              <div className="set-bad set-session-end">
                <label className="set-check">
                  <input
                    type="checkbox"
                    checked={draft.aux.sessionEndFlat}
                    onChange={(event) => setAux({ sessionEndFlat: event.target.checked })}
                  />
                  세션 끝
                </label>
                {filterInput('sessionEndMinutes', '세션 끝 정리 분', {
                  className: 'set-filter-num',
                  disabled: !draft.aux.sessionEndFlat,
                })}
                <span className="set-filter-text">분 전</span>
                <span className="set-filter-text set-session-end-text">모두 청산하고 새 진입 막기</span>
                {draft.aux.sessionEndFlat && filterSaid(['sessionEndMinutes'])}
              </div>
              {/* 값을 적은 거리 칸이 ATR 단위면, ATR 이 아직 없을 때 그 거리를 셀 수 없어
                  진입하지 않습니다(서버 판정). 값이 빈 칸은 쓰지 않는 칸이라 단위가 ATR 이어도
                  세지 않습니다 — 「비었다」는 앞뒤 공백을 걷고 빈 글자인 것으로, 칸 판정과 같습니다. */}
              {(Object.keys(EXIT_FIELDS) as (keyof typeof EXIT_FIELDS)[]).some(
                (key) => exitUnitOf(draft.aux[EXIT_FIELDS[key]]) === 'atr' && (draft.aux[key] ?? '').trim() !== '',
              ) && (
                <p className="set-hint">ATR(14)이 준비될 때까지 새로 진입하지 않습니다</p>
              )}
              {/* 청산 규칙만 위 주문 유형으로 나갑니다. 나머지는 「지금 닫는다」는 뜻이라
                  지정가로 걸면 값이 지나가 보유가 남을 수 있어 시장가로 나갑니다. */}
              <p className="set-hint">
                손절 · 익절 · 추적 청산 · 세션 끝 정리는 앱 실행 중 감시하며, 주문 유형과 상관없이 시장가로 보유 전량을 청산합니다
              </p>
            </>,
          )
  )
}

type FilterSectionArgs = Pick<CheckValues, 'problems'> &
  Pick<EditingValues, 'setAux'> &
  Pick<FieldParts, 'accordion' | 'field' | 'select' | 'stacked' | 'filterInput' | 'filterSaid'> &
  {
    draft: SettingsDraft
    version: StrategyVersion
    sessionWindow: ReturnType<typeof sessionWindows>[number] | null
  }

/** 실행 필터 절. */
export function renderFilterSection({
  accordion,
  draft,
  problems,
  field,
  select,
  version,
  setAux,
  stacked,
  filterInput,
  filterSaid,
  sessionWindow,
}: FilterSectionArgs) {
  return (
          accordion(
            'filter',
            '실행 필터',
            [
              draft.aux.session,
              entryWindowText(draft.aux.entryStart, draft.aux.entryEnd),
              Number(draft.aux.reentryWaitBars.trim()) > 0 ? `대기 ${draft.aux.reentryWaitBars.trim()}봉` : '',
              draft.aux.addWhileOpen ? '추가 진입 함' : '보유/미체결 중 추가 진입 안 함',
              `반대 신호 ${oppositeSignalLabel(draft.aux.oppositeSignal)}`,
            ]
              .filter((one) => one !== '')
              .join(' · '),
            problems.filter,
            <>
              {field(
                '세션',
                select(draft.aux.session, sessionsFor(version.market), (v) => setAux({ session: v }), '세션'),
              )}
              {/* 신규 진입 시간 — 한국시간이고, 비우면 세션 시작·끝입니다. 끝이 시작보다
                  이르면 다음 날입니다. 세션 밖 시각은 저장은 되지만 실행을 세울 때 서버가
                  막아 경고색으로 미리 알립니다. */}
              {stacked(
                '신규 진입 시간',
                <span className="set-bad set-bad-start">
                  <span className="set-window">
                    {filterInput('entryStart', '신규 진입 시작', { clock: true, placeholder: '세션 시작', className: 'set-clock' })}
                    <span className="set-filter-text">~</span>
                    {filterInput('entryEnd', '신규 진입 끝', { clock: true, placeholder: '세션 끝', className: 'set-clock' })}
                    {draft.aux.entryStart.trim() !== '' &&
                      draft.aux.entryEnd.trim() !== '' &&
                      clockMinutes(draft.aux.entryEnd) < clockMinutes(draft.aux.entryStart) && (
                        <span className="set-filter-text">익일</span>
                      )}
                    <span className="set-filter-text set-filter-dim">한국시간</span>
                  </span>
                  {filterSaid(['entryStart', 'entryEnd']) ??
                    (windowOutsideWhy(draft.aux, sessionWindow) && (
                      <span className="set-warn-why">{windowOutsideWhy(draft.aux, sessionWindow)}</span>
                    ))}
                  <span className="set-filter-note">청산은 이 시간 밖에서도 합니다</span>
                </span>,
              )}
              {stacked(
                '청산 뒤 대기',
                <span className="set-bad set-bad-start">
                  <span className="set-window">
                    {filterInput('reentryWaitBars', '청산 뒤 대기', { placeholder: '0' })}
                    <span className="set-filter-text">봉</span>
                    <span className="set-filter-text set-filter-dim">기준 {draft.baseBar}</span>
                  </span>
                  {filterSaid(['reentryWaitBars'])}
                </span>,
              )}
              <label className="set-check">
                <input
                  type="checkbox"
                  checked={draft.aux.addWhileOpen}
                  onChange={(event) => setAux({ addWhileOpen: event.target.checked })}
                />
                보유 · 미체결 중에도 추가 진입
              </label>
              {/* 보유 중에 반대 방향 진입 규칙이 참이 되면 어떻게 할지. 고른 값의 뜻을
                  바로 아래에 한 문장으로 적습니다. */}
              {field(
                '보유 중 반대 진입 신호',
                select(
                  oppositeSignalLabel(draft.aux.oppositeSignal),
                  OPPOSITE_SIGNALS.map((one) => one.label),
                  (v) =>
                    setAux({
                      oppositeSignal: OPPOSITE_SIGNALS.find((one) => one.label === v)?.id ?? 'ignore',
                    }),
                  '보유 중 반대 진입 신호',
                ),
              )}
              <p className="set-hint">{oppositeSignalNote(draft.aux.oppositeSignal)}</p>
            </>,
          )
  )
}

type RiskSectionArgs = Pick<CheckValues, 'problems'> &
  Pick<FieldParts, 'accordion' | 'field' | 'unit' | 'filterInput' | 'filterSaid'> &
  {
    draft: SettingsDraft
    currency: string
  }

/** 위험 한도 절. */
export function renderRiskSection({
  accordion,
  draft,
  currency,
  problems,
  field,
  unit,
  filterInput,
  filterSaid,
}: RiskSectionArgs) {
  return (
          accordion(
            'risk',
            '위험 한도',
            `하루 ${money(draft.aux.dailyLoss, currency)} · 예산 ${money(draft.aux.marginBudget, currency)}` +
              (draft.aux.lossStreak.trim() ? ` · 연속 손실 ${draft.aux.lossStreak.trim()}번` : '') +
              (draft.aux.maxEntriesPerDay.trim() ? ` · 최대 ${draft.aux.maxEntriesPerDay.trim()}번` : ''),
            problems.risk,
            <>
              {field(
                '하루 손실',
                unit('daily-loss', 'dailyLoss', currency, '하루 손실 한도'),
              )}
              {field(
                '증거금 예산',
                unit('margin-budget', 'marginBudget', currency, '증거금 예산'),
              )}
              {field(
                '연속 손실',
                unit('loss-streak', 'lossStreak', '번', '연속 손실 한도', {
                  placeholder: '쓰지 않음',
                  field: 'aux.lossStreak',
                }),
              )}
              <p className="set-hint">손실 거래가 이만큼 이어지면 그날은 새 진입을 멈춥니다</p>
              {field(
                '하루 최대 진입',
                <span className="set-bad">
                  <span className="set-window">
                    {filterInput('maxEntriesPerDay', '하루 최대 진입', { placeholder: '제한 없음' })}
                    <span className="set-filter-text">번</span>
                  </span>
                  {filterSaid(['maxEntriesPerDay'])}
                </span>,
              )}
            </>,
          )
  )
}

type MemoSectionArgs = Pick<EditingValues, 'patch'> &
  Pick<FieldParts, 'accordion' | 'field'> &
  {
    draft: SettingsDraft
  }

/** 메모 절. */
export function renderMemoSection({
  accordion,
  draft,
  field,
  patch,
}: MemoSectionArgs) {
  return (
          accordion(
            'memo',
            '메모',
            draft.memo.split('\n')[0] || '—',
            0,
            field(
              '메모',
              <input
                className="control set-text"
                value={draft.memo}
                placeholder="이 버전에 남길 말"
                aria-label="메모"
                onChange={(event) => patch({ memo: event.target.value })}
              />,
            ),
          )
  )
}
