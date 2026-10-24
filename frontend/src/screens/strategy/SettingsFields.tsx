import { caretAfter, currencyCode, currencyDigits, limitTyped } from '../../lib/number'
import {
  auxCheck,
  filterWhy,
  type AuxFilter,
  whyTone,
  type AuxNumber,
  type WhyKind,
} from '../../data/strategyChecks'
import { EXIT_UNITS, exitUnitOf, type SettingsDraft } from '../../data/strategyRules'
import { MONEY_KEYS } from './strategySettingsUtils'
import type { OpenSections } from './strategySettingsUtils'
import type { Dispatch, SetStateAction, RefObject, JSX } from 'react'
import type { makeRuleEditing } from './ruleEditing'

type EditingValues = ReturnType<typeof makeRuleEditing>

type SettingsFieldArgs = Pick<EditingValues, 'setAux'> &
  {
    open: OpenSections
    setOpen: Dispatch<SetStateAction<OpenSections>>
    draft: SettingsDraft
    currency: string
    problemOf: (field: string) => JSX.Element | null
    caretAfterRender: RefObject<{ input: HTMLInputElement; at: number } | null>
  }

/** 보조 설정의 접는 절과 칸 하나하나를 그리는 함수. */
export function settingsFields({
  open,
  setOpen,
  draft,
  currency,
  setAux,
  problemOf,
  caretAfterRender,
}: SettingsFieldArgs) {
  function accordion(
    id: keyof typeof open,
    title: string,
    summary: string,
    count: number,
    body: React.ReactNode,
  ) {
    return (
      <section className="card set-acc" data-acc={id}>
        <button
          type="button"
          className="set-acc-head"
          aria-expanded={open[id]}
          aria-label={`${title} ${open[id] ? '접기' : '펼치기'}`}
          onClick={() => setOpen({ ...open, [id]: !open[id] })}
        >
          <span className="set-acc-title">{title}</span>
          {/* 접혀 있어도 무엇으로 정해졌는지와 손볼 곳이 몇인지 보입니다. 펴면
              칸 아래 줄이 어느 칸인지 가리키므로 배지는 접혔을 때만 섭니다. */}
          {!open[id] && (
            <span className="set-acc-sum" title={summary}>
              {summary}
            </span>
          )}
          {!open[id] && count > 0 && <span className="badge badge-warn set-acc-bad">고칠 것 {count}</span>}
          <span className="set-acc-mark">{open[id] ? '⌃' : '⌄'}</span>
        </button>
        {open[id] && <div className="set-acc-body">{body}</div>}
      </section>
    )
  }

  const field = (label: string, node: React.ReactNode) => (
    <label className="set-row" key={label}>
      <span className="set-row-label">{label}</span>
      {node}
    </label>
  )
  /* 이름을 위에 두는 줄 — 칸이 여럿이라 한 줄에 이름과 함께 못 서는 자리(신규 진입 시간). */
  const stacked = (label: string, node: React.ReactNode) => (
    <div className="set-row set-row-stack" key={label}>
      <span className="set-row-label">{label}</span>
      {node}
    </div>
  )

  const select = (value: string, list: string[], set: (v: string) => void, label: string) => (
    <select className="control" value={value} aria-label={label} onChange={(e) => set(e.target.value)}>
      {/* 저장된 값이 비어 있으면 **빈 채로** 보입니다 — 목록 첫 값이 대신 서면
          고르지 않은 값이 고른 것처럼 읽힙니다. 다시 비우는 선택지는 아닙니다. */}
      {value === '' && !list.includes('') && (
        <option value="" disabled>
          —
        </option>
      )}
      {list.map((item) => (
        <option key={item} value={item}>
          {item}
        </option>
      ))}
    </select>
  )

  /* 수 칸. 못 받는 값이면 테두리가 그 칸을 가리키고 까닭은 칸 아래 한 줄이
     말합니다(주문 화면의 가격 칸과 같은 규칙). 값을 조용히 되돌리지 않습니다 —
     되돌리면 틀린 값이 정상인 얼굴로 남습니다. */
  const unit = (
    name: string,
    key: AuxNumber,
    suffix: string,
    label: string,
    /* 비워 둘 수 있는 칸(추적 청산·연속 손실)의 빈칸 글자. `field` 는 서버가 이
       칸에 단 말을 찾는 이름입니다 — 화면 판정이 없을 때만 그 말이 칸 아래 섭니다.
       받는 값의 규칙(정수·비움)은 `AUX_NUMBERS` 가 정합니다. */
    extra?: { placeholder?: string; field?: string },
  ) => {
    const raw = draft.aux[key] ?? ''
    /* 금액 칸(하루 손실 한도·증거금 예산)은 **보이기만** 쉼표를 답니다 — 설정에 담는
       값은 쉼표를 뗀 숫자 글자라 판정·저장은 그대로입니다. */
    const money = MONEY_KEYS.includes(key)
    const digits = currencyDigits(currencyCode(currency)) ?? 2
    const value = money ? limitTyped(raw, digits) : raw
    const set = (v: string) => setAux({ [key]: v })
    const check = auxCheck(draft.aux, key)
    const why = check?.text ?? null
    const server = !why && extra?.field ? problemOf(extra.field) : null
    const whyId = `set-why-${name}`
    return (
      <span className="set-bad">
        <span className="set-unit">
          {/* 붉은 테는 **틀린 값**에만 둡니다. 비워 둔 필수 칸은 아래 줄(경고색)이
              할 일을 말하고, 칸은 틀린 것이 아니라 테를 두르지 않습니다. */}
          <input
            className={`control set-num${check?.kind === 'wrong' ? ' is-bad' : ''}`}
            inputMode="numeric"
            value={value}
            placeholder={extra?.placeholder}
            aria-label={label}
            aria-invalid={why ? true : undefined}
            aria-describedby={why || server ? whyId : undefined}
            onChange={(e) => {
              if (!money) {
                set(e.target.value)
                return
              }
              /* 쉼표를 다시 달아도 커서는 고치던 자리에 머뭅니다 — 커서 앞의 숫자 수를
                 세어 두었다가 새 글자에서 같은 수만큼 지난 곳에 둡니다. */
              const input = e.target
              const before = input.value.slice(0, input.selectionStart ?? input.value.length)
              const count = (before.match(/[0-9.]/g) ?? []).length
              const shown = limitTyped(input.value, digits)
              caretAfterRender.current = { input, at: caretAfter(shown, count) }
              set(shown.replace(/,/g, ''))
            }}
          />
          <span className="set-unit-mark">{suffix}</span>
        </span>
        {check && (
          <span id={whyId} className={whyTone(check.kind)}>
            {check.text}
          </span>
        )}
        {server && <span id={whyId}>{server}</span>}
      </span>
    )
  }

  /* 거리 칸(손절·익절·추적 청산) — 수 칸 뒤에 단위 셀렉트입니다. 단위를 바꾸면 그
     단위의 범위로 곧바로 판정합니다(`auxWhy`). ATR 배를 고르면 칸 옆에 무엇의 배수인지
     적습니다. 서버 말은 값 칸·단위 칸 어느 쪽에 달려도 그 칸 아래 섭니다. */
  const distance = (
    name: string,
    key: 'stopTicks' | 'takeTicks' | 'trailTicks',
    unitKey: 'stopUnit' | 'takeUnit' | 'trailUnit',
    label: string,
    extra?: { placeholder?: string },
  ) => {
    const value = draft.aux[key] ?? ''
    const chosen = exitUnitOf(draft.aux[unitKey])
    const check = auxCheck(draft.aux, key)
    const why = check?.text ?? null
    const server = !why ? (problemOf(`aux.${key}`) ?? problemOf(`aux.${unitKey}`)) : null
    const whyId = `set-why-${name}`
    return (
      <span className="set-bad">
        <span className="set-unit">
          <input
            className={`control set-num set-distance${check?.kind === 'wrong' ? ' is-bad' : ''}`}
            inputMode={chosen === 'tick' ? 'numeric' : 'decimal'}
            value={value}
            placeholder={extra?.placeholder}
            aria-label={label}
            title={chosen === 'price' ? '평균가에서 떨어진 가격 거리(포인트)' : undefined}
            aria-invalid={why ? true : undefined}
            aria-describedby={why || server ? whyId : undefined}
            onChange={(e) => setAux({ [key]: e.target.value })}
          />
          <select
            className="control set-distance-unit"
            value={chosen}
            aria-label={`${label} 단위`}
            onChange={(e) => setAux({ [unitKey]: e.target.value })}
          >
            {EXIT_UNITS.map((one) => (
              <option key={one.id} value={one.id}>
                {one.label}
              </option>
            ))}
          </select>
          {/* 자리는 늘 잡아 둡니다 — ATR 배를 고른 줄만 칸이 밀리면 세 줄의 칸이 어긋납니다.
              값이 빈 칸은 그 청산을 쓰지 않으므로 ATR 도 쓰지 않습니다. 그때는 꼬리표를
              흐리게 둡니다. */}
          <span
            className={`set-unit-note${chosen === 'atr' ? '' : ' is-off'}${value.trim() === '' ? ' is-idle' : ''}`}
            aria-hidden={chosen !== 'atr'}
          >
            ATR(14)
          </span>
        </span>
        {check && (
          <span id={whyId} className={whyTone(check.kind)}>
            {check.text}
          </span>
        )}
        {server && <span id={whyId}>{server}</span>}
      </span>
    )
  }

  /* 실행 조건 칸(분·시각·봉·번). 판정은 `filterWhy` 하나이고, 화면 판정이 없을 때만 서버
     말이 칸 아래 섭니다. 비워 둘 수 있는 칸은 자리표시가 그 뜻을 말합니다. */
  const filterInput = (
    key: AuxFilter,
    label: string,
    options: { placeholder?: string; clock?: boolean; className?: string; disabled?: boolean },
  ) => {
    const why = filterWhy(draft.aux, key)
    return (
      <input
        className={`control ${options.className ?? 'set-filter-num'}${why ? ' is-bad' : ''}`}
        inputMode={options.clock ? 'text' : 'numeric'}
        value={draft.aux[key] ?? ''}
        placeholder={options.placeholder}
        aria-label={label}
        aria-invalid={why ? true : undefined}
        disabled={options.disabled}
        onChange={(e) => setAux({ [key]: e.target.value })}
      />
    )
  }
  /* 실행 조건 칸 아래 판정 줄 — 화면 판정, 없으면 서버 말. */
  const filterSaid = (keys: AuxFilter[]) => {
    for (const key of keys) {
      const why = filterWhy(draft.aux, key)
      if (why) return <span className="set-bad-why">{why}</span>
    }
    for (const key of keys) {
      const server = problemOf(`aux.${key}`)
      if (server) return server
    }
    return null
  }

  /* 고르는 칸 + 그 칸 아래 판정 줄. 화면 판정(`why`)이 먼저이고, 없으면 서버가
     그 칸에 단 말입니다 — 같은 말이 한 칸 아래 두 번 서지 않습니다. */
  const picked = (node: React.ReactNode, name: string, why: string | null, field: string, kind: WhyKind) => {
    const server = why ? null : problemOf(field)
    return (
      <span className="set-bad" key={name}>
        {node}
        {why && <span className={whyTone(kind)}>{why}</span>}
        {server}
      </span>
    )
  }

  return {
    accordion,
    field,
    stacked,
    select,
    unit,
    distance,
    filterInput,
    filterSaid,
    picked,
  }
}
