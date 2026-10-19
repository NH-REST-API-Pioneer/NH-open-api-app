import {
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
  type Dispatch,
  type SetStateAction,
} from 'react'
import type { Fill, OpenOrder, Position, ProductKind } from '../../lib/types'
import type { SplitState } from './chartSlots'
import { useStoredState } from '../../lib/useStoredState'
import { useUiState } from '../../data/uiState'
import {
  CARD_LABEL,
  CARD_MAX_WIDTH,
  DEFAULT_LAYOUT,
  GUTTER,
  LAYOUT_KEY,
  FORM_ROOMY,
  ORDERS_WIDE,
  SLOTS,
  SLOT_SPAN,
  COLUMN_LABEL,
  COLUMN_SLOTS,
  columnGaps,
  columnTracks,
  columnMaxWidth,
  columnMinWidth,
  columnWidth,
  fitLayout,
  gridHeight,
  isSlotEmpty,
  leftMinWidth,
  neighborSlot,
  normalizeLayout,
  slotFloor,
  slotMinHeight,
  swapSlots,
  COLUMN_GROW,
  fixedHeight,
  fixedMaxHeight,
  fixedSlot,
  wideWidth,
  withColumnWidth,
  withFixedHeight,
  type CardKey,
  type SlotKey,
} from './tradeLayout'
import { FUTURES_TABS, OPTION_TABS, type SlotTabs, type Tab } from './tradeScreenUtils'

/** 카드 배치 — 어느 카드가 어느 자리에 서는지, 끌어서 옮기기와 경계 크기 조절, 접기·확대. */
export function useTradeGrid({
  splitState,
  kind,
  tab,
  setTab,
  orders,
  fills,
  positions,
  ordersSince,
}: {
  splitState: SplitState
  kind: ProductKind
  tab: Tab
  setTab: Dispatch<SetStateAction<Tab>>
  orders: OpenOrder[]
  fills: Fill[]
  positions: Position[]
  ordersSince: string
}) {
  /* 슬롯마다 지금 열려 있는 카드. 적어 둔 것이 없으면 그 슬롯의 첫 카드입니다 —
     기억을 저장하지 않는 것은 탭이 「지금 무엇을 보는가」이지 배치가 아니기
     때문입니다. 다음에 열면 그 슬롯의 첫 카드부터 봅니다. */
  const [slotTabs, setSlotTabs] = useState<SlotTabs>({})
  /* 패널 편집 — 무엇을 보일지와 어느 슬롯에 둘지. 자리 교환은 손잡이가 합니다. */
  const [editorOpen, setEditorOpen] = useState(false)
  /* 차트 확대. 왼쪽 열이 차트 하나가 됩니다 — 탭 알약과 아래 칸이 숨고,
     호가와 주문 폼은 그대로입니다. 저장하지 않습니다: 다음에 열었을 때 주문
     내역이 안 보이는 화면으로 시작하면 왜 없는지 찾게 됩니다. */
  const [chartExpanded, setChartExpanded] = useState(false)
  /* 패널 배치 — 카드 여섯이 슬롯 넷 중 어디에 서는지와 경계 크기. 끌어서 바꾸고 저장합니다.
     저장된 값은 예전 모양일 수 있어 읽을 때 정규화합니다. */
  const [storedLayout, storeLayout] = useUiState<unknown>(LAYOUT_KEY, DEFAULT_LAYOUT)
  const layout = useMemo(() => normalizeLayout(storedLayout), [storedLayout])
  /* 끌고 있는 자리와, 놓으면 바꿀 자리. 키보드로 고른 대상도 같은 자리에
     듭니다 — 화살표로 고르고 Enter 로 확정, Esc 로 취소.
     **카드가 아니라 슬롯입니다.** 머리 띠는 그 자리에 선 것 전체를 가리키므로
     — 여럿이 서 있으면 띠가 탭 줄입니다 — 손잡이가 옮기는 것도 자리 전체입니다. */
  const [dragging, setDragging] = useState<SlotKey | null>(null)
  const [dropTarget, setDropTarget] = useState<SlotKey | null>(null)
  const [pending, setPending] = useState<{ from: SlotKey; to: SlotKey } | null>(null)
  /* 경계를 끄는 동안 포인터 옆에 뜨는 값 말풍선. 더 못 가는 끝에 닿으면 회색입니다. */
  const [resizeHint, setResizeHint] = useState<{ x: number; y: number; text: string; floor: boolean } | null>(null)
  /* 격자 자체. 경계를 끌 때 지금 쓸 수 있는 높이를 여기서 잽니다. */
  const splitRef = useRef<HTMLDivElement>(null)
  /* 격자가 지금 실제로 쓸 수 있는 폭과, 세로 막대가 잡아 둔 폭.
     경계를 끌 때의 한계와, 저장해 둔 폭이 지금 창에 안 맞을 때의 보정이 이
     값에 걸립니다. 창 크기가 바뀌어도 화면을 다시 그리지 않으므로 격자를
     담은 칸을 직접 지켜봅니다.

     창 크기와 칸 크기를 **둘 다** 듣습니다. 창을 넓히는 것은 창 쪽이 알려
     주고, 창은 그대로인데 옆의 최근 본 레일이 열려 본문만 좁아지는 것은 칸
     쪽이 알려 줍니다. 하나만 두면 나머지 경우에 폭이 옛 값에 멈춰, 창을
     넓혀도 열이 좁은 채로 남습니다. */
  const [room, setRoom] = useState({ width: 0, bar: 0 })
  /* 마지막으로 잰 값. 창을 끄는 동안 알림은 프레임마다 오는데 그중 대부분은
     치수가 그대로입니다 — 같은 값으로 상태를 건드리면 그때마다 화면을 다시
     그리려 들고, 차트가 그 렌더를 따라 다시 그립니다. */
  const roomRef = useRef(room)
  useLayoutEffect(() => {
    const grid = splitRef.current
    const outer = grid?.parentElement
    if (!grid || !outer) return
    const measure = () => {
      const bar = grid.offsetWidth - grid.clientWidth
      const next = { width: Math.max(0, outer.clientWidth - bar), bar }
      if (next.width === roomRef.current.width && next.bar === roomRef.current.bar) return
      roomRef.current = next
      setRoom(next)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(outer)
    observer.observe(grid)
    window.addEventListener('resize', measure)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', measure)
    }
  })

  /* 지금 포인터가 놓인 자리. 끌고 있는 카드는 포인터를 안 받으므로 제 위에
     있을 때는 아무것도 안 나옵니다 — 자기 자리에 놓는 것은 아무 일도 아닙니다.
     **칸 수가 다른 자리는 안 받습니다** — 넓은 카드가 좁은 자리에 서면 카드가
     제 모양을 잃습니다. 못 받는 자리 위에서는 아무 표시도 안 뜨므로, 손을
     떼 보고 나서 아는 일이 없습니다. */
  const slotUnder = (x: number, y: number, self: SlotKey): SlotKey | null => {
    const element = document.elementFromPoint(x, y)?.closest('.trade-card')
    const key = (element as HTMLElement | null)?.dataset.slot as SlotKey | undefined
    if (!key || key === self || !SLOTS.includes(key)) return null
    return SLOT_SPAN[key] === SLOT_SPAN[self] ? key : null
  }

  /* 끄는 동안 손끝을 따라다니는 쪽지. 카드는 제자리에 흐려진 채로 서 있으므로,
     카드 사이 빈 곳이나 경계 위에서는 이 쪽지만이 「지금 무엇을 들고 있는가」를
     말합니다.
     자리는 리렌더 없이 직접 적습니다 — 포인터가 움직일 때마다 화면을 다시
     그리면 차트가 매번 따라 그려집니다. */
  const chipRef = useRef<HTMLDivElement>(null)
  const chipPoint = useRef({ x: 0, y: 0 })
  const placeChip = (element: HTMLDivElement | null) => {
    chipRef.current = element
    if (element) {
      element.style.transform = `translate(${chipPoint.current.x}px, ${chipPoint.current.y}px)`
    }
  }

  const gripProps = (slot: SlotKey) => ({
    /* 카드 옮기기는 포인터로 직접 따라갑니다.
       브라우저의 끌어놓기에 맡기면 「여기 놓아도 되는가」를 받는 쪽이 매번
       되받아야 하고, 그 답이 한 번 늦으면 그 카드가 못 놓는 곳으로 굳습니다.
       경계 끌기와 같은 방식이라 화면 안에서 손이 한 가지로 움직입니다. */
    onPointerDown: (event: PointerEvent<HTMLButtonElement>) => {
      if (event.button !== 0) return
      /* 글자가 딸려 선택되지 않게 기본 동작을 막고, 초점은 직접 줍니다 —
         초점이 있어야 이어서 화살표 키로 옮길 수 있습니다. */
      event.preventDefault()
      event.currentTarget.focus()
      const startX = event.clientX
      const startY = event.clientY
      let moved = false
      const move = (ev: globalThis.PointerEvent) => {
        /* 몇 픽셀은 손 떨림입니다. 그 안에서는 아직 끌기가 아닙니다 —
           손잡이를 눌러 초점만 주려던 것이 자리 바꾸기가 되면 안 됩니다. */
        if (!moved && Math.abs(ev.clientX - startX) < 4 && Math.abs(ev.clientY - startY) < 4) return
        if (!moved) {
          moved = true
          setDragging(slot)
          setPending(null)
        }
        chipPoint.current = { x: ev.clientX, y: ev.clientY }
        placeChip(chipRef.current)
        aim()
      }
      /* 손끝 아래 카드를 다시 잽니다. 포인터가 움직일 때뿐 아니라 화면이
         스크롤할 때도 필요합니다 — 손을 세운 채 굴리면 카드가 손 밑으로
         지나가는데, 그때 표시가 안 따라오면 강조된 카드와 실제로 바뀌는 카드가
         달라집니다. */
      const aim = () => {
        const over = slotUnder(chipPoint.current.x, chipPoint.current.y, slot)
        setDropTarget((current) => (current === over ? current : over))
      }
      const track = () => {
        if (moved) aim()
      }
      const finish = (over: SlotKey | null) => {
        window.removeEventListener('pointermove', move)
        window.removeEventListener('pointerup', up)
        window.removeEventListener('pointercancel', cancel)
        window.removeEventListener('keydown', abort)
        window.removeEventListener('blur', cancel)
        window.removeEventListener('scroll', track, true)
        if (over) storeLayout(swapSlots(layout, slot, over))
        setDragging(null)
        setDropTarget(null)
      }
      const up = (ev: globalThis.PointerEvent) => {
        finish(moved ? slotUnder(ev.clientX, ev.clientY, slot) : null)
      }
      /* 끌기가 중간에 끊긴 경우입니다 — 창이 바뀌거나 브라우저가 제스처를
         가져간 것이라 손을 뗀 적이 없습니다. 자리는 그대로 둡니다. */
      const cancel = () => finish(null)
      /* 끌다가 무르기. 손을 떼기 전에 Esc 를 누르면 자리는 그대로입니다 —
         잘못 잡은 카드를 놓을 데 없이 들고 있는 상태가 없어야 합니다. */
      const abort = (ev: globalThis.KeyboardEvent) => {
        if (ev.key !== 'Escape') return
        ev.preventDefault()
        finish(null)
      }
      window.addEventListener('pointermove', move)
      window.addEventListener('pointerup', up)
      window.addEventListener('pointercancel', cancel)
      window.addEventListener('keydown', abort)
      /* 창이 뒤로 넘어가면 손을 뗀 자리를 받을 수 없습니다. 그대로 두면 다른
         창에 다녀온 사이에 카드가 들린 채로 남습니다. */
      window.addEventListener('blur', cancel)
      // 어느 칸이 스크롤하든 받으려고 내려가는 길에서 잡습니다.
      window.addEventListener('scroll', track, true)
    },
    onKeyDown: (event: KeyboardEvent) => {
      const direction = (
        { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' } as const
      )[event.key as 'ArrowLeft' | 'ArrowRight' | 'ArrowUp' | 'ArrowDown']
      if (direction) {
        event.preventDefault()
        /* 대상은 지금 고른 자리에서 한 칸씩 옮겨 갑니다. */
        const next = neighborSlot(pending?.to ?? slot, direction)
        if (!next) return
        /* 제 자리로 돌아오면 고른 것이 없는 상태입니다. 자기 자리에 놓는 것은
           아무 일도 아니라, 이때 제 카드에 「여기로 바꾸기」를 띄우면 눌러도
           아무 반응이 없는 단추가 됩니다 — 돌아오는 것이 곧 무르기입니다.
           빈 자리도 건너뜁니다 — 격자에서 빠져 있어 놓을 데가 없습니다. */
        setPending(next === slot || isSlotEmpty(layout, next) ? null : { from: slot, to: next })
        return
      }
      if (event.key === 'Enter' && pending?.from === slot) {
        event.preventDefault()
        storeLayout(swapSlots(layout, pending.from, pending.to))
        setPending(null)
        return
      }
      if (event.key === 'Escape' && pending) {
        event.preventDefault()
        setPending(null)
      }
    },
    onBlur: () => setPending(null),
  })

  /* 경계 끌기. 포인터를 경계에 잡아 두어 빠르게 움직여도 놓치지 않습니다. */
  const drag = (
    event: PointerEvent<HTMLDivElement>,
    apply: (dx: number, dy: number) => void,
  ) => {
    /* 경계를 잡는 동안 옆 카드의 글자가 딸려 선택되지 않게 합니다. */
    event.preventDefault()
    const startX = event.clientX
    const startY = event.clientY
    const element = event.currentTarget
    try {
      element.setPointerCapture(event.pointerId)
    } catch {
      // 포인터를 못 잡아도 경계 위에서 움직이는 동안은 따라옵니다.
    }
    element.dataset.active = 'true'
    const move = (ev: globalThis.PointerEvent) => {
      apply(ev.clientX - startX, ev.clientY - startY)
      setResizeHint((hint) => (hint ? { ...hint, x: ev.clientX, y: ev.clientY } : hint))
    }
    const up = () => {
      element.removeEventListener('pointermove', move)
      element.removeEventListener('pointerup', up)
      delete element.dataset.active
      delete element.dataset.limit
      setResizeHint(null)
    }
    element.addEventListener('pointermove', move)
    element.addEventListener('pointerup', up)
  }

  /* 경계는 **자리를 나눕니다.** 어느 경계를 끌든 카드 셋의 폭을 더한 값은 끌기
     전과 같습니다 — 한 칸이 넓어지면 이웃이 그만큼 좁아지고, 끌어서 화면을
     넓힐 수는 없습니다. 더 갈 곳이 없으면 커서가 갈 수 있는 쪽을 가리키고
     말풍선이 회색이 됩니다. */

  /* 왼쪽 열과 그 오른쪽 열 사이. 오른쪽으로 끌면 그 열이 좁아지고 왼쪽 열이
     그만큼 넓어집니다. 왼쪽 열이 제 바닥에 닿는 데서 멈춥니다.
     **어느 열이냐는 자리에 무엇이 서 있느냐가 정합니다** — 첫째 열이 비면
     왼쪽 열의 이웃은 둘째 열이고, 그때 이 경계가 그 둘을 나눕니다. */
  const startColumnResize =
    (column: 'r1' | 'r2', sign: 1 | -1) => (event: PointerEvent<HTMLDivElement>) => {
    const element = event.currentTarget
    const base = fitLayout(layout, room.width)
    const start = columnWidth(base, column)
    const min = columnMinWidth(base, column)
    const max = columnMaxWidth(base, column, room.width)
    /* 주문 폼이 선 열이면, 나란한 폼이 안 들어가는 폭에서 말풍선에 그 사실을
       덧붙입니다 — 폭만 보고는 폼 모양이 바뀐 까닭을 모릅니다. */
    const columnSlots: SlotKey[] = column === 'r2' ? ['r2'] : ['r1t', 'r1b']
    const formHere = columnSlots.some((slot) => base.slots[slot].includes('form'))
    const label = (width: number) => (formHere && width < FORM_ROOMY ? `${width}px · 좁은 폼` : `${width}px`)
    setResizeHint({ x: event.clientX, y: event.clientY, text: label(start), floor: min >= max })
    drag(event, (dx) => {
      const next = withColumnWidth(base, column, start + sign * dx, room.width)
      const width = columnWidth(next, column)
      storeLayout(next)
      element.dataset.limit =
        width <= min ? (sign === -1 ? 'left' : 'right') : width >= max ? (sign === -1 ? 'right' : 'left') : ''
      setResizeHint(
        (hint) => hint && { ...hint, text: label(width), floor: Math.round(start + sign * dx) !== width },
      )
    })
  }

  /* 행 경계. 아래로 끌면 위 칸이 커지고 아래 칸이 그만큼 줄어듭니다 — 아래
     칸이 제 바닥에 닿는 데서 멈춥니다. 열마다 하나씩 있고, 두 열의 경계가
     서는 높이는 서로 다릅니다(왼쪽은 차트 아래, 오른쪽은 호가 아래).
     말풍선에 적는 값은 **끌고 있는 위 칸의 높이**입니다 — 손이 잡은 것이
     경계이고, 그 경계가 정하는 것은 위 칸의 크기입니다. */
  const startRowResize = (column: 'left' | 'r1') => (event: PointerEvent<HTMLDivElement>) => {
    const element = event.currentTarget
    const base = fitLayout(layout, room.width)
    const start = fixedHeight(base, column, subjectShown)
    const floor = slotFloor(base, fixedSlot(column), subjectShown)
    const available = splitRef.current?.clientHeight ?? 0
    const ceiling = fixedMaxHeight(base, column, available, subjectShown)
    /* 끄는 방향과 값이 커지는 방향은 **정해진 쪽이 위냐 아래냐**에 따라
       반대입니다 — 아래 칸을 잡고 위로 끌면 그 칸이 커집니다. */
    const sign = COLUMN_GROW[column] === 'top' ? -1 : 1
    setResizeHint({ x: event.clientX, y: event.clientY, text: `${start}px`, floor: floor >= ceiling })
    drag(event, (_dx, dy) => {
      const next = withFixedHeight(base, column, start + sign * dy, available, subjectShown)
      const height = fixedHeight(next, column, subjectShown)
      storeLayout(next)
      element.dataset.limit =
        height <= floor ? (sign === 1 ? 'up' : 'down') : height >= ceiling ? (sign === 1 ? 'down' : 'up') : ''
      /* 더 못 가는 쪽에 닿았는지. 위아래 어느 끝이든 값이 안 따라오면 회색입니다. */
      setResizeHint(
        (hint) => hint && { ...hint, text: `${height}px`, floor: Math.round(start + sign * dy) !== height },
      )
    })
  }
  /* 체인을 볼 때 하단은 접혀 있습니다. 사용자가 펼치면 그 선택이 남습니다 —
     탭을 오갔다고 다시 접히면 자기가 편 것이 무시된 것으로 보입니다. */
  const [chainBottomOpen, setChainBottomOpen] = useStoredState('nh.trade.chainBottomOpen', false)
  /* 차트를 볼 때도 하단은 접혀 있습니다. 가장 작은 창(1200x720)에서 하단을
     펼친 채로 두면 카드마다 걸린 바닥이 창보다 커져, 열자마자 세로로 스크롤하는
     화면을 만나게 됩니다. 차트가 눌리지는 않지만 첫 화면이 스크롤로 시작할
     이유는 없습니다. 몇 건 있는지는 탭 옆 숫자가 말하고, 펼치는 것은 한 번
     누르면 됩니다 — 그 선택은 남습니다. */
  const [chartBottomOpen, setChartBottomOpen] = useStoredState('nh.trade.chartBottomOpen', false)
  const subjectShown = chartExpanded && splitState.split

  const tabs = kind === 'option' ? OPTION_TABS : FUTURES_TABS
  const activeTab: Tab = (tabs as readonly Tab[]).includes(tab) ? tab : tabs[0]

  /* 탭 옆 건수. 0 이면 배지를 안 답니다 — 「0건」을 적으면 없는 것을 매번
     읽게 됩니다. 건수가 있는 카드에만 답니다. */
  const counts: Partial<Record<CardKey, number>> = {
    orders: orders.length + fills.length,
    positions: positions.length,
  }
  /* 하단을 접을 수 있는 탭과, 그 탭이 기억하는 값. 탭마다 따로 기억합니다 —
     체인에서 접어 둔 것 때문에 차트에서도 접혀 있으면 고른 적 없는 상태입니다.
     접기는 「왼쪽 아래 칸」에 붙은 규칙입니다. 그 자리를 비우거나 차트를 그리로
     옮기면 접힘이 풀립니다 — 큰 칸으로 옮겨 놓고도 머리 띠만 남아 있으면,
     옮긴 자리가 통째로 빈 상자가 됩니다. */
  const collapsible =
    (activeTab === '체인' || activeTab === '차트') &&
    !isSlotEmpty(layout, 'lb') &&
    !layout.slots.lb.includes('chart')
  const bottomOpen = activeTab === '체인' ? chainBottomOpen : chartBottomOpen
  const setBottomOpen = activeTab === '체인' ? setChainBottomOpen : setChartBottomOpen
  const collapsed = collapsible && !bottomOpen
  /* 확대는 차트 탭에서만 뜻이 있습니다. 확대 중에는 탭 알약이 숨어 탭을 못
     바꾸므로 두 번째 조건은 지금 닿지 않습니다 — 옵션에서 체인 탭으로 열리는
     경로처럼 탭이 밖에서 바뀌는 경우를 막는 방어입니다. */
  const expandedChart = chartExpanded && activeTab === '차트'

  /* 확대 중에는 카드가 기본 자리에 섭니다. 폭은 사용자가 끌어 둔 값을 그대로
     쓰되, 바닥은 그 자리에 실제로 선 카드의 것으로 잽니다 — 자리와 바닥이
     어긋나면 호가 열이 차트의 바닥 폭만큼 벌어집니다. */
  const shownLayout = fitLayout(
    expandedChart ? { ...layout, slots: DEFAULT_LAYOUT.slots } : layout,
    room.width,
  )

  /* 지금 배치가 기본 그대로인지. 되돌릴 것이 없으면 되돌리는 단추가 비활성입니다. */
  const isDefaultLayout = JSON.stringify(layout) === JSON.stringify(DEFAULT_LAYOUT)

  /* 슬롯이 실제로 받는 폭. 좁은 열 둘은 제 폭이 정해져 있고, 넓은 열은
     그 둘과 경계가 쓰고 남는 만큼입니다. */
  const slotWidth = (slot: SlotKey): number =>
    slot === 'r1t' || slot === 'r1b'
      ? columnWidth(shownLayout, 'r1')
      : slot === 'r2'
        ? columnWidth(shownLayout, 'r2')
        : wideWidth(shownLayout, room.width)

  const slotsUsed = expandedChart ? DEFAULT_LAYOUT.slots : layout.slots
  const slotOfCard = (card: CardKey): SlotKey | null =>
    SLOTS.find((slot) => slotsUsed[slot].includes(card)) ?? null

  /* 차트 확대에서 자리를 비우는 카드. 주문 내역은 확대 중에 숨으므로, 그 카드만
     든 자리는 배치에서 빈 자리로 셉니다. */
  const HIDDEN_WHILE_EXPANDED: CardKey[] = ['orders', 'positions']
  const hiddenWhileExpanded = (slot: SlotKey): boolean => {
    const cards = slotsUsed[slot]
    return cards.length > 0 && cards.every((card) => HIDDEN_WHILE_EXPANDED.includes(card))
  }

  /* 슬롯에서 지금 열려 있는 카드. 고른 적이 없거나 고른 카드가 그 자리를 떠났으면
     첫 카드입니다. */
  const openIn = (slot: SlotKey): CardKey | null => {
    const cards = slotsUsed[slot]
    const picked = slotTabs[slot]
    return picked && cards.includes(picked) ? picked : (cards[0] ?? null)
  }

  /* 이 카드를 지금 그리는가. 숨긴 카드와, 같은 슬롯에서 지금 열려 있지 않은
     카드는 자리를 차지하지 않습니다.
     DOM 에서 지우지 않고 감춥니다 — 탭을 오갈 때마다 차트가 다시 만들어지면
     봉을 다시 그리고 스크롤 자리를 잃습니다. */
  const cardShown = (card: CardKey): boolean => {
    const slot = slotOfCard(card)
    return slot !== null && openIn(slot) === card
  }
  /* 카드가 서는 자리. 격자는 **열 다섯에 행 하나**이고, 위아래로 갈리는 두
     열은 행을 나누는 대신 카드에 높이와 위 여백을 적어 세웁니다.
     행 트랙으로 가르지 않는 이유는 **두 열의 경계가 서는 높이가 다르기**
     때문입니다 — 왼쪽은 차트 아래(355), 오른쪽 첫 열은 호가 아래(312)라
     한 행 트랙으로는 둘을 동시에 못 맞춥니다.
     위 칸은 제 높이만 쓰고, **아래 칸은 남는 높이를 다 가집니다**(`stretch`)
     — 그래서 열이 늘어나도 카드 안에 빈 자리가 안 생깁니다. */
  /* 슬롯이 속한 열과, 그 열이 지금 몇째 트랙에 서는지. **열 순서는 사용자가
     바꿉니다** — 카드가 어느 열에 속하는지는 안 바뀌고 열째로 자리를 옮깁니다. */
  const tracks = columnTracks(shownLayout)
  const columnOfSlot = (slot: SlotKey) =>
    (Object.keys(COLUMN_SLOTS) as (keyof typeof COLUMN_SLOTS)[]).find((key) =>
      COLUMN_SLOTS[key].includes(slot),
    )!
  const trackOf = (slot: SlotKey) => 1 + tracks.findIndex((t) => t.column === columnOfSlot(slot)) * 2
  const cardStyle = (card: CardKey): CSSProperties => {
    const slot = slotOfCard(card)
    if (slot === null) return { display: 'none' }
    /* 한 자리에 상한이 다른 좁은 카드가 함께 서면(예: 호가 320 + 시세체결 200)
       열은 큰 쪽에 맞으므로 작은 쪽만 제 상한에서 멈춥니다. */
    const cap = CARD_MAX_WIDTH[card]
    const base: CSSProperties = {
      gridColumn: trackOf(slot),
      /* 행은 하나뿐이라 모두 1 행에 둡니다. 안 적으면 격자가 카드마다 행을
         새로 만들어 세로로 늘어세웁니다. */
      gridRow: 1,
      display: cardShown(card) ? undefined : 'none',
      ...(cap === undefined ? {} : ({ '--card-max': `${cap}px` } as CSSProperties)),
    }
    const column = slot === 'lt' || slot === 'lb' ? 'left' : slot === 'r2' ? null : 'r1'
    if (column === null) return { ...base, alignSelf: 'stretch' }

    const isTop = slot === 'lt' || slot === 'r1t'
    const other: SlotKey = column === 'left' ? (isTop ? 'lb' : 'lt') : isTop ? 'r1b' : 'r1t'

    /* 확대 중에는 짝이 숨은 자리만 남는 높이를 다 씁니다.
       **위아래로 갈린 열은 확대에서도 갈라야 합니다** — 격자가 열 하나에 행
       하나뿐이라, 둘 다 그 행을 통째로 쓰면 두 카드가 같은 칸에 겹쳐 서고
       나중에 그려지는 쪽만 보입니다. */
    if (expandedChart) {
      if (isSlotEmpty(shownLayout, other) || hiddenWhileExpanded(other)) {
        return { ...base, alignSelf: 'stretch' }
      }
    } else if (isSlotEmpty(shownLayout, other)) {
      /* 짝이 비면 **남은 카드는 제 크기 그대로**이고 열 아래가 빕니다.
         늘려 채우면 카드 테두리와 머리 띠가 빈 자리를 감싸 「덜 그려진 카드」가
         됩니다 — 빈 것은 카드 안이 아니라 열입니다. */
      return { ...base, alignSelf: 'start', height: slotFloor(shownLayout, slot, subjectShown) }
    }

    /* 정해진 쪽은 제 높이로 제자리에 붙고, 늘어나는 쪽이 나머지를 다 씁니다. */
    const fixed = fixedHeight(shownLayout, column, subjectShown)
    const isFixed = slot === fixedSlot(column)
    if (isFixed) {
      return isTop
        ? { ...base, alignSelf: 'start', height: fixed }
        : { ...base, alignSelf: 'end', height: fixed }
    }
    return isTop
      ? { ...base, alignSelf: 'stretch', marginBottom: fixed + GUTTER }
      : { ...base, alignSelf: 'stretch', marginTop: fixed + GUTTER }
  }
  const highlight = (card: CardKey) => {
    const slot = slotOfCard(card)
    return slot !== null && (dropTarget === slot || pending?.to === slot)
  }
  /* 끄는 동안 **받을 수 있는 자리**를 밝힙니다. 어디에 놓을 수 있는지가 손을
     떼기 전에 보여야, 못 놓는 자리에 가져갔다가 되돌아오는 일이 없습니다.
     들고 있는 자리 자신은 뺍니다 — 제자리에 놓는 것은 아무 일도 아닙니다. */
  const droppable = (card: CardKey) => {
    const held = dragging ?? pending?.from ?? null
    if (held === null) return false
    const slot = slotOfCard(card)
    return slot !== null && slot !== held && SLOT_SPAN[slot] === SLOT_SPAN[held]
  }

  /* 확대 중에는 배치가 고정이라 손잡이가 없습니다. 그래도 자리는 비워 둡니다 —
     치우면 카드 이름이 왼쪽으로 24 튀어, 확대를 오갈 때마다 이름이 움직입니다.
     띠 왼쪽의 식별 물체는 카드마다 늘 같은 x 에 서야 합니다. */
  const grip = (slot: SlotKey) =>
    expandedChart ? (
      <span className="card-grip-space" aria-hidden="true" />
    ) : (
      <button
        type="button"
        className="card-grip"
        aria-label={`${slotsUsed[slot].map((key) => CARD_LABEL[key]).join('·')} 자리 옮기기 — 끌거나 화살표 키로 고르고 Enter`}
        title="끌어서 자리 바꾸기"
        {...gripProps(slot)}
      >
        <svg viewBox="0 0 10 14" aria-hidden="true">
          <circle cx="2" cy="2" r="1.5" />
          <circle cx="8" cy="2" r="1.5" />
          <circle cx="2" cy="7" r="1.5" />
          <circle cx="8" cy="7" r="1.5" />
          <circle cx="2" cy="12" r="1.5" />
          <circle cx="8" cy="12" r="1.5" />
        </svg>
      </button>
    )

  /* 머리 띠의 오른쪽 끝. 이 카드 자체에 대한 동작만 섭니다 — 크기·자리·펼침
     입니다. 보이는 값을 바꾸는 것은 전부 구분선 아래에 둡니다.
     설 것이 하나도 없으면 빈 상자도 두지 않습니다. */
  const cardActions = (action?: ReactNode) =>
    action ? <div className="card-head-actions">{action}</div> : null

  /* 차트 확대 — 차트가 왼쪽 열 전체가 됩니다. 「이 카드를 열 전체로」는 카드에
     대한 동작이라 도구 줄이 아니라 머리 띠에 섭니다. 확대 중에도 이 단추만은
     남습니다 — 없으면 돌아오는 길이 Esc 뿐입니다. */
  const chartExpandButton = activeTab !== '차트' ? null : (
    <button
      type="button"
      className="btn btn-quiet card-head-btn"
      aria-pressed={expandedChart}
      aria-label={expandedChart ? '차트 축소' : '차트 확대'}
      data-tip={expandedChart ? undefined : '차트 확대'}
      onClick={() => setChartExpanded(!chartExpanded)}
    >
      {expandedChart ? '축소 ⤡' : '⤢'}
    </button>
  )

  const cardProps = (card: CardKey) => {
    const slot = slotOfCard(card)
    return {
      style: cardStyle(card),
      'data-card': card,
      'data-slot': slot ?? undefined,
      /* 좁은 칸에 선 카드. 주문 내역 표들이 열 묶음을 다시 짜는 조건입니다 —
         자리가 아니라 폭을 봅니다. */
      'data-narrow': slot && slotWidth(slot) < ORDERS_WIDE ? 'true' : undefined,
      /* 주문 폼이 줄 이름과 입력칸을 나란히 못 두는 폭. 그때 폼은 줄 이름을
         입력칸 위로 올립니다(`trade.css` 의 `.card-form[data-tight]`). */
      'data-tight': card === 'form' && slot && slotWidth(slot) < FORM_ROOMY ? 'true' : undefined,
      'data-drop': highlight(card) ? 'true' : undefined,
      'data-droppable': droppable(card) ? 'true' : undefined,
      'data-lifting': slot !== null && dragging === slot ? 'true' : undefined,
    }
  }

  /* 카드 머리 띠의 왼쪽. 그 자리에 여럿이 서면 탭 줄이고, 하나면 이름 글자입니다 —
     띠 왼쪽의 식별 물체는 카드마다 정확히 하나이고 모양만 다릅니다. */
  const slotTabStrip = (slot: SlotKey) => {
    const cards = slotsUsed[slot]
    if (cards.length < 2) return <span className="card-name">{CARD_LABEL[cards[0]]}</span>
    const open = openIn(slot)
    return (
      <div className="tabs tabs-inline trade-tabs">
        {cards.map((key) => (
          <button
            key={key}
            type="button"
            className="tab"
            aria-current={open === key}
            onClick={() => {
              setSlotTabs((current) => ({ ...current, [slot]: key }))
              if (slot === 'lb' && collapsed) setBottomOpen(true)
            }}
          >
            {CARD_LABEL[key]}
            {(counts[key] ?? 0) > 0 && <span className="tab-count">{counts[key]}</span>}
          </button>
        ))}
      </div>
    )
  }

  /* 차트가 무엇을 보여줄지 고르는 줄. 카드 안의 내용 탭이지 자리 탭이 아닙니다. */
  const chartTabStrip = (
    <div className="tabs tabs-inline trade-tabs">
      {tabs.map((item) => (
        <button
          key={item}
          type="button"
          className="tab"
          aria-current={activeTab === item}
          onClick={() => setTab(item)}
        >
          {item}
        </button>
      ))}
    </div>
  )
  /* 차트가 다른 카드와 한 자리에 서면 머리 띠는 자리 탭이 가져갑니다 —
     내용 탭은 본문 첫 줄로 내려갑니다. */
  const chartSlot = slotOfCard('chart')
  const chartTabsInBody = chartSlot !== null && slotsUsed[chartSlot].length > 1

  /* 카드 머리 띠. 왼쪽은 손잡이, 가운데는 이 자리의 식별 물체, 오른쪽은 이
     카드에 대한 동작입니다.
     `own` 은 그 카드가 혼자 설 때 이름 대신 세울 것입니다 — 차트처럼 카드
     자체가 탭을 가진 경우에만 씁니다. */
  const cardHead = (card: CardKey, action?: ReactNode, own?: ReactNode) => {
    const slot = slotOfCard(card)
    if (slot === null) return null
    const grouped = slotsUsed[slot].length > 1
    return (
      <div className="card-head">
        {grip(slot)}
        {grouped ? slotTabStrip(slot) : (own ?? <span className="card-name">{CARD_LABEL[card]}</span>)}
        {cardActions(action)}
      </div>
    )
  }

  /* 접힘은 「왼쪽 아래 칸」에 붙은 규칙이라, 그 자리에 선 카드에만 걸립니다.
     같은 카드를 다른 자리로 옮기면 접히지 않습니다. */
  const collapsibleFor = (card: CardKey) => collapsible && slotOfCard(card) === 'lb'
  const collapsedFor = (card: CardKey) => collapsibleFor(card) && !bottomOpen

  /* 아래 두 카드의 머리 띠 오른쪽. 주문체결상세는 「언제부터」를 달고, 접을 수
     있는 자리면 접기 단추가 그 뒤에 섭니다. 미결제약정에는 「언제부터」가 없습니다 —
     알림으로 잇는 표가 아니라 체결마다 다시 조회하는 표라, 담긴 구간이 아니라
     마지막 조회가 그 값이고 그것은 이미 목록 얼굴이 말합니다. */
  const bottomHeadActions = (card: CardKey): ReactNode => {
    const note =
      card === 'orders' && ordersSince ? <span className="card-note">{ordersSince} 부터</span> : null
    const fold = collapsibleFor(card) ? (
      <button
        type="button"
        className="btn btn-quiet card-head-btn"
        aria-expanded={!collapsedFor(card)}
        onClick={() => setBottomOpen(collapsedFor(card))}
      >
        {collapsedFor(card) ? '펼치기' : '접기'}
      </button>
    ) : null
    if (!note && !fold) return undefined
    return (
      <>
        {note}
        {fold}
      </>
    )
  }

  /* 아래 칸이 접혀 머리 띠만 남았으면 그 칸은 내용 높이만 씁니다.
     접힘 자체가 그 자리에 붙은 규칙입니다. */
  const bottomCollapsed = collapsed

  /* 격자가 창에게 부르는 크기. 가로와 세로가 서로 다른 약속입니다.
   *
   * 가로는 앱의 최소 창(1200)이 받아 줍니다. 기본 배치가 1102(차트 598 +
   * 호가 200 + 주문 280 + 경계 둘 24)이고 세로 막대까지 1112 라, 최소 창이
   * 그보다 넓어 기본 배치에서는 가로로 밀리지 않습니다. 최근 본 패널을 열면
   * 화면 폭이 패널만큼 줄어(창 1280 미만에서 패널 160) 앱 틀 1200 에서 952,
   * 앱 틀이 창보다 13 좁게 잡힌 기록의 최소 창(앱 틀 1187)에서 939 입니다.
   * 그때는 넓은 열이 바닥(주문체결상세 415)까지 줄어 기본 배치가 932(415 + 200 +
   * 280 + 24 + 세로 막대 13)로 들어갑니다 — 패널이 1280 미만에서 좁아지는 것이
   * 이 폭 때문입니다(`shell.css` 의 `--panel-width`). 넓은 카드 셋을 나란히 세우는 배치를 만들면
   * 그때는 밀립니다 — 줄이는 것이 아니라 미는 것이 규칙입니다.
   *
   * 세로는 최소 창이 다 받아 주지 않습니다. 기본 배치에서 **왼쪽 열**이
   * 579(차트 355 + 경계 12 + 미결제약정 212)를 부르는데 최소 창에서 격자가
   * 받는 높이는 497 이라 82 가 모자랍니다 — 1366x768 노트북에서 창이 화면보다
   * 커지지 않게 720 을 택한 결과입니다. 오른쪽 첫 열은 464(호가 312 + 경계 12
   * + 시세체결 140)라 이 높이에 들어옵니다. 모자란 만큼은 `.trade-split` 이
   * 세로로 스크롤해서 받습니다. 카드를 뭉개는 것보다 스크롤이 낫습니다 —
   * 뭉개진 호가는 단계가 잘린 채로 값처럼 보입니다. 첫 화면에는 차트와 호가가
   * 온전히 서고 시세체결·주문 내역·주문 폼의 아래가 잘리며, **주문 실행 단추는
   * 첫 화면 안에 남습니다**(폼은 위에서부터 차고 아래가 빕니다).
   *
   * **빈 자리는 격자에서 통째로 빠집니다.** 카드를 다 끈 열은 폭도 경계도
   * 0 이라, 그 자리에 아무것도 없다는 것이 빈 칸이 아니라 없는 칸으로
   * 보입니다 — 빈 칸을 남기면 왜 비었는지 알 수 없는 구멍이 생기고, 그 옆
   * 경계는 아무것도 나누지 않는 손잡이가 됩니다. */
  const [gutterLR, gutterRR] = columnGaps(shownLayout)
  /* 경계가 설 자리와, 그 경계가 어느 좁은 열을 바꾸는지.
     양쪽에 나눌 것이 있고 한쪽이 좁은 열일 때만 섭니다 — 넓은 열끼리는 없고,
     좁은 열 둘 사이라면 오른쪽 것을 바꿉니다(왼쪽으로 끌면 넓어집니다). */
  const colSplits = ([0, 1] as const)
    .map((at) => {
      const gap = at === 0 ? gutterLR : gutterRR
      const left = tracks[at].column
      const right = tracks[at + 1].column
      const narrow = (key: typeof left): 'r1' | 'r2' | null =>
        key === 'narrow' ? 'r1' : key === 'far' ? 'r2' : null
      const target = narrow(right) ? { column: narrow(right)!, sign: -1 as const, label: COLUMN_LABEL[right] }
        : narrow(left) ? { column: narrow(left)!, sign: 1 as const, label: COLUMN_LABEL[left] }
        : null
      /* 확대에서는 **넓은 열에 닿는 경계만** 잠깁니다. 차트가 남는 폭을 다 쓰는
         것이 확대의 뜻이라 그 폭을 손으로 정할 자리가 아닙니다. 좁은 열끼리의
         경계는 그대로 삽니다 — 확대해도 호가와 주문 폼의 폭은 사용자 것입니다. */
      const locked = expandedChart && (left === 'wide' || right === 'wide')
      return gap > 0 && target ? { at, ...target, locked } : null
    })
    .filter((split): split is NonNullable<typeof split> => split !== null)
  /* 행 경계가 설 자리. 위아래 둘 다 카드가 있는 열에만 섭니다 — 한쪽이 비면
     나눌 것이 없어 아무것도 안 나누는 손잡이가 됩니다.
     접혀 있는 동안에는 왼쪽 경계를 감춥니다: 접힌 칸은 머리 띠 하나라
     경계를 끌어 봐야 그 띠가 커지지 않습니다. */
  /* 확대에서도 **오른쪽 열의 경계는 삽니다** — 차트가 남는 자리를 다 쓸 뿐
     호가와 시세체결은 여전히 위아래로 갈리고, 그 비율은 사용자가 정할 값입니다.
     왼쪽 열은 확대 중 아래 칸이 숨어 나눌 것이 없으므로 아래 거르개에서 빠집니다. */
  const rowSplits = ([
    { column: 'left', label: '왼쪽 열', on: !bottomCollapsed },
    { column: 'r1', label: '오른쪽 첫째 열', on: true },
  ] as const
  )
      .filter((split) => {
        const [top, bottom] = split.column === 'left' ? (['lt', 'lb'] as const) : (['r1t', 'r1b'] as const)
        if (!split.on || isSlotEmpty(shownLayout, top) || isSlotEmpty(shownLayout, bottom)) return false
        if (expandedChart && (hiddenWhileExpanded(top) || hiddenWhileExpanded(bottom))) return false
        return true
      })
      .map((split) => {
        /* 경계는 **정해진 쪽 카드에 붙어** 섭니다 — 왼쪽 열은 아래 칸 위에,
           오른쪽 첫 열은 위 칸 아래에. 잡는 손은 그 칸의 크기를 바꿉니다. */
        const fixed = fixedHeight(shownLayout, split.column, subjectShown)
        return {
          ...split,
          gridColumn: trackOf(split.column === 'left' ? 'lt' : 'r1t'),
          edge:
            COLUMN_GROW[split.column] === 'top'
              ? ({ alignSelf: 'end', marginBottom: fixed } as const)
              : ({ alignSelf: 'start', marginTop: fixed } as const),
        }
      })
  const height = expandedChart
    ? Math.max(slotMinHeight(shownLayout, 'lt'), slotMinHeight(shownLayout, 'r2'))
    : gridHeight(shownLayout)
  const gridStyle = {
    /* 트랙 다섯 — 열 · 경계 · 열 · 경계 · 열. 차례는 사용자가 정한 열 순서를
       그대로 따르고, 넓은 열만 남는 폭을 다 씁니다. */
    gridTemplateColumns: tracks
      .map((t) => (t.width === null ? `minmax(${leftMinWidth(shownLayout)}px, 1fr)` : `${t.width}px`))
      .flatMap((track, at) => (at === 0 ? [track] : [`${at === 1 ? gutterLR : gutterRR}px`, track]))
      .join(' '),
    /* 행은 하나입니다. 위아래로 갈리는 열은 카드가 제 높이와 위 여백으로
       세웁니다(`cardStyle`) — 두 열의 경계 높이가 서로 다르기 때문입니다.
       `minmax` 라 창이 더 높으면 행이 늘고, 늘어난 몫은 각 열의 아래 칸이
       가집니다. */
    gridTemplateRows: `minmax(${height}px, 1fr)`,
    /* 세로 막대가 잡아 둔 폭을 함께 셉니다. 이 값은 테두리까지 친 폭이라,
       막대 몫을 빼면 열들이 그만큼 밀려 가로 막대가 하나 더 생깁니다. */
    minWidth:
      leftMinWidth(shownLayout) +
      columnWidth(shownLayout, 'r1') +
      columnWidth(shownLayout, 'r2') +
      gutterLR +
      gutterRR +
      room.bar,
  }

  return {
    setSlotTabs,
    editorOpen,
    setEditorOpen,
    chartExpanded,
    setChartExpanded,
    storeLayout,
    layout,
    dragging,
    pending,
    resizeHint,
    splitRef,
    placeChip,
    startColumnResize,
    startRowResize,
    subjectShown,
    activeTab,
    setBottomOpen,
    expandedChart,
    isDefaultLayout,
    slotsUsed,
    slotOfCard,
    chartExpandButton,
    cardProps,
    chartTabStrip,
    chartTabsInBody,
    cardHead,
    collapsedFor,
    bottomHeadActions,
    colSplits,
    rowSplits,
    gridStyle,
  }
}
