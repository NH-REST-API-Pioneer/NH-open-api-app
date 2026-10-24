import { useEffect, useRef, useState } from 'react'
import type { MarketContext, OpenOrder, Position, Quote } from '../../lib/types'
import { sendOrder, type OrderAsk, type OrderResult } from '../../data/orders'
import { noteTradeNotice } from '../../data/alerts'
import { noteAcceptedOrder, reloadAccountLists } from '../../data/account'
import type { OrderConfirmAsk } from './OrderConfirm'
import {
  ORDERABLE_IDLE,
  askOrderable,
  canAskOrderable,
  overseasFormType,
  type OrderableAsk,
  type OrderableState,
} from '../../data/orderable'
import { needsLeg, resolve } from '../../data/instruments'
import type { EditMode, OrderEdit, Side } from './OrderForm'
import { quoteEntry } from '../../data/quotes'
import { domesticContextOf } from '../../data/session'
import type { EnvironmentState } from '../../data/environment'
import type { useTradeQuotes } from './useTradeQuotes'
import { SUBMIT_PAUSE_MS, spreadLegsOf } from './tradeScreenUtils'

/** 주문 폼의 값과 모드(새 주문·정정·취소·청산), 확인창, 보내기와 그 결과, 주문가능수량. */
export function useOrderTicket({
  shownQuote,
  priceKnown,
  shownBuilt,
  shownFailure,
  environment,
  environmentKnown,
  credentialsWhy,
  activeContext,
  activeOverseas,
  onOpenFailed,
  openCode,
}: {
  shownQuote: Quote
  priceKnown: boolean
  shownBuilt: boolean
  shownFailure: ReturnType<typeof useTradeQuotes>['shownFailure']
  environment: EnvironmentState
  environmentKnown: boolean
  credentialsWhy: string | undefined
  activeContext: MarketContext
  activeOverseas: boolean
  onOpenFailed: (code: string) => void
  openCode: (next: string) => void
}) {
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

  return {
    side,
    chooseSide,
    releaseSystemSide,
    orderType,
    setOrderType,
    condition,
    setCondition,
    price,
    setPrice,
    stopPrice,
    setStopPrice,
    quantity,
    setQuantity,
    editing,
    setEditing,
    closing,
    setClosing,
    closePriceFrom,
    touchPrice,
    confirming,
    setConfirming,
    submitPaused,
    sending,
    orderResult,
    orderable,
    keepModeForRef,
    keepTypeForRef,
    startClosing,
    startEditing,
    askToSend,
    confirmSend,
    clearResult,
    orderableAsk,
    checkOrderable,
  }
}
