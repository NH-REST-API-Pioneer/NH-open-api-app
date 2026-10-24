import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { DEFAULT_ZOOM, ZOOM_STEPS, inDesktop, stepIndex, zoomBridge } from '../lib/zoom'

/* 상단 머리의 「가」 단추와, 누르면 뜨는 작은 창.
 *
 * 네 단(작게 · 보통 · 크게 · 더 크게) 가운데 하나를 고르면 데스크톱 앱 창의 배율이
 * 그 값으로 바뀝니다(`lib/zoom`). 고른 값은 데스크톱 앱이 이 컴퓨터에 기억합니다. 사용자가 Ctrl + 휠로
 * 배율을 바꿨을 수 있어 창을 열 때 실제 배율을 읽고, 네 단 밖이면 아무 단도 고르지
 * 않은 채 「지금 125%」처럼 알립니다.
 *
 * **브라우저에서는 네 단을 누를 수 없습니다** — 브라우저의 배율은 Ctrl + / − 가 정합니다.
 * 못 누르는 까닭을 안내 줄에 적고 네 단이 그 줄을 가리킵니다.
 *
 * **창은 문서 맨 끝(`body`)에 그립니다.** 머리 줄은 높이를 넘는 것을 잘라 내므로, 그
 * 안에 두면 아래로 뜨는 창이 보이지 않습니다. 자리는 「가」 단추 바로 아래, 오른쪽 끝을
 * 단추 오른쪽 끝에 맞춥니다. 창 크기·배율이 바뀌면 다시 셉니다.
 *
 * 데스크톱에서는 화면이 뜰 때 실제 배율을 한 번 미리 읽어 둡니다. 창을 열면 그 값으로
 * 바로 그리고, 열 때 한 번 더 읽어 그사이 바뀐 배율을 맞춥니다. 처음 읽기가 끝나기 전에
 * 열면 끝날 때까지 창을 보이지 않습니다 — 잠깐 다른 단이 보였다가 바뀌지 않게 합니다.
 * 앱이 0.5초 안에 답하지 않으면 그때까지 아는 값(못 읽었으면 보통)으로 보입니다.
 *
 * 열리면 초점이 고른 단으로 가고, 화살표·Home·End 로 단을 옮겨 고릅니다. 바깥을
 * 누르거나 Esc 로 닫히고, Esc 로 닫으면 초점이 「가」 단추로 돌아옵니다. Tab 으로
 * 창 밖으로 초점이 나가도 닫힙니다.
 */

/** 단추와 창 사이 틈(px). */
const GAP = 6

/** 연 뒤 이만큼(ms) 지나도 지금 배율을 못 읽었으면, 그때까지 아는 값으로 창을 보입니다. */
const READ_WAIT_MS = 500

const NOTE_DESKTOP = '화면 전체가 함께 커집니다 · 좁은 창에서는 가로로 밀릴 수 있습니다 · 이 컴퓨터에 기억'
const NOTE_BROWSER = '데스크톱 앱에서 동작합니다 · 브라우저에서는 Ctrl + / − 로 조절하세요'

export function TextSizeMenu() {
  const desktop = inDesktop()
  const [open, setOpen] = useState(false)
  /* 지금 배율. 브라우저에서는 늘 보통입니다. 데스크톱에서는 실제 값을 읽어 맞춥니다. */
  const [value, setValue] = useState(DEFAULT_ZOOM)
  /* 지금 배율을 아는지. 데스크톱은 처음 읽기가 끝나야(못 읽었어도) 압니다. */
  const [known, setKnown] = useState(!desktop)
  const [place, setPlace] = useState<{ top: number; left: number } | null>(null)
  const button = useRef<HTMLButtonElement>(null)
  const pop = useRef<HTMLDivElement>(null)
  const items = useRef<(HTMLButtonElement | null)[]>([])
  const noteId = useId()
  const current = stepIndex(value)
  /* 지금 배율을 읽는 답이 올 때 비교할 값. 화면에 그린 값과 늘 같이 바꿉니다(`put`). */
  const valueRef = useRef(value)
  /* 읽은 값이 달라졌고 초점이 창 안이었으면, 다시 그린 뒤 초점을 새 단으로 옮깁니다. */
  const refocus = useRef(false)

  const put = useCallback((next: number) => {
    valueRef.current = next
    setValue(next)
  }, [])

  /* 읽은 배율을 적용합니다 — 미리 읽기와 열 때 읽기가 함께 씁니다. 값과 「안다」를 한
     번에 바꿔 다른 단이 먼저 보이는 그림이 없게 하고, 값이 바뀌었는데 초점이 창 안에
     있으면 초점도 새 단으로 옮깁니다. 못 읽었으면(`null`) 아는 값 그대로입니다. */
  const applyRead = useCallback(
    (actual: number | null) => {
      if (typeof actual === 'number' && actual > 0 && Math.abs(actual - valueRef.current) >= 1e-6) {
        refocus.current = pop.current?.contains(document.activeElement) ?? false
        put(actual)
      }
      setKnown(true)
    },
    [put],
  )

  const measure = useCallback(() => {
    const box = button.current?.getBoundingClientRect()
    const width = pop.current?.offsetWidth ?? 0
    if (!box) return
    setPlace({ top: box.bottom + GAP, left: Math.max(box.right - width, 0) })
  }, [])

  useLayoutEffect(() => {
    if (open) measure()
    else setPlace(null)
  }, [open, value, measure])

  /* 화면이 뜰 때 실제 배율을 한 번 미리 읽습니다. 앱이 아직 함수를 열기 전이면 열었다는
     알림(`pywebviewready`)을 받고 읽습니다. */
  useEffect(() => {
    if (!desktop) return
    let live = true
    const read = () => {
      const bridge = zoomBridge()
      if (!bridge) return false
      bridge.get_zoom().then(
        (actual) => {
          if (live) applyRead(actual)
        },
        () => {
          /* 못 읽으면 보통으로 보입니다. */
          if (live) applyRead(null)
        },
      )
      return true
    }
    if (read()) {
      return () => {
        live = false
      }
    }
    const onReady = () => {
      read()
    }
    window.addEventListener('pywebviewready', onReady, { once: true })
    return () => {
      live = false
      window.removeEventListener('pywebviewready', onReady)
    }
  }, [desktop, applyRead])

  /* 열 때 한 번 더 읽습니다 — 그사이 Ctrl + 휠로 바뀌었을 수 있습니다. 앱이 아직 함수를
     열기 전이면 여기서는 읽지 않고, 미리 읽기의 답이나 아래 기다림 시간에 맡깁니다. */
  useEffect(() => {
    if (!open) return
    const bridge = zoomBridge()
    if (!bridge) return
    let live = true
    bridge.get_zoom().then(
      (actual) => {
        if (live) applyRead(actual)
      },
      () => {
        /* 못 읽으면 마지막으로 안 값으로 보입니다. */
        if (live) applyRead(null)
      },
    )
    return () => {
      live = false
    }
  }, [open, applyRead])

  /* 앱이 답하지 않아도 창이 영영 안 보이지는 않게 합니다. 읽기가 끝나거나 창을 닫으면
     기다리기를 그만둡니다. */
  useEffect(() => {
    if (!open || known) return
    const timer = window.setTimeout(() => setKnown(true), READ_WAIT_MS)
    return () => window.clearTimeout(timer)
  }, [open, known])

  useEffect(() => {
    if (!refocus.current) return
    refocus.current = false
    const at = stepIndex(value)
    items.current[at >= 0 ? at : stepIndex(1)]?.focus()
  }, [value])

  useEffect(() => {
    if (!open) return
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node
      if (button.current?.contains(target) || pop.current?.contains(target)) return
      setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      setOpen(false)
      button.current?.focus()
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [open, measure])

  /* 열리면 초점을 고른 단(없으면 보통)으로 — 키보드로 열자마자 고를 수 있습니다. 자리를
     세고 지금 배율을 안 뒤(보이게 된 뒤) 한 번만 옮깁니다. 그 뒤로는 화살표가 초점을
     옮깁니다. */
  const shown = place !== null && known
  useEffect(() => {
    if (!open || !shown) return
    const at = stepIndex(value)
    items.current[at >= 0 ? at : stepIndex(1)]?.focus()
    // 열릴 때 한 번만 옮깁니다. 값이 바뀔 때마다 옮기면 화살표와 겹칩니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, shown])

  /* 초점이 창과 「가」 단추 밖으로 나가면(Tab 등) 닫습니다. 창은 문서 맨 끝에 있어 Tab 이
     문서 밖(앱 바깥)으로 나갈 수도 있는데, 그때는 초점이 갈 곳을 바로 알 수 없어 한 박자
     뒤에 문서가 초점을 잃었는지 봅니다. 창 안의 글자를 눌러 초점이 잠깐 빠진 것은 닫지
     않습니다. 바깥 누름은 따로 닫습니다. */
  const onPopBlur = (event: React.FocusEvent<HTMLDivElement>) => {
    const next = event.relatedTarget
    if (next instanceof Node) {
      if (!pop.current?.contains(next) && !button.current?.contains(next)) setOpen(false)
      return
    }
    window.setTimeout(() => {
      if (!document.hasFocus()) setOpen(false)
    }, 0)
  }

  const pick = (next: number) => {
    if (!desktop) return
    const bridge = zoomBridge()
    if (!bridge) return
    void bridge
      .set_zoom(next)
      .then((ok) => {
        if (ok) put(next)
      })
      .catch(() => {
        /* 바꾸지 못했으면 지금 배율 그대로 둡니다. */
      })
  }

  /* 라디오 묶음의 관례 — 화살표가 곧 고름이고, 끝에서 반대쪽 끝으로 돕니다. */
  const onRadioKey = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!desktop) return
    const at = current >= 0 ? current : stepIndex(1)
    const last = ZOOM_STEPS.length - 1
    let next: number | null = null
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = at >= last ? 0 : at + 1
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = at <= 0 ? last : at - 1
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = last
    if (next === null) return
    event.preventDefault()
    pick(ZOOM_STEPS[next].value)
    items.current[next]?.focus()
  }

  /* 네 단 밖의 배율이면 그 값을 먼저 적습니다. */
  const note = desktop
    ? `${current < 0 ? `지금 ${Math.round(value * 100)}% · ` : ''}${NOTE_DESKTOP}`
    : NOTE_BROWSER

  return (
    <>
      <button
        ref={button}
        type="button"
        className={`icon-btn text-size-btn${open ? ' is-open' : ''}`}
        onClick={() => setOpen((was) => !was)}
        aria-label="글씨 크기"
        title="글씨 크기"
        aria-expanded={open}
        aria-haspopup="dialog"
      >
        가
      </button>
      {open &&
        createPortal(
          <div
            ref={pop}
            className="text-size-pop"
            role="dialog"
            aria-label="글씨 크기"
            style={place && known ? { top: place.top, left: place.left } : { visibility: 'hidden' }}
            onBlur={onPopBlur}
          >
            <p className="text-size-title">글씨 크기</p>
            <div className="seg" role="radiogroup" aria-label="글씨 크기" onKeyDown={onRadioKey}>
              {ZOOM_STEPS.map((step, at) => {
                const checked = at === current
                const focusable = current >= 0 ? checked : step.value === 1
                return (
                  <button
                    key={step.value}
                    ref={(node) => {
                      items.current[at] = node
                    }}
                    type="button"
                    className="seg-item"
                    role="radio"
                    aria-checked={checked}
                    aria-disabled={desktop ? undefined : true}
                    aria-describedby={desktop ? undefined : noteId}
                    tabIndex={focusable ? 0 : -1}
                    onClick={() => pick(step.value)}
                  >
                    {step.label}
                  </button>
                )
              })}
            </div>
            <p className="text-size-note" id={noteId}>
              {note}
            </p>
          </div>,
          document.body,
        )}
    </>
  )
}
