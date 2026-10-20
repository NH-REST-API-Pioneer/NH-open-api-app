import type { OrderableState } from '../../data/orderable'
import { fillCondsFor } from '../../data/strategyRules'
import type { OrderEdit } from './OrderForm'

/** 주문유형 칸. */
export function renderOrderTypeField({
  orderType,
  sending,
  cancelling,
  overseas,
  editing,
  onOrderTypeChange,
  typeOptions,
}: {
  orderType: string
  sending: boolean
  cancelling: boolean
  overseas: boolean
  editing: OrderEdit | null
  onOrderTypeChange: (type: string) => void
  typeOptions: string[]
}) {
  return (
        <label className="order-field">
          <span className="control-label">주문유형</span>
          {/* 해외 정정은 원주문의 주문유형으로 나갑니다 — 바꿀 수 있어 보이면
              바꾼 유형으로 고쳐지는 것처럼 읽힙니다. */}
          <select
            className="control"
            value={orderType}
            disabled={sending || cancelling || (overseas && editing !== null)}
            onChange={(event) => onOrderTypeChange(event.target.value)}
          >
            {typeOptions.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
  )
}

/** 체결조건 칸(국내만). */
export function renderOrderCondition({
  overseas,
  condition,
  sending,
  cancelling,
  onConditionChange,
  orderType,
}: {
  overseas: boolean
  condition: string
  sending: boolean
  cancelling: boolean
  onConditionChange: (condition: string) => void
  orderType: string
}) {
  return (
        !overseas && (
          <label className="order-field">
            <span className="control-label">체결조건</span>
            <select
              className="control"
              value={condition}
              disabled={sending || cancelling}
              onChange={(event) => onConditionChange(event.target.value)}
            >
              {fillCondsFor(orderType).map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        )
  )
}

/** 가능수량 줄 — 받는 중·값·못 받음. */
export function renderOrderable({
  orderable,
  onCheckOrderable,
}: {
  orderable: OrderableState
  onCheckOrderable: () => void
}) {
  return (
        <p className="order-orderable">
          {orderable.status === 'loading' && (
            <>
              가능수량 <span className="skeleton" style={{ minWidth: '4ch' }} />
            </>
          )}
          {/* 값이 비어 올 수 있습니다. 그때 0 을 적으면 「낼 수 없다」가 되는데
              화면이 아는 것은 「받은 답에 수가 없다」까지입니다. */}
          {/* 서는 수는 **신규와 청산의 합** — 서버가 준 뜻 그대로 적습니다. 신규·청산
              가능수(`newQuantity`/`closeQuantity`)가 따로 오지만 이 자리에는 합을 그
              이름으로 보입니다. 청산 가능 수는 청산할 때 0 이면 서는 안내에만 쓰고,
              신규 가능 수는 화면에 쓰지 않습니다. */}
          {orderable.status === 'ready' &&
            (orderable.quantity === null ? (
              '가능수량 값 없음'
            ) : (
              <>
                신규·청산 합 <b>{orderable.quantity}</b>계약
              </>
            ))}
          {orderable.status === 'failed' && (
            <>
              {/* NH선물 오류 코드가 함께 온 거절이면 서버가 보낸 문장(코드와 문구)을
                  그대로 세웁니다. 코드가 없거나 문장이 안 왔거나 다시 불러 볼 만한
                  실패면 일반 문구입니다. */}
              {orderable.failure === 'rejected' && orderable.code && orderable.text
                ? orderable.text
                : '가능수량 받지 못했습니다'}
              {/* 거절은 눌러도 같은 답이 옵니다. 다시 부를 길은 조건을 바꾸는
                  것이고 그 칸들은 바로 위에 있습니다. */}
              {orderable.failure === 'retry' && (
                <button
                  type="button"
                  className="btn btn-quiet order-orderable-retry"
                  onClick={onCheckOrderable}
                >
                  다시
                </button>
              )}
            </>
          )}
        </p>
  )
}
