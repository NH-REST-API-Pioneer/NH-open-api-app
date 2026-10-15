import { useRef, useState } from 'react'
import { Modal } from '../../app/Modal'
import {
  ENVIRONMENT_LABEL,
  canSwitchTo,
  switchEnvironment,
  useEnvironment,
  type Environment,
  type SwitchResult,
} from '../../data/environment'
import { Credentials } from './Credentials'
import { AlertSettingsGroup } from './AlertSettings'
import './settings.css'

/* 설정 — 거래 환경 전환과 인증 정보 편집.
 *
 * 화면이 아니라 떠 있는 카드입니다. 설정은 「보러 가는 곳」이 아니라 「잠깐
 * 바꾸고 돌아오는 곳」이라, 보던 화면을 덮었다가 비켜 주는 편이 맞습니다.
 *
 * 전환에 확인 단계를 한 번 둡니다. 모의를 실전으로 착각하고 낸 주문은
 * 되돌릴 수 없고, 반대로 실전인 줄 알고 모의로 낸 주문은 체결된 줄 알았던
 * 포지션이 없습니다. 어느 쪽이든 한 번 더 묻는 값이 큽니다.
 *
 * **지금 어느 환경인지는 서버가 답한 값입니다.** 이 창이 바꾸는 것은 서버의
 * 활성 환경이고, 화면의 표시는 그 응답 뒤에만 따라갑니다 — 화면이 먼저 바뀌면
 * 그 사이에 낸 주문이 어느 계좌로 갔는지를 화면이 말할 수 없습니다.
 */

/* 「으로」와 「로」를 가릅니다. 받침이 없거나 ㄹ 받침이면 「로」입니다 —
 * 「모의로」와 「실전으로」가 갈립니다. 붙여 쓰면 한쪽이 늘 어색합니다. */
function ro(word: string): string {
  const last = word.charCodeAt(word.length - 1) - 0xac00
  const jong = last >= 0 && last <= 11172 ? last % 28 : 0
  return jong === 0 || jong === 8 ? '로' : '으로'
}

/** 안 된 까닭 한 줄. 서버 문구가 있으면 그것, 닿지 못한 것이면 그렇다고 — 살아 있는
 *  단추 옆에 까닭이 없으면 무엇을 다시 하라는 것인지 모릅니다. */
function failureReason(failure: Exclude<SwitchResult, { ok: true }>): string {
  if (failure.detail) return failure.detail
  return failure.kind === 'retry' ? '서버에 닿지 못했습니다' : ''
}

const TABS = ['일반', '인증 정보'] as const
type Tab = (typeof TABS)[number]

interface Props {
  /* 접속 환경에 쓸 수 있는 인증 정보가 하나도 없는지(켤 때 저절로 열리는 기준과
     같습니다). 그때는 인증 정보 탭부터 열고 왜 열렸는지 한 줄로 말합니다 — 안
     그러면 창이 저절로 뜬 이유를 모릅니다. */
  needsCredentials?: boolean
  onClose: () => void
}

export function SettingsModal({ needsCredentials, onClose }: Props) {
  const { status, active, config } = useEnvironment()
  const [tab, setTab] = useState<Tab>(needsCredentials ? '인증 정보' : '일반')
  /* 확인을 기다리는 대상. null 이면 묻는 중이 아닙니다. */
  const [asking, setAsking] = useState<Environment | null>(null)
  /* 물을 때의 환경. **전환 응답이 올 때까지 이 창은 이 값으로 말합니다** — 서버가
     실시간으로 먼저 새 환경을 알려 와 배지가 바뀌어도, 「어느 계좌의 미체결이 남나」
     같은 문장이 답 전에 새 이름으로 뒤집히면 거짓이 됩니다. 배지는 서버 값을 받는
     즉시, 확인 블록은 응답까지 옛 환경으로. */
  const [from, setFrom] = useState<Environment | null>(null)
  /* 서버에 청해 두고 답을 기다리는 중인지. 그동안은 이 창을 못 닫습니다 —
     답하지 않은 채로 사라지면 무엇을 고른 것인지가 남지 않습니다. */
  const [busy, setBusy] = useState(false)
  /* 마지막 전환이 왜 안 됐는지. 다시 묻거나 닫으면 지웁니다. */
  const [failure, setFailure] = useState<Exclude<SwitchResult, { ok: true }> | null>(null)
  /* 확인 중에 바깥을 누르면 여기로 초점이 갑니다. 「여기서 답해야 한다」를
     소리 없이 말합니다 — 카드를 흔드는 것은 오류 신호라 여기 쓸 수 없습니다. */
  const confirmRef = useRef<HTMLButtonElement>(null)

  /* 이 창이 「지금」이라고 말하는 환경. 묻는 중이면 물을 때의 값입니다. */
  const current: Environment | null = asking !== null ? from : active
  /* 지금이 아닌 쪽. 버튼도 확인 문구도 「바꿔 갈 곳」을 말합니다. 환경을 모르면
     갈 곳도 없습니다. */
  const other: Environment | null =
    current === null ? null : current === 'paper' ? 'real' : 'paper'
  const otherLabel = other ? ENVIRONMENT_LABEL[other] : ''
  const targetLabel = asking ? ENVIRONMENT_LABEL[asking] : ''
  /* 대상 환경에 인증 정보가 하나도 없으면 서버가 거절합니다. 눌러 보고 알기보다
     누르기 전에 막고 까닭을 답니다 — 할 일(인증 정보 입력)이 이 창 안에 있습니다. */
  const otherReady = other !== null && config !== null && canSwitchTo(config, other)
  /* 바꾸는 중에도 「지금 어느 쪽인지」는 서버가 답하기 전까지 옛 값이 참입니다. */
  const known = current !== null && (status === 'ready' || status === 'switching')

  const confirm = async () => {
    if (asking === null || busy) return
    setBusy(true)
    setFailure(null)
    const result = await switchEnvironment(asking)
    setBusy(false)
    if (result.ok) {
      setAsking(null)
      setFrom(null)
      return
    }
    setFailure(result)
  }

  const startAsking = () => {
    if (other === null) return
    setFrom(current)
    setAsking(other)
  }

  const stopAsking = () => {
    setAsking(null)
    setFrom(null)
    setFailure(null)
  }

  /* 서버가 답하기 전에는 닫을 수 없습니다. 닫는 길 셋(바깥 클릭·Esc·✕)이
     모두 여기를 지납니다. 그동안은 초점을 옮길 곳도 없습니다 — 답할 단추가
     잠겨 있습니다. */
  const close = () => {
    if (busy) return
    onClose()
  }

  return (
    <Modal
      label="설정"
      onClose={close}
      tall
      /* 묻는 중에는 바깥 클릭으로 안 닫힙니다. 답하지 않은 채로 사라지면
         무엇을 고른 것인지가 남지 않습니다. */
      dismissable={asking === null}
      closable={!busy}
      guard={confirmRef}
      head={
        /* 탭 둘이 곧 제목입니다. 「설정」이라는 줄을 하나 더 두면 그만큼
           내용이 줄고, 무엇을 열었는지는 누른 사람이 압니다. */
        <div className="seg" role="group" aria-label="설정 갈래">
          {TABS.map((item) => (
            <button
              key={item}
              type="button"
              className="seg-item"
              aria-pressed={tab === item}
              onClick={() => setTab(item)}
            >
              {item}
            </button>
          ))}
        </div>
      }
    >
      {tab === '일반' ? (
        <>
          <section className="settings-row" aria-label="모의 / 실전">
            <div className="settings-label">
              <h2 className="settings-name">모의 / 실전</h2>
              {/* 지금 어느 쪽인지는 서버가 답한 값입니다. 아직 못 들었으면
                  그렇다고 말합니다 — 실전이라고 가정해 두지 않습니다. */}
              <p className="settings-note">
                {known && current !== null ? (
                  <>
                    지금 <strong>{ENVIRONMENT_LABEL[current]}</strong>입니다.
                    {other && !otherReady && (
                      <>
                        {' '}
                        {otherLabel} 인증 정보가 비어 있어 바꿀 수 없습니다 — 인증 정보 탭에서
                        입력하세요.
                      </>
                    )}
                  </>
                ) : status === 'loading' ? (
                  '모의인지 실전인지 확인하는 중입니다'
                ) : (
                  '모의인지 실전인지 확인하지 못했습니다'
                )}
              </p>
            </div>

            {/* 값이 둘뿐이라 「고르는 것」이 아니라 「바꾸는 것」입니다. 세그먼트로
                두면 누른 뒤 확인을 기다리는 동안 고른 표시와 실제 상태가 갈립니다. */}
            <button
              type="button"
              className="btn btn-outline"
              onClick={startAsking}
              disabled={asking !== null || !known || !otherReady}
            >
              {other ? `${otherLabel}${ro(otherLabel)} 바꾸기` : '바꾸기'}
            </button>
          </section>

          {asking !== null && (
            <div className={`settings-confirm${asking === 'real' ? ' settings-confirm-risky' : ''}`}>
              <p className="settings-confirm-title">
                {targetLabel}
                {ro(targetLabel)} {busy ? '바꾸는 중' : '바꿀까요?'}
              </p>
              {/* 둘을 말해야 합니다 — 지금 하던 것이 끊긴다는 것과, 없어지는 게
                  아니라 안 보이게 되는 것이 있다는 것. 계좌가 바뀌는 것이라
                  미체결 주문은 그대로 남는데, 그 구분이 없으면 취소된 줄 압니다.
                  건수는 쓰지 않습니다 — 세려면 호출이 필요하고 없어도 뜻이
                  다 전달됩니다. */}
              <p className="settings-confirm-note">
                {busy ? '접속을 다시 맺고 실시간 구독을 새로 겁니다.' : '바꾸면 접속을 다시 맺고 실시간 구독을 새로 겁니다.'}{' '}
                {from ? ENVIRONMENT_LABEL[from] : ''} 계좌에 낸 미체결 주문은 그대로 남지만 이
                화면에서는 안 보입니다.
              </p>
              {/* 안 된 까닭은 같은 블록 안에 한 줄입니다. 서버가 거절한 것이면 다시
                  눌러도 같은 답이라 단추를 잠그고, 닿지 못한 것이면 단추가 곧
                  「다시」입니다 — 그때 서버 문구가 없으니 닿지 못했다고 적습니다. */}
              {failure && (
                <p className="settings-confirm-error" role="alert">
                  바꾸지 못했습니다
                  {failureReason(failure) ? ` — ${failureReason(failure)}` : ''}
                </p>
              )}
              <div className="settings-confirm-actions">
                <button
                  type="button"
                  className="btn btn-quiet"
                  onClick={stopAsking}
                  disabled={busy}
                >
                  취소
                </button>
                {/* 실전으로 가는 버튼은 초록이 아닙니다. 초록은 이 앱에서
                    「눌러도 되는 것」이라, 되돌릴 수 없는 것으로 가는 문에 붙으면
                    권유로 읽힙니다. 빨강도 못 씁니다 — 국내에서 빨강은 매수라
                    경고에 쓰면 매수 버튼과 같은 색이 됩니다. 무게로 나타냅니다. */}
                <button
                  type="button"
                  className={`btn ${asking === 'paper' ? 'btn-primary' : 'btn-heavy'}`}
                  ref={confirmRef}
                  onClick={() => void confirm()}
                  disabled={busy || failure?.kind === 'rejected'}
                >
                  {busy ? '바꾸는 중' : `${targetLabel}${ro(targetLabel)} 바꾸기`}
                </button>
              </div>
            </div>
          )}

          <AlertSettingsGroup />
        </>
      ) : (
        <>
          {needsCredentials && (
            <p className="settings-need">인증 정보를 입력하면 시작할 수 있습니다</p>
          )}
          <Credentials openUnusable={needsCredentials === true} />
        </>
      )}
    </Modal>
  )
}
