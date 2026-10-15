import { Count, Num, fracWidth } from '../../lib/number'
import { expiryText } from '../../data/instruments'
import type { ContractRow, ProductKind } from '../../lib/types'

/* 종목 카탈로그의 가운데 목록.
 *
 * 시세가 없습니다. 현재가·등락·거래량은 이 화면이 부르지 않습니다 — 무엇이
 * 있는지 고르는 자리이지 얼마인지 보는 자리가 아닙니다. 값이 없으니 조회
 * 버튼도, 값을 기다리는 자리도, 「받지 못했습니다」도 없습니다.
 *
 * 대신 마스터가 주는 종목의 성질을 보여줍니다. 거래승수와 호가단위는 주문을
 * 낼 때 알아야 하는 값인데, 고른 뒤에 품목정보에서 찾는 것보다 고르기 전에
 * 보이는 편이 순서에 맞습니다.
 *
 * 열이 시장마다 다릅니다. 국내 마스터에는 거래승수와 잔존일수가 있고 호가단위가
 * 없으며, 해외 마스터에는 호가단위가 있고 나머지 둘이 없습니다. 없는 값을 빈
 * 칸으로 두면 「아직 안 온 것」처럼 보이므로, 그 시장에 있는 열만 세웁니다.
 */

interface Props {
  rows: ContractRow[]
  overseas: boolean
  /** 지금 보고 있는 종류. 열 수와 누를 수 있는지가 여기서 갈립니다. */
  kind: ProductKind
  /** 이 품목 가격의 소수 자릿수. 호가단위를 그리는 데 씁니다. */
  decimals: number
  onOpen: (row: ContractRow) => void
}

export function CatalogList({ rows, overseas, kind, decimals, onOpen }: Props) {
  if (rows.length === 0) {
    /* 목록이 손에 있으므로 「없다」를 단정할 수 있습니다. 다른 화면과 달리
       「못 받았습니다」와 갈라 말할 필요가 없는 유일한 자리입니다.
       **「다시 받기」를 안 답니다.** 받기가 실패한 것이 아니라 받은 것이 비어
       있는 것이라, 다시 받아도 같습니다 — 눌러도 안 바뀌는 단추는 거짓말을
       합니다. 받지 못한 경우는 따로 말합니다. */
    return (
      <div className="notice">
        <p className="notice-title">이 품목에는 상장된 종목이 없습니다</p>
        <p className="notice-reason">목록은 정상으로 받았습니다 — 다시 받아도 같습니다</p>
      </div>
    )
  }

  return (
    <div className="catalog-pane">
      <div className="table-scroll">
        <table className="data-table rows-base catalog">
          {/* 값 열은 폭을 못 박고 **남는 폭은 종목명이 다 먹습니다.** 균등하게
              나누면 종목명이 다섯 중 하나만 받아, 두 만기를 다 적는 스프레드
              이름이 잘리는 자리에서 잘립니다 — 잘린 자리가 하필 만기입니다. */}
          <colgroup>
            <col className="col-name" />
            <col className="cat-code" />
            <col className="cat-expiry" />
            {overseas ? <col className="cat-tick" /> : <col className="cat-days" />}
            {!overseas && <col className="cat-mult" />}
          </colgroup>
          <thead>
            <tr>
              <th scope="col">종목명</th>
              <th scope="col">종목코드</th>
              <th scope="col">만기</th>
              {overseas ? (
                <th scope="col">호가단위</th>
              ) : (
                <>
                  <th scope="col">잔존</th>
                  <th scope="col">거래승수</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              /* 행 전체가 눌립니다. 값이 없어 행 안에 따로 누를 것이 없습니다. */
              <tr
                key={row.code}
                className="row-click"
                onClick={() => onOpen(row)}
              >
                {/* 이름이 칸보다 길면 잘립니다 — 마스터 원문을 그대로 세우는
                    스프레드에는 서른 자가 넘는 이름이 있습니다. 잘린 이름에
                    닿을 길을 남겨 둡니다. */}
                <td className="col-text" title={row.label}>
                  <span className="catalog-name">{row.label}</span>
                  {row.frontMonth && <span className="badge badge-brand">최근 만기</span>}
                </td>
                {/* 옵션의 종목코드는 행사가까지 정해져야 나옵니다. 「없다」가 아니라
                    「하나 더 고르면 생긴다」라서 「—」를 쓰지 않고 무엇을 골라야
                    하는지를 적습니다 — 행 전체가 눌려 그 자리에서 체인이 열립니다. */}
                <td className={kind === 'option' ? 'col-text' : 'col-text num'}>
                  {kind === 'option' ? (
                    <span className="catalog-pending">행사가 선택</span>
                  ) : (
                    row.code
                  )}
                </td>
                {/* 스프레드는 만기가 둘입니다. 한 값만 적으면 종목명이 말하는 두
                    만기와 어긋나 보이고, 그 하나는 이미 종목명 안에 있어 새로
                    알려주는 것도 없습니다. */}
                <td className="col-text num">{kind === 'spread' ? '—' : expiryText(row.expiry)}</td>
                {/* 호가단위는 **그 값이 요구하는 자리 수**로 적습니다. 값 쪽 자리
                    수를 쓰면 호가가 값보다 잘게 움직이는 상품에서 「0.00000」이
                    되어 0으로 읽힙니다. */}
                {overseas ? (
                  <td style={fracWidth(row.tickDecimals ?? decimals)}>
                    {row.tickSize === null ? (
                      '—'
                    ) : (
                      <Num value={row.tickSize} decimals={row.tickDecimals ?? decimals} />
                    )}
                  </td>
                ) : (
                  <>
                    {/* 잔존일수는 거래소가 주는 값입니다. 안 오면 세지 않고 비웁니다 —
                        만기에서 세면 휴장일이 빠져 거래소 값과 어긋납니다. */}
                    <td>{row.daysLeft === null ? '—' : `D-${row.daysLeft}`}</td>
                    <td>{row.multiplier === null ? '—' : <Count value={row.multiplier} />}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
