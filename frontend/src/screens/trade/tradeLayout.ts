/* 일반주문 화면의 패널 배치 — 카드 여섯이 슬롯 다섯 중 어디에 서고, 슬롯이 얼마나 큰가.
 *
 * 슬롯은 정해진 격자입니다: 왼쪽 열이 위아래 둘, 오른쪽 첫 열이 위아래 둘,
 * 맨 오른쪽이 두 줄을 통째로 씁니다. 격자 자체는 바뀌지 않습니다 — 자유
 * 배치는 되돌리기 어려운 화면을 만듭니다.
 *
 * **카드에는 칸 수가 있고, 같은 칸 수의 슬롯에만 섭니다.**
 *
 *   2칸(넓은 카드)  차트 · 주문체결상세 · 미결제약정 — 넓어지면 더 보입니다
 *   1칸(좁은 카드)  호가 · 시세체결 · 주문 폼 — 넓어져도 더 보이는 것이 없습니다
 *
 * 이 하나로 「호가가 차트 자리에 가서 이상해지는」 경우가 아예 안 생깁니다.
 * 카드마다 넓은 자리용·좁은 자리용을 따로 만들지 않아도 되고, 카드는 제
 * 모양을 지킨 채 격자가 카드를 따릅니다.
 *
 * **한 슬롯에 카드가 여럿 서면 그 슬롯은 탭이 됩니다.** 하나만 남으면 탭 줄이
 * 사라지고 카드 머리 띠가 곧 이름입니다.
 *
 * 크기는 슬롯이 아니라 카드에서 나옵니다. 좁은 열의 폭은 그 열에 선 카드들의
 * 바닥이 정하고 상한을 넘지 않으며, 넓은 열이 남는 폭을 다 씁니다. 행 높이도
 * 같습니다 — 위 슬롯은 제 카드의 바닥을 쓰고 **남는 높이는 아래 슬롯이**
 * 가집니다. 그래서 카드 안에 「덜 그려진」 빈 자리가 안 생깁니다.
 *
 * 경계를 끌면 **자리를 나눠 갖습니다.** 한 칸이 넓어진 만큼 이웃이 좁아지고,
 * 더 갈 곳이 없으면 그 자리에서 멈추고 말풍선이 회색이 됩니다.
 *
 * 두 열의 높이가 다르면 격자는 **더 높은 쪽**을 씁니다. 최소 창에서는 그만큼
 * 세로로 스크롤합니다 — 카드를 뭉개는 대신 미는 것이 이 화면의 확정
 * 동작입니다. 뭉개진 호가는 단계가 잘린 채로 값처럼 보입니다.
 *
 * 저장은 브라우저(localStorage)에 남고, 「기본 배치로」가 이 파일의 기본값으로
 * 되돌립니다. 저장된 값이 깨져 있으면 기본값으로 읽습니다.
 */

export type CardKey = 'chart' | 'orders' | 'positions' | 'book' | 'ticks' | 'form'

/** 슬롯 다섯. `lt`·`lb` 가 왼쪽 열의 위아래, `r1t`·`r1b` 가 오른쪽 첫 열의
 *  위아래, `r2` 가 맨 오른쪽 두 줄입니다. 이름의 `r1`·`r2` 는 저장해 둔 두
 *  열 폭(`r1Width`·`r2Width`)과 같은 열을 가리킵니다. */
export type SlotKey = 'lt' | 'lb' | 'r1t' | 'r1b' | 'r2'

/** 카드와 슬롯이 쓰는 칸 수. 같은 값끼리만 만납니다. */
export type Span = 1 | 2

/** 화면을 이루는 열 셋. 슬롯이 아니라 **열**을 통째로 옮기는 단위입니다. */
export type ColumnKey = 'wide' | 'narrow' | 'far'

export interface TradeLayout {
  /** 슬롯마다 어느 카드가 서는지. 여럿이면 그 슬롯은 탭이 되고, 앞이 처음 열리는 탭입니다. */
  slots: Record<SlotKey, CardKey[]>
  /** 어느 슬롯에도 안 서는 카드. 패널 편집에서 체크를 끈 것들입니다. */
  hidden: CardKey[]
  /** 오른쪽 첫째 열 폭(px) */
  r1Width: number
  /** 오른쪽 둘째 열 폭(px) */
  r2Width: number
  /** 왼쪽 열에서 **아래 슬롯**이 쓰는 높이(px). 위(차트)가 남는 만큼을 가집니다. */
  lbHeight: number
  /** 오른쪽 첫 열에서 **위 슬롯**이 쓰는 높이(px). 아래 슬롯이 남는 만큼입니다. */
  r1tHeight: number
  /** 열 셋이 왼쪽부터 서는 차례. 카드가 어느 열에 속하는지는 안 바뀝니다 —
   *  **열째로 자리를 옮기는 것**이라 그 안의 슬롯 구성은 그대로입니다. */
  columnOrder: ColumnKey[]
}

export const LAYOUT_KEY = 'nh.trade.layout'

export const CARDS: CardKey[] = ['chart', 'orders', 'positions', 'book', 'ticks', 'form']
export const SLOTS: SlotKey[] = ['lt', 'lb', 'r1t', 'r1b', 'r2']
export const COLUMNS: ColumnKey[] = ['wide', 'narrow', 'far']

/** 열마다 어느 슬롯이 있는지. 위에서 아래 차례입니다. */
export const COLUMN_SLOTS: Record<ColumnKey, SlotKey[]> = {
  wide: ['lt', 'lb'],
  narrow: ['r1t', 'r1b'],
  far: ['r2'],
}

/** 열 이름. 패널 편집의 「열 순서」 줄에 섭니다 — 자리가 바뀌면 「왼쪽」 같은
 *  이름은 거짓이 되므로, **그 열에 무엇이 서는지**로 부릅니다. */
export const COLUMN_LABEL: Record<ColumnKey, string> = {
  wide: '넓은 열',
  narrow: '호가 열',
  far: '주문 열',
}

export const CARD_LABEL: Record<CardKey, string> = {
  chart: '차트',
  orders: '주문체결상세',
  positions: '미결제약정',
  book: '호가',
  ticks: '시세체결',
  form: '주문',
}

/** 슬롯 이름. 패널 편집에서 「어느 자리」를 고를 때 씁니다.
 *
 *  **자리가 아니라 열의 내용으로 부릅니다** — 사용자가 열 순서를 바꾸면
 *  「왼쪽 위」 같은 이름은 그 자리에 있지 않은 것을 가리키게 됩니다. 열 이름
 *  (`COLUMN_LABEL`)과 같은 말을 써서 「열 순서」 줄과 이 셀렉트가 같은 것을
 *  가리키는지 눈으로 이을 수 있게 합니다. */
export const SLOT_LABEL: Record<SlotKey, string> = {
  lt: '넓은 열 위',
  lb: '넓은 열 아래',
  r1t: '호가 열 위',
  r1b: '호가 열 아래',
  r2: '주문 열',
}

/* 카드가 쓰는 칸 수. **넓어질 때 더 보여줄 것이 있는 카드가 2칸**입니다 —
 * 차트는 봉 수가, 주문체결상세는 종목 열이, 미결제약정은 펴지는 열이 늘어납니다.
 * 나머지 셋은 아무리 넓혀도 호가는 막대만, 시세체결은 가격 칸만 길어지고
 * 주문 폼은 셀렉트가 벌어질 뿐이라 1칸입니다.
 *
 * 이 표와 `CARD_MAX_WIDTH` 는 같은 사실의 두 얼굴입니다 — 상한이 있는 카드가
 * 1칸이고, 없는 카드가 2칸입니다. */
export const CARD_SPAN: Record<CardKey, Span> = {
  chart: 2,
  orders: 2,
  positions: 2,
  book: 1,
  ticks: 1,
  form: 1,
}

/** 슬롯이 받는 칸 수. 왼쪽 열이 넓은 자리, 오른쪽 둘이 좁은 자리입니다. */
export const SLOT_SPAN: Record<SlotKey, Span> = {
  lt: 2,
  lb: 2,
  r1t: 1,
  r1b: 1,
  r2: 1,
}

/** 이 카드가 저 자리에 설 수 있는지. 칸 수가 같아야 합니다. */
export function canPlace(card: CardKey, slot: SlotKey): boolean {
  return CARD_SPAN[card] === SLOT_SPAN[slot]
}

/** 못 서는 이유. 패널 편집에서 비활성 선택지 옆에 답니다 — **목록에서 빼지
 *  않습니다.** 빼면 그런 자리가 있다는 것 자체를 모르게 됩니다. */
export function placeReason(card: CardKey): string {
  return CARD_SPAN[card] === 2
    ? '이 카드는 넓은 자리에만 섭니다'
    : '이 카드는 좁은 자리에만 섭니다'
}

/* 없으면 주문을 낼 수 없는 카드. 체크를 끌 수 없습니다.
 *
 * 필수는 「없으면 못 하는 것」이고 선택은 「없으면 불편한 것」입니다. 호가가
 * 없으면 가격을 눌러 넣는 길 하나가 없어질 뿐 숫자 칸으로 넣을 수 있습니다.
 *
 * **막는 것은 「없어서 못 하는 것」이지 「어디에 두는가」가 아닙니다.** 주문
 * 폼을 다른 카드와 한 자리에 두어 탭 뒤로 보내는 것은 사용자의 선택이고,
 * 되돌리는 길(「기본 배치로」)이 한 번에 닿습니다. */
export const REQUIRED_CARD: CardKey = 'form'

/** 카드를 껐을 때 없어지는 것. 패널 편집에서 체크 아래에 답니다.
 *  「없어도 되는가」를 묻는 자리라, 답이 필요한 카드에만 답니다. */
export const CARD_HIDE_NOTE: Partial<Record<CardKey, string>> = {
  book: '가격을 눌러 넣는 길이 없어집니다',
  form: '주문을 낼 수 없어 끌 수 없습니다',
}

/* 카드의 바닥 크기. 폭은 그 카드가 좁은 열에 섰을 때 열 폭의 바닥이고,
 * 높이는 어느 칸에 서든 그 칸 높이의 바닥입니다.
 *
 * 값은 카드가 제 내용을 다 보여주는 데 실제로 드는 만큼입니다. 어림한 값을
 * 적어 두면 카드는 그 자리에 서기만 하고 안은 잘린 채가 됩니다.
 *
 * 높이가 담는 것:
 *
 *   차트   차트 칸 하나. 그 위에 봉 종류·지표 단추가 도구 줄로 섭니다
 *   주문체결상세  표 머리와 두 행. 폭은 좁은 열에서 쓰는 열 다섯(370)에 카드
 *          여백입니다 — 이보다 좁으면 구분과 정정·취소 사이에 한 열도 못
 *          지나가, 똑같이 생긴 행에 단추만 남습니다
 *   미결제약정  표 머리와 세 행. 폭 379 는 **동작(청산) 열 하나만 고정으로
 *          버티는 바닥**입니다. 고정 칸 셋(왼쪽 종목 — 좁은 배치는 구분까지 —,
 *          오른쪽 평가손익·동작)이 다 서려면 틀 안쪽이 그 셋에 가운데 창 96 을
 *          더한 폭이어야 합니다(잰 값: 좁은 배치 523, 넓은 배치 495). 그보다
 *          좁으면 표가 동작 열만 붙이고 나머지를 밉니다(`OrdersAndFills`) —
 *          청산 단추는 어느 폭에서도 온전히 섭니다
 *   호가   **312 는 다섯 단계씩 보이는 사다리를 실측한 값입니다.**
 *          띠 36 + 위 여백 6 + 열 이름 줄 22 + 사다리 235.5 + 아래 여백 12
 *          = 311.5 → 312.
 *          사다리 235.5 = 행 20 × 10(매도 다섯 · 매수 다섯) + 현재가 줄 29.5
 *          + **현재가 줄 위아래 여백 3 + 3**. 그 여백이 매도 구간과 매수
 *          구간을 가르는 자리라 빼면 두 구간이 맞붙습니다.
 *          응답은 열 단계씩 오지만 다섯씩만 세우는
 *          것은, 그 아래 시세체결이 같은 화면에 서야 하기 때문입니다 — 둘은
 *          같은 가격 축을 위아래로 읽는 짝이라, 한쪽을 보려고 다른 쪽을
 *          스크롤해야 하면 짝이 아닙니다. 이 아래로는 줄이는 단계가 없고
 *          열이 스크롤합니다
 *   시세체결  머리와 다섯 행. 폭 148 은 머리(「시세체결 · 13:41 부터」) 115 에
 *          여백 20 과 막대 13 을 더한 값입니다 — **행보다 머리가 넓어 머리가
 *          바닥을 정합니다.** 이 카드만 폭이 아니라 높이로 모양이 갈리므로,
 *          제 열에서 남는 높이는 이 카드가 가집니다
 *   주문   폼 한 벌. 셀렉트와 실행 단추까지 한 화면에 듭니다. 폭 240 은 **좁은
 *          폼**의 바닥입니다 — `FORM_ROOMY`(280)보다 좁으면 줄 이름이 입력칸
 *          위로 올라가고 실행 단추가 카드 아래에 붙박입니다. 끌기 바닥과 카드
 *          옮김 바닥을 같은 값으로 둡니다: 좁은 폼은 어느 자리에서도 240 에서
 *          온전히 서므로 둘을 가를 까닭이 없습니다
 *
 * 여기에 머리 비용이 얹힙니다 — 카드 머리 띠 36 + 본문 위 여백. 앞은 모두
 * 같고 뒤만 다릅니다(차트 10 · 표 8 · 호가 6 · 주문 12): 띠는 껍데기라 다
 * 같아야 하고, 본문 여백은 첫 줄이 무엇인지를 따릅니다.
 *
 * 띠의 36 에 구분선 1px 이 이미 들어 있습니다 — 전역이 `box-sizing: border-box`
 * 라 `height: 36px` 이 테두리까지 친 값입니다. 따로 더하면 안 됩니다.
 * **탭 줄은 따로 안 듭니다** — 여럿이 선 슬롯에서는 탭이 머리 띠 안에
 * 들어앉아 제목 자리를 대신합니다.
 *
 * 표 둘만 끝까지 세어 둔 값입니다:
 *   주문체결상세  36 + 8 + 표 머리 36 + 행 40 x 2 + 아래 여백 12 = 172
 *   미결제약정    36 + 8 + 표 머리 36 + 행 40 x 3 + 아래 여백 12 = 212
 * 나머지(차트·호가·주문)는 본문의 위아래 여백을 세지 않은 값이라 셋 다 실제보다
 * 20 남짓 낮습니다 — 바닥까지 밀린 카드는 그만큼 여백을 잃고 값은 잃지 않습니다.
 */
/* 차트의 폭 380 은 「읽을 수 있는 최소」입니다 — 그 아래에서 없어지는 것이
 * 「편함」이 아니라 「답」이 되는 지점입니다.
 *
 *   320  설정 단추가 카드 밖으로 나가 지표 설정에 못 들어갑니다
 *   360  도구 줄(320)에 본문 좌우 여백 40 을 더한 구조적 하한
 *   380  이 값. 시·고·저·종 라벨을 한 글자로 줄여 종가까지 세웁니다
 *
 * 도구 줄은 좁아져도 접히지 않고 넘칩니다. 그래서 360 아래는 폭이 아니라
 * 기능이 사라지는 자리입니다.
 *
 * 높이 355 는 판단값이 아니라 바닥입니다 — 기본 지표(이동평균선·거래량·MACD)
 * 상태에서 가격 103 + 거래량 43 + MACD 43 + 날짜축 26 이 드는 값입니다.
 * 여기서 내리면 날짜축이 사라지고 차트 칸이 제 안에서 스크롤합니다.
 *
 * 주문체결상세의 415 는 좁은 칸에서 쓰는 열 다섯(370)에 카드 좌우 여백 32 와
 * 표의 세로 막대 13 을 더한 값입니다. 막대 몫을 빼 두면 목록이 카드보다
 * 길어지는 순간 표가 가로로 밀려 「취소」 단추가 반쯤 가려집니다. */
export const CARD_MIN: Record<CardKey, { width: number; height: number }> = {
  chart: { width: 380, height: 355 },
  orders: { width: 415, height: 172 },
  positions: { width: 379, height: 212 },
  book: { width: 200, height: 312 },
  ticks: { width: 148, height: 140 },
  form: { width: 240, height: 355 },
}

/** 주문 폼이 줄 이름과 입력칸을 한 줄에 나란히 두는 폭(px). 이보다 좁으면 좁은
 *  폼으로 섭니다. 기본 배치의 주문 열 폭도 이 값입니다. */
export const FORM_ROOMY = 280

/* 좁은 카드의 폭 상한. 넓어져도 더 보이는 것이 없으니 여기서 멈춥니다.
 *
 * **조건은 슬롯이 아니라 폭입니다.** 카드가 자리를 옮겨 다니는 화면에서
 * 자리로 조건을 걸면, 같은 카드가 자리마다 다르게 굴러갑니다.
 *
 * 상한은 바닥에서 「한 자리 더 편한 만큼」입니다. 바닥은 잘리지 않는 값이고
 * 상한은 넉넉히 읽히는 값이라, 그 사이에서는 늘어나고 넘어가면 멈춥니다.
 *
 * **열 폭이 이 상한을 넘지 않게 계산하므로 카드 안에 남는 폭이 안 생깁니다.**
 * 남는 폭은 넓은 열이 가져갑니다. */
export const CARD_MAX_WIDTH: Partial<Record<CardKey, number>> = {
  book: 320,
  ticks: 200,
  form: 440,
}

/** 카드 사이 경계 트랙의 두께(px). 격자의 행·열 사이 간격이자 손잡이입니다. */
export const GUTTER = 12

/** 카드 머리 띠의 높이(px). 접힌 카드는 이 띠 하나가 카드의 전부입니다.
 *  `trade.css` 의 `.card-head` 와 같은 값이고, 구분선 1px 이 이미 들어 있습니다. */
export const HEAD_HEIGHT = 36

/** 주문체결상세가 표의 열 여섯을 다 펴는 데 드는 폭(px) — 표 543 + 카드 좌우
 *  여백 32 + 표의 세로 막대 13. 이보다 좁은 칸에 서면 열 묶음을 다시 짭니다
 *  (`trade.css` 의 `[data-narrow]`). **어느 자리냐가 아니라 얼마나 넓으냐를
 *  봅니다** — 넓은 열이 좁아졌든 어떻든 표가 겪는 일은 같습니다.
 *
 *  **넓은 열은 어떤 경계 끌기로도 제 카드 바닥(`leftMinWidth`, 기본 배치에서는
 *  주문체결상세의 415) 밑으로 안 내려갑니다.** 그래서 「끌다가 표가 깨지나」는
 *  물을 필요가 없습니다 — 미결제약정은 그 폭에서 청산 열 하나만 붙이고 밉니다.
 *  최근 본 패널을 열면 쓸 수 있는 폭이 패널만큼 줄어(앱 틀 1200 에서 952, 1187
 *  에서 939) 좁은 열이 상한에 닿기 전에 넓은 열의 바닥에서 멈춥니다
 *  (`columnMaxWidth`). */
export const ORDERS_WIDE = 588

/* 경계를 끌어도 이보다 커지지 않습니다. 한 열이 화면을 다 먹으면 나머지가
 * 밀려 나갑니다. */
const MAX_WIDTH = 720
const MAX_HEIGHT = 720

/* 기본 배치.
 *
 * 호가와 시세체결이 **같은 열에 위아래로** 섭니다 — 같은 가격 축을 위아래로
 * 읽는 둘이라, 한 자리에 탭으로 두면 그 관계가 없어집니다. 주문체결상세와
 * 미결제약정은 둘 다 내 주문의 결과이고 넓은 표라 한 자리의 탭입니다.
 *
 * 크기 기본값은 왼쪽 위 355(차트), 오른쪽 첫 열 위 312(호가), 좁은 열 폭
 * 200(호가 바닥)·280(주문 폼이 나란히 서는 폭 `FORM_ROOMY`). 주문 폼은 바닥
 * (240, 좁은 폼)이 아니라 나란한 폼으로 시작합니다 — 좁은 폼은 사용자가 경계를
 * 끌어 고르는 모양입니다. **312 는 배지가 없는 값**이라,
 * 2분할에서 호가에 종목 배지 줄이 서면 그만큼(`BOOK_SUBJECT_ROW`) 더합니다.
 *
 * **최소 창에서 이 배치는 세로로 밀립니다.** 왼쪽 열이 355 + 12 + 212 = 579 를
 * 부르는데 격자가 받는 것은 497 이라 82 가 모자랍니다. 오른쪽 첫 열은
 * 312 + 12 + 140 = 464 로 들어옵니다. 첫 화면에 차트와 호가가 온전히 서고
 * 시세체결·주문 내역·주문 폼의 아래가 잘립니다 — 카드를 뭉개는 대신 미는
 * 것이 확정 동작이고, 주문 실행 단추는 첫 화면 안에 남습니다. */
export const DEFAULT_LAYOUT: TradeLayout = {
  slots: {
    lt: ['chart'],
    lb: ['orders', 'positions'],
    r1t: ['book'],
    r1b: ['ticks'],
    r2: ['form'],
  },
  hidden: [],
  r1Width: CARD_MIN.book.width,
  r2Width: FORM_ROOMY,
  lbHeight: CARD_MIN.positions.height,
  r1tHeight: CARD_MIN.book.height,
  columnOrder: [...COLUMNS],
}

function clamp(value: unknown, min: number, max: number, fallback: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fallback
  return Math.min(max, Math.max(min, Math.round(value)))
}

function cloneSlots(slots: Record<SlotKey, CardKey[]>): Record<SlotKey, CardKey[]> {
  return {
    lt: [...slots.lt],
    lb: [...slots.lb],
    r1t: [...slots.r1t],
    r1b: [...slots.r1b],
    r2: [...slots.r2],
  }
}

/* 저장값 이행 — 저장된 배치의 판은 셋입니다.
 *
 *   v1  슬롯 넷, 자리마다 카드 이름 하나. 「주문 내역」 안에 주문체결상세와
 *       미결제약정이 탭으로 있고, 「호가」 카드 아래에 시세체결이 붙어
 *       있는 배치입니다. 그래서 옛 이름 하나를 갈라진 둘로 폅니다
 *   v2  슬롯 넷, 자리마다 카드 배열. 호가와 시세체결이 한 자리의 탭
 *   v3  지금. 오른쪽 첫 열이 위·아래 둘로 갈려 그 둘이 동시에 섭니다
 *
 * v1 은 v2 를 거쳐 옵니다. v2 → v3 은 `r1` 의 첫 카드가 위, 나머지가 아래로
 * 갑니다 — 기본값이었다면 호가가 위, 시세체결이 아래이고 사용자가 보던 것이
 * 그대로 섭니다. */
const SPLIT_FROM_V1: Record<string, CardKey[]> = {
  chart: ['chart'],
  orders: ['orders', 'positions'],
  book: ['book', 'ticks'],
  form: ['form'],
}

type SlotsV2 = { lt: CardKey[]; lb: CardKey[]; r1: CardKey[]; r2: CardKey[] }

function readV1(raw: Partial<Record<string, unknown>>): SlotsV2 | null {
  const out = {} as SlotsV2
  for (const slot of ['lt', 'lb', 'r1', 'r2'] as const) {
    const value = raw[slot]
    if (typeof value !== 'string') return null
    const cards = SPLIT_FROM_V1[value]
    if (!cards) return null
    out[slot] = [...cards]
  }
  return out
}

function readV2(raw: Partial<Record<string, unknown>>, isCard: (v: unknown) => v is CardKey): SlotsV2 | null {
  const out = {} as SlotsV2
  for (const slot of ['lt', 'lb', 'r1', 'r2'] as const) {
    const value = raw[slot]
    if (!Array.isArray(value)) return null
    out[slot] = value.filter(isCard)
  }
  return out
}

/* v2 의 한 열을 위·아래로 가릅니다. 첫 카드가 위입니다 — 그 자리에서 처음
 * 열려 있던 탭이 곧 사용자가 보던 카드라, 그것이 위로 와야 화면이 안 바뀝니다. */
function splitRightColumn(cards: CardKey[]): { top: CardKey[]; bottom: CardKey[] } {
  return { top: cards.slice(0, 1), bottom: cards.slice(1) }
}

/** 저장된 값을 화면이 쓸 수 있는 모양으로 고칩니다.
 *
 *  카드가 빠지거나 겹치면 기본 자리입니다 — **모든 슬롯의 합집합에 숨긴 것을
 *  더하면 카드 여섯이고 중복이 없어야** 하고, **칸 수가 안 맞는 자리에 선
 *  카드가 없어야** 합니다. 하나라도 어긋나면 어느 카드가 어디 있는지 답할 수
 *  없는 상태라, 고쳐 쓰는 것보다 기본으로 되돌리는 편이 낫습니다. 필수 카드가
 *  숨겨져 있는 값도 마찬가지입니다. */
export function normalizeLayout(raw: unknown): TradeLayout {
  const source = (raw && typeof raw === 'object' ? raw : {}) as Partial<TradeLayout>
  const rawSlots = (source.slots && typeof source.slots === 'object' ? source.slots : {}) as Partial<
    Record<string, unknown>
  >

  const isCard = (value: unknown): value is CardKey =>
    typeof value === 'string' && CARDS.includes(value as CardKey)

  let slots: Record<SlotKey, CardKey[]> | null = null
  if (SLOTS.every((slot) => Array.isArray(rawSlots[slot]))) {
    const built = {} as Record<SlotKey, CardKey[]>
    for (const slot of SLOTS) built[slot] = (rawSlots[slot] as unknown[]).filter(isCard)
    slots = built
  } else {
    const old = readV2(rawSlots, isCard) ?? readV1(rawSlots)
    if (old) {
      const right = splitRightColumn(old.r1)
      slots = { lt: old.lt, lb: old.lb, r1t: right.top, r1b: right.bottom, r2: old.r2 }
    }
  }

  const hidden = Array.isArray(source.hidden) ? source.hidden.filter(isCard) : []
  const placed = slots ? SLOTS.flatMap((slot) => slots![slot]) : []
  const all = [...placed, ...hidden]
  const spanOk =
    slots !== null && SLOTS.every((slot) => slots![slot].every((card) => canPlace(card, slot)))
  const valid =
    slots !== null &&
    spanOk &&
    all.length === CARDS.length &&
    new Set(all).size === CARDS.length &&
    !hidden.includes(REQUIRED_CARD)


  /* 열 순서는 **순열**이어야 합니다 — 셋이 한 번씩. 하나라도 빠지거나 겹치면
     어느 열이 어디 서는지 답할 수 없어 기본 차례로 돌립니다. */
  const rawOrder = Array.isArray(source.columnOrder) ? source.columnOrder : []
  const order = rawOrder.filter((key): key is ColumnKey => COLUMNS.includes(key as ColumnKey))
  const orderOk = order.length === COLUMNS.length && new Set(order).size === COLUMNS.length

  return {
    slots: valid ? slots! : cloneSlots(DEFAULT_LAYOUT.slots),
    hidden: valid ? hidden : [...DEFAULT_LAYOUT.hidden],
    r1Width: clamp(source.r1Width, 0, MAX_WIDTH, DEFAULT_LAYOUT.r1Width),
    r2Width: clamp(source.r2Width, 0, MAX_WIDTH, DEFAULT_LAYOUT.r2Width),
    lbHeight: clamp(source.lbHeight, 0, MAX_HEIGHT, DEFAULT_LAYOUT.lbHeight),
    r1tHeight: clamp(source.r1tHeight, 0, MAX_HEIGHT, DEFAULT_LAYOUT.r1tHeight),
    columnOrder: orderOk ? order : [...COLUMNS],
  }
}

/** 열 하나를 한 칸 옮깁니다. 끝에서 더 가면 아무 일도 안 합니다 —
 *  돌아 넘어가면 「끝까지 갔다」는 것을 누르고 나서야 알게 됩니다. */
export function moveColumn(layout: TradeLayout, column: ColumnKey, by: -1 | 1): TradeLayout {
  const order = [...layout.columnOrder]
  const at = order.indexOf(column)
  const to = at + by
  if (at < 0 || to < 0 || to >= order.length) return layout
  order[at] = order[to]
  order[to] = column
  return { ...layout, columnOrder: order }
}

/** 카드가 선 슬롯. 숨긴 카드는 어디에도 안 서므로 `null` 입니다. */
export function slotOf(layout: TradeLayout, card: CardKey): SlotKey | null {
  return SLOTS.find((slot) => layout.slots[slot].includes(card)) ?? null
}

/** 카드가 지금 보이는지. */
export function isVisible(layout: TradeLayout, card: CardKey): boolean {
  return !layout.hidden.includes(card)
}

/** 그 카드가 갈 수 있는 자리들. 칸 수가 같은 슬롯뿐입니다. */
export function slotsFor(card: CardKey): SlotKey[] {
  return SLOTS.filter((slot) => canPlace(card, slot))
}

/** 두 슬롯의 내용을 통째로 맞바꿉니다.
 *
 *  **손잡이 ⠿ 가 하는 일입니다.** 머리 띠는 그 슬롯에 선 것 전체를 가리키므로
 *  — 여럿이 서 있으면 띠가 탭 줄입니다 — 손잡이를 끌어 옮기는 것은 「이 자리와
 *  저 자리를 바꾼다」입니다. 묶음에서 카드 하나만 빼는 것은 자리 바꾸기가
 *  아니라 「무엇을 어디에 둘지」라, 패널 편집의 슬롯 셀렉트가 맡습니다.
 *
 *  **칸 수가 같은 자리끼리만 바뀝니다.** 넓은 카드가 좁은 자리에 서는 일이
 *  없어야 카드마다 자리별 모양을 따로 만들지 않아도 됩니다. */
export function swapSlots(layout: TradeLayout, a: SlotKey, b: SlotKey): TradeLayout {
  if (a === b || SLOT_SPAN[a] !== SLOT_SPAN[b]) return layout
  const slots = cloneSlots(layout.slots)
  const keep = slots[a]
  slots[a] = slots[b]
  slots[b] = keep
  return { ...layout, slots }
}

/** 카드 하나를 다른 슬롯으로 옮깁니다. 있던 자리에서 빠지고 받는 슬롯의 끝에
 *  섭니다 — 끝에 두면 그 슬롯에서 처음 열리는 탭이 안 바뀌어, 옮긴 카드가
 *  보고 있던 것을 밀어내지 않습니다. 숨긴 카드였으면 다시 보이게 됩니다.
 *  칸 수가 안 맞으면 아무 일도 안 합니다. */
export function moveCard(layout: TradeLayout, card: CardKey, to: SlotKey): TradeLayout {
  if (!canPlace(card, to)) return layout
  const slots = cloneSlots(layout.slots)
  for (const slot of SLOTS) slots[slot] = slots[slot].filter((key) => key !== card)
  slots[to] = [...slots[to], card]
  return { ...layout, slots, hidden: layout.hidden.filter((key) => key !== card) }
}

/** 카드를 숨깁니다. 필수 카드는 숨겨지지 않습니다. */
export function hideCard(layout: TradeLayout, card: CardKey): TradeLayout {
  if (card === REQUIRED_CARD || layout.hidden.includes(card)) return layout
  const slots = cloneSlots(layout.slots)
  for (const slot of SLOTS) slots[slot] = slots[slot].filter((key) => key !== card)
  return { ...layout, slots, hidden: [...layout.hidden, card] }
}

/** 숨긴 카드를 다시 세웁니다. 기본 배치에서 그 카드가 서던 슬롯으로 갑니다 —
 *  마지막으로 있던 자리를 따로 기억하지 않습니다. 저장값에 자리를 하나 더
 *  들이면 그 값이 어긋났을 때 배치 전체를 버려야 합니다. */
export function showCard(layout: TradeLayout, card: CardKey): TradeLayout {
  if (!layout.hidden.includes(card)) return layout
  const home = SLOTS.find((slot) => DEFAULT_LAYOUT.slots[slot].includes(card)) ?? slotsFor(card)[0]
  const slots = cloneSlots(layout.slots)
  slots[home] = [...slots[home], card]
  return { ...layout, slots, hidden: layout.hidden.filter((key) => key !== card) }
}

/* 슬롯 사이의 이웃. 키보드로 옮길 때 화살표 방향이 가리키는 슬롯입니다.
 * **칸 수가 같은 자리만 돕니다** — 손잡이·모달과 같은 규칙이라, 키보드로만
 * 갈 수 있는 자리가 생기지 않습니다. */
const NEIGHBOR: Record<SlotKey, Partial<Record<'left' | 'right' | 'up' | 'down', SlotKey>>> = {
  lt: { down: 'lb' },
  lb: { up: 'lt' },
  r1t: { down: 'r1b', right: 'r2' },
  r1b: { up: 'r1t', right: 'r2' },
  r2: { left: 'r1t' },
}

export function neighborSlot(slot: SlotKey, direction: 'left' | 'right' | 'up' | 'down'): SlotKey | null {
  return NEIGHBOR[slot][direction] ?? null
}

/** 슬롯의 바닥 폭. 거기 선 카드들 중 가장 넓은 바닥입니다.
 *
 *  **빈 슬롯은 0 입니다.** 카드를 다 끄면 그 자리는 없는 것이라, 폭도 경계도
 *  0 이 되어 격자에서 사라집니다 — 빈 칸을 남겨 두면 왜 비었는지 알 수 없는
 *  구멍이 생기고, 그 옆 경계는 아무것도 나누지 않는 손잡이가 됩니다. */
export function slotMinWidth(layout: TradeLayout, slot: SlotKey): number {
  const cards = layout.slots[slot]
  if (cards.length === 0) return 0
  return Math.max(...cards.map((card) => CARD_MIN[card].width))
}

/** 슬롯의 바닥 높이. 거기 선 카드들 중 가장 높은 바닥입니다.
 *
 *  **보이는 탭이 아니라 그 슬롯 전체의 최대로 잽니다.** 보이는 카드로 재면
 *  탭을 바꿀 때마다 격자가 움직여, 값을 보러 누른 탭이 화면을 흔듭니다. */
export function slotMinHeight(layout: TradeLayout, slot: SlotKey): number {
  const cards = layout.slots[slot]
  if (cards.length === 0) return 0
  return Math.max(...cards.map((card) => CARD_MIN[card].height))
}

/** 호가 카드에 종목 배지가 설 때 늘어나는 줄 높이(줄 20 + 아래 여백 6).
 *
 *  **2분할에서는 두 칸이 서로 다른 종목일 수 있습니다.** 그래서 호가가 지금
 *  어느 종목의 것인지 제 카드 안에서 말해야 하고, 그 줄이 하나 더 섭니다.
 *
 *  카드 바닥에 이 줄을 더하지 않으면 사다리가 카드를 넘습니다. 카드는
 *  `overflow: hidden` 이라 넘친 만큼을 **말없이 잘라 내므로**, 넘쳤다는 표시도
 *  스크롤도 없이 **매수 다섯째 단이 사라집니다.** */
export const BOOK_SUBJECT_ROW = 26

/** 그 상태에서 슬롯이 가지는 바닥.
 *
 *  `CARD_MIN.book.height`(312)는 **배지가 없는 값**이라, 배지가 선 호가는
 *  그만큼 더 큽니다. 바닥만 오르고 **저장값은 그대로**입니다 — 2분할을 끄면
 *  카드는 저절로 제 크기로 돌아옵니다. */
export function slotFloor(layout: TradeLayout, slot: SlotKey, subject = false): number {
  const base = slotMinHeight(layout, slot)
  if (!subject || !layout.slots[slot].includes('book')) return base
  return base + BOOK_SUBJECT_ROW
}

/** 슬롯의 상한 폭. 좁은 슬롯은 늘 상한이 있고(좁은 카드만 서므로), 넓은
 *  슬롯은 없습니다. 값은 상한들 중 큰 쪽입니다 — 작은 쪽에 맞추면 같은 자리에
 *  선 다른 카드가 제 상한에 못 미친 채로 섭니다. */
export function slotMaxWidth(layout: TradeLayout, slot: SlotKey): number {
  const cards = layout.slots[slot]
  if (cards.length === 0) return Number.POSITIVE_INFINITY
  const caps = cards.map((card) => CARD_MAX_WIDTH[card])
  if (caps.some((cap) => cap === undefined)) return Number.POSITIVE_INFINITY
  return Math.max(...(caps as number[]))
}

/** 슬롯이 비어 격자에서 빠지는지. */
export function isSlotEmpty(layout: TradeLayout, slot: SlotKey): boolean {
  return layout.slots[slot].length === 0
}

/** 오른쪽 첫 열이 통째로 비었는지. 위아래 둘 다 비면 그 열이 없어집니다. */
export function isColumnEmpty(layout: TradeLayout, column: 'r1' | 'r2'): boolean {
  return column === 'r2'
    ? isSlotEmpty(layout, 'r2')
    : isSlotEmpty(layout, 'r1t') && isSlotEmpty(layout, 'r1b')
}

/** 좁은 열의 바닥 폭 — 그 열에 선 카드들 전체의 바닥 최대입니다. 오른쪽 첫
 *  열은 위아래 두 슬롯이 한 열을 쓰므로 둘을 합쳐 봅니다. */
export function columnMinWidth(layout: TradeLayout, column: 'r1' | 'r2'): number {
  return column === 'r2'
    ? slotMinWidth(layout, 'r2')
    : Math.max(slotMinWidth(layout, 'r1t'), slotMinWidth(layout, 'r1b'))
}

/** 좁은 열의 상한 폭. */
export function columnMaxCap(layout: TradeLayout, column: 'r1' | 'r2'): number {
  if (column === 'r2') return slotMaxWidth(layout, 'r2')
  const caps = [slotMaxWidth(layout, 'r1t'), slotMaxWidth(layout, 'r1b')].filter(
    (cap) => Number.isFinite(cap),
  )
  return caps.length === 0 ? Number.POSITIVE_INFINITY : Math.max(...caps)
}

/** 좁은 열의 실제 폭. 저장값을 바닥과 상한 사이에 둡니다. 비어 있으면 0 입니다. */
export function columnWidth(layout: TradeLayout, column: 'r1' | 'r2'): number {
  if (isColumnEmpty(layout, column)) return 0
  const stored = column === 'r1' ? layout.r1Width : layout.r2Width
  const min = columnMinWidth(layout, column)
  const cap = Math.min(MAX_WIDTH, columnMaxCap(layout, column))
  return Math.min(Math.max(stored, min), Math.max(min, cap))
}

/** 넓은 열의 바닥 폭. 위아래 두 칸 중 넓은 쪽입니다. */
export function leftMinWidth(layout: TradeLayout): number {
  return Math.max(slotMinWidth(layout, 'lt'), slotMinWidth(layout, 'lb'))
}

/** 그 열이 통째로 비었는지. */
export function columnEmpty(layout: TradeLayout, column: ColumnKey): boolean {
  return COLUMN_SLOTS[column].every((slot) => isSlotEmpty(layout, slot))
}

/** 격자의 열 트랙 — 저장된 차례대로 폭 셋과 그 사이 경계 둘입니다.
 *
 *  경계는 **나눌 것이 양쪽에 있을 때만** 섭니다. 한쪽이 비면 아무것도 안
 *  나누는 손잡이가 되고, 끌면 빈 자리만 넓어집니다. 가운데 열이 비면 그 앞의
 *  경계도 사라지고, 남은 두 열 사이의 경계 하나만 섭니다.
 *
 *  넓은 열은 폭이 `null` 입니다 — 남는 것을 다 쓰므로 값이 아니라 「나머지」로
 *  적힙니다. */
export function columnTracks(
  layout: TradeLayout,
): { column: ColumnKey; width: number | null; empty: boolean }[] {
  return layout.columnOrder.map((column) => ({
    column,
    empty: columnEmpty(layout, column),
    width:
      column === 'wide' ? null : columnWidth(layout, column === 'narrow' ? 'r1' : 'r2'),
  }))
}

/** 열 트랙 사이의 경계 둘. 왼쪽에 선 것이 하나라도 있고 오른쪽 열이 비지
 *  않았을 때만 섭니다. */
export function columnGaps(layout: TradeLayout): [number, number] {
  const tracks = columnTracks(layout)
  const gap = (at: number) =>
    tracks.slice(0, at + 1).some((t) => !t.empty) && !tracks[at + 1].empty ? GUTTER : 0
  return [gap(0), gap(1)]
}

/** 넓은 열이 실제로 받는 폭 — 지금 쓸 수 있는 폭에서 좁은 열 둘과 경계를 뺀
 *  나머지입니다. 창을 아직 재지 못했으면 제 바닥만큼으로 봅니다.
 *
 *  **좁은 열이 상한에서 멈추므로 남는 폭은 전부 여기로 옵니다.** */
export function wideWidth(layout: TradeLayout, usable: number): number {
  const [g1, g2] = columnGaps(layout)
  const rest = usable - g1 - g2 - columnWidth(layout, 'r1') - columnWidth(layout, 'r2')
  return Math.max(wideFloor(layout, usable), Number.isFinite(usable) && usable > 0 ? rest : 0)
}

/** 한 열을 끌 때 갈 수 있는 끝. 옆 열은 그대로 두고 넓은 열이 제 바닥에
 *  닿는 데서 멈추며, 그 전에 제 상한에서 먼저 멈춥니다. 한계는 지금 열 폭과
 *  무관합니다 — 끌어서 간 자리는 끌어서 돌아올 수 있어야 합니다. */
export function columnMaxWidth(layout: TradeLayout, column: 'r1' | 'r2', usable: number): number {
  const other = columnWidth(layout, column === 'r1' ? 'r2' : 'r1')
  const [g1, g2] = columnGaps(layout)
  const room = Number.isFinite(usable) && usable > 0
    ? usable - g1 - g2 - leftMinWidth(layout) - other
    : Number.POSITIVE_INFINITY
  const cap = Math.min(MAX_WIDTH, columnMaxCap(layout, column))
  return Math.max(columnMinWidth(layout, column), Math.min(cap, room))
}

/** 창에 맞출 때 저절로 줄여 가는 바닥. 주문 폼이 선 열은 나란한 폼 폭
 *  (`FORM_ROOMY`)까지만 저절로 줄입니다 — 좁은 폼은 사용자가 경계를 끌어 고르는
 *  모양이라, 창이 좁다고 저절로 좁은 폼이 되면 기본 배치가 바뀝니다. 사용자가
 *  그보다 좁게 끌어 둔 폭은 그 폭이 바닥입니다. */
function fitFloor(layout: TradeLayout, column: 'r1' | 'r2', width: number): number {
  const min = columnMinWidth(layout, column)
  const slots: SlotKey[] = column === 'r2' ? ['r2'] : ['r1t', 'r1b']
  if (!slots.some((slot) => layout.slots[slot].includes('form'))) return min
  return Math.max(min, Math.min(FORM_ROOMY, width))
}

/** 저장해 둔 폭을 지금 창에 맞춥니다.
 *
 *  들어가면 그대로 쓰고, 모자라면 두 열이 **비율대로** 함께 줄어듭니다 — 한쪽만
 *  깎으면 창을 조금 줄였을 뿐인데 호가나 주문 폼 한쪽이 통째로 바닥까지
 *  내려앉습니다. 저장한 값은 건드리지 않으므로 창을 다시 넓히면 원래 폭으로
 *  돌아옵니다.
 *
 *  둘 다 그 바닥에 닿아도 모자라면(최근 본 패널을 연 좁은 창이나 글자 크기를
 *  키운 창), 주문 폼이 선 열은 좁은 폼의 폭까지 더 줄어듭니다. 그래도 모자라는
 *  만큼은 넓은 열이 정해진 끝까지 내놓습니다(`wideFloor`). 화면이 옆으로
 *  밀리면 주문 폼의 오른쪽이 잘려 실행 단추가 반쯤 가려지기 때문입니다.
 *
 *  세로에는 같은 것을 하지 않습니다. 높이가 모자랄 때는 카드를 줄이는 대신
 *  격자가 세로로 스크롤합니다 — 뭉갠 호가는 단계가 잘린 채로 값처럼 보이고,
 *  줄어든 주문 내역은 마지막 행을 글자 중간에서 자릅니다. */
export function fitLayout(layout: TradeLayout, usable: number): TradeLayout {
  if (!Number.isFinite(usable) || usable <= 0) return layout
  const w1 = columnWidth(layout, 'r1')
  const w2 = columnWidth(layout, 'r2')
  const min1 = fitFloor(layout, 'r1', w1)
  const min2 = fitFloor(layout, 'r2', w2)
  const [g1, g2] = columnGaps(layout)
  const room = usable - g1 - g2 - leftMinWidth(layout)
  if (w1 + w2 <= room) return layout
  const spare = room - min1 - min2
  if (spare < 0) {
    /* 나란한 폼의 폭까지 줄여도 모자랍니다. 이번에는 열의 바닥(좁은 폼)까지
       같은 비율로 줄입니다. */
    const floor1 = columnMinWidth(layout, 'r1')
    const floor2 = columnMinWidth(layout, 'r2')
    const left = room - floor1 - floor2
    const give = min1 - floor1 + (min2 - floor2)
    const squeeze = left > 0 && give > 0 ? Math.min(1, left / give) : 0
    return {
      ...layout,
      r1Width: floor1 + Math.floor((min1 - floor1) * squeeze),
      r2Width: floor2 + Math.floor((min2 - floor2) * squeeze),
    }
  }
  const extra = w1 - min1 + (w2 - min2)
  const ratio = extra > 0 ? spare / extra : 0
  return {
    ...layout,
    r1Width: min1 + Math.floor((w1 - min1) * ratio),
    r2Width: min2 + Math.floor((w2 - min2) * ratio),
  }
}

/** 넓은 열이 좁은 창에서 내려갈 수 있는 끝(px). 차트의 도구 줄(일·분, 지표
 *  다섯, 설정)이 한 줄에 다 들어가는 폭입니다. 이보다 좁으면 설정 단추부터
 *  카드 밖으로 잘려 누를 수 없게 되므로, 그때는 더 줄이지 않고 화면이 옆으로
 *  밀립니다. 주문 내역 표는 이 폭에서 제 안에서 옆으로 밀려 열이 다 남습니다. */
const WIDE_SQUEEZE_MIN = 340

/** 넓은 열이 지금 서는 바닥. 평소에는 제 카드의 바닥(`leftMinWidth`)이고, 좁은
 *  열 둘이 끝까지 줄어도(`fitLayout`) 모자라는 창에서만 남는 폭까지 내려갑니다 —
 *  격자가 화면보다 넓어져 옆으로 밀리면 주문 폼의 오른쪽이 잘리는데, 차트와
 *  주문 내역은 좁게 서도 값을 읽을 수 있습니다. 주문 내역은 좁은 칸에서 열
 *  묶음을 다시 짜고(`ORDERS_WIDE`), 차트는 제 폭에 맞춰 도구 줄을 줄입니다.
 *  내려가는 끝은 `WIDE_SQUEEZE_MIN` 입니다.
 *
 *  창을 아직 재지 못했으면 제 바닥 그대로입니다. */
export function wideFloor(layout: TradeLayout, usable: number): number {
  const floor = leftMinWidth(layout)
  if (!Number.isFinite(usable) || usable <= 0) return floor
  const [g1, g2] = columnGaps(layout)
  const rest = usable - g1 - g2 - columnWidth(layout, 'r1') - columnWidth(layout, 'r2')
  return Math.min(floor, Math.max(WIDE_SQUEEZE_MIN, rest))
}

/* ── 행 높이 ─────────────────────────────────────────────
 *
 * **세로로 늘어나는 카드는 차트뿐입니다.** 차트는 높이를 주면 봉의 위아래가
 * 펴져 값을 더 보여줍니다. 표는 행이 몇 줄 더 보일 뿐이고, 호가는 다섯
 * 단계씩으로 못 박혀 있어 아무것도 안 늘어납니다.
 *
 * 그래서 열마다 **한쪽은 제 크기에 서고 다른 쪽이 남는 높이를 다 가집니다.**
 * 왼쪽 열은 위(차트)가 가져가고, 오른쪽 첫 열은 늘어나는 카드가 없어 아래가
 * 받습니다 — 어느 쪽도 안 받게 두면 열 아래에 아무것도 아닌 빈 띠가 남습니다.
 *
 * 격자의 높이는 세 열 중 **가장 높은 것**입니다. 낮은 열은 그만큼 늘어나고,
 * 늘어난 몫도 같은 규칙으로 갈립니다. */

/** 열마다 남는 높이를 가져가는 쪽. */
export const COLUMN_GROW: Record<'left' | 'r1', 'top' | 'bottom'> = { left: 'top', r1: 'bottom' }

/** 그 열에서 **크기가 정해진 쪽**의 슬롯. 남는 높이는 반대쪽이 가집니다. */
export function fixedSlot(column: 'left' | 'r1'): SlotKey {
  return column === 'left' ? 'lb' : 'r1t'
}

/** 크기가 정해진 쪽의 높이. 저장값을 그 슬롯의 바닥 아래로는 안 내립니다.
 *
 *  **반대쪽이 비어 있으면 이 값은 안 쓰입니다** — 남은 슬롯 하나가 열 전체를
 *  씁니다(`isSlotEmpty` 로 가려서 씁니다). */
export function fixedHeight(
  layout: TradeLayout,
  column: 'left' | 'r1',
  subject = false,
): number {
  const slot = fixedSlot(column)
  const stored = column === 'left' ? layout.lbHeight : layout.r1tHeight
  if (isSlotEmpty(layout, slot)) return 0
  return Math.max(slotFloor(layout, slot, subject), stored)
}

/** 한 열이 부르는 높이 — 늘어나는 쪽의 바닥 + 경계 + 정해진 쪽의 높이입니다.
 *  한쪽이 비면 남은 쪽 하나가 열 전체입니다. */
export function columnHeight(
  layout: TradeLayout,
  column: 'left' | 'r1',
  subject = false,
): number {
  const [top, bottom] = column === 'left' ? (['lt', 'lb'] as const) : (['r1t', 'r1b'] as const)
  const emptyTop = isSlotEmpty(layout, top)
  const emptyBottom = isSlotEmpty(layout, bottom)
  if (emptyTop && emptyBottom) return 0
  if (emptyTop) return slotMinHeight(layout, bottom)
  if (emptyBottom) return slotMinHeight(layout, top)
  const growing = COLUMN_GROW[column] === 'top' ? top : bottom
  return slotMinHeight(layout, growing) + GUTTER + fixedHeight(layout, column, subject)
}

/** 격자가 부르는 높이 — 세 열 중 가장 높은 것입니다. 맨 오른쪽은 두 줄을
 *  통째로 쓰므로 제 카드 바닥이 곧 열 높이입니다. */
export function gridHeight(layout: TradeLayout): number {
  return Math.max(
    columnHeight(layout, 'left'),
    columnHeight(layout, 'r1'),
    slotMinHeight(layout, 'r2'),
  )
}

/** 정해진 쪽을 끌 때 갈 수 있는 끝. 늘어나는 쪽의 바닥을 남깁니다.
 *  `available` 은 격자가 지금 쓸 수 있는 높이입니다. */
export function fixedMaxHeight(
  layout: TradeLayout,
  column: 'left' | 'r1',
  available: number,
  subject = false,
): number {
  const [top, bottom] = column === 'left' ? (['lt', 'lb'] as const) : (['r1t', 'r1b'] as const)
  const growing = COLUMN_GROW[column] === 'top' ? top : bottom
  const floor = slotFloor(layout, fixedSlot(column), subject)
  if (!Number.isFinite(available) || available <= 0) return MAX_HEIGHT
  const room = available - GUTTER - slotMinHeight(layout, growing)
  return Math.max(floor, Math.min(MAX_HEIGHT, room))
}

/** 열 경계. 이 열이 넓어진 만큼 넓은 열이 좁아집니다 — 넓은 열이 제 바닥에
 *  닿거나 이 열이 제 상한에 닿는 데서 멈춥니다. */
export function withColumnWidth(
  layout: TradeLayout,
  column: 'r1' | 'r2',
  width: number,
  usable = Number.POSITIVE_INFINITY,
): TradeLayout {
  const min = columnMinWidth(layout, column)
  const next = clamp(width, min, columnMaxWidth(layout, column, usable), min)
  return column === 'r1' ? { ...layout, r1Width: next } : { ...layout, r2Width: next }
}

/** 정해진 쪽의 높이를 바꿉니다. 늘어나는 쪽의 바닥을 지키느라 거기서 멈춥니다. */
export function withFixedHeight(
  layout: TradeLayout,
  column: 'left' | 'r1',
  height: number,
  available = Number.POSITIVE_INFINITY,
  subject = false,
): TradeLayout {
  const min = slotFloor(layout, fixedSlot(column), subject)
  const next = clamp(height, min, fixedMaxHeight(layout, column, available, subject), min)
  return column === 'left' ? { ...layout, lbHeight: next } : { ...layout, r1tHeight: next }
}
