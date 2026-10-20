import { useEffect, useMemo, useRef, useState } from 'react'

import { type StrategyVersion } from '../../data/strategyList'
import {
  STRATEGY_TABS,
  archiveVersion,
  deleteVersion,
  duplicateVersion,
  dirtyOf,
  draftOf,
  loadStrategies,
  saveVersion,
  patchRun,
  patchVerify,
  revertDrafts,
  revertVersion,
  saveNewVersion,
  selectStrategy,
  setDraft,
  startDraftVersion,
  setTab,
  storeNote,
  useStrategyState,
  type StrategyTab,
  versionOf,
} from '../../data/strategyStore'
import { StrategyList } from './StrategyList'
import { blankDraft } from './strategyListParts'
import { StrategySettings } from './StrategySettings'
import { StrategyVerify } from './StrategyVerify'
import { StrategyRun } from './StrategyRun'
import { StrategyAnalysis } from './StrategyAnalysis'
import { LeaveGuard } from './LeaveGuard'
import './strategy.css'
import './StrategyList.css'
import './StrategySettings.css'
import './StrategyVerify.css'
import './StrategyAnalysis.css'
import './StrategyRun.css'

/* 전략주문 화면.
 *
 * 하위 탭 다섯이 **화면 안 첫 줄**에 섭니다 — 계좌 화면과 같은 자리·같은
 * 장치입니다. 앱 상단의 두 단(로고 줄·페이지 탭)은 어느 화면에서나 같은
 * 것이라 여기에 세 번째 단을 얹지 않습니다.
 *
 * **상태는 화면 밖(`data/strategyStore.ts`)에 있습니다.** 이 화면은 페이지를
 * 옮길 때마다 통째로 사라졌다 다시 태어나므로, 여기에 담아 두면 상단에서
 * 「종목」에 갔다 오는 것만으로 실행과 고치던 설정이 없어집니다.
 */

export function StrategyScreen() {
  const state = useStrategyState()
  const { tab, rows, status, failure, selectedId } = state

  /* 저장해 둔 전략을 받아 옵니다. **화면이 태어날 때마다** 부릅니다 — 페이지를
     옮기면 이 화면은 통째로 사라졌다 다시 서는데, 그 사이 다른 창에서 고친
     것이 있을 수 있습니다. */
  useEffect(() => {
    void loadStrategies()
  }, [])

  /* 저장 안 한 채로 하위 탭을 떠나려 할 때 붙잡는 자리. 가려던 탭과 **그때
     함께 할 일**을 들고 있다가 사용자가 답하면 그리로 보냅니다. */
  const [leaving, setLeaving] = useState<{ tab: StrategyTab; then?: () => void } | null>(null)

  /* 지금 보고 있는 버전. **아직 목록에 없는 새 버전도 여기서 나옵니다** —
     가리면 「새 전략」을 만든 직후 설정 화면이 빈 채로 섭니다. */
  /* 고른 줄. **고치는 중인 칸을 겹쳐** 냅니다(`versionOf`) — 이름을 고치는
     자리가 설정이라, 겹치지 않으면 친 글자가 칸에 안 섭니다. 겹쳐 둔 것이
     바뀔 때 다시 세야 하므로 `state.edits` 도 함께 봅니다. */
  const selected = useMemo(
    () => (selectedId ? versionOf(selectedId) : null),
    [rows, selectedId, state.draftVersion, state.edits],
  )

  const dirty = selected !== null && tab === '전략 설정' && dirtyOf(selected.id)

  /* 탭을 옮기는 길은 하나뿐입니다 — 목록의 이동 단추도 여기를 지납니다.
     길이 둘이면 한쪽만 경고가 붙습니다.

     들고 갈 것이 있으면 `then` 으로 함께 넘깁니다. **경고보다 먼저 싣지
     않습니다** — 「여기 남기」를 골랐는데 요청만 건너가 있으면, 다음에 그
     탭에 들를 때 사용자가 취소한 화면이 열립니다. */
  function goTab(next: StrategyTab, then?: () => void) {
    if (dirty && next !== tab) {
      setLeaving({ tab: next, then })
      return
    }
    then?.()
    setTab(next)
  }

  /* 목록에서 「검증 화면으로」·「진행 화면으로」. **그 전략을 들고 갑니다** —
     탭만 바꾸면 방금 고른 전략과 무관한 화면이 서고, 사용자가 거기서 같은
     전략을 다시 찾아야 합니다. */
  function openVerify() {
    if (!selected) return goTab('전략 검증')
    openRunsTab('verify', { strategy: selected.name, version: selected.version })
  }

  function openRun() {
    if (!selected) return goTab('전략 진행')
    openRunsTab('run', { strategy: selected.name, version: selected.version })
  }

  /** 검증·진행 탭으로 건너가는 길 하나. 전략을 들고 가면 그 탭이 그 버전의 첫
   *  실행을 고르고(없으면 추가 패널), 실행 하나를 들고 가면 그 실행을 엽니다.
   *  실행을 열 때 **체크는 하지 않습니다** — 일괄 조작의 대상은 사용자가 체크한
   *  것뿐이라, 건너오면서 되돌릴 수 없는 동작의 대상이 저절로 생기면 안 됩니다. */
  function openRunsTab(tab: 'verify' | 'run', ask: { strategy: string; version: string } | { runId: string }) {
    goTab(tab === 'verify' ? '전략 검증' : '전략 진행', () => {
      if ('runId' in ask) {
        if (tab === 'verify') patchVerify({ pickedId: ask.runId })
        else patchRun({ shownId: ask.runId })
      } else if (tab === 'verify') patchVerify({ pending: ask })
      else patchRun({ pending: ask })
    })
  }

  /* 「새 버전 저장」 — 목록에 **다음 버전 초안 행**을 만듭니다.
     「저장」과 결과가 같으면 두 단추가 같은 일을 하는 셈이라, 하나는 눌러도
     아무 일이 없는 단추가 됩니다.
     새 행은 초안이라 성과 칸이 비어 있습니다 — 거래를 가진 채로 태어나는
     버전은 없습니다. 지금 고치던 값이 그대로 새 행의 저장된 값이 되고,
     화면도 새 행으로 옮겨 갑니다. */
  /* 그린 값(`state.saving`)은 다음 그림까지 옛 값이라, 한 번에 몰려 온 두 번째
     누름은 이것이 막습니다. */
  const savingNew = useRef(false)

  async function saveAsNew() {
    if (!selected || state.saving !== null || savingNew.current) return
    const numbers = rows
      .filter((row) => row.groupId === selected.groupId)
      .map((row) => Number(/v(\d+)/.exec(row.version)?.[1] ?? 0))
    const next = Math.max(0, ...numbers) + 1
    const id = `draft-${Date.now()}`
    const row: StrategyVersion = {
      ...selected,
      id,
      version: `v${next} 초안`,
      status: '초안',
      pl: null,
      winRate: null,
      trades: null,
      maxDrawdown: null,
    }
    /* 새 줄은 같은 전략의 마지막 줄 **바로 뒤**에 서고(이웃한 같은 묶음을
       들여쓰기로 묶습니다), 고치던 값은 새 버전이 들고 가며, 바로 서버에
       남깁니다 — 목록에만 있고 서버에 없으면 새로고침 한 번에 사라집니다. 막히면
       모두 되돌립니다(`saveNewVersion`). */
    savingNew.current = true
    try {
      await saveNewVersion(selected, row)
    } finally {
      savingNew.current = false
    }
  }

  function settingsPanel() {
    /* 고른 것이 없을 때 빈 화면을 그대로 두지 않습니다. 비어 있는 것과
       고장난 것은 화면에서 같아 보입니다. */
    if (!selected) {
      return (
        <div className="notice">
          <p className="notice-title">전략을 아직 안 골랐습니다</p>
          <p className="notice-reason">목록에서 전략을 고르거나 새 전략을 만드세요</p>
          {/* 말한 두 길을 그 자리에서 — 새 전략은 목록의 「새 전략」과 같은 초안입니다. */}
          <div className="notice-action notice-acts">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => startDraftVersion(blankDraft('새 전략', 'v1 초안'))}
            >
              새 전략
            </button>
            <button type="button" className="btn btn-quiet" onClick={() => goTab('전략 목록')}>
              목록으로
            </button>
          </div>
        </div>
      )
    }
    const id = selected.id
    return (
      <StrategySettings
        version={selected}
        draft={draftOf(id)}
        dirty={dirtyOf(id)}
        onChange={(next) => setDraft(id, next)}
        /* 저장은 서버가 받습니다. **받은 답이 저장 여부를 정합니다** —
           오류가 있으면 저장되지 않고, 화면은 그 답을 칸 옆과 저장 단추 위에
           세웁니다(`data/strategyStore.ts` 의 `results`). */
        result={state.results[id] ?? null}
        /* 아직 목록에 없는 새 버전인가. 설정 상단 한 줄이 이 값으로 섭니다. */
        unsaved={state.draftVersion?.id === id}
        onSave={() => void saveVersion(id)}
        onSaveAsNew={() => void saveAsNew()}
        /* 어느 버전이든 저장하는 중이면 「새 버전 저장」을 잠급니다. */
        busy={state.saving !== null}
        onRevert={() => revertVersion(id)}
      />
    )
  }

  return (
    <div className="stg">
      <div className="tabs tabs-inline stg-tabs">
        {STRATEGY_TABS.map((item) => (
          <button
            key={item}
            type="button"
            className="tab"
            aria-current={item === tab}
            onClick={() => goTab(item)}
          >
            {item}
          </button>
        ))}
      </div>

      <section className="stg-panel" aria-label={tab}>
        {tab === '전략 목록' ? (
          <StrategyList
            rows={rows}
            status={status}
            failure={failure}
            /* 담아 둔 파일을 서버가 못 읽었으면 그 말을 세웁니다 — 빈 표만으로는
               「없다」와 「못 읽었다」가 같아 보입니다. */
            storeWhy={storeNote('versions', state.store)}
            onReload={() => void loadStrategies()}
            onDuplicate={duplicateVersion}
            onArchive={archiveVersion}
            onNewDraft={startDraftVersion}
            auxOf={(id) => draftOf(id).aux}
            onDelete={(id) => void deleteVersion(id)}
            selectedId={selectedId}
            onSelect={selectStrategy}
            onOpenSettings={() => goTab('전략 설정')}
            onOpenCheck={openVerify}
            onOpenRun={openRun}
            onOpenRunsOf={(row, tab) => {
              /* 그 버전을 고르고 그 탭에서 그 버전의 첫 실행을 엽니다 — 탭이 받는 요청은
                 「검증 화면으로」·「진행 화면으로」와 같은 꼴입니다. */
              selectStrategy(row.id)
              openRunsTab(tab, { strategy: row.name, version: row.version })
            }}
          />
        ) : tab === '전략 설정' ? (
          settingsPanel()
        ) : tab === '전략 검증' ? (
          <StrategyVerify onOpenRun={(runId) => openRunsTab('run', { runId })} />
        ) : tab === '전략 진행' ? (
          <StrategyRun />
        ) : (
          <StrategyAnalysis />
        )}
      </section>

      {leaving && (
        <LeaveGuard
          onStay={() => setLeaving(null)}
          onLeave={() => {
            /* 상단 페이지에서 떠날 때와 같은 자리를 씁니다 — 되돌리는 방식이
               갈리면 어느 길로 나갔는지에 따라 남는 값이 달라집니다. */
            revertDrafts()
            leaving.then?.()
            setTab(leaving.tab)
            setLeaving(null)
          }}
        />
      )}
    </div>
  )
}
