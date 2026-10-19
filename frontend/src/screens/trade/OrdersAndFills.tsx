import { useEffect, useRef } from 'react'

import { masterIndex, subscribeMaster } from '../../data/master'
import { marketOf, valueWidthOf } from '../../lib/valueWidth'

import type { ListEntry } from '../../data/account'
import { orderKindWord } from '../../data/accountRows'
import { listFace, staleNote } from '../../lib/listFace'
import { Count, Num, NumOrDash, currencyDigits, fracWidth, signSpace, toneOf } from '../../lib/number'
import type { Fill, MarketContext, OpenOrder, Position, Quote } from '../../lib/types'
import { MARKET_BADGE, NO_CODE_REASON } from '../../lib/labels'
import type { EditMode } from './OrderForm'

/* 값 좌우로 두는 여백. 칸 폭은 「값이 차지하는 자리 + 이만큼」입니다 —
 * 값끼리 맞붙으면 어느 줄 것인지가 안 갈립니다. */
const VALUE_PADDING = 16

/* 화면 아래 두 탭 — 주문체결상세와 미결제약정.
 *
 * 주문체결상세는 미체결과 체결을 한 표에 둡니다. 갈라 두면 「낸 주문이 어떻게
 * 됐나」를 보려고 탭을 오가야 하는데, 그건 한 가지 질문입니다. 상태 열이 그
 * 둘을 나릅니다.
 *
 * 열이 여섯입니다. 왼쪽 열이 사이드바를 열면 435 까지 줄어드는데, 버릴 열을
 * 고른 게 아니라 다른 열이 대신 말해주는 둘을 접습니다.
 *
 *   유형   주문가격 열이 말합니다 — 시장가면 가격 자리에 「시장가」가 섭니다
 *   출처   동작 열이 말합니다 — 다른 곳에서 낸 주문은 정정·취소 버튼이 없고
 *          그 자리에 출처가 섭니다
 *
 * 구분은 종목 칸에 합치지 않습니다. 배지도 그 칸을 쓰기 때문에 합쳐서 버는 폭이
 * 6px 뿐이고, 그 6 을 벌자고 열 머리 하나를 잃게 됩니다.
 * 여섯이 다 안 들어가는 칸에서는 표를 미는 대신 종목 열을 빼고 다시 짭니다
 * (`trade.css` 의 `[data-narrow]`).
 */

type Mode = '주문체결상세' | '미결제약정'

/** 한 시장의 사정을 말하는 줄에 쓰는 시장 이름. */
const MARKET_WORD = { domestic: '국내', overseas: '해외' } as const

interface Props {
  quote: Quote
  /** 지금 보고 있는 시장. 값 칸 폭을 잡을 무리를 이 값으로 고릅니다. */
  context: MarketContext
  orders: OpenOrder[]
  fills: Fill[]
  positions: Position[]
  /** 이 카드를 채우는 계좌 조회를 담아 둔 자리. **상태를 통째로 받습니다** —
   *  「없다」와 「불러오는 중」과 「못 받았다」가 다 다른 얼굴이고, 참·거짓 하나로
   *  줄이면 못 받은 자리가 「없습니다」로 섭니다. */
  list: ListEntry<unknown>
  onRetry: () => void
  /** 포지션을 청산하러 갑니다. 종목을 그 종목으로 바꾸고 폼을 청산 모드로 둡니다. */
  onClose: (position: Position) => void
  /** 미결제약정은 계좌 전체 표라 시장마다 따로 받습니다. 다른 시장 줄은 섰는데
   *  **이 시장만** 못 받았거나(`missing`) 새로 받지 못했으면(`stale`), 표 위에 그
   *  시장 이름으로 한 줄 섭니다. `shown` 은 표에 줄이 선 다른 시장이고, 다시 부를
   *  만한 실패면 `retry` 가 있습니다. */
  positionNotes?: {
    market: 'domestic' | 'overseas'
    kind: 'missing' | 'stale'
    shown: ('domestic' | 'overseas')[]
    retry?: () => void
  }[]
  mode: Mode
  onEdit: (order: OpenOrder, edit: EditMode) => void
}

/** 살아 있는 주문 줄의 상태 낱말. **채워진 수를 낱말이 먼저 말합니다** — 「0 / 3」
 *  처럼 수만 두면 앞 수가 「안 채워진 수」로 읽힙니다. 수의 차례(체결 / 주문)는
 *  계좌 화면 미체결 표와 같습니다.
 *
 *  - 체결을 모르면(`null`) 칸 전체가 「—」입니다. 「미체결」로 적으면 서버가
 *    말한 적 없는 0 이 섭니다.
 *  - 체결이 0 이면 「미체결」, 그 밖은 「부분 체결 {체결}/{주문}」입니다. 주문
 *    수량을 모르면 그 자리가 「—」이고, 체결이 주문 수량 이상이어도 받은 수를
 *    그대로 적습니다 — 고쳐 적지 않습니다. */
function liveStateWord(filled: number | null, quantity: number | null): string | null {
  if (filled === null) return null
  if (filled === 0) return '미체결'
  return `부분 체결 ${filled}/${quantity ?? '—'}`
}

/** 한 표에 섞이는 줄. 미체결과 체결이 상태로만 갈립니다. */
type Row =
  | { kind: 'open'; order: OpenOrder }
  | { kind: 'fill'; fill: Fill }

/** 고정 열이 있는 표가 스스로 재야 하는 것을 잽니다 — **가격 칸 폭**과, 표가
 *  넘치는지(`data-scrolls`)와, 칸 단위로 밀 때 멈출 자리입니다.
 *
 *  가격 칸 폭은 색인이 보낸 후보 행을 이 표의 글꼴로 그려 재서 넣습니다. 자릿수가
 *  섞이는 표만 이 값을 부릅니다.
 *
 *  넘칠 때만 고정 칸의 경계선이 섭니다. 다 들어가는 창에서는 고정될 것이 없어,
 *  아무것도 안 가르는 세로선만 남기 때문입니다.
 *
 *  **아래 값은 미결제약정의 것입니다.** 가격 칸 폭이 정해지면 지금 자료에서는
 *  1200×720 에서 일곱 열이 다 서고 밀 것이 없어집니다(합 555 = 스크롤 칸
 *  안쪽 555). **여유가 0 입니다** — 종목 열은
 *  최소 폭이라 가장 긴 이름(284 필요)은 잘린 채이고, 평가손익 폭은 지금 값
 *  기준입니다. 값이 길어지거나 창이 좁아지면 다시 넘치고, 그때 `data-scrolls`
 *  가 켜져 칸 단위 밀기와 고정 칸 경계선이 다시 섭니다. 고장이 아니라 그 구간의
 *  동작입니다. */
/** 표가 굴림 칸보다 얼마나 넓은지(px). **넣은 값을 걷지 않고 셈합니다** —
 *  끝 여백은 표 바깥 여백이라 표 사각형에 안 들고, 종목 열에 얹은 남는 폭
 *  (`spare`, 표 폭에 실제로 더해진 몫)만 뺍니다. 값을 0 으로 돌렸다 되넣으며
 *  재면 그 사이 굴림 한도가 줄어 밀어 둔 자리가 잘릴 수 있습니다. */
function overflowOf(box: HTMLElement, spare: number): number {
  const table = box.querySelector('table')
  if (!table) return box.scrollWidth - box.clientWidth
  return table.getBoundingClientRect().width - spare - box.clientWidth
}

/** 굴림 끝 흐림. **가려진 쪽에만** 섭니다 — 맨 앞이면 오른쪽만, 가운데면 양쪽,
 *  맨 끝이면 왼쪽만, 안 밀리면 없습니다. 가려졌는지는 **표 모서리가 굴림 칸
 *  밖에 있는지**로 봅니다. 밀기 한도로 보면 칸 단위로 멈추는 표는 마지막
 *  자리가 한도보다 조금 앞이라(끝 여백), 다 보이는데도 오른쪽이 가려졌다고
 *  나옵니다. 1px 여유를 둡니다.
 *
 *  **흐림은 밀리는 값 칸에만 섭니다.** 굴림 칸에 건 가림막은 칸 자리에 고정되어
 *  안 밀리므로, 붙어 있는 칸이 서는 자리와 막대 자리는 가리지 않게 비워 둡니다
 *  (`--fade-left-at`·`--fade-right-at`·`--fade-bar`). 그 자리는 붙은 머리 칸의
 *  **실제 모서리**에서 잽니다 — 열 폭을 더하면 소수점이 쌓이고, 막대 폭과 칸이
 *  굴림 칸 밖으로 내민 몫을 따로 셈해야 합니다. 가려진 쪽은 칸이 붙어 서 있는
 *  때라 잰 모서리가 곧 붙은 자리입니다. */
function markFades(frame: HTMLElement, box: HTMLElement) {
  const scrolls = frame.hasAttribute('data-scrolls')
  const table = box.querySelector('table')
  if (!scrolls || !table) {
    frame.toggleAttribute('data-fade-left', false)
    frame.toggleAttribute('data-fade-right', false)
    return
  }
  const outer = box.getBoundingClientRect()
  const start = outer.left + box.clientLeft
  const edges = table.getBoundingClientRect()
  const hiddenLeft = edges.left < start - 1
  const hiddenRight = edges.right > start + box.clientWidth + 1

  let left = start
  let right = start + box.clientWidth
  for (const cell of box.querySelectorAll('thead th')) {
    const style = getComputedStyle(cell)
    if (style.position !== 'sticky') continue
    const rect = cell.getBoundingClientRect()
    if (style.left !== 'auto') left = Math.max(left, rect.right)
    else if (style.right !== 'auto') right = Math.min(right, rect.left)
  }
  frame.style.setProperty('--fade-left-at', `${(left - outer.left).toFixed(2)}px`)
  frame.style.setProperty('--fade-right-at', `${(outer.right - right).toFixed(2)}px`)
  frame.style.setProperty('--fade-bar', `${box.offsetHeight - box.clientHeight}px`)
  frame.toggleAttribute('data-fade-left', hiddenLeft)
  frame.toggleAttribute('data-fade-right', hiddenRight)
}

function useFixedColumns(groups?: { market: string; decimals: number; notation: string }[]) {
  const frameRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const frame = frameRef.current
    const box = frame?.querySelector('.table-scroll')
    if (!frame || !(box instanceof HTMLElement)) return

    const apply = () => {
      const head = [...box.querySelectorAll('thead th')]
      if (head.length === 0) return
      const width = (cell: Element) => cell.getBoundingClientRect().width

      /* 가격 칸 폭은 후보 행을 그려 재서 정합니다. 여기서 재는 것은 헤더와
         따로입니다 — 표 글꼴이 한 급 작아 같은 값이라도 폭이 다릅니다. */
      /* 무리가 여럿이면(시장이 섞인 표) **가장 넓은 무리**로 잡습니다 — 좁은 쪽으로
         잡으면 넓은 무리의 값이 칸을 넘습니다. */
      if (groups && groups.length > 0) {
        const widths = groups
          .map((group) =>
            valueWidthOf(
              box,
              /* 값이 실제로 서는 칸 하나를 본으로 줍니다 — 표 글꼴이 스크롤 칸과
                 다릅니다. 수량 칸(세 번째)이 값 칸 중 첫째입니다. */
              box.querySelector('tbody tr td:nth-child(3)'),
              'positions',
              masterIndex(),
              group.market,
              group.decimals,
              group.notation,
            ),
          )
          .filter((width): width is number => width !== null)
        if (widths.length > 0) {
          frame.style.setProperty('--pos-value-w', `${Math.max(...widths) + VALUE_PADDING}px`)
        }
      }

      /* **넣은 값 가운데 표 폭에 실제로 더해진 몫.** 아래에서 종목 열에 얹는
         남는 폭은 넓은 배치에서만 열 폭이 됩니다 — 좁은 배치는 종목 열 폭을
         못 박아 두어(trade.css) 표 폭이 그대로입니다. 더해지지 않은 몫까지
         빼면 넘침을 적게 셈해, 잴 때마다 답이 뒤집힙니다. */
      const narrowCard = frame.closest('[data-narrow]') !== null
      const spare = narrowCard
        ? 0
        : Number.parseFloat(getComputedStyle(frame).getPropertyValue('--pos-name-extra')) || 0

      /* **고정 칸이 다 설 폭이 있는지.** 미결제약정 표만 봅니다. 왼쪽 고정(종목,
         좁은 배치는 구분까지)과 오른쪽 고정(평가손익·동작)에 가운데 창을 더한
         폭보다 틀이 좁으면 고정 칸끼리 겹칩니다 — 그때는 동작 열만 붙입니다.
         **자리가 아니라 열 자체의 폭으로 셉니다**: 고정을 풀어도 열 폭은 같아서,
         풀린 뒤에 다시 재도 같은 답이 나와 켜졌다 꺼졌다 하지 않습니다. 종목
         열에 얹어 둔 남는 폭은 빼고 셉니다. */
      if (frame.classList.contains('orders-positions-frame') && head.length >= 4) {
        const style = getComputedStyle(frame)
        const read = (name: string) => Number.parseFloat(style.getPropertyValue(name)) || 0
        const left = width(head[0]) - spare + (narrowCard ? width(head[1]) : 0)
        const right = width(head[head.length - 2]) + read('--pos-action-w')
        const needed = left + right + read('--pos-middle-min')
        frame.toggleAttribute('data-pin-action', box.clientWidth < needed)
      }
      /* **동작 열만 붙인 판은 보통으로 밉니다.** 칸 단위로 멈추는 장치(멈출 자리·
         종목 열에 얹는 남는 폭·끝 여백)는 고정된 왼쪽 열 옆에서 라벨 잃은 값
         조각을 안 남기려는 것인데, 이 판에는 고정된 왼쪽 열이 없습니다. 끝 여백을
         남기면 끝까지 밀었을 때 청산 열 오른쪽에 빈 띠가 섭니다. */
      if (frame.hasAttribute('data-pin-action')) {
        frame.style.setProperty('--pos-name-extra', '0px')
        frame.style.setProperty('--pos-tail-w', '0px')
        frame.style.removeProperty('--fixed-left')
        frame.style.removeProperty('--fixed-left-2')
        frame.removeAttribute('data-snaps')
        head.forEach((cell) => {
          ;(cell as HTMLElement).style.scrollSnapAlign = ''
        })
        frame.toggleAttribute('data-scrolls', overflowOf(box, spare) > 1)
        markFades(frame, box)
        return
      }

      /* 오른쪽에 붙은 열들의 폭. 밀 때 멈출 자리를 셀 때 뺍니다. */
      const pinned = head
        .filter((cell) => getComputedStyle(cell).right !== 'auto')
        .reduce((sum, cell) => sum + width(cell), 0)

      /* **어느 자리에 서도 부분 칸이 없어야 합니다.**
         값 칸은 폭이 제각각이라(구분 42 · 수량 40 · 가격 75) 아무 칸에서나
         멈추면 마지막 칸이 반쯤 걸립니다. 이 표는 값이 오른쪽 정렬이라 그
         조각이 **행마다 있다 없다** 합니다 — 짧은 값은 통째로 숨고 긴 값만
         앞머리가 나와, 「잘렸다」가 아니라 「이 행엔 값이 없다」로 읽힙니다.

         그래서 멈출 수 있는 자리를 **창이 열 끝과 맞는 자리**로만 둡니다.

         **셋을 한 번에 셈합니다.** 넣은 값을 다시 재서 셈하면 답이 서로 물려
         흔들립니다 — 넣기 전의 값(받은 폭·끝 여백을 뺀 것)만으로 셉니다. */
      const anchored = head.filter((cell) => getComputedStyle(cell).left !== 'auto')
      const anchoredBase = anchored.reduce((sum, cell) => sum + width(cell), 0) - spare

      /* 왼쪽에 열이 둘 붙는 배치에서는 **둘째 열이 첫째 열의 잰 폭 뒤에** 서야
         합니다. 열에 준 폭을 그대로 자리로 쓰면 어긋납니다 — 이 표는 폭을 열
         폭의 합으로 잡아, 각 열이 준 폭과 내용 폭 중 **넓은 쪽**으로 섭니다.
         좁은 배치에서 종목 열에 준 폭은 가장 긴 이름보다 좁아 내용 쪽이 이기고,
         둘째 열은 그 차이만큼 첫 열 밑으로 들어가 **방향을 나르는 글자를 한
         자만 남깁니다**(「매수」가 「수」로). 첫째 열의 오른쪽 모서리는 재야
         압니다. */
      if (anchored.length > 1) {
        frame.style.setProperty('--fixed-left-2', `${width(anchored[0]).toFixed(2)}px`)
      } else {
        /* 붙는 열이 하나뿐인 배치로 돌아오면 지웁니다 — 남겨 두면 다음에 그
           배치로 갈 때 지난번 폭이 잠깐 쓰입니다. */
        frame.style.removeProperty('--fixed-left-2')
      }
      const values = head.filter(
        (cell) => getComputedStyle(cell).right === 'auto' && getComputedStyle(cell).left === 'auto',
      )
      const widths = values.map(width)
      const room = box.clientWidth - anchoredBase - pinned
      const overflow = overflowOf(box, spare)

      /* 열이 끝나는 자리와 시작하는 자리. */
      let running = 0
      const begins = widths.map((w) => {
        const here = running
        running += w
        return here
      })
      const total = running
      const ends = begins.map((at, i) => at + widths[i])
      const near = (a: number, b: number) => Math.abs(a - b) < 0.5

      /* 첫 자리(밀기 0)에서 창이 열 끝에 맞도록 남는 폭을 종목 열이 받습니다.
         이것이 없으면 첫 자리부터 마지막 칸이 걸립니다. */
      const scrolls = overflow > 1
      const fits = ends.filter((e) => e <= room + 0.5)
      const firstWidth = fits.length > 0 ? fits[fits.length - 1] : room
      const extra = scrolls ? Math.max(0, room - firstWidth) : 0
      frame.style.setProperty('--pos-name-extra', `${extra.toFixed(2)}px`)
      /* 멈추는 자리는 **넓힌 뒤의** 왼쪽 고정 끝입니다. 잰 값을 그대로 쓰면
         넓히기 전 값이라 한 판이 그만큼 밀려 섭니다. */
      frame.style.setProperty('--fixed-left', `${(anchoredBase + extra).toFixed(2)}px`)

      /* **멈출 수 있는 자리 = 열이 시작하는 자리 가운데, 그 자리에서 창이 열
         끝과 맞거나 표 끝을 넘는 자리.** 그런 자리에서만 서면 어느 자리에서도
         부분 칸이 없습니다. 표 끝을 넘는 첫 자리가 마지막 자리이고, 넘은 만큼은
         꼬리 여백이 채웁니다. */
      const track = room - extra
      const last = begins.find((at) => at + track >= total - 0.5) ?? 0
      const stops = new Set(
        begins.filter(
          (at) =>
            at <= last + 0.5 &&
            (ends.some((e) => near(e, at + track)) || at + track >= total - 0.5),
        ),
      )
      /* 값 칸이 아니게 된 열에는 지난번에 단 자리가 남습니다 — 배치가 바뀌면
         고정으로 옮겨 가는 열이 있습니다. 먼저 전부 지우고 다시 답니다. */
      head.forEach((cell) => {
        ;(cell as HTMLElement).style.scrollSnapAlign = ''
      })
      values.forEach((cell, at) => {
        ;(cell as HTMLElement).style.scrollSnapAlign = stops.has(begins[at]) ? 'start' : 'none'
      })

      /* **설 자리가 하나뿐이면 칸 단위 밀기를 끕니다.** 반드시 어느 자리에는
         서게 해 둔 채(`mandatory`) 설 자리가 하나면, 밀어도 매번 그 자리로
         되돌아와 표가 잠깁니다 — 넘치는데 못 미는 상태라 값을 볼 방법이
         없어집니다. 자리가 하나뿐인 것은 열 구성이 다른 배치(좁은 칸에서
         종목·구분 둘을 붙이는 자리)에서 생깁니다. 그 구간은 칸 단위 보장
         대신 자유롭게 밀고, 잘린 쪽은 굴림 끝의 흐림(`markFades`)이 말합니다. */
      frame.toggleAttribute('data-snaps', stops.size > 1)

      /* 마지막 자리까지 밀 수 있어야 합니다. 밀기 한도는 정수로 잘리므로 한
         자리 넉넉히 둡니다. */
      const need = scrolls ? last - (overflow + extra) : 0
      frame.style.setProperty('--pos-tail-w', `${need > 0 ? Math.ceil(need) + 1 : 0}px`)
      frame.toggleAttribute('data-scrolls', scrolls)
      markFades(frame, box)
    }

    /* 밀 때는 가려진 쪽만 다시 가립니다 — 폭은 그대로라 다시 잴 것이 없습니다. */
    const onScroll = () => markFades(frame, box)

    apply()
    /* 폭 후보는 마스터와 함께 옵니다. 표가 먼저 서면 그때는 잴 것이 없으니,
       색인이 도착하면 다시 잽니다. */
    const unsubscribe = subscribeMaster(apply)
    /* 이 효과는 렌더마다 다시 걸립니다. 굴림 듣기는 정리에서 떼므로 붙어 있는
       것은 늘 하나입니다. */
    box.addEventListener('scroll', onScroll, { passive: true })
    const watch = new ResizeObserver(apply)
    watch.observe(frame)
    watch.observe(box)
    /* 표도 봅니다 — 값이 길어져 열이 넓어지면 남는 폭도 달라집니다. */
    const table = box.querySelector('table')
    if (table) watch.observe(table)
    return () => {
      box.removeEventListener('scroll', onScroll)
      watch.disconnect()
      unsubscribe()
    }
  })

  return frameRef
}

export function OrdersAndFills({
  quote,
  context,
  orders,
  fills,
  positions,
  list,
  onRetry,
  mode,
  onEdit,
  onClose,
  positionNotes = [],
}: Props) {
  const d = quote.decimals
  /* 이 종목이 분수로 불리면 주문·체결 가격도 그렇게 적습니다 — 같은 화면에서
     헤더는 `437'5` 인데 표는 `437.6472` 이면 두 값이 다른 것으로 읽힙니다. */
  const fraction = quote.fraction
  /* 음수가 설 수 있는 종목(스프레드)은 부호 한 칸을 미리 잡습니다. */
  const price = fracWidth(d, signSpace(quote.kind), fraction)

  /* 미결제 표는 **계좌 전체 줄**이라 가격 꼴이 줄마다 다릅니다(그 줄 종목의 것).
     폭을 잡는 꼴은 분수 줄이 하나라도 있으면 분수입니다 — 분수 꼴이 더 넓어,
     소수 기준으로 잡으면 분수 줄이 칸을 넘습니다. */
  const notation = positions.some((row) => row.fraction) ? 'fraction' : 'decimal'
  /* 표는 **시장이 섞일 수 있습니다**(계좌 전체). 보는 종목의 시장은 그 종목의
     자릿수로, 다른 시장은 그 시장 줄들 가운데 가장 긴 자릿수로 잽니다. */
  const shownMarket = marketOf(context)
  const otherMarkets = [...new Set(positions.map((row) => marketOf(row.market)))].filter(
    (market) => market !== shownMarket,
  )
  const positionsFrame = useFixedColumns([
    { market: shownMarket, decimals: d, notation },
    ...otherMarkets.map((market) => ({
      market,
      decimals: Math.max(
        0,
        ...positions.filter((row) => marketOf(row.market) === market).map((row) => row.decimals ?? 0),
      ),
      notation,
    })),
  ])
  /* 주문체결상세도 같은 것을 씁니다. 값 칸 폭은 안 맡깁니다 — 이 표는 한 종목만
     담아 자릿수가 섞이지 않으므로 무리를 안 넘기고, 그러면 훅은 넘치는지만
     잽니다.

     **지금 열 구성에서는 이 표가 어느 창에서도 안 넘칩니다** — 넘치기 전에 좁은
     배치가 먼저 걸려 종목 열을 빼고 하한을 내립니다(까닭은 `trade.css` 의 동작
     열 고정 주석). 그래서 `data-scrolls` 가 안 켜집니다.

     그래도 이 줄을 두는 것은, 열이 늘거나 카드 바닥이 내려가 다시 넘칠 때
     고정 칸 경계선이 함께 서야 하기 때문입니다. */
  const detailFrame = useFixedColumns()

  if (mode === '미결제약정') {
    /* **「없다」와 「모른다」와 「못 받았다」를 가릅니다.** 못 받은 자리에
       「없습니다」를 세우면 있는 포지션을 없다고 말하게 됩니다. */
    const face = listFace(list, '보유 포지션이 없습니다', onRetry)
    return (
      <div className="orders-band">
        {/* 값이 있는데 다시 받기가 안 된 자리에만 섭니다 — 그때 얼굴은
            비어 있으므로 둘이 함께 서는 일은 없습니다. */}
        {staleNote(list, onRetry)}
        {positionNotes.map((note) => (
          <p key={note.market} className="list-stale">
            {note.kind === 'missing'
              ? /* 남은 줄이 계좌 전체가 아니라는 것까지 말합니다 — 빠진 시장만 말하면
                   아래 줄이 전부인지 알 수 없습니다. */
                `${MARKET_WORD[note.market]} 잔고를 받지 못했습니다 — 아래는 ${note.shown.map((market) => MARKET_WORD[market]).join('·')} 줄뿐입니다`
              : `${MARKET_WORD[note.market]} 잔고는 마지막으로 받은 값입니다. 다시 받지 못했습니다`}
            {note.retry && (
              <button type="button" className="btn btn-quiet" onClick={note.retry}>
                다시 받기
              </button>
            )}
          </p>
        ))}
        {face ?? (
          <div className="table-frame orders-positions-frame" ref={positionsFrame}>
            {/* 표가 카드보다 넓어 늘 밀어서 봅니다. 미는 단위는 칸이고 종목 열은
                고정입니다 — 규칙과 값은 `trade.css` 의 `.orders-positions-scroll`
                에 있고, 헤더가 쓰는 것과 같은 장치입니다. */}
            <div className="table-scroll orders-positions-scroll">
              <table className="data-table rows-base t-dense orders-positions">
                <thead>
                  <tr>
                    <th scope="col" className="col-text">
                      종목
                    </th>
                    <th scope="col" className="col-text">
                      구분
                    </th>
                    <th scope="col">수량</th>
                    <th scope="col">평균가</th>
                    {/* 국내·해외 모두 줄에 장중 현재가가 실려 옵니다(국내는 응답의
                        「종가」 칸이 장중에 현재가를 따라 움직입니다). 계좌 화면의
                        잔고 표와 같은 이름입니다. */}
                    <th scope="col">현재가</th>
                    <th scope="col">평가손익</th>
                    <th scope="col">동작</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((row, index) => (
                    /* 행을 눌러도 청산으로 갑니다. 단추가 있는데도 행을 누르게
                       두는 것은, 이 표에서 할 일이 하나뿐이기 때문입니다.
                       **열쇠는 값이 아니라 자리입니다** — 종목 마스터에서 그
                       품목을 못 찾으면 코드가 빈 문자열이라, 값으로 열쇠를 만들면
                       줄마다 같은 열쇠가 됩니다. 그 줄은 청산할 종목도 없으므로
                       행과 단추가 함께 누르는 자리에서 빠집니다. */
                    <tr
                      key={`position-${index}`}
                      className={row.code ? 'row-click' : undefined}
                      aria-disabled={row.code ? undefined : true}
                      onClick={row.code ? () => onClose(row) : undefined}
                    >
                      <td className="col-text">
                        {row.name}
                        {/* 표가 계좌 전체라 **줄마다 제 시장**을 답니다 — 보는 종목과 다른
                            시장의 줄이 섞여 섭니다. 국내는 그 줄 종목의 세션입니다. */}
                        {/* 모르는 시장 값이면 배지를 안 답니다 — 글자 없는 배지는 무엇을
                            말하는지 모르는 조각으로만 남습니다. */}
                        {MARKET_BADGE[row.market] && <span className="badge">{MARKET_BADGE[row.market]}</span>}
                        {/* **서버가 종류를 준 줄에만** 답니다. 두 만기가 걸린 줄은
                            수량·평가손익을 한 다리의 것으로 읽으면 안 되어, 이름
                            옆에서 먼저 말해 줍니다. 안 주는 시장에서는 아무것도
                            안 답니다 — 이름을 뜯어 짐작하지 않습니다. */}
                        {row.productKind === 'spread' && <span className="badge">스프레드</span>}
                        {!row.code && <span className="hidden-note">{NO_CODE_REASON}</span>}
                        {/* 이름이 마스터에서 온 것이 아니면 까닭 한 줄 — 그 줄은
                            만기·자릿수도 함께 비어 있습니다. */}
                        {row.nameNote && <span className="hidden-note">{row.nameNote}</span>}
                      </td>
                      <td className={`col-text ${row.side === 'long' ? 'up' : 'down'}`}>
                        {row.side === 'long' ? '매수' : '매도'}
                      </td>
                      {/* **줄마다 오는 칸이 다릅니다.** 서버가 안 준 칸은 「—」
                          입니다 — 0 으로 채우면 「없다」가 「0 이다」가 됩니다. */}
                      <td>
                        {row.quantity === null ? (
                          <span className="dead">—</span>
                        ) : (
                          <Count value={row.quantity} />
                        )}
                      </td>
                      {/* 줄마다 종목이 달라 부호 자리도 줄마다 봅니다 — 스프레드
                          줄만 한 칸을 미리 잡습니다. */}
                      <td style={fracWidth(row.decimals ?? 0, signSpace(row.productKind), row.fraction)}>
                        <NumOrDash value={row.avgPrice} decimals={row.decimals} fraction={row.fraction} />
                      </td>
                      <td style={fracWidth(row.decimals ?? 0, signSpace(row.productKind), row.fraction)}>
                        <NumOrDash value={row.lastPrice} decimals={row.decimals} fraction={row.fraction} />
                      </td>
                      {/* 없는 값만 흐립니다. 손익 0 은 본전이라 본문색입니다. */}
                      <td className={row.pl === null ? 'dead' : toneOf(row.pl) || undefined}>
                        {row.pl === null ? (
                          '—'
                        ) : (
                          <>
                            {/* 자릿수는 **줄의 통화**로 정합니다(원 0, 달러 2).
                                반올림은 `Num` 이 그 자릿수로 한 번만 합니다. 통화를
                                모르는 줄은 정수로 적습니다. */}
                            {currencyDigits(row.currency) === null ? (
                              <Count
                                value={Math.sign(row.pl) * Math.round(Math.abs(row.pl))}
                                signed
                              />
                            ) : (
                              <Num value={row.pl} decimals={currencyDigits(row.currency) ?? 0} signed />
                            )}
                            {row.currency === 'KRW' ? '원' : row.currency ? ` ${row.currency}` : ''}
                          </>
                        )}
                      </td>
                      {/* 칸에 배치 클래스를 달지 않습니다 — 칸의 `display` 를 바꾸면 표의
                          칸이 아니게 되어, 줄 바탕(손을 올린 줄·고른 줄)이 단추 둘레에만
                          칠해지고 나머지는 띠로 남습니다. 단추는 칸의 오른쪽 정렬로
                          오른쪽 끝에 섭니다. */}
                      <td>
                        {/* **수량을 모르면 청산할 수 없습니다.** 몇 계약을 낼지
                            정할 수 없는 주문이라, 폼을 열어 주면 값을 다 채운
                            뒤에야 못 낸다는 것을 알게 됩니다. */}
                        {row.code && row.quantity !== null ? (
                          <button
                            type="button"
                            className="btn btn-quiet"
                            onClick={(event) => {
                              event.stopPropagation()
                              onClose(row)
                            }}
                          >
                            청산
                          </button>
                        ) : (
                          /* 청산할 종목이 없는 행은 흐린 단추 대신 「—」 — 이 표가
                             다른 곳에서 낸 주문에 쓰는 어법과 같고, 비활성 컨트롤이
                             없으니 이유 줄도 필요 없습니다(「—」 = 할 일 없음). */
                          <span className="dead">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    )
  }

  const rows: Row[] = [
    ...orders.map((order) => ({ kind: 'open' as const, order })),
    ...fills.map((fill) => ({ kind: 'fill' as const, fill })),
  ]

  /* **이 카드는 보고 있는 종목의 주문만 담습니다.** 계좌에 오늘 낸 주문이 있어도
     이 종목 것이 없으면 여기는 비는데, 그건 「못 받았다」가 아닙니다 — 그래서
     목록 얼굴과 따로 말합니다.
     같은 까닭으로 계좌 화면의 표처럼 **받은 줄 수를 세우지 않습니다** — 종목으로
     거른 표라 계좌 목록의 줄 수를 적으면 이 카드의 줄 수와 다른 수가 됩니다. */
  const face =
    listFace(list, '오늘 낸 주문이 없습니다', onRetry) ??
    (rows.length === 0 ? (
      <div className="notice">
        <p className="notice-title">이 종목으로 낸 주문이 없습니다</p>
      </div>
    ) : null)

  return (
    <div className="orders-band">
      {staleNote(list, onRetry)}
      {face ?? (
        <div className="table-frame" ref={detailFrame}>
          <div className="table-scroll">
            <table className="data-table rows-base t-dense orders-detail">
              <thead>
                <tr>
                  {/* 열 머리는 그 열 값과 같은 쪽에 붙입니다. 반대로 두면 머리가
                      옆 열 위에 서서 어느 머리가 어느 열인지 이을 수 없습니다. */}
                  <th scope="col" className="col-text">
                    종목
                  </th>
                  <th scope="col" className="col-text">
                    구분
                  </th>
                  <th scope="col" className="col-text">
                    상태
                  </th>
                  <th scope="col">주문가격</th>
                  <th scope="col">수량</th>
                  <th scope="col">동작</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) =>
                  row.kind === 'open' ? (
                    <tr
                      key={`o-${row.order.id}`}
                      /* 방금 얹힌 접수 줄은 한 겹 옅게 깔립니다. **방향색이
                         아닙니다** — 매수·매도를 말하는 색이 여기 서면 그 줄이
                         체결된 것으로 읽힙니다. */
                      className={row.order.progress === 'accepted' ? 'is-accepted' : undefined}
                    >
                      {/* 이 표는 한 종목만 담지만 이름을 지우지 않습니다 —
                          헤더에서 종목을 바꾸면 표도 바뀌므로, 어느 종목의
                          주문인지가 표 안에 남아 있어야 합니다. 열보다 길면
                          잘리고 전체는 마우스를 올려 봅니다. */}
                      <td className="col-text" title={quote.name}>
                        <span className="orders-subject">{quote.name}</span>
                        {/* **정정·취소는 새 주문번호로 한 줄이 더 섭니다.** 한
                            주문을 고쳐 왔을 뿐인데 표에 여러 줄이 남아, 이 표지가
                            없으면 서로 다른 주문 여럿으로 읽힙니다.

                            **배치마다 서는 칸이 다릅니다.** 좁은 배치는 이 열을
                            통째로 접으므로(아래 `[data-narrow]`) 그때는 바로 옆
                            구분 칸이 이 표지를 대신 답니다 — 둘 중 보이는 쪽만
                            섭니다. */}
                        {orderKindWord(row.order.orderKind) && (
                          <span className="badge orders-kind">
                            {orderKindWord(row.order.orderKind)}
                          </span>
                        )}
                      </td>
                      {/* 방향은 글자가 나르고 색은 거듭니다. */}
                      <td className={`col-text ${row.order.side === 'buy' ? 'up' : 'down'}`}>
                        <span className="orders-subject">
                          {row.order.side === 'buy' ? '매수' : '매도'}
                        </span>
                        {orderKindWord(row.order.orderKind) && (
                          <span className="badge orders-kind orders-kind-narrow">
                            {orderKindWord(row.order.orderKind)}
                          </span>
                        )}
                      </td>
                      {/* **진행 상태는 서버가 말한 그대로**입니다. 거절·자동취소는
                          수량을 세어 봐야 아는 것이 아니라 그 줄이 이미 들고 온
                          사실이라, 「미체결 0 / 3」으로 적으면 아직 살아 있는
                          주문처럼 읽힙니다. */}
                      <td className="col-text">
                        {row.order.progress === 'rejected'
                          ? '거절'
                          : row.order.progress === 'auto-cancelled'
                            ? '자동취소'
                            : /* 접수 답에는 체결 수량이 없습니다. 「미체결 0 / 3」으로
                                 적으면 서버가 말한 적 없는 0 이 서므로 한 낱말만
                                 둡니다. 취소는 **접수된 것**이라 「취소됨」이 아닙니다. */
                              row.order.progress === 'accepted'
                              ? '접수'
                              : row.order.progress === 'cancelled'
                                ? '취소 접수'
                                : /* **끝난 줄입니다.** 정정에 밀렸거나 취소가
                                     받아들여진 주문이라 체결도 잔량도 없습니다.
                                     여기에 「미체결 0 / 1」을 적으면 이미 끝난
                                     주문이 아직 걸려 있는 것으로 읽힙니다.
                                     무엇이 끝냈는지는 줄 종류 표지가 말합니다 —
                                     이 칸은 살았나 끝났나만 답합니다. */
                                  row.order.progress === 'closed'
                                  ? '종료'
                                  : (liveStateWord(row.order.filled, row.order.quantity) ?? (
                                      <span className="dead">—</span>
                                    ))}
                      </td>
                      {/* 시장가는 가격이 없습니다. 빈칸으로 두면 「못 받았나」가 되므로
                          그 자리에 유형을 씁니다 — 유형 열이 따로 없는 이유입니다. */}
                      <td style={price}>
                        {row.order.orderType === '시장가' ? (
                          <span className="t-label">시장가</span>
                        ) : (
                          <NumOrDash value={row.order.price} decimals={d} fraction={fraction} />
                        )}
                      </td>
                      <td>
                        {row.order.quantity === null ? (
                          <span className="dead">—</span>
                        ) : (
                          <Count value={row.order.quantity} />
                        )}
                      </td>
                      <td>
                        {/* 동작이 비어 있다는 것이 「여기서는 못 고친다」입니다.
                            그 자리에 어디서 낸 주문인지가 대신 섭니다.

                            **수량을 모르는 주문도 못 고칩니다** — 몇 계약을 낼지
                            정할 수 없어, 폼을 열어 주면 값을 다 채운 뒤에야 못
                            낸다는 것을 알게 됩니다. 그때는 출처가 아니라 그
                            까닭이 섭니다.

                            **상태 열과 맞추지 않습니다.** 상태가 「종료」인데 서버가
                            고칠 수 있다고 답하면 단추가 그대로 섭니다 — 단추는 서버의
                            편집 가능 여부, 상태는 서버 값입니다. 두 값이 어긋났을 때
                            화면이 한쪽을 지우면 그 어긋남이 화면에서 사라집니다. */}
                        {/* 접수 답만 받은 줄은 아직 조회에 안 잡힌 줄입니다. 정정·취소
                            단추를 세우면 그 주문이 서버에 어떻게 서 있는지 모르는
                            채로 또 한 걸음을 내딛게 됩니다. */}
                        {row.order.progress === 'accepted' ||
                        row.order.progress === 'cancelled' ? (
                          <span className="t-label">접수 확인 중</span>
                        ) : row.order.editable && row.order.quantity !== null ? (
                          <span className="orders-actions">
                            <button
                              type="button"
                              className="btn btn-quiet"
                              onClick={() => onEdit(row.order, 'amend')}
                            >
                              정정
                            </button>
                            <button
                              type="button"
                              className="btn btn-quiet"
                              onClick={() => onEdit(row.order, 'cancel')}
                            >
                              취소
                            </button>
                          </span>
                        ) : row.order.editable ? (
                          <span className="t-label">수량 모름</span>
                        ) : (
                          <span className="t-label">{row.order.source}</span>
                        )}
                      </td>
                    </tr>
                  ) : (
                    <tr key={`f-${row.fill.id}`}>
                      <td className="col-text" title={quote.name}>
                        {quote.name}
                      </td>
                      <td className={`col-text ${row.fill.side === 'buy' ? 'up' : 'down'}`}>
                        {row.fill.side === 'buy' ? '매수' : '매도'}
                      </td>
                      <td className="col-text">체결</td>
                      <td style={price}>
                        <NumOrDash value={row.fill.price} decimals={d} fraction={fraction} />
                      </td>
                      <td>
                        {row.fill.quantity === null ? (
                          <span className="dead">—</span>
                        ) : (
                          <Count value={row.fill.quantity} />
                        )}
                      </td>
                      <td className="num">{row.fill.time}</td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
