import { useMemo, useState } from 'react'
import { currencyDigits, limitTyped } from '../../lib/number'
import { limitValue, limitWhy } from '../../data/strategyChecks'
import { saveLimits, type LimitAxis, type Limits } from '../../data/strategyLimits'
import { overseasCurrencies, useTimetable } from '../../data/session'
import { limitShown } from './strategyRunUtils'

/* 계좌 손실 한도를 바꾸는 창.
 *
 * 칸은 **머리에 선 값**으로 채워 엽니다. 저장은 그 축의 두 시장을 함께 보내므로,
 * 손대지 않은 칸도 지금 값 그대로 실려 갑니다. 비운 칸은 「걸지 않음」입니다. 다른
 * 축은 보내지 않아 그대로입니다. */
export function LimitsForm({
  axis,
  currencies,
  start,
  saving,
  onSaving,
  onClose,
}: {
  /** 고치는 계좌 축. 창을 열 때 정해 두고 바꾸지 않습니다. */
  axis: LimitAxis
  /** 머리 줄에 선 해외 통화(달러와, 한도·실행이 있는 통화). 창의 줄도 이것으로 엽니다. */
  currencies: string[]
  start: Limits
  saving: boolean
  onSaving: (saving: boolean) => void
  onClose: () => void
}) {
  /* 줄의 통화 — 국내(원) 다음 해외 통화들. 「통화 더하기」로 늘고, 늘린 줄은 저장 전까지
     이 창에만 있습니다. */
  const [codes, setCodes] = useState<string[]>(() => ['KRW', ...currencies])
  const [text, setText] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      ['KRW', ...currencies].map((code) => {
        const value = start[code] ?? null
        return [code, value === null ? '' : limitShown(value, '', currencyDigits(code))]
      }),
    ),
  )
  const [adding, setAdding] = useState(false)
  const timetable = useTimetable()
  /* 더할 수 있는 통화 — 시간표 품목의 통화 가운데 아직 줄이 없는 것. */
  const addable = useMemo(
    () => overseasCurrencies().filter((code) => !codes.includes(code)),
    // 시간표가 오면 다시 셉니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [codes, timetable],
  )
  /* 서버가 거절한 까닭. 칸을 짚은 말은 그 칸 아래, 나머지는 창 아래입니다.
     칸을 고치면 그 칸의 서버 말은 걷습니다 — 고친 값에 대한 답이 아닙니다. */
  const [said, setSaid] = useState<{ fields: Partial<Record<string, string>>; message: string | null }>({
    fields: {},
    message: null,
  })
  const bad = Object.fromEntries(codes.map((code) => [code, limitWhy(text[code] ?? '')]))
  const invalid = codes.some((code) => bad[code] !== null)

  async function save() {
    if (invalid || saving) return
    onSaving(true)
    setSaid({ fields: {}, message: null })
    /* 그 축의 통화 전부를 보냅니다 — 안 보낸 통화는 서버가 「안 건 것」으로 지웁니다.
       창에 줄이 없는 통화도 걸려 있던 값 그대로 실어 풀리지 않게 합니다. */
    const values: Limits = { ...start }
    for (const code of codes) values[code] = limitValue(text[code] ?? '')
    const result = await saveLimits(values, axis)
    onSaving(false)
    if (result.ok) onClose()
    else setSaid({ fields: result.fields, message: result.message })
  }

  return (
    <form
      className="run-add"
      onSubmit={(e) => {
        e.preventDefault()
        void save()
      }}
    >
      {codes.map((code) => {
        const why = bad[code] ?? said.fields[code] ?? null
        const whyId = `run-limits-why-${code}`
        const won = code === 'KRW'
        return (
          <div key={code}>
            <label className="run-add-row">
              <span className="run-add-label">{won ? '국내' : `해외 ${code}`}</span>
              <span className="run-limits-unit">
                <input
                  className={`control run-num${why !== null ? ' is-bad' : ''}`}
                  value={text[code] ?? ''}
                  inputMode="decimal"
                  placeholder="걸지 않음"
                  disabled={saving}
                  aria-label={won ? '국내 하루 손실 한도' : `해외 ${code} 하루 손실 한도`}
                  aria-invalid={why !== null || undefined}
                  aria-describedby={why !== null ? whyId : undefined}
                  onChange={(e) => {
                    const next = limitTyped(e.target.value, currencyDigits(code) ?? 2)
                    setText((now) => ({ ...now, [code]: next }))
                    setSaid((now) => ({ ...now, fields: { ...now.fields, [code]: undefined } }))
                  }}
                />
                <span className="set-unit-mark">{won ? '원' : code}</span>
              </span>
            </label>
            {why !== null && (
              <p className="add-field-why" id={whyId}>
                {why}
              </p>
            )}
          </div>
        )
      })}
      {/* 통화 더하기 — 시간표 품목의 통화 가운데 고릅니다. 고르면 그 줄이 섭니다. */}
      {addable.length > 0 &&
        (adding ? (
          <label className="run-add-row">
            <span className="run-add-label">통화</span>
            <select
              className="control"
              value=""
              aria-label="더할 통화"
              disabled={saving}
              onChange={(e) => {
                const code = e.target.value
                if (!code) return
                setCodes((now) => [...now, code])
                setText((now) => ({ ...now, [code]: '' }))
                setAdding(false)
              }}
            >
              <option value="">고르기</option>
              {addable.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <button type="button" className="run-limits-add" disabled={saving} onClick={() => setAdding(true)}>
            통화 더하기
          </button>
        ))}
      <p className="run-limits-hint">
        하루 손실이 이만큼에 닿으면 그 통화로 셈하는 {axis === 'real' ? '실전' : '모의'} 계좌 실행이 모두 멈춥니다.
        비우면 걸지 않습니다
      </p>
      {said.message !== null && <p className="run-limits-fail">{said.message}</p>}
      <div className="run-add-acts">
        <button type="button" className="btn btn-quiet" aria-disabled={saving} onClick={() => !saving && onClose()}>
          그만두기
        </button>
        <button type="submit" className="btn btn-primary" aria-disabled={invalid || saving}>
          {saving ? '저장하는 중' : '저장'}
        </button>
      </div>
    </form>
  )
}