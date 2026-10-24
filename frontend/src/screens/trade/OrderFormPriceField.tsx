import { useEffect, useState } from 'react'
import { fractionText, priceHint, readPrice, stepPrice } from '../../lib/number'

/* 가격 칸.
 *
 * 값은 숫자로 들고 다니지만 칸에는 그 품목이 부르는 대로 보여야 합니다 —
 * 425.9 로 채워 두면 아래 표의 425.90 과 같은 값인데 다른 값처럼 읽힙니다.
 * 그렇다고 매번 다듬어 넣으면 「425.」 처럼 치는 중인 글자가 끊깁니다.
 * 그래서 치는 동안은 친 그대로 두고, 밖에서 값이 바뀌거나 칸을 떠날 때만
 * 다듬습니다.
 *
 * **분수로 부르는 품목에서는 글자 칸입니다.** 숫자 칸은 `99'30` 을 못 받습니다 —
 * `'` 를 치는 순간 칸이 값을 통째로 비웁니다. 대신 숫자 칸이 주던 화살표
 * 증감을 직접 답니다. 한 번에 그 품목의 호가단위 하나입니다.
 *
 * **분수 칸은 칸을 떠날 때 값이 확정됩니다.** 십진 칸은 치는 대로 값이
 * 가는데, 그건 친 글자의 앞부분이 겨냥한 값 근처라서 그렇습니다 — 425.90 을
 * 치는 도중의 425 는 목표에서 1 도 안 떨어져 있습니다. 분수는 다릅니다:
 * `99'32` 를 치는 도중의 `99'3` 은 99.09 라, 겨냥한 100 언저리에서 27/32
 * 포인트 떨어진 **다른 값**입니다. 그 잔재가 주문에 남으면 안 됩니다.
 *
 * 못 읽은 글자는 칸에 그대로 두고 이유도 그대로 둡니다. **값은 마지막으로
 * 받아들인 것 그대로이고 이유 줄도 안 지웁니다** — 지우면 틀린 값이 정상인
 * 얼굴로 남습니다. 그동안 실행 단추는 막힙니다. */
export function PriceField({
  id,
  label,
  value,
  decimals,
  fraction,
  tick,
  note,
  noteWhy,
  signed,
  step,
  disabled,
  placeholder,
  onChange,
  onBlocked,
}: {
  /** 이유 줄과 이어 붙일 이름. 폼 안에서 겹치지 않아야 합니다. */
  id: string
  label: string
  value: number | null
  decimals: number
  /** 분수로 적는 품목이면 그 분모. 있으면 칸이 분수 표기를 주고받습니다. */
  fraction?: number | null
  /** 그 품목의 호가단위. 분수 품목의 화살표 한 단이 이 값입니다. */
  tick?: number | null
  /** 값과 상관없이 늘 서는 한 줄. 지금은 **호가단위를 모를 때** 씁니다 —
   *  못 받은 것을 말하지 않으면 사용자가 지금 눈금을 거래소 눈금으로 읽습니다. */
  note?: string | null
  /** 그 한 줄이 선 까닭. **서버가 낸 문장 그대로**이고, 칸이 좁아 본문에
   *  세우지 못해 마우스를 올리면 보입니다. */
  noteWhy?: string | null
  /** 값이 음수로 설 수 있는 종목인가(스프레드). 칸이 음수를 받을지, 화살표가
   *  0 아래로 갈지를 정합니다. */
  signed: boolean
  /** 호가단위를 모르는 시장(국내)에서 숫자 칸이 쓰는 증감 폭. */
  step: number
  disabled: boolean
  placeholder?: string
  onChange: (next: number | null) => void
  /** 이 칸이 못 읽은 글자를 안고 있는지. 폼이 실행 단추를 막는 데 씁니다. */
  onBlocked: (blocked: boolean) => void
}) {
  const format = (v: number | null) =>
    v === null ? '' : fraction ? fractionText(v, fraction) : v.toFixed(decimals)
  const [text, setText] = useState(() => format(value))
  /* 못 받은 이유. 받은 순간에만 서 있습니다. */
  const [reason, setReason] = useState<string | null>(null)

  /* 밖에서 값이 바뀌면 칸도 따라갑니다. **글자가 아니라 값으로 견줍니다** —
     같은 수를 적는 방식이 둘이라(`99'30` 과 `99.9375`) 글자로 비교하면 치는
     족족 다시 씌워집니다. */
  useEffect(() => {
    setText((current) => {
      const read = readPrice(current, fraction, tick, signed)
      return read.state === 'ok' && read.value === value ? current : format(value)
    })
    setReason(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, decimals, fraction, tick])

  /* 못 읽은 글자를 안고 있는 동안은 폼이 실행을 막습니다. 칸이 사라질 때는
     막을 이유도 사라지므로 풀어 줍니다 — 주문유형을 바꿔 스탑가격 칸이
     없어졌는데 그 칸 때문에 못 내는 상태가 남으면 안 됩니다. */
  useEffect(() => {
    onBlocked(reason !== null)
    return () => onBlocked(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reason])

  /** 분수 칸은 칸을 떠날 때 확정합니다. 십진 칸만 치는 대로 값이 갑니다. */
  const live = !fraction

  const apply = (raw: string) => {
    setText(raw)
    const read = readPrice(raw, fraction, tick, signed)
    setReason(read.state === 'bad' ? read.reason : null)
    if (!live) return
    if (read.state === 'ok') onChange(read.value)
    else if (read.state === 'empty') onChange(null)
  }

  /* 칸을 떠날 때. 읽히면 그때 값이 되고, 못 읽으면 **값도 이유도 그대로**
     둡니다 — 반쯤 친 글자(`99'`)도 떠나는 순간에는 못 읽은 것입니다. */
  const settle = () => {
    const read = readPrice(text, fraction, tick, signed)
    if (read.state === 'ok') {
      setText(format(read.value))
      setReason(null)
      onChange(read.value)
      return
    }
    if (read.state === 'empty') {
      setText('')
      setReason(null)
      onChange(null)
      return
    }
    /* 못 읽은 글자는 십진 칸에서도 그대로 둡니다. 조용히 되돌리면 틀린 값이
       정상인 얼굴로 남고, 그동안 실행 단추는 막혀 있습니다. */
    setReason(read.state === 'bad' ? read.reason : fraction ? priceHint(fraction, tick) : null)
  }

  /* 화살표 증감. 눈금을 모르는 품목에서는 분모 한 칸이 한 단입니다 — 화면이
     적을 수 있는 가장 잔 자리라, 그보다 잘게 움직이면 값이 안 바뀌어 보입니다. */
  const bump = (direction: 1 | -1) => {
    const grid = tick && tick > 0 ? tick : fraction ? 1 / fraction : null
    if (grid === null) return
    const read = readPrice(text, fraction, tick, signed)
    /* 치는 중이면 마지막으로 받은 값에서 셉니다. 빈 칸에서는 셀 자리가 없어
       아무 일도 하지 않습니다 — 없던 가격이 화살표 한 번에 생기면 안 됩니다. */
    const from = read.state === 'ok' ? read.value : value
    if (from === null) return
    const next = stepPrice(from, grid, direction, signed)
    setText(format(next))
    setReason(null)
    onChange(next)
  }

  const why = `${id}-why`
  return (
    <label className="order-field">
      <span className="control-label">{label}</span>
      <input
        className={`control${reason ? ' is-bad' : ''}`}
        type={fraction ? 'text' : 'number'}
        inputMode={fraction ? undefined : 'decimal'}
        /* 화살표 한 번은 **그 품목의 호가단위**입니다. 품목과 무관한 고정값으로
           두면 미니 S&P 500(0.25)에서 `6850.30` 처럼 낼 수 없는 값이 나오고,
           바로 옆 호가 사다리는 품목 호가단위로 서 있어 둘이 어긋납니다.
           마스터가 호가단위를 안 주는 시장(국내)에서만 넘겨받은 값을 씁니다. */
        step={fraction ? undefined : tick && tick > 0 ? tick : step}
        /* 글자 칸이지만 하는 일은 숫자 칸과 같습니다. 화살표로 오르내리는
           값이라고 적어 두어야 화면을 읽어 주는 도구가 그렇게 안내합니다. */
        role={fraction ? 'spinbutton' : undefined}
        aria-valuenow={fraction && value !== null ? value : undefined}
        aria-valuetext={fraction && value !== null ? text : undefined}
        value={text}
        disabled={disabled}
        placeholder={placeholder}
        aria-invalid={reason ? true : undefined}
        aria-describedby={reason ? why : undefined}
        onChange={(event) => apply(event.target.value)}
        onKeyDown={
          fraction
            ? (event) => {
                if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
                event.preventDefault()
                bump(event.key === 'ArrowUp' ? 1 : -1)
              }
            : undefined
        }
        onBlur={settle}
      />
      {/* 왜 안 받았는지 그 자리에서 말합니다. 값만 조용히 안 바뀌면 자기가
          잘못 친 줄 모르고 그대로 냅니다.

          **고쳐야 할 것이 먼저입니다.** 안내 한 줄과 겹치면 지금 손봐야 하는
          쪽이 그 자리를 갖습니다 — 두 줄을 겹쳐 세우면 칸 밑이 두 겹이 되고,
          급한 쪽이 아래로 밀립니다. */}
      {reason ? (
        <span className="order-limit" id={why}>
          {reason}
        </span>
      ) : (
        note && (
          <span className="order-limit order-note" title={noteWhy ?? undefined}>
            {note}
          </span>
        )
      )}
    </label>
  )
}
