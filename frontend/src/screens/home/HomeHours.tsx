import { MARKET_LINES, marketLineHours } from '../../data/session'

/** 장 시간 띠. 시장 셋의 시간과 새로고침 단추·갱신 시각. */
export function renderHomeHours({
  loading,
  load,
  updatedAt,
}: {
  loading: boolean
  load: () => void
  updatedAt: string
}) {
  return (
      <section className="home-hours" aria-label="장 시간">
        {/* 띠를 **미는 자리와 안 미는 자리**로 가릅니다. 좁아지면 이 트랙만
            줄어들고, 오른쪽 덩어리는 제자리에 섭니다 — 띠가 좁아질 때 양보하는
            것은 보조 설명이고, 길을 여는 조작과 값은 양보하지 않습니다. */}
        <div className="home-hours-track">
          {MARKET_LINES.map((item) => (
            <span key={item.key} className="home-hour">
              <span className="conn-dot" aria-hidden="true" />
              <span className="home-hour-name">{item.label}</span>
              <span className="home-hour-time">{marketLineHours(item.key)}</span>
            </span>
          ))}
          {/* 세 줄이 적는 것은 **그 시장이 열려 있는 폭**이고, 그 안이 내내 열려
              있는 것은 아닙니다. 그 사실을 띠에 **한 번만** 답니다 — 줄마다 달면
              같은 말이 셋이 되고, 한 종목의 시각을 더 말해 주지도 않습니다.
              자리는 설명하는 대상 바로 뒤이고, 트랙에서 줄어드는 몫은 이 마디가
              집니다 — 줄 셋은 줄면 시각이 잘립니다. */}
          <span className="home-hours-note" title="종목 시간은 그 종목 화면에">
            종목 시간은 그 종목 화면에
          </span>
        </div>

        {/* 안 미는 덩어리. 다시 받는 길과 그 값이 언제 것인지는 창이 좁다고
            사라지면 안 됩니다 — 옆으로 굴려야 나오는 단추는 없는 것과 같습니다. */}
        <div className="home-hours-fixed">
          {/* 받는 동안 잠급니다 — 먼저 나간 요청은 취소되지 않아, 연달아 누르면
              호출 예산만 먹습니다. 잠긴 동안 무엇을 기다리는지도 단추가 말합니다.
              **이 단추가 부르는 것은 관심종목뿐입니다** — 계좌·주문 카드는 아직
              부를 곳이 없어 이 누름이 바꿀 것이 없습니다. */}
          <button
            type="button"
            className={`btn home-refresh ${loading ? '' : 'btn-outline'}`.trim()}
            disabled={loading}
            onClick={load}
          >
            {loading ? '불러오는 중' : '새로고침'}
          </button>
          <span className="as-of">{updatedAt && `갱신 ${updatedAt}`}</span>
        </div>
      </section>
  )
}
