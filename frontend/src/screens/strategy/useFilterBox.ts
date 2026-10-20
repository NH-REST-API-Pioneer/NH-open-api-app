import { useEffect, useRef, useState } from 'react'

/** 좁은 폭의 필터 상자 — 열고 닫기, 바깥 누름·Esc, 넓어지면 닫기. */
export function useFilterBox() {
  /* 좁은 폭의 필터 상자. 필터 열이 설 자리가 없으면(`strategy.css` 의 `stg`
     컨테이너 문턱) 목록 머리의 「필터」 단추가 이 상자를 엽니다. 칸은 필터 열과
     같은 것이고(`filterFields`), 값도 화면의 필터 상태 다섯 그대로입니다. */
  const [filterOpen, setFilterOpen] = useState(false)
  const filterWrapRef = useRef<HTMLSpanElement>(null)
  const filterButtonRef = useRef<HTMLButtonElement>(null)
  const filterFirstRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  /* 닫으면 초점을 단추로 돌려놓습니다 — 상자 안에 있던 초점이 사라진 칸에
     남으면 키보드로는 어디 있는지 모릅니다. */
  const closeFilter = () => {
    setFilterOpen(false)
    filterButtonRef.current?.focus()
  }

  useEffect(() => {
    if (!filterOpen) return
    filterFirstRef.current?.focus()
    /* 바깥은 **단추와 상자를 함께** 뺀 자리입니다 — 단추를 바깥으로 치면 열린 채
       단추를 누를 때 닫혔다가 곧바로 다시 열립니다. */
    const onDown = (event: MouseEvent) => {
      if (!filterWrapRef.current?.contains(event.target as Node)) closeFilter()
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        closeFilter()
      }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey, true)
    }
  }, [filterOpen])

  /* 넓어져 필터 열이 다시 서면 단추가 사라지므로 상자도 닫습니다. 문턱 수는
     스타일 한 자리에만 있어, 여기서는 단추가 보이는지로 압니다. 좁아질 때는
     상자를 저절로 열지 않습니다. */
  useEffect(() => {
    const box = listRef.current
    if (!box) return
    const watch = new ResizeObserver(() => {
      const button = filterButtonRef.current
      if (button && getComputedStyle(button).display === 'none') setFilterOpen(false)
    })
    watch.observe(box)
    return () => watch.disconnect()
  }, [])

  return { filterOpen, setFilterOpen, filterWrapRef, filterButtonRef, filterFirstRef, listRef, closeFilter }
}
