/** 종목 마스터를 글자로 찾기 — 상단 검색과 홈의 담기 창이 같은 규칙을 씁니다.
 *
 *  **결과가 곧 종목입니다.** 품목 이름을 친 사람은 아직 어느 만기인지 안 정했고
 *  종목코드를 친 사람은 이미 정했으므로, 품목에 걸리면 그 품목이 한 줄로 서고
 *  (펼치면 월물), 종목에 걸리면 그 종목이 섭니다.
 *
 *  두 자리가 규칙을 따로 가지면 같은 글자에 검색 창과 담기 창이 다른 것을
 *  찾아 주고, 사용자는 어느 쪽이 맞는지 알 수 없습니다. 무엇을 **할 수 있나**
 *  (열기·담기)는 부르는 자리가 정하고, 여기는 무엇이 **걸리나**만 답합니다.
 */
import type { Product, ProductKind } from './types'
import { contractsOf, productsOf, resolve, type ContractRef, type Market } from '../data/instruments'

/** 둘러보기의 한 묶음 — 상품군 하나와 그 품목들. **거래소 단은 없습니다** —
 *  거래소로 좁히는 것은 종목 화면의 일이고, 여기서 빼면 두 시장이 같은 깊이가
 *  됩니다. 상단 검색과 홈의 담기 창이 같은 묶음을 씁니다. */
export interface Browse {
  name: string
  order: number
  items: Product[]
}

export function browseOf(market: Market): Browse[] {
  const out: Browse[] = []
  for (const product of productsOf(market)) {
    const found = out.find((item) => item.name === product.group)
    if (found) found.items.push(product)
    else out.push({ name: product.group, order: product.groupOrder, items: [product] })
  }
  const byName = new Intl.Collator('ko', { numeric: true })
  for (const group of out) group.items.sort((a, b) => byName.compare(a.name, b.name))
  return out.sort((a, b) => a.order - b.order || byName.compare(a.name, b.name))
}

/** 품목 하나를 결과 줄로 — 둘러보기에서 품목을 골랐을 때 검색 결과와 같은 줄을
 *  세우기 위해서입니다(품목 이름으로 찾은 것과 같은 답). */
export function hitsOfProduct(market: Market, product: Product): Hit[] {
  return hitsOf(market, product, product.name.toLowerCase())
}

export const MARKETS: Market[] = ['domestic', 'overseas']
export const MARKET_LABEL: Record<Market, string> = { domestic: '국내', overseas: '해외' }

/* 종류 이름. **마스터 규격이 `type` 값 옆에 적어 둔 낱말 그대로**입니다
 * (`F` 선물 · `O` 옵션). 종목 화면의 세그먼트와 같은 말을 씁니다. */
export const KIND_LABEL: Record<ProductKind, string> = {
  futures: '선물',
  option: '옵션',
  spread: '스프레드',
}
const KINDS = ['futures', 'option', 'spread'] as const

/** 결과 한 줄. **넷입니다.**
 *
 *  ⓐ 품목 행 — 꺾쇠가 있고 누르면 그 아래에 월물이 펼쳐집니다.
 *  ⓑ 종목 행 — 코드나 만기로 찾은 그 종목. 꺾쇠도 오른쪽 라벨도 없습니다.
 *  ⓒ 옵션 행사가 종목코드로 찾은 줄 — 색인의 종목 목록에는 행사가 행이 없어
 *     품목·만기까지만 알 수 있고, 행사가는 체인에서 고릅니다.
 *
 *  **왼쪽 꺾쇠는 「펼쳐지나」, 오른쪽 끝은 「누르면 무엇이 되나」**입니다 — 축이
 *  둘이라 갈립니다. 눌러도 안 펼쳐지는 꺾쇠는 거짓말이라 ⓑ 에는 안 답니다. */
export type Hit =
  | { row: 'product'; market: Market; product: Product; kind: ProductKind; refs: ContractRef[] }
  | { row: 'contract'; market: Market; product: Product; ref: ContractRef }
  | { row: 'strike'; market: Market; product: Product; code: string; label: string }

export function hitKey(hit: Hit): string {
  if (hit.row === 'strike') return 'k:' + hit.code
  if (hit.row === 'contract') return 'c:' + hit.ref.code
  return 'p:' + hit.market + '|' + hit.product.code + '|' + hit.kind
}

/** 만기가 가장 가까운 종목. 목록의 「최근 만기」와 **같은 값**입니다 — 표시는
 *  그것이고 열리는 것은 다른 것이면, 표시가 무엇을 가리키는지 화면이 못 말합니다. */
export function nearest(refs: ContractRef[]): ContractRef | null {
  if (refs.length === 0) return null
  return refs.reduce((a, b) => (b.expiry < a.expiry ? b : a))
}

/** 만기가 가장 이른 종목의 코드. 목록의 「최근 만기」와 같은 규칙입니다.
 *  월물이 하나면 「가장 이른 것」이 뜻이 없어 `null` 입니다.
 *
 *  **스프레드에는 없습니다.** 만기가 둘이라 「가장 이른 것」이 한 값으로 정해지지
 *  않습니다 — 근월이 같고 원월만 다른 줄들이 전부 같은 만기를 가진 것으로 읽힙니다.
 *  목록 값이 같은 물음에 답하는 자리(`data/expiryQuotes.ts`)도 스프레드를 뺍니다.
 *  비워 두고 열 때 서는 줄은 그대로 목록 첫 줄이고, 그 줄에 낱말만 안 붙습니다. */
export function frontCode(refs: ContractRef[]): string | null {
  if (refs.length < 2) return null
  if (refs[0]?.kind === 'spread') return null
  return nearest(refs)?.code ?? null
}

/** 그 품목에서 세울 줄.
 *
 *  **품목에 걸리면 한 줄, 종목에 걸리면 그 종목**입니다. 품목에 걸린 품목의
 *  종목까지 함께 세우면(코드가 품목 코드로 시작하므로 다 걸립니다) 한 품목이
 *  목록을 다 먹습니다.
 *
 *  **품목 코드는 시작만 봅니다.** 코드는 두세 자라 사람이 중간부터 치는 일이
 *  없고, 포함으로 보면 「ES」에 코드 안에 그 두 자가 든 다른 품목이 딸려옵니다. */
export function hitsOf(market: Market, product: Product, term: string): Hit[] {
  const byProduct =
    product.name.toLowerCase().includes(term) || product.code.toLowerCase().startsWith(term)

  /* **종류를 안 섞습니다.** 국내는 옵션을 가진 71 품목 중 67이 선물도 갖는데,
     한 목록에 담으면 만기 순이 두 번 돕니다 — 선물이
     27년까지 갔다가 옵션이 다시 26년부터 시작하고, 같은 「26년 9월물」 줄이
     둘 섭니다. 「만기 N」도 두 종류의 합이 되어 무엇의 수인지 흐려집니다.
     펼친 목록이 **만기 순으로 이어지는 하나의 축**이어야 상한을 안 거는 근거가
     섭니다. */
  const byKind = KINDS.map((kind) => ({ kind, refs: contractsOf(product, kind) })).filter(
    (item) => item.refs.length > 0,
  )

  if (byProduct) {
    /* **월물이 하나뿐이면 품목 행을 안 세웁니다** — 그 종목이 바로 섭니다.
       펼칠 것이 하나인데 꺾쇠를 달면 「고를 게 없는데 고르는 모양」이 되고,
       누르는 횟수만 하나 늘어납니다(만기가 하나면 셀렉트가 아니라 글자로 두는
       것, 행이 하나면 배지를 안 다는 것과 같은 계열입니다). */
    const rows = byKind.map((item) =>
      item.refs.length === 1
        ? ({ row: 'contract', market, product, ref: item.refs[0] } as Hit)
        : ({ row: 'product', market, product, kind: item.kind, refs: item.refs } as Hit),
    )
    return rows
  }

  /* 종목 쪽은 코드·만기 표기에 더해 **마스터가 실어 준 이름 원문**까지 봅니다 —
     화면에는 이 앱이 지은 이름이 서지만, 마스터에 적힌 대로 친 사람도 찾을 수
     있어야 합니다. */
  return byKind
    .flatMap((item) => item.refs)
    .filter(
      (ref) =>
        ref.code.toLowerCase().includes(term) ||
        ref.label.includes(term) ||
        ref.masterName.toLowerCase().includes(term),
    )
    .map((ref) => ({ row: 'contract', market, product, ref }) as Hit)
}

/** 친 글자로 **시작하는** 것을 앞에 세웁니다 — 「ES」를 친 사람에게 「MES」가
 *  먼저 서면, 정확히 친 것이 목록 중간에 묻힙니다. */
export function startsWithTerm(hit: Hit, term: string): boolean {
  const name = hit.product.name.toLowerCase()
  const code = hit.product.code.toLowerCase()
  if (name.startsWith(term) || code.startsWith(term)) return true
  return hit.row === 'contract' && hit.ref.code.toLowerCase().startsWith(term)
}

/** 시장 하나의 결과. 시장 안의 차례는 시작 일치 묶음이 먼저이고 각 묶음은 이름순입니다. */
export interface SearchGroup {
  market: Market
  hits: Hit[]
}

export interface SearchResult {
  groups: SearchGroup[]
  /** 상한에 잘려 안 보인 **품목** 수. 0 이면 다 보인 것입니다. */
  more: number
}

/** 글자로 찾습니다. `term` 은 앞뒤 공백을 떼고 소문자로 맞춘 것이어야 합니다.
 *
 *  상한은 **훑는 길이를 막자는 것**입니다. 그때 필요한 것은 더 긴 목록이
 *  아니라 더 좁은 검색어라, 넘친 만큼을 세어 `more` 로 답합니다.
 *  **세는 단위는 품목입니다** — 국내는 한 품목이 선물 행과 옵션 행 둘로 서는데,
 *  줄 수로 자르면 「삼성전자 선물」 뒤에서 끊겨 「옵션이 없구나」로 읽힙니다.
 *  한 품목의 줄은 함께 서거나 함께 빠집니다.
 *
 *  **실재하는 코드에 「없습니다」라고 답하지 않습니다.** 옵션 행사가 종목은 색인의
 *  종목 목록에 없지만 코드를 푸는 것은 되므로(마스터가 준 옵션 신원표), 그
 *  품목의 그 만기를 한 줄(ⓓ)로 맨 위에 세웁니다. */
/** 친 글자가 그 줄의 코드(품목 코드·종목 코드)와 똑같은지. 대소문자는 안 가립니다. */
function exactCode(hit: Hit, term: string): boolean {
  if (hit.row === 'contract') return hit.ref.code.toLowerCase() === term
  if (hit.row === 'product') return hit.product.code.toLowerCase() === term
  return false
}

export function searchInstruments(term: string, limit: number): SearchResult {
  if (term === '') return { groups: [], more: 0 }
  const byName = new Intl.Collator('ko', { numeric: true })

  const hit = MARKETS.flatMap((market) =>
    productsOf(market).flatMap((product) => {
      const hits = hitsOf(market, product, term)
      if (hits.length === 0) return []
      return [{ market, product, starts: hits.some((item) => startsWithTerm(item, term)), hits }]
    }),
  )
  /* 차례는 **시장 안에서** 정합니다 — 시작 일치 묶음이 먼저이고 각 묶음은
     이름순입니다. 「ES」를 친 사람에게 「MES」가 먼저 서면 정확히 친 것이
     목록 중간에 묻히고, 묶음 안이 마스터 순서면 훑을 차례가 없습니다. */
  const found = MARKETS.flatMap((market) => {
    const mine = hit.filter((item) => item.market === market)
    const sorted = (starts: boolean) =>
      mine
        .filter((item) => item.starts === starts)
        .sort((a, b) => byName.compare(a.product.name, b.product.name))
    return [...sorted(true), ...sorted(false)]
  })

  /* **자리를 먹는 순서와 서는 순서는 따로입니다.**
     자를 때는 **두 시장의 시작 일치를 먼저** 세고 그 다음이 포함입니다 — 시장을
     먼저 두고 자르면 국내의 「이름 가운데 그 글자가 든」 품목들이 해외의 「이름이
     그 글자로 시작하는」 품목들을 밀어냅니다. 정확히 친 것이 묻히면 안 된다는
     것이 시작 일치를 둔 이유입니다. */
  /* **코드를 그대로 친 품목은 상한에 안 잘립니다** — 짧은 코드(「M」·「6E」)는 같은
     글자로 시작하는 품목이 상한보다 많아, 자른 뒤에 끌어올리면 정확히 친 것이 아예
     안 섭니다. 먼저 빼 두고 남은 자리를 나머지로 채웁니다. */
  const isExact = (item: (typeof found)[number]) => item.hits.some((one) => exactCode(one, term))
  const ranked = [...found.filter((item) => item.starts), ...found.filter((item) => !item.starts)]
  const exactItems = ranked.filter(isExact)
  const capped = [
    ...exactItems,
    ...ranked.filter((item) => !isExact(item)).slice(0, Math.max(limit - exactItems.length, 0)),
  ]
  const more = found.length - capped.length

  const typed = term.toUpperCase()
  const byCode = resolve(typed)
  const strikeHit: Hit | null =
    byCode && byCode.kind === 'option' && byCode.leg === null && byCode.contract
      ? {
          row: 'strike',
          market: byCode.market,
          product: byCode.product,
          code: byCode.contract.code,
          label: byCode.contract.label,
        }
      : null

  /* 서는 것은 시장으로 갈라 보입니다 — 같은 이름의 종목이 두 시장에 있어, 어느
     쪽을 여는지가 보여야 합니다. */
  const groups = MARKETS.map((market) => {
    const listed = capped.filter((item) => item.market === market).flatMap((item) => item.hits)
    /* **코드를 그대로 친 줄은 맨 위**입니다(「ES」·「A016C000」). 나머지 차례는
       그대로 둡니다 — 정확히 친 것 하나만 끌어올리고 이름순 묶음은 흔들지 않습니다. */
    const exact = listed.filter((item) => exactCode(item, term))
    return {
      market,
      hits: [
        /* 코드로 정확히 찾은 줄이라 맨 위입니다. */
        ...(strikeHit && strikeHit.market === market ? [strikeHit] : []),
        ...exact,
        ...listed.filter((item) => !exactCode(item, term)),
      ],
    }
  }).filter((group) => group.hits.length > 0)
  /* 코드를 그대로 친 줄이 있는 시장 묶음이 **목록 맨 위**입니다 — 「ES」를 친 사람에게
     국내 묶음이 먼저 서면 정확히 친 것이 둘째 묶음 맨 위로 밀립니다. 그 밖의 묶음
     차례는 그대로입니다. */
  const hasExact = (group: { hits: Hit[] }) => group.hits.some((item) => exactCode(item, term))
  const ordered = [...groups.filter(hasExact), ...groups.filter((group) => !hasExact(group))]

  return { groups: ordered, more }
}
