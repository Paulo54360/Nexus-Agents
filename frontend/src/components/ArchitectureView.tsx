import { useEffect, useMemo, useState } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import { Cpu, Database, Layers, RefreshCw, Shield, Wrench, X } from 'lucide-react'
import { api, type ArchitectureData } from '../lib/api'

interface ArchNodeData extends Record<string, unknown> {
  title: string
  subtitle: string
  badge: string
  status: 'online' | 'degraded' | 'standby'
  category: 'entry' | 'orchestrator' | 'agent' | 'infra'
  detailsKey: string
}

function RefinedNode({ data, selected }: NodeProps<Node<ArchNodeData>>) {
  const dotColor =
    data.status === 'online'
      ? 'var(--emerald)'
      : data.status === 'degraded'
        ? 'var(--amber)'
        : 'var(--fg-muted)'

  return (
    <div
      className="rounded-xl px-4 py-3 min-w-[196px] transition-colors"
      style={{
        backgroundColor: 'var(--bg-surface)',
        border: selected ? '1px solid var(--fg-primary)' : '1px solid var(--border-strong)',
        color: 'var(--fg-primary)',
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        style={{ background: 'var(--border-strong)', width: 6, height: 6, border: 'none' }}
      />
      <div className="flex items-center justify-between gap-2 mb-1">
        <span
          className="font-mono-tabular text-[10px] uppercase tracking-wider"
          style={{ color: 'var(--fg-muted)' }}
        >
          {data.badge}
        </span>
        <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: dotColor }} />
      </div>
      <div className="heading-tight text-[13px] font-semibold">{data.title}</div>
      <div className="text-[11px] mt-0.5 truncate max-w-[200px]" style={{ color: 'var(--fg-secondary)' }}>
        {data.subtitle}
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        style={{ background: 'var(--border-strong)', width: 6, height: 6, border: 'none' }}
      />
    </div>
  )
}

const nodeTypes = { refined: RefinedNode }

export function ArchitectureView() {
  const [data, setData] = useState<ArchitectureData | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedKey, setSelectedKey] = useState<string | null>('supervisor')

  const load = async () => {
    setLoading(true)
    try {
      const res = await api.getArchitecture()
      setData(res)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const { nodes, edges } = useMemo(() => {
    const sys = data?.system
    const findAgent = (id: string) => data?.agents.find((a) => a.id === id)
    const gmail = findAgent('gmail_agent')
    const prod = findAgent('productivity_agent')
    const asso = findAgent('asso_agent')

    const builtNodes: Node<ArchNodeData>[] = [
      {
        id: 'interfaces',
        type: 'refined',
        position: { x: 290, y: 20 },
        data: {
          title: 'Web PWA + Discord Bot',
          subtitle: sys?.discord_connected
            ? `Tailscale HTTPS · ${sys.discord_guilds} serveurs`
            : 'Tailscale HTTPS · API FastAPI',
          badge: 'ENTRÉES',
          status: 'online',
          category: 'entry',
          detailsKey: 'interfaces',
        },
      },
      {
        id: 'supervisor',
        type: 'refined',
        position: { x: 290, y: 150 },
        data: {
          title: 'LangGraph Supervisor',
          subtitle: 'Routage nexus-fast → synthèse',
          badge: 'ORCHESTRATEUR',
          status: 'online',
          category: 'orchestrator',
          detailsKey: 'supervisor',
        },
      },
      {
        id: 'gmail_agent',
        type: 'refined',
        position: { x: 40, y: 295 },
        data: {
          title: 'Gmail Agent',
          subtitle: `${gmail?.tools.length ?? 0} outils MCP · HITL`,
          badge: 'AGENT',
          status: gmail?.status ?? 'online',
          category: 'agent',
          detailsKey: 'gmail_agent',
        },
      },
      {
        id: 'productivity_agent',
        type: 'refined',
        position: { x: 290, y: 295 },
        data: {
          title: 'Productivity Agent',
          subtitle: `${prod?.tools.length ?? 0} outils Calendar & Notion`,
          badge: 'AGENT',
          status: prod?.status ?? 'online',
          category: 'agent',
          detailsKey: 'productivity_agent',
        },
      },
      {
        id: 'asso_agent',
        type: 'refined',
        position: { x: 540, y: 295 },
        data: {
          title: 'Asso Monitor Agent',
          subtitle: `${asso?.tools.length ?? 3} outils · Lecture seule`,
          badge: 'AGENT',
          status: asso?.status ?? 'standby',
          category: 'agent',
          detailsKey: 'asso_agent',
        },
      },
      {
        id: 'litellm',
        type: 'refined',
        position: { x: 110, y: 445 },
        data: {
          title: 'LiteLLM Proxy (0 €)',
          subtitle: 'Groq · Mistral · Gemini cascade',
          badge: 'LLM GATEWAY',
          status: 'online',
          category: 'infra',
          detailsKey: 'litellm',
        },
      },
      {
        id: 'postgres',
        type: 'refined',
        position: { x: 450, y: 445 },
        data: {
          title: 'PostgreSQL + pgvector',
          subtitle: sys?.postgres_connected ? 'Checkpoints, threads & FinOps' : 'Fallback mémoire',
          badge: 'PERSISTANCE',
          status: sys?.postgres_connected ? 'online' : 'degraded',
          category: 'infra',
          detailsKey: 'postgres',
        },
      },
    ]

    const edgeStyle = { stroke: 'var(--border-strong)', strokeWidth: 1.5 }
    const builtEdges: Edge[] = [
      { id: 'e-in-sup', source: 'interfaces', target: 'supervisor', animated: true, style: edgeStyle },
      { id: 'e-sup-gm', source: 'supervisor', target: 'gmail_agent', style: edgeStyle },
      { id: 'e-sup-pr', source: 'supervisor', target: 'productivity_agent', style: edgeStyle },
      { id: 'e-sup-as', source: 'supervisor', target: 'asso_agent', style: edgeStyle },
      { id: 'e-gm-llm', source: 'gmail_agent', target: 'litellm', style: edgeStyle },
      { id: 'e-pr-llm', source: 'productivity_agent', target: 'litellm', style: edgeStyle },
      { id: 'e-as-llm', source: 'asso_agent', target: 'litellm', style: edgeStyle },
      { id: 'e-pr-pg', source: 'productivity_agent', target: 'postgres', style: edgeStyle },
      { id: 'e-as-pg', source: 'asso_agent', target: 'postgres', style: edgeStyle },
    ]
    return { nodes: builtNodes, edges: builtEdges }
  }, [data])

  const selectedAgent = data?.agents.find((a) => a.id === selectedKey)

  return (
    <div className="flex h-full w-full flex-col lg:flex-row overflow-hidden">
      {/* Interactive Topology Canvas */}
      <div className="relative flex-1 min-h-[380px]">
        <div className="absolute top-4 left-4 z-10 flex items-center gap-2">
          <div
            className="rounded-xl px-3 py-2 text-xs flex items-center gap-3 backdrop-blur-md"
            style={{
              backgroundColor: 'var(--bg-glass)',
              border: '1px solid var(--border)',
            }}
          >
            <span className="font-medium">Topologie live</span>
            <span className="font-mono-tabular text-[11px]" style={{ color: 'var(--fg-muted)' }}>
              {data?.system.total_tools ?? 0} outils MCP · {data?.system.scheduled_jobs ?? 0} jobs CRON
            </span>
          </div>
          <button
            onClick={load}
            className="flex h-8 w-8 items-center justify-center rounded-lg cursor-pointer backdrop-blur-md"
            style={{
              backgroundColor: 'var(--bg-glass)',
              border: '1px solid var(--border)',
              color: 'var(--fg-secondary)',
            }}
            title="Rafraîchir l'état"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          onNodeClick={(_, node) => setSelectedKey(String(node.data.detailsKey || node.id))}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="var(--border-strong)" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>

      {/* Right-Side Precision Inspector Drawer */}
      <aside
        className="w-full lg:w-[370px] shrink-0 hairline-t lg:hairline-t-0 lg:hairline-l overflow-y-auto p-5 space-y-5"
        style={{ backgroundColor: 'var(--bg-surface)' }}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Layers className="h-4 w-4" style={{ color: 'var(--fg-secondary)' }} />
            <h3 className="heading-tight text-sm font-semibold">Inspecteur</h3>
          </div>
          {selectedKey && (
            <button
              onClick={() => setSelectedKey(null)}
              className="p-1 rounded hover:bg-white/10 cursor-pointer"
              style={{ color: 'var(--fg-muted)' }}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {selectedAgent ? (
          <div className="space-y-4">
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <div className="text-base font-semibold heading-tight">{selectedAgent.label}</div>
                {selectedAgent.hitl && (
                  <span
                    className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono-tabular text-[10px]"
                    style={{ backgroundColor: 'var(--amber-soft)', color: 'var(--amber)' }}
                  >
                    <Shield className="h-2.5 w-2.5" />
                    HITL
                  </span>
                )}
              </div>
              <p className="text-xs" style={{ color: 'var(--fg-secondary)' }}>
                {selectedAgent.role}
              </p>
              <div className="font-mono-tabular text-[11px] pt-1" style={{ color: 'var(--fg-muted)' }}>
                Modèle : {selectedAgent.model_tier}
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs font-medium">
                <span className="inline-flex items-center gap-1.5">
                  <Wrench className="h-3.5 w-3.5" style={{ color: 'var(--fg-muted)' }} />
                  Outils chargés
                </span>
                <span className="font-mono-tabular text-[11px]" style={{ color: 'var(--fg-muted)' }}>
                  {selectedAgent.tools.length}
                </span>
              </div>

              {selectedAgent.tools.length === 0 ? (
                <div
                  className="rounded-lg p-3 text-xs"
                  style={{ backgroundColor: 'var(--bg-canvas)', color: 'var(--fg-muted)' }}
                >
                  Le Supervisor route vers les agents spécialisés sans appeler d&apos;outil directement.
                </div>
              ) : (
                <div className="space-y-1.5 max-h-[380px] overflow-y-auto pr-1">
                  {selectedAgent.tools.map((tool) => (
                    <div
                      key={tool.name}
                      className="rounded-lg px-3 py-2 text-xs space-y-0.5"
                      style={{
                        backgroundColor: 'var(--bg-canvas)',
                        border: '1px solid var(--border)',
                      }}
                    >
                      <div className="font-mono-tabular text-[11px] font-medium">{tool.name}</div>
                      {tool.description && (
                        <div className="text-[11px] line-clamp-2" style={{ color: 'var(--fg-muted)' }}>
                          {tool.description}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : selectedKey === 'litellm' ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Cpu className="h-4 w-4" />
              <div className="text-sm font-semibold">Cascade LiteLLM Proxy (0 €)</div>
            </div>
            <div className="space-y-2">
              {data?.litellm.models.map((m) => (
                <div
                  key={m.alias}
                  className="rounded-lg p-3 text-xs space-y-1"
                  style={{
                    backgroundColor: 'var(--bg-canvas)',
                    border: '1px solid var(--border)',
                  }}
                >
                  <div className="font-mono-tabular font-medium">{m.alias}</div>
                  {m.targets.map((t) => (
                    <div key={t} className="font-mono-tabular text-[11px]" style={{ color: 'var(--fg-muted)' }}>
                      → {t}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-4 text-xs">
            <div className="flex items-center gap-2">
              <Database className="h-4 w-4" />
              <div className="text-sm font-semibold">État Infrastructure</div>
            </div>
            <div className="space-y-2">
              {[
                ['Environnement', data?.system.env ?? 'prod'],
                ['PostgreSQL pgvector', data?.system.postgres_connected ? 'Connecté' : 'Mémoire'],
                ['Discord Bot', data?.system.discord_connected ? 'Connecté' : 'En veille'],
                ['Langfuse Cloud', data?.system.langfuse_enabled ? 'Actif' : 'Inactif'],
                ['Outils MCP chargés', String(data?.system.total_tools ?? 0)],
                ['Automatisations actives', String(data?.system.automations_enabled ?? 0)],
              ].map(([k, v]) => (
                <div
                  key={k}
                  className="flex items-center justify-between rounded-lg px-3 py-2"
                  style={{
                    backgroundColor: 'var(--bg-canvas)',
                    border: '1px solid var(--border)',
                  }}
                >
                  <span style={{ color: 'var(--fg-secondary)' }}>{k}</span>
                  <span className="font-mono-tabular font-medium">{v}</span>
                </div>
              ))}
            </div>
            <p style={{ color: 'var(--fg-muted)' }}>
              Clique sur un nœud du graphe pour inspecter ses outils MCP ou sa configuration de routage.
            </p>
          </div>
        )}
      </aside>
    </div>
  )
}
