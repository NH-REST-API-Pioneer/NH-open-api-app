import { useEffect, useState } from 'react'
import { LOCKED_TITLE } from './strategySettingsUtils'

/** 매개변수 칸 하나. **친 글자는 칸이 들고 있고**, 수로 읽히면 수로, 아니면 글자로
 *  조건에 넘깁니다 — 「2.0」을 치는 중에 「2」로 바꿔 쓰지 않으면서, 저장된 값(수)과
 *  같은 수를 치면 조건도 그대로입니다. 밖에서 값이 바뀌면(잠긴 칸이 왼쪽을 따름)
 *  칸 글자도 따라갑니다. */
export function ParamInput({
  label,
  value,
  float,
  bad,
  locked,
  name,
  onChange,
}: {
  label: string
  value: number | string | undefined
  float: boolean
  bad: boolean
  locked: boolean
  name: string
  onChange: (next: number | string) => void
}) {
  const shownValue = value === undefined ? '' : String(value)
  const [text, setText] = useState(shownValue)
  useEffect(() => {
    if (text.trim() === '' || Number(text) !== Number(shownValue)) setText(shownValue)
    // 칸 글자는 값이 밖에서 바뀔 때만 맞춥니다. 치는 중의 글자는 그대로 둡니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shownValue])
  return (
    <label className="set-param" title={locked ? LOCKED_TITLE : undefined}>
      <span className="set-param-label">{label}</span>
      <input
        className={`control set-param-input${bad ? ' is-bad' : ''}${locked ? ' is-locked' : ''}`}
        inputMode={float ? 'decimal' : 'numeric'}
        value={locked ? shownValue : text}
        readOnly={locked}
        aria-readonly={locked || undefined}
        aria-invalid={bad || undefined}
        aria-label={name}
        onChange={(event) => {
          if (locked) return
          const next = event.target.value
          setText(next)
          const number = Number(next)
          onChange(next.trim() !== '' && Number.isFinite(number) ? number : next)
        }}
      />
    </label>
  )
}
