import type { ReactNode } from 'react'
import { PRODUCT_INFO_FAILED, ceilWon, type ProductInfoEntry } from '../../data/productInfo'

/** 옵션 카드의 증거금 안내. 빈 자리가 높이를 맞추려고 같은 문장을 씁니다. */
const OPTION_MARGIN_NOTE = '옵션 증거금은 품목정보에 없습니다'

/** 개시증거금 어림 한 줄 —「계약당 X원 · 이 주문 Y원」과 그 셈을 밝히는 한 줄.
 *
 *  **두 수는 각각 원 단위 올림입니다.** 증거금은 모자라면 안 되는 값이라, 내린 수를
 *  「묶인다」고 적으면 실제보다 적게 말합니다. 곱셈은 **받은 원값**으로 합니다 —
 *  계약당을 먼저 올려 곱하면 수량만큼 오차가 불어납니다.
 *
 *  **자리 높이는 늘 같습니다.** 값이 오기 전에도, 수량이 비어 뒷마디와 셈 줄이
 *  빠져도 두 줄의 자리를 잡아 두어, 아래 「가능수량 조회」 단추가 오르내리지
 *  않습니다. 좁은 카드에서는 「·」 뒤에서 다음 줄로 넘어갑니다. */
export function MarginLine({
  blank,
  option,
  entry,
  quantity,
}: {
  /** 신규가 아닌 주문(청산·정정·취소) — 라벨도 값도 없이 자리만 잡습니다. */
  blank: boolean
  option: boolean
  entry: ProductInfoEntry
  quantity: number
}) {
  if (blank) {
    /* 옵션의 안내 문장은 좁은 카드에서 두 줄로 꺾입니다. 빈 자리에도 **같은 문장을
       보이지 않게** 넣어, 폭이 바뀌어도 신규일 때와 같은 높이를 잡습니다. */
    return (
      <div className="order-field order-margin" aria-hidden="true">
        <span className="control-label" />
        <div>
          <p className="order-margin-value" />
          <p className="order-margin-note" style={{ visibility: 'hidden' }}>
            {option ? OPTION_MARGIN_NOTE : ''}
          </p>
        </div>
      </div>
    )
  }
  let value: ReactNode = null
  let title: string | undefined
  let note = ''
  if (option) {
    /* 옵션은 품목정보에 증거금이 없습니다. 셈할 값이 없다는 사실만 적습니다. */
    value = '계약당 —'
    note = OPTION_MARGIN_NOTE
  } else if (entry.status === 'failed') {
    value = '계약당 —'
    title = PRODUCT_INFO_FAILED
  } else if (entry.status === 'ready' && entry.row) {
    const each = entry.row.contractInitialMargin
    if (each == null) {
      value = '계약당 —'
      title = entry.row.why || undefined
    } else {
      const per = `계약당 ${ceilWon(each).toLocaleString('ko-KR')}원`
      if (Number.isFinite(quantity) && quantity > 0) {
        const total = ceilWon(each * quantity).toLocaleString('ko-KR')
        value = (
          <>
            <span className="order-margin-part">{per} ·</span>{' '}
            <span className="order-margin-part">이 주문 {total}원</span>
          </>
        )
        note = '품목 값 × 수량으로 셈했습니다'
      } else {
        value = <span className="order-margin-part">{per}</span>
      }
    }
  }
  return (
    <div className="order-field order-margin">
      <span className="control-label">개시증거금</span>
      <div>
        <p className="order-margin-value" title={title}>
          {value}
        </p>
        <p className="order-margin-note">{note}</p>
      </div>
    </div>
  )
}
