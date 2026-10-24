import type { CSSProperties } from 'react'

import { PENDING_TEXT } from '../../data/instruments'
import { useFlash } from '../../lib/flash'
import { Count, Num, fracWidth, signSpace } from '../../lib/number'
import type { BookLevel, Quote } from '../../lib/types'

/* 호가창.
 *
 * 주문 폼 바로 옆에 붙습니다 — 호가를 눌러 주문 가격을 넣는 것이 이 화면의
 * 기본 동작이라 사이에 다른 것이 끼면 손이 끊깁니다.
 *
 * 매도는 위, 매수는 아래입니다. 방향색과 함께 위아래 위치가 두 번째 단서입니다.
 *
 * **보이는 것은 위아래 다섯 단계씩입니다.** 응답은 열 단계씩 오지만 사다리를
 * 짧게 두어 그 아래 시세체결이 같은 화면에 섭니다 — 둘은 같은 가격 축을
 * 위아래로 읽는 짝이라, 한쪽을 보려고 다른 쪽을 스크롤해야 하면 짝이 아닙니다.
 * 먼 지정가는 사다리가 아니라 주문 폼의 숫자 칸으로 넣습니다.
 */

interface Props {
  quote: Quote
  /** 매도 호가. 먼 값부터 옵니다 — 가까운 다섯만 보입니다. */
  asks: BookLevel[]
  /** 매수 호가. 가까운 값부터 옵니다 — 가까운 다섯만 보입니다. */
  bids: BookLevel[]
  /** 지금 주문 폼에 들어가 있는 가격. 같은 단계에 표시가 붙습니다. */
  selectedPrice: number | null
  /** 두 차트 중 이 호가가 어느 종목인지를 머리에 답니다. 한 차트면 안 답니다. */
  subject?: boolean
  /** 호가를 못 받았으면 그 사실. 사다리 대신 이 말이 섭니다 — 빈 사다리는
   *  「호가가 없다」로 읽혀, 못 받은 것과 원래 없는 것이 한 얼굴이 됩니다. */
  failure?: { kind: 'retry' | 'rejected' | 'empty' | 'unasked'; withValues: boolean } | null
  /** 다시 받기. 다시 불러 볼 만한 실패에서만 단추가 섭니다. */
  onRetry?: () => void
  /** 이 종목의 현재가를 아는지. 사다리 가운데 줄이 현재가를 적는데, 모르는 값을
   *  적으면 **사다리는 진짜 호가인데 그 사이의 현재가만 지어낸 값**이 됩니다. */
  priceKnown?: boolean
  /** 아직 축(행사가)을 안 고른 옵션 자리인지. 종목이 정해지지 않아 물을 호가가
   *  없습니다. **사다리 틀만 남기고 값을 비우고**, 「현재가」 띠의 값 자리에 짧은
   *  표지 하나(「행사가 선택」)가 섭니다 — 헤더가 라벨만 남기고 코드 칸에 같은
   *  표지를 세우는 것과 같은 결입니다. 단계에는 글자를 두지 않습니다: 단계는
   *  구조지 값 칸이 아니라, 거기 글자가 서면 한 단계가 값처럼 읽힙니다. 기초
   *  선물의 사다리를 대신 세우지 않습니다: 눌러 주문가격에 넣는 자리라, 다른
   *  종목의 값이 서면 그 값이 주문에 실립니다. 문장은 주문 카드가 「행사가를
   *  고르세요」로 한 번만 합니다. */
  pending?: boolean
  /** 국내 예상체결가. 단일가(개장·마감 동시호가) 동안만 값이 옵니다. 값이 있으면
   *  가운데 띠가 현재가 대신 이 값을 답니다 — 줄을 더하지 않고 **갈아 끼워** 카드
   *  높이가 그대로입니다. 화면이 세션을 판단하지 않고 값의 유무만 봅니다. */
  expectedPrice?: number | null
  onPickPrice: (price: number) => void
}

/** 위아래로 보이는 단계 수. 사다리는 이 값 × 2 + 현재가 줄입니다. */
export const BOOK_LEVELS = 5

/* 사다리 한 줄.
 *
 * **줄마다 따로 세웁니다** — 이 줄의 값이 바뀌었는지를 줄이 스스로 기억해야,
 * 실시간으로 사다리가 통째로 다시 올 때 **바뀐 줄만** 비출 수 있습니다.
 * 한곳에서 그리면 열 줄이 함께 깜빡여, 무엇이 움직였는지가 도로 묻힙니다.
 */
function BookRow({
  level,
  side,
  code,
  selected,
  maxQty,
  decimals,
  fraction,
  priceStyle,
  onPick,
}: {
  level: BookLevel
  side: 'ask' | 'bid'
  /** 이 사다리가 어느 종목의 것인가. 종목이 바뀌면 값이 움직인 것이 아니라
   *  보는 대상이 바뀐 것이라, 그때는 안 비춥니다. */
  code: string
  selected: boolean
  maxQty: number
  decimals: number
  fraction?: number | null
  priceStyle: CSSProperties
  onPick: (price: number) => void
}) {
  /* 이 자리의 값이 움직이면 가격 칸을 잠깐 비춥니다. 사다리가 한 단계 밀리면
     같은 자리에 다른 단계가 서는데, 값만 조용히 갈리면 밀린 것이 안 보입니다. */
  const flash = useFlash(level.price, code)

  return (
    <button
      type="button"
      className={`book-row book-${side}`}
      aria-pressed={selected}
      onClick={() => onPick(level.price)}
    >
      <span className="book-qty">
        <span
          className="book-bar"
          style={{ width: `${(level.quantity / maxQty) * 100}%` }}
          aria-hidden="true"
        />
        <span className="book-qty-value">
          <Count value={level.quantity} />
        </span>
      </span>
      <span className={`book-price${flash ? ` is-${flash}` : ''}`} style={priceStyle}>
        <Num value={level.price} decimals={decimals} fraction={fraction} />
      </span>
    </button>
  )
}

export function OrderBook({
  quote,
  asks,
  bids,
  selectedPrice,
  subject = false,
  failure,
  onRetry,
  priceKnown = true,
  pending = false,
  expectedPrice = null,
  onPickPrice,
}: Props) {
  const d = quote.decimals
  /* 예상체결가가 바뀌면 사다리 값 칸과 같은 규칙으로 잠깐 비춥니다 — 직전
     예상체결가와 견줍니다. 잔량은 안 비춥니다. */
  const expectedFlash = useFlash(expectedPrice, quote.code)
  /* 분수로 부르는 품목이면 호가도 분수로 적습니다 — 헤더가 `102'17.5` 인데
     사다리만 소수면 같은 값을 두 말로 읽게 됩니다. */
  const fraction = quote.fraction
  /* 음수가 설 수 있는 종목(스프레드)은 부호 한 칸을 미리 잡습니다. */
  const price = fracWidth(d, signSpace(quote.kind), fraction)

  /* 매도는 먼 값부터 오므로 뒤에서, 매수는 가까운 값부터 오므로 앞에서 자릅니다 —
     양쪽 다 **현재가에 가까운 다섯**이 남습니다. */
  const shownAsks = asks.slice(-BOOK_LEVELS)
  const shownBids = bids.slice(0, BOOK_LEVELS)

  /* 잔량 막대의 눈금은 **보이는 열 줄 중 가장 큰 잔량**입니다.
     응답에는 오지만 화면에 없는 단계를 눈금에 넣으면, 같은 종목인데 배치에
     따라 막대 길이가 달라지고 그 기준이 화면 어디에도 없습니다. 보이는 것만
     세면 가장 긴 막대가 늘 화면 안에 있어, 눈금을 눈으로 확인할 수 있습니다. */
  const maxQty = Math.max(
    ...shownAsks.map((l) => l.quantity),
    ...shownBids.map((l) => l.quantity),
    1,
  )

  /* **열쇠는 자리 번호입니다.** 값으로 열쇠를 삼으면, 같은 값이 두 단계에 서는
     종목에서 열쇠가 겹쳐 종목을 바꿔도 옛 줄이 남습니다. 사다리의 한 줄은 값이
     아니라 「위에서 몇 번째 단계」라 자리로 세는 것이 뜻에도 맞습니다. */
  const row = (level: BookLevel, side: 'ask' | 'bid', index: number) => (
    <BookRow
      key={`${side}-${index}`}
      level={level}
      side={side}
      code={quote.code}
      selected={selectedPrice === level.price}
      maxQty={maxQty}
      decimals={d}
      fraction={fraction}
      priceStyle={price}
      onPick={onPickPrice}
    />
  )
  /* 값 없는 단계. 자리만 지켜 사다리의 키가 그대로라, 축을 고르는 순간 카드가
     늘어나며 아래 카드를 밀지 않습니다. 단추가 아닙니다 — 누를 값이 없습니다. */
  const blank = (side: 'ask' | 'bid') =>
    Array.from({ length: BOOK_LEVELS }, (_, index) => (
      <div key={`${side}-${index}`} className={`book-row book-${side} is-blank`} aria-hidden="true" />
    ))

  return (
    /* 이름은 카드 머리 띠가 답니다. 여기서 한 번 더 붙이면 같은 이름의 영역이
       둘로 겹쳐, 보조 기술이 「호가 안의 호가」로 읽습니다.

       **줄이는 단계가 없습니다.** 다섯씩으로 못 박혀 있어 더 줄일 것이 없고,
       카드가 제 바닥보다 낮아지면 그 열이 스크롤합니다 — 뭉갠 사다리는 단계가
       잘린 채로 값처럼 보입니다. */
    <section className="order-book">
      {/* 차트가 둘일 때 이 호가가 어느 종목인지. 차트의 주문 대상 배지와 같은
          초록 세로 바라, 바를 따라가면 같은 종목입니다. */}
      {subject && (
        <div className="subject-head" title={quote.name}>
          {quote.name}
        </div>
      )}

      <div className="book-head">
        <span className="t-label">잔량</span>
        <span className="t-label">호가</span>
      </div>

      {/* 못 받았으면 사다리 자리를 이 한 줄이 대신합니다. 카드 머리가 이미
          무엇을 담는 자리인지 말하고 있어 문구를 길게 쓰지 않습니다 — 같은
          문장이 카드마다 서면 그 길이가 그대로 소음이 됩니다. */}
      {failure && (
        <div className="book-failed">
          <span>
            {failure.kind === 'unasked'
              ? '조회 전'
              : failure.kind === 'empty'
                ? '아직 호가가 없습니다'
                : '받지 못했습니다'}
          </span>
          {/* 거절은 눌러도 같은 답이 옵니다. 그때 다시 부를 길은 종목을 바꾸는
              것이고 그 컨트롤은 헤더에 있습니다. */}
          {failure.kind === 'retry' && (
            <button type="button" className="btn btn-quiet" onClick={onRetry}>
              다시
            </button>
          )}
        </div>
      )}

      {!failure && (
        <div className="book-scroll">
        <div className="book-side book-side-ask">
          {pending ? blank('ask') : shownAsks.map((level, index) => row(level, 'ask', index))}
        </div>

        {/* 매도와 매수 사이에 현재가를 끼워 두 구간을 가릅니다. 단일가 동안은
            서버가 준 예상체결가가 그 자리에 대신 섭니다 — 그때 사다리의 축은
            체결될 값이지 마지막 체결가가 아닙니다. 대비 칸은 없습니다. */}
        <div className="book-last">
          <span className="t-label">{expectedPrice !== null ? '예상체결가' : '현재가'}</span>
          {/* **이 줄은 값 열이 아닙니다.** 사다리의 값은 오른쪽 끝에 서고 이 줄은
              이름표와 두 값이 나란히 서는 띠라, 세로로 맞출 것이 없습니다. 그런데
              소수부 칸을 자릿수만큼 미리 잡아 두면 그 빈칸이 이름표를 밀어,
              자리 수가 많은 종목에서 「현재가」가 세로로 쪼개집니다. */}
          {/* 현재가를 모르면 이 줄은 이름표만 남습니다. 사다리는 받은 값이라
              그대로 서고, 가운데 줄만 빕니다. 축을 안 고른 옵션 자리는 값 칸에
              표지가 섭니다. */}
          {pending && (
            <span className="book-pending">{PENDING_TEXT[quote.pendingAxis ?? 'strike'].pick}</span>
          )}
          {expectedPrice !== null ? (
            <span className={`book-expected${expectedFlash ? ` is-${expectedFlash}` : ''}`}>
              <Num value={expectedPrice} decimals={d} fraction={fraction} />
            </span>
          ) : (
            priceKnown && (
              <>
                <span>
                  {quote.last !== null && (
                    <Num value={quote.last} decimals={d} fraction={fraction} />
                  )}
                </span>
                <span>
                  {quote.change !== null && (
                    <Num value={quote.change} decimals={d} fraction={fraction} signed toned />
                  )}
                </span>
              </>
            )
          )}
        </div>

        <div className="book-side book-side-bid">
          {pending ? blank('bid') : shownBids.map((level, index) => row(level, 'bid', index))}
        </div>
        </div>
      )}
    </section>
  )
}
