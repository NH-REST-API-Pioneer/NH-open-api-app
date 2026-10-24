import { INDICATOR_DEFS, indicatorDef, type IndicatorDef } from './chartIndicators'

/* 차트 지표 목록 밖에서 **등록해 쓰는 지표**.
 *
 * 기본 목록(`chartIndicators.ts`)은 일반주문 차트가 고르는 지표들이고, 여기 것은
 * 다른 화면이 제 계산으로 등록해 그 화면의 차트에만 켜는 지표입니다. 차트는 두
 * 목록을 함께 읽되, 설정에 없는 지표는 꺼진 것으로 봅니다 — 일반주문 차트의 설정에는
 * 이 지표들이 없어 그려지는 것이 그대로입니다.
 */

export interface ExtraIndicatorDef extends IndicatorDef {
  /** 계산에 종목 정보가 드는 지표(세션 경계 등)가 차트에서 받는 덧붙임 값. */
  extendOf?: (code: string) => unknown
}

const extras: ExtraIndicatorDef[] = []

/** 지표 하나를 목록에 더합니다. 같은 이름은 한 번만 더합니다. */
export function addExtraIndicator(def: ExtraIndicatorDef): void {
  if (!extras.some((one) => one.name === def.name)) extras.push(def)
}

/** 기본 목록과 등록한 지표를 합친 목록. 기본 목록이 앞입니다. */
export function allIndicatorDefs(): IndicatorDef[] {
  return [...INDICATOR_DEFS, ...extras]
}

/** 이름으로 찾습니다. 기본 목록에 없으면 등록한 지표에서 찾습니다. */
export function anyIndicatorDef(name: string): IndicatorDef | undefined {
  return indicatorDef(name) ?? extras.find((one) => one.name === name)
}

/** 등록한 지표의 덧붙임 값을 내는 함수. 없으면 `undefined` 입니다. */
export function extendOfIndicator(name: string): ((code: string) => unknown) | undefined {
  return extras.find((one) => one.name === name)?.extendOf
}
