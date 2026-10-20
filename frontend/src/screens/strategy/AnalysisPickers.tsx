import { useEffect, useId, useRef, useState } from 'react'
import { setRecordFilters } from '../../data/strategyRecords'
import { curveNote } from './StrategyAnalysisParts'

/** 기간 칩에 적는 짧은 날짜 범위(「09.13 – 10.12」). 두 끝의 해가 다르면 시작
 *  날짜에만 해 두 자리를 붙입니다(「25.10.13 – 10.12」) — 달·일만으로는 시작이
 *  어느 해인지 모르고, 끝까지 붙이면 필터 줄이 한 줄에 들지 않습니다. 전체 날짜는
 *  칩에 올리면 보입니다. 날짜를 모르면 빈 글자입니다. */
export function shortRange(from: string, to: string): string {
  const parse = (date: string) => /^(\d{4})-(\d{2})-(\d{2})$/.exec(date)
  const start = parse(from)
  const end = parse(to)
  if (!start || !end) return ''
  const year = start[1] !== end[1] ? `${start[1].slice(2)}.` : ''
  return `${year}${start[2]}.${start[3]} – ${end[2]}.${end[3]}`
}

/** 「직접」 기간의 범위 단추. 날짜 칸 둘을 늘 세워 두면 필터 줄이 한 줄에 들지
 *  않으므로, 범위를 글자로 적은 단추 하나로 서고 누르면 날짜 칸 둘이 뜹니다.
 *
 *  - 단추를 누르면 열리고, 다시 누르기·Esc·바깥 클릭·초점이 둘 밖으로 나가면
 *    닫힙니다(곡선 읽는 법과 같은 규칙).
 *  - 날짜를 바꾸면 닫지 않고 바로 반영합니다 — 끝 날짜까지 이어서 고칠 수
 *    있습니다.
 *
 *  `from`·`to` 는 단추에 적을 범위(비었으면 서버가 정한 기간), `fromValue`·
 *  `toValue` 는 날짜 칸에 든 값입니다. */
export function RangePicker({
  from,
  to,
  fromValue,
  toValue,
}: {
  from: string
  to: string
  fromValue: string
  toValue: string
}) {
  const popId = useId()
  const btnRef = useRef<HTMLButtonElement>(null)
  const boxRef = useRef<HTMLSpanElement>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const onDown = (event: PointerEvent) => {
      if (boxRef.current?.contains(event.target as Node)) return
      setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      /* 날짜 칸에서 닫으면 초점이 갈 곳을 잃으므로 단추로 돌려 둡니다. */
      if (boxRef.current?.contains(document.activeElement)) btnRef.current?.focus()
      setOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const range = shortRange(from, to)
  const full = from && to ? `${from} ~ ${to}` : ''
  return (
    <span
      ref={boxRef}
      className="ana-range-box"
      onBlur={(event) => {
        if (!boxRef.current?.contains(event.relatedTarget as Node | null)) setOpen(false)
      }}
    >
      <button
        ref={btnRef}
        type="button"
        className="ana-range"
        aria-expanded={open}
        aria-controls={popId}
        aria-label={full ? `기간 ${full}, 날짜 고치기` : '날짜 고르기'}
        title={full || undefined}
        onClick={() => setOpen((now) => !now)}
      >
        <i className="ana-cal" aria-hidden="true" />
        {range || '날짜 고르기'}
      </button>
      {/* 날짜 칸이 아닌 자리를 눌러도 초점이 빠지지 않게 합니다 — 빠지면 그 자리에서
          닫힙니다. */}
      <div
        className="ana-range-pop"
        id={popId}
        role="group"
        aria-label="직접 기간"
        hidden={!open}
        onMouseDown={(event) => {
          if (!(event.target instanceof HTMLInputElement)) event.preventDefault()
        }}
      >
        <input
          className="control ana-date"
          type="date"
          aria-label="시작 날짜"
          value={fromValue}
          onChange={(event) => setRecordFilters({ from: event.target.value })}
        />
        <span aria-hidden="true">~</span>
        <input
          className="control ana-date"
          type="date"
          aria-label="끝 날짜"
          value={toValue}
          onChange={(event) => setRecordFilters({ to: event.target.value })}
        />
      </div>
    </span>
  )
}

/** 포인터가 단추·글을 떠난 뒤 글을 닫기까지 기다리는 시간(ms). 둘 사이 틈을
 *  지나가는 동안 닫히지 않을 만큼입니다. */
const HELP_LEAVE_MS = 150

/** 곡선 읽는 법. 곡선 오른쪽 아래, 날짜 축 줄 높이의 빈 바닥에 단추 하나로 서고
 *  글은 단추를 가리키거나 초점을 주면 곡선 위에 뜹니다. 글을 카드 흐름에 두지
 *  않아 곡선이 그만큼 높게 섭니다.
 *
 *  - 무엇을 쌓았는지는 단추 앞 꼬리표로 늘 보입니다(「실현 기준」·「평가 포함」).
 *    모르는 기준이면 꼬리표도, 그 문장도 지어 말하지 않습니다.
 *  - 마우스로 연 글은 포인터가 단추나 글 위에 있는 동안 열려 있고, 둘 다 벗어나면
 *    닫힙니다.
 *  - 클릭하면 열린 채로 남고, 다시 클릭·Esc·바깥 클릭·초점 이탈로 닫힙니다. */
export function CurveHelp({ totalLabel, basis, drawdown }: { totalLabel: string; basis: string; drawdown: boolean }) {
  const popId = useId()
  const btnRef = useRef<HTMLButtonElement>(null)
  const popRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [pinned, setPinned] = useState(false)
  /* 단추와 글 사이에는 틈이 있어, 단추를 떠나 글로 옮겨 가는 동안 바로 닫지 않고
     잠깐 기다립니다. 그 사이 단추나 글에 들어오면 닫기를 거둡니다. */
  const leaveTimer = useRef<number | undefined>(undefined)
  const stayOpen = () => {
    window.clearTimeout(leaveTimer.current)
    setOpen(true)
  }
  const leave = () => {
    if (pinned) return
    window.clearTimeout(leaveTimer.current)
    leaveTimer.current = window.setTimeout(() => setOpen(false), HELP_LEAVE_MS)
  }
  const close = () => {
    window.clearTimeout(leaveTimer.current)
    setPinned(false)
    setOpen(false)
  }

  useEffect(() => () => window.clearTimeout(leaveTimer.current), [])

  useEffect(() => {
    if (!open) return
    const onDown = (event: PointerEvent) => {
      const target = event.target as Node
      if (btnRef.current?.contains(target) || popRef.current?.contains(target)) return
      setPinned(false)
      setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setPinned(false)
      setOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const note = curveNote(basis)
  const tag = basis === 'realized' ? '실현 기준' : basis === 'equity' ? '평가 포함' : null
  return (
    <>
      <div className="ana-help">
        {tag && <span className="ana-help-tag">{tag}</span>}
        <button
          ref={btnRef}
          type="button"
          className="ana-help-btn"
          aria-expanded={open}
          aria-controls={popId}
          aria-describedby={open ? popId : undefined}
          onMouseEnter={stayOpen}
          onMouseLeave={leave}
          onFocus={stayOpen}
          onBlur={close}
          onClick={() => {
            window.clearTimeout(leaveTimer.current)
            const next = !pinned
            setPinned(next)
            setOpen(next)
          }}
        >
          <i className="ana-help-glyph" aria-hidden="true">
            i
          </i>
          곡선 읽는 법
        </button>
      </div>
      {/* 글 위를 눌러도 단추의 초점이 빠지지 않게 합니다 — 빠지면 그 자리에서 닫힙니다. */}
      <div
        ref={popRef}
        className="ana-help-pop"
        id={popId}
        role="tooltip"
        hidden={!open}
        onMouseEnter={stayOpen}
        onMouseLeave={leave}
        onMouseDown={(event) => event.preventDefault()}
      >
        <p className="ana-help-pop-title">곡선 읽는 법</p>
        <p className="ana-foot">곡선은 {totalLabel} 위에 고른 전략 하나만 올립니다</p>
        {note && <p className="ana-foot">{note}</p>}
        {drawdown && <p className="ana-foot">낙폭은 거래 차례로 셉니다</p>}
      </div>
    </>
  )
}
