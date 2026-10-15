import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import type {
  ConnectionState,
  MarketContext,
  OpenIntent,
  Page,
  Product,
  RecentItem,
  Theme,
} from './lib/types'
import { canSwitchTo, checkHealth, loadConfig, marketConfigured, useEnvironment } from './data/environment'
import { loadTimetable } from './data/session'
import { resolve, type Market } from './data/instruments'
import { loadMaster, masterState } from './data/master'
import { useLastQuoteLabel } from './data/lastQuote'
import { closeStream, openStream, quotesStalled, useStreamStatus, useWishes, type Wish } from './data/stream'
import { guardUnload, loadUiState, subscribeUi, uiState } from './data/uiState'
import { useMasterStatus } from './lib/useMaster'
import { useStoredState } from './lib/useStoredState'
import { TopBar } from './app/TopBar'
import { SideBar } from './app/SideBar'
import { AccountScreen } from './screens/account/AccountScreen'
import { HomeScreen } from './screens/home/HomeScreen'
import { SettingsModal } from './screens/settings/SettingsModal'
import { InstrumentsScreen } from './screens/instruments/InstrumentsScreen'
import { TradeScreen } from './screens/trade/TradeScreen'
import { StrategyScreen } from './screens/strategy/StrategyScreen'
import { LeaveGuard } from './screens/strategy/LeaveGuard'
import { hasUnsaved, openRunTab, revertDrafts } from './data/strategyStore'
import { Toasts } from './app/Toasts'
import { ScreenBoundary } from './app/ScreenBoundary'
import { notifyTargets } from './data/alerts'
import './app/shell.css'

/* 앱 셸.
 *
 * 컨텍스트를 바꿔도 페이지는 그대로 있습니다. 앱이 사용자 몰래 종목을
 * 바꾸는 경우는 없습니다.
 */

/** 최근 본에 남기는 종목 수. 모달과 사이드바가 그 앞쪽만 보입니다. */
const RECENT_KEPT = 20

function App() {
  /* 테마. **기본은 어두움**이고 사용자가 고른 값이 남습니다.
     첫 그리기 전에 `index.html` 이 같은 값을 읽어 `data-theme` 을 붙입니다 —
     여기서만 붙이면 그 일이 첫 그리기 **뒤**라 밝은 화면이 한 번 번쩍입니다. */
  const [theme, setTheme] = useStoredState<Theme>('nh.theme', 'dark')
  /* 사용자 홈 파일에 남는 값들. 도착해야 화면을 그립니다. */
  const ui = useSyncExternalStore(subscribeUi, uiState)
  /* 지금 모의인지 실전인지는 **서버가 답한 값**입니다. 화면이 따로 들고 있지
     않습니다 — 화면이 믿는 것과 요청이 나가는 환경이 갈리면 모의인 줄 알고 낸
     주문이 실전 계좌로 갑니다. 읽기 전에는 실전이라고 가정하지 않습니다. */
  const environment = useEnvironment()
  /* 설정은 화면이 아니라 떠 있는 카드입니다. 보던 화면을 잃지 않습니다. */
  const [settingsOpen, setSettingsOpen] = useState(false)
  /* 활성 환경에 **쓸 수 있는 시장이 하나도 없는지**. 국내나 해외 한쪽만 채운 것은
     그 시장만 쓰기로 고른 것이라 틀린 상태가 아닙니다 — 빈 시장은 그 시장을 쓰려는
     자리(계좌·일반주문)가 저마다 말합니다. 접속 환경을 모르면 쓸 수 있는 시장도
     없습니다. 설정을 아직 못 읽었으면 「없다」고 하지 않습니다 — 못 읽은 것과 안
     채운 것은 다릅니다. */
  const activeEnv = environment.config?.active_environment ?? null
  const needsCredentials =
    environment.config !== null && (activeEnv === null || !canSwitchTo(environment.config, activeEnv))
  /* 처음 켰을 때 쓸 수 있는 인증 정보가 없으면 설정을 열어 그 자리로 데려갑니다.
     안 그러면 빈 화면을 보고 어디서 무엇을 넣어야 하는지 찾아다니게 됩니다.
     **켤 때 한 번만 봅니다** — 환경을 바꾼 뒤나 저장한 뒤에 창이 저절로 열리면
     방해입니다. */
  const askedOnceRef = useRef(false)
  useEffect(() => {
    if (environment.config === null || askedOnceRef.current) return
    askedOnceRef.current = true
    if (needsCredentials) setSettingsOpen(true)
    // 설정이 처음 도착한 때만 봅니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [environment.config])
  const [context, setContext] = useState<MarketContext>('domestic-day')
  /* 계좌 화면이 보는 시장. **일반주문·종목 화면의 시장과 따로 갑니다** — 해외 종목을
     보다가 계좌에 들어와도 계좌는 마지막으로 본 시장 그대로 열리고, 계좌에서
     시장을 바꿔도 다른 화면은 따라가지 않습니다. 특정 시장으로 여는 길(홈의
     「더 보기」)만 그 시장으로 열고 여기에 남깁니다. */
  const [storedAccountMarket, setAccountMarket] = useStoredState<string>('nh.account.market', 'domestic')
  const accountMarket: Market = storedAccountMarket === 'overseas' ? 'overseas' : 'domestic'

  /* **계좌의 주문/체결 알림은 앱이 한 곳에서 겁니다.** 어느 화면에 있든(홈·계좌·
     일반주문) 앱 밖에서 낸 주문의 체결까지 와야, 보고 있는 목록이 따라옵니다.
     활성 환경에서 인증 정보가 찬 시장마다 한 줄입니다 — 빈 시장은 서버가 토큰부터
     못 받습니다. 국내는 주간·야간이 같은 계좌라 **주간 맥락 하나로** 겁니다. 서버는
     주간·야간 알림을 한 열쇠로 모아(`feeds.py`) 세션이 바뀌어도 다시 걸 까닭이
     없습니다. */
  const orderWishes = useMemo<Wish[]>(() => {
    const view = environment.config
    const env = view?.active_environment ?? null
    if (view === null || env === null) return []
    return (['domestic', 'overseas'] as const)
      .filter((market) => marketConfigured(view, env, market))
      .map((market) => ({ context: market === 'overseas' ? 'overseas' : 'domestic-day', kind: 'orders', sym: '' }))
  }, [environment.config])
  useWishes('account-orders', orderWishes)
  // 첫 화면은 홈입니다. 계좌가 붙어 있으니 내 돈이 지수보다 먼저입니다.
  const [page, setPage] = useState<Page>('home')
  /* 홈에 **온 횟수**. 홈 탭·로고를 누를 때마다 오릅니다 — 이미 홈에 있어도
     오릅니다. 홈은 열 때마다 관심종목을 다시 받는 화면이라, 「홈에 있는데 홈을
     또 눌렀다」도 「지금 값이 궁금하다」이고 그 신호가 페이지 값에는 없습니다. */
  const [homeVisit, setHomeVisit] = useState(0)
  /* 저장 안 한 전략 설정을 두고 **상단 페이지를** 떠나려 할 때 붙잡는 자리.
     하위 탭과 같은 창을 씁니다 — 나가는 길이 둘인데 한쪽에만 경고가 붙으면,
     사용자는 어느 길이 안전한지를 외워야 합니다(원본 §14). */
  const [leavingPage, setLeavingPage] = useState<Page | null>(null)
  const pageRef = useRef(page)
  pageRef.current = page
  /* 계좌의 어느 탭을 보고 있는지. 계좌 안이 아니라 여기에 두는 이유는,
     홈의 「더 보기」처럼 특정 탭을 보러 들어오는 길이 있어서입니다. */
  const [accountTab, setAccountTab] = useState('잔고')
  const [productCode, setProductCode] = useState<string | null>(null)
  /* 최근 본은 **사용자가 실제로 연 것만** 쌓입니다. 미리 채워 두면 열어 본 적
     없는 종목이 서고, 그 코드가 마스터에 없으면 사이드바가 풀리지 않는 줄을
     보이게 됩니다.
     **저장하는 것은 코드뿐입니다.** 이름은 마스터가 정하는 값이라, 저장해 두면
     상장이 바뀌었을 때 옛 이름이 새 이름인 척합니다 — 코드만 남기고 이름은
     열 때마다 색인에서 받습니다. 앱을 껐다 켜도 남는 것은 「무엇을 봤나」이지
     값이 아니라, 낡지 않습니다. */
  const [recentCodes, setRecentCodes] = useStoredState<string[]>('nh.recent', [])
  /* 최근 본의 **가장 새 값**. 여는 때와 지울 때 둘 다 여기서 셉니다 — 그린 때의
     목록을 붙잡고 셈하면, 한 틱 안에 두 번 바꿀 때 앞에서 뺀 코드가 뒤의 저장에
     되살아납니다. */
  const recentRef = useRef(recentCodes)
  recentRef.current = recentCodes
  const saveRecent = useCallback(
    (next: string[]) => {
      recentRef.current = next
      setRecentCodes(next)
    },
    [setRecentCodes],
  )
  /* 최근 본에서 한 종목을 뺍니다. **담긴 목록에서 그 코드만** 뺍니다 — 화면에
     세운 줄(색인에 있는 것만)로 다시 지으면, 지금 안 보이는 코드까지 말없이
     사라집니다. 차례는 그대로입니다. */
  const removeRecent = useCallback(
    (code: string) => saveRecent(recentRef.current.filter((item) => item !== code)),
    [saveRecent],
  )
  const [connection, setConnection] = useState<ConnectionState>('checking')
  /* 일반주문이 열 종목. **코드 하나입니다** — 선물인지 옵션인지, 어느 시장인지,
     어느 만기인지가 전부 코드에서 나오므로 여기서 따로 들고 있지 않습니다. */
  const [openedCode, setOpenedCode] = useState<string | null>(null)
  const [openedIntent, setOpenedIntent] = useState<OpenIntent | null>(null)

  /* 종목 마스터를 앱을 켤 때 한 번 받습니다. 화면에 서는 품목과 종목이 전부
     여기서 나오므로, 받기 전에는 목록이 비어 있고 그 사실을 화면이 말합니다. */
  const master = useMasterStatus()
  /* 시세가 흐르는지. 상단이 백엔드 연결과 나란히 보입니다 — 연결은 살아 있는데
     값만 안 오는 상태가 가장 위험합니다. */
  const feed = useStreamStatus()
  useEffect(() => {
    void loadUiState()
    void loadMaster()
    /* 활성 환경과 인증 정보 상태. 값을 담는 자리들은 이것이 오기 전에는 조회를
       내지 않습니다 — 어느 계좌의 값이 될지 모르는 채로 받으면 이름이 없습니다. */
    void loadConfig()
    /* 거래시간표. 헤더의 「주간 08:45~15:45」 같은 문자열이 여기서 나옵니다 —
       하루 한 번 서버가 받아 두는 표라 앱을 켤 때 한 번 읽습니다. */
    void loadTimetable()
    /* 실시간은 **앱에 연결 하나**입니다. 화면마다 열면 같은 종목에 구독이 여러
       번 걸리고, 서버가 한 번에 들 수 있는 자리가 그만큼 빨리 찹니다. 무엇을
       받을지는 화면이 그때그때 알립니다. */
    openStream()
    /* 화면 상태를 파일에 못 남긴 채 창을 닫으려 하면 한 번 되묻습니다. */
    const unguard = guardUnload()
    return () => {
      unguard()
      closeStream()
    }
  }, [])

  /* 다크는 OS 설정이 아니라 앱의 토글이 정합니다.
     첫 값은 `index.html` 이 이미 붙여 두었고, 이 효과는 **토글한 뒤**를 맡습니다. */
  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  /* 연결 확인은 **30초**마다입니다. 사람이 「멈췄나」를 의심하기 시작하는
     간격이고, 더 짧으면 확인 자체가 호출 예산을 갉습니다.
     **같은 확인이 활성 환경도 읽습니다.** 연결 낱말과 모의/실전 배지가 한
     응답에서 나와야 둘이 서로 다른 시각의 사실을 말하지 않습니다. */
  const checkConnection = useCallback(() => {
    setConnection('checking')
    void checkHealth().then(setConnection)
  }, [])

  /* **되풀이 확인은 답이 올 때까지 앞 답을 그대로 둡니다.** 확인이 도는 동안마다
     「확인 중」으로 돌리면, 시세 쪽이 마침 다시 붙는 중일 때 그 순간 상단이
     「백엔드 확인 중」으로 바뀝니다 — 백엔드는 멀쩡한데 백엔드를 의심하게
     만듭니다. 「확인 중」은 처음과 사용자가 「다시 확인」을 누른 때만 섭니다. */
  useEffect(() => {
    checkConnection()
    const timer = window.setInterval(() => void checkHealth().then(setConnection), 30_000)
    return () => window.clearInterval(timer)
  }, [checkConnection])

  /* **마지막으로 시세가 도착한 때**(`data/lastQuote.ts`). 연결 확인이나 마스터가
     아니라 시세 값이 기준입니다 — 연결은 살아 있는데 값만 안 오는 상태가 이
     시각에 잡혀야 합니다. **분 단위**입니다. 초 단위면 값이 흘러 눈이 그리로
     갑니다. */
  const lastQuote = useLastQuoteLabel()
  /* 멈췄는지는 시각이 바뀔 때와 30초마다 다시 봅니다. 새 시세가 안 오면 시각이
     바뀌지 않으므로, 시계 없이는 「2분이 지났다」를 알 수 없습니다. */
  const [quoteStalled, setQuoteStalled] = useState(false)
  useEffect(() => {
    const judge = () => setQuoteStalled(quotesStalled())
    judge()
    const timer = window.setInterval(judge, 30_000)
    return () => window.clearInterval(timer)
  }, [feed.state, lastQuote])

  /* 종목을 여는 단 하나의 길. 홈·종목 화면·최근 본·검색이 모두 여기로 들어오고,
     넘기는 것은 **코드 하나**입니다 — 시장도 종류도 코드가 압니다. */
  /* 종목을 못 연 자리. 조용히 아무 일도 안 하면 「눌렀는데 안 열린다」가 되고,
     사용자는 무엇이 잘못됐는지 알 길이 없습니다.
     **왜 못 열었는지를 함께 답니다.** 코드가 안 풀리는 것과 마스터가 아직 없는
     것은 사용자가 할 일이 다릅니다 — 앞은 그 종목이 상장에 없다는 뜻이라 다시
     눌러도 같고, 뒤는 기다리거나 다시 받으면 열립니다. 누른 그 시점의 상태를
     담아 둡니다. 나중에 마스터가 도착해도 그때 못 연 이유는 바뀌지 않습니다. */
  const [openFailed, setOpenFailed] = useState<{
    code: string
    reason: 'missing' | 'loading' | 'failed'
  } | null>(null)

  /* 왜 못 열었는지를 가려 담는 곳. 종목을 여는 길이 둘(밖에서 코드로 들어오는
     길과 주문 화면 안에서 옮기는 길)이라 판단을 한 군데 모아 둡니다. */
  const reportOpenFailure = useCallback((code: string) => {
    const status = masterState().status
    setOpenFailed({ code, reason: status === 'ready' ? 'missing' : status })
  }, [])

  const openInstrument = useCallback(
    (code: string, intent?: OpenIntent) => {
      if (!resolve(code)) {
        reportOpenFailure(code)
        return
      }
      setOpenFailed(null)
      /* 최신이 앞이고 스무 개까지입니다. 더 쌓아 두어도 목록에서 찾는 것보다
         다시 검색하는 편이 빠른 길이가 됩니다. */
      saveRecent([code, ...recentRef.current.filter((item) => item !== code)].slice(0, RECENT_KEPT))
      setOpenedCode(code)
      /* 무엇을 하러 왔는지도 함께 넘깁니다. 종목만 바꾸면 청산하러 온 사람이
         새 주문 폼을 받고, 방향과 수량을 다시 채워야 합니다. */
      setOpenedIntent(intent ?? null)
      goPage('trade')
    },
    [saveRecent, reportOpenFailure],
  )

  /* 최근 본에 세울 줄. **색인에 없는 코드는 걸러 냅니다** — 상장이 끝난 종목이
     남아 있으면 눌러도 안 열리는 줄이 서고, 그건 목록이 거짓말을 하는 것입니다.
     색인을 아직 못 받았으면 아무것도 안 서고, 받는 순간 채워집니다. */
  const recent: RecentItem[] = recentCodes.flatMap((code) => {
    const item = resolve(code)
    return item ? [{ code, name: item.name }] : []
  })

  /* 품목까지만 정해진 것을 여는 길. 검색창의 둘러보기에서 품목을 고르면 여기로
     옵니다 — 종목 화면에서 그 품목의 목록이 서고, 거기서 고릅니다. */
  const openProduct = (market: Market, product: Product) => {
    /* 국내는 주간·야간을 고르지 않습니다. 어느 세션인지는 시계가 정합니다. */
    setContext(market === 'overseas' ? 'overseas' : 'domestic-day')
    setProductCode(product.code)
    goPage('instruments')
  }

  /* 계좌를 열되 어느 탭인지까지 정합니다. 「미체결을 보러」 눌렀는데 보유
     포지션이 열리면, 사용자는 자기가 누른 것이 안 먹혔다고 읽습니다. */
  const openAccount = (tab: string) => {
    setAccountTab(tab)
    goPage('account')
  }

  /* 페이지를 옮기는 길은 하나뿐입니다 — 상단 탭도, 검색으로 종목을 여는
     것도 여기를 지납니다. 전략주문에서 나갈 때만, 그리고 저장 안 한 초안이
     있을 때만 붙잡습니다. */
  function goPage(next: Page) {
    /* 지금 페이지를 **ref 로** 봅니다 — 검색에서 종목을 여는 길은 기억해 둔
       함수(`useCallback`)를 지나므로, 그 함수가 만들어질 때의 페이지를 그대로
       들고 있으면 전략주문에서 나가는 것을 못 알아챕니다. */
    if (pageRef.current === 'strategy' && next !== 'strategy' && hasUnsaved()) {
      setLeavingPage(next)
      return
    }
    if (next === 'home') setHomeVisit((count) => count + 1)
    setPage(next)
  }

  /* 운영체제 알림을 눌렀을 때 — 데스크톱 앱이 창을 앞으로 가져온 뒤 이 함수를 부릅니다
     (브라우저 알림은 알림이 직접 부릅니다). 토스트의 「보기」와 같은 곳으로 갑니다. */
  useEffect(() => {
    const host = window as unknown as { __nhNotifyClick?: (runId: string) => void }
    host.__nhNotifyClick = (runId) => {
      const ids = notifyTargets(runId || null)
      if (ids.length > 0 && openRunTab(ids)) goPage('strategy')
    }
    return () => {
      delete host.__nhNotifyClick
    }
    // 페이지를 옮기는 길(`goPage`)은 ref 로 지금 페이지를 봐서 처음 것으로 충분합니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="app-shell">
      {/* 값이 하나도 없는 자리라 브랜드 색이 무엇도 가리지 않습니다. */}
      <div className="brand-bar" aria-hidden="true" />

      <TopBar
        page={page}
        environment={environment.active}
        environmentStatus={environment.status}
        theme={theme}
        connection={connection}
        feed={feed.state}
        feedLagging={feed.lagging}
        lastQuote={lastQuote || '—'}
        quoteStalled={quoteStalled}
        master={master}
        recent={recent}
        onPageChange={goPage}
        settingsOpen={settingsOpen}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenInstrument={openInstrument}
        onOpenProduct={openProduct}
        onRecheck={checkConnection}
        onToggleTheme={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      />

      {/* 못 연 종목 한 줄. 누른 자리가 화면마다 달라 그 옆에 붙일 수 없어,
          화면 위에 한 줄로 섭니다. 다음에 무엇이든 열면 사라집니다. */}
      {openFailed && (
        <p className="app-missing" role="status">
          {openFailed.reason === 'missing' ? (
            <>
              종목 목록에 없는 종목입니다 — <span className="num">{openFailed.code}</span>
            </>
          ) : openFailed.reason === 'loading' ? (
            <>종목 목록을 받는 중입니다 — 받은 뒤 다시 눌러 주세요</>
          ) : (
            <>종목 목록을 받지 못해 종목을 열 수 없습니다 — 위에서 다시 받아 주세요</>
          )}
          <button type="button" className="btn btn-quiet" onClick={() => setOpenFailed(null)}>
            닫기
          </button>
        </p>
      )}

      {/* 파일에 못 남겼을 때. 화면은 안 되돌리므로 어디도 이상해 보이지
          않습니다 — 그래서 「그 자리」가 아니라 화면 전체에 한 줄로 섭니다. */}
      {ui.failure && (
        <p className="app-warn" role="status">
          <strong>남기지 못했습니다</strong>
          {ui.failure === 'size'
            ? '그린 것이 너무 많습니다. 지우기 전에는 앱을 끄면 사라집니다'
            : '이 창에서는 그대로 쓰이지만, 앱을 끄면 사라집니다'}
        </p>
      )}

      <main className="app-main">
        <div className="app-screen">
          {/* 화면 하나가 그리다 멈춰도 그 화면 자리에만 안내가 섭니다 — 상단 띠와 옆
              레일은 살아 있어 다른 탭으로 옮길 수 있습니다. 탭을 옮기면 경계가 새로
              섭니다(`key`). */}
          <ScreenBoundary key={page}>
            {/* 화면 상태(관심종목·배치·차트에 그린 것)가 오기 전에는 화면을 안
                그립니다. 기본 배치로 그렸다가 파일 값이 도착해 카드가 자리를
                옮기면, 사용자는 자기가 옮겨 둔 것이 왜 두 번 움직이는지 알 수
                없습니다. 파일을 못 읽었으면 기본값으로 그대로 갑니다. */}
            {ui.status === 'loading' ? null : page === 'home' ? (
              <HomeScreen
                context={context}
                visit={homeVisit}
                recent={recent}
                onOpenInstrument={openInstrument}
                onGoOrders={() => openAccount('미체결')}
                onGoBalance={(overseas) => {
                  setAccountMarket(overseas ? 'overseas' : 'domestic')
                  openAccount('잔고')
                }}
              />
            ) : page === 'account' ? (
              /* 계좌의 국내·해외는 계좌가 따로 기억합니다(위 `accountMarket`). */
              <AccountScreen
                onOpenSettings={() => setSettingsOpen(true)}
                market={accountMarket}
                onMarketChange={setAccountMarket}
                onOpenInstrument={openInstrument}
                tab={accountTab}
                onTabChange={setAccountTab}
              />
            ) : page === 'instruments' ? (
              <InstrumentsScreen
                master={master}
                context={context}
                productCode={productCode}
                onContextChange={setContext}
                onProductChange={setProductCode}
                onOpenInstrument={openInstrument}
              />
            ) : page === 'trade' ? (
              <TradeScreen
                /* 이 화면의 종목은 코드가 정합니다. `context` 는 종목의 출처가
                   아니라 **검색·카탈로그의 기본 범위**로만 넘어갑니다. */
                context={context}
                openedCode={openedCode}
                openedIntent={openedIntent}
                onOpenFailed={reportOpenFailure}
                onOpenSettings={() => setSettingsOpen(true)}
              />
            ) : (
              <StrategyScreen />
            )}
          </ScreenBoundary>
        </div>

        <SideBar
          recent={recent}
          current={page === 'trade' ? openedCode : null}
          onOpen={(item) => openInstrument(item.code)}
          onRemove={removeRecent}
        />
      </main>

      {/* 전략 실행 알림. 「보기」는 전략주문으로 옮겨 그 실행을 엽니다. */}
      <Toasts
        page={page}
        onView={(runIds) => {
          if (openRunTab(runIds)) goPage('strategy')
        }}
      />

      {leavingPage && (
        <LeaveGuard
          onStay={() => setLeavingPage(null)}
          onLeave={() => {
            /* 되돌리는 것은 설정 초안뿐입니다 — 검증·진행의 실행과 보낸
               요청은 그대로 둡니다. 하위 탭에서 떠날 때와 같은 자리입니다. */
            revertDrafts()
            if (leavingPage === 'home') setHomeVisit((count) => count + 1)
            setPage(leavingPage)
            setLeavingPage(null)
          }}
        />
      )}

      {settingsOpen && (
        <SettingsModal
          needsCredentials={needsCredentials}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  )
}

export default App
