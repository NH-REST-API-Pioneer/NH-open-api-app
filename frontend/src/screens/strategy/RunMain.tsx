import { watchLine } from '../../data/ruleSummary'
import { savedOf, useStrategyState } from '../../data/strategyStore'
import {
  CONFIRM_TEXT,
  isRejectedEvent,
  reasonWord,
  tickBarOf,
  streakText,
  type VerifyRun,
} from '../../data/strategyRuns'
import { TickBadge } from './TickBadge'
import { Num, NumOrDash, moneyIn, toneOf } from '../../lib/number'
import { Modal } from '../../app/Modal'
import { RUN_KIND_LABEL } from './runKind'
import { runNameOf } from './runStats'
import { ConditionTable } from './ConditionTable'
import { BOTTOM_TABS, type BottomTab, type Confirm, clockOf, shortInstrument } from './strategyRunUtils'
import type { Dispatch, SetStateAction } from 'react'
import type { useRunView } from './useRunView'
import type { useTableWidth } from './useRunTable'
import type { useRunTables } from './useRunTable'
import type { makeRunActions } from './runActions'

type ViewValues = ReturnType<typeof useRunView>
type WidthValues = ReturnType<typeof useTableWidth>
type TableValues = ReturnType<typeof useRunTables>
type ActionValues = ReturnType<typeof makeRunActions>
type StoreState = ReturnType<typeof useStrategyState>

type RunTitleArgs = Pick<ViewValues, 'shown'> &
  {
    nameOf: (versionId: string) => ReturnType<typeof runNameOf>
  }

/** 보는 실행의 이름 줄. */
export function renderRunTitle({
  shown,
  nameOf,
}: RunTitleArgs) {
  return (
          shown && (
            <p className="vrf-title">
              <span className="vrf-title-name">{nameOf(shown.version).name || '—'}</span>
              <span className="vrf-title-sub">
                {' · '}
                {[nameOf(shown.version).version, shortInstrument(shown.code), shown.sessionLabel]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
            </p>
          )
  )
}

type RunBarArgs = Pick<ViewValues, 'shown'> &
  {
    decimals: number
    runCurrency: (run: VerifyRun) => string
    watch: NonNullable<ReturnType<typeof savedOf>>['aux'] | null | undefined
  }

/** 실행 막대 — 보유, 평균가, 평가손익, 청산 감시. */
export function renderRunBar({
  shown,
  decimals,
  runCurrency,
  watch,
}: RunBarArgs) {
  return (
          <div className="run-bar">
            <span className="run-bar-item">
              보유{' '}
              <b>
                {shown && (shown.position ?? 0) > 0
                  ? `${shown.side === 'buy' ? '매수' : '매도'} ${shown.position}계약`
                  : shown && shown.position === null
                    ? '—'
                    : '없음'}
              </b>
            </span>
            <span className="run-bar-item">
              평균가{' '}
              <b>
                {shown && shown.avgPrice !== null ? (
                  <Num value={shown.avgPrice} decimals={decimals} />
                ) : (
                  '—'
                )}
              </b>
            </span>
            <span className="run-bar-item">
              {/* 실행이 없으면 **값도 없습니다**. 0 으로 적으면 「본전」이 되는데
                  본전은 들고 있는 것이 있을 때 하는 말입니다(평균가와 같은 얼굴). */}
              평가손익{' '}
              <b className={shown ? toneOf(shown.pl ?? 0) || undefined : undefined}>
                {/* 실행의 통화로 적습니다 — 해외 실행은 품목 통화입니다. */}
                {shown ? `${(shown.pl ?? 0) > 0 ? '+' : ''}${moneyIn(shown.pl, runCurrency(shown))}` : '—'}
              </b>
            </span>
            {/* 서버가 받은 STOP 과 앱이 보고 있는 손절은 다릅니다 — 앱이 꺼지면
                뒤엣것은 멈춥니다. 그래서 「앱 감시」를 함께 적습니다. */}
            <span className="run-bar-item run-watch">
              <b>{watchLine(watch)}</b> · 앱 감시
              {/* 이어진 손실과 그 한도. 규칙대로 도는 중이라 중립 글자입니다. */}
              {streakText(shown, watch?.lossStreak) && ` · ${streakText(shown, watch?.lossStreak)}`}
            </span>
          </div>
  )
}

type RunAttentionArgs = Pick<ViewValues, 'shown'> &
  Pick<ActionValues, 'acknowledge'> &
  {
    acting: StoreState['verify']['acting']
    why: { head?: string; side?: string; ack?: string }
  }

/** 「확인 필요」 안내 띠와 확인 단추. */
export function renderRunAttention({
  shown,
  acting,
  why,
  acknowledge,
}: RunAttentionArgs) {
  return (
          shown?.state === 'attention' && (
            <div className="run-attention">
              <span>
                계좌와 앱 장부가 어긋나 멈춰 있습니다. 확인해야 다시 움직입니다. 이 실행에 남은 보유·주문이
                없으면 「실행 종료」로 끝낼 수 있습니다.
              </span>
              <button
                type="button"
                className="btn btn-quiet"
                aria-disabled={acting === shown.id}
                aria-describedby={why.ack ? 'run-ack-why' : undefined}
                onClick={() => acting !== shown.id && void acknowledge(shown.id)}
              >
                확인
              </button>
            </div>
          )
  )
}

type RunBottomArgs = Pick<ViewValues, 'snapshot' | 'tickRun' | 'narrow'> &
  Pick<WidthValues, 'tableBoxRef'> &
  Pick<TableValues, 'events' | 'tableRows'> &
  {
    bottom: BottomTab
    setBottom: Dispatch<SetStateAction<BottomTab>>
    decimals: number
  }

/** 아래 표 — 최근 체결, 미체결, 이벤트, 조건. */
export function renderRunBottom({
  bottom,
  setBottom,
  tableBoxRef,
  snapshot,
  decimals,
  tickRun,
  events,
  narrow,
  tableRows,
}: RunBottomArgs) {
  return (
          <div className="run-bottom">
            <div className="tabs tabs-inline run-bottom-tabs">
              {BOTTOM_TABS.map((item) => (
                <button
                  key={item}
                  type="button"
                  className="tab"
                  aria-current={item === bottom}
                  onClick={() => setBottom(item)}
                >
                  {item}
                </button>
              ))}
            </div>

            <div className="table-scroll run-table" ref={tableBoxRef}>
              {bottom === '조건' ? (
                <ConditionTable conditions={snapshot?.conditions} decimals={decimals} tick={tickRun} />
              ) : bottom === '이벤트' ? (
                <table className="data-table rows-base">
                  <colgroup>
                    <col className={`run-col-time${tickRun ? ' is-tick' : ''}`} />
                    <col />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col" className="col-text">
                        시각
                      </th>
                      <th scope="col" className="col-text">
                        내용
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((item) => {
                      const tick = tickBarOf({ kind: 'event', event: item })
                      return (
                        <tr key={`${item.time}-${item.kind}-${item.text}`}>
                          <td className="col-text">
                            {clockOf(item.time)}
                            {tick !== undefined && <TickBadge barTime={tick} />}
                          </td>
                          <td className="col-text">
                            {/* 계좌가 주문을 거부한 줄은 검증 탭과 같은 「거부」 배지를 앞에
                                답니다. 글은 서버가 준 거부 코드와 문구 그대로입니다. */}
                            {isRejectedEvent(item) && (
                              <span className="badge vrf-event-badge vrf-event-badge-rejected">거부</span>
                            )}
                            {item.text}
                          </td>
                        </tr>
                      )
                    })}
                    {/* 머리만 있는 빈 표는 「고장」과 구별되지 않습니다. */}
                    {events.length === 0 && (
                      <tr>
                        <td className="run-empty-row" colSpan={2}>
                          아직 남은 이벤트가 없습니다
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              ) : (
                <table className="data-table rows-base">
                  <colgroup>
                    <col className={`run-col-time${tickRun ? ' is-tick' : ''}`} />
                    {!narrow && <col className="run-col-no" />}
                    <col className="run-col-side" />
                    {/* 용도가 남는 폭을 가져갑니다 — 까닭까지 적는 칸이라
                        못 박으면 「청산 · 손절」의 까닭이 잘립니다. */}
                    <col />
                    <col className="run-col-state" />
                    <col className="run-col-price" />
                    <col className="run-col-qty" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col" className="col-text">
                        시각
                      </th>
                      {!narrow && (
                        <th scope="col" className="col-text">
                          주문번호
                        </th>
                      )}
                      <th scope="col" className="col-text">
                        구분
                      </th>
                      <th scope="col" className="col-text">
                        용도
                      </th>
                      <th scope="col" className="col-text">
                        상태
                      </th>
                      <th scope="col">가격</th>
                      <th scope="col">{bottom === '미체결' ? '미체결' : '수량'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableRows.map((one) => (
                      <tr key={one.key}>
                        {/* 주문번호 열을 접은 폭에서는 번호가 시각 칸에 마우스를
                            올렸을 때 보입니다(`ORDER_NO_FITS`). */}
                        <td
                          className="col-text"
                          title={narrow && one.orderNo ? `주문번호 ${one.orderNo}` : undefined}
                        >
                          {clockOf(one.time)}
                          {one.tick !== undefined && <TickBadge barTime={one.tick} />}
                        </td>
                        {/* 값이 아니라 주문내역에서 찾아 맞출 때 쓰는 열쇠라 한 급
                            낮게 적습니다. */}
                        {!narrow && <td className="col-text run-no">{one.orderNo ?? '—'}</td>}
                        <td className={`col-text ${one.side === 'buy' ? 'up' : 'down'}`}>
                          {one.side === 'buy' ? '매수' : '매도'}
                        </td>
                        <td className="col-text">
                          {one.intent === 'entry' ? '진입' : '청산'}
                          {reasonWord(one.reason) && ` · ${reasonWord(one.reason)}`}
                        </td>
                        <td className="col-text">{one.state}</td>
                        {/* 시장가에는 가격이 없습니다 — 0 을 적으면 「0원에
                            걸었다」로 읽히므로 「—」를 세웁니다. */}
                        <td>
                          <NumOrDash value={one.price} decimals={decimals} />
                        </td>
                        {/* 체결은 채워진 수량, 미체결은 **남은 수량**입니다 —
                            낸 수량을 적으면 부분체결이 안 줄어든 것처럼 보입니다.
                            어느 쪽인지는 위에서 탭이 정합니다. */}
                        <td>{one.amount}</td>
                      </tr>
                    ))}
                    {tableRows.length === 0 && (
                      <tr>
                        <td className="run-empty-row" colSpan={narrow ? 6 : 7}>
                          {bottom === '미체결' ? '남은 주문이 없습니다' : '아직 체결이 없습니다'}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              )}
            </div>
          </div>
  )
}

type RunConfirmArgs = Pick<ActionValues, 'skipWhy' | 'blocks' | 'apply'> &
  {
    confirm: Confirm
    setConfirm: Dispatch<SetStateAction<Confirm>>
    nameOf: (versionId: string) => ReturnType<typeof runNameOf>
  }

/** 고른 실행에 거는 동작의 확인 창. */
export function renderRunConfirm({
  confirm,
  skipWhy,
  blocks,
  setConfirm,
  nameOf,
  apply,
}: RunConfirmArgs) {
  return (
      confirm && (() => {
        /* 요청이 실제로 나가는 줄과 빠지는 줄. 창의 셈·목록·단추가 모두 이
           갈래를 씁니다. */
        const applied = confirm.runs.filter((run) => skipWhy(confirm.action, run) === null)
        const excluded = confirm.runs.filter((run) => skipWhy(confirm.action, run) !== null)
        const stopped = confirm.alreadyStopped ?? 0
        /* 나갈 줄이 없을 때 단추 곁에 세우는 까닭. 빠진 까닭이 하나면 그 말이고,
           갈리면 갈린 말들을 잇습니다 — 줄마다의 까닭은 목록에 이미 있습니다.
           중지·청산에서 빠진 줄이 모두 「확인 필요」·「대사 중」이면 그 둘을 한
           말로 묶습니다. 목록 자체가 비었으면 빠진 까닭이 아니라 대상이 없다고
           적습니다. */
        const noneWhy =
          confirm.runs.length === 0
            ? '대상 실행이 없습니다'
            : confirm.action !== '실행 종료' && excluded.every(blocks)
              ? '대상 실행이 모두 확인 필요 상태입니다'
              : [...new Set(excluded.map((run) => skipWhy(confirm.action, run) as string))].join(' · ')
        return (
        <Modal
          label={confirm.action}
          dismissable={false}
          onClose={() => setConfirm(null)}
          head={<span className="modal-title">{confirm.action}</span>}
        >
          <dl className="run-confirm">
            <div className="run-confirm-row">
              <dt>진입 주문</dt>
              <dd>{CONFIRM_TEXT[confirm.action].order}</dd>
            </div>
            <div className="run-confirm-row">
              <dt>보유분</dt>
              <dd>{CONFIRM_TEXT[confirm.action].holding}</dd>
            </div>
          </dl>

          {/* 「나열한 계좌·실행 범위에 적용」이라 적어 놓고 나열하지 않으면 그
              문장이 거짓이 됩니다 — 반대로 **나열해 놓고 안 나가는 것**이 섞여
              있어도 거짓입니다. 그래서 세는 것은 **요청이 실제로 나가는 건수**
              이고, 빠지는 줄은 목록에 두되 왜 빠지는지를 그 줄에 답니다.
              「확인 필요」는 사용자가 손을 써야 넘어가는 상태라 이 요청이
              건드리지 않습니다. */}
          {/* 괄호는 둘입니다 — **목록에 선 것 중 안 나가는 수**(제외)와 **이미
              중지되어 목록에 서지도 않은 수**. 둘 다 0 이면 적지 않고, 뒤엣것은
              「전체」에서만 생깁니다.
              뒤엣것에는 「목록에 없음」을 붙입니다. 수와 목록 줄 수가 어긋나는
              까닭을 창이 말하지 않으면, 목록의 어느 줄이 이미 중지된 것인지
              찾게 됩니다. 한 괄호에 둘을 이어 적으면 「목록에 없음」이 목록에
              선 제외 줄까지 걸려 읽혀, 괄호를 나눕니다.
              「전체」에서 끝난 실행은 어느 쪽에도 안 셉니다. 이 요청이 하려는
              일이 이미 끝난 것이라, 「안 나갔다」고 알릴 것이 없습니다. 골라서
              연 창에서는 고른 줄이 목록에 서므로 끝난 실행도 제외로 셉니다. */}
          <p className="run-confirm-title">
            적용 범위 {applied.length}건
            {excluded.length > 0 && ` (제외 ${excluded.length}건)`}
            {stopped > 0 && ` (이미 중지 ${stopped}건 — 목록에 없음)`}
          </p>
          <ul className="run-confirm-list">
            {confirm.runs.map((run) => {
              const skip = skipWhy(confirm.action, run)
              const said = nameOf(run.version)
              return (
                <li key={run.id} className={skip !== null ? 'run-confirm-skip' : undefined}>
                  {RUN_KIND_LABEL[run.mode]} · {said.name} {said.version} · {shortInstrument(run.code)}
                  {skip !== null && (
                    <span className="run-confirm-skip-why">
                      {' '}
                      · {skip}
                    </span>
                  )}
                </li>
              )
            })}
          </ul>
          {/* 종료는 취소도 청산도 내지 않습니다 — 그 창에서 이 안내는 틀린 말입니다. */}
          {confirm.action !== '실행 종료' && (
            <p className="run-hint">
              취소 요청은 취소 완료가 아니고 청산 요청은 체결 완료가 아닙니다 — 처리 결과를 확인해야 합니다
            </p>
          )}

          <p className="run-confirm-why" id="run-confirm-why">
            {/* 「고른」이라 하지 않습니다 — 「전체 신규 진입 중지」에는 고르는
                절차가 없고, 세 동작이 이 창 하나를 같이 씁니다. */}
            {applied.length === 0 ? noneWhy : ''}
          </p>

          <div className="run-confirm-acts">
            <button type="button" className="btn btn-quiet" onClick={() => setConfirm(null)}>
              그만두기
            </button>
            {/* 나갈 요청이 하나도 없으면 누를 것이 없습니다 — 눌러서 아무 일도
                안 나는 단추를 두지 않습니다. */}
            <button
              type="button"
              className="btn btn-heavy"
              aria-disabled={applied.length === 0}
              aria-describedby={applied.length === 0 ? 'run-confirm-why' : undefined}
              onClick={() => applied.length > 0 && apply(confirm.action, confirm.runs)}
            >
              {confirm.action}
            </button>
          </div>
        </Modal>
        )
      })()
  )
}
