import type { MarketContext, ProductKind } from '../../lib/types'
import type { InstrumentRef } from '../../lib/InstrumentPicker'
import { canAskOrderable } from '../../data/orderable'
import { needsLeg, resolve, type Instrument } from '../../data/instruments'
import { retryChain } from '../../data/optionChain'
import { reloadAccountLists, retryList } from '../../data/account'
import { PAPER_NIGHT_PRICE_TEXT, retryQuote } from '../../data/quotes'
import { loadSession } from '../../data/session'
import { fillCondFor } from '../../data/strategyRules'
import { InstrumentHeader } from './InstrumentHeader'
import { OrderBook } from './OrderBook'
import { OrderForm } from './OrderForm'
import { ChartPanel } from './ChartPanel'
import type { SlotState, SplitState } from './chartSlots'
import { MarketDataPanel, ProductInfoPanel } from './InfoPanels'
import { OrdersAndFills } from './OrdersAndFills'
import { OptionChain, type ChainSide } from './OptionChain'
import { TickTape } from './TickTape'
import { RealtimeNeeded } from './RealtimeNeeded'
import { CARD_LABEL, DEFAULT_LAYOUT } from './tradeLayout'
import { nextMonthOf } from './tradeScreenUtils'
import type { useOptionChainPick } from './useOptionChainPick'
import type { useTradeQuotes } from './useTradeQuotes'
import type { useTradeAccount } from './useTradeAccount'
import type { useTradeGrid } from './useTradeGrid'
import type { useOrderTicket } from './useOrderTicket'

type ChainPickValues = ReturnType<typeof useOptionChainPick>
type QuoteValues = ReturnType<typeof useTradeQuotes>
type AccountValues = ReturnType<typeof useTradeAccount>
type GridValues = ReturnType<typeof useTradeGrid>
type OrderValues = ReturnType<typeof useOrderTicket>

type HeaderArgs = Pick<
    QuoteValues,
    'shownQuote' | 'shownFailure' | 'priceKnown' | 'quoteStaleAt' | 'months' | 'legsLine'
  > &
  Pick<
    ChainPickValues,
    'pickedSide' | 'pickedStrike' | 'strikes' | 'strikeDecimals' | 'setPickedSide'
    | 'setPickedStrike'
  > &
  Pick<GridValues, 'isDefaultLayout' | 'storeLayout' | 'setEditorOpen'> &
  {
    activeContext: MarketContext
    onOpenSettings: (() => void) | undefined
    kind: ProductKind
    openCode: (next: string) => void
  }

/** 종목 머리 띠 — 종목·만기·옵션 축과 현재가, 배치 단추. */
export function renderHeader({
  shownQuote,
  activeContext,
  shownFailure,
  onOpenSettings,
  priceKnown,
  quoteStaleAt,
  months,
  legsLine,
  kind,
  pickedSide,
  pickedStrike,
  strikes,
  strikeDecimals,
  openCode,
  setPickedSide,
  setPickedStrike,
  isDefaultLayout,
  storeLayout,
  setEditorOpen,
}: HeaderArgs) {
  return (
      <InstrumentHeader
        quote={shownQuote}
        context={activeContext}
        failure={shownFailure}
        onRetry={() => retryQuote(shownQuote.code)}
        onOpenSettings={onOpenSettings}
        /* 값을 못 세운 동안에는 불러오는 중이든 실패든 값 자리를 비웁니다 —
           다른 출처의 숫자가 이 종목의 값으로 읽히면 안 됩니다. **받는 중과
           못 받음은 얼굴이 달라야 합니다** — 앞은 기다리면 되고 뒤는 아닙니다.
           받는 중에는 「여기 값이 올 자리」를 옅은 블록으로 두고, 값이 안 올
           것이 정해진 뒤에는 그 블록을 걷습니다. */
        valuesHidden={!priceKnown}
        /* 축을 안 고른 옵션은 「아직 안 골랐다」이지 「받는 중」이 아닙니다 — 뼈대는
           곧 온다는 말이라 세우지 않고, 라벨만 남기고 값을 비웁니다. */
        valuesLoading={!priceKnown && shownFailure === null && !needsLeg(shownQuote.code)}
        since={quoteStaleAt}
        months={months}
        legsLine={legsLine}
        kind={kind}
        optionSide={pickedSide}
        strike={pickedStrike}
        strikes={strikes}
        strikeDecimals={strikeDecimals}
        onMonthChange={openCode}
        onOptionSideChange={(side) => setPickedSide(side)}
        onStrikeChange={(next) => setPickedStrike(next)}
        /* 화면 구성은 카드 하나에 대한 것이 아니라 화면 전체에 대한 것이라
           카드 머리 띠가 아니라 이 띠에 섭니다. */
        actions={
          <>
            {/* 되돌리는 길이 화면에서 바로 닿아야 합니다 — 모달을 열어야만
                되돌릴 수 있으면, 배치를 망친 사람은 그 모달을 여는 단추부터
                찾아야 합니다. 모달 안의 것과 같은 동작입니다.
                이미 기본이면 눌러도 아무 일이 없으므로 비활성 + 이유입니다 —
                치우면 그 자리가 배치마다 생겼다 없어져 눈이 흔들립니다. */}
            <button
              type="button"
              className="btn btn-quiet card-head-btn"
              aria-label="기본 배치로"
              data-tip={isDefaultLayout ? '이미 기본 배치입니다' : '기본 배치로'}
              aria-disabled={isDefaultLayout || undefined}
              onClick={() => !isDefaultLayout && storeLayout(DEFAULT_LAYOUT)}
            >
              ⟲
            </button>
            <button
              type="button"
              className="btn btn-quiet card-head-btn"
              aria-label="패널 편집"
              data-tip="패널 편집"
              aria-haspopup="dialog"
              onClick={() => setEditorOpen(true)}
            >
              ▦
            </button>
          </>
        }
      />
  )
}

type ResizersArgs = Pick<GridValues, 'colSplits' | 'startColumnResize' | 'rowSplits' | 'startRowResize'>

/** 카드 사이 경계 손잡이(열 경계와 행 경계). */
export function renderResizers({
  colSplits,
  startColumnResize,
  rowSplits,
  startRowResize,
}: ResizersArgs) {
  return (
          <>
            {/* 경계는 나눌 것이 양쪽에 있을 때만 섭니다. 한쪽이 비면 아무것도
                안 나누는 손잡이가 되고, 끌면 빈 자리만 넓어집니다. */}
            {/* 열 경계 둘. **어느 열을 넓히는지는 열 순서가 정합니다** —
                넓은 열은 남는 폭을 다 쓰므로, 경계는 늘 옆에 있는 좁은 열의
                폭을 바꾸고 그만큼을 넓은 열이 내놓습니다. 넓은 열이 경계의
                왼쪽에 있으면 오른쪽으로 끌 때 좁은 열이 좁아지고, 오른쪽에
                있으면 반대입니다. */}
            {/* 잠긴 경계도 **자리는 지킵니다.** 치우면 확대를 오갈 때마다 열이
                옆으로 움직이고, 잠겼다는 것도 알 길이 없습니다 — 안 움직이는
                손잡이는 고장으로 읽히므로 커서와 설명으로 잠김을 말합니다. */}
            {colSplits.map((split) => (
              <div
                key={split.at}
                className={`col-resizer${split.locked ? ' is-locked' : ''}`}
                role="separator"
                aria-orientation="vertical"
                aria-label={`${split.label} 폭 조절`}
                aria-disabled={split.locked || undefined}
                title={split.locked ? '확대 중에는 차트 쪽 경계를 옮길 수 없습니다' : undefined}
                style={{ gridColumn: split.at === 0 ? 2 : 4, gridRow: 1 }}
                onPointerDown={split.locked ? undefined : startColumnResize(split.column, split.sign)}
              />
            ))}
            {/* 행 경계는 **열마다** 있습니다. 위아래로 갈리는 열이 둘이고
                그 경계가 서는 높이가 서로 달라(왼쪽은 차트 아래, 오른쪽 첫
                열은 호가 아래) 하나로는 둘을 못 나눕니다. */}
            {rowSplits.map((split) => (
              <div
                key={split.column}
                className="row-resizer"
                role="separator"
                aria-orientation="horizontal"
                aria-label={`${split.label} 위아래 칸 높이 조절`}
                style={{ gridColumn: split.gridColumn, gridRow: 1, ...split.edge }}
                onPointerDown={startRowResize(split.column)}
              />
            ))}
          </>
  )
}

type ChartCardArgs = Pick<
    GridValues,
    'cardProps' | 'cardHead' | 'chartExpandButton' | 'expandedChart' | 'chartTabStrip'
    | 'chartTabsInBody' | 'activeTab' | 'chartExpanded' | 'setChartExpanded'
  > &
  Pick<
    ChainPickValues,
    'chain' | 'optionProduct' | 'presets' | 'activePreset' | 'setPreset' | 'chainSide'
    | 'setChainSide' | 'chainRows' | 'chainArgs' | 'chainOwner' | 'futuresPrice' | 'atm'
    | 'strikeDecimals' | 'chainPickedCode' | 'pickFromChain' | 'pickFromCode'
  > &
  Pick<QuoteValues, 'quote' | 'secondQuote' | 'shownQuote' | 'priceKnown'> &
  {
    secondSelected: Instrument | null
    splitState: SplitState
    patchSlot: (slot: 0 | 1, patch: Partial<SlotState>) => void
    subject: Instrument | null
    setSplitState: (next: SplitState) => void
    secondCode: string | null
    selectedCode: string | null
    pickInstrument: (slot: 0 | 1, item: InstrumentRef) => void
    activeContext: MarketContext
  }

/** 차트 카드 — 체인·차트·품목정보 탭. */
export function renderChartCard({
  cardProps,
  cardHead,
  chartExpandButton,
  expandedChart,
  chartTabStrip,
  chartTabsInBody,
  activeTab,
  chain,
  optionProduct,
  presets,
  activePreset,
  setPreset,
  chainSide,
  setChainSide,
  chainRows,
  chainArgs,
  chainOwner,
  futuresPrice,
  atm,
  strikeDecimals,
  chainPickedCode,
  pickFromChain,
  quote,
  secondSelected,
  secondQuote,
  splitState,
  patchSlot,
  chartExpanded,
  setChartExpanded,
  subject,
  setSplitState,
  secondCode,
  selectedCode,
  pickFromCode,
  pickInstrument,
  shownQuote,
  activeContext,
  priceKnown,
}: ChartCardArgs) {
  return (
        <section className="trade-card card-chart" aria-label={CARD_LABEL.chart} {...cardProps('chart')}>
          {/* 이 카드가 제 자리에 혼자 서면 탭 줄이 곧 이름입니다 — 「차트」
              이름 옆에 「차트」 탭을 세우면 같은 글자가 두 번 섭니다. 띠 왼쪽의
              식별 물체는 카드마다 정확히 하나이고, 모양이 알약이냐 글자냐만
              다릅니다. 확대 중에는 탭을 못 바꾸므로 그때는 이름 글자가 섭니다.
              다른 카드와 한 자리에 서면 띠는 **자리의 탭 줄**이 되고, 차트가
              무엇을 보여줄지 고르는 이 줄은 본문 첫 줄로 내려갑니다 — 한 띠에
              탭 줄이 둘이면 어느 것이 자리를 바꾸는지 알 수 없습니다. */}
          {cardHead(
            'chart',
            chartExpandButton,
            expandedChart ? undefined : chartTabStrip,
          )}

          <div className="trade-panel">
            {!expandedChart && chartTabsInBody && (
              <div className="panel-tabs">{chartTabStrip}</div>
            )}
            {/* 체인은 이 화면에 둡니다. 행사가 축이 하나 더 있는
                것은 옵션만의 사정이라, 옵션을 주문하는 화면에 있어야 고른
                칸이 그대로 주문의 종목이 됩니다. */}
            {activeTab === '체인' && chain && optionProduct && (
              <div className="chain-panel">
                <div className="chain-controls">
                  {/* 고를 묶음이 하나(야간)면 고르개를 안 세웁니다. */}
                  {presets.length > 1 && (
                    <select
                      className="chain-select"
                      aria-label="열 묶음"
                      value={activePreset.id}
                      onChange={(event) =>
                        setPreset(presets.findIndex((item) => item.id === event.target.value))
                      }
                    >
                      {presets.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                  )}

                  {/* 이것은 주문 대상이 아니라 보기 설정입니다. 헤더의 [콜 ▾] 와
                      이름이 같으면 둘 중 하나가 고장 난 것으로 읽힙니다. */}
                  <div className="seg chain-view" role="group" aria-label="체인에 보일 쪽">
                    {(['both', 'call', 'put'] as ChainSide[]).map((item) => (
                      <button
                        key={item}
                        type="button"
                        className="seg-item"
                        aria-pressed={chainSide === item}
                        onClick={() => setChainSide(item)}
                      >
                        {item === 'both' ? '양쪽' : item === 'call' ? '콜만' : '풋만'}
                      </button>
                    ))}
                  </div>

                </div>

                <OptionChain
                  rows={chainRows}
                  preset={activePreset}
                  side={chainSide}
                  decimals={optionProduct.decimals ?? 2}
                  /* 첫 답이 오기 전에는 표가 없고 「받는 중」이 섭니다 — 행사가
                     축까지 서버가 줍니다. */
                  loaded={chain.rows !== null}
                  /* 무엇의 체인인지 — 이것이 바뀔 때만 등가격을 가운데로 엽니다. */
                  chainKey={chainArgs ? JSON.stringify(chainArgs) : ''}
                  failure={chain.failure}
                  onRetry={() => chainArgs && chainOwner && retryChain(chainArgs, chainOwner)}
                  night={chain.session === 'night'}
                  futuresPrice={futuresPrice}
                  atm={atm}
                  strikeDecimals={strikeDecimals}
                  /* 고른 줄은 **코드**로 견줍니다 — 적힌 글자로 견주면 자리 수에
                     맞춰 반올림된 두 행사가가 같은 줄로 보입니다. 고른 다리가 없을
                     때는 **이 화면의 종목코드**로 견줍니다: 종목코드로 열고 들어온
                     옵션은 축을 따로 고른 적이 없지만 표에 그 계약 줄이 있습니다. */
                  selectedCode={chainPickedCode}
                  onSelect={pickFromChain}
                  onOpen={pickFromChain}
                />
              </div>
            )}

            {activeTab === '차트' && (
              <ChartPanel
                /* 첫째 칸은 이 화면의 종목, 둘째 칸은 그 칸이 든 종목입니다.
                   주문 대상이 어느 쪽인지는 `active` 가 말하고, 헤더·호가·폼은
                   위에서 같은 기준으로 고른 `shownQuote` 를 봅니다. */
                quotes={[quote, secondSelected ? secondQuote : null]}
                slots={splitState.slots}
                onSlotChange={patchSlot}
                expanded={chartExpanded}
                onExpandedChange={setChartExpanded}
                split={splitState.split}
                onSplitChange={(split) => {
                  /* 처음 켤 때 둘째 칸은 이 종목의 차월물로 시작합니다. */
                  const slots: [SlotState, SlotState] = [splitState.slots[0], splitState.slots[1]]
                  if (split && !slots[1].instrument) {
                    slots[1] = { ...slots[1], instrument: nextMonthOf(subject) }
                  }
                  setSplitState({ ...splitState, split, slots })
                }}
                active={splitState.active}
                onActiveChange={(active) => {
                  setSplitState({ ...splitState, active })
                  /* 주문 대상이 다른 칸으로 옮겨 갔습니다. 옵션의 축은 대상
                     종목에 딸린 것이라 그 칸의 코드에서 다시 읽습니다 — 안 그러면
                     이 칸의 종목 위에 저 칸에서 고른 행사가가 서게 됩니다. */
                  const code = active === 1 ? secondCode : selectedCode
                  pickFromCode(code ? resolve(code) : null)
                }}
                onPickInstrument={pickInstrument}
              />
            )}
            {/* 정산·장운영은 품목의 성질이라 품목정보 안에 섭니다. */}
            {activeTab === '품목정보' && (
              <>
                <ProductInfoPanel quote={shownQuote} context={activeContext} />
                <MarketDataPanel quote={shownQuote} context={activeContext} priceKnown={priceKnown} />
              </>
            )}
          </div>
        </section>
  )
}

type BottomCardsArgs = Pick<
    GridValues,
    'expandedChart' | 'collapsedFor' | 'cardProps' | 'cardHead' | 'bottomHeadActions'
  > &
  Pick<OrderValues, 'startClosing' | 'startEditing'> &
  Pick<QuoteValues, 'shownQuote'> &
  Pick<
    AccountValues,
    'orders' | 'fills' | 'positions' | 'orderList' | 'positionList' | 'accountMarket'
    | 'positionSides' | 'positionNotes' | 'receivedSides'
  > &
  {
    context: MarketContext
  }

/** 아래 두 카드 — 주문체결상세와 미결제약정. */
export function renderBottomCards({
  expandedChart,
  collapsedFor,
  cardProps,
  cardHead,
  bottomHeadActions,
  startClosing,
  shownQuote,
  context,
  orders,
  fills,
  positions,
  orderList,
  positionList,
  accountMarket,
  positionSides,
  positionNotes,
  receivedSides,
  startEditing,
}: BottomCardsArgs) {
  return (
        (['orders', 'positions'] as const).map((card) => (
          <section
            key={card}
            className={`trade-card card-orders${expandedChart ? ' is-hidden' : ''}`}
            aria-label={CARD_LABEL[card]}
            data-collapsed={collapsedFor(card) ? 'true' : undefined}
            {...cardProps(card)}
          >
            {cardHead(card, bottomHeadActions(card))}

            {!collapsedFor(card) && !expandedChart && (
              <div className="trade-bottom-wrap">
                <OrdersAndFills
                  onClose={startClosing}
                  /* 표의 종목·소수 자릿수는 주문 대상 종목을 따릅니다. 목록 자체가
                     그 종목의 것이라, 화면의 첫째 차트 종목을 적으면 둘째 칸을
                     주문 대상으로 둔 동안 이름과 내용이 어긋납니다. */
                  quote={shownQuote}
                  /* 값 칸 폭을 잡을 무리를 고르는 데 씁니다. 종목이 제 시장을
                     들고 오지 않는 경우가 있어 화면이 보고 있는 시장을 줍니다. */
                  context={context}
                  orders={orders}
                  fills={fills}
                  positions={positions}
                  /* 카드마다 제 조회를 봅니다 — 하나가 못 왔다고 다른 카드가
                     못 받은 얼굴을 하면 안 됩니다. */
                  list={card === 'orders' ? orderList : positionList}
                  onRetry={() => {
                    if (card === 'orders') retryList(accountMarket, 'orders', 'all')
                    else for (const side of positionSides) retryList(side.market, 'positions')
                  }}
                  positionNotes={positionNotes.map(({ side, kind }) => ({
                    market: side.market,
                    kind,
                    /* 표에 줄이 선 다른 시장. 「아래는 … 줄뿐」이 이것을 말합니다. */
                    shown: receivedSides.filter((other) => other.market !== side.market).map((other) => other.market),
                    retry: side.entry.failure === 'retry' ? () => retryList(side.market, 'positions') : undefined,
                  }))}
                  mode={card === 'orders' ? '주문체결상세' : '미결제약정'}
                  onEdit={startEditing}
                />
              </div>
            )}
          </section>
        ))
  )
}

type BookCardArgs = Pick<GridValues, 'cardProps' | 'cardHead' | 'subjectShown'> &
  Pick<
    QuoteValues,
    'bookFailed' | 'staleAt' | 'failedExchange' | 'shownQuote' | 'book' | 'bookFailure'
    | 'priceKnown' | 'axisPending' | 'shownEntry'
  > &
  Pick<OrderValues, 'price' | 'clearResult' | 'touchPrice' | 'setPrice'>

/** 호가 카드. */
export function renderBookCard({
  cardProps,
  cardHead,
  bookFailed,
  staleAt,
  failedExchange,
  shownQuote,
  book,
  bookFailure,
  priceKnown,
  axisPending,
  shownEntry,
  price,
  subjectShown,
  clearResult,
  touchPrice,
  setPrice,
}: BookCardArgs) {
  return (
        <section className="trade-card card-book" aria-label={CARD_LABEL.book} {...cardProps('book')}>
          {/* 자리에 혼자 서면 이름 글자가 식별 물체입니다. 손잡이 `aria-label` 이
              읽는 이름과 같은 글자를 씁니다 — 눈으로 보는 이름과 소리로 듣는
              이름이 다르면 같은 카드를 가리키는지 알 수 없습니다. */}
          {cardHead(
            'book',
            bookFailed ? (
              <RealtimeNeeded
                at={staleAt}
                exchange={failedExchange}
                code={bookFailed.code}
                message={bookFailed.message}
              />
            ) : (
              staleAt && <span className="card-since">{staleAt} 기준</span>
            ),
          )}
          <OrderBook
            quote={shownQuote}
            asks={book.asks}
            bids={book.bids}
            failure={bookFailure}
            onRetry={() => retryQuote(shownQuote.code)}
            priceKnown={priceKnown}
            pending={axisPending}
            expectedPrice={shownEntry.expectedPrice}
            selectedPrice={price}
            subject={subjectShown}
            /* 호가 사다리를 눌러 가격을 넣는 것도 사용자가 값을 고친 것입니다 —
               폼의 가격 칸을 치는 것과 같은 자리라 결과 줄도 같이 걷습니다. */
            onPickPrice={(next) => {
              clearResult()
              touchPrice()
              setPrice(next)
            }}
          />
        </section>
  )
}

type TicksCardArgs = Pick<GridValues, 'cardProps' | 'cardHead'> &
  Pick<
    QuoteValues,
    'ticksFailed' | 'quoteStaleAt' | 'failedExchange' | 'tapeSince' | 'shownQuote' | 'ticks'
    | 'listening' | 'shownUnasked' | 'axisPending'
  >

/** 시세체결 카드. */
export function renderTicksCard({
  cardProps,
  cardHead,
  ticksFailed,
  quoteStaleAt,
  failedExchange,
  tapeSince,
  shownQuote,
  ticks,
  listening,
  shownUnasked,
  axisPending,
}: TicksCardArgs) {
  return (
        <section className="trade-card card-ticks" aria-label={CARD_LABEL.ticks} {...cardProps('ticks')}>
          {/* 「언제부터」는 이름 옆에 답니다. 체결은 연결한 뒤부터 쌓이므로 그
              시각이 함께 서야 빈 목록이 「고장」이 아니라 「그때부터 아직 없음」
              으로 읽히고, 몇 줄만 있을 때도 「오늘 이만큼 거래됐다」로 안 읽힙니다.
              무엇이 그 시각이 되는지는 위 `tapeSince` 에 적혀 있습니다. */}
          {cardHead(
            'ticks',
            ticksFailed ? (
              <RealtimeNeeded
                at={quoteStaleAt}
                exchange={failedExchange}
                code={ticksFailed.code}
                message={ticksFailed.message}
              />
            ) : (
              tapeSince && <span className="card-note">{tapeSince} 부터</span>
            ),
          )}
          <TickTape
            quote={shownQuote}
            ticks={ticks}
            listening={listening}
            refused={ticksFailed !== undefined}
            unasked={shownUnasked}
            pending={axisPending}
          />
        </section>
  )
}

type FormCardArgs = Pick<
    GridValues,
    'cardProps' | 'cardHead' | 'subjectShown' | 'slotOfCard' | 'setSlotTabs'
    | 'setBottomOpen'
  > &
  Pick<
    QuoteValues,
    'shownQuote' | 'bestBid' | 'bestAsk' | 'orderBlocked' | 'credentialsWhy'
    | 'environmentWhy' | 'sessionWhy' | 'sessionHeld' | 'sessionCode' | 'shownFailure'
    | 'environmentKnown'
  > &
  Pick<
    OrderValues,
    'side' | 'orderType' | 'condition' | 'price' | 'stopPrice' | 'quantity' | 'submitPaused'
    | 'editing' | 'orderable' | 'orderableAsk' | 'closing' | 'closePriceFrom'
    | 'clearResult' | 'chooseSide' | 'setOrderType' | 'setCondition' | 'touchPrice'
    | 'setPrice' | 'setStopPrice' | 'setQuantity' | 'checkOrderable' | 'setEditing'
    | 'setClosing' | 'releaseSystemSide' | 'sending' | 'orderResult' | 'askToSend'
  > &
  Pick<AccountValues, 'accountMarket'> &
  {
    activeContext: MarketContext
    kind: ProductKind
  }

/** 주문 폼 카드. */
export function renderFormCard({
  cardProps,
  cardHead,
  shownQuote,
  subjectShown,
  activeContext,
  kind,
  side,
  orderType,
  condition,
  price,
  stopPrice,
  quantity,
  bestBid,
  bestAsk,
  orderBlocked,
  submitPaused,
  credentialsWhy,
  environmentWhy,
  sessionWhy,
  sessionHeld,
  sessionCode,
  shownFailure,
  editing,
  orderable,
  environmentKnown,
  orderableAsk,
  closing,
  closePriceFrom,
  clearResult,
  chooseSide,
  setOrderType,
  setCondition,
  touchPrice,
  setPrice,
  setStopPrice,
  setQuantity,
  checkOrderable,
  setEditing,
  setClosing,
  releaseSystemSide,
  sending,
  orderResult,
  askToSend,
  slotOfCard,
  setSlotTabs,
  setBottomOpen,
  accountMarket,
}: FormCardArgs) {
  return (
        <section className="trade-card card-form" aria-label={CARD_LABEL.form} {...cardProps('form')}>
          {cardHead('form')}
          <OrderForm
            quote={shownQuote}
            subject={subjectShown}
            context={activeContext}
            kind={kind}
            side={side}
            orderType={orderType}
            condition={condition}
            price={price}
            stopPrice={stopPrice}
            quantity={quantity}
            bestBid={bestBid}
            bestAsk={bestAsk}
            orderBlocked={orderBlocked}
            submitPaused={submitPaused}
            credentialsWhy={credentialsWhy}
            environmentWhy={environmentWhy}
            sessionWhy={sessionWhy}
            onRetrySession={
              sessionHeld.status === 'failed' && sessionCode
                ? () => void loadSession('domestic', sessionCode)
                : undefined
            }
            /* 헤더가 그 자리에서 쓰는 말과 같아야 합니다. 아직 받는 중이면
               못 받은 것이 아니므로 그렇게 적지 않습니다. */
            /* **겹치면 사용자가 지금 할 수 있는 일이 먼저 섭니다.** 축을 아직
               안 골랐는데 시장도 조회 전이면 둘이 겹치는데, 고르는 것은
               사용자가 지금 할 수 있는 일이고(바로 위 셀렉터) 조회는 아닙니다.
               할 수 있는 것이 없을 때 앱 쪽 사정이 섭니다. */
            priceWhy={
              shownFailure?.kind === 'unasked'
                ? '조회 전이라 주문을 낼 수 없습니다'
                : shownFailure?.kind === 'empty'
                  ? '아직 시세가 없습니다'
                  : shownFailure?.kind === 'paper'
                    ? PAPER_NIGHT_PRICE_TEXT
                    : shownFailure
                      ? shownFailure.text || '시세를 받지 못했습니다'
                      : '시세를 받는 중입니다'
            }
            editing={editing}
            orderable={orderable}
            canCheckOrderable={
              environmentKnown && credentialsWhy === undefined && canAskOrderable(orderableAsk)
            }
            closing={closing}
            closePriceNote={closePriceFrom === 'position'}
            /* 값을 건드리는 길은 전부 결과 줄을 먼저 걷어냅니다 — 지난 주문의
               답이 지금 고치는 값 아래 남아 있으면 그 값으로 낸 것처럼 읽힙니다. */
            onSideChange={(next) => {
              clearResult()
              chooseSide(next)
            }}
            onOrderTypeChange={(next) => {
              clearResult()
              setOrderType(next)
              /* 시장가는 FAS 만 받습니다 — 남은 FOK·FAK 는 서버가 거부합니다. */
              setCondition((current) => fillCondFor(next, current))
            }}
            onConditionChange={(next) => {
              clearResult()
              setCondition(next)
            }}
            onPriceChange={(next) => {
              clearResult()
              touchPrice()
              setPrice(next)
            }}
            onStopPriceChange={(next) => {
              clearResult()
              setStopPrice(next)
            }}
            onQuantityChange={(next) => {
              clearResult()
              setQuantity(next)
            }}
            onCheckOrderable={checkOrderable}
            onCancelEditing={() => {
              setEditing(null)
              setClosing(null)
              releaseSystemSide()
            }}
            sending={sending}
            result={orderResult}
            onSubmit={askToSend}
            /* 결과를 모를 때 갈 곳. 그 카드를 열고 목록을 다시 부릅니다 —
               무엇이 나갔는지는 거기서만 알 수 있습니다. */
            onOpenOrders={() => {
              const slot = slotOfCard('orders')
              if (slot !== null) {
                setSlotTabs((current) => ({ ...current, [slot]: 'orders' }))
                if (slot === 'lb') setBottomOpen(true)
              }
              /* 결과 줄은 종목이 바뀌면 걷히므로, 이 단추가 설 때의 시장이 곧
                 보낸 주문의 시장입니다. */
              reloadAccountLists(accountMarket)
            }}
          />
        </section>
  )
}
