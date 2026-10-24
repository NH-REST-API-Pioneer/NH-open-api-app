import { useEffect, useRef, useState } from 'react'
import { resolve } from '../../data/instruments'
import { currencyOf } from '../../data/strategyList'
import {
  patchRun,
  savedOf,
  seedFromSelection,
  storeNote,
  useStrategyState,
  type ReconcileCount,
} from '../../data/strategyStore'
import { runCurrencyOf, type VerifyRun } from '../../data/strategyRuns'
import { Modal } from '../../app/Modal'
import { loadLimits, useLimits, type LimitAxis } from '../../data/strategyLimits'
import { runNameOf } from './runStats'
import { RunStatusCard } from './RunStatusCard'
import { ASK_TEXT, type AskFixed, type BottomTab, type Confirm, NOTE_DWELL } from './strategyRunUtils'
import { LimitsForm } from './LimitsForm'
import { RunAddForm } from './RunAddForm'
import { useTableWidth, useRunTables } from './useRunTable'
import { useRunView } from './useRunView'
import { useRunLimits } from './useRunLimits'
import { useRunLoads } from './useRunLoads'
import { makeRunActions } from './runActions'
import { runSideParts, renderRunsCard } from './RunSide'
import { renderRunHeadLine, renderRunLimits } from './RunHead'
import {
  renderRunTitle,
  renderRunBar,
  renderRunAttention,
  renderRunBottom,
  renderRunConfirm,
} from './RunMain'

/* 전략 진행 — 연결 계좌로 거래하는 화면.
 *
 * 검증과 공간 구조는 같지만 다루는 것이 다릅니다. 여기 나가는 것은 실제
 * 주문이고, 그래서 되돌릴 수 없는 동작마다 확인 창이 섭니다.
 *
 * **여기서 세우는 실행은 계좌로 실제 주문을 냅니다** — 접속 환경이 모의면 모의
 * 계좌(`mode: 'sim'`), 실전이면 실전 계좌(`mode: 'real'`)입니다. 그래서 시작 전에
 * 확인창을 한 번 지나고, 그 창을 지난 표지(`approvedAt`)가 없으면 서버가 한 건도
 * 내지 않습니다.
 *
 * 종이 장부로 도는 실행은 검증 화면이 봅니다. **목록은 한 벌**이고(서버가 한
 * 목록을 냅니다) 화면이 갈래로 가릅니다 — 둘로 들면 한도 일곱이 어느 쪽
 * 것인지 말할 수 없습니다.
 *
 * **차트는 두지 않습니다.** 같은 종목을 검증 화면이 이미 그리고, 이 화면이
 * 답할 것은 「지금 계좌에서 무슨 일이 일어났나」라 표가 먼저입니다.
 */

export function StrategyRun() {
  /* 실행·체크·보는 실행은 **화면 밖**에 있습니다. 보낸 요청(「취소 요청」·
     「확인 필요」)이 탭을 옮겼다는 이유로 사라지면, 화면이 아직 안 끝난 일을
     없던 일로 말하게 됩니다.
     여러 실행에 한 번에 거는 동작이 있어 **다중 선택**입니다. 고르는 것(체크)과
     보는 것(줄 몸 누름)을 따로 둡니다 — 검증 화면도 같은 두 겹입니다. */
  const store = useStrategyState()
  /* **실행 목록은 검증과 한 벌입니다.** 서버가 한 목록을 내고 화면이 갈래로
     가릅니다 — 따로 들면 방송 한 묶음을 두 번 쪼개야 하고, 한도 일곱이 어느
     쪽 것인지 말할 수 없습니다. */
  const { runs, status, failure, max, acting } = store.verify
  /* 실행을 담아 둔 파일을 서버가 못 읽었을 때 실행 카드에 세울 한 줄. */
  const storeWhy = storeNote('runs', store.runStore)
  /* 그중 **못 읽은** 경우. 빈 목록이 「없다」고 말해도 되는지가 여기서 갈립니다. */
  const storeBroken = store.runStore?.status === 'broken'
  const { checked, shownId, add, pending } = store.run
  const setChecked = (next: string[]) => patchRun({ checked: next })
  const setShownId = (id: string) => patchRun({ shownId: id })
  const openAdd = add !== null
  const closeAdd = () => patchRun({ add: null })

  /* 화면에만 남는 것들입니다. */
  const [bottom, setBottom] = useState<BottomTab>('최근 체결')
  const [confirm, setConfirm] = useState<Confirm>(null)
  const {
    tableBoxRef,
    tableInner,
  } = useTableWidth()
  /* 거래 추가 창이 **확인 얼굴**로 넘어갔는지. 창을 둘 겹치지 않고 한 창의
     얼굴을 바꿉니다 — 겹치면 뒤 카드의 칸이 앞 카드 둘레로 비어져 나오고,
     「그만두기」가 둘 보입니다. */
  const [ask, setAsk] = useState<AskFixed | null>(null)
  const asking = ask !== null
  /* 보낸 요청이 막혔을 때 서버가 준 문장. **그대로 세웁니다** — 화면이 같은
     검사를 다시 하면 둘이 갈립니다.
     **누른 단추 곁에 답니다.** 단추가 세 자리에 나뉘어 있어(머리 띠·목록
     아래·확인 띠) 한 자리에 모아 두면 누른 사람이 답을 다른 데서 찾습니다.
     새 답이 오면 앞의 답은 지웁니다 — 물음이 바뀌었는데 앞 답이 남아 있으면
     그것이 지금 답으로 읽힙니다. */
  const [why, setWhy] = useState<{ head?: string; side?: string; ack?: string }>({})
  /* 계좌와 대조를 기다리는 중인지와, 그 답(맞춰 본 수 또는 못 보낸 까닭).
     맞춰 본 결과는 잠깐 섰다가 걷힙니다 — 정상 결과라 남겨 둘 까닭이 없고,
     남으면 다음 대조의 답과 헷갈립니다. 매번 새 값이라 같은 결과가 다시 와도
     머무는 시간이 새로 셉니다. 못 보낸 까닭은 다음 대조까지 남습니다. */
  const [reconciling, setReconciling] = useState(false)
  const reconcileBusy = useRef(false)
  const [reconciled, setReconciled] = useState<
    { count: ReconcileCount | null } | { failed: string } | null
  >(null)
  useEffect(() => {
    if (reconciled === null || 'failed' in reconciled) return
    const timer = window.setTimeout(() => setReconciled(null), NOTE_DWELL)
    return () => window.clearTimeout(timer)
  }, [reconciled])

  /* 계좌 손실 한도. 창이 열려 있는지와, 저장을 보낸 사이인지. 보낸 사이에는
     창을 닫을 수 없습니다 — 닫고 나면 답이 어느 값으로 섰는지 볼 자리가 없습니다. */
  const limits = useLimits()
  const [limitsOpen, setLimitsOpen] = useState(false)
  const [limitsSaving, setLimitsSaving] = useState(false)
  /* 창을 열 때의 축. 창이 떠 있는 동안 접속 환경이 바뀌면 이 값과 갈리고, 그때
     창을 닫습니다(아래). */
  const [limitsAxis, setLimitsAxis] = useState<LimitAxis | null>(null)
  useEffect(() => {
    void loadLimits()
  }, [])
  const {
    environment,
    all,
    shown,
    snapshot,
    tickRun,
    narrow,
    picked,
    trading,
    stopped,
    ended,
    needCheck,
    reconcileLine,
    reconcileFailed,
    standingAll,
    kinds,
    split,
    askable,
  } = useRunView({
    runs,
    shownId,
    store,
    tableInner,
    checked,
    reconciling,
    reconciled,
  })
  const {
    axis,
    axisLimits,
    axisCurrencies,
    limitLine,
  } = useRunLimits({
    environment,
    limits,
    all,
    store,
  })
  /* 한도 창이 떠 있는 동안 축이 바뀌면 닫습니다 — 열 때의 계좌가 아닌 값을 고치게
     됩니다. 저장을 보낸 사이에는 답을 기다립니다. */
  useEffect(() => {
    if (limitsOpen && !limitsSaving && limitsAxis !== axis) setLimitsOpen(false)
  }, [axis, limitsAxis, limitsOpen, limitsSaving])

  /* 확인 얼굴이 떠 있는 동안 환경이 바뀌면 **닫고 폼으로 돌아갑니다.** 창에 보인
     갈래가 더는 지금 환경의 것이 아니라, 그대로 승인하면 서버가 거절하거나
     다른 계좌를 말하는 창이 남습니다. */
  useEffect(() => {
    if (ask === null) return
    const moved =
      environment.generation !== ask.generation ||
      environment.status !== 'ready' ||
      environment.active !== ask.environment ||
      !store.verify.accountModes.includes(ask.mode)
    if (moved) setAsk(null)
  }, [ask, environment.generation, environment.status, environment.active, store.verify.accountModes])

  /* 그 실행이 어느 전략의 것인가. **목록에서 찾습니다** — 실행 줄에 이름을
     적어 두면 전략 이름을 고칠 때 갈립니다(검증 화면과 같은 규칙). */
  const nameOf = (versionId: string) => runNameOf(store.rows, versionId, store.status === 'ready')
  /* 실행 줄의 통화 — 그 실행이 도는 전략의 것(검증 화면과 같은 셈). */
  const runCurrency = (run: VerifyRun) =>
    runCurrencyOf(run, currencyOf(run.market, store.rows.find((one) => one.id === run.version)?.currency))

  /* 앱이 보고 있는 청산 기준. **담긴 설정이 답합니다** — 줄에는 없는 값이고,
     서버가 받은 STOP 과도 다릅니다(앱이 꺼지면 이쪽은 멈춥니다). */
  const watch = shown ? savedOf(shown.version)?.aux : null
  /* 값의 자릿수는 **색인이 답합니다** — 줄에 적어 두면 만기가 넘어갈 때
     자릿수와 실제 종목이 갈립니다. */
  const decimals = (shown ? resolve(shown.code)?.product.decimals : null) ?? 2
  useRunLoads({
    environment,
    shown,
  })
  const {
    tableRows,
    events,
  } = useRunTables({
    bottom,
    snapshot,
  })

  /* 목록에서 「진행 화면으로」로 들고 온 전략. 이미 거래 중인 실행이 있으면
     그것을 보여 주고, 없을 때만 거래 추가 패널이 그 값으로 채워집니다. */
  useEffect(() => {
    if (!pending) return
    /* 줄은 버전 id 만 들고 있습니다 — 전략 이름은 목록에서 옵니다. */
    const wanted = store.rows.find(
      (row) => row.name === pending.strategy && row.version === pending.version,
    )
    const found = wanted ? all.find((run) => run.version === wanted.id) : undefined
    if (found) patchRun({ shownId: found.id, checked: [found.id], pending: null })
    else patchRun({ add: pending, pending: null })
    // 목록과 실행이 둘 다 있어야 고를 수 있어 둘을 함께 봅니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, runs, store.rows])
  const {
    showRun,
    toggle,
    apply,
    blocks,
    skipWhy,
    reconcile,
    openConfirm,
    acknowledge,
    badgeOf,
    directionOf,
  } = makeRunActions({
    setShownId,
    setChecked,
    checked,
    setConfirm,
    setWhy,
    reconcileBusy,
    setReconciling,
    setReconciled,
  })

  const {
    runRow,
  } = runSideParts({
    nameOf,
    shown,
    checked,
    toggle,
    showRun,
    badgeOf,
    directionOf,
    runCurrency,
  })

  return (
    <div className="run">
      <div className="card run-head">
        {renderRunHeadLine({
          kinds,
          split,
          max,
          trading,
          stopped,
          ended,
          standingAll,
          status,
          failure,
          needCheck,
          reconciling,
          reconcileLine,
          reconcile,
          reconcileFailed,
          why,
          openConfirm,
          all,
        })}

        {/* 머리 단추 둘의 까닭. **그 단추 곁**입니다 — 목록 아래 줄에 함께
            두면 머리에서 누른 사람이 답을 화면 반대쪽에서 찾게 됩니다. 자리는
            늘 비워 두어 아래가 오르내리지 않습니다. */}
        <p className="run-why run-head-why" id="run-head-why">
          {why.head ?? (trading === 0 ? '도는 실행이 없습니다' : '')}
        </p>

        {/* 계좌 전체의 하루 손실 한도. 실행 하나가 아니라 **그 축·그 시장의 계좌
            실행 전부**에 걸리므로 실행 카드가 아닌 머리에 둡니다. 어느 계좌의 한도인지
            낱말로 먼저 말합니다 — 접속 환경이 정한 축입니다.
            값을 모르는 동안에는 「바꾸기」를 잠급니다 — 저장은 한 축의 두 시장을
            함께 보내므로, 모르는 값을 빈 칸으로 보내면 걸려 있던 한도가 풀립니다. */}
        {renderRunLimits({
          axisLimits,
          limitLine,
          axis,
          limits,
          setLimitsAxis,
          setLimitsOpen,
        })}
        {/* 한도를 담아 둔 파일을 못 읽었거나 이 앱의 파일이 아니면, 서버는 한도를
            걸지 않은 채로 돕니다. 「걸지 않음」이 사용자가 고른 값으로 읽히지 않게
            까닭을 적습니다. 새로 저장하면 걷힙니다. */}
        {limits.store !== null && (limits.store.status === 'broken' || limits.store.otherApp !== null) && (
          <p className="run-store-why">한도 파일을 읽지 못해 풀렸습니다 — 다시 걸어 주세요</p>
        )}
      </div>

      <div className="run-body">
        <aside className="run-side" aria-label="실행 목록">
          <div className="run-side-inner">
            {renderRunsCard({
              storeWhy,
              status,
              all,
              runRow,
              picked,
              openConfirm,
              why,
            })}
          </div>
        </aside>

        {/* 거래 중인 실행이 하나도 없으면 오른쪽 상세(표)를 그리지 않습니다 — 빈 표는
            「고장」과 구별되지 않습니다. 가운데에 그 사실과 할 일 하나입니다. */}
        {status === 'ready' && all.length === 0 && !storeBroken ? (
          <div className="run-main notice">
            <p className="notice-title">거래 중인 실행이 없습니다</p>
            <button
              type="button"
              className="btn btn-primary notice-action"
              onClick={() => patchRun({ add: seedFromSelection() })}
            >
              거래 추가
            </button>
          </div>
        ) : (
        <div className="run-main">
          {/* 지금 보는 실행 — 전략 · 버전 · 종목 · 세션. 아래 표가 이 실행의 것입니다. */}
          {renderRunTitle({
            shown,
            nameOf,
          })}
          {renderRunBar({
            shown,
            decimals,
            runCurrency,
            watch,
          })}

          {/* 「확인 필요」는 사용자가 손을 써야 넘어가는 자리라, 목록 줄이 아니라
              **보는 실행 위**에 한 줄로 섭니다 — 줄 안에 두면 다른 실행을 보는
              동안 그 사실이 화면에서 사라집니다. */}
          {renderRunAttention({
            shown,
            acting,
            why,
            acknowledge,
          })}
          {/* 「확인」이 막힌 까닭도 그 단추 곁입니다. 띠가 서 있을 때만
              나오므로 자리를 늘 비워 두지는 않습니다. */}
          {why.ack && (
            <p className="run-why" id="run-ack-why">
              {why.ack}
            </p>
          )}

          {/* 지금 상태 — 자금·가격·신호가 나면 나갈 주문. 값은 실행 줄이 실어 온 그대로입니다.
              「확인 필요」 띠보다 아래입니다 — 손을 써야 하는 일이 먼저 보여야 합니다. */}
          {shown && (
            <RunStatusCard
              run={shown}
              aux={watch}
              rules={savedOf(shown.version)?.rules}
              decimals={decimals}
              currency={runCurrency(shown)}
            />
          )}

          {renderRunBottom({
            bottom,
            setBottom,
            tableBoxRef,
            snapshot,
            decimals,
            tickRun,
            events,
            narrow,
            tableRows,
          })}
        </div>
        )}
      </div>

      {renderRunConfirm({
        confirm,
        skipWhy,
        blocks,
        setConfirm,
        nameOf,
        apply,
      })}

      {openAdd && (
        <Modal
          label={ask ? ASK_TEXT[ask.mode].title : '거래 추가'}
          /* 확인 얼굴에서는 ✕ 도 바깥 누르기도 없습니다 — ✕ 는 아래
             「그만두기」와 같은 일인데, 첫 초점이 ✕ 로 가면 창이 물은 것에
             답하는 자리가 초점 밖에 남습니다(주문 확인창과 한 벌). */
          closable={!asking}
          dismissable={!asking}
          onClose={() => (asking ? setAsk(null) : closeAdd())}
          head={<span className="modal-title">{ask ? ASK_TEXT[ask.mode].title : '거래 추가'}</span>}
        >
          <RunAddForm
            rows={store.rows}
            savingId={store.saving}
            seed={add}
            why={store.verify.addWhy}
            ask={ask}
            askable={askable}
            onAsk={() => {
              /* 누른 순간의 갈래와 환경을 고정합니다. */
              if (askable === null || environment.active === null) return
              setAsk({ mode: askable, environment: environment.active, generation: environment.generation })
            }}
            onBack={() => setAsk(null)}
            onCancel={() => closeAdd()}
            onStarted={() => {
              setAsk(null)
              closeAdd()
            }}
          />
        </Modal>
      )}

      {limitsOpen && limitsAxis !== null && (limitsAxis === 'real' ? limits.real : limits.limits) !== null && (
        <Modal
          label={`계좌 손실 한도 · ${limitsAxis === 'real' ? '실전' : '모의'}`}
          closable={!limitsSaving}
          dismissable={!limitsSaving}
          onClose={() => !limitsSaving && setLimitsOpen(false)}
          head={
            <span className="modal-title">계좌 손실 한도 · {limitsAxis === 'real' ? '실전' : '모의'}</span>
          }
        >
          <LimitsForm
            axis={limitsAxis}
            currencies={axisCurrencies}
            start={(limitsAxis === 'real' ? limits.real : limits.limits)!}
            saving={limitsSaving}
            onSaving={setLimitsSaving}
            onClose={() => setLimitsOpen(false)}
          />
        </Modal>
      )}
    </div>
  )
}
