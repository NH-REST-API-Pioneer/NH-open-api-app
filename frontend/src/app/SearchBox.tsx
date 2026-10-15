import { useEffect, useRef, useState } from 'react'
import type { Product, RecentItem } from '../lib/types'
import { needsLeg, type ContractRef, type Market } from '../data/instruments'
import { refreshMaster, type MasterState } from '../data/master'
import { RECENT_EMPTY } from '../lib/labels'
import {
  KIND_LABEL,
  MARKETS,
  MARKET_LABEL,
  browseOf,
  frontCode,
  hitKey,
  searchInstruments,
  type Hit,
} from '../lib/instrumentSearch'

/* 상단 검색 — 1단의 알약 하나와, 누르면 뜨는 가운데 창.
 *
 * **입력 전에도 내용이 있습니다.** 빈 창을 띄우고 치기를 기다리는 대신 최근 본
 * 종목과 품목 둘러보기를 세웁니다 — 다시 여는 것이 대부분이고, 처음 오는
 * 사람에게는 무엇이 있는지 훑는 길이 필요합니다.
 *
 * **결과가 곧 종목입니다.** 품목 이름을 친 사람은 아직 어느 만기인지 안 정했고
 * 종목코드를 친 사람은 이미 정했으므로, 품목에 걸리면 그 품목의 가장 가까운
 * 만기 한 줄, 종목에 걸리면 그 종목이 섭니다.
 *
 * **여기서 끝까지 못 정하는 것은 주문 화면이 마저 정합니다.** 옵션은 행사가가
 * 한 축 더 있어 고르면 체인이 열립니다. 스프레드도 선물과 같이 주문 화면에서
 * 열립니다.
 *
 * **가격을 안 넣습니다.** 종목을 특정하는 값이 아니고, 결과 한 줄마다 시세를
 * 구독하면 화면 전체가 나눠 쓰는 실시간 구독을 검색 한 번이 다 먹습니다.
 */

/** 결과 전체 상한. 이보다 많으면 마지막 줄이 몇 개가 더 있는지 말합니다. */
const LIMIT = 40

/** 입력 전에 세우는 최근 본 줄 수. */
const RECENT_SHOWN = 5

/** 화살표가 훑는 한 줄. 세 상태가 같은 목록을 씁니다 — 훑는 차례와 보이는
 *  차례가 갈리면 화면이 가리키는 줄과 Enter 로 열리는 줄이 달라집니다. */
type Row =
  | { pick: 'recent'; item: RecentItem }
  | { pick: 'product'; market: Market; product: Product }
  | { pick: 'hit'; hit: Hit }
  /** 펼친 품목 아래의 월물 한 줄. */
  | { pick: 'month'; product: Product; ref: ContractRef; front: boolean }

interface Props {
  master: MasterState
  /** 최근 본 종목. 입력 전 첫 덩어리로 섭니다. */
  recent: RecentItem[]
  /** 종목을 엽니다. 넘기는 것은 **코드 하나**입니다. */
  onOpenInstrument: (code: string) => void
  /** 품목을 엽니다 — 둘러보기에서 품목을 고르면 여기로 옵니다. */
  onOpenProduct: (market: Market, product: Product) => void
}

export function SearchBox({ master, recent, onOpenInstrument, onOpenProduct }: Props) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  /** 펼쳐 둔 상품군. **한 번에 하나**입니다 — 종목 화면의 접기와 같은 규칙이라
   *  앱 안에서 접는 동작이 하나입니다. */
  const [openGroup, setOpenGroup] = useState<string | null>(null)
  /** 결과에서 펼쳐 둔 품목. 여기도 **한 번에 하나**입니다 — 서른여섯 줄짜리
   *  품목 둘이 동시에 펴지면 목록이 터집니다. */
  const [openHit, setOpenHit] = useState<string | null>(null)
  const pillRef = useRef<HTMLButtonElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  /* 「/」 는 창을 엽니다. 손이 키보드에 있는 화면에서 가장 빠른 길입니다. */
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const typing = target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA'
      if (event.key === '/' && !typing) {
        event.preventDefault()
        setOpen(true)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  useEffect(() => {
    setCursor(0)
    setOpenHit(null)
  }, [query])

  /* **키보드로 옮겼을 때만 굴립니다.** 마우스가 커서를 옮기는데 그때도 굴리면,
     목록 가장자리에 마우스를 둔 것만으로 목록이 한 번 튀고 튄 자리에 다른 줄이
     들어와 또 튑니다. */
  const byKeyboard = useRef(false)
  useEffect(() => {
    if (!byKeyboard.current) return
    listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [cursor])

  /* 펼치면 그 품목 행을 목록 맨 위로 올립니다 — 안 올리면 펼친 것이 화면
     밖에서 열려, 누른 사람이 아무 일도 안 일어난 것으로 봅니다. */
  useEffect(() => {
    if (openHit === null) return
    listRef.current?.querySelector('.search-row-open')?.scrollIntoView({ block: 'start' })
  }, [openHit])

  const term = query.trim().toLowerCase()

  /* 찾기는 공용 규칙입니다(`lib/instrumentSearch.ts`) — 홈의 담기 창과 같은
     글자에 같은 것을 찾아 줍니다. 여기는 찾은 것을 **여는** 자리입니다. */
  const { groups, more } = searchInstruments(term, LIMIT)

  const shownRecent = recent.slice(0, RECENT_SHOWN)

  /* 화살표가 훑는 목록. 접힌 상품군의 품목은 안 들어갑니다 — 보이지 않는 줄로
     커서가 넘어가면 화면이 아무 데도 안 가리키는 상태가 됩니다. */
  const rows: Row[] =
    term !== ''
      ? groups.flatMap((group) =>
          group.hits.flatMap((hit) => {
            const head = { pick: 'hit', hit } as Row
            if (hit.row !== 'product' || openHit !== hitKey(hit)) return [head]
            /* **월물은 상한을 안 겁니다.** 만기 순으로 이어지는 하나의 축이라
               자르면 「12월물이 없네」가 되는데, 찾는 것이 원월물일 수 있습니다.
               상한 40은 품목 행에만 겁니다. */
            const front = frontCode(hit.refs)
            return [
              head,
              ...hit.refs.map(
                (ref) =>
                  ({
                    pick: 'month',
                    product: hit.product,
                    ref,
                    front: ref.code === front,
                  }) as Row,
              ),
            ]
          }),
        )
      : [
          ...shownRecent.map((item) => ({ pick: 'recent', item }) as Row),
          ...MARKETS.flatMap((market) =>
            browseOf(market).flatMap((group) =>
              openGroup === market + '|' + group.name
                ? group.items.map((product) => ({ pick: 'product', market, product }) as Row)
                : [],
            ),
          ),
        ]

  const close = () => {
    setOpen(false)
    setQuery('')
    /* 닫고 나면 초점은 다시 알약입니다 — 열었던 자리로 돌아가지 않으면 다음
       Tab 이 화면 맨 앞에서 시작합니다. */
    pillRef.current?.focus()
  }

  const choose = (row: Row) => {
    if (row.pick === 'recent') return void (close(), onOpenInstrument(row.item.code))
    if (row.pick === 'product') return void (close(), onOpenProduct(row.market, row.product))
    if (row.pick === 'month') return void (close(), onOpenInstrument(row.ref.code))

    const hit = row.hit
    /* 행사가 줄은 그 품목의 그 만기를 엽니다 — 주문 화면이 체인을 펴고 헤더는
       「행사가 선택」으로 섭니다. 안내와 여는 일이 같은 동작입니다. */
    if (hit.row === 'strike') return void (close(), onOpenInstrument(hit.code))
    if (hit.row === 'contract') return void (close(), onOpenInstrument(hit.ref.code))
    /* 품목 행은 **여는 줄이 아니라 펼치는 줄**입니다 — 창은 닫지 않습니다. */
    setOpenHit(openHit === hitKey(hit) ? null : hitKey(hit))
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      byKeyboard.current = true
      setCursor((c) => Math.min(c + 1, rows.length - 1))
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      byKeyboard.current = true
      setCursor((c) => Math.max(c - 1, 0))
      return
    }
    if (event.key === 'Enter') {
      const row = rows[cursor]
      if (!row) return
      event.preventDefault()
      choose(row)
    }
  }

  const rowId = (index: number) => `search-row-${index}`
  const index = (row: Row) => rows.indexOf(row)

  const rowProps = (row: Row) => ({
    id: rowId(index(row)),
    type: 'button' as const,
    role: 'option',
    'aria-selected': index(row) === cursor,
    tabIndex: -1,
    'data-active': index(row) === cursor,
    onMouseEnter: () => {
      byKeyboard.current = false
      setCursor(index(row))
    },
    onClick: () => choose(row),
  })

  return (
    <>
      {/* 알약 하나가 한 덩어리로 읽힙니다 — 단축키도 문구 안입니다. */}
      <button ref={pillRef} type="button" className="search-pill" onClick={() => setOpen(true)}>
        <span className="search-icon" aria-hidden="true">
          🔍
        </span>
        종목명·코드 입력 (단축키 /)
      </button>

      {open && (
        <div
          className="search-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) close()
          }}
        >
          <div className="search-modal" role="dialog" aria-modal="true" aria-label="종목 검색">
            {/* 입력은 맨 위에 고정하고 아래만 스크롤합니다. 닫는 X 는 안 붙입니다 —
                오른쪽 위 단추는 초점 순서에서 입력과 다투는데, 나가는 길은 Esc 와
                바깥 클릭으로 이미 둘입니다. 그 자리에 Esc 를 작게 적습니다. */}
            <div className="search-head">
              <span className="search-icon" aria-hidden="true">
                🔍
              </span>
              <input
                ref={inputRef}
                className="search-field"
                type="search"
                role="combobox"
                aria-expanded="true"
                aria-controls="search-list"
                aria-activedescendant={rows.length > 0 ? rowId(cursor) : undefined}
                value={query}
                placeholder="종목명·코드 입력"
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={onKeyDown}
              />
              <span className="kbd" aria-hidden="true">
                Esc
              </span>
            </div>

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
          </div>
        </div>
      )}
    </>
  )
}
