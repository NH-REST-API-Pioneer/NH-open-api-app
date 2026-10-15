import type { CSSProperties, ReactElement } from 'react'

/* 숫자를 그리는 규칙을 한곳에 모읍니다.
 *
 * - 모든 수치는 고정폭 숫자로 그립니다
 * - 소수점 위치를 열의 기준선으로 잡습니다
 * - 방향(상승·매수 / 하락·매도)을 색으로 나타낼 때는 부호를 함께 씁니다.
 *   색만으로 방향을 나타내지 않습니다
 */

/** 값이 음수로 설 수 있는 줄이면 부호 한 칸. **줄마다 종목이 다른 표**가
 *  이것을 묻습니다 — 서버가 종류를 안 준 줄은 0 이고, 그때는 부호가 설 일도
 *  없습니다(음수를 내는 것은 스프레드뿐입니다). */
export function signSpace(productKind?: string): 0 | 1 {
  return productKind === 'spread' ? 1 : 0
}

/** 소수부 칸 너비를 열 단위로 지정합니다. 열의 최대 자릿수를 넣습니다.
 *
 *  **분수로 적는 품목은 자릿수가 아니라 분모가 정합니다.** 값이 `99'30` 으로
 *  서는 자리에 소수 다섯 자리만큼 칸을 잡아 두면, 그 칸이 옆의 이름표를 밀어
 *  글자가 세로로 쪼개집니다. */
export function fracWidth(decimals: number, extra = 0, fraction?: number | null): CSSProperties {
  const ch = fraction ? fractionChars(fraction) + extra : decimals > 0 ? decimals + 1 + extra : extra
  return { '--frac-w': `${ch}ch` } as CSSProperties
}

/** 분수 표기가 `'` 뒤에서 **세는 단위**. 32분의 몇으로 적는 것이
 *  기본이고, 32보다 굵게 나뉘는 갈래(곡물 1/8)는 그 분모가 그대로 단위입니다. */
function fractionAxis(denominator: number): number {
  return denominator < 32 ? denominator : 32
}

/** 분수 표기에서 `'` 뒤에 오는 글자 수. 분모가 정합니다 —
 *  1/32 은 `'30` 셋, 1/64 은 `'30.5` 다섯, 1/256 은 `'30.125` 일곱입니다. */
function fractionChars(denominator: number): number {
  const axis = fractionAxis(denominator)
  const per = denominator / axis
  const head = String(axis - 1).length
  /* 축 아래로 더 잘게 나뉜 만큼이 소수로 이어집니다 — 1/2 은 `.5` 둘,
     1/4 은 `.25` 셋, 1/8 은 `.125` 넷입니다. */
  const tail = per > 1 ? 1 + Math.round(Math.log2(per)) : 0
  return 1 + head + tail
}

export const MINUS = '−'

/** 돈 칸에 적는 꼴. **천 단위 쉼표는 화면이 넣습니다** — 여덟 자리 숫자를 쉼표
 *  없이 두면 자릿수를 손으로 세야 하고, 0 하나가 더 붙은 것을 못 봅니다.
 *  담기는 값은 숫자만이라 적힌 쉼표는 서버로 따라가지 않습니다. */
export function moneyText(digits: string): string {
  return digits === '' ? '' : Number(digits).toLocaleString('ko-KR')
}

/** 돈 칸에서 받은 글자에서 숫자만 남깁니다. 붙여넣은 「50,000,000원」도 그대로
 *  받습니다 — 화면이 적어 준 꼴이 도로 들어오지 못하면 복사가 늘 오류가 됩니다. */
export function moneyDigits(text: string): string {
  return text.replace(/[^0-9]/g, '')
}

/* 음수를 못 받는 종목에서 음수를 쳤을 때. **무엇이 안 되는지만** 적습니다 —
   이 칸에서 사용자가 할 일은 부호를 지우는 것 하나입니다. */
const NO_NEGATIVE = '0보다 작은 값은 없습니다'

/** 분수 표기를 정수부와 나머지로 가릅니다. 소수점 대신 `'` 가 기준선이라,
 *  열에서 세로로 맞추는 자리는 그대로 씁니다. */
function fractionSplit(value: number, denominator: number): [string, string] {
  const text = fractionText(value, denominator)
  const mark = text.indexOf("'")
  return mark === -1 ? [text, ''] : [text.slice(0, mark), text.slice(mark)]
}

/** 값 하나를 화면에 서는 두 토막으로 — 부호 붙은 정수부와 소수(또는 분수)부.
 *
 *  `Num` 이 그리는 것과 **같은 글자**를 폭을 재는 쪽에도 주기 위해 따로 냅니다.
 *  두 곳이 따로 만들면 재는 글자와 서는 글자가 조용히 갈립니다. */
export function numberParts(
  value: number,
  decimals: number,
  fraction?: number | null,
  signed = false,
): [string, string] {
  const [int, frac] = fraction ? fractionSplit(value, fraction) : split(value, decimals)
  const sign = value < 0 ? MINUS : signed && value > 0 ? '+' : ''
  return [`${sign}${int}`, frac]
}

function split(value: number, decimals: number): [string, string] {
  const text = Math.abs(value).toLocaleString('ko-KR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
  const dot = text.indexOf('.')
  return dot === -1 ? [text, ''] : [text.slice(0, dot), text.slice(dot)]
}

/** 분수로 적는 값. **32분의 몇**으로 적고, 분모가 32보다 잘면 그 아래를 소수로
 *  잇습니다(예: 1/64 이면 `102'17.5`). 곡물처럼 분모가 8인 품목은 8분의 몇으로
 *  그대로 적습니다 — 거래소가 그렇게 부릅니다(`438'2`).
 *
 *  값은 그대로이고 **적는 방식만** 다릅니다. `102.546875` 와 `102'17.5` 는 같은
 *  수입니다. */
export function fractionText(value: number, denominator: number): string {
  const sign = value < 0 ? MINUS : ''
  const size = Math.abs(value)
  /* **먼저 분모 단위로 셉니다.** 정수부를 떼고 나머지를 반올림하면 32/32 처럼
     있을 수 없는 값이 나옵니다(99.996875 → 99'32). 단위로 세어 올림이 정수부로
     넘어가게 하면 100'00 이 됩니다. */
  const units = Math.round(size * denominator)
  const whole = Math.floor(units / denominator)
  const rest = units - whole * denominator
  /* 32 를 축으로 삼되, 분모가 8 인 갈래(곡물)는 8 을 그대로 축으로 씁니다. */
  const axis = fractionAxis(denominator)
  const per = denominator / axis
  const head = Math.floor(rest / per)
  const sub = rest - head * per
  /* 축 아래로 더 잘게 나뉜 만큼만 소수로 잇습니다 — 1/64 은 `.5`,
     1/128 은 `.25`·`.75`, 1/256 은 `.125` 단위입니다. */
  const tail = sub === 0 ? '' : (sub / per).toFixed(3).replace(/0+$/, '').slice(1)
  const padded = axis === 32 ? String(head).padStart(2, '0') : String(head)
  return `${sign}${whole.toLocaleString('ko-KR')}'${padded}${tail}`
}

/** 가격 칸에 친 글자를 읽은 결과.
 *
 *  **「아직 다 안 침」과 「틀림」을 가릅니다.** `99'` 는 이어서 칠 수 있는
 *  모양이라 아직 틀린 것이 아닙니다 — 한 글자 칠 때마다 칸이 빨개지면 정작
 *  틀렸을 때의 경고를 안 읽게 됩니다. */
export type PriceRead =
  /** 값으로 읽혔습니다. */
  | { state: 'ok'; value: number }
  /** 칸이 비었습니다 — 가격 없음입니다. */
  | { state: 'empty' }
  /** 이어 칠 수 있는 모양입니다. 값도 안 바꾸고 이유도 안 답니다. */
  | { state: 'typing' }
  /** 이 품목에서 있을 수 없는 값입니다. `reason` 을 칸 아래에 답니다. */
  | { state: 'bad'; reason: string }

/** 눈금을 사람이 읽는 꼴로. 0.00005 처럼 잔 값이 `5e-5` 로 새지 않게 합니다. */
function tickText(tick: number): string {
  const plain = String(tick)
  if (!plain.includes('e')) return plain
  return tick.toFixed(12).replace(/0+$/, '').replace(/\.$/, '')
}

/** 눈금 밖의 값에 붙는 까닭 — 「눈금에 맞춰 99'30 또는 99'30.5」.
 *
 *  **친 값의 실제 이웃 둘**(바로 아래·바로 위 눈금)을 그 품목이 적는 꼴로
 *  보입니다. 꼴 본보기(`…'30 · …'31`)는 정수부를 가려 친 값의 이웃이 아니라
 *  형식 예시로 읽히고, 이웃을 보이면 둘 중 하나를 그대로 골라 칠 수 있습니다.
 *  눈금을 이름(1/64·0.25)으로 부르지 않습니다 — 이웃 둘이 눈금을 이미 보이고,
 *  가격 칸의 다른 까닭(「99'31처럼 적습니다」)도 이름 대신 꼴로 말합니다.
 *  숫자 뒤에 토씨를 안 붙입니다 — 끝자리마다 「로/으로」가 갈려 어느 한쪽은
 *  틀립니다. */
function offTickReason(
  value: number,
  tick: number,
  denominator: number | null,
  signed: boolean,
): string {
  const below = stepPrice(value, tick, -1, signed)
  const above = stepPrice(value, tick, 1, signed)
  /* **부호는 화면이 쓰는 글리프로** 적습니다(`fractionText` 와 같은 글자) —
     본보기로 보인 값을 따라 치면 그대로 읽혀야 합니다. */
  const write = (neighbour: number) =>
    denominator
      ? fractionText(neighbour, denominator)
      : Math.abs(neighbour).toFixed(decimalsOf(tick)).replace(/^/, neighbour < 0 ? MINUS : '')
  return `눈금에 맞춰 ${write(below)} 또는 ${write(above)}`
}

/** 십진 눈금의 소수 자릿수. 이웃을 그 눈금의 자릿수로 적어야 `6850.5` 와 `6850.50`
 *  처럼 같은 값이 두 꼴로 서지 않습니다. */
function decimalsOf(tick: number): number {
  const text = tickText(tick)
  const dot = text.indexOf('.')
  return dot === -1 ? 0 : text.length - dot - 1
}

/** 그 품목의 눈금 위에 실제로 있는 값인지 봅니다. 없는 값을 받아 두면 칸에는
 *  다듬어진 값이 보이고 주문에는 친 값이 실려, 화면과 주문이 갈립니다.
 *
 *  **분모와 눈금은 다른 물음입니다.** 미 10년 국채는 1/128 로 적지만 한 눈금이
 *  2/128 이라 `99'30.25` 는 적을 수는 있어도 낼 수 없는 값입니다. */
function onTick(value: number, denominator: number, tick: number, signed: boolean): PriceRead {
  const units = value / tick
  if (Math.abs(units - Math.round(units)) > 1e-6) {
    return { state: 'bad', reason: offTickReason(value, tick, denominator, signed) }
  }
  /* 눈금 위의 값으로 맞춰 돌려줍니다 — `99'30` 과 `99.9375` 가 같은 수로
     들어와야, 밖에서 온 값과 칸의 글자를 값으로 견줄 수 있습니다. */
  return { state: 'ok', value: Number((Math.round(units) * tick).toPrecision(12)) }
}

/** 십진 품목의 눈금 검사. 분수 품목과 같은 물음이고 까닭도 같은 꼴입니다 —
 *  「눈금에 맞춰 6850.25 또는 6850.50」. */
function onDecimalTick(value: number, tick: number, signed: boolean): PriceRead {
  const units = value / tick
  if (Math.abs(units - Math.round(units)) > 1e-6) {
    return { state: 'bad', reason: offTickReason(value, tick, null, signed) }
  }
  return { state: 'ok', value: Number((Math.round(units) * tick).toPrecision(12)) }
}

/** 그 품목이 값을 적는 꼴 한 벌. 못 읽은 글자 아래에 본보기로 세웁니다 —
 *  **부호를 이름으로 부르지 않고 꼴을 보입니다.** */
export function priceHint(denominator: number, tick?: number | null): string {
  const grid = tick && tick > 0 ? tick : 1 / denominator
  return `${fractionText(stepPrice(100, grid, -1, false), denominator)}처럼 적습니다`
}

/** 가격 칸에 친 글자를 값으로 되돌립니다. 분모가 있으면 분수 표기(`99'30`)로,
 *  없으면 소수로 읽습니다.
 *
 *  **분수 품목에서도 소수로 친 값을 받습니다** — `99'30` 과 `99.9375` 는 같은
 *  수이고, 다른 곳에서 옮겨 온 값은 소수인 경우가 있습니다. 다만 그 품목의
 *  눈금에 없는 값은 받지 않습니다.
 *
 *  `tick` 은 그 품목의 호가단위입니다. 없으면 분모 한 칸을 눈금으로 봅니다 —
 *  화면이 적을 수 있는 가장 잔 자리입니다. */
export function readPrice(
  input: string,
  fraction?: number | null,
  tick?: number | null,
  /** 값이 음수로 설 수 있는 종목인가(스프레드). **거짓이면 음수를 안 받습니다** —
   *  선물·옵션에 음수 가격은 없고, 받아 두면 낼 수 없는 값이 주문 칸에 남습니다. */
  signed = false,
): PriceRead {
  /* 화면이 적는 부호 글리프(`−`)를 셈에 쓰는 빼기로 맞춥니다 — 화면에서
     복사한 값이 그대로 돌아오지 않으면 붙여넣기가 늘 오류가 됩니다. */
  const text = input.trim().replace(/−/g, '-')
  if (text === '') return { state: 'empty' }
  if (text === '-') return { state: 'typing' }

  if (!fraction) {
    /* 숫자 칸이라 브라우저가 글자를 이미 거릅니다. 치는 중인 `425.` 는
       425 로 읽혀 그대로 값이 됩니다. */
    const value = Number(text)
    if (!Number.isFinite(value)) return { state: 'typing' }
    if (!signed && value < 0) return { state: 'bad', reason: NO_NEGATIVE }
    /* 눈금을 아는 품목이면 십진도 눈금 위여야 합니다 — 미니 S&P 500 은 한 단이
       0.25 라 `6850.30` 은 낼 수 없는 값입니다. 마스터가 호가단위를 안 주는
       시장(국내)에서는 잴 자가 없어 그대로 받습니다. */
    return tick && tick > 0 ? onDecimalTick(value, tick, signed) : { state: 'ok', value }
  }

  /* 화면이 천 단위 쉼표를 넣고, 옮겨 온 글자는 `'` 가 ′ 나 ’ 로 오기도
     합니다. 읽기 전에 한 벌로 맞춥니다 — 화면에서 복사한 값이 그대로 돌아오지
     않으면 붙여넣기가 늘 오류가 됩니다. */
  const cleaned = text.replace(/,/g, '').replace(/[′’‘`´]/g, "'")
  if (/^-?\d+['.]$|^-?\d+'\d+\.$/.test(cleaned)) return { state: 'typing' }

  const grid = tick && tick > 0 ? tick : 1 / fraction
  /* **`'` 뒤에 서는 수의 상한은 분모가 아니라 축입니다.** 1/64·1/128·1/256
     품목도 32분의 몇으로 적으므로 `99'40` 은 어느 갈래에서도 없는 값입니다. */
  const axis = fractionAxis(fraction)
  /* **부호는 값 전체에 걸립니다** — 「−1'16」은 −(1 + 16/32)입니다. 정수부에만
     붙이면 소수부가 부호 반대쪽으로 더해져 −0.5 가 됩니다. 적는 쪽(`fractionText`)이
     크기와 부호를 갈라 적으므로 읽는 쪽도 같게 가릅니다. */
  const marked = /^(-?)(\d+)'(\d+)(?:\.(\d+))?$/.exec(cleaned)
  if (marked) {
    const head = Number(marked[3])
    if (head >= axis) {
      return { state: 'bad', reason: `0부터 ${axis - 1}까지입니다` }
    }
    const sub = marked[4] ? Number(`0.${marked[4]}`) : 0
    const size = Number(marked[2]) + (head + sub) / axis
    if (marked[1] && !signed) return { state: 'bad', reason: NO_NEGATIVE }
    return onTick(marked[1] ? -size : size, fraction, grid, signed)
  }
  if (/^-?\d+(?:\.\d+)?$/.test(cleaned)) {
    const value = Number(cleaned)
    if (!signed && value < 0) return { state: 'bad', reason: NO_NEGATIVE }
    return onTick(value, fraction, grid, signed)
  }

  /* 부호는 이름으로 부르지 않고 본보기로 가르칩니다. 본보기는 그 품목이 실제로
     낼 수 있는 값입니다 — 눈금에 없는 꼴을 보이면 따라 친 값이 다시 거부됩니다. */
  return { state: 'bad', reason: priceHint(fraction, grid) }
}

/** 화살표 한 번에 값이 움직이는 폭. **그 품목의 눈금 위에서** 셉니다.
 *
 *  눈금에 없는 값에서 눌렀으면 **누른 방향의 바로 다음 눈금**입니다 — 한 단을
 *  더해 버리면 그 사이의 눈금 하나를 건너뛰어, 화살표로는 닿지 못하는 값이
 *  생깁니다. */
export function stepPrice(
  value: number,
  tick: number,
  direction: 1 | -1,
  /** 값이 음수로 설 수 있는 종목인가(스프레드). 거짓이면 0 에서 멈춥니다. */
  signed = false,
): number {
  const raw = value / tick
  const nearest = Math.round(raw)
  /* 나눗셈에 자릿수 찌꺼기가 남으므로 「눈금 위인가」를 자로 재지 않고
     가까운 눈금과의 거리로 봅니다. */
  const onTick = Math.abs(raw - nearest) < 1e-6
  const units = onTick ? nearest + direction : direction > 0 ? Math.ceil(raw) : Math.floor(raw)
  /* **0 아래로는 값이 음수로 서는 종목에서만** 갑니다. 스프레드는 두 만기의
     차라 음수가 정상이고 눈금도 양수 쪽과 같아, 0 에서 막으면 화살표로 닿지
     못하는 값이 생깁니다. 선물·옵션에는 음수 가격이 없어 0 에서 멈춥니다. */
  if (!signed && units < 0) return 0
  return Number((units * tick).toPrecision(12))
}

/** 방향 값의 색 이름 — 오른 것은 `up`, 내린 것은 `down`, 0 은 **빈 문자열**입니다.
 *
 *  0 을 흐리게 하지 않습니다. 손익 0 은 본전이고 증거금 0 은 안 묶인 것이라
 *  「그만큼이다」를 말하는 값입니다 — 값이 없는 자리(「—」)와 같은 얼굴로 두면
 *  본전과 모름이 한 얼굴이 됩니다. 흐림은 값이 없는 자리와, 「일어난 일이 없다」를
 *  세는 건수(거래량·미결제 0)의 것입니다. 방향 값을 그리는 자리는 전부 이 하나를
 *  씁니다 — 자리마다 따로 갈리면 같은 0 이 화면마다 다른 얼굴이 됩니다. */
export function toneOf(value: number): '' | 'up' | 'down' {
  return value > 0 ? 'up' : value < 0 ? 'down' : ''
}

interface NumberProps {
  value: number
  /** 이 종목의 소수 자릿수. 마스터가 정한 값만큼 채웁니다. */
  decimals: number
  /** 분수로 적는 품목이면 그 분모. 있으면 소수 대신 분수로 그립니다. */
  fraction?: number | null
  /** 부호를 항상 붙입니다. 등락·손익처럼 방향을 읽는 값에 씁니다. */
  signed?: boolean
  /** 방향에 따라 색을 입힙니다. 부호와 함께만 씁니다. */
  toned?: boolean
  suffix?: string
}

/* 자릿수를 세로로 맞출 자리에 씁니다 — 표의 한 열, 나란히 쌓이는 값들.
 *
 * 문장 속에 값 하나를 넣을 때는 쓰지 마세요. 소수부 칸을 자릿수만큼 미리
 * 잡아두기 때문에, 뒤에 단위가 붙으면 그 빈칸만큼 밀려나 「2.03  억원」처럼
 * 갈라집니다. 그런 자리에는 `Count` 나 평범한 숫자를 씁니다. */
export function Num({
  value,
  decimals,
  fraction,
  signed = false,
  toned = false,
  suffix,
}: NumberProps): ReactElement {
  const [int, frac] = numberParts(value, decimals, fraction, signed)
  const tone = toned ? toneOf(value) : ''

  return (
    <span className={`num-dec ${tone}`.trim()}>
      <span className="num-int">{int}</span>
      <span className="num-frac">
        {frac}
        {suffix}
      </span>
    </span>
  )
}

/** 값이나 자릿수가 없을 수 있는 자리. **없으면 「—」입니다.**
 *
 *  0 으로 채우면 「없다」가 「0 이다」가 되고, 뼈대를 세우면 「곧 온다」가 됩니다.
 *  받은 답에 그 칸이 없는 것이라 둘 다 아닙니다. 자릿수를 못 찾은 때도 같습니다 —
 *  **자릿수를 지어내면 보이는 값이 받은 값과 달라집니다.**
 *
 *  계좌 목록처럼 **줄마다 오는 칸이 다른** 자리에서 씁니다. */
export function NumOrDash({
  value,
  decimals,
  ...rest
}: Omit<NumberProps, 'value' | 'decimals'> & {
  value: number | null
  decimals: number | null
}): ReactElement {
  if (value === null || decimals === null) return <span className="dead">—</span>
  return <Num value={value} decimals={decimals} {...rest} />
}

/** 정수만 쓰는 값(거래량·미결제·수량)입니다. */
export function Count({ value, signed = false }: { value: number; signed?: boolean }): ReactElement {
  const sign = value < 0 ? MINUS : signed && value > 0 ? '+' : ''
  return (
    <span className="num">
      {sign}
      {Math.abs(value).toLocaleString('ko-KR')}
    </span>
  )
}

/** 통화의 소수 자릿수. 줄마다 오는 계좌 답(잔고·누적손익)에는 자릿수 칸이 없어
 *  통화 코드로 정합니다 — **원·엔은 0, 그 밖은 2**(ISO 4217 의 소수 자리).
 *  예탁자산 답은 자릿수를 함께 싣고 오므로 그 답은 이 표를 쓰지 않습니다.
 *
 *  코드가 없으면 `null` 입니다. 무슨 돈인지 모르는 값에 자릿수를 지어 붙이면
 *  받은 적 없는 「.00」이 섭니다 — 부르는 쪽은 그때 값을 그대로 적습니다. */
export function currencyDigits(code: string | null | undefined): number | null {
  if (!code) return null
  return code === 'KRW' || code === 'JPY' ? 0 : 2
}

/** 통화 이름을 코드로. 전략 줄은 원을 「원」으로, 계좌·기록 답은 「KRW」로 적습니다.
 *  세 글자 대문자가 아닌 것은 모르는 통화입니다(빈 글자). */
export function currencyCode(currency: string | null | undefined): string {
  if (currency === '원' || currency === 'KRW') return 'KRW'
  return currency && /^[A-Z]{3}$/.test(currency) ? currency : ''
}

/** 금액 칸에 친 글자를 그 통화의 꼴로 — 정수부는 칠 때마다 쉼표, 소수는 그 통화의
 *  자릿수까지(원·엔은 소수 없음). 숫자와 소수점 밖의 글자는 걷습니다. 손실 한도·증거금
 *  예산 칸이 이 한 함수를 씁니다 — 담는 값은 쉼표를 뗀 숫자 글자입니다. */
export function limitTyped(raw: string, digits: number): string {
  const body = raw.replace(/[^0-9.]/g, '')
  const dot = body.indexOf('.')
  const whole = (dot === -1 ? body : body.slice(0, dot)).replace(/^0+(?=\d)/, '')
  const grouped = whole === '' ? '' : Number(whole).toLocaleString('ko-KR')
  if (dot === -1 || digits === 0) return grouped
  return `${grouped || '0'}.${body.slice(dot + 1).replace(/\./g, '').slice(0, digits)}`
}

/** 쉼표를 단 글자에서 커서를 둘 자리 — 커서 앞에 있던 숫자·소수점 수(`count`)만큼
 *  지난 곳입니다. 가운데 숫자를 고쳐도 커서가 끝으로 튀지 않게 합니다. */
export function caretAfter(text: string, count: number): number {
  if (count <= 0) return 0
  let seen = 0
  for (let index = 0; index < text.length; index++) {
    if (/[0-9.]/.test(text[index])) seen += 1
    if (seen === count) return index + 1
  }
  return text.length
}

/** 전략 화면의 금액 한 줄. **원은 정수로 반올림해 「원」을 붙이고**, 그 밖의
 *  통화는 그 통화의 소수 자릿수(`currencyDigits`)에 한 칸 띄어 코드를 붙입니다
 *  (「59,168,156원」·「50,000.00 USD」). 값이나 통화를 모르면 「—」입니다 —
 *  단위 없는 수는 어느 돈인지 읽히지 않습니다. */
export function moneyIn(value: number | null | undefined, currency: string | null | undefined): string {
  const code = currencyCode(currency)
  if (value === null || value === undefined || !Number.isFinite(value) || code === '') return '—'
  const digits = currencyDigits(code) ?? 2
  const size = Math.abs(value)
  const text = size.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
  const signed = value < 0 && Number(text.replace(/,/g, '')) !== 0 ? `${MINUS}${text}` : text
  return code === 'KRW' ? `${signed}원` : `${signed} ${code}`
}
