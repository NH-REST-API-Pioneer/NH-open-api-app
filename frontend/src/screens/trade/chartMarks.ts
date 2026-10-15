import { registerOverlay, type Chart, type OverlayFigure } from 'klinecharts'
import type { FillSnapshot } from '../../data/strategyRuns'

/* 차트 위의 매매 표시.
 *
 * 「어디서 사고팔았는지」를 가격 흐름 위에서 보는 층입니다. 도형(사용자가
 * 그리는 선·상자)과 **다른 무리**로 둡니다 — 도형은 종목·봉마다 저장소에서
 * 다시 올라오고 「모두 지우기」로 한꺼번에 사라지는데, 매매 표시는 실행이
 * 주는 값이라 그 두 가지에 휩쓸리면 안 됩니다.
 */

/** 도형이 속한 무리. 다시 올리기·모두 지우기가 이 무리만 건드립니다. */
export const DRAW_GROUP = 'draw'

/** 매매 표시가 속한 무리. */
export const MARK_GROUP = 'mark'

/** 표시의 갈래. **체결만 기본으로 켭니다** — 조건이 맞았다는 것만으로 체결
 *  자리에 표를 찍으면 사지도 않은 자리가 산 자리처럼 보입니다. */
export type MarkKind = 'fill' | 'signal' | 'order'

export const MARK_KIND_LABEL: Record<MarkKind, string> = {
  fill: '체결',
  signal: '신호',
  order: '주문',
}

export interface TradeMark {
  id: string
  kind: MarkKind
  /** 이 표가 앉을 봉의 시각. 주문·신호 시각이 아니라 **체결이 실제로 붙은
   *  봉**입니다(원본 §8). */
  time: number
  /** 체결 하나면 그 값, 여럿이 묶였으면 **수량 가중평균**입니다(`mergeMarks`). */
  price: number
  /** 그 종목의 가격 자릿수. **표지가 들고 다닙니다** — 묶인 가격을 이 자릿수로
   *  반올림해 고정하고, 팝오버도 같은 자릿수로 적습니다. 한 곳이 두 자리로
   *  박아 두면 자릿수가 다른 종목에서 없는 자리가 생기거나 잘립니다. */
  decimals: number
  /** B 는 항상 매수, S 는 항상 매도입니다. 진입인지 청산인지는 색이나 글자
   *  모양이 아니라 아래 `intent` 가 말합니다 — 매수가 숏 청산일 수도 있습니다. */
  side: 'buy' | 'sell'
  intent: '진입' | '청산'
  qty: number
  /** 같은 봉에 여러 체결이 묶였으면 그 수. 1 이면 표시하지 않습니다. */
  count: number
  /** 팝오버에 세우는 값들. */
  strategy: string
  version: string
  /** 가상인지 계좌 체결인지. 검증은 「가상」, 진행은 계좌입니다. */
  virtual: boolean
  at: string
  /** 그 체결이 난 까닭의 코드(`signal`·`stop`…). 묶인 표지는 묶인 줄들의 코드를
   *  **겹치지 않게 처음 나온 차례로** 모읍니다 — 화면에 세울 말은 상세가 정합니다.
   *  까닭을 모르는 표지는 비어 있습니다. */
  reasons?: string[]
  /** 체결이 난 시각(ms). 묶인 표지에서 **가장 이른 체결**을 가리는 데 씁니다. */
  firstAt?: number
  /** 그 체결(묶이면 가장 이른 체결)의 당시 지표. 칸이 없으면 옛 기록, `null` 이면
   *  우리가 내지 않은 주문입니다 — 둘 다 상세에 그 절을 세우지 않습니다. */
  snapshot?: FillSnapshot | null
  /** 수수료(묶이면 합). 묶인 체결 가운데 하나라도 칸이 없으면 모르는 값입니다. */
  fee?: number
  /** 돈을 적을 통화(「원」·「USD」). */
  currency?: string
}

/* 표 하나의 크기. 봉 위에 얹히므로 작게 두고, 글자 하나가 들어갈 만큼만
 * 잡습니다. */
const R = 8

/* 표를 쌓는 거리. 지름 16 에 틈 2 입니다. 같은 쪽 두 표의 중심이 가로·세로
 * 모두 이보다 가까우면 겹치므로, 나중 표를 봉에서 먼 쪽으로 한 층 옮깁니다. */
const STACK_STEP = 18
/* 층은 셋까지입니다. 넷째부터는 셋째 층에 겹칩니다 — 더 쌓으면 표가 봉에서
 * 멀어져 어느 봉의 것인지 못 읽습니다. 겹친 표도 누르면 제 상세가 뜹니다. */
const STACK_LAYERS = 3

/** 표에 넘기는 값. 표 하나와, 같은 목록의 표들이 함께 쓰는 층 셈의 이름입니다.
 *  층 셈 자체는 여기 싣지 않습니다 — 라이브러리가 넘긴 값을 통째로 복사해 두어
 *  메서드가 떨어집니다. 이름으로 `stacks` 에서 찾습니다. */
export interface MarkData {
  mark: TradeMark
  stack: string
}

const stacks = new Map<string, MarkStack>()
let stackSeq = 0

/** 표 목록 하나의 층 셈을 세우고 그 이름을 돌려줍니다. 표를 내릴 때 `dropStack`. */
export function holdStack(marks: readonly TradeMark[]): string {
  stackSeq += 1
  const name = `stack-${stackSeq}`
  stacks.set(name, new MarkStack(marks))
  return name
}

export function dropStack(name: string): void {
  stacks.delete(name)
}

/** 같은 쪽 표들의 층을 셉니다. 표의 자리는 확대·이동·축 범위에 따라 달라지므로
 *  그때마다 다시 셉니다 — 봉 폭·보이는 구간·칸 높이·첫 표의 자리가 그대로면
 *  앞서 센 것을 씁니다.
 *
 *  **가로만 보지 않고 실제로 겹치는지 봅니다.** 값이 가파르게 움직이는 자리에서는
 *  이웃한 표의 높이가 이미 한 층 넘게 달라, 가로만 보고 올리면 올린 표가 앞 표
 *  위에 도로 앉습니다. 반대로 가로는 가까워도 높이가 멀면 올릴 까닭이 없습니다. */
class MarkStack {
  private layers = new Map<string, number>()
  private key = ''

  constructor(private readonly marks: readonly TradeMark[]) {}

  layerOf(chart: Chart, paneId: string, id: string): number {
    const probe = this.marks[0]
    const at = probe
      ? (chart.convertToPixel({ timestamp: probe.time, value: probe.price }, { paneId }) as {
          x?: number
          y?: number
        })
      : {}
    const range = chart.getVisibleRange()
    const key = [
      chart.getBarSpace().bar,
      range.from,
      range.to,
      chart.getDataList().length,
      chart.getSize(paneId)?.height,
      at.x,
      at.y,
    ].join('|')
    if (key !== this.key) {
      this.key = key
      this.layers = this.count(chart, paneId)
    }
    return this.layers.get(id) ?? 0
  }

  private count(chart: Chart, paneId: string): Map<string, number> {
    const layers = new Map<string, number>()
    for (const side of ['buy', 'sell'] as const) {
      /* 이른 표가 봉 곁을 먼저 차지합니다. 나중 표는 앞 표와 겹치는 동안 봉에서
         먼 쪽(매수 아래·매도 위)으로 한 층씩 물러납니다. */
      const marks = this.marks.filter((mark) => mark.side === side).sort((a, b) => a.time - b.time)
      if (marks.length === 0) continue
      const outward = side === 'buy' ? 1 : -1
      const pixels = chart.convertToPixel(
        marks.map((mark) => ({ timestamp: mark.time, value: mark.price })),
        { paneId },
      ) as Array<{ x?: number; y?: number }>
      const placed: Array<{ x: number; y: number }> = []
      marks.forEach((mark, index) => {
        const x = pixels[index]?.x
        const y = pixels[index]?.y
        if (typeof x !== 'number' || !Number.isFinite(x) || typeof y !== 'number' || !Number.isFinite(y)) {
          layers.set(mark.id, 0)
          return
        }
        let layer = 0
        let cy = y + outward * (R + 6)
        const hits = (at: number) =>
          placed.some((other) => Math.abs(other.x - x) < STACK_STEP && Math.abs(other.y - at) < STACK_STEP)
        while (layer < STACK_LAYERS - 1 && hits(cy)) {
          layer += 1
          cy += outward * STACK_STEP
        }
        placed.push({ x, y: cy })
        layers.set(mark.id, layer)
      })
    }
    return layers
  }
}

/* 차트는 캔버스에 그리므로 CSS 이름이 아니라 색 값이 필요합니다. 그릴 때마다
 * 읽어야 밝은·어두운 화면을 오갈 때 표도 따라 바뀝니다. */
function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

/* 글자 도형의 기본 스타일에는 **바탕과 테두리가 딸려 옵니다**. 그대로 두면
 * 원 위에 라이브러리 기본색 상자가 얹혀, 매수·매도 색이 그 상자에 가립니다.
 * 글자만 그리도록 바탕과 여백을 지웁니다. */
const GLYPH_BOX = {
  backgroundColor: 'transparent',
  borderSize: 0,
  paddingLeft: 0,
  paddingRight: 0,
  paddingTop: 0,
  paddingBottom: 0,
}

/* 채운 원 위에 서는 B·S 글자.
 *
 * 토큰을 쓰지 않고 흰색을 적어 둡니다. 이 자리는 짙게 채운 빨강·파랑 위이고,
 * 재어 보면 앱의 「채움 위 글자」 토큰들이 여기서는 기준(4.5)에 못 미칩니다 —
 * `--on-brand` 은 3.36·3.35(어두움) / 3.48·3.47(밝음), `--surface` 는
 * 3.61·3.60 / 4.76·4.77 입니다. 흰색만 4.94·4.95 / 4.76·4.77 로 두 화면
 * 모두 넘깁니다. 매수·매도 색 자체는 토큰 그대로입니다. */
const GLYPH = '#ffffff'

/** 끌어 옮기는 동작만 안 받습니다. 누름·선택은 그대로 살아 있어야 상세가 뜹니다. */
const NO_DRAG: OverlayFigure['ignoreEvent'] = [
  'onPressedMoveStart',
  'onPressedMoving',
  'onPressedMoveEnd',
]

let registered = false

/** 매매 표시를 라이브러리에 등록합니다. 한 번만 돕니다. */
export function ensureMarkOverlay(): void {
  if (registered) return
  registered = true
  registerOverlay({
    name: 'tradeMark',
    totalStep: 1,
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: ({ chart, overlay, coordinates }) => {
      if (coordinates.length < 1) return []
      const data = overlay.extendData as MarkData | undefined
      if (!data) return []
      const { mark, stack } = data
      const { x, y } = coordinates[0]
      /* 매수는 봉 아래, 매도는 봉 위에 답니다 — 산 자리는 바닥에서, 판
         자리는 천장에서 읽는 것이 값의 방향과 맞습니다. 쌓인 표는 그 방향으로
         한 층씩 더 멀어집니다. */
      const layer = stacks.get(stack)?.layerOf(chart, overlay.paneId, mark.id) ?? 0
      const lift = layer * STACK_STEP
      const cy = mark.side === 'buy' ? y + R + 6 + lift : y - R - 6 - lift
      const color = token(mark.side === 'buy' ? '--up' : '--down')
      /* **체결만 속을 채웁니다.** 신호·주문은 「그럴 뻔했다」이지 「그랬다」가
         아니라, 같은 모양으로 그리면 켜는 순간 사지도 않은 자리가 산 자리와
         구별되지 않습니다(원본 §8). 속이 빈 것은 아직 값이 아니라는 뜻입니다. */
      const done = mark.kind === 'fill'
      const figures: OverlayFigure[] = []
      /* 표면색 링을 한 겹 깔아 봉에서 떼어 냅니다. **채운 표에도 답니다** —
         매도 표는 파랑이고 내린 봉도 파랑이라, 채워도 파란 봉에 겹치면 봉의
         일부로 읽힙니다. 색이 같아도 경계가 있으면 갈립니다. */
      figures.push({
        type: 'circle',
        attrs: { x, y: cy, r: R + 1 },
        styles: { style: 'stroke', color: 'transparent', borderColor: token('--surface'), borderSize: 2 },
        ignoreEvent: NO_DRAG,
      })
      figures.push(
        {
          type: 'circle',
          attrs: { x, y: cy, r: R },
          styles: done
            ? { style: 'fill', color }
            : { style: 'stroke', color: 'transparent', borderColor: color, borderSize: 1.5 },
          /* 끌어 옮기는 것만 막습니다. 표는 실행이 남긴 자리라 손으로 옮길
             것이 아닙니다. 통째로 잠그면 누르는 것까지 막혀 상세를 열 수
             없으므로, 미는 동작 셋만 안 받습니다. */
          ignoreEvent: NO_DRAG,
        },
        {
          type: 'text',
          attrs: {
            x,
            y: cy,
            text: mark.side === 'buy' ? 'B' : 'S',
            align: 'center',
            baseline: 'middle',
          },
          styles: { ...GLYPH_BOX, color: done ? GLYPH : color, size: 10, weight: 'bold' },
          ignoreEvent: NO_DRAG,
        },
      )
      /* 같은 봉에 여러 체결이 있으면 겹쳐 놓지 않고 수를 답니다. 개별 체결은
         상세와 아래 표가 그대로 들고 있습니다. */
      if (mark.count > 1) {
        figures.push({
          type: 'text',
          attrs: {
            x: x + R + 2,
            y: cy - R,
            text: String(mark.count),
            align: 'left',
            baseline: 'middle',
          },
          styles: { ...GLYPH_BOX, color, size: 10, weight: 'bold' },
          ignoreEvent: NO_DRAG,
        })
      }
      return figures
    },
  })
}
