import { useEffect, useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ExternalLink, RefreshCw } from 'lucide-react'
import { api, type UsageStats } from '../lib/api'

const fmtNum = (n: number) => new Intl.NumberFormat('fr-FR').format(n)

export function FinOpsView() {
  const [days, setDays] = useState<number>(7)
  const [stats, setStats] = useState<UsageStats | null>(null)
  const [loading, setLoading] = useState(true)

  const load = async (d = days) => {
    setLoading(true)
    try {
      const data = await api.getUsageStats(d)
      setStats(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load(days)
  }, [days])

  const summary = stats?.summary
  const maxAgentTokens = Math.max(...(stats?.by_agent.map((a) => a.total_tokens) || [1]), 1)

  return (
    <div className="h-full overflow-y-auto px-4 md:px-8 py-6">
      <div className="mx-auto max-w-6xl space-y-6">
        {/* Header Row */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="heading-tight text-xl font-semibold">FinOps &amp; Consommation Tokens</h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--fg-secondary)' }}>
              Télémétrie temps réel enregistrée dans PostgreSQL pour chaque appel LangGraph / LiteLLM.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <div
              className="inline-flex rounded-lg p-0.5 text-xs"
              style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border)' }}
            >
              {[1, 7, 30].map((d) => (
                <button
                  key={d}
                  onClick={() => setDays(d)}
                  className="rounded-md px-2.5 py-1 font-mono-tabular transition-colors cursor-pointer"
                  style={{
                    backgroundColor: days === d ? 'var(--bg-elevated)' : 'transparent',
                    color: days === d ? 'var(--fg-primary)' : 'var(--fg-muted)',
                  }}
                >
                  {d === 1 ? '24h' : `${d}j`}
                </button>
              ))}
            </div>

            <button
              onClick={() => load(days)}
              className="flex h-8 w-8 items-center justify-center rounded-lg cursor-pointer"
              style={{
                backgroundColor: 'var(--bg-surface)',
                border: '1px solid var(--border)',
                color: 'var(--fg-secondary)',
              }}
              title="Rafraîchir"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>

            <a
              href="https://cloud.langfuse.com"
              target="_blank"
              rel="noreferrer"
              className="hidden sm:inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium"
              style={{
                backgroundColor: 'var(--bg-surface)',
                border: '1px solid var(--border)',
                color: 'var(--fg-primary)',
              }}
            >
              Traces Langfuse
              <ExternalLink className="h-3 w-3 opacity-60" />
            </a>
          </div>
        </div>

        {/* 4 Bento KPI Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5">
          <div className="bento-card p-4 space-y-1.5">
            <div className="text-[11px] font-medium" style={{ color: 'var(--fg-muted)' }}>
              Tokens consommés
            </div>
            <div className="font-mono-tabular text-2xl font-semibold heading-tight">
              {fmtNum(summary?.total_tokens ?? 0)}
            </div>
            <div className="font-mono-tabular text-[11px]" style={{ color: 'var(--fg-secondary)' }}>
              {fmtNum(summary?.prompt_tokens ?? 0)} in · {fmtNum(summary?.completion_tokens ?? 0)} out
            </div>
          </div>

          <div className="bento-card p-4 space-y-1.5">
            <div className="text-[11px] font-medium" style={{ color: 'var(--fg-muted)' }}>
              Appels LLM
            </div>
            <div className="font-mono-tabular text-2xl font-semibold heading-tight">
              {fmtNum(summary?.total_calls ?? 0)}
            </div>
            <div
              className="font-mono-tabular text-[11px]"
              style={{
                color: (summary?.error_calls ?? 0) > 0 ? 'var(--amber)' : 'var(--emerald)',
              }}
            >
              {summary?.error_calls ?? 0} erreur{(summary?.error_calls ?? 0) > 1 ? 's' : ''}
            </div>
          </div>

          <div className="bento-card p-4 space-y-1.5">
            <div className="text-[11px] font-medium" style={{ color: 'var(--fg-muted)' }}>
              Latence moyenne
            </div>
            <div className="font-mono-tabular text-2xl font-semibold heading-tight">
              {fmtNum(summary?.avg_latency_ms ?? 0)}{' '}
              <span className="text-xs font-normal" style={{ color: 'var(--fg-muted)' }}>
                ms
              </span>
            </div>
            <div className="text-[11px]" style={{ color: 'var(--fg-secondary)' }}>
              Cascade Groq + Mistral
            </div>
          </div>

          <div className="bento-card p-4 space-y-1.5">
            <div className="text-[11px] font-medium" style={{ color: 'var(--fg-muted)' }}>
              Coût API estimé
            </div>
            <div className="font-mono-tabular text-2xl font-semibold heading-tight">0,00 €</div>
            <div className="inline-flex items-center gap-1.5 text-[11px]" style={{ color: 'var(--emerald)' }}>
              <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: 'var(--emerald)' }} />
              Free-tier FinOps actif
            </div>
          </div>
        </div>

        {/* Charts Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Daily Tokens Area Chart */}
          <div className="bento-card p-5 lg:col-span-2 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-medium">Tokens par jour</h3>
                <p className="text-xs" style={{ color: 'var(--fg-muted)' }}>
                  Prompt (entrée) vs Completion (sortie)
                </p>
              </div>
              <div className="flex items-center gap-3 text-[11px]" style={{ color: 'var(--fg-secondary)' }}>
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: 'var(--fg-primary)' }} />
                  Prompt
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: 'var(--emerald)' }} />
                  Completion
                </span>
              </div>
            </div>

            <div className="h-56 w-full">
              {stats && stats.by_day.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={stats.by_day} margin={{ top: 6, right: 6, left: -18, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
                    <XAxis
                      dataKey="day"
                      tick={{ fill: 'var(--fg-muted)', fontSize: 11 }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fill: 'var(--fg-muted)', fontSize: 11 }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: 'var(--bg-surface)',
                        border: '1px solid var(--border-strong)',
                        borderRadius: '10px',
                        fontSize: '12px',
                        color: 'var(--fg-primary)',
                      }}
                    />
                    <Area
                      type="monotone"
                      dataKey="prompt_tokens"
                      name="Prompt"
                      stroke="var(--fg-primary)"
                      fill="var(--fg-primary)"
                      fillOpacity={0.08}
                      strokeWidth={1.75}
                    />
                    <Area
                      type="monotone"
                      dataKey="completion_tokens"
                      name="Completion"
                      stroke="var(--emerald)"
                      fill="var(--emerald)"
                      fillOpacity={0.12}
                      strokeWidth={1.75}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div
                  className="flex h-full items-center justify-center text-xs"
                  style={{ color: 'var(--fg-muted)' }}
                >
                  Envoie un premier message dans le Chat pour voir la courbe en direct.
                </div>
              )}
            </div>
          </div>

          {/* Breakdown by Agent */}
          <div className="bento-card p-5 space-y-4">
            <div>
              <h3 className="text-sm font-medium">Répartition par agent</h3>
              <p className="text-xs" style={{ color: 'var(--fg-muted)' }}>
                Volume de tokens &amp; latence
              </p>
            </div>

            <div className="space-y-3.5">
              {stats && stats.by_agent.length > 0 ? (
                stats.by_agent.map((item) => {
                  const pct = Math.max(4, Math.round((item.total_tokens / maxAgentTokens) * 100))
                  return (
                    <div key={item.agent} className="space-y-1.5">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-mono-tabular font-medium">{item.agent}</span>
                        <span className="font-mono-tabular" style={{ color: 'var(--fg-secondary)' }}>
                          {fmtNum(item.total_tokens)} tok · {item.avg_latency_ms}ms
                        </span>
                      </div>
                      <div
                        className="h-1.5 w-full rounded-full overflow-hidden"
                        style={{ backgroundColor: 'var(--bg-elevated)' }}
                      >
                        <div
                          className="h-full rounded-full"
                          style={{ width: `${pct}%`, backgroundColor: 'var(--fg-primary)' }}
                        />
                      </div>
                    </div>
                  )
                })
              ) : (
                <div className="py-12 text-center text-xs" style={{ color: 'var(--fg-muted)' }}>
                  Aucune donnée sur cette période.
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Breakdown by Model / Provider */}
        {stats && stats.by_model.length > 0 && (
          <div className="bento-card p-5 space-y-4">
            <div>
              <h3 className="text-sm font-medium">Consommation par modèle</h3>
              <p className="text-xs" style={{ color: 'var(--fg-muted)' }}>
                Cascade multi-fournisseurs LiteLLM
              </p>
            </div>
            <div className="h-44 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={stats.by_model} margin={{ top: 6, right: 6, left: -12, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
                  <XAxis
                    dataKey="model"
                    tick={{ fill: 'var(--fg-muted)', fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: 'var(--fg-muted)', fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'var(--bg-surface)',
                      border: '1px solid var(--border-strong)',
                      borderRadius: '10px',
                      fontSize: '12px',
                    }}
                  />
                  <Bar
                    dataKey="total_tokens"
                    name="Tokens"
                    fill="var(--fg-primary)"
                    radius={[6, 6, 0, 0]}
                    maxBarSize={44}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {/* Recent Calls Table */}
        <div className="bento-card overflow-hidden">
          <div className="px-5 py-3.5 hairline-b flex items-center justify-between">
            <h3 className="text-sm font-medium">Appels LLM récents</h3>
            <span className="font-mono-tabular text-[11px]" style={{ color: 'var(--fg-muted)' }}>
              25 derniers appels
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="hairline-b" style={{ color: 'var(--fg-muted)' }}>
                  <th className="px-5 py-2.5 font-medium">Heure</th>
                  <th className="px-4 py-2.5 font-medium">Agent</th>
                  <th className="px-4 py-2.5 font-medium">Provider / Modèle</th>
                  <th className="px-4 py-2.5 font-medium text-right">Tokens</th>
                  <th className="px-4 py-2.5 font-medium text-right">Latence</th>
                  <th className="px-5 py-2.5 font-medium text-right">Statut</th>
                </tr>
              </thead>
              <tbody>
                {stats && stats.recent.length > 0 ? (
                  stats.recent.map((row, idx) => (
                    <tr key={row.id ?? idx} className="hairline-b last:border-b-0">
                      <td
                        className="px-5 py-2.5 font-mono-tabular whitespace-nowrap"
                        style={{ color: 'var(--fg-muted)' }}
                      >
                        {new Date(row.created_at).toLocaleTimeString('fr-FR', {
                          hour: '2-digit',
                          minute: '2-digit',
                          second: '2-digit',
                        })}
                      </td>
                      <td className="px-4 py-2.5 font-mono-tabular">{row.agent}</td>
                      <td className="px-4 py-2.5">
                        <span className="font-medium">{row.provider}</span>{' '}
                        <span className="font-mono-tabular text-[11px]" style={{ color: 'var(--fg-muted)' }}>
                          {row.model}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 font-mono-tabular text-right">
                        {fmtNum(row.total_tokens)}
                      </td>
                      <td
                        className="px-4 py-2.5 font-mono-tabular text-right"
                        style={{ color: 'var(--fg-secondary)' }}
                      >
                        {row.latency_ms}ms
                      </td>
                      <td className="px-5 py-2.5 text-right">
                        <span
                          className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono-tabular text-[10px]"
                          style={{
                            backgroundColor:
                              row.status === 'ok' ? 'var(--emerald-soft)' : 'var(--rose-soft)',
                            color: row.status === 'ok' ? 'var(--emerald)' : 'var(--rose)',
                          }}
                        >
                          {row.status}
                        </span>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-5 py-10 text-center text-xs"
                      style={{ color: 'var(--fg-muted)' }}
                    >
                      Aucun appel LLM enregistré pour le moment.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
