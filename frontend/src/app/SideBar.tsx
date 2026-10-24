import { useEffect, useRef } from 'react'
import { needsLeg } from '../data/instruments'
import type { RecentItem } from '../lib/types'
import { RECENT_EMPTY } from '../lib/labels'
import { useStoredState } from '../lib/useStoredState'

/* 오른쪽 접이식 사이드바.
 *
 * 오른쪽 끝 아이콘 열은 늘 보이고 폭이 고정입니다. 아이콘을 누르면 패널이
 * 열리고 다시 누르면 닫힙니다.
 *
 * 패널은 본문을 덮지 않고 **밉니다.** 열리면 본문이 그만큼 좁아지고 닫히면
 * 다시 넓어집니다. 덮으면 패널 아래에 무엇이 있는지 보이지 않아, 최근 본
 * 종목을 고르는 동안 지금 보던 값이 가려집니다.
 *
 * 본문은 「고정폭 여럿 + 늘어나는 것 하나」 규칙대로 줄어듭니다 — 화면마다
 * 늘어나기로 정해 둔 자리 하나가 그 폭을 내놓습니다.
 *
 * 아이콘 열이 늘 같은 폭이라 창을 줄여도 본문 폭이 튀지 않습니다 —
 * 접히는 지점이 없습니다.
 */

interface Item {
  id: string
  /** 아이콘 열에 서는 글자. 그림 대신 짧은 글자를 씁니다. */
  glyph: string
  label: string
}

const ITEMS: Item[] = [{ id: 'recent', glyph: '⏱', label: '최근 본' }]

interface Props {
  recent: RecentItem[]
  /** 지금 보고 있는 종목. 되돌아갈 길에 「지금 어디인가」가 함께 섭니다. */
  current: string | null
  onOpen: (item: RecentItem) => void
  /** 그 종목을 최근 본에서 뺍니다. 종목을 열지 않습니다. */
  onRemove: (code: string) => void
}

export function SideBar({ recent, current, onOpen, onRemove }: Props) {
  /* 열려 있는 항목. null 이면 아이콘 열만 보입니다.
     앱을 껐다 켜도 남습니다 — 늘 열어 두고 쓰는 사람이 매번 다시 열지
     않아도 되고, 값이 아니라 「어떻게 볼지」라 낡지 않습니다. */
  const [open, setOpen] = useStoredState<string | null>('nh.sidebar.open', null)
  const active = ITEMS.find((item) => item.id === open) ?? null

  /* 줄을 뺀 뒤 초점이 갈 곳. 뺀 줄의 단추가 사라지면 초점이 문서 맨 위로 떨어져,
     키보드로 이어서 빼던 사람이 자리를 잃습니다. 다음 줄 → 앞 줄 → 패널 머리
     차례입니다. `null` 은 패널 머리입니다. */
  const panelRef = useRef<HTMLDivElement>(null)
  const headRef = useRef<HTMLDivElement>(null)
  const focusNext = useRef<string | null | undefined>(undefined)
  useEffect(() => {
    const target = focusNext.current
    if (target === undefined) return
    focusNext.current = undefined
    const button =
      target === null
        ? null
        : panelRef.current?.querySelector<HTMLButtonElement>(
            `.recent-item[data-code="${CSS.escape(target)}"]`,
          )
    ;(button ?? headRef.current)?.focus()
  }, [recent])

  const remove = (index: number) => {
    const after = recent[index + 1] ?? recent[index - 1] ?? null
    focusNext.current = after?.code ?? null
    onRemove(recent[index].code)
  }

  return (
    <div className="sidebar">
      {/* 닫혀 있을 때도 자리에 남습니다. 폭 0 에서 패널 폭으로 자라야 본문이
          같은 속도로 따라 줄어듭니다 — 열 때마다 새로 그리면 본문이 한 번에
          툭 좁아집니다. 닫힌 동안에는 탭 이동에 걸리지 않습니다. */}
      <div
        className="sidebar-panel"
        /* 패널 폭은 창 폭에 따라 둘이라 CSS 한 자리가 정합니다(`shell.css` 의
           `--panel-width`). 바깥과 안쪽이 같은 값을 읽어야 글자가 잘리거나 빈
           띠가 생기지 않습니다. */
        style={{ width: active ? 'var(--panel-width)' : 0 }}
        inert={active === null}
        aria-hidden={active === null}
      >
        <div className="sidebar-panel-inner" ref={panelRef} style={{ width: 'var(--panel-width)' }}>
          <div className="sidebar-panel-head" ref={headRef} tabIndex={-1}>
            {active?.label ?? ITEMS[0].label}
          </div>

          {recent.length === 0 ? (
            <p className="recent-empty">{RECENT_EMPTY}</p>
          ) : (
            <div className="recent-list">
              {recent.map((item, index) => (
                /* 여는 단추와 빼는 단추는 **형제**입니다. 단추 안에 단추를 두면
                   누름이 어느 쪽 것인지 화면 읽기 프로그램도 사람도 가를 수
                   없습니다. */
                <div key={item.code} className="recent-row">
                  <button
                    type="button"
                    className="recent-item"
                    data-code={item.code}
                    aria-current={item.code === current}
                    title={item.name}
                    onClick={() => onOpen(item)}
                  >
                    <span className="recent-name">{item.name}</span>
                    {/* 행사가를 고르기 전 옵션은 코드가 아직 없습니다. 코드 자리에
                        서는 글자는 값보다 한 급 낮추는데, 이 자리는 이미 가장 작은
                        급이라 그대로 둡니다 — 더 내리면 읽기만 나빠집니다. */}
                    <span className="recent-code">
                      {needsLeg(item.code) ? '행사가 선택' : item.code}
                    </span>
                  </button>
                  {/* 줄에 마우스가 오르거나 초점이 줄 안에 있을 때만 보입니다.
                      안 보일 때도 키보드 초점은 받습니다. */}
                  <button
                    type="button"
                    className="recent-remove"
                    aria-label={`${item.name} 최근 본에서 빼기`}
                    title={`${item.name} 최근 본에서 빼기`}
                    onClick={() => remove(index)}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <nav className="sidebar-icons" aria-label="사이드바">
        {ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            className="sidebar-icon"
            aria-pressed={open === item.id}
            aria-label={item.label}
            title={item.label}
            onClick={() => setOpen(open === item.id ? null : item.id)}
          >
            <span aria-hidden="true">{item.glyph}</span>
          </button>
        ))}
      </nav>
    </div>
  )
}
