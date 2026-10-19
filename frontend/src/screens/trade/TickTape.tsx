import { PENDING_TEXT } from '../../data/instruments'
import { Count, Num, fracWidth, signSpace } from '../../lib/number'
import type { Quote } from '../../lib/types'

/* 시세체결.
 *
 * 체결 틱은 웹소켓으로만 옵니다. 화면에 들어오는 순간에는 비어 있고 연결한
 * 뒤부터 쌓이므로, 머리에 그 시각이 함께 서야 「고장」이 아니라 「그때부터 아직
 * 없음」으로 읽힙니다. 세 줄만 보일 때 그 시각이 없으면 「오늘 세 번 거래됐다」로
 * 읽게 됩니다.
 *
 * **다만 담는 수에 상한이 있어, 다 차면 그 시각은 더 이상 참이 아닙니다** —
 * 앞쪽을 버린 뒤라 카드가 담고 있는 구간이 붙은 시각보다 짧습니다. 그래서 머리에
 * 서는 시각은 **담은 수가 상한에 못 미칠 때만** 붙은 시각이고, 다 찬 뒤에는
 * 담고 있는 가장 오래된 체결의 시각입니다(`TradeScreen` 의 `tapeSince`).
 *
 * 호가와 같은 가격 축을 위아래로 읽는 카드라 기본 배치에서 호가와 한 슬롯에
 * 섭니다. 그래도 **카드는 따로**입니다 — 묶어 두면 시세체결을 끄는 길이 호가를
 * 끄는 길과 같아지고, 좁은 자리에서 자리를 내주는 쪽이 늘 시세체결로 정해져
 * 있어 사용자가 고를 수 없습니다.
 */

interface Props {
  quote: Quote
  /** 실시간 체결 틱. 연결한 뒤부터 쌓입니다.
   *
   *  **방향(`side`)이 없을 수 있습니다.** 실시간이 보내는 체결구분은 그 글자가
   *  무엇을 뜻하는지 명세에 없어(국내 `1`·`2`, 해외 `+`·`-`) 백엔드가 방향을
   *  만들지 않고 받은 값을 그대로 올립니다. 없는 것을 짐작해 칠하면 **틀려도
   *  화면에서 표가 안 납니다** — 그래서 없으면 색을 안 씁니다. */
  ticks: readonly { time: string; price: number; quantity: number; side?: 'buy' | 'sell' }[]
  /** 지금 이 종목의 체결을 **실제로 듣고 있는지.** 빈 목록에 「아직 없다」를
   *  세울 수 있는 것은 듣고 있을 때뿐입니다 — 안 듣는 동안에는 없는 것이
   *  아니라 모르는 것입니다. */
  listening?: boolean
  /** 서버가 이 종목의 실시간 등록을 거절했는지(시세 사용 신청 전인 거래소). 그때는
   *  기다려도 오지 않으므로 「연결되면 쌓입니다」 대신 오지 않는다고 적습니다.
   *  까닭은 카드 머리의 꼬리표가 말합니다. */
  refused?: boolean
  /** 이 시장에 **조회 경로가 아직 없는지.** 그때는 이 카드만의 사정이 아니라
   *  화면 전체가 같은 사정이라, 카드는 짧은 표지만 답니다 — 문장은 헤더가
   *  한 번 말합니다. */
  unasked?: boolean
  /** 아직 축(행사가)을 안 고른 옵션 자리인지. 종목이 정해지지 않아 들을 체결이
   *  없습니다. 값 자리에는 **짧은 표지 하나**(「행사가 선택」)만 섭니다 — 헤더의
   *  코드 칸·주문 폼과 같은 낱말입니다. 통째로 비우면 고장으로 읽히고, 「연결되면
   *  쌓입니다」는 연결의 문제가 아니라 종목이 없는 것이라 틀린 말입니다. 문장은
   *  주문 카드가 「행사가를 고르세요」로 한 번만 합니다. */
  pending?: boolean
}

export function TickTape({
  quote,
  ticks,
  listening = false,
  refused = false,
  unasked = false,
  pending = false,
}: Props) {
  /* 음수가 설 수 있는 종목(스프레드)은 부호 한 칸을 미리 잡습니다. */
  const price = fracWidth(quote.decimals, signSpace(quote.kind), quote.fraction)

  return (
    /* 이름과 「언제부터」는 카드 머리 띠가 답니다. 여기서 한 번 더 붙이면 같은
       이름의 영역이 둘로 겹쳐, 보조 기술이 「시세체결 안의 시세체결」로 읽습니다. */
    <div className="tick-tape">
      {pending ? (
        <p className="ticks-empty">{PENDING_TEXT[quote.pendingAxis ?? 'strike'].pick}</p>
      ) : ticks.length === 0 ? (
        /* **「아직 없다」는 듣고 있을 때만 할 수 있는 말입니다.** 안 듣는 동안
           그 문구가 서면 「그때부터 듣는데 아무것도 안 왔다」가 되는데, 사실은
           안 듣고 있어서 모르는 것입니다.
           그렇다고 카드를 통째로 비우지도 않습니다 — 빈칸은 고장으로 읽힙니다.
           **까닭은 안 적습니다.** 왜 안 오는지는 상단이 이미 말하고 있고, 카드가
           같은 사실을 다른 말로 한 번 더 적으면 두 가지 일로 읽힙니다. 여기서는
           **이 자리에 무엇이 올 것인지**만 말합니다. */
        <p className="ticks-empty">
          {unasked
            ? '조회 전'
            : refused
              ? '실시간 시세가 오지 않습니다'
              : listening
              ? '아직 체결이 없습니다'
              : '시세가 연결되면 체결이 쌓입니다'}
        </p>
      ) : (
        <div className="ticks-scroll">
          {/* **열쇠는 자리 번호입니다.** 체결에는 화면이 아는 고유 번호가 없고,
              시각·가격·수량이 모두 같은 체결이 실제로 여러 건 옵니다(같은 초에
              같은 값으로 여러 번 체결됩니다). 값으로 열쇠를 지으면 그 겹치는
              줄들이 한 줄로 뭉쳐, **새 체결이 와도 옛 줄이 안 걷히고 목록이
              한없이 길어집니다.** 이 목록은 위에서부터 「몇 번째로 최근인가」라
              자리로 세는 것이 뜻에도 맞습니다. */}
          {ticks.map((t, index) => (
            <div key={index} className="tick-row">
              <span className="tick-time num">{t.time}</span>
              <span
                className={`tick-price ${t.side === 'buy' ? 'up' : t.side === 'sell' ? 'down' : ''}`.trim()}
                style={price}
              >
                <Num value={t.price} decimals={quote.decimals} fraction={quote.fraction} />
              </span>
              <span className="tick-qty">
                <Count value={t.quantity} />
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
