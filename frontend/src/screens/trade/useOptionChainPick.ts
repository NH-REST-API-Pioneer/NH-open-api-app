import { useMemo, useState } from 'react'
import type { MarketContext, PendingAxis } from '../../lib/types'
import { useOptionChain, type ChainArgs } from '../../data/optionChain'
import {
  contractsOf,
  defaultContractCode,
  needsLeg,
  productsOf,
  strikeDecimalsOf,
  type Instrument,
  type OptionLeg,
} from '../../data/instruments'
import type { ChainPick, ChainSide } from './OptionChain'
import { useSession } from '../../data/session'
import { DOMESTIC_PRESETS, NIGHT_PRESETS, OVERSEAS_PRESETS } from './chainFields'
import { type Tab, overseasSeriesCode } from './tradeScreenUtils'

/** 옵션 체인에서 고른 칸(콜/풋·행사가)과 그 체인을 세우는 데 드는 값. */
export function useOptionChainPick({
  subject,
  contextOf,
  context,
  credentialsMissing,
  tab,
  activeOverseas,
}: {
  subject: Instrument | null
  contextOf: (item: Instrument | null) => MarketContext
  context: MarketContext
  credentialsMissing: (item: Instrument | null) => boolean
  tab: Tab
  activeOverseas: boolean
}) {
  /* 체인에서 고른 칸. 고르기 전에는 없고, 그동안 헤더·호가·주문은 기초
     선물을 봅니다 — 옵션 탭을 눌렀다고 임의의 행사가를 골라주지 않습니다.
     축 둘(콜풋·행사가)만 들고 있고 값은 체인에서 찾습니다 — 값을 복사해 두면
     체인이 갱신될 때 헤더가 낡은 값을 들고 있게 됩니다.

     **두 축을 따로 듭니다.** 한 상태로 묶으면 한쪽만 골라도 나머지가 기본값으로
     채워져, 고른 적 없는 값으로 종목이 정해지고 주문 폼에 실립니다. 둘 다
     정해져야 종목입니다.

     **어느 쪽을 먼저 골라도 나머지를 채우지 않습니다.** 등가(ATM)를 채워 두면
     그 순간 주문 단추가 살아나, 사용자가 고른 적 없는 행사가로 주문을 낼 수 있는
     상태가 됩니다 — 반대 축(행사가를 먼저 고른 경우)은 막혀 있으므로 두 축의
     안전성도 달라집니다. 체인 칸만 한 번에 둘 다 정합니다: 거기서는 콜/풋과
     행사가가 한 칸에 있어 누른 것 자체가 두 축을 다 고른 것입니다. */
  const [pickedSide, setPickedSide] = useState<'call' | 'put' | null>(null)
  const [pickedStrike, setPickedStrike] = useState<number | null>(null)
  const [preset, setPreset] = useState(0)
  const [chainSide, setChainSide] = useState<ChainSide>('both')

  /* 체인이 설 옵션 품목. 지금 보는 종목이 옵션이면 **그 종목의 품목**입니다 —
     「미니 코스피200 옵션」을 골랐는데 체인에 「코스피200 옵션」이 서면 고른
     것과 보이는 것이 갈립니다. 선물을 보는 동안에는 **그 종목이 선 시장의**
     옵션 품목이 기본으로 섭니다 — 화면이 어느 시장에서 시작했는지가 아니라
     지금 보고 있는 종목이 어느 시장인지를 따릅니다. */
  const optionProduct = useMemo(
    () =>
      subject?.kind === 'option'
        ? subject.product
        : (productsOf(contextOf(subject) === 'overseas' ? 'overseas' : 'domestic').find(
            (item) => item.kinds.includes('option'),
          ) ?? null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [context, subject],
  )
  /* 체인이 설 만기 줄. 고른 옵션의 만기가 있으면 그것입니다 — 12월물 옵션을
     골랐는데 9월물 체인이 서면 고른 것과 보이는 것이 갈립니다. */
  const chainRef =
    subject?.kind === 'option' && subject.contract
      ? subject.contract
      : optionProduct
        ? (contractsOf(optionProduct, 'option')[0] ?? null)
        : null
  /* 국내는 만기일(8자리), 해외는 만기 연월(6자리)이고, 한 달에 만기가
     여럿인 품목은 해외도 만기일입니다. */
  const chainExpiry = chainRef?.expiry ?? null
  /* 체인을 부를 때 보낼 시리즈 코드. **값만 들고 다닙니다** — 줄 그대로
     들면 매번 새 객체가 되어 체인 조회가 다시 나갑니다. */
  const chainSeries = chainRef?.seriesCode ?? null
  const chainOverseas = optionProduct !== null && contextOf(subject) === 'overseas'
  /* 국내 체인은 세션을 함께 묻습니다 — 야간에는 야간 체인입니다. 세션은 종목마다
     서버가 답하므로 **그 품목의 기본 선물**로 묻습니다(옵션 만기 줄에는 세션이
     없습니다). */
  const chainMissing = credentialsMissing(subject)
  const chainAnchor =
    optionProduct && !chainOverseas && !chainMissing
      ? (defaultContractCode('domestic', optionProduct.code, 'futures') ?? '')
      : ''
  const chainSession = useSession('domestic', chainAnchor)
  /* 무엇을 물을지. 국내는 품목의 거래대상코드·만기일·세션, 해외는 거래소 코드·
     시리즈 코드입니다. 마스터가 그 값을 안 주면 못 묻고, 체인은 「받는 중」에
     머뭅니다 — 지어낸 인자로 다른 것을 받아 오지 않습니다. */
  const chainArgs = useMemo((): ChainArgs | null => {
    if (!optionProduct || !chainExpiry || chainMissing) return null
    if (chainOverseas) {
      /* 색인이 시리즈 코드를 주면 그것을 그대로 보냅니다 — 한 달에
         만기가 여럿인 품목은 만기년월로 지으면 아홉이 한 코드로 뭉칩니다. */
      const sym = chainSeries ?? overseasSeriesCode(optionProduct.code, chainExpiry)
      return optionProduct.exchangeCode && sym
        ? { market: 'overseas', exchCd: optionProduct.exchangeCode, sym }
        : null
    }
    if (!optionProduct.tradeCode || chainExpiry.length !== 8) return null
    return {
      market: 'domestic',
      prd: optionProduct.tradeCode,
      expMon: chainExpiry.slice(2),
      session: chainSession.session === 'night' ? 'night' : 'day',
    }
  }, [optionProduct, chainExpiry, chainSeries, chainOverseas, chainSession.session, chainMissing])
  /* 그 체인이 어느 품목·만기의 것인지. 서버에 보내는 값이 아니라, 답에 실려 온
     해외 옵션 종목코드를 신원표에 적을 때 씁니다(`data/optionChain.ts`). */
  const chainOwner = useMemo(
    () => (optionProduct && chainExpiry ? { productCode: optionProduct.code, expiry: chainExpiry } : null),
    [optionProduct, chainExpiry],
  )
  /* 체인 탭이 보이는 동안만 5초마다 다시 묻습니다(`data/optionChain.ts`). 체인
     탭은 옵션에만 있어, 선물을 보는 동안 탭 값이 남아 있어도 묻지 않습니다. */
  const chain = useOptionChain(chainArgs, chainOwner, tab === '체인' && subject?.kind === 'option')
  const chainRows = chain.rows ?? []

  const strikes = useMemo(() => chainRows.map((row) => row.strike), [chainRows])
  /* 기초 선물과 등가격. 국내 주간은 당월 선물 현재가에 가장 가까운 행사가이고,
     해외는 서버가 표시한 줄입니다. 야간처럼 둘 다 없으면 표시가 없습니다. */
  const futuresPrice = chain.future?.last ?? null
  const atm = useMemo(() => {
    if (futuresPrice !== null && chainRows.length > 0) {
      return chainRows.reduce((best, row) =>
        Math.abs(row.strike - futuresPrice) < Math.abs(best.strike - futuresPrice) ? row : best,
      ).strike
    }
    return chainRows.find((row) => row.call.atm || row.put.atm)?.strike ?? null
  }, [chainRows, futuresPrice])
  /* **체인이 실제로 쓰는 행사가 축**에서 셉니다. 품목의 값 자리 수로 어림하면
     반 칸씩 놓인 행사가가 반올림돼 적히고, 그 글자로 줄을 찾는 자리에서는 다른
     계약이 열립니다. */
  const strikeDecimals = useMemo(() => strikeDecimalsOf(strikes), [strikes])
  /* 둘 다 정해졌을 때만 종목입니다. 한쪽만 고른 상태는 「아직 고르는 중」이라
     헤더·차트·주문 폼이 기초 선물을 봅니다. */
  const pickedRow =
    pickedStrike !== null ? chainRows.find((row) => row.strike === pickedStrike) : undefined
  const pickedLeg =
    pickedRow && pickedSide ? (pickedSide === 'call' ? pickedRow.call : pickedRow.put) : null
  const pickedLabel =
    pickedSide && pickedStrike !== null
      ? `${pickedSide === 'call' ? '콜' : '풋'} ${pickedStrike.toFixed(strikeDecimals)}`
      : ''
  /* 아직 안 고른 축. 행사가가 남았으면 그것부터 말합니다 — 체인이 행사가로
     늘어서 있어 다음에 할 일이 그쪽입니다. */
  /* 축 둘을 한 번에 정하는 자리. 체인 칸과 밖에서 들어온 코드가 여기를 지납니다 —
     둘 다 「콜 425.0」처럼 한 종목을 통째로 가리키므로 갈라 넣을 것이 없습니다. */
  const pickLeg = (leg: OptionLeg | null) => {
    setPickedSide(leg?.side ?? null)
    setPickedStrike(leg?.strike ?? null)
  }
  /* 체인 칸은 콜/풋과 행사가가 한 칸에 있으므로 한 번에 둘 다입니다. **체인이 준
     원본 값을 그대로** 받습니다 — 화면에 적힌 글자를 되읽지 않습니다. */
  const pickFromChain = (pick: ChainPick) => pickLeg({ side: pick.side, strike: pick.strike })
  /* 코드에서 읽는 길. **코드가 콜/풋까지만 말해 주는 경우가 있습니다** — 국내
     옵션 종목코드가 그렇고, 그때 콜/풋을 버리면 사용자가 코드에 적어 넣은 것을
     화면이 다시 물어봅니다. 행사가는 색인에 없어 그대로 남습니다. */
  const pickFromCode = (item: Instrument | null) => {
    setPickedSide(item?.leg?.side ?? item?.side ?? null)
    setPickedStrike(item?.leg?.strike ?? null)
  }

  /* **코드가 아직 계약이 아닐 때만** 「고르는 중」입니다. 고른 축이 없다고 해서
     고르는 중인 것은 아닙니다 — 국내 옵션 종목코드는 상장된 계약인데 마스터에
     행사가 칸이 없어, 체인을 열기 전에는 행사가를 모른 채로 섭니다. 그때까지
     「고르는 중」으로 두면 이미 고른 종목을 화면이 다시 물어봅니다. */
  /* 체인 표가 「고른 줄」로 볼 코드. **주문 대상 종목(`subject`)에서 꺼냅니다** —
     두 칸으로 나눠 놓고 둘째 칸이 주문 대상일 때 첫째 칸의 코드로 견주면, 표가
     남의 줄을 켜거나 켤 줄을 못 찾아 등가격으로 떨어집니다. */
  const subjectCode = subject?.contract?.code ?? ''
  const chainPickedCode =
    pickedLeg?.code ??
    (subject?.kind === 'option' && !needsLeg(subjectCode) ? subjectCode || null : null)

  const pendingAxis: PendingAxis | null =
    subject?.kind === 'option' && needsLeg(subjectCode) && !pickedLeg
      ? pickedStrike === null
        ? 'strike'
        : 'side'
      : null

  /* 야간 답이면 야간 묶음 하나입니다 — 주간 묶음의 열이 통째로 빕니다. 고른 묶음
     번호는 그대로 두어 주간으로 돌아오면 보던 묶음이 다시 섭니다. */
  const presets = activeOverseas
    ? OVERSEAS_PRESETS
    : chain.session === 'night'
      ? NIGHT_PRESETS
      : DOMESTIC_PRESETS
  const activePreset = presets[Math.min(preset, presets.length - 1)]

  return {
    pickedSide,
    setPickedSide,
    pickedStrike,
    setPickedStrike,
    setPreset,
    chainSide,
    setChainSide,
    optionProduct,
    chainArgs,
    chainOwner,
    chain,
    chainRows,
    strikes,
    futuresPrice,
    atm,
    strikeDecimals,
    pickedLeg,
    pickedLabel,
    pickFromChain,
    pickFromCode,
    chainPickedCode,
    pendingAxis,
    presets,
    activePreset,
  }
}
