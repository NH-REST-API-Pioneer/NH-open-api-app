import type { CSSProperties } from 'react'
import type { FlashWay } from '../../lib/flash'
import { PAPER_NIGHT_PRICE_TEXT } from '../../data/quotes'
import { Num, toneOf } from '../../lib/number'
import type { MarketContext, ProductKind, Quote } from '../../lib/types'

/** 줄 A — 종목 이름과 만기·콜풋·행사가 고르개, 종목코드. */
export function renderHeaderName({
  quote,
  legsLine,
  months,
  onMonthChange,
  kind,
  optionSide,
  onOptionSideChange,
  strike,
  strikes,
  strikeDecimals,
  onStrikeChange,
  pending,
}: {
  quote: Quote
  legsLine: string | null
  months: { code: string; label: string }[]
  onMonthChange: (code: string) => void
  kind: ProductKind
  optionSide: 'call' | 'put' | null
  onOptionSideChange: (side: 'call' | 'put') => void
  strike: number | null
  strikes: number[]
  strikeDecimals: number
  onStrikeChange: (strike: number) => void
  pending: boolean
}) {
  return (
        <div className="hd-name">
          {/* 제목과 부제는 한 칸입니다. 부제가 없는 종목에서는 제목 한 줄이라
              지금까지와 같은 높이로 섭니다. */}
          <div className="hd-title">
            <h1 className="t-screen" title={quote.productName}>
              {quote.productName}
            </h1>
            {/* 두 다리를 한국어로 적는 자리. 제목이 마스터 원문(「코스피200 SP
                2612-2703」)이라 만기가 코드에 가까운 표기로만 서는데, 그 표기를
                읽을 수 있는 사람만 어느 두 달인지 알게 됩니다. */}
            {legsLine !== null && <p className="hd-legs">{legsLine}</p>}
          </div>

          {/* 만기를 바꾸면 다른 종목이라 주문 폼이 리셋됩니다.
              잔존일을 목록 안에 둡니다. 닫힌 셀렉터가 고른 만기의 잔존일을
              그대로 보여주므로 늘 보이고, 목록을 열면 만기끼리 견줄 수도
              있습니다 — 옆에 또 적으면 같은 값이 한 줄에 두 번 섭니다. */}
          <select
            className="hd-month"
            value={quote.code}
            aria-label="만기"
            onChange={(event) => onMonthChange(event.target.value)}
          >
            {months.map((item) => (
              <option key={item.code} value={item.code}>
                {item.label}
              </option>
            ))}
          </select>

          {kind === 'option' && (
            <>
              {/* 아직 안 고른 축은 **안 골랐다고 말합니다.** 목록의 첫 값을
                  그리면 고른 적 없는 콜과 행사가가 골라진 것처럼 보이고, 그
                  종목이 주문 폼에 실립니다. 고르고 나면 이 항목은 사라집니다 —
                  되돌아갈 자리가 아니라 아직 안 지난 자리입니다. */}
              <select
                className="hd-month"
                value={optionSide ?? ''}
                aria-label="콜 / 풋"
                onChange={(event) => onOptionSideChange(event.target.value as 'call' | 'put')}
              >
                {optionSide === null && (
                  <option value="" disabled>
                    콜/풋 선택
                  </option>
                )}
                <option value="call">콜</option>
                <option value="put">풋</option>
              </select>

              <select
                className="hd-month"
                value={strike ?? ''}
                aria-label="행사가"
                onChange={(event) => onStrikeChange(Number(event.target.value))}
              >
                {strike === null && (
                  <option value="" disabled>
                    행사가 선택
                  </option>
                )}
                {strikes.map((value) => (
                  <option key={value} value={value}>
                    {value.toFixed(strikeDecimals)}
                  </option>
                ))}
              </select>
            </>
          )}

          {/* 콜/풋과 행사가가 다 정해지기 전에는 종목코드가 아직 없습니다.
              **값 칸이라 값이 없을 때의 표시(「—」)를 씁니다** — 무엇이 남았는지는
              바로 왼쪽 두 셀렉트가 「콜/풋 선택」·「행사가 선택」으로 이미 말하고
              있어, 여기에 같은 말을 또 세우면 한 줄에 같은 글자가 나란히 섭니다.
              값이 아니라 빈자리라 한 급 낮추고 흐림색을 씁니다. */}
          <span className="hd-code">
            {pending ? <span className="hd-code-pending">—</span> : quote.code}
          </span>

        </div>
  )
}

/** 줄 B — 현재가와 전일 대비, 값의 시각, 못 받은 까닭, 거래시간. */
export function renderHeaderQuote({
  valuesHidden,
  valuesLoading,
  flash,
  price,
  quote,
  d,
  fraction,
  context,
  since,
  failure,
  onRetry,
  onOpenSettings,
  hours,
}: {
  valuesHidden: boolean
  valuesLoading: boolean
  flash: FlashWay | null
  price: CSSProperties
  quote: Quote
  d: number
  fraction: number | null | undefined
  context: MarketContext
  since: string
  failure: { kind: 'retry' | 'rejected' | 'paper' | 'empty' | 'unasked'; withValues: boolean; text?: string } | null | undefined
  onRetry: (() => void) | undefined
  onOpenSettings: (() => void) | undefined
  hours: string
}) {
  return (
        <div className="hd-quote">
          {/* 못 받았으면 값이 서던 자리가 그 사실을 말합니다. 헤더에서 가장 큰
              값이 현재가라, 없어진 것이 여기서 가장 먼저 보입니다. 값을 아직
              한 번도 못 받았으면 값 자리를 이 문구가 대신하고, 받아 둔 값이
              있으면 값 뒤에 붙습니다 — 그때 값은 틀린 값이 아니라 낡은
              값입니다. */}
          {valuesHidden ? (
            valuesLoading ? <span className="hd-price-wait" aria-hidden="true" /> : null
          ) : (
            <>
              <span className={`hd-price t-price${flash ? ` is-${flash}` : ''}`} style={price}>
                {quote.last !== null && <Num value={quote.last} decimals={d} fraction={fraction} />}
              </span>
              <span className="hd-dot">·</span>
              {/* 국내 야간의 등락은 **그 야간이 딸린 거래일의 주간 정산가**에서 잽니다.
                  「전일보다」로 적으면 어제 값에서 잰 것으로 읽힙니다. 세션은 서버
                  답(`context`)입니다. */}
              <span className="hd-since">
                {context === 'domestic-night' ? '주간 정산가보다' : '전일보다'}
              </span>
              {/* 등락이 안 온 칸은 빈 채입니다 — 0 으로 적으면 「안 움직였다」가 되고,
                  「—」는 이 시장에 원래 없는 값의 말입니다. 「전일보다」 라벨만 남습니다. */}
              <span className="hd-change" style={price}>
                {quote.change !== null && (
                  <Num value={quote.change} decimals={d} fraction={fraction} signed toned />
                )}
              </span>
              <span className={`hd-pct ${quote.change === null ? '' : toneOf(quote.change)}`}>
                {quote.changePct !== null &&
                  `(${quote.changePct > 0 ? '+' : quote.changePct < 0 ? '−' : ''}${Math.abs(quote.changePct).toFixed(2)}%)`}
              </span>
              <span className="hd-dot">·</span>
            </>
          )}
          {/* 값이 언제 것인가. 값 바로 뒤에 붙습니다 — 이 시각이 말하는 것은
              화면이 아니라 그 숫자입니다. 값이 아예 없는 자리에는 안 답니다.
              그때는 「없다」가 먼저입니다. */}
          {!valuesHidden && since && (
            <>
              <span className="hd-at">{since} 기준</span>
              <span className="hd-dot">·</span>
            </>
          )}
          {failure && (
            <span className="hd-failed">
              {/* 「못 받았다」와 「아직 없다」는 사용자가 할 일이 다릅니다 —
                  앞은 다시 불러 볼 만하고 뒤는 거래가 생겨야 값이 섭니다. */}
              <span className="hd-failed-text">
                {failure.kind === 'unasked'
                  ? /* **이 문장은 화면에 한 번만 섭니다.** 화면 전체가 같은 사정일 때는
                       카드마다 제 문장을 세우면 다른 일이 여럿 난 줄로 읽힙니다 —
                       한 번 말하고 나머지 카드는 짧은 표지만 답니다. */
                    `${context === 'overseas' ? '해외' : '국내'} 인증 정보가 없어 시세를 받지 않습니다`
                  : failure.kind === 'empty'
                    ? '아직 시세가 없습니다'
                    : failure.kind === 'paper'
                      ? /* 까닭이 정해진 답이라 그대로 말합니다. 다시 받는 단추도
                           경고색도 없습니다 — 사용자가 고칠 일이 아닙니다. */
                        PAPER_NIGHT_PRICE_TEXT
                      : failure.text || '시세를 받지 못했습니다'}
              </span>
              {/* 거절은 눌러도 같은 답이 옵니다. 그때 다시 받는 길은 이 줄의
                  만기·콜풋·행사가를 바꾸는 것이고, 그 컨트롤이 바로 옆에
                  있습니다. */}
              {failure.kind === 'retry' && (
                <button type="button" className="btn btn-quiet" onClick={onRetry}>
                  다시
                </button>
              )}
              {failure.kind === 'unasked' && onOpenSettings && (
                <button type="button" className="btn btn-quiet" onClick={onOpenSettings}>
                  설정 열기
                </button>
              )}
            </span>
          )}
          {failure && <span className="hd-dot">·</span>}
          {/* 상자에 넣지 않습니다. 이 줄의 상자는 만기와 선물·옵션 둘 다
              누르는 것이라, 안 눌리는 상자를 하나 더 놓으면 눌러 보게 됩니다. */}
          <span className="hd-hours">{hours}</span>
        </div>
  )
}
