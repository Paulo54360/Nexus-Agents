export interface ThreadItem {
  id: string
  title: string
  category: string
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  agent?: string
}

export interface PendingApproval {
  tool_name?: string
  tool_args?: Record<string, unknown>
  message?: string
  [key: string]: unknown
}

export interface StreamEvent {
  type: 'step' | 'approval_required' | 'done' | 'error'
  node?: string
  detail?: string
  thread_id?: string
  reply?: string
  pending_approval?: PendingApproval | null
  message?: string
}

export interface UsageStats {
  days: number
  summary: {
    total_tokens: number
    prompt_tokens: number
    completion_tokens: number
    total_calls: number
    avg_latency_ms: number
    error_calls: number
    estimated_cost_eur: number
  }
  by_day: Array<{
    day: string
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
    calls: number
  }>
  by_model: Array<{
    model: string
    provider: string
    total_tokens: number
    calls: number
    avg_latency_ms: number
  }>
  by_agent: Array<{
    agent: string
    total_tokens: number
    calls: number
    avg_latency_ms: number
  }>
  recent: Array<{
    id?: number
    thread_id: string | null
    agent: string
    model: string
    provider: string
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
    latency_ms: number
    status: string
    created_at: string
  }>
}

export interface AgentToolInfo {
  name: string
  description: string
}

export interface ArchitectureData {
  system: {
    env: string
    started_at: string | null
    mock_tools: boolean
    postgres_connected: boolean
    discord_connected: boolean
    discord_guilds: number
    scheduler_running: boolean
    scheduled_jobs: number
    automations_enabled: number
    total_tools: number
    langfuse_enabled: boolean
    langfuse_host: string
  }
  agents: Array<{
    id: string
    label: string
    role: string
    model_tier: string
    hitl: boolean
    tools: AgentToolInfo[]
    status: 'online' | 'degraded' | 'standby'
  }>
  mcp_servers: Array<{
    name: string
    agent: string
    enabled: boolean
    transport: string
    command: string
  }>
  litellm: {
    models: Array<{ alias: string; targets: string[] }>
    fallbacks: Array<Record<string, string[]>>
  }
}

export interface LogEntry {
  ts: string
  level: string
  logger: string
  message: string
}

export interface AutomationRule {
  id: string
  name: string
  enabled: boolean
  trigger: Record<string, unknown>
  prompt: string
  notify_channel_id: number | null
}

export interface ScheduledJob {
  id: string
  name: string
  trigger: string
  next_run_time: string | null
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${body || res.statusText}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () =>
    fetchJson<{
      status: string
      env: string
      mock_tools: string
      postgres?: boolean
      discord_ready?: boolean
    }>('/health'),

  listThreads: () => fetchJson<{ threads: ThreadItem[] }>('/api/threads'),

  createThread: (title = 'Nouvelle conversation', category = 'general') =>
    fetchJson<{ thread: ThreadItem }>('/api/threads', {
      method: 'POST',
      body: JSON.stringify({ title, category }),
    }),

  renameThread: (threadId: string, title: string, category?: string) =>
    fetchJson<{ thread: ThreadItem }>(`/api/threads/${encodeURIComponent(threadId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ title, category }),
    }),

  deleteThread: (threadId: string) =>
    fetchJson<{ deleted: boolean }>(`/api/threads/${encodeURIComponent(threadId)}`, {
      method: 'DELETE',
    }),

  getMessages: (threadId: string) =>
    fetchJson<{
      thread_id: string
      messages: ChatMessage[]
      pending_approval: PendingApproval | null
    }>(`/api/threads/${encodeURIComponent(threadId)}/messages`),

  getUsageStats: (days = 7) => fetchJson<UsageStats>(`/api/stats/usage?days=${days}`),

  getArchitecture: () => fetchJson<ArchitectureData>('/api/architecture'),

  getRecentLogs: (limit = 180) => fetchJson<{ logs: LogEntry[] }>(`/api/logs/recent?limit=${limit}`),

  getAutomations: () =>
    fetchJson<{ rules: AutomationRule[]; scheduled_jobs: ScheduledJob[] }>('/api/automations'),

  toggleAutomation: (ruleId: string) =>
    fetchJson<{ rule: AutomationRule }>(`/api/automations/${encodeURIComponent(ruleId)}/toggle`, {
      method: 'POST',
    }),

  runAutomation: (ruleId: string) =>
    fetchJson<{ status: string; rule_id: string }>(
      `/api/automations/${encodeURIComponent(ruleId)}/run`,
      { method: 'POST' },
    ),

  reloadAutomations: () =>
    fetchJson<{ reloaded: boolean; rules: AutomationRule[] }>('/api/automations/reload', {
      method: 'POST',
    }),
}

/** Consume an HTTP POST Server-Sent Events stream cleanly. */
export async function consumePostSSE(
  url: string,
  body: Record<string, unknown>,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`Stream HTTP ${res.status}: ${text}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() ?? ''

    for (const chunk of chunks) {
      for (const line of chunk.split('\n')) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('data:')) continue
        const jsonStr = trimmed.slice(5).trim()
        if (!jsonStr) continue
        try {
          onEvent(JSON.parse(jsonStr) as StreamEvent)
        } catch {
          // ignore malformed partial frame
        }
      }
    }
  }
}
