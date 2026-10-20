import { useRef, useState } from 'react'
import type { StrategyVersion } from '../../data/strategyList'
import { failLine, type SaveResult } from '../../data/strategyStore'
import { blankDraft } from './strategyListParts'
import type { makeListStats } from './listStats'

/** 머리 단추의 동작 — 새 전략·복제·보관·삭제와 못 누르는 까닭. */
export function useListActions({
  selected,
  saving,
  onNewDraft,
  resetFilters,
  onDuplicate,
  onArchive,
  onDelete,
  liveOf,
}: {
  selected: StrategyVersion | null
  saving: boolean
  onNewDraft: (row: StrategyVersion) => void
  resetFilters: () => void
  onDuplicate: (source: StrategyVersion, copy: StrategyVersion) => Promise<SaveResult>
  onArchive: (id: string) => Promise<SaveResult>
  onDelete: (id: string) => void
  liveOf: ReturnType<typeof makeListStats>['liveOf']
}) {
  /* 운영 이력이 있는 버전은 지우지 않고 보관합니다. 지워 버리면 그 버전이
     낸 체결이 어느 규칙에서 나온 것인지 되짚을 수 없습니다. */
  const canDelete = selected !== null && selected.trades === null

  /* 이미 보관한 줄은 다시 보관할 것이 없습니다 — 누르면 아무 일도 안 나는
     단추가 됩니다. */
  const archived = selected !== null && selected.status === '보관'

  /* 지금 막혀 있는 이유. 단추를 누를 수 없게만 두면 왜 안 되는지 알 길이
     없어, 못 누르는 단추와 이유를 늘 함께 답니다.
     **이유는 그 단추의 것만 답니다** — 「보관」이 막힌 이유와 「삭제」가 막힌
     이유는 다른 말입니다. 둘이 함께 설 때는 앞에 단추 이름을 붙여 어느
     단추의 답인지 가립니다. 하나면 이름 없이 그 이유만 섭니다. */
  /* 복제가 막힌 까닭. 다른 단추의 이유와 같은 줄에 섭니다 — 사본 줄은 이미
     걷혔으므로, 이 말이 없으면 누른 일이 없던 일처럼 보입니다. 그 원본을 고르고
     있는 동안만 섭니다. */
  const [copyFail, setCopyFail] = useState<{ id: string; text: string } | null>(null)
  const copyWhy = copyFail !== null && selected !== null && copyFail.id === selected.id ? copyFail.text : null
  /* 보관이 막힌 까닭. 복제와 같은 자리·같은 꼴입니다 — 상태는 서버가 받은 뒤에만
     바뀌므로, 이 말이 없으면 누른 일이 없던 일처럼 보입니다. */
  const [archiveFail, setArchiveFail] = useState<{ id: string; text: string } | null>(null)
  const archiveWhy =
    archiveFail !== null && selected !== null && archiveFail.id === selected.id ? archiveFail.text : null

  const reasons = !selected
    ? [{ id: 'stg-why-pick', name: '', text: '고른 전략이 없습니다' }]
    : [
        ...(copyWhy !== null
          ? [{ id: 'stg-why-copy', name: '', text: failLine('복제하지 못했습니다', copyWhy), fail: true }]
          : []),
        ...(archiveWhy !== null
          ? [{ id: 'stg-why-archive-fail', name: '', text: failLine('보관하지 못했습니다', archiveWhy), fail: true }]
          : []),
        /* 저장하는 동안 잠기는 단추는 복제·보관 둘이라 이름을 달지 않습니다. */
        ...(saving ? [{ id: 'stg-why-saving', name: '', text: '저장하는 중입니다' }] : []),
        ...(archived ? [{ id: 'stg-why-archive', name: '보관', text: '이미 보관한 버전입니다' }] : []),
        ...(canDelete
          ? []
          : [
              {
                id: 'stg-why-delete',
                name: '삭제',
                text: '거래 이력이 있는 버전은 삭제 대신 보관으로 둡니다',
              },
            ]),
      ]
  const named = reasons.length > 1

  /* 새로 만드는 것은 늘 초안입니다. 거래 성과를 가진 채로 태어나는 버전은
     없습니다 — 초안의 성과 칸이 「—」인 것도 그 때문입니다.
     첫 전략은 베낄 것이 없으므로 빈 자리에서 시작합니다. */

  function addNew() {
    /* **목록에 바로 세우지 않습니다.** 새 전략은 한도도 조건도 비어 있어 아직
       저장되지 않는 값이고, 목록에 세워 두면 새로고침 한 번에 사라집니다.
       설정 탭이 초안으로 열리고, 저장이 통과하면 그때 목록에 섭니다. */
    onNewDraft(blankDraft('새 전략', 'v1 초안'))
    resetFilters()
  }

  /* 그린 값(`saving`)은 다음 그림까지 옛 값이라, 한 번에 몰려 온 두 번째 누름은
     이것이 막습니다. */
  const duplicating = useRef(false)

  async function duplicate() {
    if (!selected || saving || duplicating.current) return
    duplicating.current = true
    const copy: StrategyVersion = {
      ...selected,
      id: `draft-${Date.now()}`,
      groupId: `draft-${Date.now()}`,
      name: `${selected.name} 사본`,
      version: 'v1 초안',
      status: '초안',
      pl: null,
      winRate: null,
      trades: null,
      maxDrawdown: null,
    }
    setCopyFail(null)
    try {
      const result = await onDuplicate(selected, copy)
      if (!result.ok) setCopyFail({ id: selected.id, text: result.message })
    } finally {
      duplicating.current = false
    }
  }

  const archiving = useRef(false)

  async function archive() {
    if (!selected || saving || archiving.current) return
    archiving.current = true
    setArchiveFail(null)
    try {
      const result = await onArchive(selected.id)
      if (!result.ok) setArchiveFail({ id: selected.id, text: result.message })
    } finally {
      archiving.current = false
    }
  }

  /* 삭제는 **확인 창을 한 번 지납니다** — 버전 하나를 지우는 것이고 되돌릴 수
     없습니다. 지우는 것은 서버가 합니다 — 목록에서 빼는 것도 그 답을 받은
     뒤입니다. 먼저 빼 두면 서버가 못 지웠을 때 화면에만 없는 전략이 생깁니다. */
  const [deleting, setDeleting] = useState(false)
  function remove() {
    if (!selected || !canDelete) return
    setDeleting(true)
  }
  function confirmRemove() {
    if (!selected || !canDelete || liveOf(selected.id).total > 0) return
    setDeleting(false)
    onDelete(selected.id)
  }

  return {
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
  }
}
