import { instrumentNameOf, type StrategyVersion } from '../../data/strategyList'
import type { ListStatus, StoreNote } from '../../data/strategyStore'
import { RECORDS, RecentCells, versionOnly } from './strategyListParts'
import type { makeListStats } from './listStats'

type ListStats = ReturnType<typeof makeListStats>

/** 가운데 칸 — 받는 중·못 받음·없음·0줄 안내, 또는 전략·버전 표. */
export function renderListTable({
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
}: {
  listStatus: ListStatus
  failure: string | null
  onReload: () => void
  rows: StrategyVersion[]
  storeWhy: StoreNote | null
  addNew: () => void
  shown: StrategyVersion[]
  resetFilters: () => void
  selectedId: string | null
  onSelect: (id: string | null) => void
  isSub: (index: number) => boolean
  nameText: ListStats['nameText']
  liveOf: ListStats['liveOf']
  onOpenRunsOf: (row: StrategyVersion, tab: 'verify' | 'run') => void
  record: (typeof RECORDS)[number]
}) {
    /* 받는 중·못 받음·없음은 **서로 다른 얼굴**입니다. 셋을 한 문장으로 묶으면
       만들어 둔 전략이 안 온 것인지 원래 없는 것인지 화면이 말하지 못합니다. */
    if (listStatus === 'loading') {
      return (
        <div className="notice">
          <p className="notice-title">저장해 둔 전략을 받는 중입니다</p>
        </div>
      )
    }
    if (listStatus === 'failed') {
      return (
        <div className="notice">
          <p className="notice-title">{failure ?? '목록을 받지 못했습니다'}</p>
          <p className="notice-reason">만들어 둔 전략은 서버에 그대로 있습니다</p>
          <button type="button" className="btn btn-quiet notice-action" onClick={onReload}>
            다시 받기
          </button>
        </div>
      )
    }
    if (rows.length === 0) {
      return (
        <div className="notice">
          {/* **「없다」고 단언하지 않습니다.** 담아 둔 파일을 못 읽었거나 안
              쓴 때는 없는 것이 아니라 못 세운 것이라, 이 자리가 그 까닭을
              말합니다. 표 위에 따로 한 줄을 두지 않습니다 — 한 화면이 같은
              사실을 두 번 말하게 됩니다.

              제목에만 경고색을 씁니다. 목록을 못 받은 것은 기다리면 되지만,
              파일을 못 읽은 것은 사람이 손을 써야 끝납니다. 덩어리를 통째로
              물들이면 화면 전체가 위험해 보입니다.

              「다시 받기」는 두지 않습니다 — 다시 받아도 같은 답이 옵니다. */}
          {storeWhy ? (
            <>
              <p className="notice-title is-warn">{storeWhy.title}</p>
              {storeWhy.reason && <p className="notice-reason">{storeWhy.reason}</p>}
            </>
          ) : (
            <>
              <p className="notice-title">저장된 전략이 없습니다</p>
              <p className="notice-reason">새 전략을 만들면 여기에 섭니다</p>
            </>
          )}
          {/* 채운 단추는 한 화면에 하나입니다 — 머리줄의 「새 전략」이 이미
              채운 단추라, 같은 일을 하는 이 단추는 한 급 낮춰 그립니다. */}
          <button type="button" className="btn btn-quiet notice-action" onClick={addNew}>
            새 전략
          </button>
        </div>
      )
    }
    if (shown.length === 0) {
      return (
        <div className="notice">
          <p className="notice-title">조건에 맞는 전략이 없습니다</p>
          <p className="notice-reason">저장된 전략은 {rows.length}개입니다</p>
          <button type="button" className="btn btn-quiet notice-action" onClick={resetFilters}>
            필터 초기화
          </button>
        </div>
      )
    }
    return (
      <div className="table-scroll">
        <table className="data-table rows-stacked stg-table">
          {/* 값 열은 폭을 못 박고 남는 폭은 전략 이름이 먹습니다 — 이름이
              길어져도 성과 칸이 밀리지 않습니다. */}
          <colgroup>
            <col className="stg-col-name" />
            <col className="stg-col-inst" />
            <col className="stg-col-status" />
            <col className="stg-col-pl" />
            <col className="stg-col-win" />
          </colgroup>
          <thead>
            <tr>
              <th scope="col" className="col-text">
                전략 · 버전
              </th>
              <th scope="col" className="col-text">
                시장 · 종목
              </th>
              <th scope="col" className="col-text">
                상태
              </th>
              <th scope="col">최근 순손익</th>
              <th scope="col">승률</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((row, index) => (
              <tr
                key={row.id}
                className="row-click"
                aria-selected={row.id === selectedId}
                onClick={() => onSelect(row.id)}
              >
                <td className={`col-text${isSub(index) ? ' stg-sub' : ''}`} title={nameText(row)}>
                  <span className={`stg-name${row.name.trim() ? '' : ' is-nameless'}`}>{nameText(row)}</span>
                  <span className="stg-version">{versionOnly(row.version)}</span>
                </td>
                <td className="col-text" title={instrumentNameOf(row)}>
                  <span className="stg-inst">{instrumentNameOf(row)}</span>
                  {/* 시장은 미결제 표의 시장 배지와 같은 꼴입니다 — 원·달러 금액이
                      한 표에 섞이므로 줄마다 어느 시장인지가 먼저 읽혀야 합니다. */}
                  <span className="badge stg-market-badge">{row.market === 'domestic' ? '국내' : '해외'}</span>
                </td>
                <td className="col-text stg-status">
                  <span className="badge">{row.status}</span>
                  {/* 그 버전이 지금 돌고 있는지 — 누르면 그 탭에서 그 실행을 엽니다. */}
                  {(() => {
                    const live = liveOf(row.id)
                    return (
                      <>
                        {live.paper > 0 && (
                          <button
                            type="button"
                            className="badge stg-run-badge"
                            onClick={(event) => {
                              event.stopPropagation()
                              onOpenRunsOf(row, 'verify')
                            }}
                          >
                            검증 중 {live.paper}
                          </button>
                        )}
                        {live.account > 0 && (
                          <button
                            type="button"
                            className={`badge stg-run-badge${live.real ? ' run-kind run-kind-real' : ''}`}
                            onClick={(event) => {
                              event.stopPropagation()
                              onOpenRunsOf(row, 'run')
                            }}
                          >
                            거래 중 {live.account}
                          </button>
                        )}
                        {/* 멈춘 실행 — 끝나지 않았지만 새 진입을 내지 않습니다. 정상 흐름이라
                            경고색이 아니라 기본 배지입니다. 누르면 멈춘 실행이 있는 탭을
                            엽니다(계좌 실행이 있으면 진행 탭). */}
                        {live.paused > 0 && (
                          <button
                            type="button"
                            className="badge stg-run-badge"
                            onClick={(event) => {
                              event.stopPropagation()
                              onOpenRunsOf(row, live.pausedAccount ? 'run' : 'verify')
                            }}
                          >
                            중지 {live.paused}
                          </button>
                        )}
                      </>
                    )
                  })()}
                </td>
                <RecentCells row={row} record={record} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
}
