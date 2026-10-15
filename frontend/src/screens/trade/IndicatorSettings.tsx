import { useEffect, useRef, useState } from 'react'
import {
  DEFAULT_LINE_SIZE,
  INDICATOR_DEFS,
  LINE_SIZES,
  PALETTE,
  defaultSetting,
  nextColor,
  validParam,
  type IndicatorDef,
  type IndicatorSetting,
  type IndicatorSettings,
} from './chartIndicators'

/* 지표 설정 팝오버.
 *
 * 왼쪽이 목록, 오른쪽이 고른 지표의 설정입니다. 목록의 동그라미가 켜고 끄는
 * 자리이고, 이름을 누르면 설정만 보입니다 — 이름을 눌렀는데 켜지면 설정을
 * 보려다 차트에 선이 생깁니다.
 *
 * 저장 단추가 없습니다. 바꾸는 즉시 차트에 반영되어, 값을 만지면서 결과를
 * 봅니다. 그래서 팝오버는 뒤를 잠그지 않습니다.
 *
 * 색은 팔레트에서만 고릅니다. 자유 색을 열면 봉과 같은 빨강·파랑을 골라
 * 선이 봉에 묻히는 일이 생깁니다.
 */

interface Props {
  settings: IndicatorSettings
  onChange: (name: string, next: IndicatorSetting) => void
  onClose: () => void
}

/* 색·굵기 고르기. 칩을 누르면 그 자리에 뜹니다. */
function StylePicker({
  color,
  size,
  onPick,
}: {
  color: string
  size: number
  onPick: (color: string, size: number) => void
}) {
  return (
    <div className="ind-picker" role="dialog" aria-label="선 색과 굵기">
      <p className="ind-picker-title">색</p>
      {/* 열이 색상, 행이 명도입니다. 위가 진하고 아래가 옅습니다. */}
      <div className="ind-swatches">
        {PALETTE[0].map((_, shade) =>
          PALETTE.map((row, hue) => {
            const hex = row[shade]
            return (
              <button
                key={`${hue}-${shade}`}
                type="button"
                className="ind-swatch"
                aria-label={`색 ${hue + 1}-${shade + 1}`}
                aria-pressed={hex === color}
                style={{ background: hex }}
                onClick={() => onPick(hex, size)}
              />
            )
          }),
        )}
      </div>
      <p className="ind-picker-title">굵기</p>
      <div className="ind-sizes">
        {LINE_SIZES.map((px) => (
          <button
            key={px}
            type="button"
            className="ind-size"
            aria-pressed={px === size}
            onClick={() => onPick(color, px)}
          >
            <span className="ind-size-line" style={{ height: px, background: color }} />
            {px}px
          </button>
        ))}
      </div>
    </div>
  )
}

/* 선 하나의 색·굵기 칩. 누르면 고르기가 뜹니다. */
function StyleChip({
  color,
  size,
  label,
  onPick,
}: {
  color: string
  size: number
  label: string
  onPick: (color: string, size: number) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false)
    }
    /* Esc 는 고르기만 닫습니다. 팝오버까지 닫히면 고르던 자리를 잃습니다. */
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey, true)
    }
  }, [open])

  return (
    <div className="ind-chip-wrap" ref={ref}>
      <button
        type="button"
        className="ind-chip"
        aria-label={`${label} 선 색과 굵기`}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="ind-chip-dot" style={{ background: color }} />
        {size}px
      </button>
      {open && (
        <StylePicker
          color={color}
          size={size}
          onPick={(nextColor, nextSize) => onPick(nextColor, nextSize)}
        />
      )}
    </div>
  )
}

/* 수치 하나. 0·음수·숫자 아닌 것은 받지 않고, 칸에 거부된 값이 남아 있음을
 * 테두리로 보입니다 — 조용히 이전 값으로 돌리면 왜 안 바뀌는지 알 수 없습니다. */
function ParamInput({
  value,
  label,
  integer,
  onCommit,
}: {
  value: number
  label: string
  integer: boolean
  onCommit: (next: number) => void
}) {
  const [text, setText] = useState(String(value))
  const [bad, setBad] = useState(false)

  useEffect(() => {
    setText(String(value))
    setBad(false)
  }, [value])

  const apply = (raw: string) => {
    setText(raw)
    const parsed = integer ? Number.parseInt(raw, 10) : Number(raw)
    const ok = raw.trim() !== '' && validParam(parsed) && (!integer || String(parsed) === raw.trim())
    setBad(!ok)
    if (ok && parsed !== value) onCommit(parsed)
  }

  return (
    <input
      className={`control ind-param${bad ? ' is-bad' : ''}`}
      type="number"
      inputMode={integer ? 'numeric' : 'decimal'}
      min={integer ? 1 : 0}
      step={integer ? 1 : 0.1}
      value={text}
      aria-label={label}
      aria-invalid={bad}
      onChange={(event) => apply(event.target.value)}
      onBlur={() => {
        if (bad) {
          setText(String(value))
          setBad(false)
        }
      }}
    />
  )
}

function Editor({
  def,
  setting,
  onChange,
}: {
  def: IndicatorDef
  setting: IndicatorSetting
  onChange: (next: IndicatorSetting) => void
}) {
  const setLine = (index: number, color: string, size: number) => {
    const lines = setting.lines.map((line, i) => (i === index ? { color, size } : line))
    onChange({ ...setting, lines })
  }
  const setParam = (index: number, value: number) => {
    const params = setting.params.map((p, i) => (i === index ? value : p))
    onChange({ ...setting, params })
  }
  const addLine = () => {
    if (!def.linePeriods || setting.params.length >= def.linePeriods.max) return
    /* 새 선은 가장 긴 기간의 두 배로 시작합니다. 같은 값으로 두면 기존 선에
       정확히 겹쳐 늘었는지 알 수 없습니다. */
    const longest = Math.max(...setting.params, 1)
    onChange({
      ...setting,
      params: [...setting.params, longest * 2],
      lines: [
        ...setting.lines,
        { color: nextColor(setting.lines.map((line) => line.color)), size: DEFAULT_LINE_SIZE },
      ],
    })
  }
  const removeLine = (index: number) => {
    if (setting.params.length <= 1) return
    onChange({
      ...setting,
      params: setting.params.filter((_, i) => i !== index),
      lines: setting.lines.filter((_, i) => i !== index),
    })
  }
  const reset = () => onChange({ ...defaultSetting(def), on: setting.on })

  return (
    <div className="ind-editor">
      <p className="ind-editor-title">{def.label}</p>
      <p className="ind-editor-desc">{def.description}</p>

      {def.linePeriods ? (
        <>
          <ul className="ind-rows">
            {setting.params.map((period, index) => (
              <li key={index} className="ind-row">
                <span className="ind-row-label">기간{index + 1}</span>
                <StyleChip
                  color={setting.lines[index].color}
                  size={setting.lines[index].size}
                  label={`기간${index + 1}`}
                  onPick={(color, size) => setLine(index, color, size)}
                />
                <ParamInput
                  value={period}
                  label={`기간${index + 1}`}
                  integer
                  onCommit={(next) => setParam(index, next)}
                />
                {/* 마지막 하나는 못 뺍니다. 선이 없는 지표는 끈 것과 같은데,
                    끄는 자리는 목록의 동그라미입니다. */}
                {setting.params.length > 1 && (
                  <button
                    type="button"
                    className="btn btn-quiet ind-remove"
                    aria-label={`기간${index + 1} 빼기`}
                    onClick={() => removeLine(index)}
                  >
                    ✕
                  </button>
                )}
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="btn btn-quiet ind-add"
            disabled={setting.params.length >= def.linePeriods.max}
            onClick={addLine}
          >
            ＋ 선 추가
          </button>
        </>
      ) : (
        <>
          {def.lines.length > 0 && (
            <ul className="ind-rows">
              {def.lines.map((name, index) => (
                <li key={name} className="ind-row">
                  <span className="ind-row-label">{name}</span>
                  <StyleChip
                    color={setting.lines[index].color}
                    size={setting.lines[index].size}
                    label={name}
                    onPick={(color, size) => setLine(index, color, size)}
                  />
                </li>
              ))}
            </ul>
          )}
          <ul className="ind-rows">
            {def.params.map((spec, index) => (
              <li key={spec.label} className="ind-row">
                <span className="ind-row-label">{spec.label}</span>
                <ParamInput
                  value={setting.params[index]}
                  label={spec.label}
                  integer={spec.integer !== false}
                  onCommit={(next) => setParam(index, next)}
                />
              </li>
            ))}
          </ul>
          <button type="button" className="btn btn-quiet ind-add" onClick={reset}>
            초기화
          </button>
        </>
      )}
    </div>
  )
}

export function IndicatorSettingsPopover({ settings, onChange, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [picked, setPicked] = useState('MA')
  const def = INDICATOR_DEFS.find((item) => item.name === picked) ?? INDICATOR_DEFS[0]

  /* 바깥을 누르거나 Esc 로 닫힙니다. 뒤를 잠그지는 않습니다 — 차트를 보면서
     값을 만지는 물건이라, 뒤가 잠기면 결과를 못 봅니다. */
  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose()
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [onClose])

  const group = (title: string, key: 'top' | 'bottom') => (
    <>
      <p className="ind-group">{title}</p>
      {INDICATOR_DEFS.filter((item) => item.group === key).map((item) => {
        const on = settings[item.name].on
        return (
          <div
            key={item.name}
            className="ind-item"
            aria-current={picked === item.name}
          >
            <button type="button" className="ind-item-name" onClick={() => setPicked(item.name)}>
              {item.label}
            </button>
            <button
              type="button"
              className="ind-item-check"
              role="switch"
              aria-checked={on}
              aria-label={`${item.label} ${on ? '끄기' : '켜기'}`}
              onClick={() => onChange(item.name, { ...settings[item.name], on: !on })}
            >
              {on ? '✓' : ''}
            </button>
          </div>
        )
      })}
    </>
  )

  return (
    <div className="ind-popover" role="dialog" aria-label="지표 설정" ref={ref}>
      <div className="ind-list">
        {group('상단 지표', 'top')}
        {group('하단 지표', 'bottom')}
      </div>
      <Editor
        key={def.name}
        def={def}
        setting={settings[def.name]}
        onChange={(next) => onChange(def.name, next)}
      />
    </div>
  )
}
