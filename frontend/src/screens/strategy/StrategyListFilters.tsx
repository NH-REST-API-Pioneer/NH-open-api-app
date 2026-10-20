import { MARKETS, STATUSES, RECORDS } from './strategyListParts'
import type { Dispatch, SetStateAction } from 'react'

/* 필터 칸 한 벌. 넓은 폭의 필터 열과 좁은 폭의 필터 상자가 **같은 칸**을
   세웁니다 — 따로 적으면 한쪽에만 칸이 늘거나 차례가 갈립니다. `first` 는
   상자를 열 때 초점을 줄 첫 칸입니다. */
export function renderFilterFields(
  {
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
  }: {
    query: string
    setQuery: Dispatch<SetStateAction<string>>
    market: (typeof MARKETS)[number]
    setMarket: Dispatch<SetStateAction<(typeof MARKETS)[number]>>
    status: (typeof STATUSES)[number]
    setStatus: Dispatch<SetStateAction<(typeof STATUSES)[number]>>
    record: (typeof RECORDS)[number]
    setRecord: Dispatch<SetStateAction<(typeof RECORDS)[number]>>
    runningOnly: boolean
    setRunningOnly: Dispatch<SetStateAction<boolean>>
    resetFilters: () => void
  },
  first?: React.Ref<HTMLInputElement>,
) {
    return (
      <>
        <label className="stg-field">
          <span className="stg-field-label">전략명 검색</span>
          <input
            ref={first}
            className="control stg-text"
            type="search"
            value={query}
            placeholder="전략명"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>

        <label className="stg-field">
          <span className="stg-field-label">시장</span>
          <select className="control" value={market} onChange={(e) => setMarket(e.target.value as typeof market)}>
            {MARKETS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>

        <label className="stg-field">
          <span className="stg-field-label">상태</span>
          <select className="control" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
            {STATUSES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>

        <label className="stg-field">
          <span className="stg-field-label">기록 유형</span>
          <select className="control" value={record} onChange={(e) => setRecord(e.target.value as typeof record)}>
            {RECORDS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>

        <label className="stg-check">
          <input
            type="checkbox"
            checked={runningOnly}
            onChange={(event) => setRunningOnly(event.target.checked)}
          />
          실행 중만 보기
        </label>

        <button type="button" className="btn btn-quiet stg-reset" onClick={resetFilters}>
          초기화
        </button>
      </>
    )
}
