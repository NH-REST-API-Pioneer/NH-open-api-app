import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import {
  askSeconds,
  daysToFill,
  fillMissing,
  isProvisional,
  periodDays,
  realisedOf,
  shadeOf,
  stopFilling,
  trendSummary,
  unrealisedOf,
  useTrendPeriod,
  type HistoryDay,
  type TrendSummary,
} from '../../data/depositHistory'
import {
  depositMoney,
  isDomesticDeposit,
  useListOnce,
  type DepositMarket,
  type ServerRealized,
} from '../../data/account'
import { addDays, kstDate, subtractMonths, weekdayOf } from '../../lib/kst'
import { MINUS, moneyIn, toneOf } from '../../lib/number'

/* 계좌 「추이」 탭.
 *
 * **이 화면의 값은 날마다 물어 이어 붙인 것입니다.** NH선물에 날짜별 줄을 주는
 * 계좌 조회가 없어, 하루치를 날마다 받아 이 앱이 모읍니다 — 그래서 그림 아래에
 * 「며칠치인가」를 늘 적습니다. 서버가 셈해 주는 값(해외 품목별 누적손익)에는
 * 그렇다고 따로 적습니다. 두 값이 만들어진 방법이 다른데 한 화면에 나란히
 * 서므로, 무엇이 어떻게 만들어진 값인지 화면이 말해야 합니다.
 *
 * **빠진 날은 잇지 않습니다.** 선을 끊고 사이를 비웁니다 — 이으면 이 앱이 안 받은
 * 날에 값이 있었던 것으로 읽힙니다.
 *
 * 색은 **손익에만** 씁니다 — 이익은 상승색, 손실은 하락색으로 앱의 등락색과
 * 같습니다. 예탁자산은 방향이 아니라 크기라 색이 없습니다.
 */

type Preset = '5일' | '1개월' | '3개월' | '직접'

const PRESETS: Preset[] = ['5일', '1개월', '3개월', '직접']

/** 기간 상한. 넘겨 받으면 한 번에 250 번 넘게 묻게 됩니다. */
const MAX_DAYS = 366

function asInput(text: string): string {
  return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`
}

/** 「M/D」. 축 양 끝에 적는 짧은 꼴입니다. */
function shortDay(text: string): string {
  return `${Number(text.slice(4, 6))}/${Number(text.slice(6, 8))}`
}

/** 오늘에서 영업일로 N 칸 뒤. **주말은 건너뜁니다** — 서버도 주말을 빼고 세므로
 *  달력 날짜로 세면 「5일」이 영업일 셋이 됩니다. */
function backBusinessDays(count: number): string {
  let at = kstDate()
  let left = count - 1
  while (left > 0) {
    at = addDays(at, -1)
    const day = weekdayOf(at)
    if (day !== 0 && day !== 6) left -= 1
  }
  return at
}

/** 그 끝 날에서 상한만큼 거슬러 간 날. 그보다 앞은 안 묻습니다. */
function capped(to: string, days: number): string {
  return addDays(to, -days)
}

/** 오늘에서 N 달 앞의 다음 날. 그 달에 오늘과 같은 날이 없으면 그 달의 끝날에서
 *  셉니다(3/31 의 「1개월」은 2/28 의 다음 날인 3/1 부터). */
function backMonths(count: number): string {
  return addDays(subtractMonths(kstDate(), count), 1)
}

/** 그림 칸의 가장자리 여백. 높이는 칸마다 다릅니다(`HEIGHT`). **가로는 재서
 *  씁니다** — `viewBox` 로 늘이면 칸이 넓을 때 그림이 가운데만 차지하고 양옆이
 *  빕니다. */
const PAD = 8

/** 칸 높이(px). 누적 곡선이 이 화면의 주인공이라 높고, 해외는 그 아래에 평가손익
 *  선이 한 칸 더 붙어 누적 곡선을 조금 낮춥니다. 평가손익 선은 방향만 읽으면 되어
 *  낮습니다. 창이 낮으면 묶음이 굴러갑니다(`.trend-body`). */
const HEIGHT = { domestic: 230, overseas: 190, level: 50 }

/** 날마다 점을 찍는 기간의 상한(영업일). 이보다 길면 점이 줄처럼 붙어 선을
 *  가려, 마지막 날과 외톨이 점만 찍습니다. */
const DOTS_UNTIL = 30

/** 가로 날짜 하나가 차지하는 폭(px). 날짜는 대략 이만큼에 하나씩 섭니다. */
const TICK_EVERY = 60

/** 가로 날짜끼리 떨어져야 하는 거리(px). 이보다 가까우면 뒤의 것을 뺍니다. */
const TICK_GAP = 48

/** 두 값 글자가 서로 닿지 않는 최소 간격(px). **잰 글자 높이(17)에 한 픽셀**을
 *  더한 값이라, 이보다 가까운 쌍은 실제로 겹칩니다 — 겹치지도 않는데 미는 일이
 *  없어야 라벨이 제 값 높이에 그대로 섭니다. */
const EDGE_GAP = 18

/** 글자 높이의 절반(px). 자리는 글자 **가운데**라, 칸 끝에서 이만큼은 안으로
 *  물려야 글자가 칸 밖으로 넘지 않습니다. */
const EDGE_HALF = 9

/** 두 값을 묶은 덩어리 높이의 절반(px). 잰 줄 높이 16.5 의 두 줄(33)을 반으로
 *  나눠 올린 값입니다 — 한 줄 기준(`EDGE_HALF`)으로 물리면 칸 맨 위·맨 아래에서
 *  덩어리가 반 줄 밖으로 나갑니다. */
const EDGE_PAIR_HALF = 17

/** 값 글자가 설 오른쪽 열의 폭(px). **그림은 이만큼 좁게 그립니다** — 그림 위에
 *  얹으면 값이 그 높이의 점을 가리고, 하필 가려지는 것이 **마지막 날**입니다.
 *  「143,000,000원」·「102,874.20 USD」가 드는 폭입니다. */
const EDGE_COL = 96

/** 그림이 설 칸의 가로 폭. 창을 바꾸면 따라 바뀝니다.
 *
 *  **칸이 나중에 생겨도 잽니다** — 받은 날이 없는 동안에는 그림 칸이 없다가 값이
 *  오면 생기므로, 붙는 순간의 칸을 받아 그때부터 봅니다. **값이 실제로 달라질
 *  때만** 다시 그립니다 — 같은 수로 상태를 갈면 관찰자와 그리기가 서로를 부릅니다. */
function useBoxWidth(): [(node: HTMLDivElement | null) => void, number] {
  const [box, setBox] = useState<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    if (!box) return
    const read = () => {
      const next = Math.round(box.clientWidth)
      setWidth((held) => (held === next ? held : next))
    }
    read()
    const watch = new ResizeObserver(read)
    watch.observe(box)
    return () => watch.disconnect()
  }, [box])
  return [setBox, width]
}

interface Point {
  /** 기간 안에서 몇 번째 영업일인가. 빠진 날도 자리를 차지합니다. */
  slot: number
  value: number
}

/** 그 영업일이 설 가로 자리. **그림과 띠·세로선·날짜가 모두 이 셈을 씁니다** —
 *  따로 셈하면 같은 날이 칸마다 조금씩 다른 자리에 섭니다. */
function slotX(slot: number, count: number, width: number): number {
  const wide = Math.max(count - 1, 1)
  return PAD + (slot / wide) * Math.max(width - PAD * 2, 1)
}

/** 점을 찍을 자리. **요청한 기간의 영업일 전부**를 가로축에 깔고 그 위에 값을
 *  얹습니다 — 받은 날만 늘어놓으면 한 주를 통째로 못 받아도 선이 촘촘히
 *  이어지고, 기간 앞뒤로 아직 안 받은 자리가 그림에서 사라집니다. */
function pointsOf(
  days: HistoryDay[],
  slots: string[],
  pick: (day: HistoryDay) => number | null,
): Point[] {
  const at = new Map(slots.map((day, index) => [day, index]))
  const points: Point[] = []
  for (const day of days) {
    const value = pick(day)
    const slot = at.get(day.day)
    if (value === null || slot === undefined || !Number.isFinite(value)) continue
    points.push({ slot, value })
  }
  return points
}

/** 값을 자리로 옮기는 자. `fromZero` 는 **0 을 눈금에 넣을지**입니다 — 손익은
 *  0 이 기준이라 늘 넣습니다.
 *
 *  값이 다 같은 기간은 **가운데**에 눕힙니다 — 위나 아래 끝에 붙이면 잘린
 *  그림처럼 보입니다. */
function scale(points: Point[], count: number, width: number, height: number, fromZero: boolean) {
  const values = points.map((one) => one.value)
  let top = fromZero ? Math.max(...values, 0) : Math.max(...values)
  let bottom = fromZero ? Math.min(...values, 0) : Math.min(...values)
  if (top === bottom) {
    const step = Math.abs(top) || 1
    top += step
    bottom -= step
  }
  const span = top - bottom || 1
  const inner = height - PAD * 2
  return {
    x: (slot: number) => slotX(slot, count, width),
    y: (value: number) => PAD + ((top - value) / span) * inner,
    zero: PAD + (top / span) * inner,
    /* 그림의 위아래 끝이 아니라 **값의 최고·최저**입니다 — 끝을 적으면 이 앱이
       여백으로 벌려 둔 수가 값인 것처럼 섭니다. */
    high: Math.max(...values),
    low: Math.min(...values),
  }
}

/** 그림 곁에 적는 값 — 최고·최저, 그리고 「0」 하나.
 *
 *  **칸의 모서리가 아니라 그 값의 높이에 답니다.** 모서리에 두면 아래 값이 0선
 *  옆에 붙어 **그 선을 그 값으로 읽게** 됩니다.
 *
 *  **같으면 한 번만** 적습니다 — 같은 수가 위아래로 두 번 서면 두 값인 줄 알고
 *  견주게 됩니다. 「0」은 최고·최저 글자와 닿으면 적지 않습니다(선은 남습니다).
 *
 *  `zeroWins` 이면 거꾸로 **「0」이 이기고 닿는 최고·최저 글자를 뺍니다.** 누적
 *  곡선이 씁니다 — 0 에서 떠난 거리를 읽는 그림이라, 0선 곁에 다른 수가 서면 0선을
 *  그 값으로 읽어 그림 전체를 잘못 읽습니다. 뺀 값은 곡선과 읽기 상자로 봅니다. */
function Edges({
  high,
  low,
  money,
  at,
  height,
  extra,
  zeroWins = false,
}: {
  high: number
  low: number
  money: (v: number) => string
  at: (value: number) => number
  height: number
  extra: { value: number; text: string } | null
  zeroWins?: boolean
}) {
  /* 글자가 칸 밖으로 반쯤 나가지 않게 위아래로 조금 물립니다. */
  const seat = (value: number) => Math.min(Math.max(at(value), EDGE_HALF), height - EDGE_HALF)
  if (zeroWins && extra !== null) {
    const zero = seat(extra.value)
    const kept = (high === low ? [high] : [high, low]).filter((value) => Math.abs(seat(value) - zero) >= EDGE_GAP)
    const paired = kept.length === 2 && seat(kept[1]) - seat(kept[0]) < EDGE_GAP
    return (
      <>
        {paired ? (
          <span
            className="trend-edge"
            style={{
              top: Math.min(
                Math.max((seat(kept[0]) + seat(kept[1])) / 2, EDGE_PAIR_HALF),
                height - EDGE_PAIR_HALF,
              ),
            }}
          >
            <span className="trend-edge-line">{money(kept[0])}</span>
            <span className="trend-edge-line">{money(kept[1])}</span>
          </span>
        ) : (
          kept.map((value) => (
            <span key={value} className="trend-edge" style={{ top: seat(value) }}>
              {money(value)}
            </span>
          ))
        )}
        <span className="trend-edge" style={{ top: zero }}>
          {extra.text}
        </span>
      </>
    )
  }
  if (high === low) {
    const one = seat(high)
    const third = extra === null ? null : seat(extra.value)
    return (
      <>
        <span className="trend-edge" style={{ top: one }}>
          {money(high)}
        </span>
        {third !== null && extra !== null && Math.abs(third - one) >= EDGE_GAP && (
          <span className="trend-edge" style={{ top: third }}>
            {extra.text}
          </span>
        )}
      </>
    )
  }
  const top = seat(high)
  const bottom = seat(low)
  /* 두 값이 가까운 기간에는 글자끼리 겹칩니다. 그때는 **밀지 않고 한 덩어리로
     묶어** 두 값 사이 가운데 높이에 둡니다 — 밀어 띄우면 라벨이 제 값 높이를
     벗어나, 선 옆의 수를 그 선의 값으로 읽게 됩니다. 위가 최고, 아래가 최저라는
     차례가 뜻을 말합니다. */
  if (bottom - top < EDGE_GAP) {
    const middle = Math.min(Math.max((top + bottom) / 2, EDGE_PAIR_HALF), height - EDGE_PAIR_HALF)
    return (
      <span className="trend-edge" style={{ top: middle }}>
        <span className="trend-edge-line">{money(high)}</span>
        <span className="trend-edge-line">{money(low)}</span>
      </span>
    )
  }
  const third = extra === null ? null : seat(extra.value)
  /* 「0」은 최고·최저 사이에만 서는 것이 아닙니다 — 누적이 한쪽으로만 가면 0선은
     최저 아래(또는 최고 위)에 있습니다. 두 글자 어느 쪽과도 닿지 않으면 적습니다. */
  const roomy = third !== null && Math.abs(third - top) >= EDGE_GAP && Math.abs(bottom - third) >= EDGE_GAP
  return (
    <>
      <span className="trend-edge" style={{ top }}>
        {money(high)}
      </span>
      {roomy && extra !== null && (
        <span className="trend-edge" style={{ top: third }}>
          {extra.text}
        </span>
      )}
      <span className="trend-edge" style={{ top: bottom }}>
        {money(low)}
      </span>
    </>
  )
}

/** 칸의 가로 격자 — 최고·최저 선. 옅은 행 선 색이라 값을 가리지 않고 높이만
 *  가늠하게 합니다. 0 기준선은 그리는 쪽이 따로 긋습니다. */
function Grid({ at, width }: { at: ReturnType<typeof scale>; width: number }) {
  const rows = at.high === at.low ? [at.high] : [at.high, at.low]
  return (
    <>
      {rows.map((value) => (
        <line key={value} className="trend-grid" x1={PAD} y1={at.y(value)} x2={width - PAD} y2={at.y(value)} />
      ))}
    </>
  )
}

/** 0 이 값 범위 안에 드는가(끝 포함). 「0」 글자가 이 물음을 씁니다. */
function spansZero(at: { high: number; low: number }): boolean {
  return at.low <= 0 && at.high >= 0 && at.high !== at.low
}

/** 이웃한 영업일끼리 묶은 줄들. **빈 날에서 끊습니다** — 이으면 안 받은 날에
 *  값이 있었던 것으로 읽힙니다. */
function runsOf(points: Point[]): Point[][] {
  const runs: Point[][] = []
  for (const one of points) {
    const run = runs[runs.length - 1]
    if (run && one.slot - run[run.length - 1].slot === 1) run.push(one)
    else runs.push([one])
  }
  return runs
}

/** 이어진 점들을 **두 끝이 모두 0 인 조각**과 그 밖의 조각으로 나눈 이어진 묶음들.
 *  이웃한 묶음은 끝점을 함께 씁니다(선이 끊겨 보이지 않게). 0 에 붙어 가는 구간은
 *  이익도 손실도 아니라 따로 그립니다 — 0선 높이에서 위·아래로 자르면 굵은 선이 반씩
 *  두 색으로 칠해져 한쪽 색으로 읽힙니다. */
function piecesOf(run: Point[]): { flat: boolean; points: Point[] }[] {
  const pieces: { flat: boolean; points: Point[] }[] = []
  for (let index = 1; index < run.length; index += 1) {
    const from = run[index - 1]
    const to = run[index]
    const flat = from.value === 0 && to.value === 0
    const last = pieces[pieces.length - 1]
    if (last && last.flat === flat) last.points.push(to)
    else pieces.push({ flat, points: [from, to] })
  }
  return pieces
}

/** 누적 손익 곡선. **선 하나**를 0선 높이에서 둘로 잘라, 0 위는 이익 색·0 아래는
 *  손실 색으로 칠합니다 — 선을 둘로 나눠 그리면 0 을 넘나드는 자리에서 끊겨
 *  보입니다. 채움은 **선과 0선 사이만**입니다(바닥까지 칠하면 0 아래 넓이가 손실로
 *  읽힙니다). 값이 모두 0 이면 0선만 남습니다. */
function CumulativeChart({
  points,
  count,
  width,
  height,
  money,
  name,
  picked,
}: {
  points: Point[]
  count: number
  width: number
  height: number
  money: (value: number) => string
  name: string
  picked: number | null
}) {
  const id = useId().replace(/:/g, '')
  if (points.length === 0 || width === 0) return null
  const at = scale(points, count, width, height, true)
  const flat = at.high === 0 && at.low === 0
  const zero = Math.min(Math.max(at.zero, 0), height)
  const runs = runsOf(points)
  const path = (run: Point[]) =>
    run.map((one, index) => `${index === 0 ? 'M' : 'L'}${at.x(one.slot).toFixed(2)},${at.y(one.value).toFixed(2)}`).join(' ')
  const area = (run: Point[]) =>
    `${path(run)} L${at.x(run[run.length - 1].slot).toFixed(2)},${zero.toFixed(2)} L${at.x(run[0].slot).toFixed(2)},${zero.toFixed(2)} Z`
  const tone = (value: number) => (value > 0 ? 'is-up' : value < 0 ? 'is-down' : 'is-flat')
  const last = points[points.length - 1]
  const dots = runs.filter((run) => run.length === 1).map((run) => run[0])
  if (!dots.includes(last)) dots.push(last)
  const chosen = picked === null ? undefined : points.find((one) => one.slot === picked)
  const up = `url(#${id}-up)`
  const down = `url(#${id}-down)`
  return (
    <div className="trend-plot">
      <svg className="trend-chart" width={width} height={height} role="img" aria-label={name}>
        <defs>
          <clipPath id={`${id}-up`}>
            <rect x={0} y={0} width={width} height={zero} />
          </clipPath>
          <clipPath id={`${id}-down`}>
            <rect x={0} y={zero} width={width} height={Math.max(height - zero, 0)} />
          </clipPath>
          {/* 채움은 선 가까이 짙고 0선으로 갈수록 옅어집니다. */}
          <linearGradient id={`${id}-fill-up`} gradientUnits="userSpaceOnUse" x1={0} y1={PAD} x2={0} y2={zero}>
            <stop offset={0} className="trend-stop-up" stopOpacity={0.3} />
            <stop offset={1} className="trend-stop-up" stopOpacity={0} />
          </linearGradient>
          <linearGradient
            id={`${id}-fill-down`}
            gradientUnits="userSpaceOnUse"
            x1={0}
            y1={zero}
            x2={0}
            y2={height - PAD}
          >
            <stop offset={0} className="trend-stop-down" stopOpacity={0} />
            <stop offset={1} className="trend-stop-down" stopOpacity={0.3} />
          </linearGradient>
        </defs>
        <Grid at={at} width={width} />
        {!flat &&
          runs
            .filter((run) => run.length > 1)
            .map((run) => (
              <g key={`fill-${run[0].slot}`}>
                <path d={area(run)} fill={`url(#${id}-fill-up)`} clipPath={up} />
                <path d={area(run)} fill={`url(#${id}-fill-down)`} clipPath={down} />
              </g>
            ))}
        {/* 0 기준선. 누적은 0 에서 출발하므로 늘 긋습니다. */}
        <line className="trend-zero" x1={PAD} y1={zero} x2={width - PAD} y2={zero} />
        {!flat &&
          runs
            .filter((run) => run.length > 1)
            .map((run) => (
              <g key={`line-${run[0].slot}`}>
                {piecesOf(run).map((piece) =>
                  piece.flat ? (
                    <path key={`flat-${piece.points[0].slot}`} className="trend-cum is-flat" d={path(piece.points)} />
                  ) : (
                    <g key={`tone-${piece.points[0].slot}`}>
                      <path className="trend-cum is-up" d={path(piece.points)} clipPath={up} />
                      <path className="trend-cum is-down" d={path(piece.points)} clipPath={down} />
                    </g>
                  ),
                )}
              </g>
            ))}
        {dots.map((one) => (
          <circle
            key={one.slot}
            className={`trend-cum-dot ${tone(one.value)}`}
            cx={at.x(one.slot)}
            cy={at.y(one.value)}
            r={3.5}
          />
        ))}
        {chosen && (
          <circle className="trend-dot is-picked" cx={at.x(chosen.slot)} cy={at.y(chosen.value)} r={4} />
        )}
      </svg>
      <Edges
        high={at.high}
        low={at.low}
        money={money}
        at={at.y}
        height={height}
        extra={flat ? null : { value: 0, text: '0' }}
        zeroWins
      />
    </div>
  )
}

/** 값 하나를 **선**으로 잇는 칸. 해외 평가손익이 씁니다 — 그날 번 것이 아니라
 *  **그 시점의 크기**라 누적에 더하지 않고 따로 긋습니다.
 *
 *  **이웃한 영업일끼리만 잇습니다** — 사이에 못 받은 날이 있으면 선을 끊고
 *  점만 남깁니다. 기간이 길면 점은 마지막 날과 외톨이 점에만 찍습니다. */
function LineChart({
  points,
  count,
  width,
  height,
  money,
  name,
  picked,
}: {
  points: Point[]
  count: number
  width: number
  height: number
  money: (value: number) => string
  name: string
  picked: number | null
}) {
  if (points.length === 0 || width === 0) return null
  const at = scale(points, count, width, height, true)
  const dense = count > DOTS_UNTIL
  const lines: { from: Point; to: Point }[] = []
  for (let i = 1; i < points.length; i += 1) {
    if (points[i].slot - points[i - 1].slot === 1) lines.push({ from: points[i - 1], to: points[i] })
  }
  const taken = new Set(points.map((one) => one.slot))
  const lonely = (slot: number) => !taken.has(slot - 1) && !taken.has(slot + 1)
  const last = points[points.length - 1].slot
  const dots = dense ? points.filter((one) => one.slot === last || lonely(one.slot)) : points
  const chosen = picked === null ? undefined : points.find((one) => one.slot === picked)
  const zero = spansZero(at)
  return (
    <div className="trend-plot">
      <svg className="trend-chart" width={width} height={height} role="img" aria-label={name}>
        <Grid at={at} width={width} />
        {zero && <line className="trend-zero" x1={PAD} y1={at.zero} x2={width - PAD} y2={at.zero} />}
        {lines.map((one, index) => (
          <line
            key={index}
            className={`trend-line${dense ? ' is-dense' : ''}`}
            x1={at.x(one.from.slot)}
            y1={at.y(one.from.value)}
            x2={at.x(one.to.slot)}
            y2={at.y(one.to.value)}
          />
        ))}
        {dots.map((one) => (
          <circle key={one.slot} className="trend-dot" cx={at.x(one.slot)} cy={at.y(one.value)} r={2.5} />
        ))}
        {chosen && <circle className="trend-dot is-picked" cx={at.x(chosen.slot)} cy={at.y(chosen.value)} r={3.5} />}
      </svg>
      <Edges
        high={at.high}
        low={at.low}
        money={money}
        at={at.y}
        height={height}
        extra={zero ? { value: 0, text: '0' } : null}
      />
    </div>
  )
}

/** 가로 날짜를 세울 영업일. 처음·끝은 늘 서고, 사이는 **폭 60px 에 하나꼴**로
 *  고르게 둡니다. 구간 안에 달이 바뀌는 날이 있으면 그 날을 먼저 씁니다 —
 *  달의 첫 영업일이 서야 기간을 한눈에 가늠합니다. 이웃과 너무 가까운 날짜는
 *  뺍니다(끝 날짜는 남깁니다). */
function axisTicks(slots: string[], width: number): number[] {
  const count = slots.length
  if (count === 0) return []
  const last = count - 1
  if (last === 0) return [0]
  const pieces = Math.max(Math.floor(Math.max(width - PAD * 2, 1) / TICK_EVERY), 1)
  const step = last / pieces
  const wanted = [0]
  for (let k = 1; k < pieces; k += 1) {
    const from = Math.max(Math.round(step * (k - 0.5)), 1)
    const to = Math.min(Math.round(step * (k + 0.5)), last - 1)
    let pick = Math.round(step * k)
    for (let i = from; i <= to; i += 1) {
      if (slots[i].slice(4, 6) !== slots[i - 1].slice(4, 6)) {
        pick = i
        break
      }
    }
    wanted.push(pick)
  }
  const x = (slot: number) => slotX(slot, count, width)
  const kept: number[] = []
  for (const slot of wanted) {
    const previous = kept[kept.length - 1]
    if (previous !== undefined && x(slot) - x(previous) < TICK_GAP) continue
    kept.push(slot)
  }
  while (kept.length > 1 && x(last) - x(kept[kept.length - 1]) < TICK_GAP) kept.pop()
  kept.push(last)
  return kept
}

/** 손익 값의 글자. **부호를 붙입니다** — 색만으로 오르내림을 말하지 않습니다. */
function signedMoney(value: number, money: (value: number) => string): string {
  return value > 0 ? `+${money(value)}` : money(value)
}

/* ── 요약 카드 ─────────────────────────────────────────── */

/** 카드 한 칸. 이름·값·보조 한 줄입니다. */
function Card({ name, children, sub }: { name: string; children: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="trend-stat">
      <p className="trend-stat-name">{name}</p>
      <div className="trend-stat-value">{children}</div>
      {sub !== undefined && <p className="trend-stat-sub">{sub}</p>}
    </div>
  )
}

/** 손익 값 한 줄 — 부호와 방향색을 함께 씁니다. 값이 없으면 「—」입니다. */
function Signed({ value, money }: { value: number | null; money: (value: number) => string }) {
  if (value === null) return <span className="dep-none">—</span>
  return <span className={toneOf(value) || undefined}>{signedMoney(value, money)}</span>
}

function Cards({
  summary,
  overseas,
  money,
  level,
  provisional,
}: {
  summary: TrendSummary
  overseas: boolean
  money: (value: number) => string
  /** 끝날의 평가손익(해외). */
  level: { day: string; value: number } | null
  /** 오늘 받은 값이 기간 손익에 들어 있나 — 그 값은 정산 전이라 바뀔 수 있습니다. */
  provisional: boolean
}) {
  const assets = summary.last ? money(summary.last.assets) : '—'
  /* 기간 손익 카드 보조 줄. 오늘 값이 섞였으면 끝에 그 사실을 붙입니다. */
  const withNote = (text: string | undefined): React.ReactNode =>
    provisional ? (
      <>
        {text !== undefined && `${text} · `}오늘 값 <span className="trend-provisional">잠정</span>
      </>
    ) : (
      text
    )
  /* 보조 줄은 **받은 첫날의 값**입니다. 기간 앞날은 묻지 않으므로 「기간 전 값」을
     적으면 지어낸 값이 됩니다. */
  const firstLine = summary.first ? `${shortDay(summary.first.day)} ${money(summary.first.assets)}` : undefined
  if (overseas) {
    return (
      <div className="trend-stats is-three">
        <Card name="예탁자산" sub={firstLine}>
          {assets}
        </Card>
        <Card name="기간 순손익 (수수료 차감)" sub={withNote(`이익 ${summary.gainDays}일 · 손실 ${summary.lossDays}일`)}>
          <Signed value={summary.total} money={money} />
        </Card>
        <Card name="평가손익" sub={level ? `${shortDay(level.day)} 기준` : undefined}>
          <Signed value={level?.value ?? null} money={money} />
        </Card>
      </div>
    )
  }
  const percent =
    summary.ratio === null
      ? undefined
      : `첫날 예탁의 ${summary.ratio > 0 ? '+' : summary.ratio < 0 ? MINUS : ''}${Math.abs(summary.ratio * 100).toFixed(2)}%`
  return (
    <div className="trend-stats">
      <Card name="예탁자산" sub={firstLine}>
        {assets}
      </Card>
      <Card name="기간 순손익 (수수료 차감)" sub={withNote(percent)}>
        <Signed value={summary.total} money={money} />
      </Card>
      <Card name="이익일 · 손실일" sub={`0 인 날 ${summary.zeroDays}일 · 빈 날 ${summary.blankDays}일`}>
        {summary.gainDays} · {summary.lossDays}일
      </Card>
      {/* 가장 큰 날 — 이익·손실 한 줄씩. 그런 날이 없는 기간이면 그 줄은 「—」입니다. */}
      <div className="trend-stat">
        <p className="trend-stat-name">가장 큰 날</p>
        {[summary.best, summary.worst].map((one, index) => (
          <p key={index} className="trend-stat-pair">
            <Signed value={one?.value ?? null} money={money} />
            {one && <span className="trend-stat-day">{shortDay(one.day)}</span>}
          </p>
        ))}
      </div>
    </div>
  )
}

/* ── 손익 달력 ─────────────────────────────────────────── */

/** 달력 칸 짙기 세 단의 섞는 몫(%). 마지막 단은 섞지 않은 손익 색 그대로입니다.
 *  글자는 앞 두 단 본문색, 마지막 단 흰색입니다. */
const SHADE_MIX = [40, 68, 100] as const

const WEEK = ['월', '화', '수', '목', '금']


/** 그 달(「YYYYMM」)의 평일 날짜들. */
function monthWeekdays(month: string): string[] {
  const year = Number(month.slice(0, 4))
  const index = Number(month.slice(4, 6)) - 1
  const last = new Date(Date.UTC(year, index + 1, 0)).getUTCDate()
  const days: string[] = []
  for (let date = 1; date <= last; date += 1) {
    const day = `${month}${String(date).padStart(2, '0')}`
    const week = weekdayOf(day)
    if (week !== 0 && week !== 6) days.push(day)
  }
  return days
}

/** 기간이 걸친 달들(「YYYYMM」, 차례대로). */
function monthsOf(from: string, to: string): string[] {
  const months: string[] = []
  let year = Number(from.slice(0, 4))
  let month = Number(from.slice(4, 6))
  const end = Number(to.slice(0, 6))
  while (year * 100 + month <= end && months.length < 40) {
    months.push(`${year}${String(month).padStart(2, '0')}`)
    month += 1
    if (month > 12) {
      month = 1
      year += 1
    }
  }
  return months
}

/** 칸에 적는 짧은 금액. 원은 1만 이상이면 만 단위로 반올림하고, 그 밖은 소수 없이
 *  천 단위 쉼표입니다 — 칸이 좁아 전체 금액은 읽기 상자가 말합니다. */
function cellText(value: number, won: boolean): string {
  const sign = value > 0 ? '+' : value < 0 ? MINUS : ''
  const size = Math.abs(value)
  if (won && size >= 10_000) return `${sign}${Math.round(size / 10_000).toLocaleString('ko-KR')}만`
  return `${sign}${Math.round(size).toLocaleString('ko-KR')}`
}

function PlCalendar({
  valueName,
  provisional,
  from,
  to,
  first,
  last,
  received,
  widest,
  money,
  currency,
  picked,
  onPick,
  onLeave,
}: {
  /** 칠하는 값의 이름. 카드·곡선과 같은 이름을 씁니다(순손익). */
  valueName: string
  /** 오늘 받은 날(정산 전 잠정 값). 기간 안에 오늘 값이 없으면 `null` 입니다. */
  provisional: string | null
  from: string
  to: string
  /** 기간의 첫·끝 영업일 — 곡선 가로축의 처음과 끝입니다. 두 달 이상이면 머리에 적습니다. */
  first: string | undefined
  last: string | undefined
  /** 받은 날과 그날 손익. 받았으나 손익 칸이 비었으면 `null` 입니다. */
  received: Map<string, number | null>
  widest: number
  money: (value: number) => string
  currency: string | null
  picked: string | null
  onPick: (day: string | null, by: 'mouse' | 'key') => void
  onLeave: () => void
}) {
  const months = monthsOf(from, to)
  /* 처음엔 **기간 끝 달**입니다 — 막 지난 날을 보려고 여는 탭입니다. */
  const [index, setIndex] = useState(months.length - 1)
  useEffect(() => {
    setIndex(months.length - 1)
    // 기간이 바뀔 때만 끝 달로 돌아갑니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from, to])
  /* 곡선에서 다른 달의 날을 고르면 그 달을 폅니다 — 고른 날이 안 보이면 두 그림이
     같은 날을 가리키는지 알 수 없습니다. */
  useEffect(() => {
    if (picked === null) return
    const at = months.indexOf(picked.slice(0, 6))
    if (at >= 0) setIndex(at)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [picked])
  const month = months[Math.min(Math.max(index, 0), months.length - 1)] ?? to.slice(0, 6)
  const days = monthWeekdays(month)
  const lead = days.length > 0 ? weekdayOf(days[0]) - 1 : 0
  const inside = days.filter((day) => day >= from && day <= to)
  const won = currency === 'KRW'
  const cells = useRef(new Map<string, HTMLButtonElement>())
  /* 초점이 설 칸 하나 — 고른 날이 이 달에 있으면 그 날, 없으면 이 달 기간 안의 끝 날. */
  const home = picked !== null && inside.includes(picked) ? picked : inside[inside.length - 1]

  const move = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      onPick(null, 'key')
      return
    }
    const now = inside.indexOf(document.activeElement instanceof HTMLElement ? (document.activeElement.dataset.day ?? '') : '')
    if (now < 0) return
    const step =
      event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowDown' ? 5 : event.key === 'ArrowUp' ? -5 : 0
    let next = now + step
    if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = inside.length - 1
    else if (step === 0) return
    event.preventDefault()
    /* 끝에서는 멈춥니다 — 달을 넘기는 것은 머리의 단추가 합니다. */
    next = Math.min(Math.max(next, 0), inside.length - 1)
    cells.current.get(inside[next])?.focus()
  }

  const label = (value: string) => {
    const year = Number(value.slice(0, 4))
    const same = months[0]?.slice(0, 4) === months[months.length - 1]?.slice(0, 4)
    return same ? `${Number(value.slice(4, 6))}월` : `${year}년 ${Number(value.slice(4, 6))}월`
  }

  return (
    <section
      className="trend-cal"
      aria-label={`${valueName} 달력`}
      /* 짙기 세 단의 몫은 **여기 한 자리**에서 CSS 로 내려보냅니다. */
      style={
        {
          '--trend-shade-1': `${SHADE_MIX[0]}%`,
          '--trend-shade-2': `${SHADE_MIX[1]}%`,
          '--trend-shade-3': `${SHADE_MIX[2]}%`,
        } as React.CSSProperties
      }
    >
      <div className="trend-cal-head">
        <h3 className="trend-title">{valueName} 달력</h3>
        {months.length > 1 ? (
          <span className="trend-cal-where">
            <span className="trend-cal-nav">
              <button
                type="button"
                className="btn btn-quiet trend-cal-step"
                aria-label="앞 달"
                aria-disabled={index <= 0}
                onClick={() => index > 0 && setIndex(index - 1)}
              >
                ‹
              </button>
              <span className="trend-cal-month">{label(month)}</span>
              <button
                type="button"
                className="btn btn-quiet trend-cal-step"
                aria-label="다음 달"
                aria-disabled={index >= months.length - 1}
                onClick={() => index < months.length - 1 && setIndex(index + 1)}
              >
                ›
              </button>
            </span>
            {/* 한 번에 한 달만 보이므로, 기간이 이 달 밖으로 넘친다는 것을 적습니다.
                달을 넘겨도 바뀌지 않는 **기간 전체**입니다. */}
            {first !== undefined && last !== undefined && (
              <span className="trend-cal-span">
                기간 {shortDay(first)}~{shortDay(last)}
              </span>
            )}
          </span>
        ) : (
          <span className="trend-cal-month">{label(month)}</span>
        )}
        {/* 칠한 색마다 낱말을 붙입니다. 통화가 원이 아니면 칸 금액의 단위를 여기 한 번
            적습니다. */}
        <p className="trend-cal-legend">
          <span className="trend-cal-key">
            <span className="trend-cal-swatch is-up" aria-hidden="true" />
            이익
          </span>
          <span className="trend-cal-key">
            <span className="trend-cal-swatch is-down" aria-hidden="true" />
            손실 · 짙을수록 큼
          </span>
          <span className="trend-cal-key">
            <span className="trend-cal-swatch is-missing" aria-hidden="true" />
            받지 않은 날
          </span>
          {/* 받았고 손익이 0 인 날 — 칸에 서는 「받았음」 막대 그대로를 표지로 씁니다. */}
          <span className="trend-cal-key">
            <span className="trend-cal-zero-mark" aria-hidden="true" />0 인 날
          </span>
          {/* 받았으나 손익 칸이 빈 날. 칸에 적힌 그대로 「—」를 표지로 씁니다 — 무늬
              없는 바탕 네모는 0 인 날과 같아 보입니다. */}
          <span className="trend-cal-key">
            <span className="trend-cal-dash" aria-hidden="true">
              —
            </span>
            값 없는 날
          </span>
          {!won && currency && <span className="trend-cal-key">{currency}</span>}
          {/* 오늘 받은 값이 있을 때만 — 칸의 점선 그대로를 표지로 씁니다. */}
          {provisional !== null && (
            <span className="trend-cal-key">
              <span className="trend-cal-provisional" aria-hidden="true" />
              잠정(정산 전)
            </span>
          )}
        </p>
      </div>
      <div className="trend-cal-week" aria-hidden="true">
        {WEEK.map((one) => (
          <span key={one}>{one}</span>
        ))}
      </div>
      <div
        className="trend-cal-grid"
        role="group"
        aria-label={`${label(month)} 손익`}
        onKeyDown={move}
        onMouseLeave={onLeave}
        /* 초점이 달력을 떠나면 키보드로 고른 날을 걷습니다. */
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) onPick(null, 'key')
        }}
      >
        {Array.from({ length: Math.max(lead, 0) }, (_, at) => (
          <span key={`lead-${at}`} className="trend-cal-cell is-out" aria-hidden="true" />
        ))}
        {days.map((day) => {
          const date = Number(day.slice(6, 8))
          /* 기간 밖의 날은 자리만 남깁니다 — 숫자를 적으면 그날도 본 것으로 읽힙니다. */
          if (day < from || day > to) {
            return <span key={day} className="trend-cal-cell is-out" aria-hidden="true" />
          }
          const has = received.has(day)
          const value = has ? (received.get(day) ?? null) : null
          const shade = value === null ? 0 : shadeOf(value, widest)
          const face = !has
            ? 'is-missing'
            : value === null
              ? 'is-empty'
              : value === 0
                ? 'is-zero'
                : `${value > 0 ? 'is-up' : 'is-down'} is-s${shade}`
          const text = !has ? '—' : value === null ? '—' : value === 0 ? '0' : cellText(value, won)
          const said = !has
            ? '받지 않은 날'
            : value === null
              ? '값 없는 날'
              : `${valueName} ${signedMoney(value, money)}`
          const shaky = has && day === provisional
          return (
            <button
              key={day}
              type="button"
              ref={(node) => {
                if (node) cells.current.set(day, node)
                else cells.current.delete(day)
              }}
              data-day={day}
              className={`trend-cal-cell ${face}${shaky ? ' is-provisional' : ''}`}
              tabIndex={day === home ? 0 : -1}
              aria-pressed={picked === day}
              aria-label={`${Number(day.slice(4, 6))}월 ${date}일 · ${said}${shaky ? ' · 잠정' : ''}`}
              title={shaky ? '정산 전 잠정 값 — 다시 받으면 바뀔 수 있습니다' : undefined}
              onMouseEnter={() => onPick(day, 'mouse')}
              onFocus={() => onPick(day, 'key')}
            >
              <span className="trend-cal-date">{date}</span>
              <span className="trend-cal-value">{text}</span>
              {/* 0 인 날은 칠하지 않고 「받았다」만 칸 아래 작은 막대로 말합니다. */}
              {face === 'is-zero' && <span className="trend-cal-zero-mark" aria-hidden="true" />}
            </button>
          )
        })}
      </div>
    </section>
  )
}

/* ── 품목별 누적손익 ────────────────────────────────────── */

/** 품목별 누적손익 가로 막대. **해외만** 있습니다 — 국내에는 이 값을 주는 조회가
 *  없습니다. 이것은 이 앱이 이어 붙인 값이 아니라 **서버가 셈한 기간 합계**라,
 *  아래 줄에 그렇다고 적습니다. */
function ProductBars({ from, to }: { from: string; to: string }) {
  const entry = useListOnce<ServerRealized>('overseas', 'cumulative', undefined, { from, to })
  /* **아직·없음·못 받음을 가릅니다.** 셋이 같은 얼굴이면, 못 받은 것을 「없다」로
     읽고 그 기간에 거래가 없었다고 생각하게 됩니다. */
  if (entry.rows === null) {
    /* **답의 상태가 얼굴을 정합니다.** 「없다」는 서버가 0 줄로 답했을 때만
       참입니다 — 못 받았거나 아직 안 물은 것을 「없다」로 적으면, 있는 손익을
       없다고 말하는 화면이 됩니다. */
    const word =
      entry.status === 'failed'
        ? '누적손익을 받지 못했습니다'
        : entry.status === 'loading'
          ? '누적손익을 받는 중입니다'
          : '누적손익을 아직 받지 못했습니다'
    return <p className="trend-note">{word}</p>
  }
  const rows = entry.rows.filter((row) => (row.netPl ?? null) !== null)
  if (rows.length === 0) return <p className="trend-note">이 기간에 쌓인 손익이 없습니다</p>
  /* 품목 줄은 **그 품목의 통화 그대로** 옵니다 — 환산하는 것은 합계 줄뿐입니다. 그래서
     줄마다 제 통화의 단위·자릿수로 적고, 막대 길이도 **같은 통화 줄끼리만** 견줍니다
     (달러와 엔을 한 자로 재면 길이가 아무 뜻이 없습니다). */
  const codeOf = (row: ServerRealized) => (row.currency ?? '').trim().toUpperCase()
  const widestOf = new Map<string, number>()
  for (const row of rows) {
    const code = codeOf(row)
    widestOf.set(code, Math.max(widestOf.get(code) ?? 1, Math.abs(row.netPl ?? 0)))
  }
  /* 환산 통화 — **요청한 환산 통화**입니다. 이 조회는 환산 통화를 안 보내 서버 기본
     (원화)으로 오고, 답이 그 통화를 말하면(`conversionCurrency`) 그것을 씁니다. 합계 줄의
     `currency` 칸은 쓰지 않습니다: 답은 `{productName: 「USD의 KRW환산합계」, currency:
     "USD", netPl: -14912}` 처럼 칸은 품목 통화인데 값은 환산값으로 옵니다. */
  const said = entry.extra?.conversionCurrency
  const converted = typeof said === 'string' && said !== '' ? said : 'KRW'
  const total = entry.extra?.total as ServerRealized | null | undefined
  const totalValue = typeof total?.netPl === 'number' && Number.isFinite(total.netPl) ? total.netPl : null
  /* 품목이 한 통화뿐이면 합계가 없어도 따로 말할 것이 없습니다 — 줄마다 단위가 섭니다. */
  const mixed = new Set(rows.map(codeOf)).size > 1
  return (
    <>
      <ul className="trend-products">
        {rows.map((row, index) => {
          const value = row.netPl ?? 0
          const name = row.productName ?? row.productCode ?? '—'
          const code = codeOf(row)
          const widest = widestOf.get(code) ?? 1
          return (
            <li key={`${row.productCode ?? index}`} className="trend-product">
              <span className="trend-product-name" title={name}>
                {name}
              </span>
              <span className="trend-product-bar">
                {/* 0 도 자리를 남깁니다 — 방향이 없어 본문색이고, 길이는 눈에 띄지
                    않을 만큼만 둡니다. */}
                <span
                  className={`trend-bar ${value > 0 ? 'is-up' : value < 0 ? 'is-down' : 'is-flat'}`}
                  style={{ width: value === 0 ? '2px' : `${(Math.abs(value) / widest) * 100}%` }}
                />
              </span>
              <span className="trend-product-value">
                {code === '' ? (
                  <span className="dead">—</span>
                ) : (
                  /* 값과 단위를 한 덩어리로 — 「+25,000 JPY」. 자릿수 칸을 따로 잡지 않아
                     소수 없는 통화도 단위가 값 바로 뒤에 붙습니다. */
                  <span className={toneOf(value) || undefined}>
                    {value > 0 ? '+' : ''}
                    {moneyIn(value, code)}
                  </span>
                )}
              </span>
            </li>
          )
        })}
      </ul>
      {/* 환산한 합계는 **이 줄에만** 섭니다. 서버가 합계를 안 주면 그 사실을 적고, 품목이
          모두 환산 통화와 같으면 따로 말할 것이 없어 비웁니다. */}
      {totalValue !== null ? (
        <p className="trend-product-total">
          <span className="trend-product-total-name">{total?.productName ?? '합계'}</span>
          <span className={`trend-product-total-value ${toneOf(totalValue)}`.trim()}>
            {moneyIn(totalValue, converted) !== '—' && totalValue > 0 ? '+' : ''}
            {moneyIn(totalValue, converted)}
          </span>
        </p>
      ) : (
        mixed && (
          <p className="trend-product-total trend-product-total-none">
            합계는 {converted === 'KRW' ? '원화' : converted} 환산 기준으로 서버가 줄 때만 섭니다
          </p>
        )
      )}
      {/* 이 값만은 **이 앱이 이어 붙인 것이 아닙니다.** 위 그림과 만들어진 방법이
          달라 그 사실을 이 자리에 적습니다 — 합계 줄이나 안내 줄이 서면 그 줄이 이미
          서버의 합계를 말하므로 이 줄은 걷습니다. */}
      {totalValue === null && !mixed && <p className="trend-note">서버가 셈한 기간 합계</p>}
    </>
  )
}

/** 추이. **보기 전환과 무관하게 원화 환산 값**입니다 — 날마다 쌓아 두는 기록이
 *  원화로 합친 값만 담습니다. 통화별로 보는 중이면(`byCurrency`) 그 사실을 한
 *  줄로 적습니다.
 *
 *  위에서 아래로 기간 고르개 → 요약 카드 → 누적 손익 곡선과 손익 달력 → (해외)
 *  품목별 누적손익입니다. 곡선과 달력은 **같은 「고른 날」**을 씁니다 — 한쪽에서
 *  고르면 다른 쪽도 그 날을 가리킵니다. */
export function TrendPanel({ market, byCurrency = false }: { market: DepositMarket; byCurrency?: boolean }) {
  const [preset, setPreset] = useState<Preset>('5일')
  const [customFrom, setCustomFrom] = useState(() => asInput(backBusinessDays(5)))
  const [customTo, setCustomTo] = useState(() => asInput(kstDate()))

  const to = preset === '직접' ? customTo.replace(/-/g, '') : kstDate()
  const asked =
    preset === '직접'
      ? customFrom.replace(/-/g, '')
      : preset === '5일'
        ? backBusinessDays(5)
        : backMonths(preset === '1개월' ? 1 : 3)
  /* 상한을 넘겨 고르면 **앞을 잘라** 묻습니다. 그대로 물으면 한 번에 250 번
     넘게 조회를 내게 되고, 그동안 다른 탭이 밀립니다. 잘랐다는 사실은 아래
     줄이 말합니다 — 고른 기간과 그린 기간이 다르면 그것도 값의 일부입니다. */
  const floor = capped(to, MAX_DAYS)
  const from = asked < floor ? floor : asked
  const clipped = from !== asked

  /* **기본 기간만 저절로 받습니다.** 긴 기간은 수십·수백 번을 묻게 되어,
     세그를 누른 것만으로 그만큼 나가면 안 됩니다 — 한 번 더 누르게 합니다. */
  const auto = preset === '5일'
  const state = useTrendPeriod(market, from, to, auto)
  const [boxRef, width] = useBoxWidth()
  const overseas = market === 'overseas'

  /* 금액의 통화·자릿수는 **답이 실어 준 대로**입니다(예탁자산 탭과 같은 규칙).
     해외 기본 답은 원화 환산이지만 서버가 다른 통화로 답하면 그대로 따릅니다 —
     여기서 「원」으로 못 박으면 머리 띠와 그래프가 같은 값을 다른 통화로
     말하게 됩니다. */
  const shown = state.days.length > 0 ? state.days[state.days.length - 1].value : null
  const overseasShown = shown !== null && !isDomesticDeposit(shown) ? shown : null
  const decimals = overseas ? (overseasShown?.decimals ?? 2) : 0
  const currency = overseas ? (overseasShown?.currency ?? null) : 'KRW'
  /* **환산한 값이면 그렇다고 적습니다.** 서버가 통화를 하나로 합쳐 준 값은
     그날의 환율이 섞여 있어, 환율이 움직인 날은 잔고가 그대로여도 값이
     움직입니다 — 그 사실을 낱말이 말해야 합니다. */
  const converted = overseasShown?.conversion === 'converted'

  const money = (value: number) => depositMoney(value, decimals, currency)

  /* 가로축은 **요청한 기간의 영업일 전부**입니다. 받은 날만 깔면 기간 앞뒤의
     아직 안 받은 자리가 그림에서 사라집니다. */
  const slots = periodDays(from, to)
  /* 그림에 주는 폭. 오른쪽 라벨 열을 뗀 나머지입니다 — 곡선과 평가손익 선이 같은
     값을 써야 가로축이 둘에서 같은 자리에 섭니다. */
  const plot = Math.max(width - EDGE_COL, 1)
  /* 며칠치인가. **받은 날만 셉니다** — 기간이 스물두 날이어도 다섯 날만 받았으면
     그림이 말하는 것은 다섯 날입니다. */
  const got = state.days.length
  const span = `${shortDay(from)}~${shortDay(to)}`
  /* 빠진 날 가운데 걷기가 물을 날 — 다시 물을 최근 두 날은 저절로 받으므로 셈에
     넣지 않습니다. */
  const waiting = daysToFill(state).length

  const summary = trendSummary(state.days, slots)
  const line = state.days.length > 0 ? (unrealisedOf(state.days[0].value)?.label ?? null) : null
  const cumPoints: Point[] = summary.cumulative.map((one) => ({ slot: one.slot, value: one.value }))
  const cumBySlot = new Map(summary.cumulative.map((one) => [one.slot, one]))
  const linePoints = line ? pointsOf(state.days, slots, (day) => unrealisedOf(day.value)?.value ?? null) : []
  const lastLine = linePoints.length > 0 ? linePoints[linePoints.length - 1] : null
  const byDay = new Map(state.days.map((one) => [one.day, one]))
  /* 달력이 읽는 값 — 받은 날과 그날 손익(칸이 비었으면 `null`). */
  const received = new Map(state.days.map((one) => [one.day, realisedOf(one.value).value ?? null]))
  /* 값이 선 영업일(차례대로). 키보드는 이 날들만 오갑니다 — 빈 날에 서면 읽을
     값이 없습니다. */
  const shownSlots = slots.flatMap((day, index) => (byDay.has(day) ? [index] : []))
  const curveName = '누적 순손익'
  /* 오늘 받은 값이 있으면 그날이 잠정 값입니다. 오늘이 기간 밖이거나 아직 못 받았으면
     잠정 표지를 하나도 세우지 않습니다. */
  const provisional = slots.find((day) => isProvisional(day) && byDay.has(day)) ?? null

  /* 고른 날. **마우스·키보드·달력이 한 자리를 씁니다** — 따로 고르면 두 그림이
     다른 날을 가리킵니다. 출처를 함께 적어, 마우스가 그림을 벗어날 때는 마우스가
     고른 날만 걷습니다(키보드로 고른 날은 그대로 남습니다). */
  const [picked, setPicked] = useState<{ slot: number; by: 'mouse' | 'key' } | null>(null)
  useEffect(() => {
    setPicked(null)
  }, [market, from, to])

  const plotsRef = useRef<HTMLDivElement>(null)
  const readRef = useRef<HTMLDivElement>(null)
  const [readLeft, setReadLeft] = useState(0)
  const pickedX = picked === null ? 0 : slotX(picked.slot, slots.length, plot)
  const readText = (() => {
    if (picked === null) return ''
    const day = slots[picked.slot]
    const held = byDay.get(day)
    if (!held) return `${shortDay(day)} · 받지 않은 날`
    const parts = [shortDay(day)]
    const point = cumBySlot.get(picked.slot)
    if (point) {
      parts.push(`누적 ${signedMoney(point.value, money)}`)
      parts.push(`그날 ${signedMoney(point.daily, money)}`)
    } else {
      parts.push('손익 값 없음')
    }
    const unrealised = unrealisedOf(held.value)
    if (unrealised && unrealised.value !== null) {
      parts.push(`${unrealised.label} ${signedMoney(unrealised.value, money)}`)
    }
    if (day === provisional) parts.push('잠정')
    return parts.join(' · ')
  })()
  /* 상자는 세로선 오른쪽에 서고, **그림 오른쪽 끝을 넘으면 왼쪽으로** 뒤집습니다.
     양쪽 어디에도 들지 않으면(그림이 좁고 글자가 길 때) 세로선 가운데에 두되 칸
     밖으로 나가지 않게 붙입니다 — 잘린 상자는 앞머리의 날짜부터 잃습니다. 글자
     폭은 날마다 달라 그려 본 뒤에 잽니다. */
  useLayoutEffect(() => {
    const box = readRef.current
    if (!box || picked === null) return
    const size = box.offsetWidth
    let next: number
    if (pickedX + 8 + size <= plot) next = pickedX + 8
    else if (pickedX - 8 - size >= 0) next = pickedX - 8 - size
    else next = Math.min(Math.max(pickedX - size / 2, 0), Math.max(width - size, 0))
    setReadLeft((held) => (held === next ? held : next))
  }, [picked, pickedX, plot, width, readText])

  const pickFromMouse = (event: React.MouseEvent<HTMLDivElement>) => {
    const box = plotsRef.current
    if (!box || slots.length === 0) return
    const x = event.clientX - box.getBoundingClientRect().left
    const step = Math.max(plot - PAD * 2, 1) / Math.max(slots.length - 1, 1)
    const slot = Math.min(Math.max(Math.round((x - PAD) / step), 0), slots.length - 1)
    setPicked((held) => (held?.slot === slot && held.by === 'mouse' ? held : { slot, by: 'mouse' }))
  }
  const pickFromKey = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      setPicked(null)
      return
    }
    if (shownSlots.length === 0) return
    const now = picked?.slot
    let next: number | undefined
    if (event.key === 'ArrowRight') {
      next = now === undefined ? shownSlots[shownSlots.length - 1] : shownSlots.find((slot) => slot > now)
    } else if (event.key === 'ArrowLeft') {
      next =
        now === undefined
          ? shownSlots[shownSlots.length - 1]
          : [...shownSlots].reverse().find((slot) => slot < now)
    } else if (event.key === 'Home') {
      next = shownSlots[0]
    } else if (event.key === 'End') {
      next = shownSlots[shownSlots.length - 1]
    } else {
      return
    }
    event.preventDefault()
    /* 끝에서는 멈춥니다 — 돌아 들어가면 첫 날과 끝 날이 붙은 것으로 읽힙니다. */
    if (next !== undefined) setPicked({ slot: next, by: 'key' })
  }
  const pickFromCalendar = (day: string | null, by: 'mouse' | 'key') => {
    if (day === null) {
      setPicked(null)
      return
    }
    const slot = slots.indexOf(day)
    if (slot < 0) return
    setPicked((held) => (held?.slot === slot && held.by === by ? held : { slot, by }))
  }
  const ticks = axisTicks(slots, plot)
  const gaps = slots.flatMap((day, index) => (byDay.has(day) ? [] : [index]))
  const gapWidth = Math.max(plot - PAD * 2, 1) / Math.max(slots.length - 1, 1)
  const plotNames = [curveName, ...(line ? [line] : [])].join('·')

  return (
    <div
      className="trend"
      /* 값 열의 폭은 **여기 한 자리**에서 정합니다. 그림의 셈이 이 수를 쓰고,
         CSS(값 열·축 날짜의 들임)는 이 변수를 읽습니다 — 두 자리에 따로 적으면
         한쪽만 고쳤을 때 축 날짜와 그림 끝이 어긋납니다. */
      style={{ '--trend-edge-col': `${EDGE_COL}px` } as React.CSSProperties}
    >
      <div className="dep-head">
        <div className="seg trend-period">
          {PRESETS.map((one) => (
            <button
              key={one}
              type="button"
              className="seg-item"
              aria-pressed={preset === one}
              onClick={() => setPreset(one)}
            >
              {one}
            </button>
          ))}
        </div>
        {preset === '직접' && (
          <>
            <input
              className="control acct-date"
              type="date"
              value={customFrom}
              max={customTo}
              onChange={(event) => setCustomFrom(event.target.value)}
            />
            <span className="t-label">~</span>
            <input
              className="control acct-date"
              type="date"
              value={customTo}
              min={customFrom}
              onChange={(event) => setCustomTo(event.target.value)}
            />
          </>
        )}
        {/* 오래 걸리는 조회라 **막대가 아니라 수로** 말합니다. 몇 번 남았는지는
            수가 말하고, 그만두는 길은 그 옆에 둡니다. */}
        {state.filling ? (
          <span className="trend-progress">
            {state.filled} / {state.target}일
            <button type="button" className="btn btn-quiet trend-stop" onClick={stopFilling}>
              멈추기
            </button>
          </span>
        ) : (
          /* **긴 기간은 눌러야 받습니다.** 몇 날을 얼마나 물을지 단추가 미리
             말합니다 — 누르고 나서야 아는 값이면 그만두는 판단도 늦습니다.
             빠진 날이 없으면 단추도 없습니다. */
          !auto &&
          waiting > 0 && (
            <button
              type="button"
              className="btn btn-quiet trend-fetch"
              onClick={() => void fillMissing(market)}
            >
              받기 — 빠진 {waiting}일치 · 약 {askSeconds(waiting)}초
            </button>
          )
        )}
      </div>

      {byCurrency && <p className="acct-view-note">추이는 원화 환산 값입니다</p>}

      {/* **이 묶음만 굴립니다.** 창이 낮으면 그림이 화면보다 길어지는데, 기간
          고르개와 「받기」는 조작이라 굴리는 자리 밖(위)에 둡니다. */}
      <div className="trend-body">
        {/* 쌓아 둔 파일을 못 읽으면 **지난 값이 통째로 비어 보입니다.** 그 사실을
            안 적으면 「거래가 없던 기간」으로 읽힙니다. */}
        {!state.stored && <p className="trend-note">지난 값을 읽지 못했습니다</p>}
        {clipped && (
          <p className="trend-note">한 번에 묻는 기간은 1년까지입니다 — 앞을 잘라 물었습니다</p>
        )}

        {got === 0 ? (
          /* 한 점도 없을 때만 회색 블록입니다. 한 점이라도 오면 그림이 섭니다. */
          <div className="trend-blank" aria-label={state.filling ? '받는 중' : '값 없음'}>
            <span className="dep-none">
              {state.filling ? '받는 중입니다' : '이 기간에 받아 둔 값이 없습니다'}
            </span>
          </div>
        ) : (
          <>
            <Cards
              summary={summary}
              overseas={overseas}
              money={money}
              level={lastLine ? { day: slots[lastLine.slot], value: lastLine.value } : null}
              provisional={provisional !== null}
            />

            <div className="trend-row">
              {/* 그림 폭은 **이 칸에서** 잽니다 — 달력과 나란히 서므로 칸 폭이 곧
                  그림 폭입니다. */}
              <div className="trend-curve" ref={boxRef}>
                {/* 곡선(과 해외의 평가손익 선)을 한 묶음으로 둡니다. 빈 날 띠와 읽기
                    세로선이 **묶음을 관통**해야 같은 날을 한눈에 맞춰 봅니다. 키보드
                    초점도 이 묶음 하나가 받습니다. */}
                <div className="trend-figure">
                  <div
                    className="trend-plots"
                    ref={plotsRef}
                    tabIndex={0}
                    role="group"
                    aria-label={`${plotNames} 그림 — 좌우 화살표로 날을 고릅니다`}
                    aria-describedby="trend-read"
                    onMouseMove={pickFromMouse}
                    onMouseLeave={() => setPicked((held) => (held?.by === 'mouse' ? null : held))}
                    onKeyDown={pickFromKey}
                    onBlur={() => setPicked((held) => (held?.by === 'key' ? null : held))}
                  >
                    {/* 값이 안 선 영업일(안 받음)의 옅은 띠. 선은 그 날을 건너
                        이어지지 않고, 띠가 「이 날은 비었다」를 말합니다. */}
                    <svg className="trend-under" width={plot} aria-hidden="true">
                      {gaps.map((slot) => (
                        <rect
                          key={slot}
                          className="trend-gap"
                          x={Math.max(slotX(slot, slots.length, plot) - gapWidth / 2, 0)}
                          y={0}
                          width={gapWidth}
                          height="100%"
                        />
                      ))}
                    </svg>

                    <section className="trend-card">
                      <h3 className="trend-title">{curveName}</h3>
                      <CumulativeChart
                        points={cumPoints}
                        count={slots.length}
                        width={plot}
                        height={overseas ? HEIGHT.overseas : HEIGHT.domestic}
                        money={money}
                        name={curveName}
                        picked={picked?.slot ?? null}
                      />
                    </section>

                    {line && (
                      <section className="trend-card">
                        <h3 className="trend-title">{line}</h3>
                        <LineChart
                          points={linePoints}
                          count={slots.length}
                          width={plot}
                          height={HEIGHT.level}
                          money={money}
                          name={line}
                          picked={picked?.slot ?? null}
                        />
                      </section>
                    )}

                    <svg className="trend-over" width={plot} aria-hidden="true">
                      {picked !== null && (
                        <line className="trend-cross" x1={pickedX} y1={0} x2={pickedX} y2="100%" />
                      )}
                    </svg>
                    {/* 고른 날의 값. 바뀔 때마다 화면 읽기 프로그램이 읽습니다. 고른
                        날이 없으면 비어 있고 보이지 않습니다. */}
                    <div
                      id="trend-read"
                      ref={readRef}
                      className="trend-read"
                      aria-live="polite"
                      hidden={picked === null}
                      style={{ left: readLeft }}
                    >
                      {readText}
                    </div>
                  </div>

                  {/* 가로 날짜는 **묶음이 함께 쓰는 것**이라 맨 아래 한 번만 적습니다. */}
                  <div className="trend-axis" style={{ width: plot }}>
                    {ticks.map((slot, index) => (
                      <span
                        key={slot}
                        className={`trend-tick${index === 0 ? ' is-first' : index === ticks.length - 1 ? ' is-last' : ''}`}
                        style={{ left: slotX(slot, slots.length, plot) }}
                      >
                        {shortDay(slots[slot])}
                      </span>
                    ))}
                  </div>
                </div>
                {/* 누적은 받은 날만 더합니다. 더하지 않은 날이 있으면 그 수를 적습니다. */}
                {summary.blankDays > 0 && (
                  <p className="trend-note">빈 날 {summary.blankDays}일은 더하지 않았습니다</p>
                )}
              </div>

              <PlCalendar
                valueName="순손익"
                provisional={provisional}
                from={from}
                to={to}
                first={slots[0]}
                last={slots[slots.length - 1]}
                received={received}
                widest={summary.widest}
                money={money}
                currency={currency}
                picked={picked === null ? null : (slots[picked.slot] ?? null)}
                onPick={pickFromCalendar}
                onLeave={() => setPicked((held) => (held?.by === 'mouse' ? null : held))}
              />
            </div>
            <p className="trend-note">
              {converted && '원화 환산 · '}날짜마다 물어 이은 값입니다 · {span} 중 {got}일치
            </p>
          </>
        )}

        <section className="trend-card">
          <h3 className="trend-title">품목별 누적손익</h3>
          {overseas ? (
            <ProductBars from={from} to={to} />
          ) : (
            <p className="trend-note">국내는 누적손익을 주는 API 가 없습니다</p>
          )}
        </section>
      </div>
    </div>
  )
}
