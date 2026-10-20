import type { OrderKind, OrderResult } from '../../data/orders'

/** 받아들여진 답의 머리 — 결과까지 확인됐을 때와 접수만 확인됐을 때. */
const ACCEPTED_WORD: Record<OrderKind, { confirmed: string; unconfirmed: string }> = {
  new: { confirmed: '접수됨', unconfirmed: '접수됨' },
  modify: { confirmed: '정정됨', unconfirmed: '정정 접수됨' },
  cancel: { confirmed: '취소됨', unconfirmed: '취소 접수됨' },
}

/** 거절된 답의 머리. 정정·취소의 거부는 「원주문에 그 요청이 적용되지 않았다」는
 *  뜻이라 신규의 거절과 낱말을 가릅니다. */
const REJECTED_WORD: Record<OrderKind, string> = {
  new: '거절',
  modify: '정정 거부',
  cancel: '취소 거부',
}

/* 보낸 주문의 결과 한 줄.
 *
 * **시간으로 사라지지 않습니다.** 사용자의 다음 손(값·종목 바꿈·다시 보내기)이
 * 걷어냅니다 — 몇 초 뒤 지워지면 자리를 비운 사이에 눈을 돌린 사람은 자기 주문이
 * 어떻게 됐는지 영영 못 봅니다.
 *
 * 색이 셋입니다. 거절은 **오류색**(서버가 안 받았다), 결과를 모르는 것은
 * **경고색**(냈는지 아닌지 모른다), 재생에서 못 내는 것은 **색 없음**(이 실행에서
 * 못 낼 뿐 주문에 아무 일도 없었다). 접수와 보내는 중도 색이 없습니다 — 색은
 * 「봐야 한다」는 뜻이고 잘 된 일에는 그 뜻이 없습니다.
 *
 * **결과를 모르는 자리에 「다시 보내기」를 세우지 않습니다.** 서버가 받았을 수도
 * 있는 주문을 한 번 더 내면 두 배로 체결됩니다. 대신 주문체결상세로 보냅니다 —
 * 무엇이 나갔는지는 거기서만 알 수 있습니다.
 *
 * **접수 번호를 받은 뒤 결과를 확인하지 못한 주문도 경고색입니다.** 접수는 됐지만
 * 그 뒤 거절됐는지 모르는 자리라, 「접수됨」만 적으면 확인할 까닭이 안 보입니다.
 * 신규·정정·취소가 같은 세 얼굴(됨 / 결과 미확인 / 거부)로 섭니다.
 */
export function OrderResultLine({
  sending,
  result,
  onOpenOrders,
}: {
  sending: boolean
  result: OrderResult | null
  onOpenOrders: () => void
}) {
  if (sending) {
    /* 서버가 접수 뒤 결과까지 확인하고 답하므로 몇 초 걸릴 수 있습니다. 그동안
       실행 단추는 잠겨 있어 같은 주문이 두 번 나가지 않습니다. */
    return <p className="order-result">보내는 중…</p>
  }
  if (!result) return null

  if (result.kind === 'accepted') {
    const done = ACCEPTED_WORD[result.action]
    if (result.confirmed) {
      return (
        <p className="order-result">
          {done.confirmed} · 주문번호 {result.orderId}
        </p>
      )
    }
    return (
      <div className="order-result is-unknown">
        <p className="order-result-text">
          {done.unconfirmed} · 주문번호 {result.orderId} · 결과 미확인 — 주문체결상세에서 확인하세요
        </p>
        <button type="button" className="btn btn-quiet order-result-go" onClick={onOpenOrders}>
          주문체결상세 보기
        </button>
      </div>
    )
  }
  if (result.kind === 'rejected') {
    /* 코드와 문구는 서버가 준 그대로입니다. 둘 중 비어 오는 것은 빼고 적습니다. */
    const parts = [REJECTED_WORD[result.action]]
    if (result.code) parts.push(`코드 ${result.code}`)
    if (result.reason) parts.push(result.reason)
    return <p className="order-result is-rejected">{parts.join(' · ')}</p>
  }
  if (result.kind === 'blocked') {
    return <p className="order-result">{result.reason}</p>
  }
  /* `unknown`·`failed` — 냈는지 모르는 자리. */
  return (
    <div className="order-result is-unknown">
      <p className="order-result-text">{result.reason}</p>
      {/* 문장과 **다른 줄**입니다 — 문장 끝에 붙으면 마지막 낱말처럼 읽혀서,
          읽는 도중에 눌러야 할 것이 있다는 것이 늦게 보입니다. */}
      <button type="button" className="btn btn-quiet order-result-go" onClick={onOpenOrders}>
        주문체결상세 보기
      </button>
    </div>
  )
}
