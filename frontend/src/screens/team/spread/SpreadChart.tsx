import { useEffect, useMemo, useRef, useState } from 'react'
import type { SpreadBars } from '../../../data/spread'
import { PALETTE } from '../../trade/chartIndicators'

/* 팀: 스프레드 실행의 차트 — 다리 가격과 실행기가 `ctx.log` 로 남긴 값 하나를 **축 셋**에 나눠 그리고, 체결 ●.
 *
 *   왼쪽 축          첫째로 고른 다리 (셋째부터 고른 다리도 이 축을 같이 씀)
 *   오른쪽 안쪽 축    둘째로 고른 다리
 *   오른쪽 바깥 축    실행기 값(`ctx.log`) — 오른쪽에 다리가 없으면 안쪽 자리로 당겨 그림
 *
 * 다리마다 값의 크기가 달라(4,200 대 2.4) 한 축에 다 그리면 한 선이 납작해집니다. 그래서 축마다 자기 선의
 * 최소~최대로 늘리고, 눈금 글자를 그 선과 같은 색으로 칠해 어느 축이 어느 선인지 보이게 합니다. 눈금 소수 자릿수는
 * 축의 범위로 정합니다(77.012 처럼 — 값이 좁은 범위에서만 움직여도 눈금이 같은 숫자로 겹치지 않게).
 * 점은 모두 서버가 기록에서 뽑은 것이라 화면이 다시 셈하지 않습니다. 봉이 끊긴 구간(장 쉼)은 선을 잇지 않고 비웁니다. */

/** 다리 선 색(앱 지표 팔레트). 실행기 값 선은 `LOG_COLOR`. */
const LEG_COLORS = [PALETTE[2][2], PALETTE[4][2], PALETTE[6][2], PALETTE[7][1]]
const LOG_COLOR = PALETTE[5][2]
/** 이 시간(ms)보다 벌어진 두 점은 잇지 않습니다 — 장 쉼·점심 같은 빈 구간. */
const GAP_MS = 15 * 60 * 1000
const HEIGHT = 320
/** 오른쪽 축 하나가 차지하는 폭(눈금 글자 자리). 오른쪽 축이 둘이면 두 배. */
const AXIS_W = 64
const PAD = { left: 64, top: 10, bottom: 24 }

interface Point {
  t: number
  v: number
}

/** 축 하나 — 값 범위, 눈금 소수 자릿수, 색, 이름. */
interface Axis {
  key: string
  lo: number
  hi: number
  dec: number
  color: string
}

function parseAt(at: string | null | undefined): number | null {
  if (!at) return null
  const t = Date.parse(at)
  return Number.isFinite(t) ? t : null
}

function pointsOf(rows: { at: string | null; close?: number; value?: number }[] | undefined, key: 'close' | 'value'): Point[] {
  const out: Point[] = []
  for (const row of rows ?? []) {
    const t = parseAt(row.at)
    const v = row[key]
    if (t !== null && typeof v === 'number' && Number.isFinite(v)) out.push({ t, v })
  }
  return out.sort((a, b) => a.t - b.t)
}

/** 가장 작은 값·가장 큰 값 — 펼침(`Math.min(...values)`)은 점이 수십만 개면 호출 스택을 넘겨 RangeError 라 고리로 셉니다. */
function extent(values: number[]): [number, number] {
  let lo = Infinity
  let hi = -Infinity
  for (const v of values) {
    if (v < lo) lo = v
    if (v > hi) hi = v
  }
  return [lo, hi]
}

function span(values: number[]): [number, number] {
  if (values.length === 0) return [0, 1]
  let [lo, hi] = extent(values)
  if (lo === hi) {
    const pad = Math.abs(lo) * 0.001 || 1
    lo -= pad
    hi += pad
  } else {
    const pad = (hi - lo) * 0.05
    lo -= pad
    hi += pad
  }
  return [lo, hi]
}

/** 눈금 소수 자릿수 — 눈금 한 칸(범위의 1/4)이 서로 다른 숫자로 보일 만큼. 0~6자리. */
function tickDecimals(lo: number, hi: number): number {
  const step = (hi - lo) / 4
  if (!(step > 0) || !Number.isFinite(step)) return 0
  return Math.min(6, Math.max(0, Math.ceil(-Math.log10(step))))
}

function axisOf(key: string, values: number[], color: string): Axis {
  const [lo, hi] = span(values)
  return { key, lo, hi, dec: tickDecimals(lo, hi), color }
}

function clockLabel(t: number, withDate: boolean): string {
  const d = new Date(t)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return withDate ? `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')} ${hh}:${mm}` : `${hh}:${mm}`
}

/** 선 한 줄의 경로 — 끊긴 구간마다 새로 시작합니다. */
function pathOf(points: Point[], x: (t: number) => number, y: (v: number) => number): string {
  let d = ''
  let prev: Point | null = null
  for (const p of points) {
    d += `${prev === null || p.t - prev.t > GAP_MS ? 'M' : 'L'}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`
    prev = p
  }
  return d
}

/** 고른 다리의 축 이름 — 고른 순서로 첫째 왼쪽, 둘째 오른쪽, 셋째부터 왼쪽. */
function legSide(order: number): 'left' | 'right' {
  return order === 1 ? 'right' : 'left'
}

export function SpreadChart({ bars, legNames }: { bars: SpreadBars | null; legNames: string[] }) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(640)
  useEffect(() => {
    const box = boxRef.current
    if (!box) return
    const observer = new ResizeObserver(() => setWidth(Math.max(280, box.clientWidth)))
    observer.observe(box)
    setWidth(Math.max(280, box.clientWidth))
    return () => observer.disconnect()
  }, [])

  /* 고른 다리·값. `null` = 아직 손대지 않음(기본: 앞의 두 다리, 첫 값). */
  const [legPick, setLegPick] = useState<string[] | null>(null)
  const [logPick, setLogPick] = useState<string | null>(null)
  const names = useMemo(
    () => (legNames.length > 0 ? legNames : Object.keys(bars?.legs ?? {})),
    [legNames, bars],
  )
  const logNames = Object.keys(bars?.logs ?? {})
  const shownLegs = (legPick ?? names.slice(0, 2)).filter((name) => names.includes(name))
  const shownLog = logPick === null ? (logNames[0] ?? '') : logPick

  const legSeries = shownLegs.map((name, order) => ({
    name,
    side: legSide(order),
    color: LEG_COLORS[Math.max(0, names.indexOf(name)) % LEG_COLORS.length],
    points: pointsOf(bars?.legs[name], 'close'),
  }))
  const logPoints = shownLog && logNames.includes(shownLog) ? pointsOf(bars?.logs[shownLog], 'value') : []

  const fills = (bars?.fills ?? [])
    .map((fill) => ({ ...fill, t: parseAt(fill.at) }))
    .filter((fill) => fill.t !== null && fill.leg !== null && shownLegs.includes(fill.leg) && typeof fill.price === 'number')

  const allT = [...legSeries.flatMap((s) => s.points.map((p) => p.t)), ...logPoints.map((p) => p.t)]
  const empty = allT.length === 0
  const [tLo, tHi] = extent(allT)
  const t0 = empty ? 0 : tLo
  const t1 = empty ? 1 : Math.max(tHi, t0 + 1)

  /* 축 셋. 다리 축의 범위에는 그 다리의 체결가도 넣는다(● 가 축 밖으로 나가지 않게). */
  const sideValues = (side: 'left' | 'right') => [
    ...legSeries.filter((s) => s.side === side).flatMap((s) => s.points.map((p) => p.v)),
    ...fills.filter((f) => legSeries.some((s) => s.side === side && s.name === f.leg)).map((f) => f.price as number),
  ]
  const leftLeg = legSeries.find((s) => s.side === 'left')
  const rightLeg = legSeries.find((s) => s.side === 'right')
  const left = axisOf('left', sideValues('left'), leftLeg?.color ?? 'currentColor')
  const rights: Axis[] = []
  if (rightLeg) rights.push(axisOf('leg', sideValues('right'), rightLeg.color))
  if (logPoints.length > 0) rights.push(axisOf('log', logPoints.map((p) => p.v), LOG_COLOR))
  const logAxis = rights.find((a) => a.key === 'log')
  const legRight = rights.find((a) => a.key === 'leg')

  const padRight = Math.max(1, rights.length) * AXIS_W
  const plotW = Math.max(10, width - PAD.left - padRight)
  const plotH = HEIGHT - PAD.top - PAD.bottom
  const x = (t: number) => PAD.left + ((t - t0) / (t1 - t0)) * plotW
  const yOf = (a: Axis) => (v: number) => PAD.top + (1 - (v - a.lo) / (a.hi - a.lo)) * plotH
  const yLeft = yOf(left)
  const yLegRight = legRight ? yOf(legRight) : yLeft
  const yLog = logAxis ? yOf(logAxis) : yLeft
  const yLeg = (name: string) => (legSeries.find((s) => s.name === name)?.side === 'right' ? yLegRight : yLeft)
  const withDate = new Date(t0).toDateString() !== new Date(t1).toDateString()
  const fmt = (v: number, dec: number) => v.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec })
  const ticks = [0, 1, 2, 3, 4]
  /** 오른쪽 축 `i` 번째(0 = 안쪽)의 축선 x. 눈금 글자는 그 오른쪽에. */
  const rightX = (i: number) => PAD.left + plotW + i * AXIS_W

  const toggle = (name: string) =>
    setLegPick(shownLegs.includes(name) ? shownLegs.filter((one) => one !== name) : [...shownLegs, name])
  const sideText = (name: string) => {
    const s = legSeries.find((one) => one.name === name)
    return s ? (s.side === 'right' ? '(오른쪽 축)' : '(왼쪽 축)') : ''
  }

  return (
    <div className="pyrun-chart">
      <div className="pyrun-legend">
        <span>1분 종가</span>
        {names.map((name, at) => (
          <label key={name} className="spread-chip">
            <input type="checkbox" checked={shownLegs.includes(name)} onChange={() => toggle(name)} />
            <i className="pyrun-swatch" style={{ background: LEG_COLORS[at % LEG_COLORS.length] }} />
            {name} {sideText(name)}
          </label>
        ))}
        {logNames.length > 0 && (
          <label className="spread-chip">
            <i className="pyrun-swatch" style={{ background: LOG_COLOR }} />
            <select
              className="control spread-log-select"
              aria-label="오른쪽 바깥 축에 그릴 값"
              value={shownLog}
              onChange={(e) => setLogPick(e.target.value)}
            >
              <option value="">값 없음</option>
              {logNames.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            {rightLeg ? '(오른쪽 바깥 축)' : '(오른쪽 축)'}
          </label>
        )}
        <span className="pyrun-legend-marks">● 체결 (매수 붉게 · 매도 푸르게)</span>
      </div>
      <div className="pyrun-chart-frame" ref={boxRef}>
        <svg className="spread-chart-svg" width={width} height={HEIGHT} role="img" aria-label="스프레드 다리 가격과 실행기 값 차트">
          {!empty &&
            ticks.map((i) => {
              const f = i / 4
              const yy = PAD.top + f * plotH
              return (
                <g key={i}>
                  <line className="spread-grid" x1={PAD.left} x2={PAD.left + plotW} y1={yy} y2={yy} />
                  {leftLeg && (
                    <text className="spread-tick" x={PAD.left - 6} y={yy + 4} textAnchor="end" style={{ fill: left.color }}>
                      {fmt(left.hi - f * (left.hi - left.lo), left.dec)}
                    </text>
                  )}
                  {rights.map((a, at) => (
                    <text key={a.key} className="spread-tick" x={rightX(at) + 6} y={yy + 4} textAnchor="start" style={{ fill: a.color }}>
                      {fmt(a.hi - f * (a.hi - a.lo), a.dec)}
                    </text>
                  ))}
                  <text className="spread-tick" x={PAD.left + f * plotW} y={HEIGHT - 6} textAnchor={i === 0 ? 'start' : i === 4 ? 'end' : 'middle'}>
                    {clockLabel(t0 + f * (t1 - t0), withDate)}
                  </text>
                </g>
              )
            })}
          {!empty && leftLeg && (
            <line className="spread-axis" x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={PAD.top + plotH} style={{ stroke: left.color }} />
          )}
          {!empty &&
            rights.map((a, at) => (
              <line key={a.key} className="spread-axis" x1={rightX(at)} x2={rightX(at)} y1={PAD.top} y2={PAD.top + plotH} style={{ stroke: a.color }} />
            ))}
          {legSeries.map((s) => (
            <path key={s.name} d={pathOf(s.points, x, s.side === 'right' ? yLegRight : yLeft)} fill="none" stroke={s.color} strokeWidth={1.5} />
          ))}
          {logPoints.length > 0 && <path d={pathOf(logPoints, x, yLog)} fill="none" stroke={LOG_COLOR} strokeWidth={1.5} strokeDasharray="4 2" />}
          {fills.map((fill, at) => (
            <circle
              key={`${fill.at}-${at}`}
              className={(fill.qty ?? 0) > 0 ? 'spread-fill-buy' : 'spread-fill-sell'}
              cx={x(fill.t as number)}
              cy={yLeg(fill.leg as string)(fill.price as number)}
              r={4}
            >
              <title>{`${fill.leg} ${(fill.qty ?? 0) > 0 ? '+' : ''}${fill.qty ?? ''} @ ${fill.price}`}</title>
            </circle>
          ))}
        </svg>
        {empty && <p className="pyrun-chart-empty">{bars ? '아직 그릴 점이 없습니다 (분 단위 기록이 쌓이면 보입니다)' : '차트를 받는 중입니다'}</p>}
      </div>
    </div>
  )
}
