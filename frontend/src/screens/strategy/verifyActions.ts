import { attentionEndWhy, sendEach, type VerifyRun } from '../../data/strategyRuns'
import { actOnRun, deleteRun, patchVerify, stopAllRuns } from '../../data/strategyStore'
import type { MarkPick } from './MarkPopover'
import { PICK_HINT, targetsOf } from './runStats'
import type { Dispatch, SetStateAction } from 'react'
import type { useVerifyRun } from './useVerifyRun'
import { DEEDS, DEED_KEY, DEED_LABEL, DEED_VERB, type Deed } from './strategyVerifyUtils'

type RunValues = ReturnType<typeof useVerifyRun>

/** 일괄 동작 — 고른 실행들, 동작마다 막히는 까닭, 확인 뒤 보내기, 실행 고르기. */
export function makeVerifyActions({
  all,
  checked,
  acting,
  setDeed,
  setWhy,
  setWhyWarn,
  setPickedId,
  setMarkPick,
}: {
  all: RunValues['all']
  checked: string[]
  acting: string | null
  setDeed: Dispatch<SetStateAction<Deed | null>>
  setWhy: Dispatch<SetStateAction<string | null>>
  setWhyWarn: Dispatch<SetStateAction<boolean>>
  setPickedId: (id: string) => void
  setMarkPick: Dispatch<SetStateAction<MarkPick | null>>
}) {
  /* 「선택 …」 단추의 대상 — **체크한 실행만**(`targetsOf`). 차트에 띄운 실행은
     대상이 아닙니다: 클릭 한 번에 바뀌는 것이라 청산·종료의 대상으로 삼지
     않습니다. 체크는 보는 실행을 바꾸지 않습니다 — 여럿을 고른 채 하나를 차트에
     띄워 볼 수 있어야 합니다. 대상 문장과 확인 창이 이 하나를 씁니다. */
  const chosen = targetsOf(all, checked)
  const toggleCheck = (id: string) =>
    patchVerify({ checked: checked.includes(id) ? checked.filter((x) => x !== id) : [...checked, id] })

  /* 중지·재개는 한 단추입니다. 고른 것이 **전부 중지**면 「재개」, 아니면
     「중지」이고 그때 이미 중지된 줄은 빠집니다. */
  const toggleDeed: Deed =
    chosen.length > 0 && chosen.every((run) => run.state === 'paused')
      ? '선택 검증 재개'
      : '선택 검증 중지'

  /* 그 동작에서 한 줄이 빠지는 까닭. 빠지지 않으면 `null` 입니다.
     **서버 판정을 화면이 다시 하는 것이 아니라, 서버가 준 줄의 값으로 가립니다** —
     상태와 보유는 방송이 실어 주는 사실이고, 그 사실로 이미 아는 것을 요청해
     400 을 받아 보게 하지 않습니다. 그래도 막는 최종 판정은 서버이고, 거절
     문장은 그대로 화면에 섭니다.
     「확인 필요」 줄에는 「실행 종료」 말고는 어떤 요청도 보내지 않습니다 —
     사용자가 먼저 풀어야 하는 자리입니다. 종료는 계좌로 나가는 요청이 없어, 남은
     것이 없으면 보냅니다(`attentionEndWhy`). 끝난 실행에는 지우는 것 말고는 걸
     것이 없습니다. */
  function skipWhy(action: Deed, run: VerifyRun): string | null {
    if (run.state === 'attention') {
      if (action !== '실행 종료') return '확인이 필요한 실행에는 요청을 보내지 않습니다'
      return acting === run.id ? '보낸 요청을 기다리는 중입니다' : attentionEndWhy(run)
    }
    if (acting === run.id) return '보낸 요청을 기다리는 중입니다'
    if (action === '실행삭제') return run.state === 'ended' ? null : '끝난 실행만 지웁니다'
    if (run.state === 'ended') return '끝난 실행입니다'
    if (action === '선택 검증 중지') {
      return run.state === 'paused' ? `${run.stateLabel} — 이번 요청에서 제외` : null
    }
    if (action === '선택 검증 재개') return null
    if (action === '실행 종료') {
      return run.position !== 0 ? '「선택 전략 청산」을 먼저 하세요' : null
    }
    return run.position === 0 ? '보유가 없습니다' : null
  }

  /* 단추를 못 누르는 까닭. **나갈 줄이 하나라도 있으면 누를 수 있습니다** —
     빠지는 줄은 확인 창이 까닭과 함께 보입니다. 전부 빠지면 빠진 까닭을
     단추 아래에 적습니다. */
  function whyFor(action: Deed): string | null {
    /* 도는 실행이 아예 없으면 단추 전부가 **같은 사실 하나** 때문에 막힙니다.
       「고른 실행이 없습니다」로 적으면 「검증 신규 진입 중지」만 다른 말을
       해서, 같은 사실이 까닭 두 줄로 갈립니다. */
    if (all.length === 0) return '도는 검증이 없습니다'
    if (action === '검증 신규 진입 중지') return null
    if (chosen.length === 0) return PICK_HINT
    const skips = chosen.map((run) => skipWhy(action, run))
    if (skips.some((one) => one === null)) return null
    return [...new Set(skips as string[])].join(' · ')
  }

  /* 단추 다섯과 못 누르는 까닭. **단추와 까닭 줄이 한 목록에서 나옵니다** —
     따로 두면 `aria-describedby` 가 없는 줄을 가리키게 됩니다. */
  const acts = [toggleDeed, ...DEEDS].map((deed) => ({
    id: DEED_KEY[deed],
    label: DEED_LABEL[deed],
    why: whyFor(deed),
    deed,
  }))
  const stops = acts.filter((one) => one.why !== null)
  /* 막힌 단추를 **까닭으로 묶습니다** — 다섯이 같은 말을 되풀이하면 목록보다
     까닭이 깁니다. 한 까닭이 막힌 단추 전부를 덮으면 어느 단추의 말인지 적을
     것이 없어 까닭만 세우고, 까닭이 갈리면 그 까닭이 덮는 단추 이름을 앞에
     답니다. 줄의 `id` 는 그 묶음의 첫 단추 이름으로 섭니다. */
  const groups = [...new Set(stops.map((one) => one.why as string))].map((why) => {
    const held = stops.filter((one) => one.why === why)
    return { why, ids: held.map((one) => one.id), names: held.map((one) => one.label) }
  })
  const whyIdOf = (id: string) =>
    `vrf-why-${groups.find((group) => group.ids.includes(id))?.ids[0] ?? id}`

  /** 확인 창에서 단추를 누른 뒤. 고른 것 가운데 **빠지지 않는 줄에 차례로**
   *  보내고, 하나가 거절돼도 나머지는 보냅니다. 결과는 「N건 중 K건 거절 — 첫
   *  서버 문장」 한 줄입니다(진행 화면과 같은 셈, `sendEach`). */
  async function commit(action: Deed) {
    setDeed(null)
    if (action === '검증 신규 진입 중지') {
      /* 이 탭의 전체 중지는 **종이 실행만** 멈춥니다 — 계좌 실행은 진행 탭의 것입니다. */
      const said = await stopAllRuns(['paper'])
      const warned = typeof said === 'object' && 'warn' in said
      setWhy(typeof said === 'string' ? said : warned ? said.warn : null)
      setWhyWarn(warned)
      return
    }
    const verb = DEED_VERB[action]
    const sending = chosen.filter((run) => skipWhy(action, run) === null)
    setWhyWarn(false)
    setWhy(
      await sendEach(sending, (run) =>
        verb === undefined ? deleteRun(run.id) : actOnRun(run.id, verb),
      ),
    )
  }

  /* 줄 몸을 누르면 그 실행을 봅니다. 열려 있던 마커 상세는 닫습니다 — 그
     상세는 앞 실행의 체결이라, 남겨 두면 다른 실행 위에 남의 체결이 떠 있게
     됩니다. */
  function pickRun(id: string) {
    setPickedId(id)
    setMarkPick(null)
  }

  return {
    chosen,
    toggleCheck,
    skipWhy,
    acts,
    groups,
    whyIdOf,
    commit,
    pickRun,
  }
}
