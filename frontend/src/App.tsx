import { useEffect, useState } from 'react'
import {
  Activity,
  BarChart3,
  MessageSquare,
  Moon,
  Network,
  Sun,
  Terminal,
  Zap,
  ExternalLink,
} from 'lucide-react'
import { api } from './lib/api'
import { ChatView } from './components/ChatView'
import { FinOpsView } from './components/FinOpsView'
import { ArchitectureView } from './components/ArchitectureView'
import { LogsView } from './components/LogsView'
import { AutomationsView } from './components/AutomationsView'

type TabId = 'chat' | 'finops' | 'architecture' | 'logs' | 'automations'

const NAV_ITEMS: Array<{ id: TabId; label: string; short: string; icon: typeof MessageSquare }> = [
  { id: 'chat', label: 'Conversations', short: 'Chat', icon: MessageSquare },
  { id: 'finops', label: 'FinOps & Tokens', short: 'Tokens', icon: BarChart3 },
  { id: 'architecture', label: 'Architecture', short: 'Infra', icon: Network },
  { id: 'logs', label: 'Logs temps réel', short: 'Logs', icon: Terminal },
  { id: 'automations', label: 'Automatisations', short: 'Auto', icon: Zap },
]

export function App() {
  const [activeTab, setActiveTab] = useState<TabId>('chat')
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    const saved = localStorage.getItem('nexus-theme')
    return saved === 'light' ? 'light' : 'dark'
  })
  const [health, setHealth] = useState<{
    online: boolean
    postgres: boolean
    discord: boolean
    env: string
  }>({ online: false, postgres: false, discord: false, env: 'prod' })

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('nexus-theme', theme)
    const meta = document.querySelector('meta[name="theme-color"]')
    if (meta) meta.setAttribute('content', theme === 'dark' ? '#0A0A0B' : '#FAFAFA')
  }, [theme])

  useEffect(() => {
    let mounted = true
    const check = async () => {
      try {
        const res = await api.health()
        if (mounted) {
          setHealth({
            online: res.status === 'ok',
            postgres: Boolean(res.postgres),
            discord: Boolean(res.discord_ready),
            env: res.env || 'prod',
          })
        }
      } catch {
        if (mounted) setHealth((h) => ({ ...h, online: false }))
      }
    }
    check()
    const timer = window.setInterval(check, 25000)
    return () => {
      mounted = false
      window.clearInterval(timer)
    }
  }, [])

  const currentNav = NAV_ITEMS.find((n) => n.id === activeTab)!

  return (
    <div
      className="flex h-screen w-screen overflow-hidden"
      style={{ backgroundColor: 'var(--bg-canvas)', color: 'var(--fg-primary)' }}
    >
      {/* Desktop Left Navigation Rail */}
      <aside
        className="hidden md:flex w-[228px] shrink-0 flex-col justify-between hairline-r px-3 py-4"
        style={{ backgroundColor: 'var(--bg-surface)' }}
      >
        <div className="space-y-6">
          {/* Minimal Swiss Brand Header */}
          <div className="flex items-center gap-2.5 px-2.5">
            <div
              className="flex h-7 w-7 items-center justify-center rounded-lg font-mono-tabular text-xs font-semibold"
              style={{
                backgroundColor: 'var(--accent)',
                color: 'var(--accent-fg)',
              }}
            >
              N
            </div>
            <div className="leading-tight">
              <div className="heading-tight text-sm font-semibold">Nexus</div>
              <div className="text-[11px]" style={{ color: 'var(--fg-muted)' }}>
                Mission Control
              </div>
            </div>
          </div>

          <nav className="space-y-1">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon
              const active = activeTab === item.id
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveTab(item.id)}
                  className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] font-medium transition-colors cursor-pointer"
                  style={{
                    backgroundColor: active ? 'var(--bg-elevated)' : 'transparent',
                    color: active ? 'var(--fg-primary)' : 'var(--fg-secondary)',
                    border: active ? '1px solid var(--border)' : '1px solid transparent',
                  }}
                >
                  <Icon className="h-4 w-4 shrink-0" strokeWidth={1.75} />
                  <span>{item.label}</span>
                </button>
              )
            })}
          </nav>
        </div>

        {/* Bottom Status Summary */}
        <div className="space-y-2 px-1">
          <div
            className="rounded-xl p-3 text-xs space-y-2"
            style={{
              backgroundColor: 'var(--bg-canvas)',
              border: '1px solid var(--border)',
            }}
          >
            <div className="flex items-center justify-between">
              <span style={{ color: 'var(--fg-muted)' }}>Statut cluster</span>
              <span className="inline-flex items-center gap-1.5 font-mono-tabular text-[11px]">
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{
                    backgroundColor: health.online ? 'var(--emerald)' : 'var(--rose)',
                  }}
                />
                {health.online ? 'Online' : 'Offline'}
              </span>
            </div>
            <div className="flex items-center justify-between text-[11px]">
              <span style={{ color: 'var(--fg-muted)' }}>PostgreSQL</span>
              <span
                className="font-mono-tabular"
                style={{ color: health.postgres ? 'var(--emerald)' : 'var(--amber)' }}
              >
                {health.postgres ? 'pgvector' : 'memory'}
              </span>
            </div>
            <div className="flex items-center justify-between text-[11px]">
              <span style={{ color: 'var(--fg-muted)' }}>Discord Bot</span>
              <span
                className="font-mono-tabular"
                style={{ color: health.discord ? 'var(--emerald)' : 'var(--fg-muted)' }}
              >
                {health.discord ? 'connecté' : 'veille'}
              </span>
            </div>
          </div>

          <a
            href="https://cloud.langfuse.com"
            target="_blank"
            rel="noreferrer"
            className="flex items-center justify-between rounded-lg px-2.5 py-2 text-xs transition-colors"
            style={{ color: 'var(--fg-secondary)' }}
          >
            <span className="inline-flex items-center gap-2">
              <Activity className="h-3.5 w-3.5" />
              Langfuse Cloud
            </span>
            <ExternalLink className="h-3 w-3 opacity-60" />
          </a>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex flex-1 flex-col min-w-0 overflow-hidden">
        {/* Top Glass Command Bar */}
        <header
          className="flex h-13 shrink-0 items-center justify-between px-4 md:px-6 hairline-b backdrop-blur-md"
          style={{ backgroundColor: 'var(--bg-glass)' }}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            <div
              className="flex md:hidden h-6 w-6 items-center justify-center rounded-md font-mono-tabular text-[11px] font-semibold"
              style={{ backgroundColor: 'var(--accent)', color: 'var(--accent-fg)' }}
            >
              N
            </div>
            <span className="text-xs hidden sm:inline" style={{ color: 'var(--fg-muted)' }}>
              Nexus
            </span>
            <span className="text-xs hidden sm:inline" style={{ color: 'var(--border-strong)' }}>
              /
            </span>
            <h1 className="heading-tight text-sm font-semibold truncate">{currentNav.label}</h1>
          </div>

          <div className="flex items-center gap-2">
            <div
              className="hidden sm:inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-mono-tabular"
              style={{
                backgroundColor: 'var(--bg-surface)',
                border: '1px solid var(--border)',
                color: 'var(--fg-secondary)',
              }}
            >
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: health.online ? 'var(--emerald)' : 'var(--rose)' }}
              />
              <span>azure · tailscale · 0,00 €</span>
            </div>

            <button
              onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
              aria-label="Changer de thème"
              className="flex h-8 w-8 items-center justify-center rounded-lg transition-colors cursor-pointer"
              style={{
                backgroundColor: 'var(--bg-surface)',
                border: '1px solid var(--border)',
                color: 'var(--fg-secondary)',
              }}
            >
              {theme === 'dark' ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
            </button>
          </div>
        </header>

        {/* Active View Container */}
        <main className="flex-1 min-h-0 overflow-hidden pb-14 md:pb-0">
          {activeTab === 'chat' && <ChatView />}
          {activeTab === 'finops' && <FinOpsView />}
          {activeTab === 'architecture' && <ArchitectureView />}
          {activeTab === 'logs' && <LogsView />}
          {activeTab === 'automations' && <AutomationsView />}
        </main>
      </div>

      {/* Mobile Bottom Navigation Bar */}
      <nav
        className="fixed bottom-0 left-0 right-0 z-30 flex md:hidden items-center justify-around h-14 hairline-t backdrop-blur-md px-1"
        style={{ backgroundColor: 'var(--bg-glass)' }}
      >
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon
          const active = activeTab === item.id
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className="flex flex-col items-center justify-center gap-0.5 px-2 py-1 text-[10px] font-medium"
              style={{ color: active ? 'var(--fg-primary)' : 'var(--fg-muted)' }}
            >
              <Icon className="h-4 w-4" strokeWidth={active ? 2 : 1.6} />
              <span>{item.short}</span>
            </button>
          )
        })}
      </nav>
    </div>
  )
}
