import { useState } from 'react'
import type { StrategyVersion } from '../../data/strategyList'
import type { Aux } from '../../data/strategyRules'
import type { ListStatus, SaveResult, StoreNote } from '../../data/strategyStore'
import { MARKETS, STATUSES, RECORDS, FILTER_DEFAULTS } from './strategyListParts'
import { useFilterBox } from './useFilterBox'
import { useListView } from './useListView'
import { makeListStats } from './listStats'
import { useListActions } from './useListActions'
import { renderListTable } from './StrategyListTable'
import { renderListDetail, renderDeleteConfirm } from './StrategyListDetail'
import { renderFilterFields } from './StrategyListFilters'

/* 전략 목록 — 필터 / 전략·버전 표 / 선택 상세의 3열.
 *
 * 표에 세우는 것은 전략이 아니라 **버전**입니다. 실행 중인 v3 과 편집 중인
 * v4 초안은 서로 다른 것이고, 한 줄로 합치면 어느 쪽 성과인지 읽을 수 없게
 * 됩니다. 같은 전략임은 둘째 줄부터 들여써서 나타냅니다.
 */

interface Props {
  rows: StrategyVersion[]
  /** 목록을 받아 온 상태. **받는 중과 못 받음은 얼굴이 다릅니다** — 앞은
   *  기다리면 되고 뒤는 아닙니다. 둘 다 「전략이 없다」와 다른 말입니다. */
  status: ListStatus
  /** 못 받았으면 그 까닭 한 줄. */
  failure: string | null
  /** 담아 둔 파일을 서버가 못 읽었거나 안 쓴 까닭. **「목록을 못 받았다」와
   *  다른 말입니다** — 그쪽은 서버에 못 닿은 것이고, 이쪽은 서버가 파일을 못
   *  읽은 것이라 다시 받아도 같습니다. 할 말이 없으면 `null`. */
  storeWhy: StoreNote | null
  onReload: () => void
  /** 고른 버전을 설정까지 베껴 사본으로 저장합니다(`duplicateVersion`). 저장이
   *  막히면 사본 줄은 목록에서 걷히고, 답의 한 줄이 돌아옵니다. */
  onDuplicate: (source: StrategyVersion, copy: StrategyVersion) => Promise<SaveResult>
  /** 그 버전을 보관합니다(`archiveVersion`). 서버가 받은 뒤에만 목록이 「보관」이 되고,
   *  막히면 답의 한 줄이 돌아옵니다. */
  onArchive: (id: string) => Promise<SaveResult>
  /** 새 버전을 **설정 탭의 초안으로** 엽니다. 목록에는 저장이 통과한 뒤에
   *  섭니다 — 목록에만 있고 서버에 없는 줄은 새로고침에 사라집니다. */
  onNewDraft: (row: StrategyVersion) => void
  /** 그 버전의 보조 설정. **상세의 예산·수량·손실 한도는 여기서 읽습니다** —
   *  고치는 자리가 설정이고, 줄에 적힌 값은 그 설정에서 나옵니다. 둘을 따로
   *  보면 상세와 설정이 다른 수를 말합니다. */
  auxOf: (id: string) => Aux
  /** 그 버전을 서버에서 지웁니다. 목록에서 빼는 것도 이쪽이 합니다. */
  onDelete: (id: string) => void
  selectedId: string | null
  onSelect: (id: string | null) => void
  onOpenSettings: () => void
  onOpenCheck: () => void
  onOpenRun: () => void
  /** 상태 칸의 「검증 중 n」·「거래 중 n」을 눌렀을 때 — 그 버전의 실행이 도는 탭을
   *  열고 그 버전의 첫 실행을 고릅니다. */
  onOpenRunsOf: (row: StrategyVersion, tab: 'verify' | 'run') => void
}

export function StrategyList({
  rows,
  status: listStatus,
  failure,
  storeWhy,
  onReload,
  onDuplicate,
  onArchive,
  onNewDraft,
  auxOf,
  onDelete,
  selectedId,
  onSelect,
  onOpenSettings,
  onOpenCheck,
  onOpenRun,
  onOpenRunsOf,
}: Props) {
  const [query, setQuery] = useState(FILTER_DEFAULTS.query)
  const [market, setMarket] = useState<(typeof MARKETS)[number]>(FILTER_DEFAULTS.market)
  const [status, setStatus] = useState<(typeof STATUSES)[number]>(FILTER_DEFAULTS.status)
  const [record, setRecord] = useState<(typeof RECORDS)[number]>(FILTER_DEFAULTS.record)
  const [runningOnly, setRunningOnly] = useState(FILTER_DEFAULTS.runningOnly)

  /* 기본값과 다른 필터의 수. 검색어는 공백만이면 거르지 않으므로 기본값으로 봅니다. */
  const filtersOn = [
    query.trim() !== FILTER_DEFAULTS.query,
    market !== FILTER_DEFAULTS.market,
    status !== FILTER_DEFAULTS.status,
    record !== FILTER_DEFAULTS.record,
    runningOnly !== FILTER_DEFAULTS.runningOnly,
  ].filter(Boolean).length

  const { filterOpen, setFilterOpen, filterWrapRef, filterButtonRef, filterFirstRef, listRef, closeFilter } =
    useFilterBox()

  const { verify, shown, selected, selectedCurrency, recent, saving } = useListView({
    rows,
    query,
    market,
    status,
    record,
    runningOnly,
    selectedId,
    onSelect,
  })
  const { liveOf, nameText, accountEnvironments } = makeListStats({ verify })

  function resetFilters() {
    setQuery(FILTER_DEFAULTS.query)
    setMarket(FILTER_DEFAULTS.market)
    setStatus(FILTER_DEFAULTS.status)
    setRecord(FILTER_DEFAULTS.record)
    setRunningOnly(FILTER_DEFAULTS.runningOnly)
  }

  const {
    canDelete,
    archived,
    reasons,
    named,
    addNew,
    duplicate,
    archive,
    deleting,
    setDeleting,
    remove,
    confirmRemove,
  } = useListActions({
    selected,
    saving,
    onNewDraft,
    resetFilters,
    onDuplicate,
    onArchive,
    onDelete,
    liveOf,
  })

  /* 표에서 같은 전략의 둘째 버전부터 들여씁니다. 걸러진 뒤의 차례로 보므로,
     앞 버전이 필터에 걸려 빠지면 남은 줄이 맨 위 줄이 됩니다. */
  const isSub = (index: number) =>
    index > 0 && shown[index - 1].groupId === shown[index].groupId

  return (
    <div className="stg-list" ref={listRef}>
      <aside className="card stg-filter" aria-label="필터">
        <h2 className="stg-card-title">필터</h2>
        {renderFilterFields({
          query,
          setQuery,
          market,
          setMarket,
          status,
          setStatus,
          record,
          setRecord,
          runningOnly,
          setRunningOnly,
          resetFilters,
        })}
      </aside>

      <section className="card stg-main" aria-label="전략 목록">
        <div className="stg-main-head">
          <div className="stg-main-titles">
            <h2 className="stg-card-title">
              전략 목록 <span className="stg-count">전체 {rows.length}개</span>
            </h2>
            {/* 어느 범위의 성과인지를 표 위에 한 번 적습니다. **기록 유형은
                행마다 다르므로 여기에 못 박지 않습니다** — 한 장부 이름을
                적어 두면 다른 장부에서 센 줄이 그 말 아래 섭니다.
                필터로 한 유형을 골랐을 때만 그 말을 붙입니다 — 그때는 모든
                줄의 성과가 그 유형으로 센 값입니다. */}
            <p className="stg-range">최근 30일{record === '전체' ? '' : ` · ${record}`}</p>
          </div>
          {/* 좁은 폭에서만 서는 필터 단추와 그 상자. 넓은 폭에서는 필터 열이 늘
              보이므로 단추가 없습니다(`strategy.css` 의 `stg` 컨테이너 문턱). */}
          <span className="stg-filter-pop" ref={filterWrapRef}>
            <button
              ref={filterButtonRef}
              type="button"
              className="btn btn-quiet stg-filter-toggle"
              aria-expanded={filterOpen}
              aria-controls="stg-filter-box"
              onClick={() => (filterOpen ? closeFilter() : setFilterOpen(true))}
            >
              {filtersOn > 0 ? `필터 · ${filtersOn}` : '필터'}
            </button>
            {filterOpen && (
              <div id="stg-filter-box" className="stg-filter-box" role="group" aria-label="필터">
                {renderFilterFields({
                  query,
                  setQuery,
                  market,
                  setMarket,
                  status,
                  setStatus,
                  record,
                  setRecord,
                  runningOnly,
                  setRunningOnly,
                  resetFilters,
                }, filterFirstRef)}
              </div>
            )}
          </span>
          <div className="stg-main-actions">
            <button type="button" className="btn btn-primary" onClick={addNew}>
              새 전략
            </button>
            {/* 고른 줄에 하는 일이라 고른 것이 없으면 할 일이 없습니다.
                누르게 두고 아무 일도 안 하면 눌린 것인지조차 알 수 없습니다. */}
            <button
              type="button"
              className="btn btn-quiet"
              aria-disabled={!selected || saving}
              aria-describedby={!selected ? 'stg-why-pick' : saving ? 'stg-why-saving' : undefined}
              onClick={() => !saving && void duplicate()}
            >
              복제
            </button>
            <button
              type="button"
              className="btn btn-quiet"
              aria-disabled={!selected || archived || saving}
              aria-describedby={
                !selected ? 'stg-why-pick' : archived ? 'stg-why-archive' : saving ? 'stg-why-saving' : undefined
              }
              onClick={() => !archived && !saving && void archive()}
            >
              보관
            </button>
            <button
              type="button"
              className="btn btn-quiet"
              aria-disabled={!canDelete}
              aria-describedby={!selected ? 'stg-why-pick' : canDelete ? undefined : 'stg-why-delete'}
              onClick={remove}
            >
              삭제
            </button>
          </div>
        </div>
        {/* 이유가 없을 때도 자리를 비워 둡니다. 줄이 생겼다 없어지면 고르는
            줄을 바꿀 때마다 표가 한 줄만큼 오르내려, 눈이 보던 행을 놓칩니다. */}
        {deleting && selected && renderDeleteConfirm({
          selected,
          liveOf,
          rows,
          setDeleting,
          nameText,
          confirmRemove,
        })}
        <p className="stg-why">
          {reasons.map((reason, index) => (
            /* 방금 누른 일이 서버에 막힌 글만 오류색입니다 — 나머지는 「지금 못 누르는
               까닭」이라 흐린 글자입니다. */
            <span key={reason.id} id={reason.id} className={'fail' in reason && reason.fail ? 'stg-why-fail' : undefined}>
              {index > 0 && <span aria-hidden="true"> · </span>}
              {named && reason.name ? `${reason.name} — ` : ''}
              {reason.text}
            </span>
          ))}
        </p>

        {/* 담아 둔 파일을 못 읽었는데 **줄이 일부라도 서 있으면** 표 바로 위에
            한 줄로 말합니다. 목록이 통째로 비면 표 자리의 블록이 대신 말하므로
            이 줄은 서지 않습니다 — 값이 선 자리에 블록을 세우면 서 있는 줄을
            가리고, 빈 자리에 줄과 블록을 함께 세우면 같은 말을 두 번 합니다.
            빈 자리에서만 참인 이유(「목록이 비어 있어도」)는 이 줄에 싣지
            않습니다. 둘을 마침표로 잇는 것은 이유 안에 이미 줄표가 있을 수
            있어서입니다. */}
        {storeWhy && rows.length > 0 && (
          <p className="stg-store-why">
            {storeWhy.reason && !storeWhy.emptyOnly
              ? `${storeWhy.title}. ${storeWhy.reason}`
              : storeWhy.title}
          </p>
        )}

        {renderListTable({
          listStatus,
          failure,
          onReload,
          rows,
          storeWhy,
          addNew,
          shown,
          resetFilters,
          selectedId,
          onSelect,
          isSub,
          nameText,
          liveOf,
          onOpenRunsOf,
          record,
        })}
      </section>

      <aside className="card stg-detail" aria-label="선택 상세">
        {renderListDetail({
          selected,
          nameText,
          onOpenSettings,
          accountEnvironments,
          auxOf,
          selectedCurrency,
          recent,
          onOpenCheck,
          onOpenRun,
        })}
      </aside>
    </div>
  )
}
