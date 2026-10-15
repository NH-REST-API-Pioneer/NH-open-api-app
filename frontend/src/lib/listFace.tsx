/** 목록 한 벌이 아직 값이 아닐 때 그 자리에 서는 것.
 *
 *  **계좌 목록을 그리는 자리는 다 같은 얼굴을 씁니다.** 화면마다 따로 쓰면 같은
 *  사정이 화면마다 다른 말로 서고, 한쪽만 고쳐질 때 조용히 갈립니다.
 */
import type { ReactElement, ReactNode } from 'react'

import type { ListEntry } from '../data/account'

/** 값이 있으면 `null` 을 돌려줍니다 — 그때는 표를 그리는 쪽이 이어받습니다.
 *
 *  「0건」과 「못 받았음」이 같아 보이면 안 됩니다. 포지션이 있는데 못 받아 빈
 *  표를 보면 사용자는 자기가 아무것도 안 들고 있다고 믿고, 그 상태로 낸 주문은
 *  의도한 것의 두 배가 됩니다. **그래서 0건은 받은 뒤에만 섭니다.** */
export function listFace(
  entry: ListEntry<unknown>,
  empty: string,
  again: () => void,
  /** 빈 목록에도 「다시 받기」를 세울지. 머리 줄에 같은 단추가 있는 표(`ListHead`)만 켭니다. */
  reloadEmpty = false,
): ReactElement | null {
  if (entry.rows === null) {
    /* 인증 정보가 없어 안 부른 자리. 까닭은 그 화면의 머리가 한 번 말하고, 여기는
       짧은 표지만 답니다. */
    if (entry.withheld) {
      return (
        <div className="notice">
          <p className="notice-title">조회 전</p>
        </div>
      )
    }
    if (entry.status === 'failed') {
      return (
        <div className="notice">
          <p className="notice-title">가져오지 못했습니다</p>
          {entry.failure === 'rejected' ? (
            /* 계좌가 물음 자체를 물리친 자리입니다. 다시 눌러도 같은 답이라
               단추를 안 세웁니다 — 세우면 같은 자리를 반복하게 됩니다. */
            <p className="notice-reason">계좌가 이 조회를 받지 않았습니다</p>
          ) : (
            <>
              <p className="notice-reason">잠시 뒤 다시 시도해 주세요</p>
              <button type="button" className="btn btn-primary notice-action" onClick={again}>
                다시 시도
              </button>
            </>
          )}
        </div>
      )
    }
    /* 아직 답이 없는 자리. 부르기 직전의 한 틱도 여기입니다 — 이미 부르기로
       정해진 자리라 「조회 전」이 아니라 「불러오는 중」입니다. */
    return (
      <div className="notice">
        <p className="notice-title">불러오는 중</p>
      </div>
    )
  }
  if (entry.rows.length === 0) {
    /* 빈 목록도 다시 받을 수 있습니다 — 다른 창에서 낸 주문이 아직 안 보일 때
       이 자리에서 새로 받습니다. 받는 중에는 잠급니다. */
    const busy = entry.status === 'loading' || entry.refreshing === true
    return (
      <div className="notice">
        <p className="notice-title">{empty}</p>
        {reloadEmpty && (
          <button
            type="button"
            className="btn btn-quiet notice-action"
            aria-disabled={busy || undefined}
            onClick={() => {
              if (!busy) again()
            }}
          >
            {busy ? '받는 중' : '다시 받기'}
          </button>
        )}
      </div>
    )
  }
  return null
}

/** 값은 이미 있는데 다시 받기가 안 된 자리. **값을 지우지 않습니다** — 지우면
 *  화면을 한 번 다녀왔다는 이유로 들고 있던 것이 사라집니다. 대신 지금 보는
 *  것이 마지막으로 받은 값이라고 한 줄로 답니다.
 *
 *  `again` 은 머리 줄(`ListHead`)에 「다시 받기」가 없는 자리만 넘깁니다 — 머리 줄에
 *  늘 서 있는 자리에서 여기에도 세우면 같은 단추가 두 번 섭니다. */
export function staleNote(entry: ListEntry<unknown>, again?: () => void): ReactElement | null {
  if (entry.rows === null || entry.failure === null) return null
  return (
    <p className="list-stale">
      아래는 마지막으로 받은 값입니다. 다시 받지 못했습니다
      {again && entry.failure === 'retry' && (
        <button type="button" className="btn btn-quiet" onClick={again}>
          다시 받기
        </button>
      )}
    </p>
  )
}

/** 표 머리 줄 — 왼쪽은 **무엇의 값인지**, 오른쪽 끝은 **몇 줄을 받았고 더
 *  받고 있는지**입니다.
 *
 *  「이게 전부인가」는 줄을 읽기 **전에** 생기는 물음이라 표 위에 둡니다.
 *
 *  - 받는 중: 「N줄 · 더 받는 중」 곁에 「멈추기」. 전체 쪽 수를 모르므로
 *    분모를 적지 않습니다 — 모르는 수를 지어내느니 받은 수만 셉니다.
 *  - 다 받음: 「N줄」 뿐입니다. 더 받을 것이 없다는 것은 단추가 없는 것으로
 *    이미 말하므로, 정상에 문장을 더 세우지 않습니다.
 *  - 멈춤: 「N줄 · 더 있을 수 있습니다」 곁에 「더 받기」. 마지막 쪽이었는지는
 *    그 순간에 알 수 없어 「덜 받았다」고 하지 않습니다.
 *  - 새로 받는 중: 「N줄 · 받는 중」. 받아 둔 줄은 그대로 둡니다.
 *
 *  맨 오른쪽에는 「다시 받기」가 **늘** 섭니다(`onReload` 를 준 자리). 저절로
 *  되풀이해 부르지 않으므로, 다른 창에서 낸 주문을 바로 보고 싶을 때 누르는
 *  자리입니다. 받는 중(첫 쪽·이어 받기·새로 받기)에는 잠깁니다. */
export function ListHead({
  label,
  entry,
  onStop,
  onMore,
  onReload,
  state,
}: {
  label: string
  entry: ListEntry<unknown>
  onStop: () => void
  onMore: () => void
  onReload?: () => void
  /** 오른쪽 끝에 이어 받기 대신 세울 말. 쓰는 자리만의 받는 사정이 있을 때입니다. */
  state?: ReactNode
}): ReactElement {
  const count = `${(entry.rows?.length ?? 0).toLocaleString('ko-KR')}줄`
  const busy = entry.status === 'loading' || entry.filling || entry.refreshing === true
  /* 「멈추기」·「더 받기」가 서 있으면 그 단추와 「다시 받기」 사이를 가는 선으로
     가릅니다 — 붙어 있으면 둘이 한 동작처럼 읽힙니다. */
  const paired = state === undefined && (entry.filling || (entry.capped && entry.nextKey !== null))
  return (
    <div className="list-head">
      <span className="list-head-label">{label}</span>
      <span className="list-head-state">
        {state !== undefined ? (
          state
        ) : entry.filling ? (
          <>
            {count} · 더 받는 중
            <button type="button" className="btn btn-quiet" onClick={onStop}>
              멈추기
            </button>
          </>
        ) : entry.capped && entry.nextKey !== null ? (
          <>
            {count} · 더 있을 수 있습니다
            <button type="button" className="btn btn-quiet" onClick={onMore}>
              더 받기
            </button>
          </>
        ) : entry.refreshing ? (
          `${count} · 받는 중`
        ) : (
          count
        )}
        {onReload && (
          <>
            {paired && <span className="list-head-rule" aria-hidden="true" />}
            <button
              type="button"
              className="btn btn-quiet"
              aria-disabled={busy || undefined}
              onClick={() => {
                if (!busy) onReload()
              }}
            >
              다시 받기
            </button>
          </>
        )}
      </span>
    </div>
  )
}
