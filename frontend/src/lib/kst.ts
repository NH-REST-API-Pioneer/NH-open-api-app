/* 한국시간(Asia/Seoul).
 *
 * 거래시간표·세션 판정·국내 장 시각은 모두 한국시간입니다. 화면이 그 값과 **지금**
 * 또는 **어느 시각**을 견줄 때 브라우저의 시간대로 읽으면, PC 시간대가 한국이
 * 아닐 때 판정이 몇 시간씩 어긋납니다. 견주는 자리는 모두 이 도우미를 씁니다.
 *
 * 한국은 서머타임이 없지만 고정 +9시간으로 셈하지 않고 시간대 이름으로 읽습니다 —
 * 규칙이 바뀌어도 이 한 자리만 따라가면 됩니다.
 */

const FORMAT = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Seoul',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
})

/** 한국시간의 연·월·일·시·분·초. */
export interface KstParts {
  year: number
  month: number
  day: number
  hour: number
  minute: number
  second: number
}

export function kstParts(at: Date | number): KstParts {
  const parts = FORMAT.formatToParts(at)
  const read = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((one) => one.type === type)?.value ?? '0')
  return {
    year: read('year'),
    month: read('month'),
    day: read('day'),
    hour: read('hour') % 24,
    minute: read('minute'),
    second: read('second'),
  }
}

/** 한국시간 「HH:MM」. */
export function kstClock(at: Date | number): string {
  const { hour, minute } = kstParts(at)
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}

/** 한국시간 「HH:MM:SS」. 한 분 안에 여러 번 일어나는 체결을 가려 적을 때 씁니다. */
export function kstClockSeconds(at: Date | number): string {
  const { hour, minute, second } = kstParts(at)
  const two = (value: number) => String(value).padStart(2, '0')
  return `${two(hour)}:${two(minute)}:${two(second)}`
}

/** 두 한국시각 「HH:MM」 중 더 이른 쪽. 한쪽이 비었으면 다른 쪽입니다. 둘 다
 *  지금으로부터 하루 안에 **이미 지난** 시각이라고 보고 견줍니다.
 *
 *  **글자로 견주면 안 됩니다.** 국내 야간장은 자정을 넘겨 이어지므로 23:55 와
 *  00:10 이 한 화면에 섭니다 — 글자로는 00:10 이 이르다고 나오는데 실제로는
 *  23:55 가 먼저입니다. 그래서 「지금(`nowMinutes`, 한국시간 자정부터 지난 분)으로부터
 *  얼마나 지났나」로 견줍니다. */
export function earlierClock(a: string, b: string, nowMinutes: number): string {
  if (!a) return b
  if (!b) return a
  const ago = (text: string) => {
    const [hour, minute] = text.split(':').map(Number)
    return (nowMinutes - (hour * 60 + minute) + 1440) % 1440
  }
  return ago(a) >= ago(b) ? a : b
}

/** 한국시간 자정부터 지난 분. */
export function kstMinutes(at: Date | number): number {
  const { hour, minute } = kstParts(at)
  return hour * 60 + minute
}

/** 한국 달력의 날 번호(1970-01-01 부터 센 날). 두 시각이 같은 날인지, 며칠 차이인지를
 *  견줄 때 씁니다. */
export function kstDay(at: Date | number): number {
  const { year, month, day } = kstParts(at)
  return Date.UTC(year, month - 1, day) / 86_400_000
}

/** 그 시각이 든 한국 날의 자정(ms). 한국시간과 UTC 의 차이는 그 시각에서 읽어
 *  씁니다. */
export function kstDayStart(at: Date | number): number {
  const ms = typeof at === 'number' ? at : at.getTime()
  const { year, month, day, hour, minute, second } = kstParts(ms)
  const whole = ms - (((ms % 1000) + 1000) % 1000)
  const offset = Date.UTC(year, month - 1, day, hour, minute, second) - whole
  return Date.UTC(year, month - 1, day) - offset
}

const pad2 = (value: number) => String(value).padStart(2, '0')

/** 한국 달력의 오늘(또는 그 시각의 날)을 「YYYYMMDD」로. 조회 날짜는 서버가
 *  한국시간으로 정하므로, 이 PC 의 시간대가 달라도 같은 날을 보냅니다. */
export function kstDate(at: Date | number = Date.now()): string {
  const { year, month, day } = kstParts(at)
  return `${year}${pad2(month)}${pad2(day)}`
}

/** `kstDate` 의 「YYYY-MM-DD」 꼴. 날짜 입력 칸이 쓰는 모양입니다. */
export function kstDateDash(at: Date | number = Date.now()): string {
  const { year, month, day } = kstParts(at)
  return `${year}-${pad2(month)}-${pad2(day)}`
}

/* 아래는 **날짜 글자끼리의 달력 셈**입니다. 「YYYYMMDD」와 「YYYY-MM-DD」를 모두
 * 받고 받은 꼴 그대로 돌려줍니다. 시각을 거치지 않아 시간대와 무관합니다. */

interface CalendarDay {
  year: number
  month: number
  day: number
  dash: boolean
}

function readDay(text: string): CalendarDay {
  const dash = text.includes('-')
  const digits = dash ? text.replace(/-/g, '') : text
  return {
    year: Number(digits.slice(0, 4)),
    month: Number(digits.slice(4, 6)),
    day: Number(digits.slice(6, 8)),
    dash,
  }
}

/** UTC 자정 ms 를 날짜 글자로. 달력 셈 결과를 글자로 돌려놓는 데만 씁니다. */
function writeDay(utc: number, dash: boolean): string {
  const at = new Date(utc)
  const year = at.getUTCFullYear()
  const month = pad2(at.getUTCMonth() + 1)
  const day = pad2(at.getUTCDate())
  return dash ? `${year}-${month}-${day}` : `${year}${month}${day}`
}

/** 그 날에서 `days` 날 뒤(음수면 앞)의 날. */
export function addDays(text: string, days: number): string {
  const { year, month, day, dash } = readDay(text)
  return writeDay(Date.UTC(year, month - 1, day + days), dash)
}

/** 그 시각이 드는 **거래일**(「YYYY-MM-DD」). 국내 야간(`domestic-night`)은 18:00 에
 *  열어 자정을 넘기는 창이라, 정오 뒤의 시각은 다음 날 거래일에 듭니다 — 서버가
 *  거래일을 세는 규칙과 같습니다. 휴장일은 건너뛰지 않습니다. */
export function kstTradingDay(at: number, context: string | null | undefined): string {
  const day = kstDateDash(at)
  return context === 'domestic-night' && kstParts(at).hour >= 12 ? addDays(day, 1) : day
}

/** 그 날에서 `years` 해 앞의 같은 월·일. 없는 날(2/29)은 다음 날로 넘깁니다. */
export function subtractYears(text: string, years: number): string {
  const { year, month, day, dash } = readDay(text)
  return writeDay(Date.UTC(year - years, month - 1, day), dash)
}

/** 그 날에서 `months` 달 앞의 같은 날. **그 달에 없는 날이면 그 달의 끝날**입니다
 *  (3/31 의 한 달 앞은 2/28, 윤년이면 2/29). */
export function subtractMonths(text: string, months: number): string {
  const { year, month, day, dash } = readDay(text)
  const lastDay = new Date(Date.UTC(year, month - 1 - months + 1, 0)).getUTCDate()
  return writeDay(Date.UTC(year, month - 1 - months, Math.min(day, lastDay)), dash)
}

/** 그 날의 요일(0 일 ~ 6 토). */
export function weekdayOf(text: string): number {
  const { year, month, day } = readDay(text)
  return new Date(Date.UTC(year, month - 1, day)).getUTCDay()
}

/** `from` 에서 `to` 까지 지난 날 수(같은 날이면 0). 날짜로 읽을 수 없으면 `NaN`. */
export function daysBetween(from: string, to: string): number {
  const eightDigits = (text: string) => /^\d{8}$/.test(text.replace(/-/g, ''))
  if (!eightDigits(from) || !eightDigits(to)) return Number.NaN
  const a = readDay(from)
  const b = readDay(to)
  return Math.round(
    (Date.UTC(b.year, b.month - 1, b.day) - Date.UTC(a.year, a.month - 1, a.day)) / 86_400_000,
  )
}
