import { useEffect, useMemo, useRef, useState } from 'react'
import { Pause, Play, Search, Trash2 } from 'lucide-react'
import { api, type LogEntry } from '../lib/api'

const LEVELS = ['ALL', 'INFO', 'WARNING', 'ERROR'] as const

export function LogsView() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [levelFilter, setLevelFilter] = useState<(typeof LEVELS)[number]>('ALL')
  const [query, setQuery] = useState('')
  const [paused, setPaused] = useState(false)
  const [connected, setConnected] = useState(false)
  const pausedRef = useRef(false)
  const bottomRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    pausedRef.current = paused
  }, [paused])

  useEffect(() => {
    api
      .getRecentLogs(200)
      .then((res) => setLogs(res.logs || []))
      .catch(() => {})

    const es = new EventSource('/api/logs/stream')
    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)
    es.onmessage = (ev) => {
      if (pausedRef.current) return
      try {
        const entry = JSON.parse(ev.data) as LogEntry
        setLogs((prev) => [...prev.slice(-399), entry])
      } catch {
        // ignore keepalive
      }
    }
    return () => es.close()
  }, [])

  useEffect(() => {
    if (!paused) {
      bottomRef.current?.scrollIntoView({ behavior: 'auto' })
    }
  }, [logs, paused])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return logs.filter((l) => {
      if (levelFilter !== 'ALL' && l.level !== levelFilter) return false
      if (q && !`${l.logger} ${l.message}`.toLowerCase().includes(q)) return false
      return true
    })
  }, [logs, levelFilter, query])

  const levelColor = (level: string) => {
    if (level === 'ERROR' || level === 'CRITICAL') return 'var(--rose)'
    if (level === 'WARNING') return 'var(--amber)'
    return 'var(--emerald)'
  }

  return (
    <div className="flex h-full flex-col px-4 md:px-8 py-5 gap-4 overflow-hidden">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs font-mono-tabular">
            <span
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: connected ? 'var(--emerald)' : 'var(--amber)' }}
            />
            <span style={{ color: 'var(--fg-secondary)' }}>
              {connected ? 'SSE live' : 'Reconnexion...'}
            </span>
          </div>

          <div
            className="inline-flex rounded-lg p-0.5 text-[11px]"
            style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border)' }}
          >
            {LEVELS.map((lvl) => (
              <button
                key={lvl}
                onClick={() => setLevelFilter(lvl)}
                className="rounded-md px-2.5 py-1 font-mono-tabular cursor-pointer transition-colors"
                style={{
                  backgroundColor: levelFilter === lvl ? 'var(--bg-elevated)' : 'transparent',
                  color: levelFilter === lvl ? 'var(--fg-primary)' : 'var(--fg-muted)',
                }}
              >
                {lvl}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div
            className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs"
            style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border)' }}
          >
            <Search className="h-3.5 w-3.5" style={{ color: 'var(--fg-muted)' }} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filtrer les logs..."
              className="bg-transparent outline-none w-36 sm:w-52 text-xs"
              style={{ color: 'var(--fg-primary)' }}
            />
          </div>

          <button
            onClick={() => setPaused((p) => !p)}
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium cursor-pointer"
            style={{
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              color: 'var(--fg-primary)',
            }}
          >
            {paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
            <span className="hidden sm:inline">{paused ? 'Reprendre' : 'Pause'}</span>
          </button>

          <button
            onClick={() => setLogs([])}
            className="flex h-8 w-8 items-center justify-center rounded-lg cursor-pointer"
            style={{
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              color: 'var(--fg-secondary)',
            }}
            title="Vider l'affichage"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Monospace Log Stream Container */}
      <div
        className="flex-1 min-h-0 overflow-y-auto rounded-2xl p-4 font-mono-tabular text-[11.5px] leading-relaxed"
        style={{
          backgroundColor: 'var(--bg-surface)',
          border: '1px solid var(--border)',
        }}
      >
        {filtered.length === 0 ? (
          <div className="py-16 text-center text-xs" style={{ color: 'var(--fg-muted)' }}>
            Aucun événement de log correspondant.
          </div>
        ) : (
          <div className="space-y-1">
            {filtered.map((entry, idx) => (
              <div
                key={`${entry.ts}-${idx}`}
                className="flex items-start gap-3 rounded px-2 py-0.5 hover:bg-white/[0.03]"
              >
                <span className="shrink-0" style={{ color: 'var(--fg-muted)' }}>
                  {new Date(entry.ts).toLocaleTimeString('fr-FR', {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                  })}
                </span>
                <span
                  className="shrink-0 w-14 font-medium"
                  style={{ color: levelColor(entry.level) }}
                >
                  {entry.level}
                </span>
                <span
                  className="shrink-0 hidden md:inline w-40 truncate"
                  style={{ color: 'var(--fg-muted)' }}
                >
                  {entry.logger}
                </span>
                <span className="break-all flex-1" style={{ color: 'var(--fg-primary)' }}>
                  {entry.message}
                </span>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </div>
  )
}
