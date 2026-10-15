import { useId, useState } from 'react'
import { Num } from './number'

/* 최근 흐름을 한 줄로 보여주는 선. 홈 관심 첫 타일이 씁니다.
 *
 * 선을 요청 기간 폭에 비례해 그리고 오른쪽 끝(가장 최근)에 붙입니다.
 * 봉이 며칠치인지를 글자가 아니라 길이가 말하므로 「몇 개 이하면 짧다」는
 * 판정선을 정할 필요가 없고, 화면이 말할 수 있는 것(자료가 얼마나 있나)만
 * 말하게 됩니다 — 거래가 있었는지 없었는지는 우리가 알 수 없습니다.
 *
 * **색은 전일 종가 대비입니다.** 전일 종가에 점선 기준선을 긋고, 선이 그보다
 * 위에 있는 구간은 상승색, 아래에 있는 구간은 하락색으로 칠합니다. 선과 기준선
 * 사이에는 같은 색을 옅게 깝니다. 오늘 등락 하나로 선 전체를 칠하면, 20일 동안
 * 오르다 오늘 하루 내린 종목이 통째로 「내린 선」이 됩니다.
 *
 * 전일 종가를 모르면 기준선·채움 없이 무채 선만 그립니다 — 무엇 대비인지 모르는
 * 색은 지어낸 방향입니다. */

/** 스파크라인이 덮는 기간(영업일). 선 길이는 이 기간 대비 받은 봉 개수입니다. */
export const SPARK_DAYS = 20

interface Props {
  points: number[] | null
  /** 조회 전에는 자리만 잡습니다. */
  loaded: boolean
  width?: number
  height?: number
  /** 담긴 자리 폭에 맞춰 늘어납니다. 표 안처럼 폭이 고정인 곳에서는 끕니다. */
  stretch?: boolean
  /** 기준값(전일 종가). 선의 위아래 색과 기준선이 여기서 나옵니다. **모르면
   *  `null`** 이고, 그때는 무채 선만 섭니다. 선 색은 이 값 하나에서만 나옵니다. */
  base?: number | null
  /** 점마다의 시각. 있으면 마우스를 올렸을 때 값과 함께 뜹니다. */
  times?: string[]
  /** 값에 붙는 소수 자릿수. 툴팁과 기준값 글자에서 씁니다. */
  decimals?: number
}

export function Spark({
  points,
  loaded,
  width = 56,
  height = 24,
  stretch,
  base = null,
  times,
  decimals = 2,
}: Props) {
  /* 마우스가 올라간 점. 선은 값을 형태로만 말하므로, 정확한 값이 필요한
     순간에는 물어볼 수 있어야 합니다. */
  const [at, setAt] = useState<number | null>(null)
  /* 한 화면에 선이 여럿일 수 있어 잘라 내기 이름이 겹치면 안 됩니다. */
  const clipId = useId()

  /* 늘어나는 자리에서는 크기를 CSS 가 정합니다. 인라인 높이를 주면 그것이
     이겨서, 남는 자리를 받으라고 만든 요소가 제 높이를 못 벗어납니다. */
  const style = stretch ? { width: '100%' } : { width, height }

  const baseValue = base !== null && Number.isFinite(base) ? base : null
  const known = baseValue !== null
  const frameClass = `spark-frame${stretch ? ' spark-frame-stretch' : ''}`
  /* 기준값 한 줄. **모를 때도 자리는 잡습니다**(보이지 않게) — 선이 올 때,
     기준을 알게 될 때 아래 목록이 오르내리지 않습니다. 선 안에 글자를 쓰면
     가로로 늘어나는 상자라 글자가 찌그러지므로 선 아래에 둡니다. */
  const blankLabel = (
    <span className="spark-base-label is-blank" aria-hidden="true">
      전일 종가
    </span>
  )
  const baseLabel =
    baseValue !== null ? (
      <span className="spark-base-label">
        <span className="spark-base-mark" aria-hidden="true">
          ┄
        </span>
        전일 종가 <Num value={baseValue} decimals={decimals} />
      </span>
    ) : (
      blankLabel
    )

  // 조회 전에는 회색 블록으로 선이 설 자리를 잡습니다(높이는 담는 쪽 CSS).
  if (!loaded) {
    return (
      <span className={frameClass}>
        <span className="spark-empty" style={style} aria-hidden="true" />
        {blankLabel}
      </span>
    )
  }
  /* 봉이 하나도 없으면 선 대신 까닭을 적습니다. **선이 설 자리 높이는 그대로
     둡니다** — 글자 한 줄로 줄면 값이 올 때마다 아래 목록이 오르내립니다. */
  if (!points || points.length === 0) {
    return (
      <span className={frameClass}>
        <span className="spark-none" style={stretch ? undefined : { width }}>
          자료 없음
        </span>
        {/* 기준선이 없는 자리라 그 이름도 자리만 잡습니다. */}
        {blankLabel}
      </span>
    )
  }

  /* 세로 범위에 기준값을 넣습니다 — 선이 전부 기준선 위(또는 아래)여도 기준선이
     상자 안에 서야 「얼마나 위인가」가 읽힙니다. */
  const values = baseValue !== null ? [...points, baseValue] : points
  const high = Math.max(...values)
  const low = Math.min(...values)
  const span = high - low
  const drawn = Math.min(width, (points.length / SPARK_DAYS) * width)
  const left = width - drawn
  const top = 2
  const bottom = height - 2

  /* 한 점이면 오른쪽 끝입니다. 끝에 딱 붙이면 둥근 점의 절반이 상자 밖으로
     잘리므로 점 반지름만큼 안쪽입니다. */
  const xAt = (i: number) =>
    points.length === 1 ? width - 3 : left + (i / (points.length - 1)) * drawn
  /* 범위가 0 이면(모든 값과 기준이 같음) 가운데에 섭니다 — 바닥에 붙이면 「가장
     낮다」로 읽힙니다. */
  const yAt = (value: number) =>
    span === 0 ? (top + bottom) / 2 : bottom - ((value - low) / span) * (bottom - top)

  const d =
    points.length === 1
      ? /* 길이 0 선에 둥근 끝을 주면 점이 됩니다. 원(circle)은 가로로만 늘어나는
           자리에서 타원이 되지만, 이 점은 선 굵기라 늘어나지 않습니다. */
        `M${xAt(0).toFixed(1)},${yAt(points[0]).toFixed(1)} l0,0`
      : points
          .map((value, i) => `${i === 0 ? 'M' : 'L'}${xAt(i).toFixed(1)},${yAt(value).toFixed(1)}`)
          .join(' ')

  /* 기준이 있고 범위가 있을 때만 두 색으로 나눕니다. 범위가 0 이면 선이 곧
     기준선이라 위도 아래도 아닙니다. 한 점은 나눌 선이 없어 점 하나의 색만
     기준과 견줍니다. */
  const split = known && span > 0 && points.length > 1
  const baseY = baseValue !== null ? yAt(baseValue) : null
  /* 선과 기준선 사이 면. 선을 따라가다 기준선 높이로 내려와 닫습니다 — 선이
     그려진 가로 구간만입니다. 한 점이면 면이 될 수 없습니다. */
  const area =
    split && points.length > 1 && baseY !== null
      ? `${d} L${xAt(points.length - 1).toFixed(1)},${baseY.toFixed(1)} L${xAt(0).toFixed(1)},${baseY.toFixed(1)} Z`
      : null

  /* 마우스 x 를 가장 가까운 점으로 옮깁니다. 점 사이에서 값을 지어내지
     않습니다 — 봉 하나가 하루이고, 그 사이에는 값이 없습니다. */
  const pick = (event: React.MouseEvent<SVGSVGElement>) => {
    if (!times) return
    const box = event.currentTarget.getBoundingClientRect()
    const ratio = (event.clientX - box.left) / box.width
    const i = Math.round(((ratio * width - left) / (drawn || 1)) * (points.length - 1))
    setAt(Math.min(points.length - 1, Math.max(0, i)))
  }

  /* 툴팁은 가리키는 점 위 가운데에 서되, 양 끝 가까이에서는 상자 안쪽으로
     붙입니다 — 가운데 정렬 그대로면 절반이 타일 밖으로 나가 잘립니다. */
  const tipAt = at === null ? 0 : xAt(at) / width
  const tipSide = tipAt < 0.15 ? ' spark-tip-start' : tipAt > 0.85 ? ' spark-tip-end' : ''

  const clipUp = `${clipId}-up`
  const clipDown = `${clipId}-down`

  return (
    <span className={frameClass}>
      <span className={`spark-wrap${stretch ? ' spark-wrap-stretch' : ''}`}>
        <svg
          className="spark"
          style={style}
          viewBox={`0 0 ${width} ${height}`}
          /* 늘어날 때는 가로만 늘립니다. 선의 자료 비율(요청 기간 대비 봉 개수)은
             가로로 고르게 늘어나므로 그대로 유지됩니다. */
          preserveAspectRatio={stretch ? 'none' : undefined}
          role="img"
          aria-label={`최근 흐름 ${points.length}일${known ? ', 전일 종가 대비' : ''}`}
          onMouseMove={pick}
          onMouseLeave={() => setAt(null)}
        >
          {split && baseY !== null && (
            <defs>
              {/* 기준선에서 위아래로 나누는 두 칸. 같은 선·면을 두 번 그리고 칸마다
                  제 색만 보이게 합니다. */}
              <clipPath id={clipUp}>
                <rect x={0} y={0} width={width} height={baseY} />
              </clipPath>
              <clipPath id={clipDown}>
                <rect x={0} y={baseY} width={width} height={height - baseY} />
              </clipPath>
            </defs>
          )}
          {area !== null && (
            <>
              <path className="spark-fill up" d={area} clipPath={`url(#${clipUp})`} />
              <path className="spark-fill down" d={area} clipPath={`url(#${clipDown})`} />
            </>
          )}
          {/* 기준선은 상자 전체 폭입니다 — 봉이 적어 선이 짧아도 기준은 기간 전체의
              것입니다. */}
          {baseY !== null && (
            <line
              className="spark-base"
              x1={0}
              x2={width}
              y1={baseY}
              y2={baseY}
              vectorEffect="non-scaling-stroke"
            />
          )}
          {split ? (
            <>
              <path className="spark-line up" d={d} clipPath={`url(#${clipUp})`} />
              <path className="spark-line down" d={d} clipPath={`url(#${clipDown})`} />
            </>
          ) : (
            <path
              className={`spark-line${points.length === 1 ? ' spark-point' : ''}${
                points.length === 1 && baseValue !== null ? ` ${pointTone(points[0], baseValue)}` : ''
              }`}
              d={d}
            />
          )}
          {at !== null && (
            <>
              {/* 세로선은 가로로 늘어나도 굵기가 안 변해야 합니다. 기준선 위에 섭니다. */}
              <line
                className="spark-cross"
                x1={xAt(at)}
                x2={xAt(at)}
                y1={top}
                y2={bottom}
                vectorEffect="non-scaling-stroke"
              />
              <path
                className="spark-dot"
                d={`M${xAt(at).toFixed(1)},${yAt(points[at]).toFixed(1)} l0,0`}
              />
            </>
          )}
        </svg>

        {at !== null && times && (
          <span className={`spark-tip${tipSide}`} style={{ left: `${tipAt * 100}%` }}>
            <span className="spark-tip-time">{times[at]}</span>
            <span className="spark-tip-value">
              {points[at].toLocaleString('ko-KR', {
                minimumFractionDigits: decimals,
                maximumFractionDigits: decimals,
              })}
            </span>
          </span>
        )}
      </span>
      {baseLabel}
    </span>
  )
}

/** 한 점일 때 그 점이 기준보다 위인지 아래인지. 같으면 무채입니다. */
function pointTone(value: number, base: number): string {
  return value > base ? 'up' : value < base ? 'down' : ''
}
