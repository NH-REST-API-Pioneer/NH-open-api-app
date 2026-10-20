import type { Chart } from 'klinecharts'

/* ── 두 칸의 스크롤·확대 맞추기 ─────────────────────────── */

interface SyncEntry {
  id: number
  code: string
  chart: Chart
}

/** 같은 종목인 칸끼리 스크롤·확대를 전달합니다. 한 칸이 밀면 나머지가 따라갑니다. */
export class SyncHub {
  private entries: SyncEntry[] = []
  /* 지금 맞추고 있는 칸. 맞추는 동안 그 칸이 내는 스크롤·확대 액션은 이 코드가
     만든 것이라 다시 퍼뜨리지 않습니다. 퍼뜨리면 둘이 서로를 밀며 끝없이 돕니다. */
  private aligning = new Set<number>()
  /* 맞춘 칸마다 맞춘 자리(오른쪽 끝 봉 번호와 봉 폭). 그 칸에서 나중에 온 액션이
     이 자리 그대로면 맞춘 결과가 늦게 도착한 것이라 거르고, 다르면 사용자가 그
     칸을 직접 민 것이라 따라갑니다. 시간으로 거르지 않습니다 — 끄는 동안의
     움직임은 짧은 간격으로 몰려 오는데, 시간으로 막으면 첫 움직임 뒤의 것이
     버려져 두 칸이 어긋난 채로 남습니다. */
  private placed = new Map<number, { realTo: number; bar: number }>()

  register(id: number, code: string, chart: Chart): void {
    this.entries = this.entries.filter((entry) => entry.id !== id)
    this.entries.push({ id, code, chart })
    /* 종목·주기가 바뀌어 다시 등록되면 앞 자료에서 맞춘 자리는 더 맞지 않습니다. */
    this.placed.delete(id)
  }

  unregister(id: number): void {
    this.entries = this.entries.filter((entry) => entry.id !== id)
    this.placed.delete(id)
  }

  /* 한 칸을 다른 칸의 자리에 맞춥니다. 거리(상대값)가 아니라 자리(절대값)로
     맞춥니다 — 거리로 옮기면 처음 어긋난 만큼이 끝까지 남고, 마지막 봉 너머로
     민 자리는 거리로는 전해지지 않습니다.
     보이는 구간의 `realTo` 는 마지막 봉 너머까지 센 오른쪽 끝의 봉 번호라,
     그 번호를 오른쪽 끝에 두면 같은 자리가 됩니다. */
  private static align(source: Chart, target: Chart): void {
    const bar = source.getBarSpace().bar
    const sameBar = target.getBarSpace().bar === bar
    /* 이미 같은 자리면 손대지 않습니다. 맞춘 칸이 되돌려 보내는 액션은 `follow`
       가 맞춘 자리로 거르므로, 여기서는 한 봉 차이도 맞춥니다. */
    if (sameBar && source.getVisibleRange().realTo === target.getVisibleRange().realTo) return
    if (!sameBar) target.setBarSpace(bar)
    const want = source.getVisibleRange().realTo
    target.scrollToDataIndex(want - 1, 0)
    /* 라이브러리가 봉 번호를 오른쪽 끝에 두는 방식은 칸의 여백에 따라 한 봉쯤
       어긋날 수 있습니다. 놓인 자리를 다시 재서 그 차이만큼 한 번 더 옮깁니다 —
       남겨 두면 두 칸이 늘 한 봉씩 다르게 보입니다. */
    const miss = target.getVisibleRange().realTo - want
    if (miss !== 0) target.scrollToDataIndex(want - 1 - miss, 0)
  }

  /* 한 칸을 맞추고, 맞춘 자리를 적어 둡니다. 맞추는 동안 그 칸이 바로 내는
     액션은 `aligning` 으로 거릅니다. */
  private place(source: Chart, target: SyncEntry): void {
    this.aligning.add(target.id)
    try {
      SyncHub.align(source, target.chart)
    } finally {
      this.aligning.delete(target.id)
    }
    this.placed.set(target.id, SyncHub.spot(target.chart))
  }

  private static spot(chart: Chart): { realTo: number; bar: number } {
    return { realTo: chart.getVisibleRange().realTo, bar: chart.getBarSpace().bar }
  }

  /* 이 칸에서 온 액션이 앞서 맞춘 결과가 늦게 도착한 것인지. 봉 번호는 정수라
     그대로 견주고, 봉 폭은 소수라 아주 작은 차이는 같은 값으로 봅니다. */
  private echoed(id: number, chart: Chart): boolean {
    const placed = this.placed.get(id)
    if (!placed) return false
    const now = SyncHub.spot(chart)
    return Math.abs(now.bar - placed.bar) < 1e-6 && now.realTo === placed.realTo
  }

  /** 다른 같은 종목 칸의 자리를 이 칸에 맞춥니다. 칸이 새로 열리거나 종목이 바뀔 때 씁니다. */
  adopt(id: number): void {
    const target = this.entries.find((entry) => entry.id === id)
    const source = this.entries.find((entry) => entry.id !== id && entry.code === target?.code)
    if (!target || !source || this.aligning.has(id)) return
    this.place(source.chart, target)
  }

  /** 한 칸이 움직였습니다. 같은 종목인 나머지 칸을 그 자리에 맞춥니다. */
  follow(from: number): void {
    const source = this.entries.find((entry) => entry.id === from)
    if (!source || this.aligning.has(from)) return
    if (this.echoed(from, source.chart)) return
    /* 이 칸이 직접 움직였으니 이 칸에 적어 둔 자리는 더 쓰지 않습니다. */
    this.placed.delete(from)
    for (const entry of this.entries) {
      if (entry.id !== from && entry.code === source.code) this.place(source.chart, entry)
    }
  }
}
