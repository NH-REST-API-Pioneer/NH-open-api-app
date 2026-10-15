import { Num } from '../../lib/number'
import { displayTickOf, needsLeg, resolve } from '../../data/instruments'
import { useProductExpiry } from '../../data/productExpiry'
/* 타입 이름이 아래 화면 부품과 같아 다른 이름으로 들입니다 — 같은 이름을 두
   뜻으로 쓰면 읽는 사람이 어느 쪽인지 되짚어야 합니다. */
import {
  PRODUCT_INFO_FAILED,
  useOverseasProductInfo,
  useProductInfo,
  type OverseasProductInfo as OverseasSpec,
  type ProductInfoEntry,
} from '../../data/productInfo'
import {
  domesticAuctionHoursFor,
  domesticHoursFor,
  domesticProductDetail,
  overseasProductHours,
  useSession,
  useTimetable,
  windowText,
  type Window,
} from '../../data/session'
import { INVESTOR_LABEL, UNIT_LABEL, useTrend } from '../../data/trendInvestor'
import type { MarketContext, ProductKind, Quote } from '../../lib/types'

/* 품목정보 탭과 시장자료 탭.
 *
 * 품목정보는 한 화면 스펙 시트라 2열 격자면 끝납니다.
 * 항목이 시장마다 다릅니다 — 빈칸이 생기는 게 아니라 있는 항목이 서로 다릅니다.
 * 두 탭의 가름은 **안 바뀌는 것과 날마다 바뀌는 것**입니다 — 규격·시간·만기는
 * 품목정보, 시가·정산가는 시장자료입니다.
 */

/** 시트 한 줄. 셋째 칸 `wide` 는 **두 칸을 덮으라**는 뜻입니다 — 값이 줄로
 *  여럿인 줄(거래시간)만 넓게 두고 나머지는 두 칸 격자 그대로입니다. 좁은 값
 *  칸에서는 시각 하나가 가운데서 꺾여 두 줄에 나뉩니다. */
type SheetRow = [string, React.ReactNode] | [string, React.ReactNode, 'wide']

function Sheet({ rows }: { rows: SheetRow[] }) {
  return (
    <dl className="spec-sheet">
      {rows.map(([label, value, wide]) => (
        <div key={label} className={wide ? 'spec-row spec-row-wide' : 'spec-row'}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}


/** 돈·수를 세 자리로 끊어 적습니다. **받은 값 그대로**입니다 — 자리 수를 못 박아
 *  두면 소수가 붙어 오는 증거금(`612,380.385`)이 조용히 반올림되어, 화면의 수와
 *  서버가 답한 수가 달라집니다. */
function won(value: number): string {
  return value.toLocaleString('ko-KR', { maximumFractionDigits: 20 })
}

/** 틱을 적는 데 드는 소수 자리 수. **값이 요구하는 만큼**입니다 — 0.01 을 한 자리로
 *  적으면 0.0 이 되어 0 으로 읽힙니다. */
function tickDigits(tick: number): number {
  const text = String(tick)
  const at = text.indexOf('.')
  return at < 0 ? 0 : text.length - at - 1
}

/** 마스터가 준 만기를 날짜로. **날까지 오는 것만** 적습니다 — 월까지만 아는
 *  종목(해외)에서 날을 지어내면 그날 거래가 끝나는 것으로 읽힙니다. */
function expiryDate(expiry: string): string | null {
  const digits = expiry.replace(/\D/g, '')
  if (digits.length < 8) return null
  return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)}`
}

/** 여러 줄짜리 값 한 칸. **창 하나가 한 줄입니다** — 창이 둘 이상인 값(거래시간)을
 *  한 줄로 이으면 어디서 끊어 읽어야 하는지가 안 보이고, 칸이 좁을 때 아무 데서나
 *  접힙니다. */
function Lines({ items }: { items: readonly string[] }) {
  return (
    <>
      {items.map((text) => (
        <div key={text}>{text}</div>
      ))}
    </>
  )
}

/** 국내 거래시간. **그 품목 줄에 있는 창만 적습니다**(`data/session.ts`) — 시각을
 *  이 자리에서 짓지 않습니다. 시장 공통값이 아니라 품목의 값이라, 같은 주간이라도
 *  08:45 에 여는 품목과 09:00 에 여는 품목이 제 시각을 말합니다.
 *
 *  세션마다 한 줄이고, 단일가 창이 그 줄에 있으면 괄호로 덧붙입니다. 단일가는
 *  접속매매 창 **안쪽**이라(끝 시각이 같습니다) 따로 세우면 두 구간이 잇달아
 *  있는 것으로 읽힙니다. 야간이 없는 종목(`hasNight` 거짓)은 주간 한 줄입니다.
 *  그 품목 줄이 없는 세션은 시장 공통값을 적고 줄 끝에 「· 시장 공통」을 답니다. */
function domesticTradingHours(
  productCode: string | null,
  kind: ProductKind,
  hasNight: boolean,
): string[] {
  /* 야간 줄을 세우는 근거. 품목 줄이 있는 품목은 **그 품목의 야간 줄**이 있어야
     하고, 품목 줄이 아예 없는 종목은 세션 판정이 야간이 있다고 답해야 합니다 —
     공통 표에는 늘 야간이 있어, 거기로 내려가면 야간이 없는 종목에도 야간이 섭니다. */
  const night =
    domesticProductDetail(productCode, kind, 'night') !== null ||
    (domesticProductDetail(productCode, kind, 'day') === null && hasNight)
  return (['day', 'night'] as const)
    .map((session) => {
      if (session === 'night' && !night) return ''
      const trading = domesticHoursFor(productCode, kind, session)
      if (!trading.text) return ''
      const auction = domesticAuctionHoursFor(productCode, kind, session)
      const name = session === 'day' ? '주간' : '야간'
      /* 단일가는 **거래시간과 같은 출처일 때만** 답니다. 품목 줄에 단일가가 없는
         품목에 공통 표의 단일가를 붙이면, 꼬리 없는 줄 안에 시장 값이 섞입니다. */
      const held =
        auction.text && auction.common === trading.common ? ` (단일가 ${auction.text})` : ''
      /* 시장 공통값이면 그 사실을 줄 끝에 답니다 — 꼬리가 붙고 안 붙고가 그
         자체로 정보라, 안 붙은 줄은 그 품목이 제 시각을 말한 것입니다. */
      return `${name} ${trading.text}${held}${trading.common ? ' · 시장 공통' : ''}`
    })
    .filter((text) => text !== '')
}

/** 시각 구간 하나. 시작과 끝이 같으면(정산가 산정 시각이 한 점인 품목) 하나만 적습니다. */
function spanText(window: Window | null): string {
  if (!window) return ''
  if (window.open === window.close && !window.nextDay) return window.open
  return windowText(window)
}

/** 품목 표가 값을 못 채웠을 때 **시트 꼬리에 서는 한 줄.** 칸마다 까닭을 달면
 *  같은 말이 여러 칸에 서고, 마우스를 올려야 보이는 자리에 두면 그 말이 있다는
 *  것조차 모릅니다.
 *
 *  **어느 갈래인지는 답의 모양이 말합니다** — 글자를 맞춰 보지 않습니다. 품목을
 *  찾았고 표도 받았는데 그 줄이 없으면 이 종목만의 일이고, 그 앞 단계에서
 *  막혔으면 서버 문장이 그대로 사용자에게 할 말입니다. */
function specNote(row: OverseasSpec | null): string | null {
  if (!row || !row.why) return null
  if (row.productCode !== null && row.source !== null) {
    return '이 종목의 품목 줄을 찾지 못해 몇 칸이 비어 있습니다'
  }
  return row.why
}

/** 품목 표의 인수도구분을 **그 줄이 읽는 서버의 낱말**로. 서버가 영어 코드로
 *  줍니다(`cash`·`physical`).
 *
 *  **낱말은 만기 조회 쪽에 맞춥니다.** 같은 칸을 두 출처가 채우는데 꼴이
 *  갈리면(「인수도」와 「실물인수도」) 읽는 사람이 둘을 맞춰 봐야 합니다.
 *  모르는 값은 적지 않습니다 — 지어낸 낱말이 서면 그것이 서버가 한 말로
 *  읽힙니다. */
function deliveryWord(code: string | null): string | null {
  if (code === 'cash') return '현금'
  if (code === 'physical') return '인수도'
  return null
}

/** 해외 품목정보. **서버와 마스터가 주는 칸만** 섭니다 — 정비 창처럼 어느
 *  출처도 안 주는 칸은 행을 안 세우고, 출처는 있는데 값을 못 받은 칸은 라벨만
 *  남기고 값 자리를 비웁니다(헤더가 값을 못 받았을 때와 같은 결).
 *
 *  차례는 신원(거래소·통화) → 규격(틱사이즈·틱값·거래승수) → 시간(거래시간·정산가
 *  산정 시각) → 만기(만기 월물·최종거래일·결제방법·최초통보일·최종결제일)입니다.
 *  결제방법이 최초통보일 앞에 서는 것은 실물인수도인지가 그 날짜의 뜻을 정하기
 *  때문입니다.
 *
 *  출처 넷: 거래소·통화·시간은 거래시간표(`data/session.ts`, 한국시간), 틱사이즈·
 *  틱값·만기 월물은 종목 마스터, 만기 날짜 셋은 만기 정보 조회
 *  (`data/productExpiry.ts`), 거래승수와 적용일자는 품목 표
 *  (`data/productInfo.ts`). 마스터의 거래소는 파일 축(`FCME`)이라 시간표의
 *  거래소 이름(`CME`)을 먼저 쓰고, 시간표를 못 받았을 때만 마스터 것을 씁니다. */
function OverseasProductInfo({ quote }: { quote: Quote }) {
  /* 시간표가 뒤늦게 오면 다시 그립니다. 값은 아래 접근자로 읽습니다. */
  useTimetable()
  const item = resolve(quote.code)
  const product = item?.product ?? null
  const contract = item?.contract ?? null
  const hours = product ? overseasProductHours(product.exchangeNo, product.code) : null
  /* 행사가를 아직 안 고른 옵션 자리는 종목이 없어 안 묻습니다 — 만기 날짜 셋이
     빈 채로 섭니다. */
  const expiry = useProductExpiry(needsLeg(quote.code) ? '' : quote.code)
  /* 품목 표가 주는 값 — 계약단위·적용일자는 여기밖에 없고, 통화·인수도구분은
     다른 출처가 비었을 때만 씁니다. 행사가를 안 고른 옵션 자리는 안 묻습니다. */
  const spec = useOverseasProductInfo(needsLeg(quote.code) ? '' : quote.code)
  const currency = hours?.currency ?? null
  /* **수만 적습니다** — 값이 한 단 움직일 때 얼마가 되는지를 정하는 수이고,
     단위 이름은 품목마다 달라(배럴·부셸·지수) 표가 주지 않습니다.
     못 채웠으면 「—」만 두고 까닭은 시트 꼬리가 한 번 말합니다. */
  const multiplier =
    spec.row?.contractUnit != null
      ? spec.row.contractUnit.toLocaleString('ko-KR', { maximumFractionDigits: 6 })
      : spec.row?.why
        ? <span className="dead">—</span>
        : null

  /* 호가단위는 **값을 적는 단위**로 맞춘 것입니다(`displayTickOf`) — 곡물처럼
     값은 센트로 부르는데 마스터가 달러로 실어 주는 품목에서, 사다리가 오르내리는
     한 단과 같은 수가 서야 합니다. 자릿수는 값이 정합니다. */
  const displayTick = product ? displayTickOf(product) : null
  const tickSize =
    displayTick !== null ? displayTick.toLocaleString('ko-KR', { maximumFractionDigits: 10 }) : null
  /* 틱값은 마스터가 곱해 둔 값(`tval`)입니다. 돈 표기는 앱 공통으로 **값 뒤에
     통화 코드**(「1.25 USD」)이고, 통화를 모르면 수만 적습니다. */
  const tickValue =
    contract?.tickValue != null
      ? `${contract.tickValue.toLocaleString('ko-KR', {
          minimumFractionDigits: 2,
          maximumFractionDigits: 6,
        })}${currency ? ` ${currency}` : ''}`
      : null
  /* 만기 조회에서 오는 네 칸(결제방법·최종거래일·최초통보일·최종결제일)이
     「값 없음」을 **한 얼굴로** 말합니다 — **답이 왔는데 그 칸이 없으면 「—」**,
     아직 안 왔으면 빈 채입니다. 한 시트 안에서 어떤 칸은 「—」이고 어떤 칸은
     비어 있으면, 읽는 사람이 그 차이에서 없는 뜻을 찾습니다. */
  const expiryBlank = expiry.status === 'ready' ? <span className="dead">—</span> : null

  /* 창이 둘·셋인 품목(1차·2차·익일)은 **한 창이 한 줄**입니다 — 이어 적으면
     칸이 좁을 때 한 창의 가운데에서 접힙니다. */
  const trading = hours
    ? [hours.trading, hours.second, hours.nextDayTrading]
        .map((window) => windowText(window))
        .filter((text) => text !== '')
    : []

  const rows: [string, React.ReactNode][] = [
    ['거래소', hours?.exchange ?? product?.exchange ?? null],
    /* 통화는 거래시간표가 먼저입니다. 품목 표에도 같은 값이 있어, 시간표를
       못 받았을 때만 그쪽에서 받아 씁니다 — 한 칸에 출처 둘을 나란히 두면
       어긋나는 날 어느 쪽이 맞는지 못 가립니다. */
    ['통화', currency ?? spec.row?.currency ?? null],
    ['틱사이즈', tickSize],
    ['틱값', tickValue],
    /* **품목 표에만 있는 값입니다.** 마스터는 이 수를 안 싣습니다 — 틱값 ÷
       호가단위로 셈할 수도 있지만(재생 서버의 세 품목에서 맞았습니다) 표에
       직접 있는 값을 씁니다. 셈해서 내면 그 나눗셈이 맞는지 늘 함께 믿어야
       합니다. */
    ['거래승수', multiplier],
    ['거래시간', trading.length > 0 ? <Lines items={trading} /> : null],
    ['정산가 산정 시각', spanText(hours?.settlementWindow ?? null) || null],
    ['만기 월물', contract?.label ?? null],
    ['최종거래일', expiry.row?.expiry ?? expiryBlank],
    /* 서버 낱말 그대로(반입해 둔 답에서는 「현금」·「인수도」). **품목 표의
       인수도구분은 같은 사실**이라 행을 따로 세우지 않고, 만기 조회가 그 칸을
       안 줄 때만 그쪽 값을 **같은 낱말로** 옮겨 씁니다 — 한 사실이 두 이름으로
       서면 읽는 사람이 둘을 맞춰 봐야 합니다. */
    ['결제방법', expiry.row?.settlement ?? deliveryWord(spec.row?.delivery ?? null) ?? expiryBlank],
    ['최초통보일', expiry.row?.firstNotice ?? expiryBlank],
    ['최종결제일', expiry.row?.lastSettlement ?? expiryBlank],
  ]
  return (
    <div className="info-panel">
      <Sheet rows={rows} />
      {/* **못 채운 까닭이 먼저입니다.** 빈 칸을 보고 있는 사람에게 먼저 필요한
          말이고, 기준일은 값이 있을 때 붙는 곁말입니다. */}
      {specNote(spec.row) && <p className="spec-note">{specNote(spec.row)}</p>}
      {/* **적용일자는 줄이 아니라 시트의 꼬리입니다.** 값 하나하나에 붙는 것이
          아니라 이 표의 품목 값이 언제 것인지를 말하는 한 마디라, 줄로 세우면
          다른 줄들과 같은 무게가 됩니다. */}
      {spec.row?.appliedDate && <p className="spec-note">{spec.row.appliedDate} 기준</p>}
    </div>
  )
}

export function ProductInfoPanel({ quote, context }: { quote: Quote; context: MarketContext }) {
  /* 시간표가 뒤늦게 오면 다시 그립니다. 값은 접근자로 읽습니다 — 품목 규격도
     같은 응답에서 옵니다(`data/session.ts`). */
  const timetable = useTimetable()
  const overseas = context === 'overseas'
  /* 야간이 있는 종목인지는 세션 판정이 압니다. 머리 띠가 이미 같은 종목을 물어 둔
     값이라 새로 묻지 않습니다. */
  const asked = overseas || needsLeg(quote.code) ? '' : quote.code
  const session = useSession('domestic', asked)
  /* 증거금 셋은 **종목별 품목 값**에서 옵니다. 날마다 바뀌는 값이라, 앱을 켤 때
     한 번 받는 시간표가 아니라 종목을 고를 때 받는 답을 씁니다 — 서버가 거래일이
     바뀐 뒤 한 번 다시 받습니다. 주문 카드가 이미 같은 종목을 물어 둔 값입니다. */
  const info = useProductInfo(asked)
  if (overseas) return <OverseasProductInfo quote={quote} />

  const item = resolve(quote.code)
  /* **품목 규격은 품목별세부정보 줄에서 옵니다.** 그 줄이 없는 품목(주식선물옵션)은
     규격 여덟 줄이 다 빈 채입니다 — 다른 품목의 값을 옮겨 오지 않습니다. */
  const spec = item ? domesticProductDetail(item.product.tradeCode, item.kind) : null

  /* 거래시간도 같은 줄에서 먼저 읽습니다. 그 줄이 없으면 시장 공통값을 적고
     「· 시장 공통」으로 그 사실을 답니다 — 규격과 달리 시각은 시장 전체에 기준이
     있어 비우지 않습니다. 야간이 있는지는 세션 판정이 답한 뒤에만 참입니다. */
  const hasNight = session.status === 'ready' && session.source !== 'unknown' && session.hasNight
  const trading = item ? domesticTradingHours(item.product.tradeCode, item.kind, hasNight) : []

  /* **시트 안의 「없음」 얼굴은 하나입니다.** 시간표를 받았는데도 값이 없으면 그
     품목에 원래 없는 값이라 「—」이고(줄이 없는 품목), 아직 받는
     중이면 자리를 비워 둡니다 — 둘은 사용자가 할 일이 다릅니다. 같은 응답에서
     오는 여덟 줄이 서로 다른 얼굴을 하면 한 칸은 기다릴 값, 한 칸은 없는 값으로
     읽힙니다. */
  const said = (value: React.ReactNode | null) =>
    value !== null && value !== '' ? value : timetable === 'ready' ? '—' : null
  /* 증거금 셋의 얼굴. 위와 같은 규칙을 품목 값의 상태로 읽습니다 — 아직 안 왔으면
     빈 자리, 왔으면 값, 값이 없으면 「—」이고 까닭은 마우스를 올리면 보입니다.
     **옵션에는 증거금이 안 옵니다** — 「—」가 그 사실을 말합니다. */
  const margin = (value: string | null) => marginFace(info, asked, timetable === 'ready', value)
  const row = info.status === 'ready' ? info.row : null
  const why = row && tailWhy(row.whyCode) ? row.why : ''

  const rows: SheetRow[] = [
        [
          '틱',
          said(spec?.tick == null ? null : <Num value={spec.tick} decimals={tickDigits(spec.tick)} />),
        ],
        ['틱가치', said(spec?.tickValue == null ? null : `${won(spec.tickValue)}원`)],
        ['거래승수', said(spec?.multiplier == null ? null : won(spec.multiplier))],
        /* **최종거래일은 마스터가 줍니다** — 국내에는 만기 정보 라우트가 없고,
           품목 줄의 만기는 그 품목의 최근월이라 지금 보고 있는 월물의 것이
           아닙니다. 행사가를 고르기 전에도 만기는 정해져 있어 값이 섭니다 —
           옵션 만기 코드가 날짜까지 들고 있습니다. 날을 안 주는 시장(해외)은
           이 시트에 오지 않습니다. */
        ['최종거래일', said(expiryDate(item?.contract?.expiryDate ?? ''))],
        ['결제방법', said(spec?.settlement ? spec.settlement : null)],
        /* 값이 비율이라 이름도 「률」입니다 — 계좌 탭의 개시증거금·유지증거금은
           금액이라, 같은 낱말이 한 앱에서 두 뜻이 되지 않게 합니다. */
        ['개시증거금률', margin(row?.initialMarginRate ?? null)],
        ['유지증거금률', margin(row?.maintenanceMarginRate ?? null)],
        [
          '계약당 증거금',
          margin(row?.contractInitialMargin == null ? null : `${won(row.contractInitialMargin)}원`),
        ],
        /* 두 칸을 덮는 줄이라 **맨 끝**입니다. 가운데 두면 앞 줄이 왼쪽 칸에서 끝날 때
           이 줄이 다음 행으로 내려가 그 오른쪽 칸이 빕니다. */
        ['거래시간', said(trading.length > 0 ? <Lines items={trading} /> : null), 'wide'],
      ]

  return (
    <div className="info-panel">
      <Sheet rows={rows} />
      {/* 꼬리 두 줄은 **설명하는 값이 섰을 때만** 섭니다. 값이 「—」인 시트(옵션 등)에
          값의 성질을 풀어 쓰면 없는 값을 설명하는 말이 됩니다. */}
      {row?.contractInitialMargin != null && (
        <p className="t-label info-note">
          계약당 증거금은 품목 단위로 와서 종목별 차이가 반영되지 않습니다
        </p>
      )}
      {/* 계약당 유지증거금은 품목정보에 없는 값입니다. 줄을 「—」로 세우면 언젠가 올
          값처럼 읽혀, 줄 대신 서버가 낸 문장을 꼬리에 그대로 답니다. 「유지증거금률로
          보세요」라고 가리키는 말이라 그 률이 섰을 때만 답니다. */}
      {row?.maintenanceMarginRate && row.maintenanceMarginWhy && (
        <p className="t-label info-note">{row.maintenanceMarginWhy}</p>
      )}
      {why && <p className="t-label info-note">{why}</p>}
    </div>
  )
}

/** 증거금 칸 하나의 얼굴. 물을 종목이 없으면(행사가를 아직 안 고른 옵션) 시간표
 *  칸들과 같이 「원래 없음」입니다.
 *
 *  | 상태 | 얼굴 |
 *  | --- | --- |
 *  | `idle`·`loading` | 빈 자리 |
 *  | `ready`, 값 있음 | 값 |
 *  | `ready`, 값 없음 | 「—」, 까닭은 `title` |
 *  | `failed` | 「—」, 까닭은 `title` |
 *
 *  못 받았을 때 다시 받는 단추는 두지 않습니다 — 종목을 다시 고르면 다시 부릅니다. */
function marginFace(
  info: ProductInfoEntry,
  asked: string,
  timetableReady: boolean,
  value: string | null,
): React.ReactNode {
  if (!asked) return timetableReady ? '—' : null
  if (info.status === 'failed') return <span title={PRODUCT_INFO_FAILED}>—</span>
  if (info.status !== 'ready' || !info.row) return null
  if (value !== null && value !== '') return value
  return info.row.why ? <span title={info.row.why}>—</span> : '—'
}

/** 시트 꼬리에 세울 까닭인가. **찾지 못함·받지 못함만** 섭니다.
 *
 *  옵션처럼 품목정보에 증거금이 원래 없는 것(`no_margin`)은 칸의 「—」가 이미 그
 *  사실을 말하므로 꼬리에 또 적지 않습니다 — 같은 말이 한 화면에 두 번 섭니다.
 *  호가단위가 없다는 것(`no_tick`)도 증거금 시트의 일이 아니라 세우지 않습니다. */
const TAIL_WHY = new Set([
  'no_master',
  'no_symbol',
  'no_product',
  'no_kind',
  'no_table',
  'table_failed',
  'no_keys',
])

function tailWhy(code: string | null): boolean {
  return code !== null && TAIL_WHY.has(code)
}

/** 자릿수만 맞춰 그대로 찍습니다. 부호가 뜻을 나르는 값에는 붙여 씁니다.
 *  이 시장에 원래 없는 값(`undefined`)은 「—」, 오늘 아직 안 생긴 값(`null` — 그날
 *  거래가 없어 시가가 안 온 종목)은 빈 채입니다. 둘을 한 얼굴로 두면 거래가 생기면
 *  올 값이 「원래 없음」으로 읽힙니다. */
function fixed(value: number | null | undefined, decimals: number, signed = false): string {
  if (value === undefined) return '—'
  if (value === null) return ''
  const text = Math.abs(value).toLocaleString('ko-KR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
  const sign = value < 0 ? '−' : signed && value > 0 ? '+' : ''
  return `${sign}${text}`
}

/* 시장자료는 탭 이름 자체가 시장마다 바뀝니다 —
 * 국내는 계산값과 투자자 매매동향, 해외는 정산가와 결제일입니다. 세션(장 상태·
 * 개장·폐장)은 여기 없습니다 — 그것은 헤더 한 곳이 서버 판정으로 말합니다.
 *
 * 이론가·베이시스·괴리율·변동성은 헤더가 아니라 여기 있습니다. 매번 보는
 * 값이 아니라 필요할 때 찾아보는 계산값이라, 헤더 한 줄을 쓰면 그 자리만큼
 * 호가 사다리가 줄어듭니다. 뺀 것이 아니라 자리를 옮긴 것입니다.
 *
 * 상장 후 최고·최저도 같은 이유로 여기 있습니다. 계약 한 살이의 값이라 하루
 * 동안 거의 안 움직이고, 헤더는 장중에 움직이는 것만 답니다. */
export function MarketDataPanel({
  quote,
  context,
  priceKnown = true,
}: {
  quote: Quote
  context: MarketContext
  /** 이 종목의 값을 받아서 세운 것인지. 아니면 `quote` 에 든 수는 자리를 지키는
   *  임시 값이라 적지 않습니다 — 헤더가 그때 값을 비우는 것과 같은 결입니다. */
  priceKnown?: boolean
}) {
  const d = quote.decimals

  /* 해외는 날마다 바뀌는 것뿐입니다 — 시가·정산가·정산일, 셋 다 현재가 응답이
     줍니다. 정산일은 정산가가 어느 날의 값인지라 정산가 바로 아래 섭니다(휴장
     뒤에는 이틀 전 값일 수 있습니다). 만기 날짜들은 안 바뀌는 값이라 품목정보에
     있습니다. 못 받은 값은 라벨만 남기고 비웁니다 — 품목정보와 같은 결입니다. */
  if (context === 'overseas') {
    return (
      /* 날마다 바뀌는 값은 위의 규격과 결이 다르라, 머리글 대신 항목 사이보다
         넓은 여백 하나로 가릅니다. */
      <div className="info-panel info-panel-daily">
        <Sheet
          rows={[
            ['시가', priceKnown ? fixed(quote.open, d) : null],
            [
              '정산가',
              priceKnown && quote.settlement !== undefined ? fixed(quote.settlement, d) : null,
            ],
            ['정산일', priceKnown ? (quote.prevSettlementDate ?? null) : null],
          ]}
        />
      </div>
    )
  }

  return (
    <div className="info-panel">
      <Sheet
        rows={[
          ['시가', fixed(quote.open, d)],
          ['상장 후 최고', fixed(quote.lifeHigh, d)],
          ['상장 후 최저', fixed(quote.lifeLow, d)],
          ['이론가', fixed(quote.theory, d)],
          ['이론베이시스', fixed(quote.basisTheory, d, true)],
          ['실제베이시스', fixed(quote.basisActual, d, true)],
          ['괴리율', `${fixed(quote.disparity, 2, true)}%`],
          ['변동성', `${fixed(quote.iv, 2)}%`],
        ]}
      />

      <InvestorTrend quote={quote} />
    </div>
  )
}

/* 투자자별 매매동향.
 *
 * **서버가 준 무리를 그대로 세웁니다** — 「기관」처럼 여럿을 합친 줄은 만들지
 * 않습니다. 합치는 규칙은 우리가 정하는 것이고, 그 줄을 보는 사람은 서버가
 * 그렇게 답한 줄로 읽습니다.
 *
 * **못 받은 것과 줄이 없는 것을 가릅니다.** 받았는데 비어 있으면 그 품목의 기록이
 * 없는 것이고, 못 받은 것은 다시 부를 만합니다. */
function InvestorTrend({ quote }: { quote: Quote }) {
  const item = resolve(quote.code)
  const product = item?.product.tradeCode ?? null
  /* 옵션은 콜·풋이 다른 답입니다. 콜풋이 아직 안 정해진 자리에서는 선물로 묻지
     않고 기다립니다 — 다른 것을 물어 온 표가 서면 안 됩니다. */
  const side = item?.leg?.side ?? item?.side ?? null
  const kind = item?.kind === 'option' ? side : 'futures'
  const trend = useTrend(kind ? product : null, kind ?? 'futures', true)

  if (trend.status === 'loading' && trend.rows === null) {
    return <p className="info-note">투자자 매매동향을 받는 중입니다</p>
  }
  if (trend.status === 'failed' && trend.rows === null) {
    return <p className="info-note">투자자 매매동향을 받지 못했습니다</p>
  }
  if (trend.rows !== null && trend.rows.length === 0) {
    return <p className="info-note">이 품목의 투자자 매매동향이 없습니다</p>
  }
  if (trend.rows === null) return null

  /* 수가 무엇을 센 것인지. **모르면 안 붙입니다** — 지어낸 단위가 붙으면 계약 수를
     금액으로 읽습니다. */
  const unit = trend.unit ? UNIT_LABEL[trend.unit] : null
  const head = (label: string) => (unit ? `${label}(${unit})` : label)

  return (
    <table className="data-table rows-base">
      <thead>
        <tr>
          <th className="col-text">투자자</th>
          <th>{head('매수')}</th>
          <th>{head('매도')}</th>
          <th>{head('순매수')}</th>
        </tr>
      </thead>
      <tbody>
        {trend.rows.map((row) => (
          <tr key={row.group}>
            {/* 표에 없는 무리가 와도 줄이 사라지지 않게 받은 열쇠를 그대로 세웁니다. */}
            <td className="col-text">{INVESTOR_LABEL[row.group] ?? row.group}</td>
            {/* 매수·매도는 **건수**라 0 이 「그만큼」이 아니라 「일어난 일이 없다」
                입니다 — 흐리게 두어 볼 것이 없다는 것을 먼저 말합니다. 순매수는
                방향 값이라 0 도 본문색입니다(본전은 뜻 있는 값입니다). */}
            <td>
              {/* 값이 없는 자리의 「—」도 흐림입니다 — 볼 것이 없다는 말이라
                  건수 0 과 같은 급입니다. */}
              <span className={`num${row.buy === null || row.buy === 0 ? ' dead' : ''}`}>
                {row.buy === null ? '—' : row.buy.toLocaleString('ko-KR')}
              </span>
            </td>
            <td>
              <span className={`num${row.sell === null || row.sell === 0 ? ' dead' : ''}`}>
                {row.sell === null ? '—' : row.sell.toLocaleString('ko-KR')}
              </span>
            </td>
            {/* 순매수는 방향 값이라 부호가 색과 함께 섭니다. **0 은 색이 없습니다** —
                빨강도 파랑도 아닌 사실이고, 0 을 한쪽 색으로 칠하면 그 방향으로
                읽힙니다. */}
            <td>
              {row.netBuy === null ? (
                <span className="num dead">—</span>
              ) : (
                <span className={`num ${row.netBuy > 0 ? 'up' : row.netBuy < 0 ? 'down' : ''}`}>
                  {row.netBuy > 0 ? '+' : row.netBuy < 0 ? '−' : ''}
                  {Math.abs(row.netBuy).toLocaleString('ko-KR')}
                </span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
