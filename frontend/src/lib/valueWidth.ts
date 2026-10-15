/** 값 칸이 잡아 둘 폭을 **그려 보고 정합니다.**
 *
 *  값이 설 자리는 그 품목이 낼 수 있는 가장 긴 값에 맞춰야 합니다. 지금 값에
 *  맞추면 값이 커질 때 칸이 넓어지면서 옆 칸이 전부 밀립니다.
 *
 *  「가장 긴 값」을 자릿수로 계산하지 않습니다. 자리 수가 늘수록 넓어지는 것이
 *  아니고(소수를 많이 쓰는 상품은 값 자체가 작습니다), 정수부 최댓값과 소수
 *  자릿수를 따로 더하면 **실제로는 없는 행**의 폭이 나옵니다. 그래서 마스터
 *  색인이 무리마다 진짜 행을 골라 보내고, 화면은 그 행을 제 표시 규칙으로
 *  그려서 잽니다.
 *
 *  **재는 자리마다 따로 잽니다.** 헤더와 표는 글꼴 크기가 달라 같은 값이라도
 *  폭이 다릅니다. 그래서 「어디서 재는지」를 열쇠에 넣고, 같은 자리·같은 무리는
 *  한 번만 잽니다.
 */
import { numberParts } from './number'
import { fractionOfProduct } from '../data/master'
import type { MasterIndex, WidthCandidate, WidthGroup } from '../data/master'

/** 화면이 부르는 이름(`domestic-day`·`domestic-night`·`overseas`)을 색인이
 *  나누는 축(`domestic`·`overseas`)으로. **낮과 밤은 같은 시장입니다** — 값을
 *  적는 규칙이 같아 폭도 같습니다. */
export function marketOf(context: string): string {
  return context.startsWith('domestic') ? 'domestic' : 'overseas'
}

/** 무리를 가리키는 열쇠. 색인이 나누는 축과 같습니다. */
export function groupKey(market: string, decimals: number, notation: string): string {
  return `${market}|${decimals}|${notation}`
}

/** 잰 폭. **0 은 안 담습니다** — 아직 화면에 안 선 자리에서 재면 0 이 나오는데,
 *  그것을 답으로 담아 두면 나중에 제대로 잴 수 있게 돼도 영영 0 입니다. */
const measured = new Map<string, number>()

/** 후보가 아예 없는 무리. 이건 다시 재도 결과가 같아 담아 둡니다. */
const absent = new Set<string>()

/** 후보 행을 그려 볼 자리.
 *
 *  화면에 안 보이지만 **값이 실제로 서는 자리와 같은 글꼴이어야** 합니다 —
 *  글꼴이 한 급만 달라도 잰 폭이 어긋나고, 좁게 나오면 값이 칸을 넘칩니다.
 *  그래서 값 칸 하나(`sample`)의 글꼴을 그대로 베껴 옵니다. 물려받기에
 *  기대지 않는 것은, 재는 자리가 값 칸의 부모라 규칙이 다를 수 있어서입니다. */
function stage(host: HTMLElement, sample: HTMLElement): HTMLElement {
  const box = host.ownerDocument.createElement('div')
  box.style.cssText =
    'position:absolute;visibility:hidden;pointer-events:none;white-space:nowrap;left:0;top:0'
  const from = host.ownerDocument.defaultView?.getComputedStyle(sample)
  if (from) {
    box.style.fontFamily = from.fontFamily
    box.style.fontSize = from.fontSize
    box.style.fontWeight = from.fontWeight
    box.style.fontStyle = from.fontStyle
    box.style.letterSpacing = from.letterSpacing
    box.style.setProperty('--frac-w', from.getPropertyValue('--frac-w'))
  }
  host.appendChild(box)
  return box
}

/** 후보 하나를 `Num` 과 같은 꼴로 그립니다. */
function draw(box: HTMLElement, candidate: WidthCandidate, group: WidthGroup, denominator: number | null): number {
  const value = Number(candidate.value)
  if (!Number.isFinite(value)) return 0
  const [int, frac] = numberParts(value, group.decimals, denominator)
  const d = box.ownerDocument
  const cell = d.createElement('span')
  cell.className = 'num-dec'
  const head = d.createElement('span')
  head.className = 'num-int'
  head.textContent = int
  const tail = d.createElement('span')
  tail.className = 'num-frac'
  tail.textContent = frac
  cell.append(head, tail)
  box.append(cell)
  const width = cell.getBoundingClientRect().width
  cell.remove()
  return width
}

/** 분수로 부르는 무리는 후보에 분모가 안 실려 옵니다 — 후보가 어느 종목에서
 *  왔는지로 그 종목 줄을 찾아, 거기 실린 가격표시방법으로 분모를 얻습니다. */
function denominatorOf(index: MasterIndex, code: string): number | null {
  const contract = index.contracts.find((row) => row.code === code)
  return fractionOfProduct(contract?.pind as string | undefined)
}

/** 이 자리에서 이 무리의 값 칸이 잡아야 할 폭(px). 후보가 없으면 `null`. */
export function valueWidthOf(
  host: HTMLElement | null,
  sample: HTMLElement | null,
  place: string,
  index: MasterIndex | null,
  market: string,
  decimals: number,
  notation: string,
): number | null {
  const key = `${place}|${groupKey(market, decimals, notation)}`
  const known = measured.get(key)
  if (known !== undefined) return known
  if (absent.has(key)) return null
  if (!host || !sample || !index?.width_candidates) return null

  const group = index.width_candidates.groups.find(
    (item) => item.market === market && item.decimals === decimals && item.notation === notation,
  )
  if (!group || group.candidates.length === 0) {
    absent.add(key)
    return null
  }

  const box = stage(host, sample)
  let widest = 0
  for (const candidate of group.candidates) {
    /* 분모는 **후보마다** 찾습니다. 한 무리 안에 분모가 다른 품목이 섞일 수
       있고(자릿수가 같아도 1/64 과 1/128 이 갈립니다), 분모가 다르면 `'` 뒤의
       글자 수가 달라집니다. */
    const denominator = notation === 'fraction' ? denominatorOf(index, candidate.code) : null
    widest = Math.max(widest, draw(box, candidate, group, denominator))
  }
  box.remove()

  /* 소수점 아래 자리는 CSS 가 `--frac-w` 로 잡아 두므로 그린 폭에 이미 들어
     있습니다. 소수점 위로 한 자리가 더 늘어날 일은 없습니다 — 이 값이 그
     무리의 가장 긴 행입니다. */
  /* 0 이면 아직 잴 수 있는 자리가 아닙니다 — 접혀 있거나 아직 안 그려진
     자리에서 재면 이렇게 나옵니다. 담지 않고 다음에 다시 잽니다. */
  const width = Math.ceil(widest)
  if (width <= 0) return null
  measured.set(key, width)
  return width
}

/** 시험이 자리를 비우고 다시 재게 합니다. */
export function forgetValueWidths(): void {
  measured.clear()
  absent.clear()
}
