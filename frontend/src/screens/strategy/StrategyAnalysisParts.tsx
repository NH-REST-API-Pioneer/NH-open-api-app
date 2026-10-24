import {
  amountText,
  loadRecords,
  minuteText,
  type RecordsState,
  type StrategyPerf,
} from '../../data/strategyRecords'
import { resolve } from '../../data/instruments'
import { strategyState } from '../../data/strategyStore'
import { MINUS, Num, currencyCode, toneOf } from '../../lib/number'
import { DELETED } from './runStats'

export const INNER = ['성과 요약', '기간·방향', '비용·체결 품질', '거래 내역'] as const
export type InnerTab = (typeof INNER)[number]

/** 거래 내역 표가 한 번에 더 세우는 줄 수. 5,000건을 한 번에 그리면 탭을 여는
 *  순간이 멈칫합니다. */
export const TRADE_PAGE = 200

/** 거래 내역 표에 종목 열까지 설 수 있는 안쪽 폭. 이보다 좁으면 종목 열을
 *  접고 종목은 전략 칸에 올렸을 때 보입니다. 값 열 넷(종료 시각 140·방향 80·
 *  수량 80·순손익 150)과 종목 열(224)의 폭에, 전략 이름이 말줄임 없이 설
 *  최소 폭(160)을 더한 값입니다. 열 폭은 `strategy.css` 의 `.ana-col-*` 와
 *  같이 고칩니다. */
export const CODE_FITS = 834

export const isKrw = (currency: string) => currencyCode(currency) === 'KRW'

/** 만 단위로 줄인 금액. 좁은 카드의 보조줄에서만 쓰고, **원에만** 씁니다. */
export const man = (value: number) => {
  const unit = Math.abs(value) / 10_000
  const text = unit.toLocaleString('ko-KR', { maximumFractionDigits: 1 })
  return `${value < 0 ? MINUS : ''}${text}만`
}

/** 표와 카드의 금액. 자릿수를 세로로 맞추는 자리에 씁니다. 원은 정수, 그 밖의
 *  통화는 소수 둘째 자리까지입니다. */
export function Amount({
  value,
  currency,
  signed,
  toned,
}: {
  value: number
  currency: string
  signed?: boolean
  toned?: boolean
}) {
  if (isKrw(currency)) return <Num value={value} decimals={0} signed={signed} toned={toned} suffix="원" />
  /* 원이 아닌 통화는 글자로 적습니다. 자릿수 맞춤 부품은 소수부 뒤 칸을 좁게
     잡아 두어, 「 USD」처럼 긴 단위가 붙으면 칸을 넘어 잘리거나 줄이 갈립니다. */
  const tone = toned ? toneOf(value) : ''
  return (
    <span className={`num${tone ? ` ${tone}` : ''}`}>
      {signed && value > 0 ? '+' : ''}
      {amountText(value, currency)}
    </span>
  )
}

/** 건수. 천 단위를 끊습니다. */
export const countText = (value: number) => value.toLocaleString('ko-KR')

export const Dash = () => <span className="ana-none">—</span>

/** 종목 이름. 마스터에 없으면(만기가 지난 월물 등) 코드를 그대로 적습니다. */
export const codeName = (code: string) => resolve(code)?.name ?? code

/** 곡선을 끌어 줄일 수 있는 바닥. `.ana-curve` 의 min-height 와 같습니다 */
export const CURVE_MIN = 150
/** 곡선을 끌어 늘릴 수 있는 끝 */
export const CURVE_MAX = 600

/** 곡선에 무엇을 쌓았는지 말하는 한 줄. 모르는 기준이면 `null` 이고, 지어
 *  말하지 않습니다. */
export function curveNote(basis: string): string | null {
  if (basis === 'realized') {
    return '곡선은 거래일마다 그날까지 닫힌 거래의 순손익(실현 − 수수료) 누적입니다 — 평가손익은 들지 않습니다'
  }
  if (basis === 'equity') {
    return '곡선은 거래일마다 그날 끝의 실현 − 수수료 + 평가손익이고, 기간 앞 값에서 달라진 만큼입니다 — 기간 앞뒤에 보유가 있으면 카드·표의 순손익과 끝점이 다릅니다'
  }
  return null
}

/** 서버 낙폭 기준의 설명. 청산 거래 차례 기준일 때만 섭니다 — 다른 기준이면 그
 *  기준을 지어 말하지 않습니다. */
export function drawdownTitle(basis: string | undefined): string | undefined {
  return basis === 'trades-realized'
    ? '실현 거래 차례 기준 — 청산 시각 차례의 누적 손익에서 고점 대비 최대 감소'
    : undefined
}

/** 전략 줄의 이름. 버전이 지워졌으면 서버가 이름 자리에 「알 수 없음」을 적고
 *  버전 글자를 비워 보냅니다. 그 줄은 전략 목록으로 가립니다 — 목록을 받았는데
 *  없으면 「지운 전략」, 아직 못 받았으면 「—」입니다(받기 전에 「지운」이라 하면
 *  목록이 늦게 온 것만으로 멀쩡한 전략이 지운 것으로 읽힙니다). */
export function perfName(perf: StrategyPerf): string {
  if (perf.version) return `${perf.name} ${perf.version}`
  const { rows, status } = strategyState()
  if (rows.some((row) => row.id === perf.id)) return perf.name
  return status === 'ready' ? DELETED : '—'
}

/** 필터 줄 빈자리의 「받는 중」. 조건을 바꿀 때마다 잠깐 서는 글이라 남는 폭만
 *  씁니다 — 이 글 때문에 필터 줄이 감기면 그때마다 아래 화면이 들썩입니다.
 *  남는 폭이 글보다 좁으면 글 대신 점 하나가 서고, 올리면 「받는 중」이 보입니다. */
export function Busy({ records }: { records: RecordsState }) {
  const { data, status } = records
  if (status !== 'loading' || data === null) return null
  return (
    <div className="ana-busy" role="status" aria-label="받는 중" title="받는 중">
      <span className="ana-busy-text" aria-hidden="true">
        받는 중
      </span>
      <span className="ana-busy-dot" aria-hidden="true" />
    </div>
  )
}

/** 필터 줄 아래의 안내. 잘린 답과 읽는 사이 바뀐 파일 — 이 둘만 섭니다. 잘린
 *  것이 먼저입니다: 화면의 모든 수가 그 범위의 값입니다. 드물게 서는 경고라
 *  줄여 적지 않고 제 줄에 온전히 세웁니다. */
export function Notes({ records }: { records: RecordsState }) {
  const { data } = records
  if (!data?.truncated && !data?.incomplete) return null
  return (
    <div className="ana-notes">
      {data.truncated && (
        <p className="ana-note">
          최근 {data.listed.length.toLocaleString('ko-KR')}건만 셉니다 — {minuteText(data.earliestAt)} 이후
          거래입니다
        </p>
      )}
      {data.incomplete && (
        <p className="ana-note">
          기록을 읽는 사이 파일이 바뀌어 일부가 빠졌을 수 있습니다
          <button type="button" className="btn btn-quiet" onClick={() => void loadRecords()}>
            다시 받기
          </button>
        </p>
      )}
    </div>
  )
}

export function Metric({
  title,
  value,
  note,
  hint,
}: {
  title: string
  value: React.ReactNode
  note: React.ReactNode
  /** 제목에 마우스를 올리면 뜨는 설명. 값이 어떻게 셈한 것인지 말할 때 씁니다. */
  hint?: string
}) {
  return (
    <div className="card ana-metric">
      <h3 className="ana-metric-title" title={hint}>
        {title}
      </h3>
      <p className="ana-metric-value">{value}</p>
      <p className="ana-metric-note">{note}</p>
    </div>
  )
}

/** 아직 답이 없는 자리. **「거래가 없다」와 가릅니다** — 받는 중이거나 못 받은
 *  것을 빈 기록으로 적으면 사용자는 거래가 없었다고 믿습니다. */
export function Waiting({ status }: { status: RecordsState['status'] }) {
  if (status === 'loading') {
    return (
      <div className="notice">
        <p className="notice-title">기록을 받는 중입니다</p>
      </div>
    )
  }
  return (
    <div className="notice">
      <p className="notice-title">기록을 받지 못했습니다</p>
      {/* 조건을 물린 답(기간 아래에 까닭이 섬)은 다시 받아도 같아 단추를
          세우지 않습니다. */}
      {status === 'failed' && (
        <button type="button" className="btn btn-quiet notice-action" onClick={() => void loadRecords()}>
          다시 받기
        </button>
      )}
    </div>
  )
}

export function EmptyRange() {
  return (
    <div className="notice">
      <p className="notice-title">이 기간에 종료된 거래가 없습니다</p>
      <p className="notice-reason">기록 유형이나 기간을 바꿔 보세요</p>
    </div>
  )
}
