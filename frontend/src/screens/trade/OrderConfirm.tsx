import { Modal } from '../../app/Modal'
import { Num } from '../../lib/number'
import { ENVIRONMENT_LABEL, useEnvironment } from '../../data/environment'
import { expiryLabel } from '../../data/instruments'
import type { MasterLegs } from '../../data/master'
import type { OrderKind } from '../../data/orders'

/* 주문을 보내기 전에 한 번 되묻는 창.
 *
 * **되돌릴 수 없는 한 걸음에만 섭니다.** 대상을 고르는 단계(표의 정정·취소
 * 단추)에는 안 붙습니다 — 거기서 물으면 한 주문에 두 번 묻게 되고, 두 번째
 * 물음은 첫 번째를 읽지 않게 만듭니다.
 *
 * 되묻는 값은 **틀렸을 때 피해가 큰 순서**입니다: 계좌 → 종목 → 구분 → 수량 →
 * 가격. 모의인 줄 알고 낸 주문이 실전 계좌로 나가면 종목이 무엇이든 되돌릴 수
 * 없고, 가격이 틀리면 그 값에 체결될 뿐입니다.
 *
 * ✕ 가 없습니다. 창이 물은 것에 답하는 자리는 아래 단추 둘이고, ✕ 를 두면 첫
 * 초점이 그리로 갑니다. 바깥을 눌러도 안 닫힙니다.
 *
 * **「다시 묻지 않기」는 없습니다.** 한 번 꺼 두면 그 뒤로 모든 주문이 확인 없이
 * 나가는데, 이 창이 막으려는 것은 익숙해진 손입니다.
 */

/** 창이 되묻는 한 건. 값은 **폼에 보이는 그대로** 받습니다 — 여기서 다시
 *  계산하면 폼과 창이 다른 값을 말할 수 있습니다. */
export interface OrderConfirmAsk {
  kind: OrderKind
  /** 청산인가. 신규와 라우트는 같지만 단추 낱말이 다릅니다. */
  closing?: boolean
  side: 'buy' | 'sell'
  /** 만기까지 붙은 종목 이름. */
  name: string
  quantity: number
  orderType: string
  price: number | null
  /** 체결조건(국내). 가격 줄에 붙습니다. */
  condition?: string
  /** 스탑가격(해외 STOP). 주문유형이 STOP 이면 가격 줄 아래 한 줄로 섭니다. */
  stopPrice?: number | null
  decimals: number
  fraction?: number | null
  /** 정정에서 **바뀌는 값**을 가리는 데 쓰는 원주문 값. */
  before?: { quantity: number | null; price: number | null; stop?: number | null }
  /** 스프레드 종목의 두 다리 만기(마스터에서). 스프레드가 아니거나 다리가 안 실려
   *  오면 없습니다. */
  legs?: MasterLegs | null
}

/** 실행 단추에 서는 낱말. **카드의 실행 단추와 같아야 합니다** — 누른 단추와 창의
 *  단추가 다른 낱말이면 다른 일을 하는 것으로 읽힙니다. */
export function actionWord(ask: OrderConfirmAsk): string {
  if (ask.kind === 'cancel') return '주문 취소'
  if (ask.kind === 'modify') return '주문 정정'
  if (ask.closing) return ask.side === 'buy' ? '매수 청산' : '매도 청산'
  return ask.side === 'buy' ? '매수' : '매도'
}

/** 창 제목에 서는 **동작 이름**. 단추 낱말과 갈라 둡니다 — 단추는 「무엇을 누르나」
 *  라 카드와 같은 낱말이어야 하고, 제목은 「무슨 창인가」라 그것만으로 무슨 일이
 *  일어나는지 읽혀야 합니다. 「매도」 한 낱말은 방향이지 동작이 아닙니다. */
function titleWord(ask: OrderConfirmAsk): string {
  if (ask.kind === 'cancel') return '주문 취소'
  if (ask.kind === 'modify') return '주문 정정'
  return `${ask.side === 'buy' ? '매수' : '매도'} 주문`
}

/** 값이 정해지지 않은 주문유형인지. 가격 줄이 유형 이름(「시장가」·「STOP-M」)으로
 *  섭니다. STOP-M 은 스탑가격에 닿으면 시장가로 나가 주문가격이 없습니다. */
function priceless(orderType: string): boolean {
  return orderType === '시장가' || orderType === '최유리지정가' || orderType === 'STOP-M'
}

/** 스탑가격이 있는 주문유형인지(해외 STOP 두 유형). */
function stopped(orderType: string): boolean {
  return orderType === 'STOP-M' || orderType === 'STOP-L'
}

function Row({
  label,
  children,
  faint,
}: {
  label: string
  children: React.ReactNode
  /** 정정에서 **안 바뀐 값**. 바뀌는 값만 눈에 들어와야 합니다. */
  faint?: boolean
}) {
  return (
    <div className="confirm-row">
      <dt>{label}</dt>
      <dd className={faint ? 'dead' : undefined}>{children}</dd>
    </div>
  )
}

export function OrderConfirm({
  ask,
  onConfirm,
  onCancel,
}: {
  ask: OrderConfirmAsk
  onConfirm: () => void
  onCancel: () => void
}) {
  const word = actionWord(ask)
  const title = titleWord(ask)
  /* 어느 환경에 붙어 있는지는 **서버가 답한 값**뿐입니다. 화면이 따로 들고
     있지 않습니다 — 화면이 믿는 것과 요청이 나가는 곳이 갈리면, 이 창이
     말한 계좌와 주문이 닿는 계좌가 달라집니다. */
  const environment = useEnvironment().active
  const sideWord = ask.side === 'buy' ? '매수' : '매도'
  const d = ask.decimals
  const noPrice = priceless(ask.orderType)
  /* 정정은 바뀌는 값만 굵습니다. 원주문 값이 없으면(모르는 줄) 다 굵게 둡니다 —
     안 바뀐 것으로 흐리면 고치는 값이 안 보입니다. */
  const sameQuantity = ask.before ? ask.before.quantity === ask.quantity : false
  const samePrice = ask.before ? ask.before.price === ask.price : false
  const hasStop = stopped(ask.orderType)
  const stop = ask.stopPrice ?? null
  const beforeStop = ask.before?.stop ?? null
  const sameStop = ask.before ? beforeStop === stop : false

  /* 가격 줄. **체결조건은 값이 없는 유형에서도 함께 섭니다** — 시장가로 내도
     FOK 인지 FAS 인지에 따라 체결이 달라지고, 그것도 나가는 값입니다. */
  const condition = ask.condition ? <span className="t-label"> · {ask.condition}</span> : null
  const price = noPrice ? (
    <span>
      {ask.orderType}
      {condition}
    </span>
  ) : (
    <span>
      <Num value={ask.price ?? 0} decimals={d} fraction={ask.fraction} />
      {condition}
    </span>
  )

  return (
    <Modal
      label={`${title} 확인`}
      head={<h2 className="modal-title">{title}</h2>}
      dismissable={false}
      closable={false}
      onClose={onCancel}
    >
      <div className="order-confirm">
        {/* 취소는 고칠 값이 없어 되물을 것이 「이 주문이 맞나」 하나입니다 —
            라벨–값 넷으로 늘어놓으면 읽을 것이 네 줄인데 고를 것은 없습니다. */}
        {ask.kind === 'cancel' ? (
          <>
            {/* 취소도 되돌릴 수 없습니다 — 어느 계좌의 주문인지 신규·정정과 같은
                줄로 먼저 적습니다. 모르면 이 줄을 안 세웁니다(아래와 같은 까닭). */}
            {environment !== null && (
              <dl className="confirm-sheet">
                <Row label="계좌">
                  <span className={`badge ${environment === 'paper' ? 'env-sim' : 'env-live'}`}>
                    {ENVIRONMENT_LABEL[environment]}
                  </span>
                </Row>
              </dl>
            )}
            <p className="confirm-sentence">
              {`${ask.name} · ${sideWord} ${ask.quantity}계약`}
              {ask.price !== null && !noPrice ? (
                <>
                  {' · '}
                  <Num value={ask.price} decimals={d} fraction={ask.fraction} />
                </>
              ) : null}
              {' 주문을 취소합니다'}
            </p>
          </>
        ) : (
          <dl className="confirm-sheet">
            {/* 어느 계좌로 나가는가. 낱말·표시는 상단 배지와 같은 것입니다 —
                같은 사실을 두 자리가 다른 말로 하면 어느 쪽이 맞는지 세어
                보게 됩니다.
                **모르면 이 줄을 안 세웁니다.** 「모의」를 기본으로 적어 두면
                실전에서 거짓이 되는데, 이 창 다음 걸음은 되돌릴 수 없습니다. */}
            {environment !== null && (
              <Row label="계좌">
                <span className={`badge ${environment === 'paper' ? 'env-sim' : 'env-live'}`}>
                  {ENVIRONMENT_LABEL[environment]}
                </span>
              </Row>
            )}
            <Row label="종목">{ask.name}</Row>
            <Row label="구분">
              <span className={`badge ${ask.side === 'buy' ? 'badge-buy' : 'badge-sell'}`}>
                {sideWord}
              </span>
              {ask.closing ? <span className="t-label"> 청산</span> : null}
            </Row>
            {/* 스프레드는 어느 두 만기가 맞물린 종목인지를 구분 바로 아래 적습니다.
                다리마다 사고파는 방향은 적지 않습니다 — 서버 답에 그 값이 없어,
                적으면 화면이 지은 규칙이 됩니다. 수량은 다리마다 되풀이하지 않습니다. */}
            {ask.legs && (
              <Row label="다리">
                근월 {expiryLabel(ask.legs.near)}
                <br />
                원월 {expiryLabel(ask.legs.far)}
              </Row>
            )}
            <Row label="수량" faint={sameQuantity}>
              {ask.quantity}계약
              {ask.before && ask.before.quantity !== null && !sameQuantity ? (
                <span className="t-label"> ← {ask.before.quantity}계약</span>
              ) : null}
            </Row>
            <Row label="가격" faint={samePrice}>
              {ask.before && ask.before.price !== null && !samePrice && !noPrice ? (
                <>
                  <span className="t-label">
                    <Num value={ask.before.price} decimals={d} fraction={ask.fraction} /> →{' '}
                  </span>
                  {price}
                </>
              ) : (
                price
              )}
            </Row>
            {/* 스탑가격은 가격 줄 바로 아래입니다 — 폼도 주문가격 다음에 스탑가격
                칸이 섭니다. 정정이면 가격 줄과 같은 규칙으로 바뀐 값만 굵습니다. */}
            {hasStop && (
              <Row label="스탑가격" faint={sameStop}>
                {ask.before && beforeStop !== null && !sameStop ? (
                  <span className="t-label">
                    <Num value={beforeStop} decimals={d} fraction={ask.fraction} /> →{' '}
                  </span>
                ) : null}
                {stop === null ? '—' : <Num value={stop} decimals={d} fraction={ask.fraction} />}
              </Row>
            )}
          </dl>
        )}

        {/* 시장가는 값을 정하지 않고 나갑니다. 가격 줄에 「시장가」만 서면 그
            사실이 안 읽혀, 지금 보이는 현재가에 나가는 것으로 오해합니다.
            STOP-M 은 스탑가격에 닿은 뒤에 그렇게 나갑니다. */}
        {noPrice && ask.kind !== 'cancel' && (
          <p className="confirm-note">
            {hasStop ? '스탑가격에 닿으면 가격을 정하지 않고 나갑니다' : '가격을 정하지 않고 나갑니다'}
          </p>
        )}

        <div className="confirm-actions">
          {/* 「취소」는 주문 취소와 겹칩니다. 창을 물러나는 낱말은 앱 전체에서
              「그만두기」입니다. 첫 초점이 여기입니다 — 창이 뜬 순간 Enter 를
              누르면 아무 일도 안 일어나야 합니다. */}
          <button type="button" className="btn btn-quiet" onClick={onCancel}>
            그만두기
          </button>
          <button
            type="button"
            className={`btn ${
              ask.kind === 'new' ? `order-submit-${ask.side}` : 'btn-primary'
            }`}
            onClick={onConfirm}
          >
            {word}
          </button>
        </div>
      </div>
    </Modal>
  )
}
