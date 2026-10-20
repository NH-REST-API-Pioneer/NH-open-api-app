import { Num, fracWidth, signSpace } from '../../lib/number'
import type { Position, Quote } from '../../lib/types'
import { PENDING_TEXT } from '../../data/instruments'
import type { OrderEdit, Side } from './OrderForm'

/** 두 차트일 때 이 폼이 어느 종목인지 다는 머리. */
export function renderOrderSubject({
  subject,
  quote,
  pendingLeg,
  d,
}: {
  subject: boolean
  quote: Quote
  pendingLeg: boolean
  d: number
}) {
  return (
      subject && (
        <div className="order-subject">
          <span className="order-subject-title">주문 대상</span>
          <b className="order-subject-name">{quote.name}</b>
          {/* 아직 종목이 아니면 값 자리에 남은 축을 세웁니다. 그 값은 기초
              선물의 것이라, 「주문 대상」이라고 적힌 자리에 그대로 두면 이 값으로
              낸다는 뜻이 됩니다 — 차트 배지가 값을 뺀 것과 같은 자리입니다. */}
          {pendingLeg ? (
            <span className="order-subject-pending">{PENDING_TEXT[quote.pendingAxis ?? 'strike'].pick}</span>
          ) : (
            <span className="order-subject-quote">
              {quote.last !== null && (
                <Num value={quote.last} decimals={d} fraction={quote.fraction} />
              )}{' '}
              {quote.change !== null && (
                <Num value={quote.change} decimals={d} fraction={quote.fraction} signed toned />
              )}
            </span>
          )}
        </div>
      )
  )
}

/** 정정·취소 중인 주문의 띠. */
export function renderOrderEditing({
  editing,
  cancelling,
  onCancelEditing,
}: {
  editing: OrderEdit | null
  cancelling: boolean
  onCancelEditing: () => void
}) {
  return (
      editing && (
        <div className="order-editing">
          <span className="badge badge-brand">{cancelling ? '취소' : '정정'}</span>
          <span className="t-label">
            {editing.order.side === 'buy' ? '매수' : '매도'} {editing.order.quantity}계약
          </span>
          <button type="button" className="btn order-editing-cancel" onClick={onCancelEditing}>
            그만두기
          </button>
        </div>
      )
  )
}

/** 청산 중인 보유의 띠. */
export function renderOrderClosing({
  closing,
  onCancelEditing,
}: {
  closing: Position | null | undefined
  onCancelEditing: () => void
}) {
  return (
      closing && (
        <div className="order-editing">
          <span className="badge">청산</span>
          <span className="t-label">
            {closing.side === 'long' ? '매수' : '매도'} {closing.quantity}계약 보유
          </span>
          <button type="button" className="btn order-editing-cancel" onClick={onCancelEditing}>
            그만두기
          </button>
        </div>
      )
  )
}

/** 매수·매도 세그먼트와 그 방향의 최우선 호가. */
export function renderOrderSide({
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
}: {
  side: Side
  sending: boolean
  editing: OrderEdit | null
  closing: Position | null | undefined
  onSideChange: (side: Side) => void
  pendingLeg: boolean
  bestBid: number | null
  d: number
  quote: Quote
  bestAsk: number | null
}) {
  return (
      <div className="seg order-side">
        <button
          type="button"
          className="seg-item seg-buy"
          aria-pressed={side === 'buy'}
          disabled={sending || editing !== null || closing != null}
          onClick={() => onSideChange('buy')}
        >
          매수
          {/* 걸린 호가가 없으면 **숫자 자리를 통째로 뺍니다.** 「—」를 세우면
              그 글리프가 이 화면에서 이미 맡은 뜻(「이 자리에 값이 안 선다 —
              할 일이 없다」)과 부딪힙니다. 값을 못 받은 것은 할 일이 있는
              상태이고, 그 이유는 실행 단추 밑이 한 번 말합니다. 단추의 이름은
              「매수」이고 값은 덤이라, 덤이 없으면 이름만 남습니다. */}
          {!pendingLeg && bestBid !== null && (
            <span className="seg-price" style={fracWidth(d, signSpace(quote.kind), quote.fraction)}>
              <Num value={bestBid} decimals={d} fraction={quote.fraction} />
            </span>
          )}
        </button>
        <button
          type="button"
          className="seg-item seg-sell"
          aria-pressed={side === 'sell'}
          disabled={sending || editing !== null || closing != null}
          onClick={() => onSideChange('sell')}
        >
          매도
          {!pendingLeg && bestAsk !== null && (
            <span className="seg-price" style={fracWidth(d, signSpace(quote.kind), quote.fraction)}>
              <Num value={bestAsk} decimals={d} fraction={quote.fraction} />
            </span>
          )}
        </button>
      </div>
  )
}

/** 정정·취소·청산에서 바꿀 수 없는 것을 적는 한 줄. */
export function renderOrderLocked({
  editing,
  closing,
  cancelling,
  overseas,
}: {
  editing: OrderEdit | null
  closing: Position | null | undefined
  cancelling: boolean
  overseas: boolean
}) {
  return (
      (editing || closing) && (
        <p className="order-locked">
          {cancelling
            ? '취소는 낸 주문 그대로 나갑니다'
            : editing
              ? overseas
                ? '정정은 방향·주문유형을 바꿀 수 없습니다'
                : '정정은 방향을 바꿀 수 없습니다'
              : '보유와 반대 방향으로 채웠습니다. 수량·가격은 바꿔도 됩니다'}
        </p>
      )
  )
}
