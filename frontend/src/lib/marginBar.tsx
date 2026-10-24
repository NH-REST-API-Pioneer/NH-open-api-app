/* 증거금 셈 — 사용률, 돈의 흐름, 유지선까지 거리.
 *
 * 계좌의 증거금이 쓸 수 있는 돈 가운데 얼마를 묶고 있는지, 예탁자산이 어디로
 * 갔는지, 추가증거금이 생기는 선까지 얼마나 남았는지를 셉니다. **셈은 여기 한
 * 자리입니다** — 같은 계좌를 두고 화면마다 따로 셈하면 자리마다 다른 비율을
 * 말하게 됩니다. 그림은 쓰는 자리가 그립니다.
 *
 * 들어오는 값은 서버가 준 칸 그대로이고, 없으면 `null` 입니다. **없는 값을 0 으로
 * 셈하지 않습니다** — 0 은 「안 묶였다」는 말이고, 없는 것은 「모른다」입니다.
 */

const clamp = (value: number) => Math.min(Math.max(value, 0), 1)
const finite = (value: number | null): value is number => value !== null && Number.isFinite(value)

/** 증거금 사용률 = 위탁증거금 ÷ (위탁증거금 + 주문가능). [0, 1].
 *
 *  - 주문가능이 음수이거나 없으면 쓸 수 있는 돈이 없는 것이라, 증거금이 있으면 1 입니다.
 *  - 둘 다 0 이면 묶인 것이 없어 0 입니다.
 *  - 위탁증거금을 모르면 셀 수 없어 `null` 입니다 — 0 으로 두면 「안 묶였다」가 됩니다. */
export function marginUse(margin: number | null, orderable: number | null): number | null {
  if (!finite(margin)) return null
  const held = Math.max(margin, 0)
  if (!finite(orderable) || orderable < 0) return held > 0 ? 1 : 0
  const base = held + orderable
  return base > 0 ? clamp(held / base) : 0
}

/** 도넛에 그릴 사용률. `marginUse` 와 같은 값이되, **넘친 계좌는 전부 묶임**으로
 *  그립니다 — 주문가능이 음수이거나 위탁증거금이 예탁자산보다 크면 쓸 수 있는 돈이
 *  없는 것이라, 비율을 그대로 그리면 여유가 남은 것처럼 보입니다. `over` 가 참이면
 *  그리는 자리가 모자람을 따로 말합니다. */
export function usedShare(
  total: number | null,
  margin: number | null,
  orderable: number | null,
): { share: number | null; over: boolean } {
  const over =
    (finite(orderable) && orderable < 0) || (finite(margin) && finite(total) && margin > total)
  if (over) return { share: 1, over: true }
  return { share: marginUse(margin, orderable), over: false }
}

/** 흐름 막대의 폭 — 「예탁자산 − 위탁증거금 = 주문가능」의 둘째·셋째 줄. 폭은
 *  **서버 값 ÷ 예탁자산**이고 [0, 1] 로 자릅니다. 주문가능을 뺄셈으로 짓지
 *  않습니다 — 서버의 주문가능이 예탁 − 위탁과 다를 수 있고, 그 차이를 화면이
 *  메우면 서버가 말하지 않은 값이 섭니다. 값이 없으면 그 줄은 `null`(막대 없음)이고,
 *  예탁자산이 없거나 0 이하면 둘 다 `null` 입니다. */
export function flowShares(
  total: number | null,
  margin: number | null,
  orderable: number | null,
): { held: number | null; free: number | null; short: boolean; mismatch: number | null } {
  const base = finite(total) && total > 0 ? total : null
  /* 서버 주문가능이 예탁자산 − 위탁증거금과 **1원 넘게** 다르면 그 차이(절댓값)입니다.
     그때는 「=」로 잇지 않습니다 — 등호가 서면 서버가 말하지 않은 셈을 화면이 말하게
     됩니다. 까닭은 짓지 않습니다. 셋 중 하나라도 모르면 견줄 수 없어 `null` 입니다. */
  const gap =
    base !== null && finite(margin) && finite(orderable) ? Math.abs(base - margin - orderable) : null
  return {
    held: base !== null && finite(margin) ? clamp(margin / base) : null,
    free: base !== null && finite(orderable) ? clamp(orderable / base) : null,
    short: finite(orderable) && orderable < 0,
    mismatch: gap !== null && gap > 1 ? gap : null,
  }
}

/** 유지선까지 거리.
 *
 *  **거리 = 예탁자산 − 유지증거금**입니다. 예탁자산이 이만큼 줄면 유지증거금에 닿아
 *  추가증거금이 생깁니다. `mark` 는 유지증거금 표시선의 자리(예탁자산 대비, [0, 1]),
 *  `share` 는 거리가 예탁자산에서 차지하는 몫입니다.
 *
 *  - `none` — 유지증거금이 없거나 0 이하. 닿을 선이 없습니다.
 *  - `above` — 아직 선 위. `gap` 만큼 남았습니다.
 *  - `below` — 이미 선 아래. `gap` 만큼 모자랍니다.
 *  예탁자산이 없거나 0 이하면 셀 수 없어 `null` 입니다. */
export type KeepDistance =
  | { kind: 'none' }
  | { kind: 'above'; gap: number; share: number; mark: number }
  | { kind: 'below'; gap: number; mark: number }

export function keepDistance(total: number | null, maintenance: number | null): KeepDistance | null {
  if (!finite(total) || total <= 0) return null
  if (!finite(maintenance) || maintenance <= 0) return { kind: 'none' }
  const gap = total - maintenance
  if (gap < 0) return { kind: 'below', gap: -gap, mark: 1 }
  return { kind: 'above', gap, share: clamp(gap / total), mark: clamp(maintenance / total) }
}
