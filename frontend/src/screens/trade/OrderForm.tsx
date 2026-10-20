import { useEffect, useState } from 'react'
import type { MarketContext, OpenOrder, Position, ProductKind, Quote } from '../../lib/types'
import { PENDING_TEXT, needsLeg } from '../../data/instruments'
import type { OrderableState } from '../../data/orderable'
import type { OrderResult } from '../../data/orders'
import { useProductInfo } from '../../data/productInfo'
import { PriceField } from './OrderFormPriceField'
import { MarginLine } from './OrderFormMargin'
import { OrderResultLine } from './OrderFormResult'
import {
  renderOrderSubject,
  renderOrderEditing,
  renderOrderClosing,
  renderOrderSide,
  renderOrderLocked,
} from './OrderFormHead'
import { renderOrderTypeField, renderOrderCondition, renderOrderable } from './OrderFormFields'

/* 주문 폼.
 *
 * 매수와 매도가 대등하므로 세그먼트가 최상단 첫 컨트롤이고, 고른 쪽만 그
 * 방향색으로 채워집니다. 실행 버튼도 같은 색이라 한 묶음으로 읽힙니다.
 *
 * 라벨은 입력 위가 아니라 왼쪽 열에 둡니다. 위에 쌓으면 행마다 라벨 높이가
 * 더해져 폼이 길어집니다. 이 카드에서는 세로 길이가 곧 안전입니다.
 *
 * 실행 버튼은 가능수량 조회 바로 아래에 붙습니다. 창이 낮아 폼이 다 안
 * 들어가면 입력 칸만 스크롤하고, 방향 세그먼트와 실행 버튼은 스크롤 밖에
 * 두어 어느 창 크기에서도 보이게 합니다.
 *
 * 폼 자체가 시장마다 다릅니다. 국내는 체결조건이 붙고 스탑가격이 없으며,
 * 해외는 스탑가격이 붙고 체결조건이 없습니다.
 *
 * 새 주문 · 정정 · 취소 세 가지 일을 한 카드가 합니다. 정정과 취소는 이미
 * 낸 주문을 건드리는 것이라 카드 전체가 초록으로 물듭니다 — 폼 어딘가에
 * 작은 배지 하나로 알리면, 새 주문을 내는 줄 알고 수량을 고치는 일이 납니다.
 */

export type Side = 'buy' | 'sell'

/** 낸 주문에 하는 일. 새 주문이면 없습니다. */
export type EditMode = 'amend' | 'cancel'

/** 정정·취소 대상. 어느 주문에 무엇을 하는지가 늘 붙어 다닙니다. */
export interface OrderEdit {
  order: OpenOrder
  mode: EditMode
}

/** 국내 주문유형. 스탑가격이 없습니다. */
const DOMESTIC_TYPES = ['지정가', '시장가', '조건부지정가', '최유리지정가']
/** 해외 주문유형. 뒤 둘은 스탑가격을 함께 받습니다. */
const OVERSEAS_TYPES = ['시장가', '지정가', 'STOP-M', 'STOP-L']

/** 호가단위를 모를 때 화살표가 움직이는 폭. **그 종목의 눈금이 아닙니다** —
 *  모르는 채로 멈춰 세우면 값을 아예 못 넣으므로 움직이게 두고, 대신 칸 밑에
 *  그 사실을 적습니다. */
const DEFAULT_STEP = 0.05

interface Props {
  quote: Quote
  context: MarketContext
  /** 선물·옵션·스프레드. 국내 스프레드는 스프레드 종목 자체의 매수·매도로 나가고,
   *  **해외 스프레드는 아직 낼 수 없어** 폼이 이 값으로 막습니다. */
  kind: ProductKind
  /* 청산할 포지션. 있으면 폼이 청산 모드입니다 — 새 주문이지만 값이 이미
     정해져 있습니다. 방향은 반대, 수량은 들고 있는 만큼, 가격은 현재가입니다. */
  closing?: Position | null
  /** 청산 가격을 잔고 조회 때 값으로 채운 동안 참입니다. 가격 칸 아래 한 줄이 섭니다. */
  closePriceNote?: boolean
  side: Side
  orderType: string
  condition: string
  price: number | null
  stopPrice: number | null
  quantity: number
  /** 최우선 매수호가 — 매수 버튼에 붙습니다. **걸린 호가가 없으면 `null`**
   *  입니다. 거래가 뜸한 종목에서는 한 단계도 안 서는 때가 있습니다. */
  bestBid: number | null
  /** 최우선 매도호가 — 매도 버튼에 붙습니다. 없으면 `null` 입니다. */
  bestAsk: number | null
  /** 시세를 몰라 주문을 막아야 하는지. **못 받았거나 아직 받는 중이면** 낼 값을
   *  지어낼 수 없어 가격 칸을 잠그고 실행도 막습니다 — 값이 안 든 채로 나가는
   *  주문이 이 화면에서 가장 나쁜 일입니다.
   *
   *  **아직 거래가 없는 종목은 막지 않습니다.** 그건 화면이 아는 사실이고,
   *  상장되어 호가가 서 있으면 첫 거래를 만드는 것이 지정가 주문입니다. */
  orderBlocked?: boolean
  /** 값을 모르는 까닭. 헤더가 그 자리에서 쓰는 말과 같아야 합니다 — 한 화면에서
   *  같은 사실을 두 낱말로 부르면 다른 일이 일어난 것으로 읽힙니다. */
  priceWhy?: string
  /** 그 시장의 인증 정보가 없어 못 내는 까닭. **모든 까닭 가운데 맨 앞**입니다 —
   *  설정에서 넣기 전에는 다른 무엇을 고쳐도 낼 수 없습니다. */
  credentialsWhy?: string
  /** 모의인지 실전인지 몰라 못 내는 까닭. 있으면 인증 정보 다음, **다른 어떤 까닭보다
   *  앞에** 섭니다 — 행사가를 고르고 값을 고쳐도 이것이 풀리지 않으면 낼 수 없어서,
   *  앞의 둘을 먼저 말하면 사용자가 할 수 있는 일이 없는 것을 시키는 셈입니다. */
  environmentWhy?: string
  /** 국내 종목의 주간·야간을 몰라 못 내는 까닭. 환경 다음, 행사가 앞에 섭니다. */
  sessionWhy?: string
  /** 세션을 못 받았을 때 다시 묻는 손. 있을 때만 사유 줄 곁에 「다시」가 섭니다. */
  onRetrySession?: () => void
  /** 정정·취소 모드면 폼이 그 주문을 다루는 자리로 바뀝니다. */
  editing: OrderEdit | null
  /** 조회해서 받아온 주문가능수량과 그 자리의 상태.
   *
   *  **누르기 전에는 값 자리에 아무것도 안 섭니다.** 어느 시장이든 마찬가지라,
   *  한쪽에만 표지를 세우면 덜 아는 쪽이 더 많이 말하는 화면이 됩니다. */
  orderable: OrderableState
  /** 지금 물어볼 수 있는지. **가격을 모르면 못 물어봅니다** — 두 시장 모두
   *  주문가격이 있어야 답이 나오고, 시장가로 물을 때는 그 종목의 지금 값을
   *  대신 싣습니다. 그 값마저 없으면 부를 곳이 없어 단추가 안 눌립니다. */
  canCheckOrderable?: boolean
  /** 두 차트 중 이 폼이 어느 종목인지를 머리에 크게 답니다. 한 차트면 안 답니다. */
  subject?: boolean
  /** 보낸 주문의 답이 오기를 기다리는 중인지. **단추를 잠그고 폼도 잠급니다** —
   *  답을 기다리는 동안 값을 고치면, 무슨 값으로 나갔는지 화면이 말할 수 없게
   *  됩니다. */
  sending?: boolean
  /** 마지막으로 보낸 주문의 답. **시간으로 사라지지 않습니다** — 사용자의 다음
   *  손(값·종목 바꿈·다시 보내기)이 걷어냅니다. */
  result?: OrderResult | null
  onSideChange: (side: Side) => void
  onOrderTypeChange: (type: string) => void
  onConditionChange: (condition: string) => void
  onPriceChange: (price: number | null) => void
  onStopPriceChange: (price: number | null) => void
  onQuantityChange: (quantity: number) => void
  onCheckOrderable: () => void
  onCancelEditing: () => void
  /** 계좌가 바뀌어 주문을 접은 직후라 실행 단추를 잠깐 멈춰 둡니다. 누르면 아무 일도
   *  없고, 시간이 지나면 저절로 풀립니다. */
  submitPaused?: boolean
  /** 실행 단추를 눌렀습니다. **여기서 보내지 않습니다** — 되묻는 창이 먼저
   *  뜨고, 보내는 일은 그 창의 답을 받은 쪽이 합니다. */
  onSubmit: () => void
  /** 결과를 모를 때 주문체결상세로 가는 길. 그 자리에서 다시 조회합니다. */
  onOpenOrders: () => void
}

export function OrderForm({
  quote,
  context,
  kind,
  side,
  orderType,
  condition,
  price,
  stopPrice,
  quantity,
  bestBid,
  bestAsk,
  orderBlocked = false,
  priceWhy = '시세를 받지 못했습니다',
  credentialsWhy,
  environmentWhy,
  sessionWhy,
  onRetrySession,
  closing,
  closePriceNote = false,
  editing,
  orderable,
  canCheckOrderable = true,
  subject = false,
  sending = false,
  result = null,
  onSideChange,
  onOrderTypeChange,
  onConditionChange,
  onPriceChange,
  onStopPriceChange,
  onQuantityChange,
  onCheckOrderable,
  onCancelEditing,
  submitPaused = false,
  onSubmit,
  onOpenOrders,
}: Props) {
  const overseas = context === 'overseas'

  /* 국내 호가단위를 담아 둔 자리. **해외는 안 묻습니다** — 마스터가 종목마다
     주므로 이 자리가 비어 있어도 눈금은 이미 있습니다.

     **그래서 해외에서는 아래 안내가 서지 않습니다.** 마스터가 품목마다
     호가단위를 주는 것을 전제로 선 조건입니다 — 안 주는 품목이 나오면 그
     종목은 눈금 없이 조용히 움직이게 되므로, 그때 이 자리를 고칩니다. */
  const tick = useProductInfo(overseas ? '' : quote.code)

  /* **「아직 안 왔다」에는 아무 말도 안 합니다.** 종목을 고를 때마다 답이 오기
     전 한 박자가 있는데, 그 사이에 「못 받았다」를 세우면 곧 값이 설 자리에서
     화면이 거짓을 말합니다. 답이 왔는데 값이 없거나(`ready`) 못 받은
     때(`failed`)만 섭니다.

     **눈금을 모르는 채로 멈춰 세우지는 않습니다.** 화살표는 그대로 움직이되
     그 폭이 거래소 눈금이 아니라는 것을 적습니다 — 말이 없으면 사용자가 그
     폭을 그 종목의 눈금으로 읽습니다. 왜 못 받았는지는 서버가 낸 문장을
     그대로 답니다. */
  const tickMissing =
    quote.code !== '' &&
    quote.tickSize == null &&
    (tick.status === 'ready' || tick.status === 'failed')
  /* 한 줄에 들어야 합니다 — 쓸 수 있는 폭이 164px 이고, 「호가단위를 못
     받았습니다 · 0.05 씩」은 170 이라 낱말 하나가 다음 줄로 넘어갑니다.

     **눈금을 모르는 동안에는 값을 거절하지 않습니다.** 값 읽기가 눈금을 받았을
     때만 격자를 보므로(`readPrice`), 이 줄이 선 종목에서는 아무 값이나 통과
     합니다 — 모르는 눈금으로 사용자의 값을 막으면, 맞는 값을 틀렸다고 말하게
     됩니다. */
  const tickNote = tickMissing ? `호가단위 못 받음 · ${DEFAULT_STEP} 씩` : null
  const tickWhy = tickMissing ? (tick.row?.why ?? '') || null : null
  /* 스프레드는 스프레드 종목 하나를 매수·매도합니다. 매수·매도가 두 다리에 어떻게
     걸리는지는 서버 답에 없어, **화면이 다리별 방향을 문장으로 적지 않습니다.**
     증거금 어림과 가능수량 조회도 두 다리의 셈을 몰라 세우지 않습니다. */
  const spread = kind === 'spread'
  /* 해외 스프레드는 아직 붙는 길이 없습니다. */
  const overseasSpread = overseas && spread
  const types = overseas ? OVERSEAS_TYPES : DOMESTIC_TYPES
  /* 정정·취소로 옮겨 온 원주문의 유형이 목록에 없는 낱말이면 그 낱말 그대로 한
     줄 더 둡니다. 목록 첫 줄이 대신 보이면 폼이 원주문과 다른 유형을 말합니다. */
  const typeOptions = types.includes(orderType) ? types : [...types, orderType]
  /* 값을 정하지 않고 나가는 유형. **최유리지정가도 여기입니다** — 명세가 주문가격을
     `0` 으로 실으라고 하므로, 칸을 열어 두면 받아 놓고 안 쓰는 값이 생깁니다. */
  const needsPrice = orderType !== '시장가' && orderType !== '최유리지정가' && orderType !== 'STOP-M'
  const needsStop = overseas && orderType.startsWith('STOP')
  const d = quote.decimals

  /* 취소는 낸 그대로를 물러 달라는 것이라 고칠 값이 없습니다.
     칸을 열어 두면 고친 값이 반영되는 것처럼 보입니다. */
  const cancelling = editing?.mode === 'cancel'
  /* 청산은 새 주문이지만 값이 이미 정해져 있습니다. 정정·취소와 같은 자리에
     띠가 서지만 하는 일이 달라 모드를 따로 둡니다. */
  const mode = editing ? (cancelling ? 'cancel' : 'amend') : closing ? 'close' : 'new'

  /* 수량 상한.
   *
   * 청산은 들고 있는 만큼입니다 — 넘겨서 넣으면 청산에 신규 진입이 섞이는데,
   * 「청산」이라고 이름 붙인 단추가 그 일을 하면 안 됩니다.
   * 정정은 낸 주문의 수량까지입니다 — 그보다 늘리는 것은 정정이 아니라 새
   * 주문입니다. 둘 다 더 넣으려면 그만두기로 나가서 새로 냅니다. */
  /* 청산·정정의 수량 상한.
   *
   *  **수량을 모르는 줄은 여기까지 오지 않습니다** — 목록에서 단추를 안 세우고,
   *  폼을 여는 자리에서 한 번 더 막습니다. 그래도 0 으로 둡니다: 혹 새어 들어와도
   *  **막히는 쪽으로 실패**해야 합니다. 상한을 무한으로 두면 모르는 수량이
   *  그대로 주문에 실립니다. */
  const maxQuantity =
    (closing ? closing.quantity : editing ? editing.order.quantity : Number.POSITIVE_INFINITY) ?? 0
  const capQuantity = (value: number) => Math.min(maxQuantity, Math.max(1, value))
  /* 옵션인데 아직 안 고른 축이 있으면 낼 종목이 없습니다. 헤더·차트 배지가
     보는 것과 같은 자리에서 보고, 남은 축의 말도 같은 한 벌에서 가져옵니다. */
  const pendingLeg = needsLeg(quote.code)
  const pendingAsk = PENDING_TEXT[quote.pendingAxis ?? 'strike'].ask
  const limitLabel = closing ? '보유' : '낸 주문'
  /* 상한을 넘겨 친 적이 있는지. 넘긴 그 순간에만 한 줄이 뜹니다. */
  const [overLimit, setOverLimit] = useState(false)

  /* 가격 칸이 못 읽은 글자를 안고 있는지. **되돌릴 수 없는 자리의 마지막
     방어선입니다** — 그 상태에서는 칸에 보이는 글자와 주문에 실린 값이 다르므로,
     단추를 살려 두면 사용자가 안 친 값이 나갑니다. */
  const [priceBad, setPriceBad] = useState(false)
  const [stopBad, setStopBad] = useState(false)
  /* STOP 은 스탑가격이 있어야 나갑니다. 비어 있는 것도 「고칠 칸」입니다 — 서버가
     돌려보낼 요청을 단추가 살아서 보내게 두지 않습니다. 취소는 칸이 잠겨 고칠 수
     없어 여기서 막지 않고, 보내는 자리가 원주문의 값을 모르면 멈춥니다. */
  const stopMissing = needsStop && !cancelling && !pendingLeg && stopPrice === null
  const badFields = [priceBad ? '주문가격' : '', stopBad || stopMissing ? '스탑가격' : ''].filter(
    Boolean,
  )
  /* 못 내는 이유는 하나만 답니다. 종목이 아직 없으면 값을 고칠 자리도 없어
     그쪽이 먼저입니다. 어투는 같은 자리에 서는 「행사가를 고르세요」와
     맞춥니다 — 한 자리에 두 말투가 서면 다음 문장을 더할 기준이 없습니다.
     겹치면 사용자가 지금 할 수 있는 것(환경·행사가·값)부터 말합니다. */
  const blocked =
    credentialsWhy !== undefined ||
    overseasSpread ||
    environmentWhy !== undefined ||
    sessionWhy !== undefined ||
    pendingLeg ||
    orderBlocked ||
    badFields.length > 0
  const blockedWhy =
    /* 인증 정보가 없으면 그 말이 맨 앞입니다. 그다음 **해외 스프레드는 아직 붙는 길이
       없습니다** — 값을 고치고 행사가를 골라도 이것이 풀리지 않습니다. */
    credentialsWhy !== undefined
      ? credentialsWhy
      : overseasSpread
      ? '해외 스프레드 주문은 아직 연결되지 않았습니다'
      : environmentWhy !== undefined
        ? environmentWhy
        : sessionWhy !== undefined
          ? sessionWhy
          : pendingLeg
          ? pendingAsk
          : orderBlocked
            ? priceWhy
            : `${badFields.join('과 ')}을 고치세요`

  /* 모드가 바뀌면 지난 경고를 지웁니다 — 다른 주문에 붙은 말이 남아 있으면
     지금 값이 잘못된 것으로 보입니다. */
  useEffect(() => {
    setOverLimit(false)
  }, [closing, editing])

  /* 칸에 친 값을 상한 안으로 들여놓습니다.
   *
   * 다듬은 값이 지금 값과 같으면 React 는 다시 그리지 않습니다. 그러면 상태는
   * 3 인데 칸에는 방금 친 9 가 남아, **화면이 주문과 다른 수를 말합니다.**
   * 그래서 칸의 값도 직접 되돌려 놓습니다. */
  const applyQuantity = (input: HTMLInputElement) => {
    const typed = Number(input.value)
    const next = capQuantity(Number.isFinite(typed) && typed > 0 ? typed : 1)
    setOverLimit(input.value !== '' && typed > maxQuantity)
    if (next !== quantity) onQuantityChange(next)
    if (String(next) !== input.value) input.value = String(next)
  }

  return (
    /* 이름은 카드 머리 띠가 답니다. 여기서 한 번 더 붙이면 같은 이름의 영역이
       둘로 겹쳐, 보조 기술이 「주문 안의 주문」으로 읽습니다. */
    <section className={`order-form order-form-${side} order-form-${mode}`}>
      {/* 차트가 둘일 때 이 폼이 어느 종목인지. 왼쪽 초록 세로 바는 차트의 주문
          대상 배지와 같은 표시이고, 종목명이 큽니다 — 다른 칸의 종목을 보며
          이 폼으로 주문하는 일이 없어야 합니다. 머리를 색으로 채우지 않습니다:
          그러면 방향 세그먼트의 빨강·파랑 옆에 색 덩어리가 하나 더 섭니다. */}
      {renderOrderSubject({
        subject,
        quote,
        pendingLeg,
        d,
      })}

      {renderOrderEditing({
        editing,
        cancelling,
        onCancelEditing,
      })}

      {/* 청산은 「무엇을 덜어내는가」가 먼저입니다 — 들고 있는 방향과 수량을
          적어 두어야, 반대 방향으로 바뀐 폼이 실수로 보이지 않습니다.
          배지는 중립색입니다. 초록은 정정·취소가 쓰는데, 그 둘은 시장에 새
          주문을 안 냅니다 — 청산은 냅니다. */}
      {renderOrderClosing({
        closing,
        onCancelEditing,
      })}

      {/* 선물은 매수와 매도가 대등하므로 이것이 첫 컨트롤입니다.
          각 버튼에 그 방향의 최우선 호가가 함께 섭니다.

          **종목이 아직 안 정해졌으면 값은 빼고 방향만 둡니다.** 그때 호가는
          기초 선물의 것이라, 옵션을 고르는 중인 화면에서 그 값이 방향 단추에
          붙으면 「이 값으로 낸다」로 읽힙니다. 방향은 미리 골라 둘 수 있으므로
          단추 자체는 그대로 삽니다(차트 배지와 같은 판단). */}
      {renderOrderSide({
        side,
        sending,
        editing,
        closing,
        onSideChange,
        pendingLeg,
        bestBid,
        d,
        quote,
        bestAsk,
      })}

      {/* 정정·취소는 원주문의 매매구분을 그대로 따릅니다. 방향을 바꾸려면
          취소하고 새로 내야 하므로, 누를 수 있어 보이면 안 됩니다. */}
      {renderOrderLocked({
        editing,
        closing,
        cancelling,
        overseas,
      })}

      <div className="order-fields">
        {renderOrderTypeField({
          orderType,
          sending,
          cancelling,
          overseas,
          editing,
          onOrderTypeChange,
          typeOptions,
        })}

        {/* 체결조건은 국내에만 있습니다. 선택지는 주문유형이 받는 것만 둡니다 —
            시장가는 FAS 만 받습니다(`fillCondsFor`). */}
        {renderOrderCondition({
          overseas,
          condition,
          sending,
          cancelling,
          onConditionChange,
          orderType,
        })}

        {/* 값 칸 둘은 **낼 값**이라 대기 중에 기초 선물 값을 담지 않습니다.
            보이는 값은 그대로 두는데 이 둘만 비우는 이유는, 이것이 읽는 값이
            아니라 실제로 실려 나갈 숫자이기 때문입니다 — 기초 선물은 수백 단위,
            옵션 프리미엄은 한 자리 단위라 그 값을 기준으로 지정가를 잡으면
            자릿수가 어긋납니다. 왜 못 쓰는지는 실행 단추 밑에 한 번 적혀 있어
            칸에 또 적지 않습니다. */}
        <PriceField
          id="order-price"
          label="주문가격"
          /* 시장가로 나가는 주문에는 가격이 없습니다. 값을 남겨 두면 안 나가는
             값이 칸에 서 있습니다. */
          value={needsPrice && !pendingLeg ? price : null}
          decimals={d}
          fraction={quote.fraction}
          tick={quote.tickSize}
          signed={spread}
          step={DEFAULT_STEP}
          note={tickNote}
          noteWhy={tickWhy}
          disabled={sending || !needsPrice || cancelling || pendingLeg || orderBlocked}
          /* 값을 안 싣는 유형은 종목이 정해져도 안 쓰는 칸이라, 남은 할 일보다
             「이 칸은 안 쓴다」가 먼저입니다. **고른 유형의 이름을 그대로** 적되
             조사를 붙이지 않습니다 — 유형 이름의 끝소리가 제각각이라(「시장가」·
             「STOP-M」) 조사를 붙이면 어느 하나는 반드시 어색해집니다. */
          placeholder={needsPrice ? '' : `${orderType} · 가격 없이 나갑니다`}
          onChange={onPriceChange}
          onBlocked={setPriceBad}
        />
        {/* 잔고 조회 때의 값으로 채운 청산 가격. 지금 값이 아닐 수 있다는 것과
            시세가 오면 바뀐다는 것을 함께 말합니다 — 조용히 바뀌면 사용자는
            자기가 본 값이 왜 달라졌는지 모릅니다. */}
        {closePriceNote && needsPrice && (
          <p className="order-close-price-note">잔고 조회 때 값 — 시세가 오면 바꿉니다</p>
        )}

        {/* 스탑가격은 해외에만 있습니다. 값의 성질이 주문가격과 같아 적는
            방식도 같습니다 — 한쪽만 분수로 두면 같은 종목의 두 가격이 다른
            꼴로 서서, 어느 쪽이 어느 값인지 대볼 수 없습니다. */}
        {needsStop && (
          <PriceField
            id="order-stop"
            label="스탑가격"
            value={pendingLeg ? null : stopPrice}
            decimals={d}
            fraction={quote.fraction}
            tick={quote.tickSize}
            signed={spread}
            step={0.01}
            /* 주문가격 칸과 **같은 대접**입니다. 한 카드에서 한 칸은 막히고
               한 칸은 쳐지면, 못 내는 화면에서 값을 채우게 되고 그 값이
               가능수량을 묻는 길로 나갑니다. */
            disabled={sending || cancelling || pendingLeg || orderBlocked}
            onChange={onStopPriceChange}
            onBlocked={setStopBad}
          />
        )}

        <div className="order-field">
          <span className="control-label" id="order-qty-label">
            주문수량
          </span>
          {/* 선물 수량은 대개 한 자리 수라 타이핑보다 스테퍼가 빠르고,
              오타로 자릿수가 튀는 사고를 막습니다. */}
          <div className="qty-stepper">
            <button
              type="button"
              disabled={sending || cancelling}
              onClick={() => onQuantityChange(capQuantity(quantity - 1))}
              aria-label="수량 하나 줄이기"
            >
              −
            </button>
            <input
              type="number"
              inputMode="numeric"
              min={1}
              max={Number.isFinite(maxQuantity) ? maxQuantity : undefined}
              value={quantity}
              disabled={sending || cancelling}
              aria-labelledby="order-qty-label"
              onChange={(event) => applyQuantity(event.target)}
              onBlur={(event) => applyQuantity(event.target)}
            />
            <button
              type="button"
              disabled={sending || cancelling || quantity >= maxQuantity}
              onClick={() => onQuantityChange(capQuantity(quantity + 1))}
              aria-label="수량 하나 늘리기"
            >
              +
            </button>
          </div>

          {/* 왜 되돌아갔는지 그 자리에서 말합니다. 값만 조용히 바뀌면 자기가
              잘못 친 줄 알고 다시 칩니다. */}
          {overLimit && (
            <p className="order-limit">
              {limitLabel} {maxQuantity}계약까지만 {closing ? '청산할' : '정정할'} 수 있습니다
            </p>
          )}
          {/* 청산하러 왔는데 계좌가 청산가능을 0 으로 답했을 때. **막지 않습니다** —
              그 값이 보유와 어떻게 맞물리는지 화면이 단정할 수 없어, 서버가
              받을 수도 있는 주문을 화면이 막지 않습니다. 값이 없거나 0 보다 크거나
              못 물었으면 말하지 않습니다. */}
          {closing && orderable.status === 'ready' && orderable.closeQuantity === 0 && (
            <p className="order-limit order-close-zero">
              청산가능 0계약 — 서버가 이 청산을 받지 않을 수 있습니다
            </p>
          )}
        </div>

        {/* 이 주문이 묶을 개시증거금의 어림. **국내 신규 주문에서만** 값이 섭니다 —
            해외는 증거금을 주는 표가 없어 셈할 근거가 없고, 청산은 증거금을 푸는
            쪽이라 「이 주문 Y원」이 거짓이 되며, 정정·취소는 새로 묶는 것이 없습니다.
            스프레드는 두 다리에 증거금이 어떻게 걸리는지 셈할 근거가 없어 세우지
            않습니다.
            국내에서는 신규가 아닐 때도 **같은 높이의 빈 자리**를 둡니다 — 신규와 청산을
            오갈 때 아래 「가능수량 조회」 단추가 오르내리지 않게 합니다. */}
        {!overseas && !spread && (
          <MarginLine
            blank={mode !== 'new'}
            option={kind === 'option'}
            entry={tick}
            quantity={quantity}
          />
        )}

        {/* 가능수량은 계좌를 물어봐야 나오는 값이라 저절로 채워지지 않습니다.
            받은 값을 수량 칸에 넣어주지도 않습니다 — 증거금 한도까지 채우는
            것은 이 화면에서 가장 위험한 선택이라 한 번 눌러 들어가면 안 됩니다. */}
        {/* **자리를 늘 잡아 둡니다.** 누르기 전에는 비어 있지만 높이는 그대로라,
            답이 오고 가는 동안 아래 조회 단추가 오르내리지 않습니다 — 누르려던
            자리가 누르는 순간 움직이면 두 번째 누름이 엉뚱한 데로 갑니다. */}
        {renderOrderable({
          orderable,
          onCheckOrderable,
        })}
        <div className="order-check">
          <button
            type="button"
            className="btn btn-quiet"
            disabled={sending || cancelling || !canCheckOrderable}
            onClick={onCheckOrderable}
          >
            가능수량 조회
          </button>
        </div>
      </div>

      {/* 실행 버튼은 가능수량 조회 바로 아래, 스크롤 밖에 섭니다. 입력 칸이
          다 안 들어가는 낮은 창에서도 버튼은 밀려나지 않습니다.

          새 주문은 되돌릴 수 없어 방향색으로 채웁니다.
          정정과 취소는 이미 낸 주문을 줄이거나 고치는 쪽이라 초록입니다 —
          이 앱에서 초록은 「눌러도 되는 것」이고, 그 뜻이 여기서 맞습니다. */}
      <button
        type="button"
        /* 청산 단추는 방향색입니다. 초록으로 두면 정정·취소와 같은 무게로
           읽히는데, 그 둘과 달리 이건 시장에 새 주문을 냅니다. */
        /* 값이 상한을 넘은 채로는 나가지 않습니다. 들여놓기가 먼저 막지만,
           되돌릴 수 없는 자리라 단추에서 한 번 더 봅니다.
           **답을 기다리는 동안에도 잠깁니다** — 두 번 누르면 두 건이 나갑니다. */
        disabled={quantity > maxQuantity || sending}
        /* 누르면 되묻는 창이 뜹니다. 여기서 바로 보내지 않습니다. */
        onClick={() => {
          if (blocked || submitPaused || sending || quantity > maxQuantity) return
          onSubmit()
        }}
        /* 낼 종목이 없거나(콜/풋·행사가 미정) 가격 칸이 못 읽은 글자를 안고
           있으면 못 냅니다. `disabled` 가 아니라 `aria-disabled` 인 것은 초점을
           받아야 왜 못 내는지 적어 둔 말에 키보드로도 닿기 때문입니다. */
        aria-disabled={blocked || submitPaused || undefined}
        aria-describedby={blocked ? 'order-submit-why' : undefined}
        className={`btn order-submit ${editing ? 'btn-primary' : `order-submit-${side}`}`}
      >
        {cancelling
          ? '주문 취소'
          : editing
            ? '주문 정정'
            : side === 'buy'
              ? closing
                ? '매수 청산'
                : '매수'
              : closing
                ? '매도 청산'
                : '매도'}
        {/* 어느 종목에 내는지가 단추에 붙습니다. 차트가 둘이면 눈은 차트에
            있고 손은 여기 있어, 단추만 보고도 종목이 맞는지 알아야 합니다. */}
        <small className="order-submit-name">{quote.name}</small>
      </button>
      {/* 못 누르는 이유는 단추 바로 아래입니다. 고를 자리(체인)도 고칠 자리
          (가격 칸)도 같은 화면에 있어, 이 말이 시키는 것과 눈이 갈 곳이 같습니다.

          **보낸 결과도 같은 자리에 섭니다.** 한 자리에 둘이 겹치면 못 내는
          이유가 먼저입니다 — 지난 주문의 결과보다 지금 못 내는 사정이 급합니다. */}
      {blocked ? (
        /* 단추는 사유 문장 **밖**에 둡니다. 실행 단추가 이 문장을 설명으로 가리키므로
           (`aria-describedby`), 안에 두면 읽어 주는 도구가 사유 끝에 「다시」까지
           읽어 문장이 틀려집니다. 보이는 꼴은 문장 뒤에 붙은 그대로입니다. */
        <div className="order-submit-why">
          <p id="order-submit-why">{blockedWhy}</p>
          {/* 세션을 못 받아 막힌 때만 다시 묻는 손이 섭니다. */}
          {credentialsWhy === undefined &&
            environmentWhy === undefined &&
            sessionWhy !== undefined &&
            onRetrySession && (
            <button type="button" className="btn btn-quiet order-submit-retry" onClick={onRetrySession}>
              다시
            </button>
          )}
        </div>
      ) : (
        <OrderResultLine sending={sending} result={result} onOpenOrders={onOpenOrders} />
      )}
    </section>
  )
}
