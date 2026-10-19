import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'

/* 카드 머리의 「실시간 신청 필요」 꼬리표와 그 말풍선.
 *
 * 시세 사용 신청을 하지 않은 거래소의 종목은 서버가 실시간 등록을 거절합니다.
 * 그때 카드 머리의 시각 꼬리표 자리에 이 꼬리표가 섭니다. 조회로 받은 값이 있으면
 * 그 값의 시각을 앞에 붙여(「09:12 기준 · 실시간 신청 필요」) 값이 언제 것인지도
 * 함께 말합니다.
 *
 * **까닭과 할 일은 말풍선에 둡니다.** 카드 머리는 좁아 문장이 들어가지 않습니다.
 * 마우스를 올리거나 키보드로 초점을 옮기면 열리고, Esc 로 닫힙니다. 서버가 준
 * 원문은 화면에 세우지 않고 말풍선 끝의 코드에 마우스를 올리면 보입니다 — 원문은
 * 영어이거나 내부 표현이 섞여 있어, 그대로 세우면 사용자가 할 일보다 먼저 읽힙니다.
 *
 * **말풍선은 화면 기준 자리에 띄웁니다.** 호가 카드는 표가 옆 카드로 흐르지 않게
 * 제 안을 자르는데, 말풍선은 카드보다 넓어 카드 안에 두면 잘립니다. 그래서 열려
 * 있는 동안 화면이 스크롤되거나 창 크기가 바뀌면 말풍선을 닫습니다. 꼬리표 아래에
 * 자리가 모자라면 위로 엽니다.
 */

/** 말풍선 폭. 화면 끝에 닿으면 이 폭만큼 안쪽으로 당깁니다. */
const TIP_WIDTH = 300

/** 말풍선과 꼬리표 사이, 말풍선과 화면 끝 사이의 틈. */
const GAP = 6
const EDGE = 8

/** 꼬리표에서 말풍선으로 포인터를 옮기는 사이 닫히지 않게 기다리는 시간(ms). */
const LEAVE_DELAY = 150

interface Props {
  /** 조회로 받은 값의 시각(`HH:MM`). 없으면 비어 있습니다. */
  at: string
  /** 거래소 이름. 알면 말풍선에 「이 거래소(ICE)는」으로 섭니다. */
  exchange?: string
  /** NH선물이 준 오류 코드와 문구. */
  code: string
  message: string
}

export function RealtimeNeeded({ at, exchange, code, message }: Props) {
  const id = useId()
  const anchor = useRef<HTMLSpanElement>(null)
  const tip = useRef<HTMLSpanElement>(null)
  const timer = useRef<number | undefined>(undefined)
  const [open, setOpen] = useState(false)
  const [spot, setSpot] = useState<{ top: number; left: number } | null>(null)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  /* 꼬리표의 지금 자리에 맞춰 말풍선을 놓습니다. 오른쪽 끝을 꼬리표에 맞추고 화면
     왼쪽·오른쪽 끝을 넘지 않게 당깁니다. 아래에 들어가지 않으면 꼬리표 위로 엽니다. */
  const place = useCallback(() => {
    const box = anchor.current?.getBoundingClientRect()
    const height = tip.current?.offsetHeight ?? 0
    if (!box) return
    const left = Math.max(EDGE, Math.min(box.right - TIP_WIDTH, window.innerWidth - TIP_WIDTH - EDGE))
    const below = box.bottom + GAP
    const top =
      below + height > window.innerHeight - EDGE ? Math.max(EDGE, box.top - GAP - height) : below
    setSpot({ top, left })
  }, [])

  /* 열려 있는 동안만 화면의 움직임을 듣습니다. 스크롤이나 창 크기 변경이 오면
     말풍선을 닫습니다 — 꼬리표가 움직인 뒤 옛 자리에 남은 말풍선은 다른 카드 위에
     떠 있게 됩니다. 스크롤은 어느 상자에서 일어나도 꼬리표를 옮기므로 잡아 내리는
     단계에서 듣습니다. 초점은 꼬리표에 그대로 남습니다. */
  useLayoutEffect(() => {
    if (!open) {
      setSpot(null)
      return
    }
    place()
    const shut = () => setOpen(false)
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('scroll', shut, true)
    window.addEventListener('resize', shut)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('scroll', shut, true)
      window.removeEventListener('resize', shut)
      window.removeEventListener('keydown', onKey)
    }
  }, [open, place])

  const show = () => {
    window.clearTimeout(timer.current)
    setOpen(true)
  }
  const leave = () => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setOpen(false), LEAVE_DELAY)
  }
  const close = () => {
    window.clearTimeout(timer.current)
    setOpen(false)
  }

  return (
    <>
      <span
        ref={anchor}
        className="card-since card-realtime"
        tabIndex={0}
        aria-describedby={id}
        onMouseEnter={show}
        onMouseLeave={leave}
        onFocus={show}
        onBlur={close}
      >
        {at ? `${at} 기준 · ` : ''}실시간 신청 필요
      </span>
      {/* 자리를 재기 전 한 순간은 보이지 않게 둡니다 — 높이를 알아야 위아래를 정합니다. */}
      <span
        ref={tip}
        id={id}
        role="tooltip"
        className="card-realtime-tip"
        hidden={!open}
        style={
          spot
            ? { top: spot.top, left: spot.left, width: TIP_WIDTH }
            : { top: 0, left: 0, width: TIP_WIDTH, visibility: 'hidden' }
        }
        onMouseEnter={show}
        onMouseLeave={leave}
      >
        <span>이 거래소{exchange ? `(${exchange})` : ''}는 시세 사용 신청을 해야 실시간 시세를 받습니다.</span>
        <span className="card-realtime-tip-sub">
          HTS 9726 화면 또는 WTS 「실시간 시세신청」에서 신청할 수 있습니다.
        </span>
        {code && (
          <span className="card-realtime-tip-code" title={message || undefined}>
            NH 답 {code}
          </span>
        )}
      </span>
    </>
  )
}
