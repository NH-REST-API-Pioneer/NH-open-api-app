/* 전략 실행 알림의 토스트 묶음. 화면 오른쪽 아래, 본문 영역 안쪽 모서리에 섭니다 —
 * 오른쪽 세로 막대(최근 본 종목)는 본문 밖이라 가리지 않습니다. 일반주문 화면에서
 * 주문 카드가 그 모서리에 있으면 **주문 카드 왼쪽**에 섭니다 — 주문 단추를 덮으면
 * 주문을 내려던 손이 토스트를 누릅니다.
 *
 * **초점을 빼앗지 않습니다.** 토스트가 떠도 입력 중인 칸은 그대로이고, 토스트 안에
 * 초점이 있을 때만 Esc 가 그 토스트를 닫습니다. 마우스나 초점이 묶음 안에 있거나
 * 창이 가려진 동안에는 머무는 시간을 세지 않습니다. */
import { useEffect, useLayoutEffect, useState } from 'react'

import {
  bindRunName,
  dismissAllToasts,
  dismissToast,
  holdToasts,
  useToasts,
  type Toast,
} from '../data/alerts'
import { useStrategyState } from '../data/strategyStore'
import { RunKindBadge } from '../screens/strategy/runKind'
import { runNameOf } from '../screens/strategy/runStats'
import './toasts.css'

/** 한 번에 보이는 토스트 수. 넘치면 맨 위에 「알림 n개 더」가 섭니다. */
const SHOWN = 3
/** 본문 영역 모서리에서 띄우는 거리. */
const GAP = 16
/** 토스트 폭. 주문 카드와 겹치는지 셀 때 씁니다(`toasts.css` 와 같은 값). */
const WIDTH = 320

/** HH:MM:SS. */
function clock(ms: number): string {
  const at = new Date(ms)
  return [at.getHours(), at.getMinutes(), at.getSeconds()].map((one) => String(one).padStart(2, '0')).join(':')
}

export function Toasts({ page, onView }: { page: string; onView: (runIds: string[]) => void }) {
  const list = useToasts()
  const strategy = useStrategyState()
  /* 운영체제 알림의 제목에 적을 전략 이름 — 토스트와 같은 이름입니다. */
  useEffect(() => {
    bindRunName((version) => (version ? runNameOf(strategy.rows, version, strategy.rows.length > 0).name : ''))
  }, [strategy.rows])
  /* 자리는 본문 영역(`.app-screen`)의 오른쪽 아래 모서리입니다. 일반주문 화면에서
     주문 카드(`.card-form`)가 그 모서리 아래에 있으면 주문 카드 왼쪽으로 비킵니다 —
     높이·개수와 상관없이 주문 단추를 덮지 않습니다. 다만 카드 왼쪽에 토스트 폭만큼의
     자리가 없으면(주문 카드를 맨 왼쪽 열로 옮긴 배치) 기본 자리에 둡니다 — 닫을
     때까지 머무는 경고가 화면 밖에 서면 안 되므로 보이는 것이 먼저입니다. 창 크기·
     옆 막대의 폭·카드 배치가 바뀌면 다시 셉니다. 토스트가 떠 있는 동안 저절로
     자리를 바꾸지는 않습니다(배치가 바뀔 때만). */
  const [place, setPlace] = useState({ right: GAP, bottom: GAP })
  const firstShown = list.length > 0
  useLayoutEffect(() => {
    const screen = document.querySelector('.app-screen')
    if (!screen) return
    const measure = () => {
      const box = screen.getBoundingClientRect()
      let right = Math.max(0, window.innerWidth - box.right) + GAP
      const form = screen.querySelector('.card-form')
      if (form) {
        const card = form.getBoundingClientRect()
        const left = window.innerWidth - right - WIDTH
        const roomLeft = card.left - GAP - WIDTH
        if (card.width > 0 && card.right > left && card.left < window.innerWidth - right && roomLeft >= 0) {
          right = Math.max(0, window.innerWidth - card.left) + GAP
        }
      }
      setPlace({ right, bottom: Math.max(0, window.innerHeight - box.bottom) + GAP })
    }
    measure()
    const watch = new ResizeObserver(measure)
    watch.observe(screen)
    const form = screen.querySelector('.card-form')
    if (form) watch.observe(form)
    window.addEventListener('resize', measure)
    return () => {
      watch.disconnect()
      window.removeEventListener('resize', measure)
    }
    /* 화면을 옮겼을 때와 첫 토스트가 설 때 다시 셉니다 — 그 사이에 카드를 옮겼을
       수 있습니다. */
  }, [page, firstShown])

  const shown = list.slice(-SHOWN)
  const more = list.length - shown.length

  return (
    <section
      className="toasts"
      role="region"
      aria-label="알림"
      style={{ right: place.right, bottom: place.bottom }}
      onMouseEnter={() => holdToasts(true)}
      onMouseLeave={() => holdToasts(false)}
      onFocus={() => holdToasts(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) holdToasts(false)
      }}
    >
      {more > 0 && (
        <div className="toast-more">
          알림 {more}개 더 ·{' '}
          <button type="button" className="toast-link" onClick={dismissAllToasts}>
            모두 닫기
          </button>
        </div>
      )}
      {shown.map((one) => (
        <ToastCard key={one.id} toast={one} strategy={strategy} onView={onView} />
      ))}
    </section>
  )
}

function ToastCard({
  toast,
  strategy,
  onView,
}: {
  toast: Toast
  strategy: ReturnType<typeof useStrategyState>
  onView: (runIds: string[]) => void
}) {
  const name = toast.version ? runNameOf(strategy.rows, toast.version, strategy.rows.length > 0).name : ''
  /* 여는 실행 — 한 실행의 토스트는 그 실행, 묶음 토스트는 묶인 실행들입니다. 모두
     끝났거나 목록에서 빠졌으면 갈 화면이 없습니다. 단추는 남기되 잠급니다. */
  const targets = toast.runIds ?? (toast.runId !== null ? [toast.runId] : [])
  const gone = !targets.some((id) => {
    const run = strategy.verify.runs.find((one) => one.id === id)
    return run !== undefined && run.state !== 'ended'
  })
  const many = toast.runIds !== undefined
  return (
    <article
      className={`toast${toast.warn ? ' is-warn' : ''}`}
      role={toast.urgent ? 'alert' : 'status'}
      onKeyDown={(event) => {
        if (event.key !== 'Escape') return
        event.stopPropagation()
        dismissToast(toast.id)
      }}
    >
      <div className="toast-head">
        {toast.mode === 'real' && <RunKindBadge kind="real" short />}
        <span className="toast-kind">{toast.label}</span>
        <span className="toast-name">{name}</span>
        {toast.count > 1 && <span className="toast-count">×{toast.count}</span>}
        <span className="toast-time">{clock(toast.time)}</span>
        <button
          type="button"
          className="toast-close"
          aria-label="알림 닫기"
          onClick={() => dismissToast(toast.id)}
        >
          ✕
        </button>
      </div>
      <p className="toast-body">
        {toast.body.map((part, index) => (
          <span key={index} className={part.tone}>
            {part.text}
          </span>
        ))}
      </p>
      {targets.length > 0 && (
        <div className="toast-foot">
          <button
            type="button"
            className="toast-link"
            aria-label={many ? '끊긴 동안의 이벤트 보기' : `${name || '그'} 실행 보기`}
            aria-disabled={gone}
            title={gone ? '끝난 실행입니다' : undefined}
            onClick={() => {
              if (gone) return
              onView(targets)
              dismissToast(toast.id)
            }}
          >
            {many ? '이벤트 보기' : '보기'}
          </button>
        </div>
      )}
    </article>
  )
}
