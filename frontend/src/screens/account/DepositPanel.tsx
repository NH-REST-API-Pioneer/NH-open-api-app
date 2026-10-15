import { useState, type CSSProperties, type ReactNode } from 'react'
import {
  depositMoney,
  isDomesticDeposit,
  useDepositOnce,
  type DepositEntry,
  type DepositMarket,
  type DepositRow,
  type DomesticDeposit,
  type OverseasDeposit,
  type OverseasView,
} from '../../data/account'
import { currencyDigits } from '../../lib/number'
import { flowShares, keepDistance, usedShare } from '../../lib/marginBar'

/* 예탁자산 — 위에 **한눈에 읽는 덩어리**, 아래에 **값을 확인하는 표**입니다.
 *
 * 위 덩어리는 셋이 뜻을 나눕니다. 도넛은 증거금 사용률(쓸 수 있는 돈 가운데 묶인
 * 몫), 흐름 막대는 돈이 어디로 갔나(예탁자산 − 위탁증거금 = 주문가능)와 유지선까지
 * 거리, 카드 넷은 그 값들을 확인하는 자리입니다. 원형은 하나뿐입니다 — 둘이면 두
 * 원이 같은 말을 하는지 다른 말을 하는지부터 읽어야 합니다.
 *
 * 아래 표는 두 시장이 **낱말과 차례는 같고 모양은 다릅니다.** 국내는 항목 일곱이
 * 네 구분(총액·현금·대용·외화)을 다 가져 격자이고, 해외는 네 구분이 있는 항목이
 * 둘뿐이라 묶음 다섯 칸입니다. 차례는 사용자의 물음을 따릅니다 — 있다 → 쓸 수
 * 있다 → 묶였다 → 모자라다 → 그 밖.
 *
 * **그림 색은 그림에만 씁니다.** 여유는 녹색, 묶임은 옅은 빨강, 유지선은 짙은 빨강,
 * 모자람은 가장 짙은 빨강입니다. 금액 글자는 잔액이라 칠하지 않고, 음수 주문가능과
 * 모자람 금액만 모자람 색입니다. 이 앱의 빨강은 상승도 뜻하므로 칠한 것마다 곁에
 * 낱말(범례·줄 이름·카드 점)을 둡니다.
 */

/** 네 구분의 이름. 격자의 열 이름이자, 해외에서 펴지는 줄의 하위 이름입니다. */
const PARTS = ['총액', '현금', '대용', '외화']

/** 방향색을 쓰는 자리. **손익만입니다** — 수수료·미수는 늘 나가는 돈이라
 *  방향이 없습니다. 부호는 두 번째 단서이고 색이 첫 단서라, 색이 없으면
 *  두 번째만 있는 값이 됩니다. 선물정산차금은 그날의 선물 손익을 정산한 금액이라
 *  손익과 같은 색을 씁니다. */
const TONED = new Set([
  'totalPl',
  'futuresRealisedPl',
  'optionUnrealisedPl',
  'optionRealisedPl',
  'futuresIntradayLoss',
  'futuresSettlement',
  'unrealisedPl',
  'futuresUnrealisedPl',
  'realisedPl',
])

/** 국내 격자 곁의 낱개 값들. 응답이 이름을 안 줘서 화면이 답니다 —
 *  명세의 이름 그대로입니다. */
const DOMESTIC_SINGLES: { key: keyof DomesticDeposit; label: string }[] = [
  { key: 'totalPl', label: '손익총액금액' },
  { key: 'futuresRealisedPl', label: '선물확정손익금액' },
  { key: 'optionUnrealisedPl', label: '옵션평가손익금액' },
  { key: 'optionRealisedPl', label: '옵션확정손익금액' },
  { key: 'futuresIntradayLoss', label: '장중선물순손실상당액' },
  { key: 'futuresSettlement', label: '선물정산차금' },
  { key: 'fee', label: '수수료' },
  { key: 'nightFee', label: '야간수수료' },
  { key: 'unpaid', label: '미수총금액' },
  { key: 'nextDaySettlement', label: '익일결제총금액' },
]

/** 해외 다섯 칸과 그 안의 차례. 응답 순서가 아니라 **사용자의 물음** 차례입니다. */
const OVERSEAS_BANDS: { title: string; keys: string[]; fold?: boolean }[] = [
  {
    title: '있다',
    keys: ['start', 'assets', 'assetsValue', 'totalAccountValue', 'totalAccountValueWithCollateral'],
  },
  { title: '쓸 수 있다', keys: ['orderable', 'withdrawable', 'exchangeable'] },
  {
    title: '묶였다',
    keys: ['orderMargin', 'positionMargin', 'initialMargin', 'maintenanceMargin', 'afterMargin'],
  },
  /* 위험비율이 맨 위입니다. 이 칸을 보는 까닭이 「마진콜 났나」이고 그 물음에
     가장 먼저 답하는 값이라, 금액이 아니라는 이유로 뒤에 두면 확인하는 사람이
     두 자리를 오갑니다. */
  { title: '모자라다', keys: ['riskRate', 'additionalMargin', 'unpaid'] },
  /* **「그 밖」은 늘 마지막입니다.** 세 칸·두 칸일 때 마지막 칸이 두 칸 폭을 써서 줄의
     남은 자리를 채웁니다(account.css 의 `.dep-cell:last-child`). 차례를 바꾸면 그
     규칙도 함께 봐야 합니다. */
  {
    title: '그 밖',
    keys: [
      'unrealisedPl',
      'realisedPl',
      'futuresIntradayLoss',
      'optionMarketValue',
      'fee',
      'nextDaySettlement',
    ],
    fold: true,
  },
]

/** 펴면 보이는 하위 값. **「이 값이 어디서 왔나」 하나를 말합니다** — 축이
 *  구분이든 상품종류든 하는 일이 같아 모양을 가르지 않습니다. */
const OVERSEAS_PARTS: Record<string, { key: string; label: string }[]> = {
  orderMargin: [
    { key: 'futuresOrderMargin', label: '선물' },
    { key: 'optionOrderMargin', label: '옵션' },
  ],
  unrealisedPl: [
    { key: 'futuresUnrealisedPl', label: '선물' },
    { key: 'optionUnrealisedPl', label: '옵션' },
  ],
  fee: [
    { key: 'futuresFee', label: '선물' },
    { key: 'optionFee', label: '옵션' },
    { key: 'etcFee', label: '기타' },
  ],
}

function toneOf(key: string, value: number | null): string | undefined {
  if (value === null || !TONED.has(key)) return undefined
  return value > 0 ? 'up' : value < 0 ? 'down' : undefined
}

/** 값 한 칸. **없는 값은 「—」입니다** — 0 으로 적으면 「없다」가 「0 이다」가
 *  됩니다. 그 둘은 계좌에서 다른 말입니다. */
function Amount({
  value,
  decimals,
  currency,
  percent,
}: {
  value: number | null
  decimals: number
  currency: string | null
  percent?: boolean
}) {
  if (value === null || !Number.isFinite(value)) return <span className="dep-none">—</span>
  if (percent) {
    return <>{value.toLocaleString('ko-KR', { maximumFractionDigits: 2 })}%</>
  }
  return <>{depositMoney(value, decimals, currency)}</>
}

/** 0 인 줄을 접는 끝 줄. 접힌 수를 글자로 말하고, 키보드로 펼 수 있습니다. */
function FoldToggle({
  count,
  open,
  onToggle,
  title,
}: {
  count: number
  open: boolean
  onToggle: () => void
  /** 묶음 이름이 따로 서지 않는 자리에서 끝 줄이 제 묶음을 함께 말합니다. */
  title?: string
}) {
  if (count === 0) return null
  return (
    <button type="button" className="dep-fold" aria-expanded={open} onClick={onToggle}>
      <span className="dep-caret" aria-hidden="true">
        {open ? '▾' : '▸'}
      </span>
      {title && `${title} · `}0 인 항목 {count}개
    </button>
  )
}

/* ── 위: 도넛 · 흐름 · 카드 ─────────────────────────────── */

/** 도넛의 크기. 고리 굵기 안쪽으로 반지름을 잡아 고리가 상자 밖으로 안 나갑니다. */
const RING = { size: 168, stroke: 18 }

/** 두 몫 사이에 비우는 틈(고리 둘레 길이, px). 녹색과 빨강은 밝기가 비슷해 색을
 *  잘 가리지 못하는 눈에는 한 덩어리로 보입니다 — 틈이 두 몫의 경계를 모양으로 말합니다. */
const RING_GAP = 3

/** 도넛. 원(circle)의 테두리를 몫만큼만 칠합니다 — 묶임(빨강)은 12 시부터 시계
 *  방향으로, 여유(녹색)는 그 뒤부터 한 바퀴 끝까지입니다. **호를 path 로 그리지
 *  않습니다** — 100% 는 시작점과 끝점이 같아 path 호가 아무것도 안 그립니다. 테두리를
 *  칠하는 한 방법으로 0 부터 100% 까지 그려집니다. 한쪽이 0 이면 다른 쪽이 한 바퀴를
 *  다 칠하고 틈이 없습니다. 몫을 모르면 바탕 고리만 섭니다. */
function Donut({ share, label, empty = false }: { share: number | null; label: string; empty?: boolean }) {
  const r = (RING.size - RING.stroke) / 2
  const round = 2 * Math.PI * r
  const center = RING.size / 2
  const held = share === null ? 0 : share * round
  const free = share === null ? 0 : round - held
  /* 둘 다 있을 때만 두 경계에 틈을 둡니다. */
  const gap = held > 0 && free > 0 ? RING_GAP : 0
  const arc = (length: number, start: number, className: string) =>
    length - gap > 0 ? (
      <circle
        className={className}
        cx={center}
        cy={center}
        r={r}
        strokeWidth={RING.stroke}
        strokeDasharray={`${(length - gap).toFixed(3)} ${round.toFixed(3)}`}
        strokeDashoffset={(-(start + gap / 2)).toFixed(3)}
        /* 12 시에서 시작해 시계 방향으로 돕니다. */
        transform={`rotate(-90 ${center} ${center})`}
      />
    ) : null
  return (
    <svg
      className="dep-donut-svg"
      width={RING.size}
      height={RING.size}
      viewBox={`0 0 ${RING.size} ${RING.size}`}
      role="img"
      aria-label={label}
    >
      <circle
        className={`dep-ring-base${empty ? ' is-empty' : ''}`}
        cx={center}
        cy={center}
        r={r}
        strokeWidth={RING.stroke}
      />
      {arc(held, 0, 'dep-ring-held')}
      {arc(free, held, 'dep-ring-free')}
    </svg>
  )
}

/** 흐름 한 줄. 이름·금액 한 줄에 그 아래 막대입니다. 폭을 모르면 막대를 안 그립니다. */
function FlowRow({
  name,
  amount,
  share,
  kind,
  short,
}: {
  name: string
  amount: ReactNode
  share: number | null
  kind: 'total' | 'held' | 'free'
  short?: boolean
}) {
  return (
    <div className="dep-flow-row">
      <div className="dep-flow-head">
        <span className="dep-flow-name">{name}</span>
        <span className={`dep-flow-amount${short ? ' is-short' : ''}`}>{amount}</span>
      </div>
      <div className={`dep-flow-track is-${kind}${short ? ' is-short' : ''}`}>
        {share !== null && share > 0 && (
          <span className="dep-flow-fill" style={{ width: `${(share * 100).toFixed(3)}%` }} />
        )}
      </div>
    </div>
  )
}

function DepositTop({ value }: { value: DomesticDeposit | OverseasDeposit }) {
  const domestic = isDomesticDeposit(value)
  /* 금액의 통화·자릿수는 아래 표와 같은 셈입니다(해외는 지금 보는 통화). */
  const decimals = domestic ? 0 : (value.decimals ?? currencyDigits(value.currency) ?? 2)
  const currency = domestic ? 'KRW' : value.currency
  const money = (amount: number | null) =>
    amount === null || !Number.isFinite(amount) ? '—' : depositMoney(amount, decimals, currency)
  const percent = (share: number) => `${(share * 100).toFixed(1)}%`

  const assetsRow = domestic
    ? value.items.find((row) => row.key === 'assets')
    : value.groups.find((row) => row.key === 'assets')
  const pick = (key: string): number | null =>
    domestic
      ? (value.items.find((row) => row.key === key)?.values[0] ?? null)
      : (value.items.find((row) => row.key === key)?.value ?? null)

  const total = assetsRow?.values[0] ?? null
  const margin = pick('initialMargin')
  const orderable = pick('orderable')
  const withdrawable = pick('withdrawable')
  const maintenance = pick('maintenanceMargin')
  const additional = pick('additionalMargin')
  const start = domestic ? null : (value.groups.find((row) => row.key === 'start')?.values[0] ?? null)
  const short = additional !== null && additional > 0 ? additional : null

  /* **예탁 총액이 없거나 0 이하면 그리지 않습니다.** 0% 를 그리면 「하나도 안
     묶였다」로 읽히는데, 실제로는 그릴 기준이 없는 것입니다. */
  const drawable = total !== null && Number.isFinite(total) && total > 0
  const used = usedShare(total, margin, orderable)
  const flow = flowShares(total, margin, orderable)
  const keep = keepDistance(total, maintenance)

  /* 국내 예탁 구성(현금·대용·외화). **몫은 세 구분의 합으로 나눕니다** — 총액 칸으로
     나누면 서버 총액이 세 구분의 합과 조금만 달라도(반올림 등) 몫의 합이 100% 를
     넘거나 모자랍니다. 어느 구분이 없거나 음수이거나 합이 0 이하면 적지 않습니다. */
  const parts = domestic && assetsRow ? assetsRow.values.slice(1, 4) : []
  const whole = parts.reduce<number>((sum, part) => sum + (part ?? 0), 0)
  const composed =
    parts.length === 3 &&
    parts.every((part) => part !== null && Number.isFinite(part) && part >= 0) &&
    whole > 0
      ? (parts as number[]).map((part) => Math.round((part / whole) * 100))
      : null

  /* 해외 위험비율. **서버 값을 퍼센트 수로 봅니다**(12.3 이면 12.3%) — 실제 계좌에서
     뜻과 단위를 확인하기 전의 가정입니다. 그래서 그림 없이 글자로만 적고, 곁에
     그 사실을 표지로 답니다. */
  const risk = domestic ? null : pick('riskRate')
  const converted = !domestic && value.conversion === 'converted'

  /* 까닭은 짓지 않습니다 — 대용·미수 같은 짐작을 적으면 서버가 말하지 않은 것이 섭니다. */
  const mismatchLine =
    flow.mismatch === null ? null : `주문가능은 서버 값 — 예탁 − 위탁증거금과 ${money(flow.mismatch)} 다릅니다`

  const keepLine =
    keep === null
      ? null
      : keep.kind === 'none'
        ? '유지증거금 없음'
        : keep.kind === 'below'
          ? `유지선 아래 ${money(keep.gap)}`
          : `유지선까지 ${money(keep.gap)} · 예탁의 ${percent(keep.share)}`

  return (
    <section className="dep-top" aria-label="예탁자산 요약">
      {drawable ? (
        <>
          <div className="dep-donut">
            <div className="dep-donut-box">
              <Donut
                share={used.share}
                label={`증거금 사용률 ${used.share === null ? '모름' : percent(used.share)}, 묶임 ${money(margin)}, 주문가능 ${money(orderable)}`}
              />
              <div className="dep-donut-center" aria-hidden="true">
                <span className="dep-donut-value">{used.share === null ? '—' : percent(used.share)}</span>
                <span className="dep-donut-name">증거금 사용률</span>
              </div>
            </div>
            <p className="dep-legend">
              <span className="dep-dot is-held" aria-hidden="true" />
              묶임
              <span className="dep-dot is-free" aria-hidden="true" />
              여유
            </p>
            {/* 도넛은 위탁증거금 사용률이라 「모자람」만 적으면 위탁증거금 − 예탁으로 읽힙니다.
                서버의 추가증거금이라는 출처를 이름으로 적습니다. */}
            {used.over && short !== null && <p className="dep-donut-short">추가증거금 {money(short)}</p>}
          </div>

          <div
            className="dep-flow"
            role="img"
            aria-label={`예탁자산 ${money(total)}, 위탁증거금 ${money(margin)}, 주문가능 ${money(orderable)}${keepLine ? `, ${keepLine}` : ''}${mismatchLine ? `, ${mismatchLine}` : ''}`}
          >
            <FlowRow name="예탁자산" amount={money(total)} share={1} kind="total" />
            <FlowRow name="− 위탁증거금" amount={money(margin)} share={flow.held} kind="held" />
            <FlowRow
              /* 서버 주문가능이 예탁 − 위탁증거금과 다르면 「=」로 잇지 않습니다. */
              name={flow.mismatch === null ? '= 주문가능' : '주문가능'}
              amount={money(orderable)}
              share={flow.short ? 0 : flow.free}
              kind="free"
              short={flow.short}
            />
            {keep !== null && (
              <div className="dep-keep">
                <div className="dep-keep-track">
                  {keep.kind !== 'none' && (
                    <span className="dep-keep-mark" style={{ left: `${(keep.mark * 100).toFixed(3)}%` }} />
                  )}
                </div>
                <p className={`dep-keep-line${keep.kind === 'below' ? ' is-short' : ''}`}>{keepLine}</p>
              </div>
            )}
            {mismatchLine && <p className="dep-flow-note">{mismatchLine}</p>}
          </div>
        </>
      ) : (
        /* 그릴 기준이 없어도 **자리 모양은 그대로** 둡니다 — 도넛·흐름 두 자리를 한
           줄로 대신하면 위 덩어리가 줄어, 값이 올 때마다 아래 표가 오르내립니다.
           고리는 바탕만 서고 칠한 몫이 없습니다. */
        <>
          <div className="dep-donut">
            <div className="dep-donut-box">
              <Donut share={null} label="그릴 값이 없습니다" empty />
              <div className="dep-donut-center" aria-hidden="true">
                <span className="dep-donut-value">—</span>
                <span className="dep-donut-name">증거금 사용률</span>
              </div>
            </div>
            <p className="dep-legend">예탁자산 없음</p>
          </div>
          <p className="dep-flow-empty">
            그릴 값이 없습니다
            {/* 까닭은 값이 있을 때만 적습니다 — 줄이 아예 없으면 0 이하인지 모릅니다. */}
            {total !== null && Number.isFinite(total) && ' · 예탁자산이 0 이하입니다'}
          </p>
        </>
      )}

      <div className="dep-cards">
        <div className="dep-card">
          <p className="dep-card-name">{converted ? '예탁자산 · 원화 환산' : '예탁자산'}</p>
          {/* 예탁자산이 없거나 0 이하면 그림과 같은 까닭으로 값을 세우지 않습니다 —
              그릴 기준이 없는 자리에 「0원」이 서면 계좌가 비었다는 말로 읽힙니다. */}
          <p className="dep-card-value">{drawable ? money(total) : '—'}</p>
          <p className="dep-card-sub">
            {domestic
              ? composed
                ? `현금 ${composed[0]}% · 대용 ${composed[1]}% · 외화 ${composed[2]}%`
                : ''
              : `개시예탁 ${money(start)}`}
          </p>
        </div>
        <div className="dep-card">
          <p className="dep-card-name">
            <span className="dep-dot is-free" aria-hidden="true" />
            주문가능
          </p>
          <p className={`dep-card-value${orderable !== null && orderable < 0 ? ' is-short' : ''}`}>
            {money(orderable)}
          </p>
          <p className="dep-card-sub">인출가능 {money(withdrawable)}</p>
        </div>
        <div className="dep-card">
          <p className="dep-card-name">
            <span className="dep-dot is-held" aria-hidden="true" />
            위탁증거금
          </p>
          <p className="dep-card-value">{money(margin)}</p>
          {/* 퍼센트는 도넛 하나만 말합니다. 여기에 「예탁의 N%」를 두면 도넛의 사용률과
              가까운 두 수가 나란히 서서, 뜻이 다른 두 비율을 견주게 됩니다. 증거금이
              어디까지 내려가도 되는지를 말하는 유지증거금(서버 값)을 적습니다. */}
          <p className="dep-card-sub">유지증거금 {money(maintenance)}</p>
        </div>
        {domestic ? (
          <div className="dep-card">
            <p className="dep-card-name">추가증거금</p>
            <p className={`dep-card-value${short !== null ? ' is-short' : ''}`}>{money(additional)}</p>
            {/* **발생했을 때만 이유를 답니다.** 응답은 안 생겼을 때도 글자를 채워
                보내므로(「발생 없음」), 글자가 있다고 발생한 것이 아닙니다. */}
            <p className="dep-card-sub">{short !== null ? (value.marginCallReason ?? '') : '발생 없음'}</p>
          </div>
        ) : (
          <div className="dep-card">
            <p className="dep-card-name">
              위험비율
              <span className="dep-card-tag">서버 값 · 뜻 확인 중</span>
            </p>
            <p className="dep-card-value">
              {risk === null || !Number.isFinite(risk)
                ? '—'
                : `${risk.toLocaleString('ko-KR', { maximumFractionDigits: 2 })}%`}
            </p>
            <p className={`dep-card-sub${short !== null ? ' is-short' : ''}`}>추가증거금 {money(additional)}</p>
          </div>
        )}
      </div>
    </section>
  )
}

/* ── 아래: 국내 항목 일곱 × 구분 넷 + 그 밖 ─────────────────── */

function DomesticDetail({ value }: { value: DomesticDeposit }) {
  const [open, setOpen] = useState(false)
  const margin = value.items.find((row) => row.key === 'additionalMargin')?.values[0] ?? null
  /* **발생했을 때만 이유를 답니다.** 응답은 안 생겼을 때도 글자를 채워 보내므로
     (「발생 없음」), 글자가 있다고 발생한 것이 아닙니다. 총액이 0 보다 큰지로
     봅니다 — 백엔드 주석이 못 박아 둔 자리입니다. */
  const called = margin !== null && margin > 0

  /* 낱개 값은 **칸이 빠져 올 수 있어** 없는 칸을 빈 값으로 읽습니다 — 그대로 읽으면
     빠진 칸이 「NaN원」으로 섭니다. 0 인 줄은 접습니다 — 열 줄 가운데 대개 여덟이
     0 이라, 다 펴 두면 값이 있는 줄이 묻힙니다. 빈 값(—)은 0 이 아니라 접지 않습니다. */
  const singles = DOMESTIC_SINGLES.map((single) => ({
    ...single,
    cell: (value[single.key] ?? null) as number | null,
  }))
  const zero = singles.filter((single) => single.cell === 0)
  const shown = open ? singles : singles.filter((single) => single.cell !== 0)
  /* **접으면 보일 줄이 없을 때**는 「그 밖」 열을 걷고 표가 전체 폭을 씁니다 — 빈
     열이 폭의 넷 중 하나를 차지하면 표가 까닭 없이 좁습니다. 접힘 줄은 표 아래로
     갑니다. 펼쳐도 이 배치를 지킵니다 — 되돌리면 표 폭이 튑니다. 접는 셈과 같은
     자리(`zero`)에서 가립니다. */
  const allZero = zero.length === singles.length

  return (
    <div className={`dep-detail${allZero ? ' is-full' : ''}`}>
      <table className="dep-grid">
        <thead>
          <tr>
            <th scope="col" />
            {PARTS.map((part) => (
              <th key={part} scope="col">
                {part}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {value.items.map((row) => {
            const warn = row.key === 'additionalMargin' && called
            return (
              <tr key={row.key}>
                <th scope="row">
                  {row.label}
                  {/* 이유는 항목 이름 아래 한 줄입니다. **색을 안 씁니다** —
                      경보를 내는 것은 값이고, 이유는 그것이 어느 종류인지를
                      설명할 뿐입니다. 둘 다 칠하면 색이 두 가지를 말합니다. */}
                  {warn && value.marginCallReason && (
                    <span className="dep-why">{value.marginCallReason}</span>
                  )}
                </th>
                {row.values.map((cell, index) => (
                  <td
                    key={PARTS[index]}
                    /* **0 인 칸에는 경고색을 안 씁니다.** 색은 이상할 때만
                       쓰는 것이라, 0 까지 물들면 0 이 이상하다고 말합니다. */
                    className={warn && cell !== null && cell !== 0 ? 'dep-warn' : undefined}
                  >
                    <Amount value={cell} decimals={0} currency="KRW" />
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>

      <dl className="dep-col dep-singles">
        {allZero ? (
          /* 표 아래 한 줄이라 묶음 이름을 끝 줄이 함께 말합니다. 펼친 줄은 그 아래에
             섭니다 — 끝 줄이 제자리에 있어야 다시 접기 쉽습니다. */
          <FoldToggle count={zero.length} open={open} onToggle={() => setOpen((now) => !now)} title="그 밖" />
        ) : (
          <p className="dep-band">그 밖</p>
        )}
        {shown.map((single) => (
          <div key={single.key} className="dep-row">
            <dt>{single.label}</dt>
            <dd className={toneOf(single.key, single.cell)}>
              <Amount value={single.cell} decimals={0} currency="KRW" />
            </dd>
          </div>
        ))}
        {!allZero && <FoldToggle count={zero.length} open={open} onToggle={() => setOpen((now) => !now)} />}
      </dl>
    </div>
  )
}

/* ── 아래: 해외 다섯 칸 ─────────────────────────────────── */

function OverseasDetail({ value }: { value: OverseasDeposit }) {
  const [open, setOpen] = useState<string[]>([])
  const [folded, setFolded] = useState(true)
  /* 자릿수는 **답이 실어 준 통화 자릿수**가 먼저이고, 없으면 통화 코드로 정합니다
     (원화 환산이면 원이라 0). 둘 다 모르면 둘째 자리까지입니다. */
  const decimals = value.decimals ?? currencyDigits(value.currency) ?? 2
  /* 금액 단위는 칸 머리에 한 번 적고, 줄의 값에는 단위를 안 붙입니다. */
  const unit = value.currency === 'KRW' ? '원' : (value.currency ?? '')

  const groups = new Map(value.groups.map((row) => [row.key, row]))
  const items = new Map(value.items.map((row) => [row.key, row]))
  /* **이름은 서버가 준 것만** 씁니다. 답에 없는 줄은 세우지 않습니다 — 열쇠를
     이름 자리에 세우면 영어 코드가 항목 이름으로 읽힙니다. */
  const labelOf = (key: string): string | null => groups.get(key)?.label ?? items.get(key)?.label ?? null
  const amountOf = (key: string): number | null => {
    const group = groups.get(key)
    if (group) return group.values[0] ?? null
    return items.get(key)?.value ?? null
  }

  const margin = amountOf('additionalMargin')
  const called = margin !== null && margin > 0

  const toggle = (key: string) =>
    setOpen((keys) => (keys.includes(key) ? keys.filter((one) => one !== key) : [...keys, key]))

  /** 이 줄이 펴지는지, 펴면 무엇이 보이는지. 네 구분을 가진 줄과 상품종류로
   *  갈리는 줄이 **같은 모양**으로 펴집니다. */
  const partsOf = (key: string): { label: string; value: number | null }[] | null => {
    const group = groups.get(key)
    if (group) {
      return PARTS.slice(1).map((label, index) => ({ label, value: group.values[index + 1] ?? null }))
    }
    const spec = OVERSEAS_PARTS[key]
    if (!spec) return null
    return spec.map((part) => ({ label: part.label, value: amountOf(part.key) }))
  }

  return (
    <div className="dep-five">
      {OVERSEAS_BANDS.map((band) => {
        const present = band.keys.filter((key) => labelOf(key) !== null)
        /* 「그 밖」만 0 인 줄을 접습니다. 앞 넷은 0 도 답입니다 — 「묶인 돈 없음」이
           「묶였다」 칸이 할 말입니다. */
        const zero = band.fold ? present.filter((key) => amountOf(key) === 0) : []
        const rows = band.fold && folded ? present.filter((key) => amountOf(key) !== 0) : present
        /* 「그 밖」은 다섯 칸이 한 줄에 안 들어갈 때 두 칸 폭을 씁니다(account.css).
           그때 줄이 둘 이상이면 두 단으로 나눠, 넓어진 칸에 줄이 한쪽으로 몰리지
           않게 합니다. 둘째 단의 첫 줄은 단의 맨 위라 위 선을 긋지 않습니다. */
        const split = band.fold === true && rows.length >= 2
        const half = Math.ceil(rows.length / 2)
        return (
          <section key={band.title} className="dep-cell" aria-label={band.title}>
            <p className="dep-cell-head">
              <span>{band.title}</span>
              {unit && <span className="dep-cell-unit">{unit}</span>}
            </p>
            <dl
              className={`dep-cell-rows${split ? ' is-split' : ''}`}
              style={split ? ({ '--dep-rows': half } as CSSProperties) : undefined}
            >
              {rows.map((key, index) => {
                const parts = partsOf(key)
                const shown = open.includes(key)
                const amount = amountOf(key)
                const warn = key === 'additionalMargin' && called
                return (
                  <div key={key} className={split && index === half ? 'is-col-top' : undefined}>
                    <div className="dep-cell-row">
                      <dt>
                        {parts ? (
                          <button
                            type="button"
                            className="dep-toggle"
                            aria-expanded={shown}
                            onClick={() => toggle(key)}
                          >
                            <span className="dep-caret" aria-hidden="true">
                              {shown ? '▾' : '▸'}
                            </span>
                            {labelOf(key)}
                          </button>
                        ) : (
                          labelOf(key)
                        )}
                        {warn && <span className="dep-why">추가증거금 발생</span>}
                      </dt>
                      <dd className={warn ? 'dep-warn' : toneOf(key, amount)}>
                        <Amount
                          value={amount}
                          decimals={decimals}
                          currency={null}
                          percent={key === 'riskRate'}
                        />
                      </dd>
                    </div>
                    {parts &&
                      shown &&
                      parts.map((part) => (
                        <div key={part.label} className="dep-cell-row dep-part">
                          <dt>{part.label}</dt>
                          {/* 하위 줄은 **부모 줄의 색 규칙**을 따릅니다 — 부모가 손익이면
                              하위도 등락색, 아니면 색이 없습니다. */}
                          <dd className={toneOf(key, part.value)}>
                            <Amount value={part.value} decimals={decimals} currency={null} />
                          </dd>
                        </div>
                      ))}
                  </div>
                )
              })}
            </dl>
            {band.fold && (
              <FoldToggle count={zero.length} open={!folded} onToggle={() => setFolded((now) => !now)} />
            )}
          </section>
        )
      })}
    </div>
  )
}

/* ── 얼굴 ──────────────────────────────────────────────── */

function DepositFace({ entry }: { entry: DepositEntry }) {
  if (entry.status === 'loading') {
    return (
      <div className="dep-word">
        <span className="skeleton" style={{ minWidth: '12ch' }} />
      </div>
    )
  }
  /* **문장은 화면에 한 번입니다.** 바로 위 요약 띠가 같은 사정을 이미 말하고
     다시 부를 단추도 거기 있습니다. 같은 문장을 여기 또 세우면 한 화면이 같은
     말을 두 번 하고, 단추가 둘이면 어느 것을 눌러야 하는지도 갈립니다.
     여기는 그 표가 왜 비었는지를 잇는 짧은 표지입니다. */
  if (entry.status === 'failed') {
    return <div className="dep-word">받지 못했습니다</div>
  }
  return <div className="dep-word">조회 전</div>
}

interface Props {
  market: DepositMarket
  /** 해외 금액을 보는 통화. 국내는 쓰지 않습니다. */
  view?: OverseasView
}

export function DepositPanel({ market, view }: Props) {
  /* **이 탭을 열 때 부릅니다.** 계좌 조회에는 초당 한도가 있어, 안 보는 탭까지
     부르면 보는 탭이 밀립니다. */
  const entry = useDepositOnce(market, view)
  const value = entry.value

  if (value === null) return <DepositFace entry={entry} />

  return (
    <div className="dep">
      <DepositTop value={value} />
      {isDomesticDeposit(value) ? <DomesticDetail value={value} /> : <OverseasDetail value={value} />}
    </div>
  )
}

export type { DepositRow }
