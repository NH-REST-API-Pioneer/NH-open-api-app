/* 차트에 그린 도형의 저장.
 *
 * 도형은 종목에 붙습니다. 코스피200 에 그은 추세선이 WTI 위에 나타나면 안
 * 되므로 종목 코드별로 나눠 두고, 차트가 그 종목으로 바뀔 때 다시 그립니다.
 *
 * 저장하는 것은 이름·점·색·굵기뿐입니다. 라이브러리 안의 id 는 만들 때마다
 * 새로 받으므로 남기지 않습니다.
 */

import { setUiValue, uiValue } from '../../data/uiState'
import { DEFAULT_LINE_SIZE, PALETTE } from './chartIndicators'

export interface DrawingStyle {
  color: string
  size: number
}

export interface DrawingPoint {
  timestamp: number
  value: number
}

export interface Drawing {
  name: string
  points: DrawingPoint[]
  style: DrawingStyle
}

export const DRAWINGS_KEY = 'nh.trade.drawings'

/* 처음 그리는 선의 색. 초록 계열입니다 — 이 앱에서 초록은 「사용자가 한 것」이고,
 * 봉(빨강·파랑)과 지표 기본색(주황·보라·초록·회색) 어느 것과도 같지 않습니다. */
export const DEFAULT_DRAWING_STYLE: DrawingStyle = { color: PALETTE[7][1], size: DEFAULT_LINE_SIZE }

interface Store {
  /** 종목 코드 → 도형 목록 */
  byCode: Record<string, Drawing[]>
  /** 마지막에 쓴 색·굵기. 새 도형의 기본값입니다. */
  last: DrawingStyle
}

/* 그린 것은 사용자 홈의 파일에 남습니다. 담긴 것이 예전 모양이거나 깨져 있을
 * 수 있어, 읽을 때마다 꼴을 확인하고 아니면 빈 것으로 봅니다. */
function read(): Store {
  const raw = uiValue<Partial<Store> | null>(DRAWINGS_KEY, null)
  return {
    byCode: raw?.byCode && typeof raw.byCode === 'object' ? raw.byCode : {},
    last:
      raw?.last && typeof raw.last.color === 'string' && typeof raw.last.size === 'number'
        ? raw.last
        : DEFAULT_DRAWING_STYLE,
  }
}

function write(store: Store): void {
  setUiValue(DRAWINGS_KEY, store)
}

export function loadDrawings(code: string): Drawing[] {
  return read().byCode[code] ?? []
}

export function saveDrawings(code: string, drawings: Drawing[]): void {
  const store = read()
  if (drawings.length === 0) delete store.byCode[code]
  else store.byCode[code] = drawings
  write(store)
}

export function lastDrawingStyle(): DrawingStyle {
  return read().last
}

export function rememberDrawingStyle(style: DrawingStyle): void {
  const store = read()
  store.last = style
  write(store)
}

/** 도형 하나의 색·굵기를 라이브러리 스타일로 옮깁니다. 선·사각형·글자가 같은 색을 씁니다. */
export function overlayStyles(style: DrawingStyle) {
  return {
    point: {
      color: style.color,
      borderColor: style.color,
      activeColor: style.color,
      activeBorderColor: style.color,
    },
    line: { color: style.color, size: style.size },
    rect: { color: `${style.color}22`, borderColor: style.color, borderSize: style.size },
    polygon: { color: `${style.color}22`, borderColor: style.color },
    text: { color: '#ffffff', backgroundColor: style.color },
  }
}
