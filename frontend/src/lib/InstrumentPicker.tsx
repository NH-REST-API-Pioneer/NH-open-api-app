import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import type { MarketContext, Product, ProductKind } from './types'
import {
  contractRows,
  expiryPaperNight,
  useExpiryQuoteUpdates,
  useExpiryQuotes,
} from '../data/expiryQuotes'
import { productsOf } from '../data/instruments'
import { contractsOf, resolve, searchTextOf, type ContractRef, type Market } from '../data/instruments'
import { KIND_LABEL, MARKET_LABEL, MARKETS as MARKET_LIST } from './instrumentSearch'
import './instrumentPicker.css'

/* 종목 고르기 — 국내·해외·스프레드를 한 자리에서.
 *
 * **부르는 쪽이 무엇을 고르는지 정합니다.** 차트 칸은 그 칸의 종목을 바꾸고,
 * 전략 설정은 그 전략이 거래할 종목을 고릅니다 — 판은 같고 고른 것을 어디에
 * 쓰는지만 다릅니다. 두 화면이 제 나름의 검색을 두면 같은 종목이 화면에 따라
 * 다르게 찾아집니다.
 *
 * **고르는 것이 종목인 자리와 품목인 자리가 있습니다.** 차트는 월물까지 정해야
 * 값이 오므로 종목 모드이고, 전략은 「무엇을 거래하나」만 정한 뒤 어느 달인가는
 * 따로 두므로 품목 모드입니다(`mode="product"`). 품목 모드에서는 월물 칩도 만기
 * 표시도 서지 않습니다 — 여기서 고르는 것이 월물이 아니라서, 보이면 누른 월물이
 * 버려진 것처럼 읽힙니다.
 *
 * 위에 「이 종목의 다른 만기」 칩을 두는 것은, 같은 품목의 근월·차월을 나란히
 * 놓는 것이 두 차트의 가장 흔한 쓰임이기 때문입니다. 아래 검색은 시장을
 * 가리지 않습니다 — 국내와 해외를 나란히 보는 것도 막지 않습니다.
 */

/** 고른 종목. 차트 한 칸이 들고 있는 것이 이것입니다. */
export interface InstrumentRef {
  code: string
  /** 만기까지 붙인 전체 이름. 배지·알약·주문 단추에 씁니다. */
  name: string
  /** 품목 이름. 헤더의 제목 자리입니다. */
  productName: string
  market: MarketContext
  /** 배지에 적을 현재가. **아직 값이 없으면 `null`** 이고 그 자리는 빈 채입니다 —
   *  대신 세울 숫자가 없습니다. */
  lastPrice: number | null
  decimals: number
  currency: string
}

/** 고른 품목. **월물이 없습니다** — 품목 모드가 답하는 것은 「무엇을 거래하나」
 *  하나이고, 어느 달인가는 부르는 쪽의 다른 칸이 답합니다. */
export interface ProductRef {
  productCode: string
  productKind: ProductKind
  market: Market
  /** 품목 이름. 부르는 쪽의 칸에 적히는 것이 이것입니다. */
  productName: string
}

interface CommonProps {
  onClose: () => void
}

/** 종목 모드 — 월물까지 고릅니다. */
interface InstrumentProps extends CommonProps {
  mode?: 'instrument'
  /** 지금 이 칸의 종목 코드. 만기 칩도 검색 폴백도 여기서 나옵니다 —
   *  같은 것을 고르면 아무 일도 안 합니다. */
  current: string
  onPick: (item: InstrumentRef) => void
}

/** 품목 모드 — 품목과 갈래까지만 고릅니다. */
interface ProductProps extends CommonProps {
  mode: 'product'
  /** 지금 이 칸의 품목·갈래. 아직 안 골랐으면 `null` 이고, 눌린 줄이 서지 않습니다. */
  current: ProductRef | null
  /** 검색어가 없을 때 세울 시장. 국내 전략을 고치는 사람 앞에 해외 품목이 먼저
   *  서면 목록이 길기만 하고 고를 것이 안 보입니다. */
  market: Market
  onPick: (item: ProductRef) => void
}

type Props = InstrumentProps | ProductProps

/* 만기 표시를 짧게. 「2609」이고, 날 단위 품목은 「2609-17」입니다.
   한 달에 만기가 여럿인 품목은 날까지 남겨야 칩끼리 갈립니다 — 월까지만 적으면
   아홉 칸이 모두 「2609」로 서서 어느 것을 고르는지가 칩에 안 남습니다.

   **화면에 선 이름이 아니라 종목이 들고 있는 값에서 짓습니다.** 이름을 다시
   읽어 숫자를 뽑으면 이름 짓는 규칙이 바뀌는 날 칩만 조용히 옛 모양으로
   남습니다. */
function shortMonth(item: ContractRef, byDay: boolean): string {
  const digits = (item.expiryDate ?? item.expiry).replace(/\D/g, '')
  const month = digits.slice(2, 6)
  return byDay && digits.length >= 8 ? `${month}-${digits.slice(6, 8)}` : month
}

const MARKETS: MarketContext[] = ['domestic-day', 'overseas']

/** 목록 한 줄. 고를 종목과, 그 줄에 붙는 표시 둘입니다.
 *
 *  **표시를 `InstrumentRef` 에 안 싣습니다** — 고른 종목은 차트 칸이 그대로
 *  들고 다니며 저장까지 되는 값이고, 이 둘은 목록에서만 쓰는 화면 값입니다. */
interface PickRow {
  item: InstrumentRef
  /** 마스터가 주력으로 표시한 월물인가(해외 선물 `lmon`). 붙는 낱말이 갈립니다. */
  main: boolean
  /** 표시를 달 줄인가 — 주력이거나, 주력 축이 없는 시장에서 만기가 가장 가까운 줄. */
  tagged: boolean
  /** **비워 두고 열면 서는 줄인가.** 초록은 이 뜻이라 한 품목에 하나뿐입니다. */
  opens: boolean
  /** 값이 주간 마감인 줄인가(국내 야간에 야간 값을 안 받은 월물). 수를 흐리게 세웁니다. */
  closeOnly: boolean
}

/** 품목 모드의 한 줄. **품목 하나에 갈래 하나**입니다 — 한 품목이 선물·옵션·
 *  스프레드를 함께 가지므로, 품목 이름만으로는 무엇을 거래하는지가 안 정해집니다. */
interface ProductPickRow {
  market: Market
  product: Product
  kind: ProductKind
}

/** 한 품목의 줄 묶음. **묶어 두는 까닭은 코드 때문입니다** — 같은 품목의 갈래
 *  줄마다 코드를 되풀이하면 한 품목이 여러 품목처럼 보입니다. 코드는 묶음의 첫
 *  줄에만 답니다. */
interface ProductBlock {
  product: Product
  rows: ProductPickRow[]
}

/** 시장 한 덩이. 검색 결과도 **검색어가 없을 때와 같은 꼴**로 시장마다 묶습니다 —
 *  한 목록에 두 시장이 섞여 서면 같은 이름의 국내·해외 품목이 구별되지 않습니다. */
interface MarketGroup {
  market: Market
  blocks: ProductBlock[]
}

/** 줄 수로 자릅니다. **품목 묶음째 자릅니다** — 줄 수로 자르면 묶음 가운데가
 *  끊겨, 코드 없는 갈래 줄만 남은 품목이 목록 끝에 섭니다. */
function cut(blocks: ProductBlock[], max: number): ProductBlock[] {
  const kept: ProductBlock[] = []
  let count = 0
  for (const block of blocks) {
    if (count >= max) break
    kept.push(block)
    count += block.rows.length
  }
  return kept
}

export function InstrumentPicker(props: Props) {
  const { onClose } = props
  const productMode = props.mode === 'product'
  const ref = useRef<HTMLDivElement>(null)
  const [query, setQuery] = useState('')

  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose()
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey, true)
    }
  }, [onClose])

  /* 「이 종목의 다른 만기」 — **지금 이 칸에 선 종목**의 품목과 종류에서
     나옵니다. 시장에서 뽑으면 무엇을 보고 있든 같은 목록이 서서, 코스닥150을
     보다가 칩을 누르면 코스피200이 나옵니다. */
  /* 종목 모드에서만 쓰는 값들입니다. **훅은 그대로 부르고 끄기만 합니다** —
     모드에 따라 훅을 건너뛰면 한 판에서 훅 차례가 달라집니다. */
  const currentCode = props.mode === 'product' ? '' : props.current
  const here = useMemo(() => (currentCode ? resolve(currentCode) : null), [currentCode])
  /* **열려 있는 동안 지금 종목의 품목만** 값을 받습니다. 검색 결과에 걸리는 품목을
     다 부르면 한 번 치는 사이에 조회가 수십 건 나갑니다 — 그 품목들의 값 자리는
     빈 채로 두고, 고르면 그때 그 품목을 부릅니다. 품목 모드는 값을 안 세우므로
     아무것도 안 부릅니다. */
  useExpiryQuotes(here?.product ?? null, here?.kind ?? 'futures', !productMode)
  /* 값이 오면 목록을 다시 그립니다. */
  const quoteTick = useExpiryQuoteUpdates()
  /* 지금 품목이 모의투자의 국내 야간이라 값을 안 받는가. 목록을 다시 셈할 때 함께 봅니다. */
  const paperNight = !!here && !productMode && expiryPaperNight(here.product, here.kind)
  const months = useMemo(
    () => (here && !productMode ? contractsOf(here.product, here.kind) : []),
    [here, productMode],
  )
  /* 칩에 날까지 적을지는 **품목이 정합니다** — 만기 목록의 이름을 정하는 것과
     같은 값이라 둘이 갈리지 않습니다. */
  const byDay = here?.product.expiryUnit === 'day'

  /* 검색 결과. 걸리는 품목의 모든 종목을 폅니다. 비어 있으면 앞쪽 몇 품목의
     기본 월물만 보여 줍니다 — 빈 목록은 무엇을 칠 수 있는지 말해 주지
     않습니다. */
  const rows = useMemo(() => {
    if (productMode) return []
    const term = query.trim().toLowerCase()
    const out: PickRow[] = []
    for (const market of MARKETS) {
      for (const product of productsOf(market === 'overseas' ? 'overseas' : 'domestic')) {
        /* 이 목록은 차트 칸에 올릴 종목이라 옵션·스프레드는 빼고 선물만 세웁니다. */
        if (!product.kinds.includes('futures')) continue
        if (term && !searchTextOf(product).includes(term)) continue
        const contracts = contractRows(product, 'futures')
        /* 이 품목의 기본 월물 — **마스터가 주력으로 표시한 월물**입니다(해외
           선물 `lmon`). 근월이 한산하고 분기물에 거래가 실리는 상품에서 근월을
           세우면, 비워 두고 연 사람이 거래가 거의 없는 월물을 봅니다.
           주력 표시가 없는 시장·품목(국내 전부)에서는 만기가 가장 가까운 종목이고,
           그것도 없으면 첫 줄입니다. */
        const front =
          contracts.find((row) => row.main) ?? contracts.find((row) => row.frontMonth) ?? contracts[0]
        /* 검색어가 품목에 걸리면 **월물은 다 세우되 기본 월물을 맨 위**로 올립니다.
           한 줄만 남기면 특정 월물을 보러 온 사람의 길이 막히고, 받은 순서(만기
           순)를 그대로 두면 Enter 가 거래가 거의 없는 근월을 엽니다. 만기가 가장
           가까운 월물이 곧 기본인 품목(국내 전부)에서는 순서가 안 바뀝니다. */
        const picked = term
          ? front
            ? [front, ...contracts.filter((row) => row !== front)]
            : contracts
          : front
            ? [front]
            : []
        for (const row of picked) {
          out.push({
            main: row.main,
            tagged: row.main || row.frontMonth,
            opens: row === front,
            closeOnly: row.closeOnly === true,
            item: {
              code: row.code,
              name: row.name,
              productName: product.name,
              market,
              lastPrice: row.last,
              decimals: product.decimals ?? 2,
              currency: market === 'overseas' ? 'USD' : '원',
            },
          })
        }
      }
    }
    return out.slice(0, 40)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, quoteTick, productMode])

  /* 품목 모드의 목록. **월물을 안 폅니다** — 품목 하나가 갈래마다 한 줄로 서고,
     값 칸도 만기 표시도 없습니다. 고르고 나서 어느 달인가는 부르는 쪽의 월물
     칸이 묻습니다. */
  const listMarket: Market = props.mode === 'product' ? props.market : 'domestic'
  /* 지금 칸에 선 품목인가. **갈래까지 견줍니다** — 같은 품목의 선물과 옵션은
     다른 줄이라, 품목만 맞춰 보면 둘 다 눌린 것으로 섭니다. */
  const isHere = (row: ProductPickRow) =>
    props.mode === 'product' &&
    props.current !== null &&
    props.current.market === row.market &&
    props.current.productCode === row.product.code &&
    props.current.productKind === row.kind

  const productGroups = useMemo(() => {
    if (!productMode) return []
    const term = query.trim().toLowerCase()
    const out: MarketGroup[] = []
    /* 검색어가 없으면 **지금 시장**만 세웁니다. 글자를 치면 두 시장을 다 훑습니다 —
       시장을 바꾸려고 이 칸을 여는 경우도 막지 않습니다. */
    for (const market of term ? MARKET_LIST : [listMarket]) {
      const blocks: ProductBlock[] = []
      for (const product of productsOf(market)) {
        if (term && !searchTextOf(product).includes(term)) continue
        blocks.push({
          product,
          rows: product.kinds.map((kind) => ({ market, product, kind })),
        })
      }
      /* **지금 칸에 선 품목을 맨 위로.** 목록은 이름 순이고 길이가 잘리므로, 그대로
         두면 이미 고른 품목이 잘려 나간 뒤에 서서 「내가 고른 것이 목록에 없다」로
         읽힙니다. 찾는 글자를 친 뒤에는 걸린 것이 곧 답이라 안 올립니다. */
      const head = term ? -1 : blocks.findIndex((block) => block.rows.some(isHere))
      if (head > 0) blocks.unshift(...blocks.splice(head, 1))
      if (blocks.length > 0) out.push({ market, blocks: cut(blocks, 40) })
    }
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productMode, query, listMarket, props.mode === 'product' ? props.current : null])

  /* Enter 가 여는 줄 — 맨 위 시장의 맨 위 품목, 그 첫 갈래입니다. */
  const productHead = productGroups[0]?.blocks[0]?.rows[0] ?? null

  const pickProduct = (row: ProductPickRow) => {
    if (props.mode !== 'product') return
    props.onPick({
      productCode: row.product.code,
      productKind: row.kind,
      market: row.market,
      productName: row.product.name,
    })
  }


  /* 종목 모드의 고르기. 갈래가 갈린 props 라 부르는 자리마다 좁히지 않고
     여기서 한 번만 좁힙니다. */
  const pickInstrument = (item: InstrumentRef) => {
    if (props.mode === 'product') return
    props.onPick(item)
  }

  const pickMonth = (month: { code: string; label: string }) => {
    if (props.mode === 'product') return
    const onPick = props.onPick
    /* 같은 품목의 다른 만기는 검색 결과에도 있어 값을 거기서 찾습니다. */
    const found = rows.find((row) => row.item.code === month.code)
    if (found) onPick(found.item)
    else if (here) {
      /* 검색 목록에 없으면 이 종목의 품목에서 직접 찾습니다 — 어느 경우에도
         지금 보고 있는 종목의 만기이지 다른 품목의 만기가 아닙니다. */
      const market: MarketContext = here.market === 'overseas' ? 'overseas' : 'domestic-day'
      const contract = contractRows(here.product, here.kind).find((row) => row.code === month.code)
      if (contract) {
        onPick({
          code: contract.code,
          name: contract.name,
          productName: here.product.name,
          market,
          lastPrice: contract.last,
          decimals: here.product.decimals ?? 2,
          currency: here.market === 'overseas' ? 'USD' : '원',
        })
      }
    }
  }

  return (
    <div
      className="pick-popover"
      role="dialog"
      aria-label={productMode ? '고를 품목' : '이 차트의 종목'}
      ref={ref}
      /* 팝오버 안을 눌러도 칸의 주문 대상은 안 바뀝니다. */
      onMouseDown={(event) => event.stopPropagation()}
    >
      <input
        className="control pick-input"
        autoFocus
        value={query}
        placeholder={productMode ? '품목 이름이나 코드로 찾기' : '종목 이름이나 코드로 찾기'}
        aria-label={productMode ? '품목 검색' : '종목 검색'}
        onChange={(event) => setQuery(event.target.value)}
        /* Enter 는 **목록 맨 위**를 엽니다 — 검색어가 품목에 걸렸으면 그 품목의
           기본 월물입니다. 훑어 내려가는 커서가 없어 화면이 가리키는 줄이 곧
           첫 줄이고, 빈 검색어에서는 아무 품목이나 열리므로 안 받습니다. */
        onKeyDown={(event) => {
          if (event.key !== 'Enter' || query.trim() === '') return
          if (props.mode === 'product') {
            if (!productHead) return
            event.preventDefault()
            pickProduct(productHead)
            return
          }
          const first = rows[0]
          if (!first) return
          event.preventDefault()
          props.onPick(first.item)
        }}
      />

      {productMode ? (
        /* **머리글이 목록 안에 섭니다.** 시장이 둘 이상 설 수 있어, 머리글을
           밖에 두면 아래로 내려간 시장이 어느 것인지가 안 남습니다. */
        <div className="pick-rows">
          {productGroups.length === 0 ? (
            <p className="pick-empty">찾는 품목이 없습니다</p>
          ) : (
            productGroups.map((group) => (
              <Fragment key={group.market}>
                <p className="pick-title">{MARKET_LABEL[group.market]} 품목</p>
                {group.blocks.map((block) =>
                  block.rows.map((row, index) => (
                    <button
                      key={`${row.market}:${row.product.code}:${row.kind}`}
                      type="button"
                      className="pick-row"
                      aria-pressed={isHere(row)}
                      onClick={() => pickProduct(row)}
                    >
                      {/* 코드는 **묶음의 첫 줄에만**입니다 — 갈래 줄마다 되풀이하면
                          같은 품목이 여러 품목처럼 늘어섭니다. */}
                      <span className="pick-row-name">
                        {row.product.name}
                        {index === 0 && (
                          <span className="pick-row-code">{row.product.code}</span>
                        )}
                      </span>
                      {/* 갈래는 **이름보다 한 급 낮춥니다.** 이름에 「스프레드」가 든
                          품목이 있어, 갈래를 이름과 같은 글자로 이어 붙이면 둘이 한
                          이름으로 읽힙니다. */}
                      <span className="badge pick-row-kind">{KIND_LABEL[row.kind]}</span>
                    </button>
                  )),
                )}
              </Fragment>
            ))
          )}
        </div>
      ) : (
        <>
          <p className="pick-title">이 종목의 다른 만기</p>
          <div className="pick-chips">
            {months.map((month, index) => (
              <button
                key={month.code}
                type="button"
                className="pick-chip"
                aria-pressed={month.code === currentCode}
                onClick={() => pickMonth(month)}
              >
                {shortMonth(month, byDay)}
                {index === 0 && <small>근월</small>}
                {index === 1 && <small>차월</small>}
              </button>
            ))}
          </div>

          {/* 흐린 수가 **하나라도 설 때만** 제목 줄 끝에 그 뜻을 한 번 적습니다. 줄마다
              달지 않습니다 — 줄에는 표시 하나(주력·최근 만기) 규칙이 있고, 지금
              세션은 머리 띠가 이미 말합니다. 모의투자의 국내 야간이면 수가 모두 빈
              까닭을 같은 자리에 적습니다. */}
          <p className="pick-title pick-title-noted">
            검색 결과
            {paperNight ? (
              <span className="pick-title-note">모의투자에서는 야간 시세를 받을 수 없습니다</span>
            ) : (
              rows.some((row) => row.closeOnly) && (
                <span className="pick-title-note">흐린 값은 주간 마감</span>
              )
            )}
          </p>
          <div className="pick-rows">
            {rows.length === 0 ? (
              <p className="pick-empty">찾는 품목이 없습니다</p>
            ) : (
              rows.map(({ item, main, tagged, opens, closeOnly }) => (
                <button
                  key={`${item.market}:${item.code}`}
                  type="button"
                  className="pick-row"
                  aria-pressed={item.code === currentCode}
                  onClick={() => pickInstrument(item)}
                >
                  <span className="pick-row-name">
                    {item.name}
                    <span className="pick-row-code">{item.code}</span>
                  </span>
                  {/* **한 줄에 표시 하나, 초록은 한 품목에 하나입니다.** 둘은 같은
                      물음(「어느 월물을 볼까」)에 답하는 표시라 나란히 세우면 어느 쪽을
                      따라야 하는지가 흐려지고, 초록은 「비워 두고 열면 이 줄이 선다」는
                      뜻이라 그 줄에만 붙습니다 — 주력 축이 없는 시장(국내)에서는 만기가
                      가장 가까운 줄이 곧 그 줄입니다. */}
                  {tagged ? (
                    <span className={`badge pick-row-tag${opens ? ' badge-brand' : ''}`}>
                      {main ? '주력' : '최근 만기'}
                    </span>
                  ) : null}
                  {/* 값이 아직 없으면 자리만 두고 비웁니다 — 줄 높이가 흔들리지
                      않게 칸은 남깁니다. */}
                  {/* 주간 마감 값은 **흐리게** 섭니다 — 같은 열에서 지금 움직이는 값과
                      멈춘 값을 무게로 가릅니다. 색은 등락이 쓰므로 쓰지 않습니다. */}
                  <span className={`pick-row-price${closeOnly ? ' is-close' : ''}`}>
                    {item.lastPrice !== null &&
                      item.lastPrice.toLocaleString('ko-KR', {
                        minimumFractionDigits: item.decimals,
                        maximumFractionDigits: item.decimals,
                      })}
                  </span>
                </button>
              ))
            )}
          </div>
        </>
      )}
    </div>
  )
}
