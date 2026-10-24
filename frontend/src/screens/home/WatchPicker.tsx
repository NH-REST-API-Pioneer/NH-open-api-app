import { useEffect, useRef, useState } from 'react'
import { Modal } from '../../app/Modal'
import { resolve, type ContractRef, type Market } from '../../data/instruments'
import { tileOf, watchable } from '../../data/homeWatch'
import type { Product, RecentItem } from '../../lib/types'
import { RECENT_EMPTY } from '../../lib/labels'
import {
  KIND_LABEL,
  MARKETS,
  MARKET_LABEL,
  browseOf,
  frontCode,
  hitKey,
  hitsOfProduct,
  searchInstruments,
  type Hit,
} from '../../lib/instrumentSearch'

/* 관심종목에 담을 종목 고르기 — 종목 마스터 전체에서 이름·코드로 찾습니다.
 *
 * **상단 검색과 같은 부품입니다** — 찾는 규칙(`lib/instrumentSearch.ts`), 줄 셋
 * (품목 행·종목 행·담을 수 없는 행), 입력 전의 최근 본·둘러보기, 시장 머리,
 * 상한과 「N개 더」까지. 같은 글자에 두 창이 다른 것을 찾아 주면 사용자는
 * 어느 쪽이 맞는지 알 수 없습니다. 다른 것은 제목과 **누른 뒤의 일**뿐입니다 —
 * 검색은 그 종목의 화면으로 가고, 여기는 담기만 하고 화면은 그대로입니다.
 *
 * **담기는 것은 시세를 부를 수 있는 계약 하나입니다.** 품목 이름을 친 사람은
 * 아직 어느 월물인지 안 정했으므로 품목 행을 펼쳐 월물을 고르게 합니다. 행사가를
 * 아직 안 고른 옵션과 스프레드는 부를 코드가 아니라서 담지 못하고, 그 줄은 왜
 * 안 되는지를 말합니다 — 영영 안 눌리는 것은 그 자리에 까닭을 세웁니다. 행이
 * 없으면 「없다」와 「담을 수 없다」가 안 갈려, 오타인지 규칙인지 모릅니다.
 */

/** 결과 품목 상한. 상단 검색과 같은 수입니다. */
const LIMIT = 40

/** 입력 전에 세우는 최근 본 줄 수. 상단 검색과 같습니다. */
const RECENT_SHOWN = 5

/** 목록에 서는 한 줄 — 검색 결과 그대로이거나, 같은 품목의 담을 수 없는 종목
 *  여럿을 접은 한 줄입니다. */
type PickerRow =
  | Hit
  | { row: 'folded'; key: string; market: Market; product: Product; reason: string }

/** 같은 품목에서 같은 까닭으로 담을 수 없는 종목 행들을 한 줄로 접습니다 —
 *  코드로 걸린 옵션 월물이 열 줄 서면 목록이 까닭으로 찹니다. 담을 수 있는
 *  행과 품목 행은 그대로 둡니다. */
function foldUnwatchable(hits: Hit[]): PickerRow[] {
  const out: PickerRow[] = []
  const folded = new Map<string, Extract<PickerRow, { row: 'folded' }>>()
  for (const hit of hits) {
    if (hit.row !== 'contract') {
      out.push(hit)
      continue
    }
    const verdict = watchable(hit.ref.code)
    if (verdict.ok) {
      out.push(hit)
      continue
    }
    const key = `f:${hit.market}|${hit.product.code}|${verdict.reason}`
    if (folded.has(key)) continue
    const made = {
      row: 'folded' as const,
      key,
      market: hit.market,
      product: hit.product,
      reason: verdict.reason,
    }
    folded.set(key, made)
    out.push(made)
  }
  return out
}

interface Props {
  /** 이미 담긴 코드. 같은 종목을 두 칸에 담지 않습니다. */
  taken: string[]
  /** 최근 본 종목. 입력 전 첫 덩어리로 섭니다 — 담을 후보로 가장 센 신호입니다. */
  recent: RecentItem[]
  onPick: (code: string) => void
  onClose: () => void
}

/* 이 창에는 화살표 커서가 없습니다 — 마우스와 Tab 으로 고릅니다. 담을 수 없는
 * 줄은 `disabled` 라 Tab 도 건너뜁니다: 가리켜지는 것은 늘 누를 수 있는 줄
 * 하나입니다. */
export function WatchPicker({ taken, recent, onPick, onClose }: Props) {
  const [query, setQuery] = useState('')
  /** 펼쳐 둔 품목. **한 번에 하나**입니다 — 상단 검색과 같은 규칙입니다. */
  const [openHit, setOpenHit] = useState<string | null>(null)
  /** 펼쳐 둔 상품군. 여기도 한 번에 하나입니다. */
  const [openGroup, setOpenGroup] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  useEffect(() => {
    setOpenHit(null)
  }, [query])

  const term = query.trim().toLowerCase()
  const { groups, more } = searchInstruments(term, LIMIT)

  /* **친 글자가 그대로 담을 수 있는 코드면 맨 위에 한 줄.** 행사가까지 정해진
     옵션 종목은 색인의 종목 목록에 없어 검색 결과에 안 서는데, 코드를 푸는 것은
     되므로 「없다」 대신 그 종목을 세웁니다. */
  const typed = query.trim().toUpperCase()
  const direct = typed !== '' && watchable(typed).ok ? tileOf(typed) : null
  const directShown =
    direct !== null &&
    !groups.some((group) => group.hits.some((hit) => hit.row === 'contract' && hit.ref.code === typed))

  const isTaken = (code: string) => taken.includes(code)

  /** 담기는 종목 행 하나 — 담을 수 있으면 눌리고, 못 담으면 까닭이 오른쪽에 섭니다.
   *  **누르면 담기고 창이 닫힙니다.** */
  const contractRow = (ref: ContractRef, name: string | null, key: string, month: boolean) => {
    const verdict = watchable(ref.code)
    const held = isTaken(ref.code)
    return (
      <button
        key={key}
        type="button"
        className={`search-row${month ? ' search-row-month' : ''}`}
        disabled={held || !verdict.ok}
        onClick={() => onPick(ref.code)}
      >
        {!month && <span className="search-caret" aria-hidden="true" />}
        <span className="search-row-name">{name ?? ref.label}</span>
        {name !== null && <span className="search-row-expiry">{ref.label}</span>}
        <span className="search-row-code">
          {held ? '이미 담김' : verdict.ok ? ref.code : verdict.reason}
        </span>
      </button>
    )
  }

  /** 품목 행과 그 아래 펼친 월물, 또는 담을 수 없는 품목 행. 검색 결과와
   *  둘러보기가 같은 줄을 씁니다. */
  const productRows = (hit: Hit, deep: boolean) => {
    if (hit.row === 'contract') return contractRow(hit.ref, hit.product.name, hitKey(hit), false)
    /* 옵션 품목은 펼쳐도 담을 월물이 없습니다 — 행사가가 한 축 더 있어서 월물까지
       골라도 부를 코드가 아닙니다. 펼쳐서 열한 줄이 전부 안 눌리는 것보다 품목
       줄에서 까닭을 말하는 편이 짧고, 안 펼쳐지니 꺾쇠도 없습니다. */
    const optionProduct = hit.row === 'product' && hit.kind === 'option'
    const expands = hit.row === 'product' && !optionProduct
    const expanded = expands && openHit === hitKey(hit)
    return (
      <div key={hitKey(hit)}>
        <button
          type="button"
          className={`search-row${expanded ? ' search-row-open' : ''}${deep ? ' search-row-deep' : ''}`}
          aria-expanded={expands ? expanded : undefined}
          disabled={!expands}
          onClick={() => setOpenHit(expanded ? null : hitKey(hit))}
        >
          <span className="search-caret" aria-hidden="true">
            {expands ? (expanded ? '▾' : '▸') : ''}
          </span>
          <span className="search-row-name">{hit.product.name}</span>
          <span className="search-row-sub">{hit.product.code}</span>
          {hit.row === 'strike' && <span className="search-row-expiry">{hit.label}</span>}
          {expands ? (
            <span className="search-row-count">
              {hit.market === 'domestic' ? KIND_LABEL[hit.kind] + ' ' : ''}
              만기 {hit.refs.length}
            </span>
          ) : (
            /* 종류는 **국내에만** 답니다 — 팔레트와 같은 규칙입니다. 해외는 이름이
               종류를 이미 말합니다(「… 옵션」·「… 스프레드」). */
            <span className="search-row-code">
              {hit.market === 'domestic' ? `${KIND_LABEL.option} · ${OPTION_REASON}` : OPTION_REASON}
            </span>
          )}
        </button>

        {expanded &&
          hit.row === 'product' &&
          (() => {
            /* **초록은 「비워 두고 열면 이 줄이 선다」**는 뜻이라 한 품목에 하나뿐입니다.
               창이 달라도 같은 말입니다 — 어느 월물을 담을지 고를 때 그 단서가
               필요합니다. 주력 축이 있는 시장(해외)에서는 주력 줄, 없는 시장
               (국내)에서는 만기가 가장 가까운 줄입니다. */
            const front = frontCode(hit.refs)
            const hasMain = hit.refs.some((ref) => ref.main)
            return hit.refs.map((ref) => {
              const isFront = ref.code === front
              const opens = ref.main || (!hasMain && isFront)
              const verdict = watchable(ref.code)
              const held = isTaken(ref.code)
              return (
                <button
                  key={ref.code}
                  type="button"
                  className="search-row search-row-month"
                  disabled={held || !verdict.ok}
                  onClick={() => onPick(ref.code)}
                >
                  <span className="search-row-name">{ref.label}</span>
                  {ref.main || isFront ? (
                    <span className={`badge${opens ? ' badge-brand' : ''}`}>
                      {ref.main ? '주력' : '최근 만기'}
                    </span>
                  ) : null}
                  <span className="search-row-code">
                    {held ? '이미 담김' : verdict.ok ? ref.code : verdict.reason}
                  </span>
                </button>
              )
            })
          })()}
      </div>
    )
  }

  /* 풀리는 것만 세고 다섯을 셉니다 — 자른 뒤에 걸러 내면 다섯보다 적게 섭니다. */
  const shownRecent = recent.filter((item) => resolve(item.code)?.contract).slice(0, RECENT_SHOWN)

  return (
    <Modal
      label="관심종목에 추가"
      onClose={onClose}
      tall
      /* 제목을 답니다. 검색칸과 목록이라는 생김새가 종목 검색 창과 같은데
         하는 일이 다릅니다 — 검색은 그 종목의 화면으로 가고, 여기는 담기만 하고
         화면은 그대로입니다. 제목이 없으면 담으려던 사람이 화면이 안 바뀐 것을
         고장으로 봅니다. */
      head={<span className="modal-title">관심종목에 추가</span>}
    >
      <input
        ref={inputRef}
        className="modal-search"
        type="search"
        value={query}
        placeholder="종목 이름이나 코드"
        aria-label="담을 종목 찾기"
        onChange={(event) => setQuery(event.target.value)}
      />

      <div className="home-picker-rows">
        {directShown && direct && (
          <div>
            <h2 className="search-head-row">코드로 찾음</h2>
            <button
              type="button"
              className="search-row"
              disabled={isTaken(direct.code)}
              onClick={() => onPick(direct.code)}
            >
              <span className="search-caret" aria-hidden="true" />
              <span className="search-row-name">{direct.name}</span>
              <span className="search-row-code">{isTaken(direct.code) ? '이미 담김' : direct.code}</span>
            </button>
          </div>
        )}

        {term === '' ? (
          <>
            {/* 입력 전 — 최근 본 종목과 품목 둘러보기. 상단 검색과 같습니다. */}
            <div>
              <h2 className="search-head-row">최근 본</h2>
              {shownRecent.length === 0 ? (
                <p className="search-note">{RECENT_EMPTY}</p>
              ) : (
                shownRecent.map((item) => {
                  const found = resolve(item.code)
                  if (!found?.contract) return null
                  return contractRow(found.contract, found.product.name, 'r:' + item.code, false)
                })
              )}
            </div>
            {MARKETS.map((market) => (
              <div key={market}>
                <h2 className="search-head-row">{MARKET_LABEL[market]}</h2>
                {browseOf(market).map((group) => {
                  const key = market + '|' + group.name
                  const open = openGroup === key
                  return (
                    <div key={key}>
                      <button
                        type="button"
                        className={`search-row${open ? ' search-row-open' : ''}`}
                        aria-expanded={open}
                        onClick={() => setOpenGroup(open ? null : key)}
                      >
                        <span className="search-caret" aria-hidden="true">
                          {open ? '▾' : '▸'}
                        </span>
                        <span className="search-row-name">{group.name}</span>
                        <span className="search-row-count">품목 {group.items.length}</span>
                      </button>
                      {open &&
                        group.items.flatMap((product) =>
                          foldUnwatchable(hitsOfProduct(market as Market, product)).map((row) =>
                            row.row === 'folded' ? foldedRow(row) : productRows(row, true),
                          ),
                        )}
                    </div>
                  )
                })}
              </div>
            ))}
          </>
        ) : groups.length === 0 && !directShown ? (
          <p className="search-note">찾는 종목이 없습니다</p>
        ) : (
          groups.map((group) => (
            <div key={group.market}>
              <h2 className="search-head-row">{MARKET_LABEL[group.market]}</h2>
              {foldUnwatchable(group.hits).map((row) =>
                row.row === 'folded' ? foldedRow(row) : productRows(row, false),
              )}
            </div>
          ))
        )}
        {/* 상한을 넘은 만큼을 적습니다. **누를 수 없습니다** — 무엇을 담는 줄이
            아니라 목록이 잘렸다는 사실입니다. */}
        {more > 0 && (
          <p className="search-note search-more">{more}개 더 있습니다 — 검색어를 좁혀 주세요</p>
        )}
      </div>
    </Modal>
  )
}

/* 담을 수 없는 까닭 — 오른쪽 끝에 서는 한 마디라 짧고, **무엇이 모자라는지만**
 * 말합니다(`data/homeWatch.ts` 의 까닭과 같은 낱말). 「행사가 선택」이라고 쓰지
 * 않습니다 — 고르러 가는 길이 이 창에서 안 닿으므로 못 지킬 약속입니다. */
const OPTION_REASON = '행사가가 필요합니다'

/** 같은 품목의 담을 수 없는 종목 여럿을 접은 한 줄. 몇 줄을 접었는지는 안 적습니다 —
 *  담을 수 없는 줄에서 그 수는 할 일이 없는 정보입니다. 종류는 국내에만 답니다. */
function foldedRow(row: Extract<PickerRow, { row: 'folded' }>) {
  return (
    <button key={row.key} type="button" className="search-row" disabled>
      <span className="search-caret" aria-hidden="true" />
      <span className="search-row-name">{row.product.name}</span>
      <span className="search-row-sub">{row.product.code}</span>
      <span className="search-row-code">
        {row.market === 'domestic' && row.reason === OPTION_REASON
          ? `${KIND_LABEL.option} · ${row.reason}`
          : row.reason}
      </span>
    </button>
  )
}
