import type { Bar } from '../../data/quotes'
import type { TradeMark } from '../trade/chartMarks'

/* 체결 표지를 **차트가 실제로 그리는 봉**에 앉힙니다.
 *
 * 표지의 자리는 봉이 정합니다 — 봉과 따로 잰 자리에 세우면 표지가 봉이 없는
 * 허공에 뜨거나, 봉 종류를 바꿀 때 봉과 다른 쪽으로 옮겨 갑니다. 그래서 봉은
 * 차트와 같은 곳(시세 저장소)에서 읽고, 그 시각을 덮는 봉이 없으면 표지를
 * 세우지 않습니다. 없는 자리를 지어내면 그 자리가 산 자리처럼 읽힙니다.
 */

/** 봉 하나가 덮는 시간(ms). 일봉은 한국시간 자정에서 시작합니다. */
export const SPAN_MS = { day: 86_400_000, minute: 60_000 } as const

export type Span = keyof typeof SPAN_MS

/** 이 시각이 든 봉. 봉 목록은 오래된 것부터입니다.
 *
 *  첫 봉 앞·마지막 봉 뒤·봉 사이의 빈 구간(장 마감 뒤, 세션 사이)이면
 *  `null` 입니다 — 가장 가까운 봉으로 당기면 마감 뒤 체결이 마감 봉에 앉아
 *  그때 난 것처럼 보입니다. */
export function barHolding(bars: readonly Bar[], time: number, span: Span): Bar | null {
  let found: Bar | null = null
  for (const bar of bars) {
    if (bar.timestamp > time) break
    found = bar
  }
  return found && time < found.timestamp + SPAN_MS[span] ? found : null
}

/** 같은 봉에 같은 방향으로 앉은 표지를 하나로 묶습니다.
 *
 *  봉 하나에 원을 여럿 포개면 겹친 만큼 안 보이고 누르는 것도 맨 위 하나뿐
 *  입니다. 묶은 표지는 수량과 건수를 더해 들고, 상세는 「N건 묶음」으로
 *  답합니다. 매수와 매도는 봉의 아래·위로 갈려 서므로 서로 묶지 않고,
 *  체결과 신호·주문도 모양이 다르므로 따로 둡니다. 진입과 청산도 따로입니다.
 *
 *  **가격은 수량 가중평균입니다.** 앞선 표지의 값을 그대로 들고 가면 그 가격에
 *  붙지 않은 수량까지 한 값에 달려, 표지가 일어나지 않은 거래를 말합니다. 수량이
 *  줄마다 있어 답이 하나인 셈이라 화면이 셉니다.
 *
 *  **평균은 호가 눈금 사이에 떨어질 수 있습니다** — 세 계약을 두 값에 나눠
 *  받으면 그 사이 어디든 나옵니다. 그 종목이 값을 적는 자릿수로 반올림하는 것은
 *  끝없는 소수를 끊는 것뿐이고, **눈금에 올리는 것이 아닙니다**(자릿수는 눈금보다
 *  잘 수 있습니다 — 눈금 0.05 인 종목의 자릿수가 2 입니다).
 *
 *  그래서 이 값을 주문가로 옮기는 길을 두지 않습니다 — 낼 수 없는 값이 주문
 *  칸에 들어갑니다. */
export function mergeMarks(marks: readonly TradeMark[]): TradeMark[] {
  const out: TradeMark[] = []
  const seen = new Map<string, TradeMark>()
  /* 평균을 낼 밑값. 묶인 표지의 `price` 는 반올림한 값이라 그것으로 다시
     평균을 내면 묶을 때마다 조금씩 밀립니다. */
  const weighed = new Map<string, { sum: number; qty: number }>()
  for (const mark of marks) {
    /* 진입과 청산은 다른 사건이라 묶지 않습니다 — 같은 봉·같은 방향이라도
       묶으면 머리는 앞 줄의 「진입」인데 까닭에 청산의 까닭이 섞입니다.
       가상·계좌 여부는 열쇠에 안 넣습니다 — 표지는 한 실행의 체결이고, 한
       실행은 한 갈래(앱 시뮬레이션 또는 모의 계좌)로만 돕니다. */
    const key = `${mark.time}|${mark.side}|${mark.kind}|${mark.intent}`
    const held = seen.get(key)
    if (!held) {
      const copy = { ...mark }
      seen.set(key, copy)
      weighed.set(key, { sum: mark.price * mark.qty, qty: mark.qty })
      out.push(copy)
      continue
    }
    held.qty += mark.qty
    held.count += mark.count
    /* 수수료는 더합니다. 한쪽이라도 칸이 없으면 합을 알 수 없어 비웁니다. */
    held.fee = held.fee === undefined || mark.fee === undefined ? undefined : held.fee + mark.fee
    /* 당시 지표는 **가장 이른 체결 하나**의 것입니다 — 다른 체결로 대신 채우지
       않습니다(그 체결이 옛 기록이거나 우리가 낸 주문이 아니면 절이 안 섭니다). */
    if (mark.firstAt !== undefined && (held.firstAt === undefined || mark.firstAt < held.firstAt)) {
      held.firstAt = mark.firstAt
      held.snapshot = mark.snapshot
      held.at = mark.at
    }
    /* 까닭은 더하지 않고 모읍니다 — 같은 까닭이 여럿이면 한 번만 둡니다. */
    for (const reason of mark.reasons ?? []) {
      if (!(held.reasons ?? []).includes(reason)) held.reasons = [...(held.reasons ?? []), reason]
    }
    const running = weighed.get(key)
    if (running) {
      running.sum += mark.price * mark.qty
      running.qty += mark.qty
      /* 수량이 0 인 줄만 묶였으면 나눌 수 없습니다 — 그때는 첫 값을 둡니다. */
      if (running.qty > 0) held.price = round(running.sum / running.qty, held.decimals)
    }
  }
  return out
}

/** 자릿수를 정해 반올림합니다. 자릿수를 모르면 그대로 둡니다. */
function round(value: number, decimals: number): number {
  if (!Number.isFinite(decimals) || decimals < 0) return value
  const scale = 10 ** decimals
  return Math.round(value * scale) / scale
}
