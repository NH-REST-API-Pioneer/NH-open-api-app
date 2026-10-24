import { useEffect, useRef, useState } from 'react'
import type { Product, RecentItem } from '../lib/types'
import type { Market } from '../data/instruments'
import type { MasterState } from '../data/master'
import {
  MARKETS,
  browseOf,
  frontCode,
  hitKey,
  searchInstruments,
} from '../lib/instrumentSearch'
import { renderSearchList, type Row } from './SearchBoxList'

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

            {renderSearchList({
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
            })}
          </div>
        </div>
      )}
    </>
  )
}
