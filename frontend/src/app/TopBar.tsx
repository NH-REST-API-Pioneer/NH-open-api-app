import { ENVIRONMENT_LABEL, type Environment, type EnvironmentStatus } from '../data/environment'
import type { LaggingMarket, StreamState } from '../data/stream'
import type { ConnectionState, Page, Product, RecentItem, Theme } from '../lib/types'
import type { Market } from '../data/instruments'
import type { MasterState } from '../data/master'
import { SearchBox } from './SearchBox'
import { TextSizeMenu } from './TextSizeMenu'
import symbol from '../assets/nh-symbol.png'

/* 상단 띠 — 두 단입니다.
 *
 *   1단   브랜드 · 검색 · 모의/실전 · 연결 상태 · 마지막 시세 · 글씨 크기 · 테마 · 설정
 *   2단   화면 탭 다섯
 *
 * **오른쪽 덩어리는 「무거운 표시 → 상태 → 조작」 순서**입니다. 모의/실전이 가장
 * 무겁고(실전인데 모의인 줄 알고 낸 주문은 실제 계좌에 들어갑니다), 연결과 시세
 * 시각은 상태이며, 글씨 크기·테마·설정은 조작이라 모서리에 둡니다.
 *
 * 시장(국내 주간/야간/해외)을 고르는 띠는 없습니다. 앱 전역에 「지금 시장」이라는
 * 상태를 두지 않고, 국내와 해외가 갈리는 자리(계좌·종목)에서 그 화면이 직접
 * 고릅니다. 주간과 야간은 아예 고르지 않습니다 — 시계가 정하는 것을 사용자가
 * 맞추게 두면, 맞추지 못한 채로 주문이 다른 세션으로 나갑니다.
 */

const PAGES: { id: Page; label: string }[] = [
  { id: 'home', label: '홈' },
  { id: 'instruments', label: '종목' },
  { id: 'trade', label: '일반주문' },
  { id: 'strategy', label: '전략주문' },
  { id: 'account', label: '계좌' },
]

/* 연결 상태 셋.
 *
 * **「연결 실패」가 아니라 「연결 안 됨」입니다.** 「실패」는 시도가 실패한 것이고
 * 「끊김」은 있던 것이 끊어진 것인데, 우리가 아는 상태는 하나라 둘을 못 가릅니다 —
 * 「연결 안 됨」이 둘 다 맞고 나머지 둘은 각각 반쪽입니다. */
const CONNECTION: Record<ConnectionState, string> = {
  checking: '백엔드 확인 중',
  ok: '백엔드 연결됨',
  error: '백엔드 연결 안 됨',
}

/* 시세가 흐르는 길의 상태. **자리를 새로 만들지 않고 이 한 자리를 씁니다** —
 * 끊김에는 화면에 흔적이 있습니다(옆의 「마지막 시세」가 멈춥니다). 띠를 새로
 * 세우면 저장 실패 띠와 둘이 되어, 함께 뜨는 날 본문이 두 줄 밀립니다.
 *
 * **백엔드에 못 닿는 것이 먼저입니다.** 그때는 시세도 당연히 안 오므로 둘을
 * 같이 적으면 같은 사실을 두 번 말하게 됩니다.
 *
 * 다시 붙는 중과 끊김을 가릅니다 — 앞은 기다리면 되고 뒤는 눌러야 합니다.
 * 다시 붙은 뒤 조회를 다시 부르는 것은 **알리지 않습니다.** 사용자에게 알릴
 * 것은 끊겼다는 사실 하나이고, 복구 과정은 알릴 것이 아닙니다. */
const FEED: Partial<Record<StreamState, string>> = {
  live: '시세 연결됨',
  connecting: '시세 붙는 중',
  reconnecting: '시세 다시 붙는 중',
  stopped: '시세 연결 안 됨',
}

/* 「시세 연결됨」 뒤에 덧붙이는 시장 하나. 국내와 해외는 서버 쪽 연결이 따로라,
 * 한쪽이 다시 붙는 동안 다른 쪽은 그대로 받습니다 — 그때 전체를 「다시 붙는 중」
 * 으로 세우면 멀쩡한 쪽까지 끊긴 것으로 읽히고, 아무것도 안 세우면 끊긴 쪽이
 * 가려집니다. **끊긴 시장만 이름을 답니다.** */
const LAG_MARKET: Record<LaggingMarket['market'], string> = {
  domestic: '국내',
  overseas: '해외',
}

/* 덧붙임에서는 처음 붙는 것과 다시 붙는 것을 한 낱말로 적습니다. 다시 붙을 때는
 * 두 상태가 번갈아 오는데, 낱말이 바뀌면 덧붙임 길이가 따라 바뀌어 옆의 「마지막
 * 시세」가 그때마다 좌우로 밀립니다. 기다리면 된다는 뜻은 둘이 같습니다. */
const LAG_STATE: Partial<Record<StreamState, string>> = {
  connecting: '붙는 중',
  reconnecting: '붙는 중',
  stopped: '연결 안 됨',
}

interface Props {
  page: Page
  /** 서버가 답한 활성 환경. 아직 못 들었거나 서버도 모르면 `null` 입니다 —
   *  그때 실전이라고 세우지 않습니다. */
  environment: Environment | null
  environmentStatus: EnvironmentStatus
  theme: Theme
  connection: ConnectionState
  /** 실시간이 흐르는지. 백엔드에 닿는 것과 값이 오는 것은 다른 사실이라
   *  따로 받습니다 — 연결은 살아 있는데 값만 안 오는 상태가 가장 위험합니다. */
  feed?: StreamState
  /** 전체는 받고 있는데 아직 다 붙지 않은 시장. `feed` 가 `live` 일 때만 찹니다. */
  feedLagging?: readonly LaggingMarket[]
  /** 마지막으로 **시세가** 도착한 때(`HH:MM`). 아직 없으면 「—」. */
  lastQuote: string
  /** 장이 열려 있는데 새 시세가 2분 넘게 없는가(`quotesStalled`). */
  quoteStalled: boolean
  master: MasterState
  /** 최근 본 종목. 검색 창이 입력 전에 세웁니다. */
  recent: RecentItem[]
  onPageChange: (page: Page) => void
  settingsOpen: boolean
  onOpenSettings: () => void
  onOpenInstrument: (code: string) => void
  onOpenProduct: (market: Market, product: Product) => void
  onRecheck: () => void
  onToggleTheme: () => void
}

export function TopBar({
  page,
  environment,
  environmentStatus,
  theme,
  connection,
  feed,
  feedLagging = [],
  lastQuote,
  quoteStalled,
  master,
  recent,
  settingsOpen,
  onPageChange,
  onOpenSettings,
  onOpenInstrument,
  onOpenProduct,
  onRecheck,
  onToggleTheme,
}: Props) {
  const failed = connection === 'error'
  /* 백엔드는 닿는데 시세만 안 오는 상태. 이때도 누를 것이 생깁니다 —
     연결은 누를 때마다 답이 달라질 수 있습니다. */
  const feedLost = !failed && connection === 'ok' && feed === 'stopped'
  const feedLabel = feed ? FEED[feed] : undefined
  const lagText = feedLagging
    .flatMap(({ market, state }) => {
      const word = LAG_STATE[state]
      return word ? [`${LAG_MARKET[market]} ${word}`] : []
    })
    .join(' · ')
  /* 끊긴 때는 연결 표시가 이미 말하므로 시각을 겹쳐 칠하지 않습니다. */
  const stalled = quoteStalled && !failed && !feedLost

  return (
    <header className="topbar">
      <div className="topbar-main">
        {/* 로고를 누르면 홈으로 갑니다. 어느 화면에서 길을 잃어도 왼쪽 위로
            돌아오면 처음 화면이라는 것이, 여기서도 그대로여야 합니다.
            마크와 이름은 함께 하나의 이름이라 따로 읽히지 않고, 대신 단추
            전체에 「홈으로」라는 이름을 답니다. */}
        <button
          type="button"
          className="brand"
          aria-label="홈으로 이동"
          onClick={() => onPageChange('home')}
        >
          <img className="brand-mark" src={symbol} alt="" aria-hidden="true" />
          <span className="brand-name">NH FUTURES API</span>
        </button>

        {/* 검색은 **로고 바로 오른쪽**입니다. 가운데 남는 폭은 비워 둡니다 —
            채우려고 무언가를 넣으면 늘 서 있는 비용이 되고, 창이 좁아질 때
            줄어드는 것도 그 빈 폭이라 알약은 그대로 남습니다. */}
        <SearchBox
          master={master}
          recent={recent}
          onOpenInstrument={onOpenInstrument}
          onOpenProduct={onOpenProduct}
        />

        <div className="topbar-right">
          {/* 실전 쪽이 무겁습니다. 실전인데 모의인 줄 알고 낸 주문은 실제 계좌에
              들어가고, 반대는 손해가 없습니다 — 위험이 한쪽으로 쏠려 있으니
              표시도 그쪽이 무거워야 합니다.
              색은 안 씁니다. 빨강은 하락·매도와 부딪히고 초록은 「지금 여기」의
              뜻이 흐려집니다. 채움과 테두리로 가릅니다.
              전환은 설정에서만 합니다 — 손이 닿는 자리에 두면 잘못 눌립니다. */}
          {/* 값은 서버가 답한 것뿐입니다. 아직 못 들었으면 자리만 잡아 둡니다 —
              값이 오는 순간 오른쪽 덩어리가 움직이지 않게 배지와 같은 폭입니다.
              서버도 모른다고 하면 그렇다고 세웁니다. 「곧 온다」는 뼈대를 그때도
              남기면 거짓입니다. */}
          {environment !== null ? (
            <span className={`badge env-badge${environment === 'paper' ? ' env-sim' : ' env-live'}`}>
              {ENVIRONMENT_LABEL[environment]}
            </span>
          ) : environmentStatus === 'failed' ? (
            <span className="badge env-badge badge-warn">확인 안 됨</span>
          ) : (
            <span
              className="env-badge env-skeleton"
              role="status"
              aria-label="모의인지 실전인지 확인하는 중"
            />
          )}

          {/* 끊겼을 때만 눌립니다. 정상일 때 단추 모양이면 「눌러야 하나」가
              생기는데, 누를 일이 없습니다. 「다시 확인」은 「다시 받기」 규칙과
              안 부딪힙니다 — 그건 눌러도 같은 결과가 나오는 단추를 막는 것이고,
              연결은 누를 때마다 답이 달라질 수 있습니다. */}
          {failed || feedLost ? (
            <button type="button" className="conn conn-error" onClick={onRecheck}>
              <span className="conn-dot conn-dot-error" aria-hidden="true" />
              {failed ? CONNECTION.error : FEED.stopped}
              <span className="conn-again">다시 확인</span>
            </button>
          ) : (
            <span className="conn">
              <span className="conn-dot" aria-hidden="true" />
              {/* **시세가 흐르는 것이 「확인 중」보다 강한 증거입니다.** 그
                  연결은 같은 서버로 난 길이라, 값이 오고 있으면 서버에 닿는다는
                  뜻입니다. 그래서 확인이 도는 동안(`checking`)에는 시세 낱말이
                  앞섭니다 — 30초마다 한 번씩 「확인 중」이 시세 낱말을 덮으면
                  멀쩡한 화면이 주기적으로 흔들립니다.
                  **덮는 것은 「확인 중」 하나뿐입니다.** 백엔드가 안 닿는 것으로
                  판명된 때는 시세가 흐르고 있어도 그쪽을 세웁니다 — 소켓은 열린
                  채 값만 멈추고 확인만 실패하는 조합이 있는데, 그때 「연결됨」이
                  서면 **진짜 고장을 가려 줍니다.**
                  앱을 켠 직후처럼 아직 아무것도 모를 때는 그대로 확인 중입니다 —
                  그때는 시세도 안 붙어 있어 이 조건에 안 걸립니다. */}
              {(connection === 'ok' || (connection === 'checking' && feed === 'live')) &&
              feedLabel ? (
                <>
                  {feedLabel}
                  {/* 글자색만 바꿉니다 — 기다리면 붙는 일이라 누를 단추로 만들지
                      않습니다. 앞의 공백은 화면 읽기 프로그램이 「연결됨」과
                      덧붙임을 한 낱말로 붙여 읽지 않게 합니다. */}
                  {lagText && (
                    <>
                      {' '}
                      <span className="conn-lag">· {lagText}</span>
                    </>
                  )}
                </>
              ) : (
                CONNECTION[connection]
              )}
            </span>
          )}

          {/* **상시 보입니다.** 「연결됨」과 「값이 오고 있음」은 갈리는데, 연결은
              살아 있고 값만 안 오는 상태가 가장 위험하고 그때 이 시각이 유일한
              단서입니다. 그래서 무엇의 시각인지를 이름에 적습니다 — 계좌 띠의
              「마지막 갱신」은 계좌 값의 시각이라 섞이면 안 됩니다. 장이 열려
              있는데 2분 넘게 새 시세가 없으면 시각을 경고색으로 칠합니다. 분
              단위라 눈이 값을 좇지 않습니다. */}
          <span
            className="conn-updated"
            title={stalled ? '2분 넘게 새 시세가 없습니다' : undefined}
          >
            마지막 시세{' '}
            <span className={`conn-time${stalled ? ' is-stalled' : ''}`}>{lastQuote}</span>
          </span>

          <TextSizeMenu />

          <button
            type="button"
            className="icon-btn"
            onClick={onToggleTheme}
            aria-label={theme === 'dark' ? '밝은 화면으로' : '어두운 화면으로'}
            title={theme === 'dark' ? '밝은 화면으로' : '어두운 화면으로'}
          >
            {theme === 'dark' ? '☀' : '☾'}
          </button>

          <button
            type="button"
            className="icon-btn"
            onClick={onOpenSettings}
            aria-label="설정"
            title="설정"
            aria-expanded={settingsOpen}
          >
            ⚙
          </button>
        </div>
      </div>

      {/* 탭을 아래 단으로 내립니다. 1단이 검색과 상태를 함께 이고 있어, 탭까지
          한 줄에 두면 화면을 옮기는 자리와 지금 상태를 읽는 자리가 섞입니다. */}
      <nav className="topbar-tabs" aria-label="화면">
        {PAGES.map((item) => (
          <button
            key={item.id}
            type="button"
            className="tab tab-page"
            aria-current={page === item.id}
            onClick={() => onPageChange(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>
    </header>
  )
}
