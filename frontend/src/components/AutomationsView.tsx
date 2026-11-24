import { useEffect, useState } from 'react'
import { Clock, Play, RefreshCw, Zap } from 'lucide-react'
import { api, type AutomationRule, type ScheduledJob } from '../lib/api'

export function AutomationsView() {
  const [rules, setRules] = useState<AutomationRule[]>([])
  const [jobs, setJobs] = useState<ScheduledJob[]>([])
  const [loading, setLoading] = useState(true)
  const [toast, setToast] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const flash = (msg: string) => {
    setToast(msg)
    window.setTimeout(() => setToast(null), 3500)
  }

  const load = async () => {
    setLoading(true)
    try {
      const data = await api.getAutomations()
      setRules(data.rules || [])
      setJobs(data.scheduled_jobs || [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const handleToggle = async (ruleId: string) => {
    setBusyId(ruleId)
    try {
      const { rule } = await api.toggleAutomation(ruleId)
      setRules((prev) => prev.map((r) => (r.id === ruleId ? { ...r, enabled: rule.enabled } : r)))
      flash(`Règle « ${rule.id} » ${rule.enabled ? 'activée' : 'mise en pause'}.`)
    } finally {
      setBusyId(null)
    }
  }

  const handleRun = async (ruleId: string) => {
    setBusyId(ruleId)
    try {
      await api.runAutomation(ruleId)
      flash(`Automatisation « ${ruleId} » déclenchée — suis son exécution dans l'onglet Logs.`)
    } finally {
      setBusyId(null)
    }
  }

  const handleReload = async () => {
    setLoading(true)
    try {
      const res = await api.reloadAutomations()
      setRules(res.rules || [])
      await load()
      flash('Fichier config/automations.yaml rechargé.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto px-4 md:px-8 py-6">
      <div className="mx-auto max-w-5xl space-y-6">
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="heading-tight text-xl font-semibold">Automatisations &amp; CRON</h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--fg-secondary)' }}>
              Règles événementielles issues de <code className="font-mono-tabular">config/automations.yaml</code> et tâches APScheduler.
            </p>
          </div>
          <button
            onClick={handleReload}
            className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium cursor-pointer"
            style={{
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              color: 'var(--fg-primary)',
            }}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            Recharger YAML
          </button>
        </div>

        {toast && (
          <div
            className="rounded-xl px-4 py-2.5 text-xs flex items-center gap-2"
            style={{
              backgroundColor: 'var(--emerald-soft)',
              border: '1px solid var(--emerald)',
              color: 'var(--emerald)',
            }}
          >
            <Zap className="h-3.5 w-3.5 shrink-0" />
            <span>{toast}</span>
          </div>
        )}

        {/* Declarative YAML Rules */}
        <section className="space-y-3">
          <div className="text-xs font-medium uppercase tracking-wider" style={{ color: 'var(--fg-muted)' }}>
            Règles déclaratives ({rules.length})
          </div>

          {rules.length === 0 ? (
            <div className="bento-card p-8 text-center text-xs" style={{ color: 'var(--fg-muted)' }}>
              Aucune règle active dans config/automations.yaml.
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3.5">
              {rules.map((rule) => (
                <div key={rule.id} className="bento-card p-5 space-y-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span
                          className="h-2 w-2 rounded-full"
                          style={{
                            backgroundColor: rule.enabled ? 'var(--emerald)' : 'var(--fg-muted)',
                          }}
                        />
                        <h3 className="text-sm font-semibold">{rule.name}</h3>
                      </div>
                      <div className="flex flex-wrap items-center gap-2 font-mono-tabular text-[11px]">
                        <span
                          className="rounded px-2 py-0.5"
                          style={{
                            backgroundColor: 'var(--bg-elevated)',
                            color: 'var(--fg-secondary)',
                          }}
                        >
                          {rule.id}
                        </span>
                        <span style={{ color: 'var(--fg-muted)' }}>
                          trigger: {String(rule.trigger.type || 'inconnu')}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleToggle(rule.id)}
                        disabled={busyId === rule.id}
                        className="rounded-lg px-3 py-1.5 text-xs font-medium cursor-pointer transition-colors"
                        style={{
                          backgroundColor: rule.enabled ? 'var(--bg-elevated)' : 'var(--bg-canvas)',
                          border: '1px solid var(--border-strong)',
                          color: 'var(--fg-primary)',
                        }}
                      >
                        {rule.enabled ? 'Actif' : 'En pause'}
                      </button>
                      <button
                        onClick={() => handleRun(rule.id)}
                        disabled={busyId === rule.id}
                        className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium cursor-pointer"
                        style={{ backgroundColor: 'var(--accent)', color: 'var(--accent-fg)' }}
                      >
                        <Play className="h-3 w-3" />
                        Lancer
                      </button>
                    </div>
                  </div>

                  <p
                    className="rounded-lg p-3 text-xs whitespace-pre-wrap line-clamp-4 font-mono-tabular"
                    style={{
                      backgroundColor: 'var(--bg-canvas)',
                      border: '1px solid var(--border)',
                      color: 'var(--fg-secondary)',
                    }}
                  >
                    {rule.prompt}
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* APScheduler CRON Jobs */}
        <section className="space-y-3">
          <div className="text-xs font-medium uppercase tracking-wider" style={{ color: 'var(--fg-muted)' }}>
            Tâches planifiées APScheduler ({jobs.length})
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
            {jobs.map((job) => (
              <div key={job.id} className="bento-card p-4 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-2 text-sm font-medium">
                    <Clock className="h-3.5 w-3.5" style={{ color: 'var(--fg-muted)' }} />
                    {job.id}
                  </span>
                </div>
                <div className="font-mono-tabular text-[11px]" style={{ color: 'var(--fg-secondary)' }}>
                  {job.trigger}
                </div>
                {job.next_run_time && (
                  <div className="font-mono-tabular text-[11px]" style={{ color: 'var(--fg-muted)' }}>
                    Prochaine exécution :{' '}
                    {new Date(job.next_run_time).toLocaleString('fr-FR', {
                      dateStyle: 'short',
                      timeStyle: 'short',
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
