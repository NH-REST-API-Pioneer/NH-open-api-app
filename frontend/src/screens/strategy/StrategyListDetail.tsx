import { accountOf, instrumentNameOf, type StrategyVersion } from '../../data/strategyList'
import type { Aux } from '../../data/strategyRules'
import { Modal } from '../../app/Modal'
import {
  Money,
  Pl,
  Blank,
  versionOnly,
  amount,
  count,
  objectMark,
} from './strategyListParts'
import type { Dispatch, SetStateAction } from 'react'
import type { makeListStats } from './listStats'
import type { useListView } from './useListView'

type ListStats = ReturnType<typeof makeListStats>
type ViewValues = ReturnType<typeof useListView>

/** 오른쪽 칸 — 고른 버전의 상세. */
export function renderListDetail({
  selected,
  nameText,
  onOpenSettings,
  accountEnvironments,
  auxOf,
  selectedCurrency,
  recent,
  onOpenCheck,
  onOpenRun,
}: {
  selected: StrategyVersion | null
  nameText: ListStats['nameText']
  onOpenSettings: () => void
  accountEnvironments: ListStats['accountEnvironments']
  auxOf: (id: string) => Aux
  selectedCurrency: ViewValues['selectedCurrency']
  recent: ViewValues['recent']
  onOpenCheck: () => void
  onOpenRun: () => void
}) {
    if (!selected) {
      return (
        <div className="notice">
          <p className="notice-title">고른 전략이 없습니다</p>
          <p className="notice-reason">표에서 한 줄을 고르면 여기에 섭니다</p>
        </div>
      )
    }
    return (
      <>
        {/* **이름과 버전이 먼저 붙습니다.** 둘은 「무엇을 보고 있나」 한 덩이라,
            사이에 단추가 끼면 버전이 단추에 딸린 값처럼 읽힙니다. */}
        <div className="stg-detail-head">
          <h2 className={`stg-detail-name${selected.name.trim() ? '' : ' is-nameless'}`}>{nameText(selected)}</h2>
          <span className="badge">{selected.status}</span>
        </div>
        <p className="stg-detail-version">{versionOnly(selected.version)}</p>
        {/* **이름·종목을 고치는 자리는 설정 하나**입니다. 목록은 고르는
            자리라 여기서도 고쳐지면 잘못 눌러 이름이 바뀝니다 — 어디로
            가야 하는지만 알려 주고 보냅니다. 이름 덩이 아래에 섭니다. */}
        <button type="button" className="btn btn-quiet stg-detail-edit" onClick={onOpenSettings}>
          설정에서 고치기
        </button>
        <p className="stg-detail-summary">{selected.summary}</p>

        <h3 className="stg-detail-title">실행 정보</h3>
        <dl className="stg-sheet">
          <div className="stg-sheet-row">
            <dt>시장 · 종목</dt>
            <dd>{instrumentNameOf(selected)}</dd>
          </div>
          <div className="stg-sheet-row">
            <dt>연결 계좌</dt>
            {/* 그 버전이 **지금 계좌 실행으로 붙어 있는 계좌**입니다(실행이 세운 환경,
                모의 다음 실전). 접속 환경으로 채우지 않습니다 — 모의로만 돈 전략에
                「실전」이 서면 실전 계좌로 거래한 것으로 읽힙니다. 끝나지 않은 계좌
                실행이 없으면 「—」입니다. */}
            <dd>
              {(() => {
                const envs = accountEnvironments(selected.id)
                /* 묶음 사이는 쉼표입니다 — 「모의 · 국내 · 실전 · 국내」는 가운뎃점이 안팎에
                   같아 네 항목으로 읽힙니다. */
                return envs.length === 0 ? '—' : envs.map((one) => accountOf(selected.market, one)).join(', ')
              })()}
            </dd>
          </div>
          {/* 셋 다 **설정에서 고치는 값**이라 설정에서 읽습니다. 아직 안 정했으면
              「—」입니다 — 0 으로 적으면 「한도 없음」으로 읽히는데 그것과 「안
              정했다」는 다른 말입니다. */}
          <div className="stg-sheet-row">
            <dt>증거금 예산</dt>
            <dd>{amount(auxOf(selected.id).marginBudget, selectedCurrency)}</dd>
          </div>
          <div className="stg-sheet-row">
            <dt>하루 손실</dt>
            <dd>{amount(auxOf(selected.id).dailyLoss, selectedCurrency)}</dd>
          </div>
          <div className="stg-sheet-row">
            <dt>주문</dt>
            <dd>{count(auxOf(selected.id).perOrder, '계약')}</dd>
          </div>
        </dl>

        <h3 className="stg-detail-title">
          최근 성과 <span className="stg-detail-range">(최근 30일)</span>
        </h3>
        <dl className="stg-sheet">
          <div className="stg-sheet-row">
            <dt>순손익</dt>
            <dd>
              {recent?.pl == null ? <Blank /> : <Pl value={recent.pl} currency={selectedCurrency} />}
            </dd>
          </div>
          <div className="stg-sheet-row">
            <dt>승률</dt>
            <dd>{recent?.winRate == null ? <Blank /> : `${recent.winRate}% (${recent.trades}건)`}</dd>
          </div>
          <div className="stg-sheet-row">
            <dt>최대 낙폭</dt>
            <dd>
              {recent?.maxDrawdown == null ? (
                <Blank />
              ) : (
                <Money value={recent.maxDrawdown} currency={selectedCurrency} />
              )}
            </dd>
          </div>
        </dl>

        {/* 셋 다 화면을 옮기는 일이라 채운 단추는 쓰지 않습니다 — 채움은
            되돌릴 수 없는 동작의 것이고, 화면 이동은 되돌아오면 그만입니다.
            다만 셋 중 하나만 초록입니다. 고른 전략으로 이어서 할 일은 설정을
            여는 것이고, 검증·진행은 그 다음에 가는 자리입니다. 셋을 다 초록으로
            두면 어디로 가야 할지를 화면이 말하지 않게 됩니다. */}
        <div className="stg-detail-actions">
          <button type="button" className="btn btn-outline" onClick={onOpenSettings}>
            전략 설정 열기
          </button>
          <button type="button" className="btn btn-quiet" onClick={onOpenCheck}>
            검증 화면으로
          </button>
          <button type="button" className="btn btn-quiet" onClick={onOpenRun}>
            진행 화면으로
          </button>
        </div>
      </>
    )
}

/** 삭제 확인 창. 고른 버전이 있고 창이 열렸을 때만 부릅니다. */
export function renderDeleteConfirm({
  selected,
  liveOf,
  rows,
  setDeleting,
  nameText,
  confirmRemove,
}: {
  selected: StrategyVersion
  liveOf: ListStats['liveOf']
  rows: StrategyVersion[]
  setDeleting: Dispatch<SetStateAction<boolean>>
  nameText: ListStats['nameText']
  confirmRemove: () => void
}) {
          const live = liveOf(selected.id)
          const last = rows.filter((one) => one.groupId === selected.groupId).length === 1
          return (
            <Modal
              label="전략 삭제"
              onClose={() => setDeleting(false)}
              head={<span className="modal-title">전략 삭제</span>}
              /* 답을 받아야 하는 창이라 바깥을 눌러도 안 닫힙니다. Esc 는 그만두기입니다. */
              dismissable={false}
              closable={false}
            >
              <p className="stg-delete-lead">
                {nameText(selected)} {versionOnly(selected.version)}
                {objectMark(versionOnly(selected.version))} 지웁니다
              </p>
              <dl className="run-confirm">
                <div className="run-confirm-row">
                  <dt>거래 기록</dt>
                  <dd>{(selected.trades ?? 0).toLocaleString('ko-KR')}건</dd>
                </div>
              </dl>
              {/* 지우는 것은 그 버전과 설정뿐이고 거래 기록 파일은 서버가 건드리지
                  않습니다. 그 전략의 마지막 버전이면 목록에서 전략이 사라지는 것도 먼저
                  말합니다. */}
              {last && <p className="stg-delete-note">마지막 버전이라 전략이 목록에서 사라집니다</p>}
              <p className="stg-delete-note">기록은 분석에 남습니다</p>
              {live.total > 0 && (
                <p className="stg-delete-warn">끝나지 않은 실행 {live.total}개가 있어 지울 수 없습니다 — 먼저 종료하세요</p>
              )}
              <div className="run-confirm-acts">
                <button type="button" className="btn btn-quiet" onClick={() => setDeleting(false)}>
                  그만두기
                </button>
                <button
                  type="button"
                  className="btn btn-heavy"
                  aria-disabled={live.total > 0}
                  onClick={confirmRemove}
                >
                  삭제
                </button>
              </div>
            </Modal>
          )
}
