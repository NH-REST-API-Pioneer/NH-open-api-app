import { useEffect, useRef, type ReactNode } from 'react'

/* 화면 위에 뜨는 카드.
 *
 * 설정과 종목 담기가 함께 씁니다. 둘 다 「지금 하던 일을 멈추고 잠깐 다녀오는
 * 곳」이라, 화면을 갈아 끼우는 대신 그 자리에 뜹니다 — 갈아 끼우면 돌아올 때
 * 무엇을 보고 있었는지 다시 찾아야 합니다.
 *
 * 뒤를 어둡게 덮는 것은 밝은 화면에서만 일합니다. 어두운 화면은 바탕이 이미
 * 검어서 검정으로 덮어도 갈리지 않으므로, 카드가 떠 보이게 하는 것은 그림자가
 * 맡습니다. 그림자 색이 잉크 토큰이라 밝기에 따라 저절로 바뀝니다 — 밝은
 * 화면에서는 카드 아래 그늘, 어두운 화면에서는 카드 둘레 옅은 후광입니다.
 */

interface Props {
  /** 화면에 안 보이는 이름. 무엇이 열렸는지는 읽어 주는 쪽에도 있어야 합니다. */
  label: string
  onClose: () => void
  /** 머리 줄 왼쪽 — 탭이거나 제목 한 줄. */
  head: ReactNode
  /* 높이를 못 박습니다. 탭이 있는 모달은 고정해야 합니다 — 안 그러면 탭을
     바꿀 때 내용 길이만큼 카드가 뛰어서, 방금 누른 탭이 손가락 밑에서
     사라집니다. 접었다 펴는 칸이 있으면 한 탭 안에서도 같은 일이 납니다. */
  tall?: boolean
  /** 바깥을 눌러 닫을 수 있는지. 답을 받아야 하는 상태에서는 끕니다. */
  dismissable?: boolean
  /** 머리의 닫기(✕)를 둘지. **아래 단추 하나와 같은 일이면 뺍니다** — 첫
   *  초점이 그 ✕ 로 가는데, 창이 물은 것에 답하는 자리는 아래 단추입니다. */
  closable?: boolean
  /* 바깥을 눌렀는데 안 닫힐 때 초점을 옮길 곳. 카드를 흔들지 않습니다 —
     흔들림은 오류 신호인데 여기는 오류가 아니라 「여기서 답해야 한다」입니다. */
  guard?: React.RefObject<HTMLElement | null>
  children: ReactNode
}

/* 지금 떠 있는 모달 수. **세는 이유는 겹쳐 뜰 수 있기 때문입니다** — 하나가
 * 닫힐 때 표시를 지우면, 아직 떠 있는 다른 모달 뒤의 화면이 되살아납니다. */
let openCount = 0

/* 모달이 떠 있는 동안 뒤에 남는 **채운 단추**를 죽입니다.
 *
 * 뒷막이가 화면 전체를 덮고 초점도 카드 안에 갇히므로 뒤의 단추는 이미 못
 * 누릅니다. 그런데 초록 채움은 이 앱에서 「다음 걸음」이라, 못 누르는 단추가
 * 모달 안 단추와 같은 무게로 서면 한 화면에 다음 걸음이 둘이 됩니다.
 * 덮개를 더 진하게 해도 흰 바탕 위 초록은 원래 대비가 낮아 갈리지 않습니다.
 *
 * 그래서 표시를 몸통에 남기고, 채움은 CSS 가 벗깁니다(`app/shell.css`). */
function markOpen(): () => void {
  openCount += 1
  document.body.dataset.modalOpen = 'true'
  return () => {
    openCount -= 1
    if (openCount <= 0) {
      openCount = 0
      delete document.body.dataset.modalOpen
    }
  }
}

/** 초점이 갈 수 있는 것들. 순서는 화면에 놓인 순서 그대로입니다. */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function Modal({
  label,
  onClose,
  head,
  tall,
  dismissable = true,
  closable = true,
  guard,
  children,
}: Props) {
  const cardRef = useRef<HTMLDivElement>(null)
  /* 열기 전에 초점이 있던 곳. 닫을 때 그리로 되돌립니다 — 안 되돌리면 닫은
     뒤 Tab 을 눌렀을 때 초점이 문서 맨 앞으로 튑니다. */
  const openerRef = useRef<Element | null>(null)

  useEffect(() => {
    openerRef.current = document.activeElement
    const first = cardRef.current?.querySelector<HTMLElement>(FOCUSABLE)
    first?.focus()
    const unmark = markOpen()

    return () => {
      unmark()
      const opener = openerRef.current
      if (opener instanceof HTMLElement) opener.focus()
    }
  }, [])

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    /* Tab 은 카드 안에서만 돕니다. 밖으로 나가면 보이는 곳과 눌리는 곳이
       어긋나 — 화면은 카드를 가리키는데 Enter 는 뒤 화면의 단추를 누릅니다. */
    if (event.key !== 'Tab') return

    const items = [...(cardRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])]
    if (items.length === 0) return
    const first = items[0]
    const last = items[items.length - 1]
    const active = document.activeElement

    if (event.shiftKey && active === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && active === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target !== event.currentTarget) return
        if (dismissable) {
          onClose()
          return
        }
        guard?.current?.focus()
      }}
    >
      <div
        className={`modal${tall ? ' modal-tall' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        ref={cardRef}
        onKeyDown={onKeyDown}
      >
        <div className="modal-head">
          {head}
          {closable && (
            <button type="button" className="modal-close" aria-label="닫기" onClick={onClose}>
              ✕
            </button>
          )}
        </div>

        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}
