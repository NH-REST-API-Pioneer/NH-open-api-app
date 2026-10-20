import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { contractsOf, frontContractOf } from '../../data/instruments'
import { productOfVersion, useStrategyCurrency } from '../../data/strategyList'
import { BacktestCard } from './BacktestCard'
import { sessionWindows, useTimetable } from '../../data/session'
import { severityKind, sideBases, whyTone } from '../../data/strategyChecks'
import type { SaveResult } from '../../data/strategyStore'
import type { StrategyVersion } from '../../data/strategyList'
import { needsPriceFor, type RuleKey, type SettingsDraft } from '../../data/strategyRules'
import { MAIN_MIN } from './strategySettingsUtils'
import { useSettingsLayout } from './useSettingsLayout'
import { useSettingsChecks } from './useSettingsChecks'
import { makeRuleEditing } from './ruleEditing'
import { ruleEditorParts, renderRuleMain } from './RuleEditor'
import { settingsFields } from './SettingsFields'
import { renderSettingsHead } from './SettingsHead'
import {
  renderSummary,
  renderEvaluateSection,
  renderOrderSection,
  renderExitSection,
  renderFilterSection,
  renderRiskSection,
  renderMemoSection,
} from './SettingsAside'

/* 전략 설정 — 조건 본문 2/3, 보조 1/3.
 *
 * 규칙 넷을 탭으로 나눕니다. 넷을 한 화면에 펼치면 어느 조건이 어느 규칙의
 * 것인지 읽는 데 화면 절반이 듭니다.
 */

interface Props {
  version: StrategyVersion
  draft: SettingsDraft
  onChange: (next: SettingsDraft) => void
  dirty: boolean
  /** 마지막 저장 시도에 서버가 답한 것. **경고와 오류를 갈라 그립니다** —
   *  경고는 저장을 막지 않고 알려만 주고, 오류는 막습니다. 아직 저장을 안
   *  눌렀으면 `null` 입니다. */
  result: SaveResult | null
  /** 아직 목록에 없는 새 버전인가. **저장이 통과해야 목록에 섭니다** — 그
   *  사실을 상단 한 줄이 먼저 말합니다. */
  unsaved: boolean
  onSave: () => void
  /** 「새 버전 저장」. 목록에 다음 버전 초안 행을 만듭니다. */
  onSaveAsNew: () => void
  /** 어느 버전이든 저장하는 중인지. 그동안 「새 버전 저장」을 잠급니다. */
  busy: boolean
  onRevert: () => void
}

export function StrategySettings({
  version,
  draft,
  onChange,
  dirty,
  result,
  unsaved,
  onSave,
  onSaveAsNew,
  busy,
  onRevert,
}: Props) {
  const [ruleKey, setRuleKey] = useState<RuleKey>('buyEntry')
  /* 종목 고르개가 열려 있는지. 화면에만 남는 값입니다. */
  const [picking, setPicking] = useState(false)

  /* 이 줄이 가리키는 품목과, 지금 그것이 푸는 월물. **색인이 답합니다** —
     줄에 이름을 적어 두면 만기가 넘어갈 때 이름과 실제 종목이 갈립니다. */
  const product = productOfVersion(version)
  /* 금액의 통화. 해외인데 담긴 코드가 없으면 품목정보의 통화입니다. */
  const currency = useStrategyCurrency(version)
  const months = useMemo(
    () => (product ? contractsOf(product, version.productKind) : []),
    [product, version.productKind],
  )
  /* 「근월 자동」이 지금 무엇을 가리키는지. 자동을 골라 둔 사람도 오늘 어느
     달로 도는지는 알아야 합니다 — 고르개에는 「근월 · 12월물」처럼 짧게 적고,
     연도까지 붙은 이름은 마우스를 올리면 나옵니다(`title`). */
  const frontName = product
    ? (frontContractOf(product, version.productKind)?.label ?? '')
    : ''

  /* 서버가 그 칸에 짚은 말. **칸 옆에 답니다** — 종목은 고르는 자리라 꼬리줄에
     두면 무엇을 고쳐야 하는지가 화면 반대쪽에 섭니다. */
  const problemOf = (field: string) => {
    const one = said.find((item) => item.field === field)
    if (!one) return null
    return (
      <span className={whyTone(severityKind(one.severity))}>
        {one.message}
      </span>
    )
  }
  /* 이 전략이 도는 세션의 창 — 신규 진입 시간이 그 안인지 알리는 데 씁니다. 시간표가
     늦게 오면 그때 다시 셉니다. 국내는 주간·야간, 해외는 1차 거래 창입니다. */
  const timetable = useTimetable()
  const sessionWindow = useMemo(() => {
    if (!product) return null
    const windows = sessionWindows(version.market, product.exchangeNo ?? null, product.code)
    if (windows.length === 0) return null
    if (version.market === 'domestic') return draft.aux.session.includes('야간') ? (windows[1] ?? null) : windows[0]
    return windows[0]
    // 시간표가 오면 다시 셉니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [product, version.market, draft.aux.session, timetable])
  const needsPrice = needsPriceFor(draft.aux.orderType)
  /* 가격 기준 세 칸의 판정 — 칸 아래 줄과 접힌 절의 「고칠 것」이 같은 셈입니다. */
  const bases = useMemo(() => sideBases(draft.aux), [draft.aux])
  const basisWhy = (name: 'priceBasis' | 'buyPriceBasis' | 'sellPriceBasis') =>
    bases.find((one) => one.field === name)?.why ?? null
  /* 쉼표를 다시 단 금액 칸의 커서 자리. 새 글자가 그려진 뒤에 둡니다. */
  const caretAfterRender = useRef<{ input: HTMLInputElement; at: number } | null>(null)
  useLayoutEffect(() => {
    const pending = caretAfterRender.current
    if (!pending) return
    caretAfterRender.current = null
    if (document.activeElement === pending.input) pending.input.setSelectionRange(pending.at, pending.at)
  })
  const {
    bodyRef,
    asideRef,
    side,
  } = useSettingsLayout()
  const [open, setOpen] = useState({
    evaluate: false,
    order: true,
    exit: true,
    filter: false,
    risk: false,
    memo: false,
  })
  const {
    rule,
    used,
    full,
    problems,
    daily,
    blocked,
    nothingToSave,
    saveParts,
    goToProblem,
    liveRuns,
    lines,
    said,
    tabBadge,
    ruleSaid,
    condSaid,
    nightSession,
    warnings,
    looseErrors,
    aux,
    missing,
  } = useSettingsChecks({
    draft,
    ruleKey,
    setRuleKey,
    setOpen,
    dirty,
    unsaved,
    version,
    currency,
    result,
  })
  const {
    patch,
    setAux,
    setOrderType,
    setRule,
    toggleRule,
    editStep,
    editCond,
    pickLeft,
    pickRight,
    paramFields,
    pickOp,
    addCond,
    dropCond,
    addStep,
    dropStep,
    limitWhy,
  } = makeRuleEditing({
    onChange,
    draft,
    version,
    ruleKey,
    rule,
    full,
  })

  const {
    stepCard,
  } = ruleEditorParts({
    daily,
    condSaid,
    ruleKey,
    nightSession,
    pickLeft,
    pickOp,
    editCond,
    pickRight,
    dropCond,
    paramFields,
    rule,
    problemOf,
    editStep,
    dropStep,
    full,
    addCond,
  })
  const {
    accordion,
    field,
    stacked,
    select,
    unit,
    distance,
    filterInput,
    filterSaid,
    picked,
  } = settingsFields({
    open,
    setOpen,
    draft,
    currency,
    setAux,
    problemOf,
    caretAfterRender,
  })

  return (
    <div className="set">
      {renderSettingsHead({
        liveRuns,
        version,
        product,
        picking,
        setPicking,
        draft,
        setAux,
        problemOf,
        months,
        frontName,
        dirty,
        onRevert,
        blocked,
        nothingToSave,
        unsaved,
        onSave,
        busy,
        onSaveAsNew,
        saveParts,
        goToProblem,
        result,
        looseErrors,
      })}

      <div
        className="set-body"
        ref={bodyRef}
        style={
          side.size === null
            ? undefined
            : { gridTemplateColumns: `minmax(${MAIN_MIN}px, 1fr) 8px ${side.size}px` }
        }
      >
        {renderRuleMain({
          ruleKey,
          setRuleKey,
          tabBadge,
          draft,
          toggleRule,
          used,
          rule,
          ruleSaid,
          stepCard,
          problemOf,
          setRule,
          full,
          addStep,
          limitWhy,
        })}

        {/* 끌거나 화살표 키로 오른쪽 칸 폭을 바꿉니다. 더블클릭·Enter 는 원래 비율로. */}
        <div
          className="split-handle split-handle-x"
          aria-label="오른쪽 칸 폭"
          title="끌어서 오른쪽 칸 폭 조절 · 더블클릭하면 원래대로"
          {...side.handleProps}
        />

        <aside className="set-aux" aria-label="보조 설정" ref={asideRef}>
          {/* 요약은 **읽는 것**이라 고치는 자리(왼쪽 편집기)에서 떼어 오른쪽
              열 맨 위에 둡니다 — 왼쪽 맨 아래에 붙박이로 두면 조건이 구르는
              칸의 세로를 그만큼 먹습니다. 이 열은 제 안에서 굴러, 요약과 보조
              설정이 둘 다 닿습니다. */}
          {renderSummary({
            draft,
            lines,
            ruleKey,
            rule,
            aux,
            missing,
            warnings,
          })}
          {/* 요약 바로 아래 — 이 규칙으로 지난 봉을 돌려 본 답. 저장이 막힌 상태면
              셈을 부르지 않습니다(저장 단추와 같은 판정). */}
          <BacktestCard version={version} draft={draft} dirty={dirty} blocked={blocked} currency={currency} />
          {/* 조건을 **어느 봉으로 재는가.** 조건을 재는 것이 주문보다 앞서므로 맨
              위입니다. 접힌 줄은 낱말과 값을 함께 적습니다 — 「마감」만 두면 무엇의
              값인지 안 읽힙니다. */}
          {renderEvaluateSection({
            accordion,
            draft,
            field,
            select,
            patch,
          })}

          {renderOrderSection({
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
          })}

          {renderExitSection({
            accordion,
            draft,
            problems,
            field,
            distance,
            unit,
            setAux,
            filterInput,
            filterSaid,
          })}

          {renderFilterSection({
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
          })}

          {renderRiskSection({
            accordion,
            draft,
            currency,
            problems,
            field,
            unit,
            filterInput,
            filterSaid,
          })}

          {/* 이 버전에 남긴 말. **실행에는 안 쓰이는 값**이라 맨 끝이고, 위 요약
              문단에도 넣지 않습니다(요약은 실제로 쓰이는 것만). 접힌 줄은 첫 줄만
              적고, 비었으면 「—」입니다. */}
          {renderMemoSection({
            accordion,
            draft,
            field,
            patch,
          })}
        </aside>
      </div>
    </div>
  )
}
