import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  Edit3,
  Loader2,
  Menu,
  MessageSquarePlus,
  ShieldAlert,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import {
  api,
  consumePostSSE,
  type ChatMessage,
  type PendingApproval,
  type ThreadItem,
} from '../lib/api'

interface TraceStep {
  node: string
  detail: string
}

const STARTER_PROMPTS = [
  {
    tag: 'Discord Staff',
    title: 'Veille de la journée',
    prompt: 'Fais-moi un résumé de la journée sur le serveur Discord du staff.',
  },
  {
    tag: 'Gmail',
    title: 'Emails non lus',
    prompt: 'Quels sont mes derniers emails non lus importants ?',
  },
  {
    tag: 'Google Calendar',
    title: 'Agenda de la semaine',
    prompt: 'Quels sont mes événements prévus cette semaine sur tous mes agendas ?',
  },
  {
    tag: 'Notion',
    title: 'Tâches ToDo & LPA',
    prompt: 'Liste mes tâches en cours dans ma base Notion ToDo.',
  },
]

export function ChatView() {
  const [threads, setThreads] = useState<ThreadItem[]>([])
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null)
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [traceSteps, setTraceSteps] = useState<TraceStep[]>([])
  const [traceOpen, setTraceOpen] = useState(true)
  const [loadingThread, setLoadingThread] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)

  const bottomRef = useRef<HTMLDivElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  const loadThreads = async (selectFirst = false) => {
    try {
      const { threads: list } = await api.listThreads()
      setThreads(list)
      if (selectFirst && list.length > 0 && !activeThreadId) {
        setActiveThreadId(list[0].id)
      }
    } catch {
      // backend might be restarting
    }
  }

  useEffect(() => {
    loadThreads(true)
  }, [])

  useEffect(() => {
    if (!activeThreadId) {
      setMessages([])
      setPendingApproval(null)
      return
    }
    let cancelled = false
    setLoadingThread(true)
    setTraceSteps([])
    api
      .getMessages(activeThreadId)
      .then((data) => {
        if (cancelled) return
        setMessages(data.messages || [])
        setPendingApproval(data.pending_approval || null)
      })
      .catch(() => {
        if (!cancelled) setMessages([])
      })
      .finally(() => {
        if (!cancelled) setLoadingThread(false)
      })
    return () => {
      cancelled = true
    }
  }, [activeThreadId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, traceSteps, pendingApproval])

  const handleNewThread = async () => {
    const { thread } = await api.createThread('Nouvelle conversation', 'general')
    setThreads((prev) => [thread, ...prev])
    setActiveThreadId(thread.id)
    setMessages([])
    setPendingApproval(null)
    setTraceSteps([])
    setMobileSidebarOpen(false)
  }

  const handleDeleteThread = async (threadId: string) => {
    await api.deleteThread(threadId)
    setThreads((prev) => {
      const next = prev.filter((t) => t.id !== threadId)
      if (activeThreadId === threadId) {
        setActiveThreadId(next[0]?.id ?? null)
      }
      return next
    })
  }

  const handleRenameSubmit = async (threadId: string) => {
    const clean = editingTitle.trim()
    setEditingId(null)
    if (!clean) return
    const { thread } = await api.renameThread(threadId, clean)
    setThreads((prev) => prev.map((t) => (t.id === threadId ? thread : t)))
  }

  const sendMessage = async (textOverride?: string) => {
    const text = (textOverride ?? input).trim()
    if (!text || streaming) return

    let tid = activeThreadId
    if (!tid) {
      const { thread } = await api.createThread(text.slice(0, 52), 'general')
      setThreads((prev) => [thread, ...prev])
      tid = thread.id
      setActiveThreadId(tid)
    }

    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setStreaming(true)
    setTraceSteps([])
    setTraceOpen(true)
    setPendingApproval(null)

    try {
      await consumePostSSE(
        `/api/threads/${encodeURIComponent(tid)}/stream`,
        { message: text },
        (ev) => {
          if (ev.type === 'step') {
            setTraceSteps((prev) => [
              ...prev,
              { node: ev.node || 'nexus', detail: ev.detail || 'Traitement...' },
            ])
          } else if (ev.type === 'approval_required') {
            setPendingApproval(ev.pending_approval || { message: ev.reply })
            setTraceOpen(false)
          } else if (ev.type === 'done') {
            setMessages((prev) => [
              ...prev,
              { role: 'assistant', content: ev.reply || 'Tâche terminée.' },
            ])
            setTraceOpen(false)
          } else if (ev.type === 'error') {
            setMessages((prev) => [
              ...prev,
              { role: 'assistant', content: `⚠️ ${ev.message || 'Erreur inattendue.'}` },
            ])
          }
        },
      )
      await loadThreads(false)
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `⚠️ Impossible de joindre Nexus : ${err instanceof Error ? err.message : String(err)}`,
        },
      ])
    } finally {
      setStreaming(false)
    }
  }

  const handleApproval = async (approved: boolean) => {
    if (!activeThreadId || streaming) return
    setStreaming(true)
    setPendingApproval(null)
    setTraceSteps([
      {
        node: 'hitl',
        detail: approved ? 'Action approuvée par Paulo — reprise...' : 'Action refusée — annulation...',
      },
    ])
    setTraceOpen(true)

    try {
      await consumePostSSE(
        `/api/threads/${encodeURIComponent(activeThreadId)}/approve/stream`,
        { approved, reason: approved ? '' : 'Refusé depuis Mission Control' },
        (ev) => {
          if (ev.type === 'step') {
            setTraceSteps((prev) => [
              ...prev,
              { node: ev.node || 'nexus', detail: ev.detail || 'Traitement...' },
            ])
          } else if (ev.type === 'approval_required') {
            setPendingApproval(ev.pending_approval || { message: ev.reply })
          } else if (ev.type === 'done') {
            setMessages((prev) => [
              ...prev,
              { role: 'assistant', content: ev.reply || 'Reprise terminée.' },
            ])
            setTraceOpen(false)
          } else if (ev.type === 'error') {
            setMessages((prev) => [
              ...prev,
              { role: 'assistant', content: `⚠️ ${ev.message || 'Erreur HITL.'}` },
            ])
          }
        },
      )
    } finally {
      setStreaming(false)
    }
  }

  const threadSidebarContent = (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between p-3 hairline-b">
        <span className="text-xs font-medium" style={{ color: 'var(--fg-secondary)' }}>
          Fils ({threads.length})
        </span>
        <button
          onClick={handleNewThread}
          className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-opacity hover:opacity-90 cursor-pointer"
          style={{ backgroundColor: 'var(--accent)', color: 'var(--accent-fg)' }}
        >
          <MessageSquarePlus className="h-3.5 w-3.5" />
          Nouveau
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {threads.length === 0 && (
          <div className="px-3 py-8 text-center text-xs" style={{ color: 'var(--fg-muted)' }}>
            Aucune conversation.
            <br />
            Crée un fil ou envoie un message.
          </div>
        )}
        {threads.map((t) => {
          const active = t.id === activeThreadId
          const isEditing = editingId === t.id
          return (
            <div
              key={t.id}
              onClick={() => {
                if (!isEditing) {
                  setActiveThreadId(t.id)
                  setMobileSidebarOpen(false)
                }
              }}
              className="group flex items-center justify-between gap-1.5 rounded-lg px-2.5 py-2 text-xs transition-colors cursor-pointer"
              style={{
                backgroundColor: active ? 'var(--bg-elevated)' : 'transparent',
                border: active ? '1px solid var(--border)' : '1px solid transparent',
                color: active ? 'var(--fg-primary)' : 'var(--fg-secondary)',
              }}
            >
              <div className="min-w-0 flex-1">
                {isEditing ? (
                  <input
                    autoFocus
                    value={editingTitle}
                    onChange={(e) => setEditingTitle(e.target.value)}
                    onBlur={() => handleRenameSubmit(t.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleRenameSubmit(t.id)
                      if (e.key === 'Escape') setEditingId(null)
                    }}
                    className="w-full rounded px-1.5 py-0.5 text-xs outline-none"
                    style={{
                      backgroundColor: 'var(--bg-canvas)',
                      border: '1px solid var(--border-strong)',
                      color: 'var(--fg-primary)',
                    }}
                  />
                ) : (
                  <>
                    <div className="truncate font-medium">{t.title}</div>
                    <div
                      className="font-mono-tabular text-[10px] mt-0.5 truncate"
                      style={{ color: 'var(--fg-muted)' }}
                    >
                      {t.id}
                    </div>
                  </>
                )}
              </div>

              {!isEditing && (
                <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      setEditingId(t.id)
                      setEditingTitle(t.title)
                    }}
                    title="Renommer"
                    className="p-1 rounded hover:bg-white/10 cursor-pointer"
                  >
                    <Edit3 className="h-3 w-3" />
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      handleDeleteThread(t.id)
                    }}
                    title="Supprimer"
                    className="p-1 rounded hover:bg-white/10 cursor-pointer"
                    style={{ color: 'var(--rose)' }}
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )

  return (
    <div className="relative flex h-full w-full overflow-hidden">
      {/* Desktop Threads Sidebar */}
      <aside
        className="hidden lg:block w-[264px] shrink-0 hairline-r"
        style={{ backgroundColor: 'var(--bg-canvas)' }}
      >
        {threadSidebarContent}
      </aside>

      {/* Mobile Slide-Over Threads Drawer */}
      {mobileSidebarOpen && (
        <div className="fixed inset-0 z-40 flex lg:hidden">
          <div
            className="w-72 max-w-[82vw] h-full hairline-r shadow-2xl"
            style={{ backgroundColor: 'var(--bg-surface)' }}
          >
            {threadSidebarContent}
          </div>
          <div
            className="flex-1 bg-black/50 backdrop-blur-xs"
            onClick={() => setMobileSidebarOpen(false)}
          />
        </div>
      )}

      {/* Main Conversation Stage */}
      <section className="flex flex-1 flex-col min-w-0 h-full">
        {/* Compact Sub-bar for Mobile Thread Picker */}
        <div className="flex lg:hidden items-center justify-between px-4 py-2 hairline-b text-xs">
          <button
            onClick={() => setMobileSidebarOpen(true)}
            className="inline-flex items-center gap-1.5 font-medium"
            style={{ color: 'var(--fg-secondary)' }}
          >
            <Menu className="h-3.5 w-3.5" />
            <span>
              {threads.find((t) => t.id === activeThreadId)?.title || 'Conversations'}
            </span>
          </button>
          <button
            onClick={handleNewThread}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium"
            style={{ backgroundColor: 'var(--bg-elevated)', border: '1px solid var(--border)' }}
          >
            <MessageSquarePlus className="h-3 w-3" />
            Nouveau
          </button>
        </div>

        {/* Scrollable Messages Area */}
        <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6">
          <div className="mx-auto max-w-3xl space-y-5">
            {loadingThread && (
              <div className="flex items-center gap-2 text-xs py-6" style={{ color: 'var(--fg-muted)' }}>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Chargement de la conversation...
              </div>
            )}

            {!loadingThread && messages.length === 0 && !streaming && (
              <div className="py-10 md:py-16 space-y-8">
                <div className="space-y-2">
                  <div
                    className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-mono-tabular"
                    style={{
                      backgroundColor: 'var(--bg-surface)',
                      border: '1px solid var(--border)',
                      color: 'var(--fg-secondary)',
                    }}
                  >
                    <Sparkles className="h-3 w-3" />
                    LangGraph · 3 Agents · 56 outils MCP
                  </div>
                  <h2 className="heading-tight text-2xl md:text-3xl font-semibold">
                    Que veux-tu orchestrer ?
                  </h2>
                  <p className="text-sm max-w-xl" style={{ color: 'var(--fg-secondary)' }}>
                    Chaque fil conserve sa propre mémoire PostgreSQL. Les actions critiques (envoi
                    d&apos;email, création d&apos;événement) demandent ta validation en direct.
                  </p>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {STARTER_PROMPTS.map((item) => (
                    <button
                      key={item.title}
                      onClick={() => sendMessage(item.prompt)}
                      className="bento-card bento-card-interactive p-4 text-left space-y-1.5 cursor-pointer"
                    >
                      <div
                        className="font-mono-tabular text-[10px] uppercase tracking-wider"
                        style={{ color: 'var(--fg-muted)' }}
                      >
                        {item.tag}
                      </div>
                      <div className="text-sm font-medium">{item.title}</div>
                      <div className="text-xs line-clamp-2" style={{ color: 'var(--fg-secondary)' }}>
                        {item.prompt}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, idx) => (
              <div
                key={idx}
                className={msg.role === 'user' ? 'flex justify-end' : 'flex justify-start'}
              >
                {msg.role === 'user' ? (
                  <div
                    className="max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed"
                    style={{
                      backgroundColor: 'var(--bg-elevated)',
                      border: '1px solid var(--border-strong)',
                    }}
                  >
                    {msg.content}
                  </div>
                ) : (
                  <div className="w-full bento-card px-5 py-4 space-y-2">
                    <div className="flex items-center justify-between">
                      <span
                        className="font-mono-tabular text-[11px] font-medium"
                        style={{ color: 'var(--fg-muted)' }}
                      >
                        nexus · {msg.agent || 'supervisor'}
                      </span>
                    </div>
                    <div className="nexus-prose">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                    </div>
                  </div>
                )}
              </div>
            ))}

            {/* Real-Time Execution Trace Pill */}
            {(streaming || traceSteps.length > 0) && (
              <div
                className="rounded-xl px-4 py-3 text-xs space-y-2"
                style={{
                  backgroundColor: 'var(--bg-surface)',
                  border: '1px solid var(--border)',
                }}
              >
                <button
                  onClick={() => setTraceOpen((v) => !v)}
                  className="flex w-full items-center justify-between text-left cursor-pointer"
                >
                  <span className="inline-flex items-center gap-2 font-medium">
                    {streaming ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" style={{ color: 'var(--emerald)' }} />
                    ) : (
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: 'var(--emerald)' }}
                      />
                    )}
                    <span>
                      {streaming
                        ? 'Exécution multi-agents en cours...'
                        : `Trace d'exécution (${traceSteps.length} étapes)`}
                    </span>
                  </span>
                  {traceOpen ? (
                    <ChevronDown className="h-3.5 w-3.5" style={{ color: 'var(--fg-muted)' }} />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5" style={{ color: 'var(--fg-muted)' }} />
                  )}
                </button>

                {traceOpen && traceSteps.length > 0 && (
                  <div className="space-y-1.5 pt-1 hairline-t">
                    {traceSteps.map((step, i) => (
                      <div key={i} className="flex items-start gap-2.5 font-mono-tabular text-[11px]">
                        <span
                          className="shrink-0 rounded px-1.5 py-0.5"
                          style={{
                            backgroundColor: 'var(--bg-elevated)',
                            color: 'var(--fg-secondary)',
                          }}
                        >
                          {step.node}
                        </span>
                        <span style={{ color: 'var(--fg-secondary)' }}>{step.detail}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Human-in-the-Loop Interactive Approval Card */}
            {pendingApproval && (
              <div
                className="bento-card p-5 space-y-4"
                style={{
                  borderColor: 'var(--amber)',
                  borderLeftWidth: '3px',
                }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <ShieldAlert className="h-4 w-4 shrink-0" style={{ color: 'var(--amber)' }} />
                    <div>
                      <div className="text-sm font-semibold">Validation humaine requise (HITL)</div>
                      <div className="text-xs" style={{ color: 'var(--fg-secondary)' }}>
                        {pendingApproval.message ||
                          'Une action critique attend ton feu vert avant exécution.'}
                      </div>
                    </div>
                  </div>
                  {pendingApproval.tool_name && (
                    <span
                      className="font-mono-tabular text-[11px] rounded-md px-2 py-0.5"
                      style={{
                        backgroundColor: 'var(--amber-soft)',
                        color: 'var(--amber)',
                      }}
                    >
                      {pendingApproval.tool_name}
                    </span>
                  )}
                </div>

                {pendingApproval.tool_args && (
                  <pre
                    className="font-mono-tabular text-[11px] rounded-lg p-3 overflow-x-auto"
                    style={{
                      backgroundColor: 'var(--bg-canvas)',
                      border: '1px solid var(--border)',
                      color: 'var(--fg-secondary)',
                    }}
                  >
                    {JSON.stringify(pendingApproval.tool_args, null, 2)}
                  </pre>
                )}

                <div className="flex items-center gap-2.5">
                  <button
                    onClick={() => handleApproval(true)}
                    disabled={streaming}
                    className="inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-xs font-medium cursor-pointer"
                    style={{ backgroundColor: 'var(--accent)', color: 'var(--accent-fg)' }}
                  >
                    <Check className="h-3.5 w-3.5" />
                    Valider et exécuter
                  </button>
                  <button
                    onClick={() => handleApproval(false)}
                    disabled={streaming}
                    className="inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-xs font-medium cursor-pointer"
                    style={{
                      backgroundColor: 'var(--rose-soft)',
                      color: 'var(--rose)',
                      border: '1px solid var(--border)',
                    }}
                  >
                    <X className="h-3.5 w-3.5" />
                    Refuser
                  </button>
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        </div>

        {/* Composer Input Bar */}
        <div className="shrink-0 px-4 md:px-8 pb-4 pt-2">
          <div
            className="mx-auto max-w-3xl flex items-end gap-2 rounded-2xl p-2 pl-4 transition-colors"
            style={{
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-strong)',
            }}
          >
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  sendMessage()
                }
              }}
              placeholder="Demande à Nexus (Gmail, Calendar, Notion, Discord staff...)"
              className="flex-1 resize-none bg-transparent py-2 text-sm outline-none max-h-36"
              style={{ color: 'var(--fg-primary)' }}
            />
            <button
              onClick={() => sendMessage()}
              disabled={streaming || !input.trim()}
              aria-label="Envoyer"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition-opacity disabled:opacity-35 cursor-pointer"
              style={{ backgroundColor: 'var(--accent)', color: 'var(--accent-fg)' }}
            >
              {streaming ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ArrowUp className="h-4 w-4" />
              )}
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
