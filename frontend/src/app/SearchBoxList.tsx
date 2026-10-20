import type { RefObject } from 'react'
import type { Product, RecentItem } from '../lib/types'
import { needsLeg, type ContractRef, type Market } from '../data/instruments'
import { refreshMaster, type MasterState } from '../data/master'
import { RECENT_EMPTY } from '../lib/labels'
import {
  KIND_LABEL,
  MARKETS,
  MARKET_LABEL,
  browseOf,
  hitKey,
  type Hit,
  type SearchGroup,
} from '../lib/instrumentSearch'

/** 화살표가 훑는 한 줄. 세 상태가 같은 목록을 씁니다 — 훑는 차례와 보이는
 *  차례가 갈리면 화면이 가리키는 줄과 Enter 로 열리는 줄이 달라집니다. */
export type Row =
  | { pick: 'recent'; item: RecentItem }
  | { pick: 'product'; market: Market; product: Product }
  | { pick: 'hit'; hit: Hit }
  /** 펼친 품목 아래의 월물 한 줄. */
  | { pick: 'month'; product: Product; ref: ContractRef; front: boolean }

/** 검색 창의 목록 — 받는 중·못 받음 안내, 검색 결과 묶음, 입력 전의 최근 본과 둘러보기. */
export function renderSearchList({
  listRef,
  master,
  term,
  rows,
  groups,
  openHit,
  rowProps,
  more,
  shownRecent,
  openGroup,
  setOpenGroup,
}: {
  listRef: RefObject<HTMLDivElement | null>
  master: MasterState
  term: string
  rows: Row[]
  groups: SearchGroup[]
  openHit: string | null
  rowProps: (row: Row) => {
    id: string
    type: 'button'
    role: string
    'aria-selected': boolean
    tabIndex: number
    'data-active': boolean
    onMouseEnter: () => void
    onClick: () => undefined
  }
  more: number
  shownRecent: RecentItem[]
  openGroup: string | null
  setOpenGroup: (group: string | null) => void
}) {
  return (
            <div className="search-list" id="search-list" role="listbox" ref={listRef}>
              {/* **입력은 어느 상태에서도 안 막습니다.** 받는 동안에도 칠 수 있게
                  두고 목록 자리에만 지금 상태를 적습니다. 여기 「다시 받기」는
                  답니다: 받기가 실패한 것이라 누르면 결과가 달라질 수 있습니다. */}
              {master.status === 'loading' ? (
                <p className="search-note">종목 목록을 받는 중입니다</p>
              ) : master.status === 'failed' ? (
                <p className="search-note">
                  종목 목록을 못 받았습니다
                  <button
                    type="button"
                    className="search-retry"
                    onClick={() => void refreshMaster()}
                  >
                    다시 받기
                  </button>
                </p>
              ) : term !== '' ? (
                rows.length === 0 ? (
                  <p className="search-note">찾는 종목이 없습니다</p>
                ) : (
                  <>
                    {groups.map((group) => (
                      <div key={group.market}>
                        <h2 className="search-head-row">{MARKET_LABEL[group.market]}</h2>
                        {group.hits.map((hit) => {
                          const row = rows.find((item) => item.pick === 'hit' && item.hit === hit)
                          if (!row) return null
                          const expanded = hit.row === 'product' && openHit === hitKey(hit)
                          return (
                            <div key={hitKey(hit)}>
                              <button
                                className={
                                  expanded ? 'search-row search-row-open' : 'search-row'
                                }
                                aria-expanded={hit.row === 'product' ? expanded : undefined}
                                {...rowProps(row)}
                              >
                                {/* **왼쪽 꺾쇠는 「펼쳐지나」**입니다. 안 펼쳐지는
                                    줄에는 안 달되 그 자리는 남깁니다 — 이름의
                                    왼쪽 끝이 세 종류 다 같은 세로선에 서야 합니다. */}
                                <span className="search-caret" aria-hidden="true">
                                  {hit.row === 'product' ? (expanded ? '▾' : '▸') : ''}
                                </span>
                                <span className="search-row-name">{hit.product.name}</span>
                                {/* 품목 코드. **친 글자가 코드 앞자리에 걸려 선
                                    줄**이 있어(「6J」로 셋이 섭니다), 코드가 화면에
                                    없으면 왜 걸렸는지 못 읽습니다. */}
                                <span className="search-row-sub">{hit.product.code}</span>
                                {hit.row === 'contract' && (
                                  <span className="search-row-expiry">{hit.ref.label}</span>
                                )}
                                {hit.row === 'strike' && (
                                  <span className="search-row-expiry">{hit.label}</span>
                                )}
                                {/* **오른쪽 끝은 「누르면 무엇이 되나」**입니다.
                                    품목 행은 몇 개가 펼쳐질지, 스프레드는 이
                                    창을 떠난다는 것, 종목 행은 그 코드입니다. */}
                                {hit.row === 'product' ? (
                                  /* 종류는 **국내에만** 답니다. 해외는 **이름이
                                     종류를 이미 말합니다** — 지금 색인에서 해외
                                     옵션 품목 22가 전부 이름에 「옵션」을, 스프레드
                                     18이 전부 「스프레드」를 답니다. 이름에 종류가
                                     없는 해외 품목이 실려 오면 이 규칙이 깨집니다. */
                                  <span className="search-row-count">
                                    {hit.market === 'domestic' ? KIND_LABEL[hit.kind] + ' ' : ''}
                                    만기 {hit.refs.length}
                                  </span>
                                ) : hit.row === 'strike' ? (
                                  /* 친 코드는 실재하지만 색인의 종목 목록에 없는
                                     행사가 종목입니다. 「없다」 대신 어디서 고르는지
                                     적고, 누르면 그 체인이 열립니다. */
                                  <span className="search-row-code">행사가는 체인에서 ›</span>
                                ) : (
                                  /* 행사가를 고르기 전 옵션은 코드가 아직 없습니다. */
                                  <span className="search-row-code">
                                    {needsLeg(hit.ref.code) ? '행사가 선택' : hit.ref.code}
                                  </span>
                                )}
                              </button>

                              {expanded &&
                                (() => {
                                  /* **초록은 「비워 두고 열면 이 줄이 선다」**는 뜻이라
                                     한 품목에 하나뿐입니다. 주력 축이 있는 시장(해외)에서는
                                     주력 줄이 그것이고, 축이 없는 시장(국내)에서는 만기가
                                     가장 가까운 줄이 그것입니다. */
                                  const hasMain = hit.refs.some((ref) => ref.main)
                                  return hit.refs.map((ref) => {
                                    const monthRow = rows.find(
                                      (item) => item.pick === 'month' && item.ref === ref,
                                    )
                                    if (!monthRow) return null
                                    const front = monthRow.pick === 'month' && monthRow.front
                                    const opens = ref.main || (!hasMain && front)
                                    return (
                                      <button
                                        key={ref.code}
                                        className="search-row search-row-month"
                                        {...rowProps(monthRow)}
                                      >
                                        <span className="search-row-name">{ref.label}</span>
                                        {/* **한 줄에 표시 하나입니다.** 둘은 같은 물음
                                            (「어느 월물을 볼까」)에 답하므로 나란히
                                            세우면 어느 쪽을 따라야 하는지가 흐려집니다.
                                            거래가 근월이 아니라 분기물에 실리는 해외
                                            상품에서는 초록이 근월 아래 줄에 섭니다. */}
                                        {ref.main || front ? (
                                          <span className={`badge${opens ? ' badge-brand' : ''}`}>
                                            {ref.main ? '주력' : '최근 만기'}
                                          </span>
                                        ) : null}
                                        <span className="search-row-code">
                                          {needsLeg(ref.code) ? '행사가 선택' : ref.code}
                                        </span>
                                      </button>
                                    )
                                    })
                                })()}
                            </div>
                          )
                        })}
                      </div>
                    ))}
                    {/* 상한을 넘은 만큼을 적습니다. **누를 수 없습니다** — 무엇을
                        여는 줄이 아니라 목록이 잘렸다는 사실입니다. */}
                    {more > 0 && (
                      <p className="search-note search-more">
                        {more}개 더 있습니다 — 검색어를 좁혀 주세요
                      </p>
                    )}
                  </>
                )
              ) : (
                <>
                  {/* 최근 본이 위입니다 — 다시 여는 것이 대부분이고, 둘러보기는
                      처음 오는 사람의 길입니다. */}
                  <h2 className="search-head-row">최근 본</h2>
                  {shownRecent.length === 0 ? (
                    <p className="search-note search-note-left">{RECENT_EMPTY}</p>
                  ) : (
                    shownRecent.map((item) => {
                      const row = rows.find(
                        (candidate) => candidate.pick === 'recent' && candidate.item === item,
                      )
                      if (!row) return null
                      return (
                        <button key={item.code} className="search-row" {...rowProps(row)}>
                          <span className="search-row-name">{item.name}</span>
                          <span className="search-row-code">
                            {needsLeg(item.code) ? '행사가 선택' : item.code}
                          </span>
                        </button>
                      )
                    })
                  )}

                  {MARKETS.map((market) => (
                    <div key={market}>
                      <h2 className="search-head-row">{MARKET_LABEL[market]}</h2>
                      {browseOf(market).map((group) => {
                        const key = market + '|' + group.name
                        const expanded = openGroup === key
                        return (
                          <div key={key}>
                            <button
                              type="button"
                              className="search-group"
                              aria-expanded={expanded}
                              /* 마우스로 누를 때 초점이 입력칸을 떠나지 않게 해 ↓↑·Enter·Esc 가 이어서 듣게 합니다. */
                              onMouseDown={(event) => event.preventDefault()}
                              onClick={() => setOpenGroup(expanded ? null : key)}
                            >
                              <span className="search-caret" aria-hidden="true">
                                {expanded ? '▾' : '▸'}
                              </span>
                              <span className="search-group-name">{group.name}</span>
                            </button>
                            {expanded &&
                              group.items.map((product) => {
                                const row = rows.find(
                                  (item) => item.pick === 'product' && item.product === product,
                                )
                                if (!row) return null
                                return (
                                  <button
                                    key={product.code}
                                    className="search-row search-row-deep"
                                    {...rowProps(row)}
                                  >
                                    <span className="search-row-name">{product.name}</span>
                                    {/* 해외는 같은 상품군에 거래소가 섞여 있어
                                        어디 것인지를 답니다. 국내에는 거래소
                                        축이 없어 붙일 것이 없습니다. */}
                                    {product.exchange !== '' && (
                                      <span className="search-row-where">{product.exchange}</span>
                                    )}
                                  </button>
                                )
                              })}
                          </div>
                        )
                      })}
                    </div>
                  ))}
                </>
              )}
            </div>
  )
}
