import { CONFIRM_TEXT, isTickRun, tickBarOf, reasonWord, streakText } from '../../data/strategyRuns'
import { savedOf, useStrategyState } from '../../data/strategyStore'
import { TickBadge } from './TickBadge'
import { Num, NumOrDash, moneyIn, toneOf } from '../../lib/number'
import { Modal } from '../../app/Modal'
import { ChartPanel } from '../trade/ChartPanel'
import { MarkPopover, type MarkPick } from './MarkPopover'
import { ConditionTable } from './ConditionTable'
import { RUN_KIND_LABEL } from './runKind'
import type { SlotState } from '../trade/chartSlots'
import {
  BOTTOM_TABS,
  type BottomTab,
  DEED_LABEL,
  type Deed,
  EventText,
  FEED_LABEL,
  FEED_TONE,
  clockOf,
  runSessionLabel,
  shortInstrument,
} from './strategyVerifyUtils'
import type { Dispatch, SetStateAction } from 'react'
import type { useVerifyRun } from './useVerifyRun'
import type { useVerifyChart } from './useVerifyChart'
import type { useVerifyTables } from './useVerifyTables'
import type { makeVerifyActions } from './verifyActions'

type RunValues = ReturnType<typeof useVerifyRun>
type ChartValues = ReturnType<typeof useVerifyChart>
type TableValues = ReturnType<typeof useVerifyTables>
type ActionValues = ReturnType<typeof makeVerifyActions>
type StoreState = ReturnType<typeof useStrategyState>

type VerifyHeadArgs = Pick<
    RunValues,
    'picked' | 'standing' | 'running' | 'stopped' | 'ended' | 'tradingLink' | 'full'
    | 'fullWhy' | 'openAdd'
  > &
  {
    max: number
    status: StoreState['verify']['status']
    failure: string | null
    why: string | null
    whyWarn: boolean
  }

/** 검증 머리 — 시세 구독, 실행 수, 막힌 까닭과 「검증 추가」 단추. */
export function renderVerifyHead({
  picked,
  standing,
  max,
  running,
  stopped,
  ended,
  tradingLink,
  status,
  failure,
  why,
  whyWarn,
  full,
  fullWhy,
  openAdd,
}: VerifyHeadArgs) {
  return (
      <div className="card vrf-head">
        <div className="vrf-head-left">
          {/* **화면 전체의 구독**을 말하는 자리라 그 범위를 낱말로 밝힙니다 —
              줄의 「시세 …」는 그 실행 하나의 것입니다. */}
          <span className="vrf-feed">
            <span className={FEED_TONE[picked?.feed ?? 'idle']} />
            시세 구독 — {FEED_LABEL[picked?.feed ?? 'idle']}
          </span>
          {/* 「동시 실행 n / 상한」 — n 은 **상한을 먹는 실행**(끝나지 않은 것, 중지 포함)을
              진행 탭의 것까지 센 수이고 상한은 서버 값입니다. 「이 탭」과 중지·종료는
              이 탭의 종이 실행만 셉니다. 끝난 실행은 상한을 안 먹어 따로 셉니다.
              진행 탭에 계좌 실행이 돌면 그 수와 그리로 가는 길을 바로 뒤에 답니다. */}
          <span className="vrf-counts-line">
            <span className="vrf-counts">
              동시 실행 {standing}
              {max > 0 && ` / ${max}`}
              {` · 이 탭 ${running + stopped} · 중지 ${stopped} · 종료 ${ended}`}
            </span>
            {tradingLink}
          </span>
          {/* 못 한 일은 **한 자리에 한 줄**입니다. 차트 위에 따로 띠를 두면
              그만큼 차트가 낮아지는데, 이 화면의 세로는 차트와 아래 표가
              다투는 자리입니다. */}
          {status === 'failed' && (
            <span className="vrf-pending" title={failure ?? undefined}>
              {failure}
            </span>
          )}
          {why !== null && (
            <span className={whyWarn ? 'vrf-pending is-warn' : 'vrf-pending'} title={why}>
              {why}
            </span>
          )}
        </div>
        {/* 그냥 누르면 목록에서 고른 전략으로 채워 엽니다. 목록에서 들고 온
            경우에는 그 전략·버전이 이미 담겨 있습니다. */}
        {/* 동시 실행이 상한이면 잠그고 까닭을 `title` 에 둡니다. */}
        <button
          type="button"
          className="btn btn-primary"
          aria-disabled={full}
          title={full ? fullWhy : undefined}
          onClick={openAdd}
        >
          검증 추가
        </button>
      </div>
  )
}

type MainTitleArgs = Pick<RunValues, 'picked'> &
  Pick<ChartValues, 'nameOf'>

/** 지금 보는 실행의 이름 줄. */
export function renderMainTitle({
  picked,
  nameOf,
}: MainTitleArgs) {
  return (
          picked && (
            <p className="vrf-title">
              <span className="vrf-title-name">{nameOf(picked.version).name || '—'}</span>
              <span className="vrf-title-sub">
                {' · '}
                {[nameOf(picked.version).version, shortInstrument(picked.code), runSessionLabel(picked)]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
            </p>
          )
  )
}

type MainBarArgs = Pick<RunValues, 'picked'> &
  Pick<ChartValues, 'decimals' | 'currency'> &
  {
    showDetail: boolean
    setShowDetail: (on: boolean) => void
  }

/** 실행 막대 — 세션, 가상 보유, 평균가, 평가손익과 표시 선택. */
export function renderMainBar({
  picked,
  decimals,
  currency,
  showDetail,
  setShowDetail,
}: MainBarArgs) {
  return (
          <div className="vrf-bar">
            {/* 이 실행이 붙은 세션. 같은 전략을 두 세션으로 돌릴 때 지금 보는 것이
                어느 쪽인지 여기서 읽힙니다. */}
            <span className="vrf-bar-item">
              세션 <b>{picked ? runSessionLabel(picked) : '—'}</b>
            </span>
            <span className="vrf-bar-item">
              가상 보유{' '}
              <b>
                {picked && (picked.position ?? 0) > 0
                  ? `${picked.side === 'buy' ? '매수' : '매도'} ${picked.position}계약`
                  : picked && picked.position === null
                    ? '—'
                    : '없음'}
              </b>
            </span>
            <span className="vrf-bar-item">
              평균가{' '}
              <b>
                {picked && picked.avgPrice !== null ? (
                  <Num value={picked.avgPrice} decimals={decimals} />
                ) : (
                  '—'
                )}
              </b>
            </span>
            <span className="vrf-bar-item">
              {/* 실행이 없으면 값도 없습니다 — 0 은 「본전」이고, 본전은 들고
                  있는 것이 있을 때 하는 말입니다. */}
              평가손익{' '}
              <b className={picked ? toneOf(picked.pl ?? 0) || undefined : undefined}>
                {picked ? `${(picked.pl ?? 0) > 0 && currency ? '+' : ''}${moneyIn(picked.pl, currency)}` : '—'}
              </b>
            </span>
            {/* 이어진 손실과 그 한도(진행 띠와 같은 글자). 한도를 정했고 1 이상일
                때만 섭니다. */}
            {streakText(picked, picked ? savedOf(picked.version)?.aux.lossStreak : undefined) && (
              <span className="vrf-bar-item">
                {streakText(picked, picked ? savedOf(picked.version)?.aux.lossStreak : undefined)}
              </span>
            )}
            {/* 체결만 기본으로 켜 두고, 신호·주문은 여기서 켭니다. */}
            <label className="vrf-check">
              <input
                type="checkbox"
                checked={showDetail}
                onChange={(event) => setShowDetail(event.target.checked)}
              />
              신호 · 주문도 표시
            </label>
          </div>
  )
}

type MainChartArgs = Pick<RunValues, 'picked'> &
  Pick<ChartValues, 'quote' | 'indicatorLayer'> &
  Pick<TableValues, 'marks'> &
  {
    slot: SlotState
    setSlot: Dispatch<SetStateAction<SlotState>>
    setMarkPick: Dispatch<SetStateAction<MarkPick | null>>
    markPick: MarkPick | null
  }

/** 고른 실행의 차트와 체결 표시 상세. */
export function renderMainChart({
  picked,
  quote,
  slot,
  setSlot,
  marks,
  setMarkPick,
  indicatorLayer,
  markPick,
}: MainChartArgs) {
  return (
          <div className="vrf-chart">
            {picked && (
            <ChartPanel
              quotes={[quote, null]}
              slots={[slot, { instrument: null, span: 'minute', indicators: null }]}
              onSlotChange={(_, patch) => setSlot({ ...slot, ...patch })}
              expanded={false}
              onExpandedChange={() => {}}
              split={false}
              onSplitChange={() => {}}
              active={0}
              onActiveChange={() => {}}
              tradeMarks={marks}
              onMarkPick={(mark, at) => setMarkPick({ mark, ...at })}
              indicatorLayer={indicatorLayer}
            />
            )}
            {markPick && <MarkPopover pick={markPick} onClose={() => setMarkPick(null)} />}
          </div>
  )
}

type MainBottomArgs = Pick<RunValues, 'snapshot' | 'picked'> &
  Pick<ChartValues, 'decimals' | 'pickedRow'> &
  Pick<TableValues, 'eventBoxRef' | 'events' | 'tableRows'> &
  {
    bottom: BottomTab
    setBottom: Dispatch<SetStateAction<BottomTab>>
  }

/** 아래 표 — 조건, 체결, 미체결, 이벤트. */
export function renderMainBottom({
  bottom,
  setBottom,
  eventBoxRef,
  snapshot,
  decimals,
  pickedRow,
  picked,
  events,
  tableRows,
}: MainBottomArgs) {
  return (
          <div className="vrf-bottom">
            <div className="tabs tabs-inline vrf-bottom-tabs">
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

            <div className="table-scroll vrf-table" ref={eventBoxRef}>
              {bottom === '조건' ? (
                <ConditionTable
                  conditions={snapshot?.conditions}
                  decimals={decimals}
                  tick={pickedRow ? savedOf(pickedRow.id)?.evalMode === '틱' : false}
                />
              ) : bottom === '이벤트' ? (
                <table className="data-table rows-base">
                  <colgroup>
                    <col className={`vrf-col-time${isTickRun(picked) ? ' is-tick' : ''}`} />
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
                    {events.map((item, index) => {
                      const tick = tickBarOf({ kind: 'event', event: item })
                      return (
                        <tr key={`${item.time}-${index}`}>
                          <td className="col-text">
                            {clockOf(item.time)}
                            {tick !== undefined && <TickBadge barTime={tick} />}
                          </td>
                          <td className="col-text">
                            <EventText kind={item.kind} reason={item.reason} text={item.text} />
                          </td>
                        </tr>
                      )
                    })}
                    {/* 머리만 있는 빈 표는 「고장」과 구별되지 않습니다. */}
                    {events.length === 0 && (
                      <tr>
                        <td className="vrf-empty-row" colSpan={2}>
                          아직 남은 이벤트가 없습니다
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              ) : (
                <table className="data-table rows-base">
                  <colgroup>
                    <col className={`vrf-col-time${isTickRun(picked) ? ' is-tick' : ''}`} />
                    <col className="vrf-col-side" />
                    {/* 용도가 남는 폭을 가져갑니다 — 까닭까지 적는 칸이라
                        못 박으면 「청산 · 손절」의 까닭이 잘립니다. */}
                    <col />
                    <col className="vrf-col-price" />
                    <col className="vrf-col-qty" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col" className="col-text">
                        시각
                      </th>
                      <th scope="col" className="col-text">
                        구분
                      </th>
                      <th scope="col" className="col-text">
                        용도
                      </th>
                      <th scope="col">가격</th>
                      <th scope="col">{bottom === '미체결' ? '미체결' : '수량'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableRows.map((one) => (
                      <tr key={one.key}>
                        <td className="col-text">
                          {clockOf(one.time)}
                          {one.tick !== undefined && <TickBadge barTime={one.tick} />}
                        </td>
                        {/* 표의 매수·매도는 방향값이라 색을 씁니다 — 문장 속
                            낱말이 아니라 값이 서는 칸입니다. */}
                        <td className={`col-text ${one.side === 'buy' ? 'up' : 'down'}`}>
                          {one.side === 'buy' ? '매수' : '매도'}
                        </td>
                        <td className="col-text">
                          {one.intent === 'entry' ? '진입' : '청산'}
                          {reasonWord(one.reason) && ` · ${reasonWord(one.reason)}`}
                        </td>
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
                        <td className="vrf-empty-row" colSpan={5}>
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

type DeedConfirmArgs = Pick<RunValues, 'running'> &
  Pick<ChartValues, 'nameOf'> &
  Pick<ActionValues, 'chosen' | 'skipWhy' | 'commit'> &
  {
    deed: Deed | null
    setDeed: Dispatch<SetStateAction<Deed | null>>
  }

/** 고른 실행에 거는 동작의 확인 창. */
export function renderDeedConfirm({
  deed,
  chosen,
  skipWhy,
  running,
  setDeed,
  nameOf,
  commit,
}: DeedConfirmArgs) {
  return (
      deed !== null && (() => {
        /* 창의 두 줄. 중지는 진행 화면의 「신규 진입 중지」와 같은 일이라 그
           설명을 씁니다. 재개는 막는 것을 푸는 일이라 설명할 되돌릴 수 없는
           결과가 없어 두 줄을 안 세웁니다. */
        const text =
          deed === '선택 검증 중지'
            ? CONFIRM_TEXT['신규 진입 중지']
            : deed === '선택 검증 재개'
              ? null
              : CONFIRM_TEXT[deed]
        /* 요청이 실제로 나가는 줄과 빠지는 줄. 창의 셈·목록·단추가 모두 이
           갈래를 씁니다(진행 화면의 창과 같은 꼴). */
        const everyone = deed === '검증 신규 진입 중지'
        const applied = chosen.filter((run) => skipWhy(deed, run) === null)
        const excluded = chosen.filter((run) => skipWhy(deed, run) !== null)
        /* 창이 떠 있는 동안에도 실행 상태는 방송으로 바뀝니다 — 나갈 요청이 없어지면
           단추를 잠그고 그 까닭을 단추 곁에 적습니다. 대상이 아예 없으면 그렇게
           말하고, 있는데 다 빠졌으면 빠진 까닭(목록 줄마다 단 말)을 모아 적습니다. */
        const none = everyone ? running === 0 : applied.length === 0
        const noneWhy = !none
          ? ''
          : everyone || chosen.length === 0
            ? '대상 실행이 없습니다'
            : [...new Set(excluded.map((run) => skipWhy(deed, run) as string))].join(' · ')
        return (
        <Modal
          label={DEED_LABEL[deed]}
          onClose={() => setDeed(null)}
          head={<span className="modal-title">{DEED_LABEL[deed]}</span>}
          /* 답을 받아야 하는 창이라 바깥을 눌러도 안 닫고 머리의 ✕ 도 안
             둡니다 — ✕ 는 아래 「그만두기」와 같은 일인데, 첫 초점이 ✕ 로
             가면 창이 물은 것에 답하는 자리가 초점 밖에 남습니다. 뜬 순간
             Enter 를 눌러도 아무 일이 안 나야 합니다(주문 확인창과 한 벌). */
          dismissable={false}
          closable={false}
        >
          {text !== null && (
            <dl className="run-confirm">
              <div className="run-confirm-row">
                <dt>주문</dt>
                <dd>{text.order}</dd>
              </div>
              <div className="run-confirm-row">
                <dt>보유분</dt>
                <dd>{text.holding}</dd>
              </div>
            </dl>
          )}
          {everyone ? (
            <p className="run-confirm-title">{`도는 검증 ${running}개에 겁니다`}</p>
          ) : (
            <>
              {/* 세는 것은 **요청이 실제로 나가는 건수**이고, 빠지는 줄은 목록에
                  두되 왜 빠지는지를 그 줄에 답니다. */}
              <p className="run-confirm-title">
                적용 범위 {applied.length}건
                {excluded.length > 0 && ` (제외 ${excluded.length}건)`}
              </p>
              <ul className="run-confirm-list">
                {chosen.map((run) => {
                  const skip = skipWhy(deed, run)
                  const said = nameOf(run.version)
                  return (
                    <li key={run.id} className={skip !== null ? 'run-confirm-skip' : undefined}>
                      {RUN_KIND_LABEL[run.mode]} · {said.name} {said.version} ·{' '}
                      {shortInstrument(run.code)}
                      {skip !== null && <span className="run-confirm-skip-why"> · {skip}</span>}
                    </li>
                  )
                })}
              </ul>
            </>
          )}
          <p className="run-confirm-why" id="vrf-confirm-why">
            {noneWhy}
          </p>
          <div className="run-confirm-acts">
            <button type="button" className="btn btn-quiet" onClick={() => setDeed(null)}>
              그만두기
            </button>
            {/* 창을 연 뒤 상태가 바뀌어 나갈 줄이 없어졌으면 누를 것이 없습니다. */}
            <button
              type="button"
              className="btn btn-heavy"
              aria-disabled={none}
              aria-describedby={none ? 'vrf-confirm-why' : undefined}
              onClick={() => !none && void commit(deed)}
            >
              {DEED_LABEL[deed]}
            </button>
          </div>
        </Modal>
        )
      })()
  )
}
