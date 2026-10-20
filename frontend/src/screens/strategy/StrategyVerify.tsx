import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { isPaperRun } from '../../data/strategyRuns'
import { loadRuns, patchVerify, storeNote, useStrategyState } from '../../data/strategyStore'
import { Modal } from '../../app/Modal'
import type { MarkPick } from './MarkPopover'
import type { IndicatorSettings } from '../trade/chartIndicators'
import type { SlotState } from '../trade/chartSlots'
import type { BottomTab, Deed } from './strategyVerifyUtils'
import { VerifyAddForm } from './VerifyAddForm'
import { useVerifyRun } from './useVerifyRun'
import { useVerifyChart } from './useVerifyChart'
import { useVerifyTables } from './useVerifyTables'
import { makeVerifyActions } from './verifyActions'
import { verifySideParts, renderRunsCard, renderFundSections } from './VerifySide'
import {
  renderVerifyHead,
  renderMainTitle,
  renderMainBar,
  renderMainChart,
  renderMainBottom,
  renderDeedConfirm,
} from './VerifyMain'

/* 전략 검증 — 왼쪽 실행 목록, 가운데 큰 차트, 아래 표.
 *
 * **여기 서는 실행이 종이 하나는 아닙니다.** 모의 계좌로 도는 실행도 이 목록에
 * 함께 섭니다 — 진행 화면에는 차트가 없어, 모의 실행의 봉과 체결을 보는 자리가
 * 여기뿐입니다. 그래서 「앱 시뮬레이션」이라고 못 박지 않고 **고른 실행의 갈래가**
 * 머리 배지와 낱말을 정합니다(모의면 진행 화면과 같은 「모의 계좌」 배지).
 *
 * 모드를 고르는 자리는 여기 없습니다 — 실행을 세울 때 정해집니다. **이 화면에
 * 주문 단추는 없지만, 여기 선 모의 실행은 계좌로 주문을 냅니다** — 그 실행을
 * 세우고 승인하는 자리가 진행 화면일 뿐입니다.
 *
 * 오른쪽에 계산 카드를 늘어놓지 않습니다. 이 화면에서 읽는 것은 「어디서
 * 사고팔았는가」이고 그것은 차트 폭이 넓을수록 잘 읽힙니다 — 상세는 필요할
 * 때 열고 닫습니다.
 */

export function StrategyVerify({ onOpenRun }: {
  /** 「거래 중 n — 진행에서 보기」를 눌렀을 때 — 진행 탭으로 건너가 그 계좌
   *  실행을 엽니다. 목록의 「거래 중 n」 배지와 같은 이동 길입니다. */
  onOpenRun: (runId: string) => void
}) {
  /* 실행 목록·고른 실행·「신호 · 주문도 표시」는 **화면 밖**에 있습니다. 탭을
     옮겼다 와도, 상단에서 다른 페이지에 갔다 와도 검증은 계속 도는 것이어야
     합니다. 임시 자료로 시작한 실행과 「검증 추가」로 더한 실행을
     한 벌로 두는 것도 같은 이유입니다 — 따로 들면 중지·시작이 한쪽에만
     먹습니다. */
  const store = useStrategyState()
  const { runs, pickedId, checked, showDetail, add, pending, status, failure, acting, max } =
    store.verify
  /* 실행을 담아 둔 파일을 서버가 못 읽었을 때 실행 카드에 세울 한 줄. */
  const storeWhy = storeNote('runs', store.runStore)
  /* 그중 **못 읽은** 경우. 빈 목록이 「없다」고 말해도 되는지가 여기서 갈립니다. */
  const storeBroken = store.runStore?.status === 'broken'
  const setPickedId = (id: string) => patchVerify({ pickedId: id })
  const setShowDetail = (on: boolean) => patchVerify({ showDetail: on })
  const openPanel = add !== null
  const closePanel = () => patchVerify({ add: null })

  /* 화면에만 남는 것들입니다 — 어느 하단 탭을 보고 있었는지, 상세를 폈는지는
     다시 들어오면 처음 자리에서 시작해도 잃는 것이 없습니다. */
  /* 아래 탭. **조건이 첫 탭·기본**입니다 — 「왜 안 걸리나」가 이 화면에서 가장 먼저
     묻는 것이라서입니다. 실행을 바꿀 때 그 실행에 체결이 있으면 「체결」로 엽니다. */
  const [bottom, setBottom] = useState<BottomTab>('조건')
  /* 카드의 「안 낸 신호」를 눌러 고른 실행이면, 그 실행의 한 벌이 와도 탭을 바꾸지
     않고 이벤트에 둡니다. */
  const tabAsked = useRef<BottomTab | null>(null)
  const [markPick, setMarkPick] = useState<MarkPick | null>(null)
  const [open, setOpen] = useState({ fund: true, fill: true })
  const boxRef = useRef<HTMLDivElement>(null)
  /* 확인 창이 열려 있는 동작과, 마지막 요청이 막힌 까닭. 까닭은 **서버 문장
     그대로**입니다 — 화면이 다시 판정하면 서버와 갈립니다. */
  const [deed, setDeed] = useState<Deed | null>(null)
  const [why, setWhy] = useState<string | null>(null)
  /* 그 한 줄이 **경고**인지 — 검증 탭의 전체 중지가 계좌 실행까지 멈춘 경우입니다.
     막혀서 못 한 일과 달리 이미 일어난 일이라 흐린 글자로 두면 놓칩니다. */
  const [whyWarn, setWhyWarn] = useState(false)

  /* 돌고 있는 실행을 받아 옵니다. **화면이 태어날 때 한 번**입니다 — 그 뒤로는
     허브가 보내 주는 것으로 채웁니다(회차 ③-b). */
  useEffect(() => {
    void loadRuns()
  }, [])

  /* 목록에서 「검증 화면으로」로 들고 온 전략. **이미 도는 실행이 있으면 그것을
     고르고**, 없을 때만 추가 패널이 그 값으로 채워진 채 섭니다. */
  useEffect(() => {
    if (!pending) return
    const wanted = store.rows.find(
      (row) => row.name === pending.strategy && row.version === pending.version,
    )
    /* 찾는 것은 **그 버전의 종이 실행**입니다 — 계좌 실행은 이 탭이 보지 않습니다. */
    const found = wanted
      ? runs.find((run) => isPaperRun(run) && run.version === wanted.id)
      : undefined
    if (found) patchVerify({ pickedId: found.id, pending: null })
    else patchVerify({ add: pending, pending: null })
  }, [pending, runs, store.rows])

  /* 낮은 창에서는 상세 아코디언을 접은 채로 엽니다. 펴 둔 채로
     시작하면 왼쪽이 길어져 처음 보는 화면이 이미 굴러 있습니다. */
  useLayoutEffect(() => {
    const height = boxRef.current?.clientHeight ?? 0
    if (height > 0 && height < 600) setOpen({ fund: false, fill: false })
  }, [])
  const [slot, setSlot] = useState<SlotState>({ instrument: null, span: 'minute', indicators: null })
  /* 검증 차트에만 덮는 지표 — 실행마다 한 벌입니다. 처음은 **그 실행이 도는 규칙의
     지표**(`ruleIndicators`)이고, 보는 동안 끄고 켠 것은 그 실행에 한해 기억합니다.
     저장하지 않아 창을 닫으면 잊고, 일반주문 차트의 지표 구성은 그대로입니다. */
  const [layers, setLayers] = useState<Record<string, IndicatorSettings>>({})
  const {
    all,
    picked,
    snapshot,
    running,
    stopped,
    ended,
    standing,
    full,
    fullWhy,
    tradingLink,
    openAdd,
  } = useVerifyRun({
    runs,
    pickedId,
    store,
    max,
    onOpenRun,
    tabAsked,
    setBottom,
  })
  const {
    indicatorLayer,
    decimals,
    pickedRow,
    currency,
    runCurrency,
    nameOf,
    quote,
    bars,
  } = useVerifyChart({
    picked,
    layers,
    setLayers,
    store,
    slot,
  })
  const {
    marks,
    tableRows,
    events,
    eventBoxRef,
  } = useVerifyTables({
    picked,
    snapshot,
    nameOf,
    bars,
    slot,
    decimals,
    currency,
    store,
    bottom,
  })
  const {
    chosen,
    toggleCheck,
    skipWhy,
    acts,
    groups,
    whyIdOf,
    commit,
    pickRun,
  } = makeVerifyActions({
    all,
    checked,
    acting,
    setDeed,
    setWhy,
    setWhyWarn,
    setPickedId,
    setMarkPick,
  })

  const {
    runRow,
    accordion,
    money,
    usedText,
    marginLine,
  } = verifySideParts({
    picked,
    checked,
    toggleCheck,
    setBottom,
    tabAsked,
    pickRun,
    nameOf,
    runCurrency,
    open,
    setOpen,
    currency,
  })

  return (
    <div className="vrf" ref={boxRef}>
      {renderVerifyHead({
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
      })}

      <div className="vrf-body">
        {/* 왼쪽은 제 안에서 구릅니다. 이 열이 길어질 때 화면 전체를 늘리면
            차트와 아래 표까지 밀려 내려갑니다 — 상세는 필요할 때 열고 닫는
            자리이고, 화면의 높이를 정하는 것은 차트와 표입니다. */}
        <aside className="vrf-side" aria-label="검증 실행 목록">
          <div className="vrf-side-inner">
          {renderRunsCard({
            storeWhy,
            status,
            all,
            runRow,
            chosen,
            acts,
            whyIdOf,
            setDeed,
            groups,
          })}

          {/* 실행이 하나도 없으면 자금·체결 가정 카드를 그리지 않습니다 — 고른 실행이
              없어 칸이 다 「—」라, 선 카드가 빈 값을 값처럼 보입니다. */}
          {renderFundSections({
            all,
            accordion,
            picked,
            usedText,
            money,
            marginLine,
            currency,
          })}
          </div>
        </aside>

        {/* 도는 검증이 하나도 없으면 오른쪽 상세(차트·표)를 그리지 않습니다 — 빈 차트와
            빈 표는 「고장」과 구별되지 않습니다. 가운데에 그 사실과 할 일 하나입니다. */}
        {status === 'ready' && all.length === 0 && !storeBroken ? (
          <div className="vrf-main notice">
            <p className="notice-title">도는 검증이 없습니다</p>
            {/* 진행 탭에 계좌 실행만 돌고 있으면 「없다」만으로는 그 실행들이 사라진
                것처럼 읽힙니다 — 어디서 보는지 한 줄로 잇습니다. */}
            {tradingLink}
            <button
              type="button"
              className="btn btn-primary notice-action"
              aria-disabled={full}
              title={full ? fullWhy : undefined}
              onClick={openAdd}
            >
              검증 추가
            </button>
          </div>
        ) : (
        <div className="vrf-main">
          {/* 지금 보는 실행이 무엇인지 — 전략 · 버전 · 종목 · 세션. 차트·표가 이 실행의
              것입니다. */}
          {renderMainTitle({
            picked,
            nameOf,
          })}
          {renderMainBar({
            picked,
            decimals,
            currency,
            showDetail,
            setShowDetail,
          })}

          {renderMainChart({
            picked,
            quote,
            slot,
            setSlot,
            marks,
            setMarkPick,
            indicatorLayer,
            markPick,
          })}

          {renderMainBottom({
            bottom,
            setBottom,
            eventBoxRef,
            snapshot,
            decimals,
            pickedRow,
            picked,
            events,
            tableRows,
          })}
        </div>
        )}
      </div>

      {openPanel && (
        <Modal
          label="검증 추가"
          onClose={() => closePanel()}
          head={<span className="modal-title">검증 추가</span>}
        >
          <VerifyAddForm
            rows={store.rows}
            savingId={store.saving}
            seed={add}
            why={store.verify.addWhy}
            onCancel={() => closePanel()}
            onStarted={() => closePanel()}
          />
        </Modal>
      )}

      {/* 되돌릴 수 없는 동작의 확인 창. **무엇이 일어나는지를 줄여 적지
          않습니다** — 진입 주문과 보유분이 각각 어떻게 되는지 두 줄로 적고,
          그 표는 진행 화면과 같은 한 벌입니다. */}
      {renderDeedConfirm({
        deed,
        chosen,
        skipWhy,
        running,
        setDeed,
        nameOf,
        commit,
      })}
    </div>
  )
}
