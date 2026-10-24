import { Fragment } from 'react'
import { contractsOf } from '../../data/instruments'
import { accountOf, codeOfVersion, currencyOf, productOfVersion } from '../../data/strategyList'
import { loadOverseasProductInfo, overseasProductInfoEntry } from '../../data/productInfo'
import { InstrumentPicker } from '../../lib/InstrumentPicker'
import { revertCountOf, setVersionEdit, versionOf, type SaveResult } from '../../data/strategyStore'
import type { StrategyVersion } from '../../data/strategyList'
import {
  FILL_CONDS,
  fillCondFor,
  orderTypesFor,
  sessionsFor,
  type SettingsDraft,
} from '../../data/strategyRules'
import type { Dispatch, SetStateAction, JSX } from 'react'
import type { useSettingsChecks } from './useSettingsChecks'
import type { makeRuleEditing } from './ruleEditing'

type CheckValues = ReturnType<typeof useSettingsChecks>
type EditingValues = ReturnType<typeof makeRuleEditing>

type SettingsHeadArgs = Pick<
    CheckValues,
    'liveRuns' | 'blocked' | 'nothingToSave' | 'saveParts' | 'goToProblem' | 'looseErrors'
  > &
  Pick<EditingValues, 'setAux'> &
  {
    version: StrategyVersion
    product: ReturnType<typeof productOfVersion>
    picking: boolean
    setPicking: Dispatch<SetStateAction<boolean>>
    draft: SettingsDraft
    problemOf: (field: string) => JSX.Element | null
    months: ReturnType<typeof contractsOf>
    frontName: string
    dirty: boolean
    onRevert: () => void
    unsaved: boolean
    onSave: () => void
    busy: boolean
    onSaveAsNew: () => void
    result: SaveResult | null
  }

/** 설정 머리 — 전략명·버전·종목·월물과 되돌리기·저장 단추, 그 아래 줄들. */
export function renderSettingsHead({
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
}: SettingsHeadArgs) {
  return (
      <div className={`card set-head${liveRuns > 0 ? ' has-runs' : ''}`}>
        <div className="set-head-main">
          <label className="set-field set-name">
            <span className="set-field-label">전략명</span>
            {/* **이름을 고치는 자리는 여기 하나**입니다. 목록은 고르는 자리라
                거기서도 고쳐지면 잘못 눌러 이름이 바뀝니다. 고친 이름은 저장을
                눌러야 목록에 섭니다 — 그때까지 목록은 저장된 이름 그대로입니다. */}
            <input
              className="control set-name-value"
              value={version.name}
              aria-label="전략명"
              /* 칸보다 긴 이름은 말줄임으로 서므로 전체를 여기 둡니다. */
              title={version.name}
              onChange={(event) => setVersionEdit(version.id, { name: event.target.value })}
            />
          </label>

          <label className="set-field set-version">
            <span className="set-field-label">버전</span>
            {/* `disabled` 를 안 씁니다 — 초점이 건너뛰면 옆에 달아 둔 이유를
                읽을 길이 없습니다. 고를 것이 하나라 값은 안 바뀝니다. */}
            <select
              className="control"
              value={version.version}
              aria-label="버전"
              aria-disabled
              title="버전은 목록에서 고릅니다"
              onChange={(event) => event.preventDefault()}
            >
              <option>{version.version}</option>
            </select>
          </label>

          {/* **품목과 월물을 나눠 둡니다.** 품목은 이 전략이 무엇을 거래하나이고,
              월물은 그 가운데 어느 달인가입니다 — 한 칸에 담으면 만기가 넘어갈
              때마다 전략이 없는 종목을 가리킵니다. 기본이 「근월 자동」인 것도
              그 때문입니다. */}
          <div className="set-field set-instrument">
            <span className="set-field-label" id="set-product-label">
              품목
            </span>
            <button
              type="button"
              className="control set-pick"
              aria-label={`품목 바꾸기 — ${product ? product.name : version.instrumentFallback || '고르지 않음'}`}
              aria-expanded={picking}
              onClick={() => setPicking((open) => !open)}
            >
              <span className="set-pick-name">
                {product ? product.name : (version.instrumentFallback || '품목을 고르세요')}
              </span>
              {/* **여는 칸이라는 표시**입니다. 옆의 월물은 셀렉트라 브라우저가
                  꺾쇠를 그려 주는데, 이 칸은 단추라 아무 표시가 없으면 적어 둔
                  값으로만 보입니다 — 누를 수 있다는 것이 안 읽힙니다. */}
              <span className="set-pick-mark" aria-hidden="true" />
            </button>
            {picking && (
              /* **품목 모드**로 엽니다. 여기서 정하는 것은 「무엇을 거래하나」
                 하나이고 어느 달인가는 옆 칸이 맡으므로, 월물이 늘어선 판을
                 세우면 누른 월물이 버려진 것처럼 읽힙니다. */
              <InstrumentPicker
                mode="product"
                market={version.market}
                current={
                  product
                    ? {
                        productCode: product.code,
                        productKind: version.productKind,
                        market: version.market,
                        productName: product.name,
                      }
                    : null
                }
                onClose={() => setPicking(false)}
                /* 품목을 바꾸면 월물은 「근월 자동」으로 돌아갑니다 — 앞 품목의
                   월물은 새 품목에서 가리킬 것이 없습니다. */
                onPick={(item) => {
                  /* 계좌·통화는 **시장이 정합니다.** 해외 통화는 품목정보가 답하므로
                     그 답이 오면 채웁니다 — 원으로 남겨 두면 달러 한도가 원으로
                     읽힙니다. */
                  setVersionEdit(version.id, {
                    market: item.market,
                    productCode: item.productCode,
                    productKind: item.productKind,
                    contractCode: '',
                    instrumentFallback: item.productName,
                    account: accountOf(item.market),
                    currency: currencyOf(item.market, ''),
                  })
                  /* 시장이 바뀌면 그 시장에 없는 값을 그 시장의 값으로 — 국내 세션이 남은
                     해외 전략은 저장이 막히고, 해외의 STOP 주문유형이 남은 국내 전략은
                     주문 유형 칸이 다른 값을 보이며 그 값으로 저장됩니다. 주문유형은 새
                     시장에도 있으면 그대로 둡니다. 체결조건은 국내 주문에만 붙습니다. */
                  if (item.market !== version.market) {
                    const types = orderTypesFor(item.market)
                    const orderType = types.includes(draft.aux.orderType) ? draft.aux.orderType : types[0]
                    setAux({
                      session: sessionsFor(item.market)[0] ?? '',
                      orderType,
                      fillCond:
                        item.market === 'domestic'
                          ? fillCondFor(
                              orderType,
                              FILL_CONDS.includes(draft.aux.fillCond) ? draft.aux.fillCond : FILL_CONDS[0],
                            )
                          : '',
                    })
                  }
                  if (item.market === 'overseas') {
                    const code = codeOfVersion({ ...item, contractCode: '' })
                    const asked = revertCountOf(version.id)
                    void loadOverseasProductInfo(code).then(() => {
                      /* 답이 오는 사이 품목을 또 바꿨으면 이 답은 앞 품목의 것이라 안 씁니다.
                         되돌렸어도 같습니다 — 버린 변경의 통화를 다시 세우면 되돌린
                         버전이 「고친 것 있음」으로 돌아갑니다. */
                      if (revertCountOf(version.id) !== asked) return
                      const now = versionOf(version.id)
                      if (now?.market !== 'overseas' || now.productCode !== item.productCode) return
                      const found = currencyOf('overseas', overseasProductInfoEntry(code).row?.currency)
                      if (found) setVersionEdit(version.id, { currency: found })
                    })
                  }
                  setPicking(false)
                }}
              />
            )}
            {problemOf('productCode')}
            {problemOf('market')}
          </div>

          <label className="set-field set-month">
            <span className="set-field-label">월물</span>
            {/* 「근월 자동」이 기본입니다 — 만기가 넘어가도 살아 있고, 만기
                당일은 건너뜁니다(엔진이 그날 진입을 막습니다). 특정 월물을
                고르면 그 달로 못 박히고, 그 달이 지나면 고쳐야 합니다.
                칸에는 짧은 꼴(「근월 · 10월물」)로 **지금 가리키는 달**을 남기고,
                전체 문장은 칸의 `title` 에 둡니다 — 전체를 칸에 세우면 이 폭에서
                음절 가운데가 잘립니다. 「근월」이 앞에 서서 못 박은 월물과
                갈립니다. */}
            <select
              className="control"
              value={version.contractCode ?? ''}
              aria-label="월물"
              title={
                version.contractCode
                  ? (months.find((item) => item.code === version.contractCode)?.label ?? '')
                  : `근월 자동${frontName && ` — 지금 ${frontName}`}`
              }
              onChange={(event) =>
                setVersionEdit(version.id, { contractCode: event.target.value })
              }
            >
              <option value="">
                {frontName ? `근월 · ${frontName.replace(/^\d+년\s*/, '')}` : '근월 자동'}
              </option>
              {months.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.label}
                </option>
              ))}
            </select>
            {problemOf('contractCode')}
          </label>
          {/* 기준 봉·평가 봉·메모는 **오른쪽 보조 설정**(「조건 평가」·「메모」)에
              있습니다. 머리는 「이 전략이 무엇인가」 넷만 둡니다 — 일곱 칸이 한 줄에
              서면 칸이 서로를 밀어 글자가 잘립니다. 셋은 훑는 값이 아니라 정하는
              값입니다. */}
        </div>

        <div className="set-head-acts">
          <button
            type="button"
            className="btn btn-quiet"
            aria-disabled={!dirty}
            /* 막힌 이유는 「고친 것이 없음」입니다 — 단추에 마우스를 올리면 섭니다.
               단추 아래 줄은 저장을 막는 까닭만 둡니다. */
            title={dirty ? undefined : '고친 것이 없습니다'}
            onClick={onRevert}
          >
            되돌리기
          </button>
          {/* 화면의 초록은 이 하나입니다. 「새 버전 저장」은 같은 일의 갈래라
              한 급 낮춰 무채색 테두리로 둡니다.
              못 받은 값이 있으면 둘 다 안 눌립니다 — `disabled` 가 아니라
              `aria-disabled` 인 것은 초점이 닿아야 아래 줄의 까닭을 읽을 수
              있어서입니다(되돌리기와 같은 규칙).
              마지막으로 저장한 것에서 고친 것이 없으면 「저장」도 잠급니다 — 이유는
              되돌리기와 같은 말이 마우스를 올리면 섭니다. 아직 목록에 없는 새 버전은
              고치지 않았어도 저장해야 목록에 서므로 잠그지 않습니다. */}
          <button
            type="button"
            className="btn btn-primary"
            aria-disabled={blocked || nothingToSave || undefined}
            aria-describedby={blocked ? 'set-save-why' : undefined}
            title={
              nothingToSave
                ? '고친 것이 없습니다'
                : unsaved
                  ? '저장 전 초안 — 목록에는 저장 뒤에 섭니다'
                  : undefined
            }
            onClick={() => !blocked && !nothingToSave && onSave()}
          >
            저장
          </button>
          {/* 「저장」과 다른 일입니다 — 목록에 **다음 버전 초안 행**을 만듭니다.
              못 받은 값은 새 버전에도 실을 수 없어 같은 까닭으로 막습니다. */}
          <button
            type="button"
            className="btn btn-quiet"
            aria-disabled={blocked || busy || undefined}
            aria-describedby={blocked ? 'set-save-why' : undefined}
            title={!blocked && busy ? '저장하는 중입니다' : undefined}
            onClick={() => !blocked && !busy && onSaveAsNew()}
          >
            새 버전 저장
          </button>
          {/* 못 고치는 칸·못 누르는 단추의 이유가 여기 한 줄에 모입니다.
              이유를 칸 밑에 달면 그 칸만 키가 커져 머리줄의 다른 칸들이
              눌립니다 — 머리는 폭이 좁고 칸이 여섯입니다.
              **이유가 둘 이상이면 앞에 그 칸·단추의 이름을 답니다** — 이름이
              없으면 어느 것이 왜 막혔는지 줄에서 갈리지 않습니다. 하나뿐일
              때는 이름 없이 그 이유만 섭니다.
              **없는 이유는 자리도 안 만듭니다** — 가운뎃점만 남으면 뒤에 무언가
              더 있었던 것처럼 읽힙니다. */}
          {/* 단추 아래에는 **저장을 막는 까닭만** 둡니다 — 묶음마다 그 수와 함께, 누르면
              그 자리로 갑니다. 되돌리기·버전·저장 전 초안의 까닭은 그 단추·칸에
              마우스를 올리면 섭니다. 막는 것이 없으면 이 줄은 자리도 안 만듭니다. */}
          {saveParts.length > 0 && (
            <p className="set-note" id="set-save-why">
              저장하려면 —{' '}
              {saveParts.map((part, index) => (
                <Fragment key={part.id}>
                  {index > 0 && <span aria-hidden="true"> · </span>}
                  <button type="button" className="set-note-link" onClick={() => goToProblem(part.id)}>
                    {part.text}
                  </button>
                </Fragment>
              ))}
            </p>
          )}

          {/* 서버가 저장을 안 받은 까닭. **막는 말이라 저장 단추 위**에 오류색
              한 줄로 섭니다 — 자리를 못 찾은 오류(본문 불일치·저장소 오류)는
              칸 옆에 붙을 데가 없어 여기가 유일한 자리입니다. */}
          {result !== null && !result.ok && (
            <p className="set-fail" id="set-fail-why">
              {/* 머리가 따로 온 실패(새 버전 저장)는 머리가 이미 까닭까지 담은 한 줄입니다. */}
              {[result.head ?? '저장', [result.message, ...looseErrors.map((one) => one.message)].filter(Boolean).join(' · ')]
                .filter(Boolean)
                .join(' — ')}
            </p>
          )}
        </div>
        {/* 도는 실행이 있으면 저장이 그 실행에 안 닿는다는 말. 단추가 왜 잠겼나를
            말하는 오른쪽 줄과 뜻이 달라 **머리 맨 아래 따로** 한 줄로 섭니다. */}
        {liveRuns > 0 && (
          <p className="set-runs-note" id="set-runs-why">
            도는 실행 {liveRuns}개는 시작할 때의 설정으로 돕니다 — 저장은 새로 세우는 실행부터
          </p>
        )}
      </div>
  )
}
