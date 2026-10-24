import { Modal } from '../../app/Modal'
import {
  CARDS,
  CARD_HIDE_NOTE,
  CARD_LABEL,
  COLUMN_LABEL,
  COLUMN_SLOTS,
  DEFAULT_LAYOUT,
  REQUIRED_CARD,
  SLOTS,
  SLOT_LABEL,
  canPlace,
  hideCard,
  isVisible,
  moveCard,
  moveColumn,
  showCard,
  slotOf,
  type CardKey,
  type SlotKey,
  type TradeLayout,
} from './tradeLayout'

/* 패널 편집 — 무엇을 보일지와 어느 자리에 둘지.
 *
 * **자리 교환은 여기가 아니라 카드 머리의 손잡이 ⠿ 가 합니다.** 편집은 「무엇을
 * 보일지」, 손잡이는 「어디에 둘지」로 갈라 둡니다 — 같은 일을 두 곳에서 할 수
 * 있으면 어느 쪽이 최신인지 매번 확인하게 됩니다. 이 목록의 셀렉트는 카드
 * 하나를 다른 자리로 **옮기는** 것이고, 손잡이는 두 자리를 통째로 **맞바꾸는**
 * 것이라 하는 일이 다릅니다.
 *
 * 카드 머리 띠에 붙이지 않고 별도 모달로 엽니다. 띠는 「무슨 카드인가」만
 * 답하기로 이미 정했고, 여기서 다루는 것은 화면 전체의 구성입니다.
 */

interface Props {
  layout: TradeLayout
  onChange: (layout: TradeLayout) => void
  onClose: () => void
}

export function PanelEditor({ layout, onChange, onClose }: Props) {
  /* 필수 카드의 체크는 끌 수 없습니다. `disabled` 대신 `aria-disabled` 입니다 —
     `disabled` 는 초점을 못 받아서, 왜 못 끄는지 적어 둔 줄에 닿는 길이
     마우스를 얹는 것 하나만 남습니다. 키보드로도 그 줄에 가서 이유를 읽을 수
     있어야 합니다. */
  const noteId = (card: CardKey) => `panel-note-${card}`

  const toggle = (card: CardKey) => {
    if (card === REQUIRED_CARD) return
    onChange(isVisible(layout, card) ? hideCard(layout, card) : showCard(layout, card))
  }

  return (
    <Modal label="패널 편집" onClose={onClose} head={<h2 className="modal-title">패널 편집</h2>}>
      {/* 왜 어떤 자리가 회색인지 목록 위에서 한 번에 답합니다. 줄마다 되풀이하면
          여섯 번 읽게 되고, 안 적으면 회색이 고장으로 보입니다. */}
      <h3 className="panel-section">보일 카드와 자리</h3>
      {/* 한 줄로 끊습니다 — 어느 카드가 어느 쪽인지는 바로 아래 목록의 셀렉트가
          답하므로, 여기서 카드 이름을 다시 늘어놓으면 같은 말이 두 번입니다. */}
      <p className="panel-guide">
        넓어지면 더 보여주는 카드는 넓은 열에, 그렇지 않은 카드는 호가 열·주문 열에만 섭니다.
      </p>

      <ul className="panel-editor">
        {CARDS.map((card) => {
          const shown = isVisible(layout, card)
          const slot = slotOf(layout, card)
          const required = card === REQUIRED_CARD
          const note = CARD_HIDE_NOTE[card]
          return (
            <li key={card} className="panel-row">
              <label className="panel-check">
                <input
                  type="checkbox"
                  checked={shown}
                  aria-disabled={required || undefined}
                  aria-describedby={note ? noteId(card) : undefined}
                  onChange={() => toggle(card)}
                />
                <span className="panel-name">{CARD_LABEL[card]}</span>
              </label>

              {/* 어느 자리에 둘지. 숨긴 카드는 어디에도 안 서므로 고를 것이
                  없습니다 — 체크를 켜면 기본 배치에서 그 카드가 서던 자리로
                  돌아오고, 그때부터 고를 수 있습니다.

                  **못 가는 자리도 목록에 남겨 두고 비활성으로만 둡니다.**
                  빼 버리면 그런 자리가 있다는 것 자체를 모르게 되어, 왜 이
                  카드가 저기 못 가는지가 아니라 저기가 없는 것으로 읽힙니다. */}
              <select
                className="control panel-slot"
                aria-label={`${CARD_LABEL[card]} 자리`}
                value={slot ?? ''}
                disabled={!shown}
                onChange={(event) => onChange(moveCard(layout, card, event.target.value as SlotKey))}
              >
                {!shown && <option value="">—</option>}
                {SLOTS.map((key) => (
                  <option key={key} value={key} disabled={!canPlace(card, key)}>
                    {SLOT_LABEL[key]}
                  </option>
                ))}
              </select>

              {/* 이 줄에만 있는 말만 답니다. 어느 자리에 설 수 있는지는 목록
                  위에서 한 번 답했으므로, 여기서 되풀이하면 여섯 줄이 같은 말을
                  하고 정작 이 카드에만 해당하는 말이 그 회색 덩어리에 묻힙니다. */}
              {note && (
                <p className="panel-note" id={noteId(card)}>
                  {note}
                </p>
              )}
            </li>
          )
        })}
      </ul>

      {/* 열 순서. **카드가 아니라 열째로** 옮깁니다 — 그 열 안의 슬롯 구성은
          그대로이고 서는 자리만 바뀝니다.
          끌기가 아니라 화살표 단추입니다: 이 화면에는 이미 끄는 동작이 둘
          (손잡이·경계) 있고, 셋째를 모달 안에 들이면 같은 손짓이 자리마다
          다른 것을 옮기게 됩니다. 단추는 키보드로도 그대로 됩니다. */}
      <h3 className="panel-section">열 순서</h3>
      <ol className="panel-order-list">
        {layout.columnOrder.map((column, at) => {
          /* 그 열에 지금 무엇이 서 있는지. 「호가 열」 같은 이름만으로는 카드를
             옮겨 둔 뒤에 어느 열인지 알 수 없습니다. */
          const inside = COLUMN_SLOTS[column]
            .flatMap((slot) => layout.slots[slot])
            .map((card) => CARD_LABEL[card])
          const first = at === 0
          const last = at === layout.columnOrder.length - 1
          return (
            <li key={column} className="panel-order-item">
              {/* 끝에 닿은 화살표는 비활성이고 이유를 답니다 — 치우면 열마다
                  단추 수가 달라져 줄이 들쭉날쭉해지고, 그냥 두면 눌러도 아무
                  일이 없는 단추가 됩니다. */}
              <button
                type="button"
                className="btn btn-quiet panel-order-btn"
                aria-label={`${COLUMN_LABEL[column]} 왼쪽으로`}
                aria-disabled={first || undefined}
                title={first ? '맨 왼쪽입니다' : undefined}
                onClick={() => !first && onChange(moveColumn(layout, column, -1))}
              >
                ◀
              </button>
              <span className="panel-order-col">
                <span className="panel-order-label">{COLUMN_LABEL[column]}</span>
                <span className="panel-order-cards">
                  {inside.length > 0 ? inside.join(' · ') : '비어 있음'}
                </span>
              </span>
              <button
                type="button"
                className="btn btn-quiet panel-order-btn"
                aria-label={`${COLUMN_LABEL[column]} 오른쪽으로`}
                aria-disabled={last || undefined}
                title={last ? '맨 오른쪽입니다' : undefined}
                onClick={() => !last && onChange(moveColumn(layout, column, 1))}
              >
                ▶
              </button>
            </li>
          )
        })}
      </ol>

      {/* 바닥에 붙여 둡니다. **되돌리는 길이 이것 하나**라, 목록이 길어져
          본문이 스크롤할 때 이 단추가 아래로 밀려 나가면 「배치를 망쳤는데
          되돌릴 수가 없는」 상태가 실제로 생깁니다. */}
      <div className="panel-editor-foot">
        {/* 확인 없이 바로 되돌립니다. 되돌린 것을 다시 고르면 되므로 잃는 것이
            없습니다 — 자리와 크기가 함께 처음으로 갑니다. */}
        <button type="button" className="btn btn-quiet" onClick={() => onChange(DEFAULT_LAYOUT)}>
          <span aria-hidden="true">⟲</span> 기본 배치로
        </button>
      </div>
    </Modal>
  )
}
