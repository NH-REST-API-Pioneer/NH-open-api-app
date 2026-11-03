import { useId, useRef, useState } from 'react'
import { contractsOf, productOf, resolve, type ContractRef, type Market } from '../../data/instruments'
import { refreshMaster } from '../../data/master'
import {
  SYM_AUTO,
  SYM_REFUSED,
  USD_PRODUCT,
  autoSymGuess,
  autoSymLabel,
  isUsdFutures,
  symLabel,
  symVerdict,
} from '../../data/pyrun'
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
import { useMasterStatus } from '../../lib/useMaster'
import { foldUnwatchable, type PickerRow } from '../home/WatchPicker'

/* 팀: 「실행 세우기」의 종목 고르기 — 종목 마스터 전체에서 이름·코드로 찾되, 고를 수 있는 것은
 * 미국달러선물(`A75…`)뿐입니다.
 *
 * 찾는 규칙·줄 모양·접기는 상단 검색·관심종목 담기 창과 같은 부품입니다(`lib/instrumentSearch.ts`,
 * `home/WatchPicker.tsx`). 같은 글자에 창마다 다른 것을 찾아 주면 어느 쪽이 맞는지 알 수 없습니다.
 * 다른 것은 **고를 수 있는 줄이 하나뿐**이라는 점입니다 — 서버가 다른 종목을 거절하지만, 거절될 줄을
 * 숨기면 「없다」와 「이 실행기는 안 된다」가 안 갈려서 줄은 두고 까닭을 답니다.
 *
 * 값은 `sym` 문자열 하나입니다. 빈 문자열이 「최근월물 (자동)」이고 그대로 `sym: null` 로 나갑니다. */

/** 결과 품목 상한. 상단 검색과 같은 수입니다. */
const LIMIT = 40

const DOMESTIC: Market = 'domestic'

/** 미국달러선물의 월물. 마스터를 아직 못 받았으면 빈 목록입니다. */
function usdMonths(): ContractRef[] {
  const product = productOf(DOMESTIC, USD_PRODUCT)
  return product ? contractsOf(product, 'futures') : []
}

/** 「최근월물 (자동)」이 가리킬 코드. 서버의 규칙(만기가 가장 가까운 A75 월물)과 같은 값이며,
 *  마스터를 모르면 `null` 입니다. */
function autoCodeOf(refs: ContractRef[]): string | null {
  return frontCode(refs) ?? refs[0]?.code ?? null
}

/** 지금 고른 종목을 글로. 확인 얼굴과 입력칸이 같은 문장을 씁니다. */
export function symText(sym: string): string {
  const code = sym.trim()
  return symLabel(code, code ? (resolve(code)?.name ?? null) : null, autoCodeOf(usdMonths()))
}

/** 확인 얼굴의 종목 글. 「최근월물」은 서버가 시작할 때 라이브 조회로 정하므로 코드는 어림으로만 적습니다
 *  (입력칸의 글과 다릅니다 — 거기는 고르는 자리고, 여기는 실제 주문이 나가기 직전입니다). */
export function symConfirmText(sym: string): string {
  return sym.trim() === '' ? autoSymGuess(autoCodeOf(usdMonths())) : symText(sym)
}

export function PySymbolPicker({ sym, onChange }: { sym: string; onChange: (sym: string) => void }) {
  const master = useMasterStatus()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  /** 펼쳐 둔 품목·상품군. **각각 한 번에 하나**입니다 — 상단 검색과 같은 규칙입니다. */
  const [openHit, setOpenHit] = useState<string | null>(null)
  const [openGroup, setOpenGroup] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  /* 닫고 입력칸에 초점을 돌려줄 때 그 초점이 다시 목록을 열지 않게 합니다. */
  const quiet = useRef(false)
  const listId = useId()

  const ready = master.status === 'ready'
  const months = ready ? usdMonths() : []
  const autoCode = autoCodeOf(months)
  const usd = ready ? productOf(DOMESTIC, USD_PRODUCT) : null

  const term = query.trim().toLowerCase()
  const { groups, more } = searchInstruments(term, LIMIT)

  const focusInput = () => {
    quiet.current = true
    inputRef.current?.focus()
    quiet.current = false
  }

  const close = () => {
    setOpen(false)
    setQuery('')
    setOpenHit(null)
  }

  const pick = (code: string) => {
    onChange(code)
    close()
    /* 마우스는 초점이 입력칸에 머물고, 키보드로 줄을 눌렀다면 그 줄이 사라지므로 되돌립니다. */
    focusInput()
  }

  /** 월물 줄 하나. 고를 수 있으면 눌리고, 못 고르면 까닭이 오른쪽에 섭니다. */
  const contractRow = (ref: ContractRef, name: string | null, key: string, month: boolean, badge?: string) => {
    const verdict = symVerdict(ref.code)
    const picked = ref.code === sym
    return (
      <button
        key={key}
        type="button"
        className={`search-row pyrun-sym-row${month ? ' search-row-month' : ''}${picked ? ' is-picked' : ''}`}
        disabled={!verdict.ok}
        aria-current={picked ? 'true' : undefined}
        onClick={() => pick(ref.code)}
      >
        {!month && <span className="search-caret" aria-hidden="true" />}
        <span className="search-row-name">{name ?? ref.label}</span>
        {picked && <span className="pyrun-sym-check" aria-hidden="true">✓</span>}
        {name !== null && <span className="search-row-expiry">{ref.label}</span>}
        {badge && <span className="badge badge-brand">{badge}</span>}
        <span className="search-row-code">{verdict.ok ? ref.code : verdict.reason}</span>
      </button>
    )
  }

  /** 품목 행과 그 아래 펼친 월물. 미국달러선물이 하나도 없는 품목은 펼쳐도 고를 월물이 없어,
   *  펼쳐서 줄마다 같은 까닭을 되풀이하는 대신 품목 줄에서 한 번 말합니다. */
  const productRows = (hit: Hit, deep: boolean) => {
    if (hit.row === 'contract') return contractRow(hit.ref, hit.product.name, hitKey(hit), false)
    const expands = hit.row === 'product' && hit.refs.some((ref) => isUsdFutures(ref.code))
    const expanded = expands && openHit === hitKey(hit)
    return (
      <div key={hitKey(hit)}>
        <button
          type="button"
          className={`search-row pyrun-sym-row${expanded ? ' search-row-open' : ''}${deep ? ' search-row-deep' : ''}`}
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
          {hit.row === 'product' && expands ? (
            <span className="search-row-count">
              {hit.market === 'domestic' ? KIND_LABEL[hit.kind] + ' ' : ''}
              만기 {hit.refs.length}
            </span>
          ) : (
            <span className="search-row-code">{SYM_REFUSED}</span>
          )}
        </button>
        {expanded &&
          hit.row === 'product' &&
          (() => {
            /* 초록은 「비워 두면 이 줄이 선다」는 뜻이라 한 품목에 하나뿐입니다(다른 창과 같은 말). */
            const front = frontCode(hit.refs)
            return hit.refs.map((ref) =>
              contractRow(ref, null, ref.code, true, ref.code === front ? '최근 만기' : undefined),
            )
          })()}
      </div>
    )
  }

  /** 같은 품목의 못 고르는 종목 여럿을 접은 한 줄. */
  const foldedRow = (row: Extract<PickerRow, { row: 'folded' }>) => (
    <button key={row.key} type="button" className="search-row pyrun-sym-row" disabled>
      <span className="search-caret" aria-hidden="true" />
      <span className="search-row-name">{row.product.name}</span>
      <span className="search-row-sub">{row.product.code}</span>
      <span className="search-row-code">{row.reason}</span>
    </button>
  )

  const rowsOf = (hits: Hit[], deep: boolean) =>
    foldUnwatchable(hits, symVerdict).map((row) => (row.row === 'folded' ? foldedRow(row) : productRows(row, deep)))

  const label = sym.trim() === '' ? autoSymLabel(autoCode) : symText(sym)

  return (
    <div
      className="pyrun-sym"
      onBlur={(event) => {
        /* 초점이 이 칸 밖으로 나가면 닫습니다. 목록 안(줄 단추)으로 옮겨 가는 것은 나간 것이 아닙니다. */
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) close()
      }}
      onKeyDown={(event) => {
        /* Esc 는 목록만 닫고 창은 닫지 않습니다 — 창의 Esc 까지 올라가지 않게 막습니다. */
        if (event.key !== 'Escape' || !open) return
        event.preventDefault()
        event.stopPropagation()
        close()
        focusInput()
      }}
    >
      <div className="run-add-row">
        <span className="run-add-label" id={`${listId}-label`}>
          종목
        </span>
        <input
          ref={inputRef}
          className="control pyrun-sym-input"
          type="text"
          aria-labelledby={`${listId}-label`}
          aria-expanded={open}
          autoComplete="off"
          spellCheck={false}
          /* 닫혀 있을 때는 지금 고른 것을 보이고, 열면 비워서 바로 칠 수 있게 합니다. */
          value={open ? query : label}
          /* 닫힌 칸에 치면 고른 글 뒤에 글자가 붙으므로, 닫혀 있을 때는 읽기만 합니다.
             Esc 로 닫은 뒤에는 Enter·Space·↓ 나 클릭으로 다시 엽니다. */
          readOnly={!open}
          placeholder={open ? '종목 이름이나 코드' : ''}
          onKeyDown={(event) => {
            if (open || (event.key !== 'Enter' && event.key !== ' ' && event.key !== 'ArrowDown')) return
            event.preventDefault()
            setOpen(true)
          }}
          onFocus={() => {
            if (!quiet.current) setOpen(true)
          }}
          onClick={() => setOpen(true)}
          onChange={(event) => {
            setOpen(true)
            setQuery(event.target.value)
            setOpenHit(null)
          }}
        />
      </div>

      {open && (
        /* 줄을 눌러도 초점이 입력칸을 떠나지 않게 합니다(떠나면 위의 blur 가 목록을 먼저 닫습니다). */
        <div className="search-list pyrun-sym-list" id={listId} role="group" aria-label="종목 고르기" onMouseDown={(event) => event.preventDefault()}>
          <button
            type="button"
            className={`search-row pyrun-sym-row${sym.trim() === '' ? ' is-picked' : ''}`}
            aria-current={sym.trim() === '' ? 'true' : undefined}
            onClick={() => pick('')}
          >
            <span className="search-caret" aria-hidden="true" />
            <span className="search-row-name">{SYM_AUTO}</span>
            {sym.trim() === '' && <span className="pyrun-sym-check" aria-hidden="true">✓</span>}
            {autoCode && <span className="search-row-code">{autoCode}</span>}
          </button>

          {master.status === 'loading' ? (
            <p className="search-note">종목 목록을 받는 중입니다</p>
          ) : master.status === 'failed' ? (
            <p className="search-note">
              종목 목록을 못 받았습니다
              <button type="button" className="search-retry" onClick={() => void refreshMaster()}>
                다시 받기
              </button>
            </p>
          ) : term === '' ? (
            <>
              {/* 입력 전 — 고를 수 있는 미국달러선물 월물이 먼저이고, 그 아래가 둘러보기입니다. */}
              {usd && months.length > 0 && (
                <div>
                  <h2 className="search-head-row">{usd.name}</h2>
                  {months.map((ref) => contractRow(ref, null, 'u:' + ref.code, true, ref.code === autoCode ? '최근 만기' : undefined))}
                </div>
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
                          className={`search-row${expanded ? ' search-row-open' : ''}`}
                          aria-expanded={expanded}
                          onClick={() => setOpenGroup(expanded ? null : key)}
                        >
                          <span className="search-caret" aria-hidden="true">
                            {expanded ? '▾' : '▸'}
                          </span>
                          <span className="search-row-name">{group.name}</span>
                          <span className="search-row-count">품목 {group.items.length}</span>
                        </button>
                        {expanded && group.items.flatMap((product) => rowsOf(hitsOfProduct(market, product), true))}
                      </div>
                    )
                  })}
                </div>
              ))}
            </>
          ) : groups.length === 0 ? (
            <p className="search-note">찾는 종목이 없습니다</p>
          ) : (
            groups.map((group) => (
              <div key={group.market}>
                <h2 className="search-head-row">{MARKET_LABEL[group.market]}</h2>
                {rowsOf(group.hits, false)}
              </div>
            ))
          )}
          {more > 0 && <p className="search-note search-more">{more}개 더 있습니다 — 검색어를 좁혀 주세요</p>}
        </div>
      )}
    </div>
  )
}
