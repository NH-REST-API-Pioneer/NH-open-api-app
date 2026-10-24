import { useMemo, useState } from 'react'
import type { ContractRow, MarketContext, ProductKind } from '../../lib/types'
import { useResizableWidth } from '../../lib/useResizableWidth'
import { contractRows } from '../../data/expiryQuotes'
import { kindsOf, productsOf } from '../../data/instruments'
import { refreshMaster, type MasterState } from '../../data/master'
import { ProductNav } from './ProductNav'
import { CatalogList } from './CatalogList'
import './instruments.css'

/* 종목 — 무엇이 있는지 고르는 카탈로그.
 *
 * 이 화면은 아무것도 부르지 않습니다. 종목 목록은 마스터 파일에서 오고,
 * 시세는 여기서 안 봅니다. 그래서 이 프로젝트에서 「없음」과 「모름」이 안
 * 갈리는 유일한 화면입니다 — 고른 조합에 종목이 없으면 「없다」를 단정할 수
 * 있습니다. 다른 화면이 계속 갈라 온 「받지 못했습니다」가 여기에는 없습니다.
 *
 * 네 단계를 열 넷으로 나누지 않습니다. 국내/해외는 왼쪽 위 세그먼트, 거래소는
 * 왼쪽 목록의 그룹 머리, 상품은 그 항목, 선물/옵션은 가운데 위 세그먼트입니다.
 * 열로 나누면 내비가 화면의 절반을 먹고, 국내는 거래소가 하나뿐이라 그 열이
 * 늘 한 줄짜리가 됩니다.
 */

const NAV_WIDTH = 240

/* 종류 이름. **마스터 규격이 `type` 값 옆에 적어 둔 낱말 그대로**입니다
 * (`F` 선물 · `O` 옵션 · `S` 스프레드). 이 앱이 따로 짓지 않습니다. */
const KIND_LABEL: Record<ProductKind, string> = {
  futures: '선물',
  option: '옵션',
  spread: '스프레드',
}

interface Props {
  context: MarketContext
  productCode: string | null
  onContextChange: (context: MarketContext) => void
  onProductChange: (code: string) => void
  onOpenInstrument: (code: string) => void
  /** 종목 마스터를 받는 중인지. 목록이 마스터에서 오므로 받기 전에는 셀 것이
   *  없습니다 — **빈 목록으로 두면 「없다」로 읽힙니다.** */
  master: MasterState
}

export function InstrumentsScreen({
  context,
  productCode,
  onContextChange,
  onProductChange,
  onOpenInstrument,
  master,
}: Props) {
  const overseas = context === 'overseas'
  const nav = useResizableWidth({
    key: 'nh.instruments.navWidth',
    initial: NAV_WIDTH,
    min: 180,
    max: 380,
  })

  const all = productsOf(overseas ? 'overseas' : 'domestic')

  const product = all.find((item) => item.code === productCode) ?? all[0]

  /* **종류를 고르는 축은 시장마다 다릅니다.**
   *
   * 국내는 한 품목이 선물·옵션·스프레드를 함께 갖는 것이 보통이라(310 품목 중
   * 304), 종류가 품목 안에서 고르는 축입니다. 그래서 세그먼트가 서고 그 값을
   * 따로 들고 있습니다 — 품목에서 뽑으면 「어느 것을 보고 있는지」를 화면이 못
   * 말합니다. 고른 품목에 그 종류가 없으면 그 품목이 가진 첫 종류로 내려섭니다.
   *
   * 해외는 한 품목에 종류가 **하나뿐**입니다(178 품목 전부). 옵션도 스프레드도
   * 별도 품목으로 실려 오므로, 종류는 고르는 축이 아니라 품목의 꼬리표입니다 —
   * 세그먼트를 세우면 늘 한 칸만 눌리는 세그먼트가 되고, 그것으로 목록을 거르면
   * 나머지 품목이 내비에서 사라집니다. */
  const [pickedKind, setPickedKind] = useState<ProductKind>('futures')
  const available = product ? kindsOf(product) : []
  const kind = overseas
    ? (available[0] ?? 'futures')
    : available.includes(pickedKind)
      ? pickedKind
      : (available[0] ?? 'futures')

  /* 열려 있는 거래소. 고른 품목이 있으면 그 거래소가 열려 있습니다. */
  const [openExchange, setOpenExchange] = useState('')
  const exchange = product?.exchange ?? openExchange

  /* 이 거래소에 그 종류가 있는지. 마스터가 손에 있어 확실히 압니다 —
     없는 것을 「모를 수도 있음」으로 두지 않고 아예 못 누르게 합니다. */
  const hasKind = (want: ProductKind) =>
    all.some((item) => item.exchange === exchange && kindsOf(item).includes(want))

  const pickKind = (next: ProductKind) => {
    if (next === kind || !hasKind(next)) return
    setPickedKind(next)
    /* 지금 품목에 그 종류가 있으면 품목을 안 바꿉니다 — 「이 상품의 옵션」을
       보려는 것이지 다른 상품으로 옮기려는 것이 아닙니다. */
    if (product && kindsOf(product).includes(next)) return
    const first = all.find((item) => item.exchange === exchange && kindsOf(item).includes(next))
    if (first) onProductChange(first.code)
  }

  /* 거래소를 바꿔도 고른 종류는 그대로 둡니다 — 「옵션을 보다가 다른 거래소의
     옵션을 보는」 흐름이 자연스럽고, 되돌리면 매번 다시 눌러야 합니다.
     그 거래소에 그 종류가 없으면 **첫 품목으로 가고 종류는 그 품목이 가진
     첫 종류**가 됩니다 — 종류를 먼저 정해 두고 품목을 찾으면 빈 화면이
     나올 수 있습니다. */
  const pickExchange = (next: string) => {
    setOpenExchange(next)
    const keep = all.find((item) => item.exchange === next && kindsOf(item).includes(kind))
    const first = keep ?? all.find((item) => item.exchange === next)
    if (first) onProductChange(first.code)
  }

  const pickMarket = (next: 'domestic' | 'overseas') => {
    if ((next === 'overseas') === overseas) return
    /* 국내는 주간·야간을 고르지 않습니다. 어느 세션인지는 시계가 정합니다. */
    onContextChange(next === 'overseas' ? 'overseas' : 'domestic-day')
    const list = productsOf(next)
    const first = list.find((item) => kindsOf(item).includes(kind)) ?? list[0]
    if (first) {
      setOpenExchange(first.exchange)
      onProductChange(first.code)
    }
  }

  /* **이 목록은 값을 안 그립니다** — 종목명·코드·만기·잔존·거래승수·호가단위뿐이고
     그 여섯은 다 마스터에서 옵니다. 그래서 시세를 부르지 않습니다: 안 그리는 값을
     받으려고 조회를 내면 헤더·호가가 쓰는 한도를 말없이 갉아먹습니다.
     받아 두는 자리에서 읽는 것은 「최근 만기」 표시 하나입니다. */
  const rows = useMemo(() => (product ? contractRows(product, kind) : []), [product, kind])

  const open = (row: ContractRow) => onOpenInstrument(row.code)

  /* 마스터를 받기 전과 못 받았을 때는 목록 대신 그 사실을 말합니다.
     **「없다」와 「아직 모른다」와 「못 받았다」가 다른 상태**라, 빈 목록을
     세우면 사용자가 「이 시장에는 종목이 없구나」로 읽습니다. */
  if (master.status !== 'ready') {
    return (
      <div className="instruments">
        <div className="notice">
          {master.status === 'loading' ? (
            <p className="notice-title">종목 목록을 받는 중입니다</p>
          ) : (
            <>
              <p className="notice-title">종목 목록을 받지 못했습니다</p>
              {master.detail !== '' && <p className="notice-reason">{master.detail}</p>}
              <button
                type="button"
                className="btn btn-primary notice-action"
                onClick={() => void refreshMaster()}
              >
                다시 받기
              </button>
            </>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="instruments">
      <div className="instr-nav-side" style={{ width: nav.width }}>
        {/* 「둘 중 하나」라 균등 폭입니다. 아래 목록은 「여럿 중 하나」라 모양이
            갈려서 어느 쪽이 바깥 선택인지 보입니다. */}
        <div className="seg seg-even instr-market" role="group" aria-label="시장">
          <button
            type="button"
            className="seg-item"
            aria-pressed={!overseas}
            onClick={() => pickMarket('domestic')}
          >
            국내
          </button>
          <button
            type="button"
            className="seg-item"
            aria-pressed={overseas}
            onClick={() => pickMarket('overseas')}
          >
            해외
          </button>
        </div>

        <ProductNav
          products={all}
          market={overseas ? 'overseas' : 'domestic'}
          selected={product?.code ?? ''}
          /* 해외는 종류가 고르는 축이 아니라 품목의 꼬리표라 안 거릅니다.
             거르면 선물 품목만 남고 옵션·스프레드 품목이 내비에서 사라집니다. */
          kind={overseas ? null : kind}
          exchange={exchange}
          width={nav.width}
          onSelect={(item) => onProductChange(item.code)}
          onExchangeChange={pickExchange}
        />
      </div>

      {/* 경계선을 끌어 내비 폭을 바꿉니다. 품목 이름 길이가 시장마다 달라
          한 값으로 고정하면 어느 쪽에서는 잘리고 어느 쪽에서는 남습니다. */}
      <div
        className="resize-handle"
        data-dragging={nav.dragging}
        role="separator"
        aria-orientation="vertical"
        aria-label="내비 폭"
        onMouseDown={nav.onHandleDown}
      />

      <div className="instr-body">
        <div className="instr-head">
          <h1 className="t-screen">{product?.name ?? '종목'}</h1>

          {/* 해외는 고를 것이 없어 세그먼트 대신 지금 종류를 적기만 합니다.
              칸을 비워 두면 국내에서 보이던 자리가 통째로 사라져 화면이
              달라 보이고, 「이 품목이 무엇인지」도 말하지 않게 됩니다. */}
          {overseas ? (
            <span className="instr-kind-tag">{KIND_LABEL[kind]}</span>
          ) : (
            <div className="seg instr-kind" role="group" aria-label="종류">
              {(['futures', 'option', 'spread'] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  className="seg-item"
                  aria-pressed={kind === item}
                  disabled={!hasKind(item)}
                  onClick={() => pickKind(item)}
                >
                  {KIND_LABEL[item]}
                </button>
              ))}
            </div>
          )}
        </div>

        <CatalogList
          rows={rows}
          overseas={overseas}
          decimals={product?.decimals ?? 2}
          kind={kind}
          onOpen={open}
        />
      </div>
    </div>
  )
}
