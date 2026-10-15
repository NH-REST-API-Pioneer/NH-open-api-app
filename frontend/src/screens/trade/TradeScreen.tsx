import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from 'react'
import type {
  MarketContext,
  OpenIntent,
  Fill,
  OpenOrder,
  Position,
  ProductKind,
  PendingAxis,
} from '../../lib/types'
import { contractRows } from '../../data/expiryQuotes'
import { sendOrder, type OrderAsk, type OrderResult } from '../../data/orders'
import { noteTradeNotice } from '../../data/alerts'
import { noteAcceptedOrder, reloadAccountLists } from '../../data/account'
import { OrderConfirm, type OrderConfirmAsk } from './OrderConfirm'
import { retryChain, useOptionChain, type ChainArgs } from '../../data/optionChain'
import {
  ORDERABLE_IDLE,
  askOrderable,
  canAskOrderable,
  overseasFormType,
  type OrderableAsk,
  type OrderableState,
} from '../../data/orderable'
import {
  contractsOf,
  defaultContractCode,
  defaultInstrumentCode,
  expiryOption,
  needsLeg,
  productsOf,
  resolve,
  spreadLegsLine,
  strikeDecimalsOf,
  type Instrument,
  type OptionLeg,
} from '../../data/instruments'
import type { MasterLegs } from '../../data/master'
import { InstrumentHeader } from './InstrumentHeader'
import { OrderBook } from './OrderBook'
import { OrderForm, type EditMode, type OrderEdit, type Side } from './OrderForm'
import { ChartPanel } from './ChartPanel'
import type { InstrumentRef } from '../../lib/InstrumentPicker'
import { SPLIT_KEY, defaultSplit, normalizeSplit, type SlotState, type SplitState } from './chartSlots'
import { MarketDataPanel, ProductInfoPanel } from './InfoPanels'
import { OrdersAndFills } from './OrdersAndFills'
import {
  retryList,
  useListOnce,
  type DepositMarket,
  type ListEntry,
  type ServerOrder,
  type ServerPosition,
} from '../../data/account'
import { toPosition, toTradeRow } from '../../data/accountRows'
import { OptionChain, type ChainPick, type ChainSide } from './OptionChain'
import { PAPER_NIGHT_PRICE_TEXT, quoteEntry, retryQuote, TRADE_KEEP } from '../../data/quotes'
import { useQuote } from '../../data/instrumentQuote'
import { useStreamStatus, useWishes, wishKey, type Wish } from '../../data/stream'
import {
  domesticContextOf,
  domesticProductDetail,
  loadSession,
  subscribeSession,
  useSession,
  useTimetable,
} from '../../data/session'
import { marketConfigured, useEnvironment } from '../../data/environment'
import { earlierClock, kstMinutes } from '../../lib/kst'
import { useStoredState } from '../../lib/useStoredState'
import { useUiState } from '../../data/uiState'
import { PanelEditor } from './PanelEditor'
import { TickTape } from './TickTape'
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
import { DOMESTIC_PRESETS, NIGHT_PRESETS, OVERSEAS_PRESETS } from './chainFields'
import { fillCondFor } from '../../data/strategyRules'
import './trade.css'

/* 일반주문 — 가장 오래 머무는 화면.
 *
 * 세 열입니다. 왼쪽이 차트·품목정보와 그 아래 주문체결상세·미결제약정,
 * 가운데가 호가와 시세체결, 오른쪽이 주문 폼입니다.
 *
 * 폭은 호가 200 과 주문 폼 280 이 고정이고 왼쪽 열이 남는 폭을 다 씁니다.
 * 경계선을 끌어 조절하지 않습니다 — 고정 둘이 정해져 있으면 왼쪽 폭도 이미
 * 정해진 값이라, 끌 수 있게 두면 창을 넓혀도 안 따라오는 자리가 생깁니다.
 *
 * 호가가 가운데에서 전체 높이를 씁니다. 위아래 10단계에 현재가 줄까지 21행이라
 * 이 화면의 세로 예산을 호가가 정하고, 나머지가 그 옆에서 맞춰 섭니다.
 * 하단 탭을 화면 전체 폭이 아니라 왼쪽 열 안에 두는 것도 그 때문입니다.
 *
 * 호가·주문은 탭이 바뀌어도 그대로 있습니다. 호가를 눌러 주문 가격을 넣는
 * 것이 이 화면의 기본 동작이라 사이에 다른 것이 끼면 손이 끊깁니다.
 *
 * 선물과 옵션은 같은 화면의 두 입구입니다. 옵션은 행사가 축이 하나 더 있어
 * 종목이 바로 정해지지 않으므로, 왼쪽 열 첫 탭에 체인이 서고 거기서 고른
 * 칸이 헤더·호가·주문의 종목이 됩니다.
 */

const FUTURES_TABS = ['차트', '품목정보'] as const
const OPTION_TABS = ['체인', '차트', '품목정보'] as const
type Tab = (typeof OPTION_TABS)[number]

/* 슬롯 안에서 몇 번째 카드가 열려 있는지. 슬롯에 하나만 서면 쓰이지 않습니다. */
type SlotTabs = Partial<Record<SlotKey, CardKey>>


/* 2분할을 처음 켤 때 둘째 칸에 넣는 종목 — 이 화면 종목의 차월물입니다.
 * 같은 차트 둘로 시작하면 「왜 같은 게 둘이지」가 되고, 근월·차월을 나란히
 * 보는 것이 두 칸의 가장 흔한 쓰임입니다. 차월물이 없으면 그 종목 그대로입니다. */
function nextMonthOf(item: Instrument | null): InstrumentRef | null {
  /* **지금 보고 있는 종목의** 차월물입니다. 시장에서 첫 선물 품목을 집으면
     무엇을 보고 있든 코스피200(해외면 WTI)이 둘째 칸에 서서, 근월·차월을
     견주려던 자리에 남의 종목이 들어옵니다. */
  if (!item || item.kind !== 'futures') return null
  const market: MarketContext = item.market === 'overseas' ? 'overseas' : 'domestic-day'
  const contracts = contractRows(item.product, 'futures')
  const index = contracts.findIndex((row) => row.code === item.contract?.code)
  const row = contracts[index >= 0 ? index + 1 : 1] ?? contracts[0]
  if (!row) return null
  return {
    code: row.code,
    name: row.name,
    productName: item.product.name,
    market,
    lastPrice: row.last,
    decimals: item.product.decimals ?? 2,
    currency: item.market === 'overseas' ? 'USD' : '원',
  }
}

/* 코드 하나를 차트 칸이 들 수 있는 모양으로 바꿉니다.
 *
 * 칸은 신원만이 아니라 배지에 그릴 값까지 들고 있어, 코드만으로는 칸을 채울 수
 * 없습니다. 신원은 해석기에서, 값은 그 품목의 만기 목록에서 받습니다 — 두 곳을
 * 쓰지만 **어느 종목인가는 해석기 하나가 정합니다.** */
function refFor(code: string): InstrumentRef | null {
  const item = resolve(code)
  if (!item) return null
  const market: MarketContext = item.market === 'overseas' ? 'overseas' : 'domestic-day'
  /* 옵션은 행사가마다 종목이라 만기 목록에 없습니다. 값은 기초 선물의 것을
     쓰고, 행사가를 고르면 체인이 그 칸의 값을 냅니다. */
  const row = contractRows(item.product, item.kind).find((entry) => entry.code === code)
  return {
    code,
    name: item.name,
    productName: item.product.name,
    market,
    /* 배지에 적을 값은 **그 품목의 만기 목록에 실린 행**에서 옵니다(위 `row`).
       그 값은 만기 목록 조회가 받아 둔 것입니다(`data/expiryQuotes.ts`).

       **행이 없거나 그 월물이 답에 없으면 빈 채로 둡니다** — 옵션 만기 코드처럼
       목록에 안 서는 종목이 있고, 조회에 안 실려 온 월물도 있습니다. 그때 다른
       줄의 값이나 대신 지은 숫자를 세우면 그 배지가 이 종목의 현재가로 읽힙니다. */
    lastPrice: row?.last ?? null,
    decimals: item.product.decimals ?? 2,
    currency: item.market === 'overseas' ? 'USD' : '원',
  }
}


/* 자리가 모자랄 때 무엇이 남아야 하나. **주문 대상 종목이 가장 높습니다** —
 * 그 값이 멈추면 지금 내려는 주문의 가격이 낡습니다. 두 칸 모드의 다른 칸은
 * 보고는 있지만 주문 대상이 아니라 한 급 아래이고, 홈의 관심종목은 훑는
 * 자리라 그보다 아래입니다(`HomeScreen`). */
/** 계좌가 바뀌어 주문을 접은 뒤 실행 단추를 멈춰 두는 시간(ms). */
const SUBMIT_PAUSE_MS = 1500

const SUBJECT_RANK = 9
const SECOND_RANK = 7

/** 해외 옵션 시리즈 코드(`O_ESU26`) — 품목코드 + 월물 글자 + 연도 뒤 두 자리.
 *
 *  **색인이 코드를 안 줄 때만 씁니다.** 한 달에 만기가 하나인 품목은 만기년월로
 *  지으면 맞지만, 여럿인 품목은 만기마다 다른 코드라 이 규칙으로는 못 짓습니다. */
const MONTH_LETTERS = 'FGHJKMNQUVXZ'
function overseasSeriesCode(productCode: string, expiry: string): string | null {
  if (expiry.length < 6) return null
  const month = Number(expiry.slice(4, 6))
  if (!Number.isInteger(month) || month < 1 || month > 12) return null
  return `${productCode}${MONTH_LETTERS[month - 1]}${expiry.slice(2, 4)}`
}

interface Props {
  /** 검색과 카탈로그가 기본으로 훑을 범위. **이 화면의 종목은 여기서 안 나옵니다** —
   *  종목은 코드가 정하고, 시장도 코드에서 나옵니다. */
  context: MarketContext
  /** 밖에서 고른 종목의 코드. 홈·종목 화면·최근 본·검색이 모두 이 하나로 들어옵니다. */
  openedCode: string | null
  /** 무엇을 하러 왔는가. 없으면 새 주문입니다. */
  openedIntent?: OpenIntent | null
  /** 못 푸는 코드를 만났을 때. 화면 위 한 줄로 이유가 섭니다. */
  onOpenFailed: (code: string) => void
  /** 설정 창 열기. 그 시장의 인증 정보가 없을 때 헤더가 이 길을 냅니다. */
  onOpenSettings?: () => void
}

/** 시장마다 받은 잔고 목록을 **표 하나의 상태**로 합칩니다.
 *
 *  한 시장이라도 줄이 있으면 그 줄들로 표가 섭니다 — 다른 시장이 아직 오지
 *  않았거나 못 받았다고 받은 줄까지 가리지 않습니다(못 받은 시장은 표 위 한 줄이
 *  따로 말합니다). 받은 시장이 **모두** 새로 받기에 실패했을 때만 그 사정을
 *  이어받아 표 전체의 「지난 값」 문장이 섭니다 — 한 시장만 옛값이면 그 시장
 *  이름을 단 한 줄이 따로 말합니다. 줄이 하나도 없으면 받는 중인 시장의 얼굴을,
 *  없으면 첫 시장의 얼굴(못 받음 등)을 씁니다. 찬 시장이 없으면 `fallback`
 *  (인증 정보가 없어 안 부른 자리)입니다. */
function mergedPositionList(
  entries: ListEntry<ServerPosition>[],
  fallback: ListEntry<ServerPosition>,
): ListEntry<ServerPosition> {
  if (entries.length === 0) return fallback
  const received = entries.filter((entry) => entry.rows !== null)
  if (received.length === 0) {
    return entries.find((entry) => entry.status === 'loading' || entry.status === 'idle') ?? entries[0]
  }
  return {
    ...received[0],
    status: 'ready',
    rows: received.flatMap((entry) => entry.rows ?? []),
    failure: received.every((entry) => entry.failure !== null) ? received[0].failure : null,
    refreshing: entries.some((entry) => entry.refreshing === true || entry.status === 'loading'),
  }
}

/** 그 종목이 스프레드면 두 다리의 만기(마스터 값), 아니면 `null`. */
function spreadLegsOf(code: string): MasterLegs | null {
  const found = resolve(code)
  return found?.contract?.kind === 'spread' ? (found.contract.legs ?? null) : null
}

export function TradeScreen({ context, openedCode, openedIntent, onOpenFailed, onOpenSettings }: Props) {
  /* 이 화면이 보고 있는 종목 — **코드 하나**입니다.
     품목·만기·선물인지 옵션인지·어느 시장인지가 전부 여기서 풀려 나오므로,
     화면이 그것들을 따로 기억하지 않습니다. 기억이 여럿이면 서로 어긋나고,
     어긋나면 헤더가 말하는 종목과 주문 단추가 내는 종목이 갈립니다. */
  const [selectedCode, setSelectedCode] = useState<string | null>(
    /* 밖에서 고르고 들어오지 않았으면 이 시장의 기본 종목으로 엽니다. 코드를
       비워 두면 화면은 기본 종목의 값을 보여주면서 만기 목록만 비어, 어느
       만기를 보고 있는지가 헤더에서 사라집니다. */
    openedCode ?? defaultInstrumentCode(context === 'overseas' ? 'overseas' : 'domestic'),
  )

  const [tab, setTab] = useState<Tab>('차트')
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

  /* 2분할 상태 — 켜져 있는지, 어느 칸이 주문 대상인지, 칸마다 종목·봉·지표.
     남깁니다: 축소했다 다시 확대해도, 앱을 껐다 켜도 두 칸이 그대로 돌아옵니다.
     저장된 것은 예전 모양일 수 있어 읽을 때 정규화합니다. */
  const [storedSplit, storeSplit] = useUiState<unknown>(SPLIT_KEY, defaultSplit())
  const splitState = useMemo(() => normalizeSplit(storedSplit), [storedSplit])
  const setSplitState = (next: SplitState) => storeSplit(next)
  const patchSlot = (slot: 0 | 1, patch: Partial<SlotState>) => {
    const slots: [SlotState, SlotState] = [{ ...splitState.slots[0] }, { ...splitState.slots[1] }]
    slots[slot] = { ...slots[slot], ...patch }
    setSplitState({ ...splitState, slots })
  }
  /* 코드를 종목으로 풉니다. 모르는 코드(상장이 끝난 종목)면 `null` 이고, 그때는
     이 시장의 기본 종목을 봅니다.
     **스프레드도 이 경로로 옵니다** — 검색·종목 화면이 스프레드를 이 화면으로
     보냅니다. 값은 선물과 같은 자리에 서고, 주문만 아직 막혀 있습니다. */
  const selected = useMemo(() => (selectedCode ? resolve(selectedCode) : null), [selectedCode])
  /* 그 종목의 시장에 인증 정보가 없는지. 그러면 그 종목의 시세·호가·체인·세션을
     **묻지 않습니다** — 빈 키로 물으면 토큰 발급부터 실패해 오류만 쌓입니다. 헤더가
     까닭을 한 번 말하고 주문 폼이 잠깁니다. 설정이나 접속 환경을 아직 모르면
     「없다」고 하지 않습니다 — 그때는 환경을 확인하는 중이라는 말이 먼저 섭니다. */
  const environment = useEnvironment()
  const credentialsMissing = (item: Instrument | null): boolean => {
    const view = environment.config
    const env = view?.active_environment ?? null
    return item !== null && view !== null && env !== null && !marketConfigured(view, env, item.market)
  }
  /* 시장은 **종목이** 정하고, 낮이냐 밤이냐는 **서버가 답한 세션**이 정합니다 —
     같은 종목을 낮에 보든 밤에 보든 품목과 만기는 같고, 세션은 화면의 시계가
     아니라 서버의 판정입니다(`data/session.ts`). 세션이 바뀌면 이 값이 바뀌어
     실시간 선언과 조회가 야간 것으로 다시 나가되, **주문 폼은 그대로입니다** —
     같은 계좌입니다. 화면의 `context` 는 검색·카탈로그의 기본 범위로만 남습니다. */
  useSyncExternalStore(
    subscribeSession,
    () =>
      `${domesticContextOf(selectedCode ?? '')}|${domesticContextOf(splitState.slots[1].instrument?.code ?? '')}`,
    () => '',
  )
  const contextOf = (item: Instrument | null): MarketContext =>
    item?.market === 'overseas'
      ? 'overseas'
      : item
        ? domesticContextOf(item.contract?.code ?? '')
        : context

  /* 체인에서 고른 칸. 고르기 전에는 없고, 그동안 헤더·호가·주문은 기초
     선물을 봅니다 — 옵션 탭을 눌렀다고 임의의 행사가를 골라주지 않습니다.
     축 둘(콜풋·행사가)만 들고 있고 값은 체인에서 찾습니다 — 값을 복사해 두면
     체인이 갱신될 때 헤더가 낡은 값을 들고 있게 됩니다.

     **두 축을 따로 듭니다.** 한 상태로 묶으면 한쪽만 골라도 나머지가 기본값으로
     채워져, 고른 적 없는 값으로 종목이 정해지고 주문 폼에 실립니다. 둘 다
     정해져야 종목입니다.

     **어느 쪽을 먼저 골라도 나머지를 채우지 않습니다.** 등가(ATM)를 채워 두면
     그 순간 주문 단추가 살아나, 사용자가 고른 적 없는 행사가로 주문을 낼 수 있는
     상태가 됩니다 — 반대 축(행사가를 먼저 고른 경우)은 막혀 있으므로 두 축의
     안전성도 달라집니다. 체인 칸만 한 번에 둘 다 정합니다: 거기서는 콜/풋과
     행사가가 한 칸에 있어 누른 것 자체가 두 축을 다 고른 것입니다. */
  const [pickedSide, setPickedSide] = useState<'call' | 'put' | null>(null)
  const [pickedStrike, setPickedStrike] = useState<number | null>(null)
  const [preset, setPreset] = useState(0)
  const [chainSide, setChainSide] = useState<ChainSide>('both')
  /* 체인을 볼 때 하단은 접혀 있습니다. 사용자가 펼치면 그 선택이 남습니다 —
     탭을 오갔다고 다시 접히면 자기가 편 것이 무시된 것으로 보입니다. */
  const [chainBottomOpen, setChainBottomOpen] = useStoredState('nh.trade.chainBottomOpen', false)
  /* 차트를 볼 때도 하단은 접혀 있습니다. 가장 작은 창(1200x720)에서 하단을
     펼친 채로 두면 카드마다 걸린 바닥이 창보다 커져, 열자마자 세로로 스크롤하는
     화면을 만나게 됩니다. 차트가 눌리지는 않지만 첫 화면이 스크롤로 시작할
     이유는 없습니다. 몇 건 있는지는 탭 옆 숫자가 말하고, 펼치는 것은 한 번
     누르면 됩니다 — 그 선택은 남습니다. */
  const [chartBottomOpen, setChartBottomOpen] = useStoredState('nh.trade.chartBottomOpen', false)

  /* 매수·매도와 **그 값을 누가 정했는가**.
   *
   * 방향은 사용자가 고르기도 하고 화면이 정하기도 합니다 — 청산·정정으로
   * 들어오면 보유나 원주문의 반대쪽으로 화면이 정합니다. 값만 두면 그 둘을
   * 구별할 수 없어서, 그 모드가 풀릴 때 화면이 정해 둔 값을 사용자가 고른
   * 값으로 오해하고 그대로 남깁니다.
   *
   * `user` 는 사용자가 단추로 고른 값이라 아무도 못 되돌립니다. `system` 은
   * 화면이 잠깐 정해 둔 값이라, 그 모드가 끝나면 **사용자가 마지막으로 고른
   * 값**으로 돌아갑니다. */
  const [side, setSideValue] = useState<Side>('buy')
  /* 출처와, 사용자가 마지막으로 고른 방향. **화면에 그리지 않는 값**이라 상태가
     아니라 ref 입니다 — 이것들이 바뀐다고 다시 그릴 것은 없습니다. 화면이 잠깐
     다른 값을 세워 둔 동안에도 `userSide` 는 그대로라 되돌아갈 자리가 남습니다. */
  const sideFrom = useRef<'user' | 'system'>('user')
  const userSide = useRef<Side>('buy')

  /* 사용자가 단추로 고른 방향. 기억해 두고 출처를 `user` 로 둡니다. */
  const chooseSide = (next: Side) => {
    userSide.current = next
    sideFrom.current = 'user'
    setSideValue(next)
  }
  /* 화면이 정한 방향(청산·정정). **사용자가 고른 값은 건드리지 않습니다** —
     청산이 연달아 와도(청산 → 다른 종목에서 또 청산 → 해제) 기억해 둔 값은
     그대로라, 마지막에 풀릴 때 사용자가 마지막으로 고른 값으로 돌아갑니다.
     화면이 정한 값이 그다음 화면 값의 바탕이 되면, 몇 번 오갔는지에 따라
     돌아갈 자리가 달라집니다. */
  const setSideBySystem = (next: Side) => {
    sideFrom.current = 'system'
    setSideValue(next)
  }
  /* 청산·정정이 풀릴 때. 화면이 정해 둔 값이면 사용자 값으로 되돌리고,
     사용자가 그동안 단추로 직접 고쳤으면 그 값이 이깁니다. */
  const releaseSystemSide = () => {
    if (sideFrom.current === 'system') setSideValue(userSide.current)
    sideFrom.current = 'user'
  }
  const [orderType, setOrderType] = useState('지정가')
  const [condition, setCondition] = useState('FAS')
  /* **비운 채로 엽니다.** 시세가 오면 아래에서 한 번 채우고(`filledForRef`),
     사용자가 손댄 뒤에는 덮지 않습니다 — 처음부터 숫자를 세워 두면 그 값이
     어디서 왔는지 모르는 채로 주문이 나갑니다. */
  const [price, setPrice] = useState<number | null>(null)
  const [stopPrice, setStopPrice] = useState<number | null>(null)
  const [quantity, setQuantity] = useState(1)
  const [editing, setEditing] = useState<OrderEdit | null>(null)
  const [closing, setClosing] = useState<Position | null>(null)
  /* 청산 가격이 어디서 왔나 — 받아 둔 시세(`quote`), 잔고 줄 값(`position`),
     사용자가 고친 값(`user`). **잔고 줄 값인 동안만** 그 종목의 첫 시세가 오면
     한 번 갈아 끼웁니다(아래 효과). 청산 모드가 아니면 `null` 입니다. */
  const [closePriceFrom, setClosePriceFrom] = useState<'quote' | 'position' | 'user' | null>(null)
  /* 사용자가 가격을 건드렸다고 적습니다. 잔고 값으로 채운 동안에만 뜻이 있습니다 —
     친 값은 시세가 와도 덮지 않습니다. */
  const touchPrice = () => setClosePriceFrom((from) => (from === 'position' ? 'user' : from))
  /* 되묻는 창에 걸어 둔 주문. 창이 떠 있는 동안 여기 있고, 그만두면 없어집니다. */
  const [confirming, setConfirming] = useState<{ ask: OrderAsk; show: OrderConfirmAsk } | null>(null)
  /* 계좌가 바뀌어 주문을 접은 직후 잠깐 실행 단추를 멈춥니다(`SUBMIT_PAUSE_MS`). 눌러
     가던 손이 새 모드의 단추를 그대로 누르지 않게 하려는 것입니다. */
  const [submitPaused, setSubmitPaused] = useState(false)
  const pauseTimer = useRef<number | null>(null)
  const pauseSubmit = () => {
    if (pauseTimer.current !== null) window.clearTimeout(pauseTimer.current)
    setSubmitPaused(true)
    pauseTimer.current = window.setTimeout(() => {
      pauseTimer.current = null
      setSubmitPaused(false)
    }, SUBMIT_PAUSE_MS)
  }
  useEffect(
    () => () => {
      if (pauseTimer.current !== null) window.clearTimeout(pauseTimer.current)
    },
    [],
  )
  /* 보낸 뒤 답을 기다리는 중인지. 폼과 실행 단추를 잠급니다. */
  const [sending, setSending] = useState(false)
  /* 마지막으로 보낸 주문의 답. **시간으로 안 사라집니다** — 아래 효과가
     사용자의 다음 손에 걷어냅니다. */
  const [orderResult, setOrderResult] = useState<OrderResult | null>(null)
  /* 주문가능수량은 계좌를 물어봐야 나오는 값이라 누르기 전에는 없습니다. */
  const [orderable, setOrderable] = useState<OrderableState>(ORDERABLE_IDLE)
  /* 지금 나가 있는 물음이 어느 것인지. **늦게 온 답을 버리는 자리입니다** —
     조건을 바꾸며 여러 번 누르면 먼저 부른 답이 뒤에 도착할 수 있고, 그러면
     화면이 지금 조건이 아닌 답을 말합니다. */
  const orderableAskRef = useRef(0)
  /* 폼을 비우지 않고 넘어갈 종목. 청산·정정으로 화면을 그 종목으로 옮길 때
     그 코드를 담습니다. 「한 번 건너뛰기」가 아니라 「이 코드일 때 건너뛰기」인
     것은, 옮겨 간 곳이 지금 보는 종목과 같으면 아래 효과가 아예 돌지 않아
     건너뛸 차례가 오지 않기 때문입니다. */
  const keepModeForRef = useRef<string | null>(null)
  /** 해외 정정·취소가 폼에 옮긴 원주문의 주문유형을 지킬 시장. 다른 시장에서
   *  정정하러 들어오면 시장이 바뀌면서 주문유형을 처음으로 돌리는 효과가 도는데,
   *  그때 옮긴 값이 지워지지 않게 합니다. */
  const keepTypeForRef = useRef<MarketContext | null>(null)
  /** 이 종목의 주문가격을 이미 한 번 채웠는지. 실시간이 값을 갈아 끼울 때마다
   *  다시 채우면 사용자가 친 값이 덮입니다. */
  const filledForRef = useRef<string | null>(null)

  /* 둘째 차트 칸의 종목. 첫째 칸과 **같은 길로** 풉니다 — 코드에서 신원을 얻고
     신원에서 시세를 얻습니다. 칸마다 다른 길로 만들면 한쪽만 고쳐지는 자리가
     생깁니다. */
  const secondCode = splitState.slots[1].instrument?.code ?? null
  const secondSelected = useMemo(() => (secondCode ? resolve(secondCode) : null), [secondCode])

  /* 헤더·호가·주문 폼이 보는 종목 = **주문 대상인 칸**의 종목. 2분할에서 둘째
     칸이 대상이면 그 종목이고, 그 밖에는 화면의 종목입니다.

     **옵션의 축(콜/풋·행사가)도 여기서부터 나옵니다.** 아래 체인·시세·헤더가
     모두 이 값을 기준으로 서므로, 첫째 칸을 기준으로 두면 둘째 칸이 주문
     대상인 옵션일 때 헤더의 두 셀렉트만 첫째 칸을 가리킵니다. */
  const secondIsSubject = splitState.split && splitState.active === 1 && secondSelected !== null
  const subject = secondIsSubject ? secondSelected : selected

  /* 체인이 설 옵션 품목. 지금 보는 종목이 옵션이면 **그 종목의 품목**입니다 —
     「미니 코스피200 옵션」을 골랐는데 체인에 「코스피200 옵션」이 서면 고른
     것과 보이는 것이 갈립니다. 선물을 보는 동안에는 **그 종목이 선 시장의**
     옵션 품목이 기본으로 섭니다 — 화면이 어느 시장에서 시작했는지가 아니라
     지금 보고 있는 종목이 어느 시장인지를 따릅니다. */
  const optionProduct = useMemo(
    () =>
      subject?.kind === 'option'
        ? subject.product
        : (productsOf(contextOf(subject) === 'overseas' ? 'overseas' : 'domestic').find(
            (item) => item.kinds.includes('option'),
          ) ?? null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [context, subject],
  )
  /* 체인이 설 만기 줄. 고른 옵션의 만기가 있으면 그것입니다 — 12월물 옵션을
     골랐는데 9월물 체인이 서면 고른 것과 보이는 것이 갈립니다. */
  const chainRef =
    subject?.kind === 'option' && subject.contract
      ? subject.contract
      : optionProduct
        ? (contractsOf(optionProduct, 'option')[0] ?? null)
        : null
  /* 국내는 만기일(8자리), 해외는 만기 연월(6자리)이고, 한 달에 만기가
     여럿인 품목은 해외도 만기일입니다. */
  const chainExpiry = chainRef?.expiry ?? null
  /* 체인을 부를 때 보낼 시리즈 코드. **값만 들고 다닙니다** — 줄 그대로
     들면 매번 새 객체가 되어 체인 조회가 다시 나갑니다. */
  const chainSeries = chainRef?.seriesCode ?? null
  const chainOverseas = optionProduct !== null && contextOf(subject) === 'overseas'
  /* 국내 체인은 세션을 함께 묻습니다 — 야간에는 야간 체인입니다. 세션은 종목마다
     서버가 답하므로 **그 품목의 기본 선물**로 묻습니다(옵션 만기 줄에는 세션이
     없습니다). */
  const chainMissing = credentialsMissing(subject)
  const chainAnchor =
    optionProduct && !chainOverseas && !chainMissing
      ? (defaultContractCode('domestic', optionProduct.code, 'futures') ?? '')
      : ''
  const chainSession = useSession('domestic', chainAnchor)
  /* 무엇을 물을지. 국내는 품목의 거래대상코드·만기일·세션, 해외는 거래소 코드·
     시리즈 코드입니다. 마스터가 그 값을 안 주면 못 묻고, 체인은 「받는 중」에
     머뭅니다 — 지어낸 인자로 다른 것을 받아 오지 않습니다. */
  const chainArgs = useMemo((): ChainArgs | null => {
    if (!optionProduct || !chainExpiry || chainMissing) return null
    if (chainOverseas) {
      /* 색인이 시리즈 코드를 주면 그것을 그대로 보냅니다 — 한 달에
         만기가 여럿인 품목은 만기년월로 지으면 아홉이 한 코드로 뭉칩니다. */
      const sym = chainSeries ?? overseasSeriesCode(optionProduct.code, chainExpiry)
      return optionProduct.exchangeCode && sym
        ? { market: 'overseas', exchCd: optionProduct.exchangeCode, sym }
        : null
    }
    if (!optionProduct.tradeCode || chainExpiry.length !== 8) return null
    return {
      market: 'domestic',
      prd: optionProduct.tradeCode,
      expMon: chainExpiry.slice(2),
      session: chainSession.session === 'night' ? 'night' : 'day',
    }
  }, [optionProduct, chainExpiry, chainSeries, chainOverseas, chainSession.session, chainMissing])
  /* 그 체인이 어느 품목·만기의 것인지. 서버에 보내는 값이 아니라, 답에 실려 온
     해외 옵션 종목코드를 신원표에 적을 때 씁니다(`data/optionChain.ts`). */
  const chainOwner = useMemo(
    () => (optionProduct && chainExpiry ? { productCode: optionProduct.code, expiry: chainExpiry } : null),
    [optionProduct, chainExpiry],
  )
  /* 체인 탭이 보이는 동안만 5초마다 다시 묻습니다(`data/optionChain.ts`). 체인
     탭은 옵션에만 있어, 선물을 보는 동안 탭 값이 남아 있어도 묻지 않습니다. */
  const chain = useOptionChain(chainArgs, chainOwner, tab === '체인' && subject?.kind === 'option')
  const chainRows = chain.rows ?? []

  const strikes = useMemo(() => chainRows.map((row) => row.strike), [chainRows])
  /* 기초 선물과 등가격. 국내 주간은 당월 선물 현재가에 가장 가까운 행사가이고,
     해외는 서버가 표시한 줄입니다. 야간처럼 둘 다 없으면 표시가 없습니다. */
  const futuresPrice = chain.future?.last ?? null
  const atm = useMemo(() => {
    if (futuresPrice !== null && chainRows.length > 0) {
      return chainRows.reduce((best, row) =>
        Math.abs(row.strike - futuresPrice) < Math.abs(best.strike - futuresPrice) ? row : best,
      ).strike
    }
    return chainRows.find((row) => row.call.atm || row.put.atm)?.strike ?? null
  }, [chainRows, futuresPrice])
  /* **체인이 실제로 쓰는 행사가 축**에서 셉니다. 품목의 값 자리 수로 어림하면
     반 칸씩 놓인 행사가가 반올림돼 적히고, 그 글자로 줄을 찾는 자리에서는 다른
     계약이 열립니다. */
  const strikeDecimals = useMemo(() => strikeDecimalsOf(strikes), [strikes])
  /* 둘 다 정해졌을 때만 종목입니다. 한쪽만 고른 상태는 「아직 고르는 중」이라
     헤더·차트·주문 폼이 기초 선물을 봅니다. */
  const pickedRow =
    pickedStrike !== null ? chainRows.find((row) => row.strike === pickedStrike) : undefined
  const pickedLeg =
    pickedRow && pickedSide ? (pickedSide === 'call' ? pickedRow.call : pickedRow.put) : null
  const pickedLabel =
    pickedSide && pickedStrike !== null
      ? `${pickedSide === 'call' ? '콜' : '풋'} ${pickedStrike.toFixed(strikeDecimals)}`
      : ''
  /* 아직 안 고른 축. 행사가가 남았으면 그것부터 말합니다 — 체인이 행사가로
     늘어서 있어 다음에 할 일이 그쪽입니다. */
  /* 축 둘을 한 번에 정하는 자리. 체인 칸과 밖에서 들어온 코드가 여기를 지납니다 —
     둘 다 「콜 425.0」처럼 한 종목을 통째로 가리키므로 갈라 넣을 것이 없습니다. */
  const pickLeg = (leg: OptionLeg | null) => {
    setPickedSide(leg?.side ?? null)
    setPickedStrike(leg?.strike ?? null)
  }
  /* 체인 칸은 콜/풋과 행사가가 한 칸에 있으므로 한 번에 둘 다입니다. **체인이 준
     원본 값을 그대로** 받습니다 — 화면에 적힌 글자를 되읽지 않습니다. */
  const pickFromChain = (pick: ChainPick) => pickLeg({ side: pick.side, strike: pick.strike })
  /* 코드에서 읽는 길. **코드가 콜/풋까지만 말해 주는 경우가 있습니다** — 국내
     옵션 종목코드가 그렇고, 그때 콜/풋을 버리면 사용자가 코드에 적어 넣은 것을
     화면이 다시 물어봅니다. 행사가는 색인에 없어 그대로 남습니다. */
  const pickFromCode = (item: Instrument | null) => {
    setPickedSide(item?.leg?.side ?? item?.side ?? null)
    setPickedStrike(item?.leg?.strike ?? null)
  }

  /* **코드가 아직 계약이 아닐 때만** 「고르는 중」입니다. 고른 축이 없다고 해서
     고르는 중인 것은 아닙니다 — 국내 옵션 종목코드는 상장된 계약인데 마스터에
     행사가 칸이 없어, 체인을 열기 전에는 행사가를 모른 채로 섭니다. 그때까지
     「고르는 중」으로 두면 이미 고른 종목을 화면이 다시 물어봅니다. */
  /* 체인 표가 「고른 줄」로 볼 코드. **주문 대상 종목(`subject`)에서 꺼냅니다** —
     두 칸으로 나눠 놓고 둘째 칸이 주문 대상일 때 첫째 칸의 코드로 견주면, 표가
     남의 줄을 켜거나 켤 줄을 못 찾아 등가격으로 떨어집니다. */
  const subjectCode = subject?.contract?.code ?? ''
  const chainPickedCode =
    pickedLeg?.code ??
    (subject?.kind === 'option' && !needsLeg(subjectCode) ? subjectCode || null : null)

  const pendingAxis: PendingAxis | null =
    subject?.kind === 'option' && needsLeg(subjectCode) && !pickedLeg
      ? pickedStrike === null
        ? 'strike'
        : 'side'
      : null

  /* 두 칸의 시세. **고른 축은 주문 대상인 칸에만 싣습니다** — 양쪽에 실으면
     대상이 아닌 칸까지 그 행사가의 값을 그리고, 그 칸이 든 종목과 갈립니다.
     신원과 시세를 한 자리에서 함께 고르므로 둘이 어긋날 수 없습니다. */
  const first = useQuote(
    selected,
    contextOf(selected),
    secondIsSubject ? null : pickedLeg,
    secondIsSubject ? '' : pickedLabel,
    secondIsSubject ? null : pendingAxis,
    credentialsMissing(selected),
  )
  const second = useQuote(
    secondSelected,
    contextOf(secondSelected),
    secondIsSubject ? pickedLeg : null,
    secondIsSubject ? pickedLabel : '',
    secondIsSubject ? pendingAxis : null,
    credentialsMissing(secondSelected),
  )
  const quote = first.quote
  const secondQuote = second.quote
  const shownEntry = secondIsSubject ? second.entry : first.entry
  const shownAsked = secondIsSubject ? second.asked : first.asked
  const shownBuilt = secondIsSubject ? second.built : first.built
  const shownUnasked = secondIsSubject ? second.unasked : first.unasked

  /* **이 화면이 지금 보고 있는 것**을 실시간 쪽에 알립니다. 등급은 「자리가
     모자라면 무엇이 남아야 하나」입니다 — 주문 대상 종목이 가장 높고, 두 칸
     모드의 다른 칸이 그다음입니다. 홈의 관심종목은 그보다 낮게 겁니다.
     목록을 통째로 넘기는 것은 계약이 「지금 보고 있는 것 전체」를 받기 때문입니다. */
  const wishes = useMemo(() => {
    const want: Wish[] = []
    const add = (code: string, context: MarketContext, priority: number) => {
      if (!code) return
      want.push({ context, kind: 'quote', sym: code, priority })
      want.push({ context, kind: 'book', sym: code, priority })
    }
    /* 인증 정보가 없는 시장의 종목은 걸지 않습니다 — 조회와 같은 까닭입니다. */
    if (!credentialsMissing(selected)) {
      add(quote.code, contextOf(selected), secondIsSubject ? SECOND_RANK : SUBJECT_RANK)
    }
    if (splitState.split && !credentialsMissing(secondSelected)) {
      add(secondQuote.code, contextOf(secondSelected), secondIsSubject ? SUBJECT_RANK : SECOND_RANK)
    }
    /* 계좌의 주문/체결 알림은 이 화면이 걸지 않습니다 — 앱이 찬 시장마다 한 번 겁니다
       (`App.tsx` 의 `account-orders`). 같은 구독을 두 자리가 걸지 않게 합니다. */
    return want
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    quote.code,
    secondQuote.code,
    secondIsSubject,
    splitState.split,
    selected,
    secondSelected,
    /* 세션이 바뀌면 같은 종목이라도 맥락(주간/야간)이 바뀌어 다시 선언합니다. */
    contextOf(selected),
    contextOf(secondSelected),
    /* 인증 정보를 채우면 그 시장의 종목을 다시 겁니다. */
    environment.config,
  ])
  useWishes('trade', wishes)

  /* 값이 안 서는 까닭은 둘이고 **사용자가 할 일이 다릅니다.**
     못 받은 것은 다시 불러 볼 만하고(연결·시간 초과), 거절은 눌러도 같은 답이며,
     **받았는데 값이 안 찬 것은 아직 거래가 없는 것**이라 다시 부를 일이
     아닙니다. 셋을 한 얼굴로 두면 사용자가 될 때까지 단추를 누릅니다. */
  const shownFailure: {
    kind: 'retry' | 'rejected' | 'paper' | 'empty' | 'unasked'
    withValues: boolean
    text?: string
  } | null = shownUnasked
    ? /* **이 시장은 아직 안 물어봅니다.** 값이 없는 것이 실패가 아니라, 우리가
         그 조회를 아직 안 붙인 것입니다. 사용자가 할 일이 없으므로 다시
         받는 단추도 안 세웁니다. */
      { kind: 'unasked', withValues: false }
    : shownEntry.failure
      ? { kind: shownEntry.failure, withValues: shownBuilt, text: shownEntry.failureText }
      : shownAsked && shownEntry.status === 'ready' && !shownBuilt
        ? { kind: 'empty', withValues: false }
        : null

  /* 호가는 따로 실패합니다 — 현재가가 와도 호가만 못 받을 수 있습니다. 그때
     빈 사다리를 세우면 「호가가 없다」로 읽히므로 그 카드가 제 말을 합니다.
     **까닭도 그 호출의 것을 씁니다** — 호가가 거절당했으면 다시 부를 일이
     아니라 단추를 안 세웁니다. 값이 안 찬 것(`empty`)은 호가와 무관하니
     호가는 받은 대로 그립니다. **모의투자라 현재가만 못 받은 것(`paper`)도
     호가와 무관합니다** — 호가는 제 조회의 답대로 섭니다. */
  const bookFailure: {
    kind: 'retry' | 'rejected' | 'empty' | 'unasked'
    withValues: boolean
  } | null = shownUnasked
    ? { kind: 'unasked', withValues: false }
    : shownEntry.failure && shownEntry.failure !== 'paper'
      ? { kind: shownEntry.failure, withValues: shownBuilt }
      : shownAsked && shownEntry.status === 'ready' && shownEntry.book === null
        ? { kind: shownEntry.bookFailure ?? 'retry', withValues: false }
        : null

  /* 이 종목의 값을 실제로 아는지 — **받아서 세운 값이 있을 때만** 참입니다.
     「아직 안 물어봤다」(종목 색인이 오기 전의 창, 축을 안 고른 옵션)는 모르는
     것입니다. 그 자리에 서는 기초 선물의 값은 「무엇을 고르는 중인가」를 보이는
     것이지 이 종목의 값이 아니라, 그 값으로 주문을 낼 수 없습니다. */
  const priceKnown = !shownUnasked && shownAsked && shownBuilt

  /* **값을 모르는 것과 주문을 막는 것은 다릅니다.**
     못 받음·거절은 우리가 이 종목의 값을 모르는 상태라, 낼 값을 지어낼 수 없어
     막습니다. **아직 거래가 없는 것(`empty`)은 우리가 아는 상태**입니다 — 응답이
     왔고 「값이 아직 없다」가 그 답입니다. 상장되어 호가가 서 있으면 그 종목에
     첫 거래를 만드는 것이 지정가 주문이므로, 값 자리는 비워 두되 사용자가
     적어 넣으면 낼 수 있어야 합니다. 아는 것을 모른다고 다루면 멀쩡한 종목에
     주문을 못 냅니다. */
  const orderBlocked = !priceKnown && shownFailure?.kind !== 'empty'
  /* **모의인지 실전인지 모르면 주문을 낼 수 없습니다.** 어느 계좌로 나가는지를
     화면이 말하지 못하는 상태라, 값을 알아도 막습니다. 까닭은 행사가·시세보다
     앞에 섭니다 — 그것들을 고쳐도 이것이 풀리지 않으면 낼 수 없습니다. 가능수량
     조회도 같은 까닭으로 못 묻습니다(그 수는 계좌의 것입니다).
     바꾸는 중은 「모름」이 아닙니다 — 서버가 답하기 전까지 옛 환경이 참이고, 그동안
     이 화면은 잠긴 설정 창 뒤에 있어 여기서 또 문장을 세우지 않습니다. */
  const environmentKnown =
    environment.active !== null &&
    (environment.status === 'ready' || environment.status === 'switching')
  const environmentWhy = environmentKnown
    ? undefined
    : environment.status === 'failed'
      ? '모의인지 실전인지 확인하지 못해 주문을 낼 수 없습니다'
      : '모의인지 실전인지 확인하는 중입니다'
  const shownQuote = secondIsSubject ? secondQuote : quote
  /* **국내 주문은 주간인지 야간인지 알아야 나갑니다** — 주문 요청이 그 세션의 길을
     싣습니다. 그래서 야간 창이 있는 품목은 그 종목의 세션 답이 올 때까지 잠급니다.
     **야간 창이 없는 품목은 세션을 안 기다립니다** — 주간뿐이라 물을 것이 없고, 그
     품목은 세션을 묻지 않는 자리도 있어 기다리면 늘 잠깁니다. 시간표를 아직 모르면
     야간 창을 가릴 수 없어 세션 답으로 가립니다. 해외 주문은 세션과 무관합니다.
     세션은 헤더가 이 종목으로 묻습니다(`InstrumentHeader` 의 `useSession`). */
  const timetable = useTimetable()
  const sessionCode =
    subject?.market === 'domestic' && !needsLeg(shownQuote.code) && !credentialsMissing(subject)
      ? shownQuote.code
      : ''
  /* 그 시장의 인증 정보가 없어 못 내는 까닭. 주문 폼의 까닭 가운데 맨 앞입니다. */
  const credentialsWhy =
    subject !== null && credentialsMissing(subject)
      ? `${subject.market === 'overseas' ? '해외' : '국내'} 인증 정보가 없어 주문을 낼 수 없습니다`
      : undefined
  const sessionHeld = useSession('domestic', sessionCode)
  const nightWindow =
    subject !== null &&
    domesticProductDetail(
      subject.product.tradeCode,
      subject.kind === 'option' ? 'option' : 'futures',
      'night',
    ) !== null
  const sessionWhy =
    !sessionCode || sessionHeld.status === 'ready' || (timetable === 'ready' && !nightWindow)
      ? undefined
      : sessionHeld.status === 'failed'
        ? '주간인지 야간인지 확인하지 못해 주문을 낼 수 없습니다'
        : '주간인지 야간인지 확인하는 중입니다'
  /* 헤더 제목 아래 서는 다리 한 줄. **헤더가 보고 있는 종목**에서 나옵니다 —
     화면을 둘로 나눠 둘째 칸이 주문 대상이면 그 칸의 종목입니다. 스프레드가
     아니거나 다리 만기가 안 실려 오면 `null` 이고 줄을 만들지 않습니다. */
  const legsLine = useMemo(() => {
    const shown = resolve(shownQuote.code)
    return shown?.contract?.kind === 'spread' && shown.contract.legs
      ? spreadLegsLine(shown.contract.legs)
      : null
  }, [shownQuote.code])
  const subjectShown = chartExpanded && splitState.split

  /* 받아 온 호가가 있으면 그것을 씁니다. **지어낸 사다리는 세우지 않습니다** —
     사용자가 그 가격을 눌러 주문가격에 넣습니다. 아직 축을 안 고른 옵션 자리도
     같습니다 — 거기는 종목이 없어 물을 호가가 없고, 카드가 틀만 남깁니다. */
  const book = useMemo(() => {
    if (shownUnasked || !shownAsked) return { asks: [], bids: [] }
    if (shownEntry.status === 'ready') return shownEntry.book ?? { asks: [], bids: [] }
    return { asks: [], bids: [] }
  }, [shownUnasked, shownAsked, shownEntry])
  /* 아직 축(행사가)을 안 고른 옵션 자리 — 종목이 없어 아무것도 안 물었습니다.
     호가·시세체결 카드가 이 값으로 틀만 남깁니다. */
  const axisPending = !shownUnasked && !shownAsked
  /* **이 카드에 서는 것은 실시간이 준 체결뿐입니다.** 지어낸 체결을 세우면,
     같은 카드가 실시간이 붙을 때는 진짜이고 안 붙을 때는 지어낸 값인데
     **화면에서 둘이 안 갈립니다.** 그러면 사용자는 지어낸 시각·가격을 최근
     체결로 읽습니다.
     안 부른 자리(해외·종목 미정)도 같습니다 — 거기는 아직 실시간을 걸지
     않아서 빈 채로 「시세가 연결되면 체결이 쌓입니다」가 섭니다. */
  const live = shownEntry.trades
  const ticks = live
  /* 매수·매도 버튼에 그 방향의 최우선 호가가 함께 섭니다. **한 단계도 없이 올 수
     있습니다** — 그 종목에 걸린 호가가 없으면 서버가 빈 배열을 냅니다. */
  const bestBid = book.bids.length > 0 ? book.bids[0].price : null
  const bestAsk = book.asks.length > 0 ? book.asks[book.asks.length - 1].price : null
  /* 주문 대상 종목의 시장. 다른 시장의 종목을 차트 칸에 올려 주문 대상으로 삼으면
     헤더의 장 표시·주문유형·만기 목록·포지션 목록이 그 시장을 따라야 합니다 —
     화면의 시장 범위는 「어디서 시작했는가」이고, 주문은 「지금 무엇을 보는가」입니다. */
  const activeContext = contextOf(subject)
  const activeOverseas = activeContext === 'overseas'
  /* 계좌 조회는 시장마다 다른 계좌입니다. 주문 대상 종목이 속한 쪽을 봅니다 —
     화면의 시장 범위가 아니라 「지금 무엇을 주문하는가」입니다. */
  const accountMarket: DepositMarket = activeOverseas ? 'overseas' : 'domestic'

  /* **주문·체결 목록과 미결제약정은 계좌 조회에서 옵니다.** 두 카드가 늘 서 있는
     화면이라 들어올 때 부릅니다. 계좌 화면의 미체결 탭과는 조회구분이 달라
     (여기는 전체, 거기는 미체결만) 담는 자리도 갈립니다. */
  const orderList = useListOnce<ServerOrder>(accountMarket, 'orders', 'all')
  /* **미결제약정은 계좌 전체입니다** — 인증 정보가 찬 시장 모두의 잔고를 한 표에
     둡니다. 해외 종목을 보다가도 국내 보유를 청산하러 갈 수 있어야 합니다. 시장마다
     계좌 화면과 같은 목록 저장소를 읽고, 인증 정보가 없는 시장은 부르지 않습니다
     (`withheld`). */
  const domesticPositions = useListOnce<ServerPosition>('domestic', 'positions')
  const overseasPositions = useListOnce<ServerPosition>('overseas', 'positions')
  /* 보고 있는 종목의 시장이 먼저입니다. 청산하러 오는 줄은 대개 지금 보는 쪽입니다. */
  const positionSides = (
    accountMarket === 'overseas'
      ? [
          { market: 'overseas' as const, entry: overseasPositions },
          { market: 'domestic' as const, entry: domesticPositions },
        ]
      : [
          { market: 'domestic' as const, entry: domesticPositions },
          { market: 'overseas' as const, entry: overseasPositions },
        ]
  ).filter((side) => !side.entry.withheld)
  const positionList = mergedPositionList(
    positionSides.map((side) => side.entry),
    accountMarket === 'overseas' ? overseasPositions : domesticPositions,
  )
  /* 한 시장의 사정을 **그 시장 이름으로** 말하는 줄들. 다른 시장 줄이 섰을 때만
     섭니다 — 표 전체를 「받지 못했습니다」로 덮으면 받은 줄까지 가리고, 표 전체의
     「지난 값」 문장은 새로 받은 시장의 줄까지 옛것으로 읽히게 합니다.
     `missing` 은 받은 적 없이 못 받은 시장, `stale` 은 받아 둔 줄은 있는데 새로
     받기에 실패한 시장입니다(받은 시장이 모두 그러면 표 전체 문장이 대신합니다). */
  const receivedSides = positionSides.filter((side) => side.entry.rows !== null)
  const allStale = receivedSides.every((side) => side.entry.failure !== null)
  const positionNotes =
    positionList.rows === null
      ? []
      : positionSides.flatMap((side): { side: (typeof positionSides)[number]; kind: 'missing' | 'stale' }[] => {
          if (side.entry.rows === null && side.entry.status === 'failed') {
            return [{ side, kind: 'missing' as const }]
          }
          if (side.entry.rows !== null && side.entry.failure !== null && !allStale) {
            return [{ side, kind: 'stale' as const }]
          }
          return []
        })

  /* **주문체결상세는 보고 있는 종목의 것만** 담습니다. 계좌 전체를 세우면 이
     카드가 무엇에 대한 카드인지 흐려집니다. 미결제약정은 반대로 계좌 전체입니다 —
     계좌 화면과 같은 목록을 봅니다. */
  const { orders, fills } = useMemo(() => {
    const open: OpenOrder[] = []
    const done: Fill[] = []
    for (const row of orderList.rows ?? []) {
      if (row.code !== shownQuote.code) continue
      const made = toTradeRow(row)
      if (made.kind === 'open') open.push(made.order)
      else done.push(made.fill)
    }
    return { orders: open, fills: done }
  }, [orderList.rows, shownQuote.code])

  const domesticRows = domesticPositions.rows
  const overseasRows = overseasPositions.rows
  const positions: Position[] = useMemo(() => {
    const domestic = (domesticRows ?? []).map((row) => toPosition(row, false))
    const overseas = (overseasRows ?? []).map((row) => toPosition(row, true))
    return activeOverseas ? [...overseas, ...domestic] : [...domestic, ...overseas]
  }, [domesticRows, overseasRows, activeOverseas])

  /* **자리가 모자라 실시간이 안 붙은 칸**은 값이 언제 것인지를 적습니다.
     「실시간 아님」처럼 없는 것의 이름을 붙이지 않습니다 — 사용자에게 필요한
     것은 이 값이 언제 것인가이고, 그것을 말하면 「안 바뀐다」는 저절로
     읽힙니다. 값이 아예 없는 칸에는 안 답니다 — 그때는 「없다」가 먼저입니다. */
  const stream = useStreamStatus()
  /* 이 종목이 속한 시장의 실시간. **국내와 해외는 따로 끊기고 따로 붙습니다** —
     다른 시장이 다시 붙는 동안에도 이 카드의 「언제부터」는 그대로여야 합니다. */
  const feedHere = stream.markets[activeContext === 'overseas' ? 'overseas' : 'domestic']
  const staleAt =
    priceKnown &&
    stream.rejected.includes(
      wishKey({ context: activeContext, kind: 'book', sym: shownQuote.code }),
    )
      ? shownEntry.at
      : ''
  /* 현재가 쪽은 호가와 **따로 밀립니다** — 자리는 구독 하나씩 세므로 한쪽만
     남을 수 있습니다. 그때 헤더의 값이 언제 것인지는 호가 카드가 대신 말해
     주지 못하므로, 그 줄에 제 시각을 답니다. */
  const quoteStaleAt =
    priceKnown &&
    stream.rejected.includes(
      wishKey({ context: activeContext, kind: 'quote', sym: shownQuote.code }),
    )
      ? shownEntry.at
      : ''

  /* 시세체결 카드 머리의 「언제부터」. 이 이름표가 참으로 만들어야 하는 문장은
     하나입니다 — **「이 카드는 그 시각부터의 체결을 담고 있다」.**

     그래서 담은 수가 상한(`TRADE_KEEP`)에 못 미치면 **실시간이 붙은 시각**입니다.
     그때는 붙은 뒤의 체결을 하나도 안 버렸습니다. 가장 오래된 줄을 쓰면
     「15:19부터 보고 있었는데 첫 체결은 15:21이었다」는 사실이 사라져, 세 줄만
     있을 때 「15:21부터 셋」으로 읽힙니다.

     상한까지 차면 앞쪽을 버린 뒤라 붙은 시각은 더 이상 참이 아닙니다. 그때는
     담고 있는 가장 오래된 체결의 시각입니다.

     **임시 체결값이 서는 자리는 그 목록의 가장 오래된 줄을 씁니다** — 실시간을
     안 건 자리라 붙은 시각이 그 값들과 아무 상관이 없고, 머리와 바로 아래 줄이
     어긋나 보입니다.

     체결 시각은 `HH:MM:SS` 로 오는데 분까지만 씁니다 — 카드가 말하는 것은
     구간의 시작이지 특정 체결이 아닙니다. */
  /* **지금 이 종목의 체결을 실제로 듣고 있는지.** 빈 카드에 「아직 체결이
     없습니다」를 세울 수 있는 것은 듣고 있을 때뿐입니다 — 안 듣는 동안 그
     문구가 서면 「그때부터 듣는데 아무것도 안 왔다」가 되는데, 사실은 안 듣고
     있어서 모르는 것입니다. 끊겼다는 것은 상단이 이미 말하므로 카드는 잠자코
     있으면 됩니다. */
  const listening =
    shownAsked &&
    feedHere.state === 'live' &&
    !stream.rejected.includes(
      wishKey({ context: activeContext, kind: 'quote', sym: shownQuote.code }),
    )

  const oldestTick = ticks.length > 0 ? ticks[ticks.length - 1].time.slice(0, 5) : ''
  const tapeSince =
    ticks.length === 0
      ? /* 담은 것이 없을 때 「그때부터」를 적을 수 있는 것은 **듣고 있을 때뿐**
           입니다. 안 듣는 중에는 그 시각이 「그때부터 듣는데 안 온다」로 읽혀,
           카드가 하지 않기로 한 말을 머리가 대신 하게 됩니다. */
        (listening ? feedHere.since : '')
      : live.length === 0
        ? /* 임시 값이 서는 자리 — 붙은 시각과 아무 상관이 없습니다. */
          oldestTick
        : live.length >= TRADE_KEEP
          ? /* 다 차서 앞을 버린 뒤라 붙은 시각은 더 이상 참이 아닙니다. */
            oldestTick
          : /* **둘 중 이른 쪽입니다.** 끊겼다 다시 붙으면 붙은 시각만 새로
               갱신되고 받아 둔 체결은 그대로 남아, **머리보다 오래된 줄이 그
               아래 서는** 일이 생깁니다. 이른 쪽을 적으면 「이 카드는 그
               시각부터의 체결을 담고 있다」가 되붙기 뒤에도 참입니다. */
            earlierClock(oldestTick, feedHere.since, kstMinutes(Date.now()))
  /* 주문체결상세 머리의 「언제부터」. 시세체결과 같은 문장을 참으로 만듭니다 —
     **「이 표는 그 시각부터의 접수·체결을 담고 있다」.** 표는 조회로 채우고 그 위에
     실시간 알림을 이어 붙입니다. 조회가 그 앞을 다 담아 오므로, 빠짐이 없는 구간의
     시작은 **알림을 듣기 시작한 시각**입니다. 시세체결과 달리 가장 이른 줄의 시각을
     견주지 않습니다 — 그 줄보다 앞도 조회가 채웠습니다.

     끊겼다 붙으면 목록을 다시 불러 빈 구간을 메우고(`data/stream.ts`) 그 시각이
     다시 섭니다 — 과정은 머리에 안 적습니다. **듣고 있을 때만** 섭니다 — 안 듣는
     동안 서면 「그때부터 듣는데 안 온다」로 읽힙니다. 끊겼다는 것은 상단이 이미
     말합니다. */
  /* 알림 구독은 앱이 겁니다. 국내는 주간 맥락 하나로 걸려 있어, 야간에도 그 열쇠로
     물립니다. */
  const ordersSince =
    feedHere.state === 'live' &&
    !stream.rejected.includes(
      wishKey({ context: activeContext === 'overseas' ? 'overseas' : 'domestic-day', kind: 'orders', sym: '' }),
    )
      ? feedHere.since
      : ''
  /* 헤더의 만기 목록은 **주문 대상 종목의 품목과 종류**에서 나옵니다 —
     코스닥150 옵션을 보고 있으면 코스닥150 옵션의 만기가 서야 합니다. 시장에서
     뽑으면 어느 종목을 보든 같은 목록이 서고, 종류를 안 주면 한 품목의 선물과
     옵션 만기가 한 목록에 섞여 보고 있는 것이 어느 줄인지 못 가릅니다. */
  const months = useMemo(
    () => (subject ? contractsOf(subject.product, subject.kind).map(expiryOption) : []),
    [subject],
  )

  /* 선물이냐 옵션이냐도 **주문 대상 종목**이 정합니다. 헤더의 이름·시세·만기가
     그 종목을 말하는데 여기만 화면의 첫 종목을 보면, 선물을 주문하는 화면에
     콜풋·행사가 컨트롤이 서고 그것을 돌려도 아무것도 안 바뀝니다. */
  const kind: ProductKind = subject?.kind ?? 'futures'

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

  /* 야간 답이면 야간 묶음 하나입니다 — 주간 묶음의 열이 통째로 빕니다. 고른 묶음
     번호는 그대로 두어 주간으로 돌아오면 보던 묶음이 다시 섭니다. */
  const presets = activeOverseas
    ? OVERSEAS_PRESETS
    : chain.session === 'night'
      ? NIGHT_PRESETS
      : DOMESTIC_PRESETS
  const activePreset = presets[Math.min(preset, presets.length - 1)]

  /* 종목이 바뀌면 다른 종목이라 주문 폼을 비웁니다. 만기를 바꾸든 체인에서
     다른 칸을 고르든 결과는 같으므로, 종목 코드 하나만 봅니다.

     **여기서 값(현재가)을 보지 않습니다.** 실시간이 붙은 뒤로 현재가는 한 틱마다
     바뀌는데, 그것을 보면 **틱마다 이 효과가 돌아 사용자가 치던 주문가격·수량과
     정정·청산 모드가 통째로 날아갑니다.** 지정가를 치는 동안 값이 한 번 뛰면 친
     것이 사라지는 셈입니다. 값이 처음 설 때 주문가격을 채우는 일은 아래 효과가
     따로 맡습니다 — 「종목이 바뀌면 비운다」와 「첫 값이 오면 한 번 채운다」는
     다른 일이고, 한 효과에 두면 뒤엣것 때문에 앞엣것이 계속 돕니다. */
  useEffect(() => {
    /* 청산·정정하러 종목을 옮긴 경우는 예외입니다. 방금 채운 값을 이 효과가
       곧바로 지우면, 누른 결과가 한 프레임 만에 사라집니다. 예외는 옮겨 간 그
       종목에만 쓰고, 그다음 종목이 오면 버립니다. */
    const keepFor = keepModeForRef.current
    keepModeForRef.current = null
    if (keepFor === shownQuote.code) {
      /* 그 경로가 이미 주문가격을 채웠으므로, 아래 효과가 덧칠하지 않게
         「채운 것으로」 표시합니다. */
      filledForRef.current = shownQuote.code
      return
    }
    setPrice(null)
    setStopPrice(null)
    setQuantity(1)
    setEditing(null)
    setClosing(null)
    releaseSystemSide()
    setOrderable(ORDERABLE_IDLE)
    /* 앞 종목에 물어본 답이 뒤늦게 오면 버립니다. 종목이 바뀐 뒤에 도착한
       계약 수가 새 종목의 값으로 서면, 화면이 묻지도 않은 답을 말합니다. */
    orderableAskRef.current += 1
    /* 새 종목이라 아직 안 채웠습니다. */
    filledForRef.current = null
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shownQuote.code])

  /* **물음이 바뀌면 앞 답을 내립니다.**
   *
   *  가능수량은 방향·주문유형·가격마다 답이 다릅니다. 매수로 물어 받은 수가
   *  매도로 바꾼 뒤에도 그대로 서 있으면, **화면이 지금 조건의 답인 척하는 옛
   *  답**을 말합니다. 낼 수량을 정하는 값이라 그대로 두면 안 됩니다.
   *
   *  **그 종목의 현재가는 여기 안 넣습니다.** 시장가로 물을 때는 지금 값을
   *  실어 보내므로 틱마다 답이 조금씩 달라지지만, 틱을 넣으면 실시간이 뛸
   *  때마다 답이 지워져 읽을 수가 없습니다. 값이 크게 움직였으면 다시 누르는
   *  것이 사용자가 할 수 있는 일이고, 그 단추는 답 바로 아래 있습니다. */
  useEffect(() => {
    setOrderable(ORDERABLE_IDLE)
    orderableAskRef.current += 1
  }, [side, orderType, price, stopPrice])

  /* **환경(모의·실전)이 바뀌면 다른 계좌라 주문 폼을 비웁니다.** 종목이 바뀔 때와
     같은 자리입니다 — 특히 정정·취소·청산 모드는 옛 계좌의 주문번호·포지션을 잡고
     있어, 남겨 두면 모의 주문번호로 실전에 정정이 나갑니다. 물어봐 둔 가능수량도
     옛 계좌의 수입니다. 처음 그릴 때는 돌지 않습니다 — 그때는 바뀐 것이 없습니다. */
  const generationRef = useRef(environment.generation)
  useEffect(() => {
    if (generationRef.current === environment.generation) return
    generationRef.current = environment.generation
    /* **열려 있던 확인창도 닫습니다.** 창은 바뀌기 전 계좌의 주문을 묻고 있어, 그대로
       「확인」을 누르면 다른 계좌로 나갑니다(보내는 자리도 한 번 더 막습니다 —
       `sendOrder`). 정정·취소·청산하던 주문을 접었으면 그 사실도 말하고, 손이 이미
       단추로 가 있을 수 있어 잠깐 단추를 멈춥니다. */
    const folded = editing ? (editing.mode === 'cancel' ? '취소' : '정정') : closing ? '청산' : null
    const open = confirming
    const where =
      environment.active === 'real' ? '실전으로 ' : environment.active === 'paper' ? '모의로 ' : ''
    if (open) {
      const word = open.show.closing
        ? '청산'
        : open.show.kind === 'cancel'
          ? '취소'
          : open.show.kind === 'modify'
            ? '정정'
            : open.show.side === 'buy'
              ? '매수'
              : '매도'
      noteTradeNotice({
        label: '확인창 닫음',
        text:
          `계좌가 ${where}바뀌어 ${word} 확인창을 닫았습니다 — 주문은 나가지 않았습니다` +
          (folded ? ` · ${folded}하던 주문도 접었습니다` : ''),
        urgent: true,
        mergeKey: 'trade|confirm-closed',
      })
    } else if (folded) {
      noteTradeNotice({
        label: '주문 접음',
        text: `계좌가 ${where}바뀌어 ${folded}하던 주문을 접었습니다`,
        urgent: false,
        mergeKey: 'trade|account-switch',
      })
    }
    if (open || folded) pauseSubmit()
    setConfirming(null)
    setPrice(null)
    setStopPrice(null)
    setQuantity(1)
    setEditing(null)
    setClosing(null)
    releaseSystemSide()
    setOrderable(ORDERABLE_IDLE)
    orderableAskRef.current += 1
    filledForRef.current = null
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [environment.generation])

  /* 그 종목의 값이 처음 서면 주문가격을 **한 번** 채웁니다.
     **그다음부터는 실시간이 값을 갈아 끼워도 안 채웁니다** — 사용자가 친 값을
     덮으면 안 되고, 덮으면 지정가를 칠 수가 없습니다.

     아직 종목이 아니면(콜풋·행사가 미정) 낼 가격도 없습니다. 기초 선물의
     현재가를 넣어 두면 옵션 프리미엄 자리에 수백 단위 값이 실려, 고르는 순간
     자릿수가 어긋난 지정가가 남습니다.

     **시세를 못 받아 값이 없는 종목도 같습니다.** 그때 화면에 남아 있는 숫자는
     이 종목의 값이 아니므로 주문가격에 실으면 안 됩니다 — 낼 값을 그 자리가
     지어내는 셈이 됩니다. */
  useEffect(() => {
    if (filledForRef.current === shownQuote.code) return
    if (needsLeg(shownQuote.code) || !priceKnown) return
    /* **받은 값일 때만 채웁니다.** 종목 색인이 아직 안 와서 자리만 채워 둔 값은
       이 종목의 값이 아닙니다 — 그대로 두면 주문가격 칸이 지어낸 숫자로 서고,
       그 칸은 화면에 보이는 데서 끝나지 않고 **그 값으로 주문이 나갑니다.** */
    if (!shownBuilt) return
    filledForRef.current = shownQuote.code
    /* 비어 있을 때만 채웁니다. 값이 늦게 서는 종목에서 사용자가 먼저 쳐 두는
       경우가 있고, 그때 채우면 친 값을 덮습니다. */
    setPrice((current) => (current === null ? shownQuote.last : current))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shownQuote.code, shownQuote.last, priceKnown, shownBuilt])

  /* **청산 가격을 잔고 줄 값으로 채운 동안만**, 그 종목의 첫 시세가 오면 한 번
     시세로 바꿉니다. 잔고 값은 조회한 때의 값이라 지금 값과 다를 수 있고, 화면을
     여는 순간 나간 조회가 곧 제 값을 가져옵니다. 바꾼 뒤로는 시세가 움직여도
     다시 안 바꿉니다 — 위의 「한 번만 채운다」와 같은 원칙입니다. 사용자가 칸을
     건드렸으면(`user`) 여기 오지 않습니다. */
  useEffect(() => {
    if (closePriceFrom !== 'position' || !closing) return
    if (shownQuote.code !== closing.code) return
    if (!priceKnown || !shownBuilt) return
    if (shownQuote.last === null || shownQuote.last === undefined) return
    setPrice(shownQuote.last)
    setClosePriceFrom('quote')
  }, [closePriceFrom, closing, shownQuote.code, shownQuote.last, priceKnown, shownBuilt])

  /* 청산 모드가 끝나면(그만두기·접수·종목이나 환경이 바뀜) 가격 출처도 걷습니다. */
  useEffect(() => {
    if (!closing) setClosePriceFrom(null)
  }, [closing])

  /* **청산을 누르면 그 종목의 주문가능수량을 한 번 스스로 묻습니다.** 청산가능이
     0 이면 폼이 그렇게 말합니다 — 보유가 있어도 서버가 청산으로 받지 않는 경우를
     내기 전에 알 수 있습니다. 묻는 것은 누를 때 한 번뿐이고, 그 뒤는 폼의 조회
     단추입니다.

     폼이 그 종목으로 옮겨 간 **뒤에** 묻습니다 — 옮기기 전의 폼 값(앞 종목·가격)으로
     물으면 다른 물음의 답입니다. 청산 가격을 잔고 줄 값으로 채운 동안은 첫 시세를
     기다립니다. 곧 가격이 시세로 바뀌고, 가격이 바뀌면 앞 답을 내리므로(위 효과)
     그 전에 물은 답은 곧바로 지워집니다. 시세를 못 받으면 잔고 값으로 묻습니다. */
  const closeCheckRef = useRef<Position | null>(null)
  useEffect(() => {
    const target = closeCheckRef.current
    if (!target || closing !== target) return
    if (shownQuote.code !== target.code) return
    if (closePriceFrom === 'position' && !shownFailure) return
    if (!environmentKnown || credentialsWhy !== undefined || !canAskOrderable(orderableAsk)) return
    closeCheckRef.current = null
    checkOrderable()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [closing, shownQuote.code, closePriceFrom, shownFailure, price, side, orderType, environmentKnown, credentialsWhy])

  /* 밖에서 종목을 고르고 들어온 경우(검색·최근 본·종목 화면).

     **들어오는 코드는 늘 주문 대상 칸으로 갑니다.** 어디서 골랐든 결과가 같아야
     하므로 화면 안에서 고를 때와 같은 길(`openCode`)을 지납니다 — 밖에서 온
     것만 첫째 칸에 넣으면, 2분할에서 둘째 칸이 주문 대상일 때 고른 종목이
     보지도 않는 칸에 들어가고 주문 폼은 옛 종목 그대로입니다. */
  useEffect(() => {
    if (!openedCode) return
    openCode(openedCode)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openedCode])

  /* 무엇을 하러 왔는지를 폼에 옮깁니다. 종목이 바뀌면 폼을 비우는 효과가
     먼저 도는데, 그 뒤에 이것이 다시 채웁니다 — 순서가 뒤집히면 채운 값이
     곧바로 지워집니다. */
  useEffect(() => {
    if (!openedIntent) return
    if (openedIntent.kind === 'close') {
      startClosing(openedIntent.position)
      return
    }
    const order = openedIntent.order
    /* 다른 종목의 주문을 정정하러 왔으면 **화면이 그 종목으로 옮겨 갑니다.**
       폼만 바뀌고 헤더·호가·차트가 그대로면 「주문 정정」 단추에 엉뚱한 종목
       이름이 붙습니다 — 다른 어긋남은 「보는 것이 틀리다」인데 이건 「내는 것이
       틀릴 수 있다」입니다. */
    if (!resolve(order.code)) {
      onOpenFailed(order.code)
      return
    }
    /* **수량을 모르는 주문은 못 고칩니다.** 서버가 그 칸을 안 준 줄이라, 폼을
       열면 몇 계약을 낼지 우리가 지어내게 됩니다. 목록 쪽에서 이미 단추를 안
       세우지만 되돌릴 수 없는 자리라 여기서 한 번 더 봅니다.

       가격은 비어 있어도 됩니다 — 시장가 주문은 주문가격이 없고, 그건 못 받은
       것이 아니라 그 주문에 없는 값입니다. */
    if (order.quantity === null) return
    keepModeForRef.current = order.code
    openCode(order.code)
    startEditing(
      {
        id: order.id,
        side: order.side,
        orderType: order.orderType,
        /* 미체결 탭에서 온 주문은 아직 일하는 중입니다 — 끝났거나 거절된
           주문은 그 탭에 서지 않습니다. */
        progress: 'working',
        price: order.price,
        stopPrice: order.stopPrice,
        quantity: order.quantity,
        filled: order.filled,
        source: order.source,
        editable: true,
      },
      'amend',
      order.market === 'overseas',
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openedIntent])

  /* 주문 대상의 시장이 바뀌면 주문유형·체결조건을 처음으로 돌립니다. 국내의
     조건부지정가는 해외에 없고 해외의 STOP 은 국내에 없어, 들고 넘어가면 없는
     유형이 골라진 채가 됩니다. 지정가는 양쪽에 다 있습니다. */
  useEffect(() => {
    /* 해외 정정·취소가 방금 원주문의 유형을 옮겨 둔 시장이면 그대로 둡니다. */
    const keep = keepTypeForRef.current
    keepTypeForRef.current = null
    if (keep === activeContext) return
    setOrderType('지정가')
    setCondition('FAS')
    setStopPrice(null)
  }, [activeContext])

  /* 종목을 이 화면으로 가져오는 단 하나의 길. 어디서 고르든(만기 드롭다운·
     청산·정정) 여기로 들어오고, 넘기는 것은 **코드 하나**입니다. 선물인지
     옵션인지, 어느 행사가인지는 코드가 말합니다.
     바꾸는 것은 「화면의 종목」이 아니라 **「주문 대상 칸의 종목」**입니다 —
     2분할에서 둘째 칸이 주문 대상인데 첫 칸을 바꾸면, 주문 폼은 새 종목이고
     헤더·호가·차트는 둘째 칸 그대로여서 내는 것과 보는 것이 갈립니다. */
  const openCode = (next: string) => {
    const item = resolve(next)
    /* 못 푸는 코드로는 화면을 옮기지 않고 이유를 말합니다. 그냥 옮기면 헤더가
       종목명과 만기 목록을 잃은 반쪽 화면이 서는데, 무엇이 잘못됐는지 알 수
       없다는 점에서 아무 일도 안 일어나는 것보다 나쁩니다. */
    if (!item) {
      onOpenFailed(next)
      return
    }
    if (secondIsSubject) {
      const ref = refFor(next)
      /* 못 푸는 코드면 칸을 비우지 않고 그대로 둡니다 — 고른 것이 안 열리는
         것보다 엉뚱한 칸이 비는 것이 나쁩니다. */
      if (ref) patchSlot(1, { instrument: ref })
    } else {
      setSelectedCode(next)
    }
    /* 고른 축은 **주문 대상 종목**에 딸린 것이라 그 종목이 바뀌면 새 코드에서
       다시 읽습니다. 옵션 코드면 콜/풋과 행사가가 그 안에 있고, 선물이나 아직
       행사가가 없는 코드면 비어 옵니다 — 어느 칸이 대상이든 같은 길입니다. */
    pickFromCode(item)
    if (item?.kind === 'option') setTab('체인')
    else if (tab === '체인') setTab('차트')
  }

  /* 차트 배지에서 종목을 골랐을 때. 둘째 칸은 제 종목만 바꿉니다 — 다만 그
     칸이 주문 대상이면 옵션의 축도 그 종목의 것으로 다시 읽습니다. */
  const pickInstrument = (slot: 0 | 1, item: InstrumentRef) => {
    if (slot === 1) {
      patchSlot(1, { instrument: item })
      if (secondIsSubject) pickFromCode(resolve(item.code))
      return
    }
    openCode(item.code)
  }

  /* 청산 대상 포지션. 정정·취소와 같은 폼을 쓰지만 하는 일이 달라 따로 둡니다 —
     정정은 낸 주문을 고치는 것이고 청산은 새 주문을 내는 것입니다. */
  const startClosing = (position: Position) => {
    /* 못 푸는 종목이면 폼도 건드리지 않습니다. 화면은 그대로 두고 폼만 청산으로
       바꾸면, 보고 있는 종목을 그 수량만큼 청산하겠다는 폼이 서서 **내는 것이
       틀립니다.** */
    if (!resolve(position.code)) {
      onOpenFailed(position.code)
      return
    }
    /* **수량을 모르면 청산할 수 없습니다.** 몇 계약을 덜어낼지 정할 수 없습니다. */
    if (position.quantity === null) return
    /* 사용자가 누른 것이라 지난 결과 줄을 걷습니다. */
    clearResult()
    /* 화면이 그 종목으로 옮겨 갑니다. 폼만 바뀌고 헤더·호가·차트가 그대로면
       무엇을 청산하는지와 화면이 보여주는 것이 어긋납니다. */
    keepModeForRef.current = position.code
    closeCheckRef.current = position
    openCode(position.code)

    setEditing(null)
    setClosing(position)
    /* 방향은 보유의 반대입니다. 들고 있는 것을 덜어내는 주문이라 고를 값이
       아니라 정해진 값입니다. */
    setSideBySystem(position.side === 'long' ? 'sell' : 'buy')
    setQuantity(position.quantity)
    /* 가격은 **받은 값만** 씁니다.
     *
     *  이 종목을 물어본 적이 있으면 그때 받은 현재가를 넣습니다 — 청산은 지금
     *  내는 주문이라 헤더·호가가 보여주는 값과 같아야 하고, 폼에만 다른 값이
     *  서면 어느 쪽으로 나가는 주문인지 알 수 없습니다.
     *
     *  물어본 적이 없으면 **잔고 줄이 실어 온 값**입니다. 조회한 시점의 값이라
     *  지금 값과 다를 수 있지만, 서버가 준 값입니다 — 화면을 여는 순간 그 종목의
     *  조회가 함께 나가므로 곧 헤더가 제 값을 말합니다.
     *
     *  **둘 다 없으면 비웁니다.** 빈 칸은 「고르세요」이고, 지어낸 값은 「이 값으로
     *  내세요」입니다. 주문 폼에서 둘의 차이는 되돌릴 수 없습니다. */
    const asked = quoteEntry(position.code).price
    setPrice(asked?.last ?? position.lastPrice)
    /* 잔고 줄 값으로 채웠으면 그렇다고 적어 둡니다 — 칸 아래 한 줄이 서고, 첫
       시세가 오면 한 번 바꿉니다. 둘 다 없어 비운 칸은 사용자가 채웁니다. */
    setClosePriceFrom(
      asked?.last != null ? 'quote' : position.lastPrice !== null ? 'position' : null,
    )
    setOrderable(ORDERABLE_IDLE)
  }

  const startEditing = (order: OpenOrder, mode: EditMode, overseas = activeOverseas) => {
    /* **수량을 모르는 주문은 못 고칩니다.** 목록이 이미 단추를 안 세우지만,
       주문을 내는 자리라 여기서 한 번 더 봅니다. */
    if (order.quantity === null) return
    /* 사용자가 누른 것이라 지난 결과 줄을 걷습니다 — 다른 주문을 다루러 온
       자리에 앞 주문의 답이 남아 있으면 그 답이 이 주문의 것으로 읽힙니다. */
    clearResult()
    setClosing(null)
    // 정정·취소는 모달이 아니라 주문 패널을 그 모드로 바꿉니다.
    // 정정은 대개 리프라이싱이라 호가를 보면서 가격을 고쳐야 하는데,
    // 모달을 띄우면 그 호가창이 가려집니다.
    setEditing({ order, mode })
    setSideBySystem(order.side)
    setPrice(order.price)
    setQuantity(order.quantity)
    /* **해외는 원주문의 주문유형과 스탑가격도 옮깁니다.** 해외 정정·취소는 원주문의
       유형과 값을 함께 실어야 서버가 받습니다. 줄의 낱말을 폼 낱말로 못 옮기면
       그 낱말 그대로 두고, 보내는 자리가 「알 수 없어 보내지 않았습니다」로
       멈춥니다 — 아는 유형으로 바꿔 두지 않습니다. 국내는 지금까지처럼 폼의
       유형을 그대로 둡니다. */
    if (overseas) {
      keepTypeForRef.current = 'overseas'
      setOrderType(overseasFormType(order.orderType) ?? order.orderType)
      setStopPrice(order.stopPrice ?? null)
    }
    /* 새 주문의 가능수량은 정정에서 쓸 수 없습니다. 이미 낸 수량이 잡혀 있어
       기준이 다릅니다 — 남겨 두면 다른 질문의 답을 읽게 됩니다. */
    setOrderable(ORDERABLE_IDLE)
  }

  /* 실행 단추를 눌렀습니다. **여기서 보내지 않습니다** — 되묻는 창을 걸어 두고,
     보내는 일은 그 창의 답을 받은 뒤입니다.

     창에 보이는 값은 **폼에 보이는 그대로**입니다. 여기서 다시 계산하면 폼과
     창이 다른 값을 말할 수 있고, 그러면 되묻는 뜻이 없습니다. */
  const askToSend = () => {
    const code = shownQuote.code
    if (!code || needsLeg(code)) return
    /* 창이 말하는 계좌를 요청에 함께 싣습니다. 계좌를 모르면 단추가 이미 잠겨
       있습니다(`environmentWhy`). */
    const opened = environment.active
    if (!opened) return
    const kind = editing ? (editing.mode === 'cancel' ? 'cancel' : 'modify') : 'new'
    const ask: OrderAsk = {
      kind,
      environment: opened,
      context: activeContext,
      code,
      side,
      quantity,
      orderType,
      condition,
      price,
      /* 스탑가격은 해외 STOP 에만 있습니다. 국내 요청에는 싣지 않습니다. */
      ...(activeOverseas ? { stopPrice } : {}),
      decimals: shownQuote.decimals,
      originalOrderNo: editing?.order.id,
    }
    setConfirming({
      ask,
      show: {
        kind,
        closing: closing !== null,
        side,
        name: shownQuote.name,
        quantity,
        orderType,
        price,
        /* 해외에는 체결조건이 없습니다 — 넘기면 가격 줄에 국내의 꼬리가 섭니다. */
        condition: activeOverseas ? undefined : condition,
        ...(activeOverseas ? { stopPrice } : {}),
        decimals: shownQuote.decimals,
        fraction: shownQuote.fraction,
        /* 스프레드면 두 다리의 만기. 종목 마스터가 실어 준 값이고, 종목 코드를
           잘라 짓지 않습니다. */
        legs: spreadLegsOf(code),
        /* 정정에서 **무엇이 바뀌는지**를 가리는 데 쓰는 원주문 값. */
        before: editing
          ? {
              quantity: editing.order.quantity,
              price: editing.order.price,
              ...(activeOverseas ? { stop: editing.order.stopPrice ?? null } : {}),
            }
          : undefined,
      },
    })
  }

  /* 창에서 실행을 눌렀습니다. **여기부터가 되돌릴 수 없는 자리입니다.** */
  const confirmSend = async () => {
    const held = confirming
    if (!held || sending) return
    setConfirming(null)
    setSending(true)
    setOrderResult(null)
    /* **국내는 보내는 순간의 세션으로 냅니다.** 창이 열려 있는 사이 주간이 끝나고
       야간이 열렸으면(또는 그 반대) 창을 연 때의 길로 나가면 안 됩니다. 다른 값은
       창이 보여 준 그대로입니다. */
    const ask =
      held.ask.context === 'overseas'
        ? held.ask
        : { ...held.ask, context: domesticContextOf(held.ask.code) }
    const result = await sendOrder(ask)
    setSending(false)
    setOrderResult(result)
    const market = held.ask.context === 'overseas' ? 'overseas' : 'domestic'
    if (result.kind !== 'accepted') {
      /* 접수 번호를 받은 뒤 거절된 것이면 계좌 기록에는 그 거절이 남아 있습니다.
         줄을 얹지 않고 목록을 다시 불러 계좌가 적은 그대로 보입니다. 모드는 그대로
         둡니다 — 접수 자리에서 바로 거절된 때와 같이, 무엇이 거부됐는지 보며 다음
         손을 정하게 합니다. */
      if (result.kind === 'rejected' && result.orderId) reloadAccountLists(market)
      return
    }

    /* 접수된 줄을 **조회를 기다리지 않고** 목록 맨 위에 얹습니다 — 접수 답이
       주문내역 줄과 한 벌 모양이라 같은 길로 들어갑니다. 뒤이어 오는 실시간
       알림과 재조회가 같은 `id` 로 그 줄을 덮습니다.
       **얹는 목록은 보낸 주문의 시장입니다** — 지금 화면의 시장이 아니라 요청이
       말한 시장이라, 답을 기다리는 사이 종목을 바꿔도 다른 계좌 목록에 얹히지
       않습니다. */
    noteAcceptedOrder(market, result.row)
    reloadAccountLists(market)
    /* 청산·정정·취소는 **접수되면 그 모드에서 나옵니다.** 한 주문에 하는 일이
       끝났는데 띠가 남아 있으면 다음 주문이 그 주문에 딸린 것으로 보입니다. */
    setEditing(null)
    setClosing(null)
    releaseSystemSide()
  }

  /* 결과 줄을 걷어내는 손. **시간이 아니라 사용자의 다음 조작입니다** — 값이나
     종목을 바꾸면 그 답은 지금 폼이 말하는 주문의 것이 아닙니다.
 
     **화면이 바꾼 값은 「다음 조작」이 아닙니다.** 접수되면 정정·취소·청산 모드에서
     빠져나오면서 방향이 사용자가 고른 값으로 되돌아가는데, 그것을 조작으로 세면
     방금 받은 「접수됨 · 주문번호」가 그 자리에서 사라집니다. 그래서 값이 바뀌는
     것을 지켜보지 않고, **사용자가 칸을 건드린 자리에서** 직접 걷어냅니다. */
  const clearResult = () => setOrderResult(null)
  /* 종목이 바뀌는 것은 사용자가 고른 것뿐입니다 — 화면이 스스로 종목을 바꾸지
     않습니다. 그래서 이것만 지켜봅니다. */
  useEffect(() => {
    setOrderResult(null)
  }, [shownQuote.code])

  /* 지금 조건으로 물어볼 것. 폼의 값이 바뀌면 이것도 함께 바뀌므로, 단추가
     눌리는지도 값이 바뀔 때마다 다시 섭니다. */
  const orderableAsk: OrderableAsk = {
    context: activeContext,
    code: shownQuote.code,
    side,
    orderType,
    price,
    stopPrice,
    /* **아는 값일 때만 넘깁니다.** `shownQuote` 는 시세를 못 받았을 때도 자리를
       채우는 값을 들고 있어서, 그대로 넘기면 시장가·STOP 시장가처럼 가격 칸을
       안 쓰는 유형에서 **받은 적 없는 값이 서버로 나갑니다.** 그러면 돌아온
       수는 그 값으로 계산된 것인데 화면에는 계좌가 답한 것처럼 섭니다.
       「가격을 아는가」는 주문유형이 아니라 시세가 답할 물음입니다. */
    last: priceKnown ? shownQuote.last : null,
    decimals: shownQuote.decimals,
  }

  const checkOrderable = () => {
    const ticket = orderableAskRef.current + 1
    orderableAskRef.current = ticket
    setOrderable({ status: 'loading' })
    void askOrderable(orderableAsk).then((next) => {
      /* 그 사이 다시 눌렀거나 종목이 바뀌었으면 이 답은 버립니다. */
      if (orderableAskRef.current !== ticket) return
      setOrderable(next)
    })
  }

  return (
    <div className="trade">
      <InstrumentHeader
        quote={shownQuote}
        context={activeContext}
        failure={shownFailure}
        onRetry={() => retryQuote(shownQuote.code)}
        onOpenSettings={onOpenSettings}
        /* 값을 못 세운 동안에는 불러오는 중이든 실패든 값 자리를 비웁니다 —
           다른 출처의 숫자가 이 종목의 값으로 읽히면 안 됩니다. **받는 중과
           못 받음은 얼굴이 달라야 합니다** — 앞은 기다리면 되고 뒤는 아닙니다.
           받는 중에는 「여기 값이 올 자리」를 옅은 블록으로 두고, 값이 안 올
           것이 정해진 뒤에는 그 블록을 걷습니다. */
        valuesHidden={!priceKnown}
        /* 축을 안 고른 옵션은 「아직 안 골랐다」이지 「받는 중」이 아닙니다 — 뼈대는
           곧 온다는 말이라 세우지 않고, 라벨만 남기고 값을 비웁니다. */
        valuesLoading={!priceKnown && shownFailure === null && !needsLeg(shownQuote.code)}
        since={quoteStaleAt}
        months={months}
        legsLine={legsLine}
        kind={kind}
        optionSide={pickedSide}
        strike={pickedStrike}
        strikes={strikes}
        strikeDecimals={strikeDecimals}
        onMonthChange={openCode}
        onOptionSideChange={(side) => setPickedSide(side)}
        onStrikeChange={(next) => setPickedStrike(next)}
        /* 화면 구성은 카드 하나에 대한 것이 아니라 화면 전체에 대한 것이라
           카드 머리 띠가 아니라 이 띠에 섭니다. */
        actions={
          <>
            {/* 되돌리는 길이 화면에서 바로 닿아야 합니다 — 모달을 열어야만
                되돌릴 수 있으면, 배치를 망친 사람은 그 모달을 여는 단추부터
                찾아야 합니다. 모달 안의 것과 같은 동작입니다.
                이미 기본이면 눌러도 아무 일이 없으므로 비활성 + 이유입니다 —
                치우면 그 자리가 배치마다 생겼다 없어져 눈이 흔들립니다. */}
            <button
              type="button"
              className="btn btn-quiet card-head-btn"
              aria-label="기본 배치로"
              data-tip={isDefaultLayout ? '이미 기본 배치입니다' : '기본 배치로'}
              aria-disabled={isDefaultLayout || undefined}
              onClick={() => !isDefaultLayout && storeLayout(DEFAULT_LAYOUT)}
            >
              ⟲
            </button>
            <button
              type="button"
              className="btn btn-quiet card-head-btn"
              aria-label="패널 편집"
              data-tip="패널 편집"
              aria-haspopup="dialog"
              onClick={() => setEditorOpen(true)}
            >
              ▦
            </button>
          </>
        }
      />

      {editorOpen && (
        <PanelEditor
          layout={layout}
          onChange={storeLayout}
          onClose={() => setEditorOpen(false)}
        />
      )}

      {/* 카드 여섯이 슬롯 넷에 서는 격자. 열: 왼쪽(남는 폭) · 경계 · 오른쪽
          첫째 · 경계 · 오른쪽 둘째. 행: 위(남는 높이) · 경계 · 왼쪽 아래.
          카드의 DOM 순서는 고정이고 grid-area 만 바뀝니다 — 자리를 바꿔도,
          한 자리 안에서 탭을 바꿔도 차트가 다시 만들어지지 않습니다. */}
      <div
        className="trade-split"
        ref={splitRef}
        style={gridStyle}
        /* 끄는 중이거나 키보드로 고르는 중. 둘 다 「지금 자리를 옮기고 있다」라
           받을 수 있는 자리 표시가 같이 걸립니다 — 한쪽만 걸면 키보드로 옮길
           때는 어디에 놓을 수 있는지가 안 보입니다. */
        data-dragging={dragging || pending ? 'true' : undefined}
      >
        {resizeHint && (
          <div
            className="resize-pill"
            data-floor={resizeHint.floor ? 'true' : undefined}
            style={{ left: resizeHint.x, top: resizeHint.y }}
          >
            {resizeHint.text}
          </div>
        )}
        {/* 지금 손에 들려 있는 카드. 놓으면 무슨 일이 일어나는지는 대상 카드가
            제 자리에서 말합니다. */}
        {dragging && (
          <div className="drag-chip" ref={placeChip} aria-hidden="true">
            {slotsUsed[dragging].map((key) => CARD_LABEL[key]).join(' · ')}
          </div>
        )}
        {
          <>
            {/* 경계는 나눌 것이 양쪽에 있을 때만 섭니다. 한쪽이 비면 아무것도
                안 나누는 손잡이가 되고, 끌면 빈 자리만 넓어집니다. */}
            {/* 열 경계 둘. **어느 열을 넓히는지는 열 순서가 정합니다** —
                넓은 열은 남는 폭을 다 쓰므로, 경계는 늘 옆에 있는 좁은 열의
                폭을 바꾸고 그만큼을 넓은 열이 내놓습니다. 넓은 열이 경계의
                왼쪽에 있으면 오른쪽으로 끌 때 좁은 열이 좁아지고, 오른쪽에
                있으면 반대입니다. */}
            {/* 잠긴 경계도 **자리는 지킵니다.** 치우면 확대를 오갈 때마다 열이
                옆으로 움직이고, 잠겼다는 것도 알 길이 없습니다 — 안 움직이는
                손잡이는 고장으로 읽히므로 커서와 설명으로 잠김을 말합니다. */}
            {colSplits.map((split) => (
              <div
                key={split.at}
                className={`col-resizer${split.locked ? ' is-locked' : ''}`}
                role="separator"
                aria-orientation="vertical"
                aria-label={`${split.label} 폭 조절`}
                aria-disabled={split.locked || undefined}
                title={split.locked ? '확대 중에는 차트 쪽 경계를 옮길 수 없습니다' : undefined}
                style={{ gridColumn: split.at === 0 ? 2 : 4, gridRow: 1 }}
                onPointerDown={split.locked ? undefined : startColumnResize(split.column, split.sign)}
              />
            ))}
            {/* 행 경계는 **열마다** 있습니다. 위아래로 갈리는 열이 둘이고
                그 경계가 서는 높이가 서로 달라(왼쪽은 차트 아래, 오른쪽 첫
                열은 호가 아래) 하나로는 둘을 못 나눕니다. */}
            {rowSplits.map((split) => (
              <div
                key={split.column}
                className="row-resizer"
                role="separator"
                aria-orientation="horizontal"
                aria-label={`${split.label} 위아래 칸 높이 조절`}
                style={{ gridColumn: split.gridColumn, gridRow: 1, ...split.edge }}
                onPointerDown={startRowResize(split.column)}
              />
            ))}
          </>
        }

        <section className="trade-card card-chart" aria-label={CARD_LABEL.chart} {...cardProps('chart')}>
          {/* 이 카드가 제 자리에 혼자 서면 탭 줄이 곧 이름입니다 — 「차트」
              이름 옆에 「차트」 탭을 세우면 같은 글자가 두 번 섭니다. 띠 왼쪽의
              식별 물체는 카드마다 정확히 하나이고, 모양이 알약이냐 글자냐만
              다릅니다. 확대 중에는 탭을 못 바꾸므로 그때는 이름 글자가 섭니다.
              다른 카드와 한 자리에 서면 띠는 **자리의 탭 줄**이 되고, 차트가
              무엇을 보여줄지 고르는 이 줄은 본문 첫 줄로 내려갑니다 — 한 띠에
              탭 줄이 둘이면 어느 것이 자리를 바꾸는지 알 수 없습니다. */}
          {cardHead(
            'chart',
            chartExpandButton,
            expandedChart ? undefined : chartTabStrip,
          )}

          <div className="trade-panel">
            {!expandedChart && chartTabsInBody && (
              <div className="panel-tabs">{chartTabStrip}</div>
            )}
            {/* 체인은 종목 화면에서 여기로 왔습니다. 행사가 축이 하나 더 있는
                것은 옵션만의 사정이라, 옵션을 주문하는 화면에 있어야 고른
                칸이 그대로 주문의 종목이 됩니다. */}
            {activeTab === '체인' && chain && optionProduct && (
              <div className="chain-panel">
                <div className="chain-controls">
                  {/* 고를 묶음이 하나(야간)면 고르개를 안 세웁니다. */}
                  {presets.length > 1 && (
                    <select
                      className="chain-select"
                      aria-label="열 묶음"
                      value={activePreset.id}
                      onChange={(event) =>
                        setPreset(presets.findIndex((item) => item.id === event.target.value))
                      }
                    >
                      {presets.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                  )}

                  {/* 이것은 주문 대상이 아니라 보기 설정입니다. 헤더의 [콜 ▾] 와
                      이름이 같으면 둘 중 하나가 고장 난 것으로 읽힙니다. */}
                  <div className="seg chain-view" role="group" aria-label="체인에 보일 쪽">
                    {(['both', 'call', 'put'] as ChainSide[]).map((item) => (
                      <button
                        key={item}
                        type="button"
                        className="seg-item"
                        aria-pressed={chainSide === item}
                        onClick={() => setChainSide(item)}
                      >
                        {item === 'both' ? '양쪽' : item === 'call' ? '콜만' : '풋만'}
                      </button>
                    ))}
                  </div>

                </div>

                <OptionChain
                  rows={chainRows}
                  preset={activePreset}
                  side={chainSide}
                  decimals={optionProduct.decimals ?? 2}
                  /* 첫 답이 오기 전에는 표가 없고 「받는 중」이 섭니다 — 행사가
                     축까지 서버가 줍니다. */
                  loaded={chain.rows !== null}
                  /* 무엇의 체인인지 — 이것이 바뀔 때만 등가격을 가운데로 엽니다. */
                  chainKey={chainArgs ? JSON.stringify(chainArgs) : ''}
                  failure={chain.failure}
                  onRetry={() => chainArgs && chainOwner && retryChain(chainArgs, chainOwner)}
                  night={chain.session === 'night'}
                  futuresPrice={futuresPrice}
                  atm={atm}
                  strikeDecimals={strikeDecimals}
                  /* 고른 줄은 **코드**로 견줍니다 — 적힌 글자로 견주면 자리 수에
                     맞춰 반올림된 두 행사가가 같은 줄로 보입니다. 고른 다리가 없을
                     때는 **이 화면의 종목코드**로 견줍니다: 종목코드로 열고 들어온
                     옵션은 축을 따로 고른 적이 없지만 표에 그 계약 줄이 있습니다. */
                  selectedCode={chainPickedCode}
                  onSelect={pickFromChain}
                  onOpen={pickFromChain}
                />
              </div>
            )}

            {activeTab === '차트' && (
              <ChartPanel
                /* 첫째 칸은 이 화면의 종목, 둘째 칸은 그 칸이 든 종목입니다.
                   주문 대상이 어느 쪽인지는 `active` 가 말하고, 헤더·호가·폼은
                   위에서 같은 기준으로 고른 `shownQuote` 를 봅니다. */
                quotes={[quote, secondSelected ? secondQuote : null]}
                slots={splitState.slots}
                onSlotChange={patchSlot}
                expanded={chartExpanded}
                onExpandedChange={setChartExpanded}
                split={splitState.split}
                onSplitChange={(split) => {
                  /* 처음 켤 때 둘째 칸은 이 종목의 차월물로 시작합니다. */
                  const slots: [SlotState, SlotState] = [splitState.slots[0], splitState.slots[1]]
                  if (split && !slots[1].instrument) {
                    slots[1] = { ...slots[1], instrument: nextMonthOf(subject) }
                  }
                  setSplitState({ ...splitState, split, slots })
                }}
                active={splitState.active}
                onActiveChange={(active) => {
                  setSplitState({ ...splitState, active })
                  /* 주문 대상이 다른 칸으로 옮겨 갔습니다. 옵션의 축은 대상
                     종목에 딸린 것이라 그 칸의 코드에서 다시 읽습니다 — 안 그러면
                     이 칸의 종목 위에 저 칸에서 고른 행사가가 서게 됩니다. */
                  const code = active === 1 ? secondCode : selectedCode
                  pickFromCode(code ? resolve(code) : null)
                }}
                onPickInstrument={pickInstrument}
              />
            )}
            {/* 정산·장운영은 품목의 성질이라 품목정보 안으로 들어왔습니다.
                탭을 셋에서 둘로 줄이면서 자리를 옮긴 것이지 뺀 것이 아닙니다. */}
            {activeTab === '품목정보' && (
              <>
                <ProductInfoPanel quote={shownQuote} context={activeContext} />
                <MarketDataPanel quote={shownQuote} context={activeContext} priceKnown={priceKnown} />
              </>
            )}
          </div>
        </section>

        {/* 체인을 보는 동안에는 하단이 머리 띠만 남고 접힙니다.
            체인 탭에 있다는 것은 「어느 행사가로 갈지 고르는 중」이라는
            뜻이고, 그때 아래 칸의 표는 볼 일이 아닙니다. 몇 건 있는지는 탭
            옆 숫자가 대신 말합니다 — 머리와 한 행만 남기면 그 한 건이
            내가 찾는 건지 알 수 없어 결국 펼치게 됩니다. */}
        {(['orders', 'positions'] as const).map((card) => (
          <section
            key={card}
            className={`trade-card card-orders${expandedChart ? ' is-hidden' : ''}`}
            aria-label={CARD_LABEL[card]}
            data-collapsed={collapsedFor(card) ? 'true' : undefined}
            {...cardProps(card)}
          >
            {cardHead(card, bottomHeadActions(card))}

            {!collapsedFor(card) && !expandedChart && (
              <div className="trade-bottom-wrap">
                <OrdersAndFills
                  onClose={startClosing}
                  /* 표의 종목·소수 자릿수는 주문 대상 종목을 따릅니다. 목록 자체가
                     그 종목의 것이라, 화면의 첫째 차트 종목을 적으면 둘째 칸을
                     주문 대상으로 둔 동안 이름과 내용이 어긋납니다. */
                  quote={shownQuote}
                  /* 값 칸 폭을 잡을 무리를 고르는 데 씁니다. 종목이 제 시장을
                     들고 오지 않는 경우가 있어 화면이 보고 있는 시장을 줍니다. */
                  context={context}
                  orders={orders}
                  fills={fills}
                  positions={positions}
                  /* 카드마다 제 조회를 봅니다 — 하나가 못 왔다고 다른 카드가
                     못 받은 얼굴을 하면 안 됩니다. */
                  list={card === 'orders' ? orderList : positionList}
                  onRetry={() => {
                    if (card === 'orders') retryList(accountMarket, 'orders', 'all')
                    else for (const side of positionSides) retryList(side.market, 'positions')
                  }}
                  positionNotes={positionNotes.map(({ side, kind }) => ({
                    market: side.market,
                    kind,
                    /* 표에 줄이 선 다른 시장. 「아래는 … 줄뿐」이 이것을 말합니다. */
                    shown: receivedSides.filter((other) => other.market !== side.market).map((other) => other.market),
                    retry: side.entry.failure === 'retry' ? () => retryList(side.market, 'positions') : undefined,
                  }))}
                  mode={card === 'orders' ? '주문체결상세' : '미결제약정'}
                  onEdit={startEditing}
                />
              </div>
            )}
          </section>
        ))}

        <section className="trade-card card-book" aria-label={CARD_LABEL.book} {...cardProps('book')}>
          {/* 자리에 혼자 서면 이름 글자가 식별 물체입니다. 손잡이 `aria-label` 이
              읽는 이름과 같은 글자를 씁니다 — 눈으로 보는 이름과 소리로 듣는
              이름이 다르면 같은 카드를 가리키는지 알 수 없습니다. */}
          {cardHead('book', staleAt && <span className="card-since">{staleAt} 기준</span>)}
          <OrderBook
            quote={shownQuote}
            asks={book.asks}
            bids={book.bids}
            failure={bookFailure}
            onRetry={() => retryQuote(shownQuote.code)}
            priceKnown={priceKnown}
            pending={axisPending}
            expectedPrice={shownEntry.expectedPrice}
            selectedPrice={price}
            subject={subjectShown}
            /* 호가 사다리를 눌러 가격을 넣는 것도 사용자가 값을 고친 것입니다 —
               폼의 가격 칸을 치는 것과 같은 자리라 결과 줄도 같이 걷습니다. */
            onPickPrice={(next) => {
              clearResult()
              touchPrice()
              setPrice(next)
            }}
          />
        </section>

        <section className="trade-card card-ticks" aria-label={CARD_LABEL.ticks} {...cardProps('ticks')}>
          {/* 「언제부터」는 이름 옆에 답니다. 체결은 연결한 뒤부터 쌓이므로 그
              시각이 함께 서야 빈 목록이 「고장」이 아니라 「그때부터 아직 없음」
              으로 읽히고, 몇 줄만 있을 때도 「오늘 이만큼 거래됐다」로 안 읽힙니다.
              무엇이 그 시각이 되는지는 위 `tapeSince` 에 적혀 있습니다. */}
          {cardHead('ticks', tapeSince && <span className="card-note">{tapeSince} 부터</span>)}
          <TickTape
            quote={shownQuote}
            ticks={ticks}
            listening={listening}
            unasked={shownUnasked}
            pending={axisPending}
          />
        </section>

        <section className="trade-card card-form" aria-label={CARD_LABEL.form} {...cardProps('form')}>
          {cardHead('form')}
          <OrderForm
            quote={shownQuote}
            subject={subjectShown}
            context={activeContext}
            kind={kind}
            side={side}
            orderType={orderType}
            condition={condition}
            price={price}
            stopPrice={stopPrice}
            quantity={quantity}
            bestBid={bestBid}
            bestAsk={bestAsk}
            orderBlocked={orderBlocked}
            submitPaused={submitPaused}
            credentialsWhy={credentialsWhy}
            environmentWhy={environmentWhy}
            sessionWhy={sessionWhy}
            onRetrySession={
              sessionHeld.status === 'failed' && sessionCode
                ? () => void loadSession('domestic', sessionCode)
                : undefined
            }
            /* 헤더가 그 자리에서 쓰는 말과 같아야 합니다. 아직 받는 중이면
               못 받은 것이 아니므로 그렇게 적지 않습니다. */
            /* **겹치면 사용자가 지금 할 수 있는 일이 먼저 섭니다.** 축을 아직
               안 골랐는데 시장도 조회 전이면 둘이 겹치는데, 고르는 것은
               사용자가 지금 할 수 있는 일이고(바로 위 셀렉터) 조회는 아닙니다.
               할 수 있는 것이 없을 때 우리 사정이 섭니다. */
            priceWhy={
              shownFailure?.kind === 'unasked'
                ? '조회 전이라 주문을 낼 수 없습니다'
                : shownFailure?.kind === 'empty'
                  ? '아직 시세가 없습니다'
                  : shownFailure?.kind === 'paper'
                    ? PAPER_NIGHT_PRICE_TEXT
                    : shownFailure
                      ? shownFailure.text || '시세를 받지 못했습니다'
                      : '시세를 받는 중입니다'
            }
            editing={editing}
            orderable={orderable}
            canCheckOrderable={
              environmentKnown && credentialsWhy === undefined && canAskOrderable(orderableAsk)
            }
            closing={closing}
            closePriceNote={closePriceFrom === 'position'}
            /* 값을 건드리는 길은 전부 결과 줄을 먼저 걷어냅니다 — 지난 주문의
               답이 지금 고치는 값 아래 남아 있으면 그 값으로 낸 것처럼 읽힙니다. */
            onSideChange={(next) => {
              clearResult()
              chooseSide(next)
            }}
            onOrderTypeChange={(next) => {
              clearResult()
              setOrderType(next)
              /* 시장가는 FAS 만 받습니다 — 남은 FOK·FAK 는 서버가 거부합니다. */
              setCondition((current) => fillCondFor(next, current))
            }}
            onConditionChange={(next) => {
              clearResult()
              setCondition(next)
            }}
            onPriceChange={(next) => {
              clearResult()
              touchPrice()
              setPrice(next)
            }}
            onStopPriceChange={(next) => {
              clearResult()
              setStopPrice(next)
            }}
            onQuantityChange={(next) => {
              clearResult()
              setQuantity(next)
            }}
            onCheckOrderable={checkOrderable}
            onCancelEditing={() => {
              setEditing(null)
              setClosing(null)
              releaseSystemSide()
            }}
            sending={sending}
            result={orderResult}
            onSubmit={askToSend}
            /* 결과를 모를 때 갈 곳. 그 카드를 열고 목록을 다시 부릅니다 —
               무엇이 나갔는지는 거기서만 알 수 있습니다. */
            onOpenOrders={() => {
              const slot = slotOfCard('orders')
              if (slot !== null) {
                setSlotTabs((current) => ({ ...current, [slot]: 'orders' }))
                if (slot === 'lb') setBottomOpen(true)
              }
              /* 결과 줄은 종목이 바뀌면 걷히므로, 이 단추가 설 때의 시장이 곧
                 보낸 주문의 시장입니다. */
              reloadAccountLists(accountMarket)
            }}
          />
        </section>
      </div>

      {/* 되돌릴 수 없는 한 걸음 앞에 한 번 되묻습니다. 창이 떠 있는 동안
          바깥은 안 눌리고, 그만두면 아무 일도 일어나지 않습니다. */}
      {confirming && (
        <OrderConfirm
          ask={confirming.show}
          onConfirm={() => void confirmSend()}
          onCancel={() => setConfirming(null)}
        />
      )}
    </div>
  )
}
