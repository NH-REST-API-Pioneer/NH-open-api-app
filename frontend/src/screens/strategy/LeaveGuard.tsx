import { Modal } from '../../app/Modal'

/* 저장 안 한 설정을 두고 떠나려 할 때 붙잡는 창.
 *
 * **하위 탭과 상단 페이지가 같은 창을 씁니다.** 나가는 길이 둘인데 한쪽에만
 * 경고가 붙으면, 사용자는 「어떤 길로 나가면 안 사라지는지」를 외워야 합니다.
 * 그래서 창을 화면 밖으로 빼서 두 자리가 함께 씁니다.
 *
 * 버리는 것은 **설정 초안뿐**입니다 — 검증·진행의 실행과 보낸 요청은 그대로
 * 둡니다(원본 §2).
 */

export function LeaveGuard({ onStay, onLeave }: { onStay: () => void; onLeave: () => void }) {
  return (
    <Modal
      label="저장하지 않은 변경"
      dismissable={false}
      /* ✕ 가 「여기 남기」와 같은 일을 하는데 첫 초점이 그리로 갑니다 —
         창이 물은 것에 답하는 자리는 아래 두 단추입니다. */
      closable={false}
      onClose={onStay}
      head={<span className="modal-title">저장하지 않은 변경이 있습니다</span>}
    >
      <p className="set-leave-text">
        이 화면을 떠나면 저장하지 않은 것이 사라집니다. 저장한 것은 그대로 남습니다.
      </p>
      <div className="set-leave-acts">
        <button type="button" className="btn btn-quiet" onClick={onStay}>
          여기 남기
        </button>
        <button type="button" className="btn btn-heavy" onClick={onLeave}>
          버리고 이동
        </button>
      </div>
    </Modal>
  )
}
