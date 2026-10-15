/** 종목 하나를 차트·헤더가 읽는 한 벌로 세우는 자리.
 *
 *  시세 저장소(`data/quotes.ts`)는 **받은 값**을 담고, 여기는 그 값을 종목의
 *  신원과 묶어 화면이 그대로 그릴 수 있는 꼴로 만듭니다. 둘을 한 자리에 두면
 *  값이 한 번 움직일 때마다 신원까지 다시 계산됩니다.
 */
import { useMemo } from 'react'

import { displayTickOf, type Instrument } from './instruments'
import { useProductInfo } from './productInfo'
import { applyPrice, useQuoteEntry, type QuoteEntry } from './quotes'
import type { ChainLeg, MarketContext, PendingAxis, ProductKind, Quote } from '../lib/types'

/** 아직 아무 값도 없는 시세 한 벌.
 *
 *  **숫자 자리를 전부 비웁니다.** 종목의 신원과 품목이 정하는 것(자릿수·통화·
 *  거래승수·호가단위·분수)만 마스터에서 채우고, 시세로 오는 칸은 `null` 입니다 —
 *  자리를 채우려고 지어낸 숫자를 한 번 세우면 사용자는 그것을 이 종목의 값으로
 *  읽고, 주문가격 칸까지 거기서 나옵니다. 값은 조회 답이 와서 `applyPrice` 가
 *  얹습니다(`data/quotes.ts`). */
function blankQuote(fields: {
  market: MarketContext
  code: string
  name: string
  productName: string
  kind?: ProductKind
  decimals: number
  currency: string
  multiplier?: number | null
  daysLeft?: number | null
  fraction?: number | null
  tickSize?: number | null
}): Quote {
  return {
    market: fields.market,
    code: fields.code,
    name: fields.name,
    productName: fields.productName,
    kind: fields.kind ?? 'futures',
    decimals: fields.decimals,
    fraction: fields.fraction ?? null,
    tickSize: fields.tickSize ?? null,
    daysLeft: fields.daysLeft ?? null,
    multiplier: fields.multiplier ?? null,
    currency: fields.currency,
    last: null,
    change: null,
    changePct: null,
    open: null,
    high: null,
    low: null,
    volume: null,
    turnover: null,
    openInterest: null,
    openInterestChange: null,
  }
}

/** 종목이 지금 얼마인가. **신원과 갈라 둡니다.**
 *
 *  품목·만기·종류·시장은 하루 동안 안 바뀌고, 시세는 초당 여러 번 바뀝니다.
 *  한 곳에서 둘을 같이 돌려주면 값이 한 번 움직일 때마다 만기 목록과 주문유형
 *  목록, 미결제약정 필터까지 다시 계산됩니다.
 *
 *  마스터가 아는 것(이름·자릿수·통화·거래승수·호가단위)을 먼저 깔고, 조회 답이
 *  오면 그 위에 숫자를 얹습니다. 답이 아직이거나 못 받았으면 깔아 둔 것이 그대로
 *  남아 값 자리가 「—」로 섭니다 — 무엇이 빠졌는지는 함께 돌려주는 `entry` 가
 *  말합니다.
 *
 *  **차트를 그리는 화면이 모두 이것을 씁니다**(일반주문·전략 검증). 화면마다
 *  제 나름으로 지으면 같은 종목이 화면에 따라 다른 이름·자릿수로 섭니다. */
export function useQuote(
  selected: Instrument | null,
  context: MarketContext,
  leg: ChainLeg | null,
  legLabel: string,
  /** 옵션인데 아직 안 고른 축. 화면 셋이 이 값으로 같은 말을 냅니다. */
  pendingAxis: PendingAxis | null = null,
  /** 그 시장의 인증 정보가 없어 **묻지 않는지**. 빈 키로 물으면 토큰 발급부터
   *  실패해 오류만 남습니다. */
  withheld = false,
): { quote: Quote; entry: QuoteEntry; asked: boolean; built: boolean; unasked: boolean } {
  /* 두 시장 다 서버에서 받습니다. 옵션에서 행사가를 안 골랐으면 종목이 아직
     없으므로 안 부릅니다. **고른 다리가 있으면 그 종목코드**로 묻습니다 — 체인
     줄이 실제 코드를 들고 있고, 만기 줄의 코드는 종목이 아닙니다. */
  const asked = !pendingAxis && !withheld ? (leg?.code || selected?.contract?.code || '') : ''
  /* 안 묻는 것은 인증 정보가 없는 시장 하나뿐입니다. 그 밖에 값이 안 서는 까닭은
     못 받음·거절·값 없음 셋입니다. */
  const unasked = withheld && selected !== null
  const entry = useQuoteEntry(asked)

  /* 국내 호가단위는 **품목 표에서만** 옵니다 — 국내 종목 마스터에 그 칸이
     없습니다. 해외는 마스터가 종목마다 주므로 안 부릅니다(빈 코드를 넘겨
     막습니다). 종목이 정해질 때 한 번 부르고, 그 뒤로는 담아 둔 값입니다. */
  const info = useProductInfo(selected?.market === 'domestic' ? asked : '')
  const askedTick = info.row?.tickSize ?? null

  const placeholder = useMemo(() => {
    /* 코드를 아직 못 푼 자리(마스터를 받는 중이거나 상장이 끝난 코드)입니다.
       그 시장의 대표 종목을 대신 세우지 않습니다 — 이름도 값도 이 화면이 보고
       있는 것이 아닙니다. */
    if (!selected) {
      return blankQuote({
        market: context,
        code: '',
        name: '',
        productName: '',
        decimals: 2,
        currency: context === 'overseas' ? 'USD' : '원',
      })
    }

    const base = blankQuote({
      market: context,
      /* 만기까지 붙은 이름입니다. 배지·주문 단추·호가 머리·주문 내역 표가 이
         이름을 읽으므로, 품목 이름만 넣으면 그 넷이 만기를 잃습니다. */
      code: selected.contract?.code ?? selected.product.code,
      name: selected.name,
      /* 헤더 제목입니다. **스프레드만 마스터 원문**을 세웁니다 — 두 다리를 한
         이름에 담는 표기는 거래소가 짓는 것이고, 우리가 다시 지으면 주문 내역·
         체결 통보에 적힌 이름과 갈립니다. 우리 말로 적은 두 만기는 제목 아래
         한 줄로 따로 섭니다. */
      productName:
        selected.contract?.kind === 'spread' && selected.contract.masterName
          ? selected.contract.masterName
          : selected.product.name,
      kind: selected.kind,
      decimals: selected.product.decimals ?? 2,
      currency: selected.market === 'overseas' ? 'USD' : '원',
      multiplier: selected.product.multiplier,
      daysLeft: selected.contract?.daysLeft ?? null,
      /* 분수로 부르는 품목(국채·곡물 등 해외 23)이면 값 그리는 자리가 그렇게
         적습니다. 소수로 부르는 품목에서는 `null` 입니다. */
      fraction: selected.product.fraction,
      /* 호가 사다리와 가격 칸 화살표가 한 단을 이 값으로 짓습니다.

         **마스터가 먼저입니다.** 해외는 마스터가 종목마다 호가단위를 주고,
         값을 적는 단위로 맞추는 손질(`displayTickOf` — 값은 센트로 부르는데
         마스터가 달러로 실어 주는 품목)까지 그 자리에서 끝납니다. 국내는 그
         칸이 마스터에 없어 품목 표에서 받은 값이 대신 섭니다. 둘 다 없으면
         `null` 이고, 그때 화면은 눈금을 모른다고 말합니다. */
      tickSize: displayTickOf(selected.product) ?? askedTick,
    })

    if (selected.kind !== 'option') return base

    /* 행사가를 고르기 전에는 **아직 종목이 아닙니다.** 이름과 코드는 옵션 품목의
       것이고 값 자리는 빈 채입니다 — 기초 선물의 값을 대신 세우면 「주문 대상」
       자리에 다른 종목의 가격이 서고, 화면 셋이 `pendingAxis` 로 「무엇을 아직
       안 골랐나」를 말합니다. */
    if (!leg) return { ...base, pendingAxis: pendingAxis ?? 'strike' }

    /* 고른 다리. **체인이 실어 온 값을 그대로 씁니다** — 받은 값이라 지어낸
       것이 아니고, 그 다리의 조회 답이 오면 `applyPrice` 가 덮습니다. 체인에
       없는 칸(시가·고가·저가·거래대금)은 빈 채로 두어 「—」로 섭니다. */
    return {
      ...base,
      code: leg.code,
      name: `${selected.product.name} ${legLabel}`,
      last: leg.last,
      change: leg.change,
      changePct: leg.changePct,
      volume: leg.volume,
      openInterest: leg.openInterest,
      openInterestChange: leg.oiChange,
      theory: leg.theo ?? undefined,
      disparity: leg.disparity ?? undefined,
      iv: leg.iv ?? undefined,
    }
  }, [selected, context, leg, legLabel, pendingAxis, askedTick])

  /* 받아 온 숫자를 얹습니다. 못 받았거나 얹을 수 없으면 임시 값이 그대로
     남습니다 — 화면은 `entry` 를 보고 그 자리가 「받는 중」인지 「못 받았다」인지
     말합니다.

     **잠그는 것은 「받는 중인가」가 아니라 「이 종목의 값이 있는가」입니다.**
     저장소는 종목마다 따로 담으므로 여기 있는 `price` 는 언제나 이 종목의
     것이고, 다시 받는 동안에도 지우지 않습니다(`data/quotes.ts`). 그런데
     받는 중이라고 화면이 값을 버리면, **홈에서 값이 선 종목을 주문 화면에서
     열 때마다** 헤더가 한 번 비었다가 다시 찹니다 — 홈이 현재가만 받아 두므로
     그 화면은 호가·분봉을 채우러 다시 부릅니다. 저장소가 「잠깐 사라지는 쪽이
     더 나쁘다」고 지켜 둔 값을 화면이 버리는 셈이라, 같은 기준으로 맞춥니다.
     종목을 바꾸면 그 자리는 애초에 비어 있어 앞 종목 값이 남지 않습니다. */
  const built = useMemo(
    () => (entry.price ? applyPrice(placeholder, entry.price) : null),
    [placeholder, entry],
  )

  const shown = built ?? placeholder
  const quote = useMemo(() => (unasked ? { ...shown, withheld: true } : shown), [shown, unasked])
  return { quote, entry, asked: asked !== '', built: built !== null, unasked }
}
