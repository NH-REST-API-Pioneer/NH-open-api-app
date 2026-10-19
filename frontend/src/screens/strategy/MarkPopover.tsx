import { kstClock } from '../../lib/kst'
import { MINUS, Num, moneyIn, toneOf } from '../../lib/number'
import { reasonWord } from '../../data/strategyRuns'
import { CLOCK_ID, PICK_OPERANDS, PRICE_AXIS_IDS, operandWord } from '../../data/strategyRules'
import { parseOperandKey } from '../../data/indicatorOperands'
import { MARK_KIND_LABEL, type TradeMark } from '../trade/chartMarks'

/* 차트 마커를 누르면 뜨는 상세.
 *
 * **지금 이것을 쓰는 화면은 검증 하나입니다** — 차트에 표지를 세우는 자리가
 * 거기뿐입니다. 그래도 화면 밖에 두는 것은, 마커가 말하는 것(무엇이 언제
 * 얼마에)이 어느 화면에서나 같아서입니다. 가상 장부인지 계좌인지도 마커가
 * 들고 다니므로 화면이 따로 적을 것이 없습니다.
 */

/** 그 종목의 자릿수로 적는 값 — 가격과 가격에서 나온 선들, 호가 가격. */
const PRICE_LIKE = PRICE_AXIS_IDS
/** 소수 둘로 적는 지표 — 오실레이터와 변동폭. */
const TWO_PLACES = ['rsi', 'atr', 'macdLine', 'macdSignal', 'macdHist', 'stochK', 'stochD']
/** 천 단위 정수로 적는 값 — 거래량·잔량·보유 수량·봉 순서. */
const WHOLE = ['volume', 'bid1Qty', 'ask1Qty', 'positionQty', 'barOrder']

const twoDigits = (value: number) => String(value).padStart(2, '0')

/** 봉 시작 시각(분)을 「HH:MM」으로. **야간은 자정을 넘어 이어 센 값**(하루 1440 을
 *  넘음)이 오므로 하루를 빼서 새벽 시각으로 적습니다 — 「25:30」은 「01:30」입니다.
 *  24 를 넘는 시각은 화면 어디에도 세우지 않습니다. */
function clockText(minutes: number): string {
  const within = ((Math.round(minutes) % 1440) + 1440) % 1440
  return `${twoDigits(Math.floor(within / 60))}:${twoDigits(within % 60)}`
}

/** 봉의 시작 시각(ms)을 한국시각 「HH:MM」으로. */
function barTimeText(time: number | null): string {
  if (time === null || !Number.isFinite(time)) return '—'
  return kstClock(time)
}

/** 돈을 적는 말. 전략 화면의 다른 금액과 같은 규칙입니다(`moneyIn` — 통화를
 *  모르면 「—」). */
function moneyText(value: number, currency: string | undefined): string {
  return moneyIn(value, currency)
}

/** 당시 지표 한 칸의 값. 준비 전이면 「—」입니다. */
function SnapValue({ id, value, mark }: { id: string; value: number | null; mark: TradeMark }) {
  if (value === null || !Number.isFinite(value)) return <>—</>
  if (id === CLOCK_ID) return <>{clockText(value)}</>
  if (PRICE_LIKE.includes(id)) return <Num value={value} decimals={mark.decimals} />
  if (TWO_PLACES.includes(id)) {
    const text = Math.abs(value).toFixed(2)
    return <>{value < 0 && Number(text) !== 0 ? `${MINUS}${text}` : text}</>
  }
  if (WHOLE.includes(id)) return <>{Math.round(value).toLocaleString('ko-KR')}</>
  if (id === 'openPl') return <span className={toneOf(value) || undefined}>{moneyText(value, mark.currency)}</span>
  return <>{String(value)}</>
}

export interface MarkPick {
  mark: TradeMark
  left: number
  top: number
}

export function MarkPopover({ pick, onClose }: { pick: MarkPick; onClose: () => void }) {
  const { mark } = pick
  const words = (mark.reasons ?? []).map(reasonWord).filter((word) => word !== '')
  const reason = [...new Set(words)].join(' · ')
  /* 당시 지표 줄 — 서버가 준 이름들을 **편집기 목록 차례**로 세웁니다(서버의
     칸 차례에 기대지 않습니다). 목록에 없는 이름은 세우지 않습니다. */
  const values = mark.snapshot?.values ?? {}
  /* 칸 이름은 **값 열의 이름**입니다 — 새 체결은 「ema(20)」 꼴, 매개변수가 생기기
     전에 쌓인 체결은 「ema20」 꼴입니다. 둘 다 `{지표, 매개변수}`로 되읽어 편집기와
     같은 이름(「EMA(20)」)으로 세웁니다. 차례는 편집기 목록의 차례이고, 같은 지표는
     매개변수가 작은 것부터입니다(EMA(5) → EMA(20)). */
  const order = (id: string) => {
    const at = PICK_OPERANDS.findIndex((item) => item.id === id)
    return at === -1 ? PICK_OPERANDS.length : at
  }
  const rows = Object.keys(values)
    .map((key) => {
      const parsed = parseOperandKey(key)
      return { key, id: parsed.id, word: operandWord(parsed.id, parsed.params), value: values[key] ?? null }
    })
    .filter((row): row is { key: string; id: string; word: string; value: number | null } => row.word !== null)
    .sort((a, b) => order(a.id) - order(b.id) || a.key.localeCompare(b.key, 'en', { numeric: true }))
  return (
    <div className="mark-pop" style={{ left: pick.left, top: pick.top }}>
      <div className="mark-pop-head">
        <b>
          {mark.side === 'buy' ? '매수' : '매도'} {mark.intent}
        </b>
        <button type="button" className="btn btn-quiet mark-pop-close" aria-label="닫기" onClick={onClose}>
          ✕
        </button>
      </div>
      {/* **왜 여기서 났나**가 마커를 누르는 물음이라 머리 바로 아래입니다. 묶인
          표지에서 까닭이 갈리면 서로 다른 낱말을 이어 한 줄로 적습니다. 낱말이
          없으면(모르는 코드) 줄을 안 세웁니다. */}
      {reason !== '' && (
        <p className="mark-pop-line mark-pop-reason" title={reason}>
          {reason}
        </p>
      )}
      <p className="mark-pop-line">
        {mark.strategy} {mark.version}
      </p>
      <p className="mark-pop-line">
        {mark.virtual ? '가상' : '계좌'} {MARK_KIND_LABEL[mark.kind]} · {mark.at}
      </p>
      {/* **묶인 표지의 가격은 수량 가중평균**입니다(`mergeMarks`). 그 값을 그냥
          적으면 일어나지 않은 거래 하나로 읽히므로, 묶였을 때만 「평균」을 답니다 —
          계좌 화면의 「평균가」와 같은 어법입니다. 한 건이면 실제로 난 값이라
          그대로 적습니다. */}
      <p className="mark-pop-line">
        {mark.count > 1 && '평균 '}
        <Num value={mark.price} decimals={mark.decimals} /> · {mark.qty}계약
        {mark.count > 1 && ` · ${mark.count}건 묶음`}
      </p>
      {/* 그 체결의 수수료(묶이면 합). **계약당 설정값으로 센 값**이라 가상이든
          모의 계좌든 같은 말입니다 — 계좌가 실제로 물린 값이 아닙니다. 칸이 없는
          옛 기록은 줄을 세우지 않습니다. */}
      {mark.fee !== undefined && (
        <p className="mark-pop-line">수수료 {moneyText(mark.fee, mark.currency)} · 계약당 설정값으로 셈</p>
      )}
      {/* 주문을 낸 순간의 지표. 전략 엔진이 내지 않은 주문(`null`)과 칸이 없는 옛
          기록은 절 전체를 세우지 않습니다. 차례는 편집기 목록의 차례이고, 줄이
          많으면 이 표만 안에서 구릅니다. 묶인 표지는 가장 이른 체결의 것입니다. */}
      {rows.length > 0 && mark.snapshot && (
        <div className="mark-pop-snap">
          <p className="mark-pop-snap-head">
            당시 지표 · {mark.count > 1 ? '첫 체결 ' : ''}
            {barTimeText(mark.snapshot.barTime)} 봉
            {/* 틱 판정이면 아직 안 끝난 봉의 값입니다 — 그 봉의 마감 값과 다를 수 있습니다. */}
            {mark.snapshot.partialBar === true && ' 진행 중 값'}
          </p>
          <dl className="mark-pop-snap-list">
            {rows.map((row) => (
              <div className="mark-pop-snap-row" key={row.key}>
                <dt title={row.word}>{row.word}</dt>
                <dd>
                  <SnapValue id={row.id} value={row.value} mark={mark} />
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  )
}
