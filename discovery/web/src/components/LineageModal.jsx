import React, { useState, useEffect } from 'react'
import { api } from '../api'

// Node layout constants
const NODE_W = 140
const NODE_H = 52
const X_GAP = 200
const Y_GAP = 80

const TYPE_STYLE = {
  source:  { fill: '#e0f2fe', stroke: '#0284c7', text: '#0c4a6e', icon: '📂' },
  dataset: { fill: '#f0fdf4', stroke: '#16a34a', text: '#14532d', icon: '🗄️' },
  table:   { fill: '#f0fdf4', stroke: '#16a34a', text: '#14532d', icon: '🗄️' },
  job:     { fill: '#faf5ff', stroke: '#7c3aed', text: '#3b0764', icon: '⚙️' },
  default: { fill: '#f8fafc', stroke: '#94a3b8', text: '#1e293b', icon: '📦' },
}

// Topological rank assignment (Kahn's algorithm)
function assignRanks(nodes, edges) {
  const inDeg = {}, adj = {}
  nodes.forEach(n => { inDeg[n.id] = 0; adj[n.id] = [] })
  edges.forEach(e => {
    inDeg[e.target] = (inDeg[e.target] || 0) + 1
    adj[e.source] = adj[e.source] || []
    adj[e.source].push(e.target)
  })
  const rank = {}
  const queue = nodes.filter(n => !inDeg[n.id]).map(n => n.id)
  queue.forEach(id => { rank[id] = 0 })
  while (queue.length) {
    const cur = queue.shift()
    ;(adj[cur] || []).forEach(next => {
      rank[next] = Math.max(rank[next] ?? 0, (rank[cur] ?? 0) + 1)
      if (--inDeg[next] === 0) queue.push(next)
    })
  }
  return rank
}

function layoutGraph(nodes, edges) {
  const rank = assignRanks(nodes, edges)
  const byRank = {}
  nodes.forEach(n => {
    const r = rank[n.id] ?? 0
    byRank[r] = byRank[r] || []
    byRank[r].push(n.id)
  })
  const positions = {}
  Object.entries(byRank).forEach(([r, ids]) => {
    const totalH = (ids.length - 1) * Y_GAP
    ids.forEach((id, i) => {
      positions[id] = {
        x: Number(r) * X_GAP + 20,
        y: i * Y_GAP - totalH / 2 + 20,
      }
    })
  })
  return positions
}

function LineageGraph({ nodes, edges }) {
  const positions = layoutGraph(nodes, edges)

  // Canvas size
  const xs = Object.values(positions).map(p => p.x)
  const ys = Object.values(positions).map(p => p.y)
  const minY = Math.min(...ys, 0)
  const maxX = Math.max(...xs, 0) + NODE_W + 20
  const maxY = Math.max(...ys, 0) + NODE_H + 20
  const svgH = maxY - minY + 60
  const offsetY = -minY + 30

  // Edge path: horizontal bezier between node centres
  const edgePath = (src, tgt) => {
    const s = positions[src], t = positions[tgt]
    if (!s || !t) return ''
    const x1 = s.x + NODE_W, y1 = s.y + NODE_H / 2 + offsetY
    const x2 = t.x,          y2 = t.y + NODE_H / 2 + offsetY
    const cx = (x1 + x2) / 2
    return `M ${x1} ${y1} C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}`
  }

  return (
    <svg width={maxX + 20} height={svgH} style={{ minWidth: maxX + 20 }}>
      <defs>
        <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0,0 L0,6 L8,3 z" fill="#7c3aed" />
        </marker>
      </defs>

      {/* Edges */}
      {edges.map(e => (
        <path
          key={e.id}
          d={edgePath(e.source, e.target)}
          fill="none"
          stroke="#7c3aed"
          strokeWidth="1.5"
          strokeDasharray="5,3"
          markerEnd="url(#arrow)"
          opacity="0.7"
        />
      ))}

      {/* Nodes */}
      {nodes.map(n => {
        const pos = positions[n.id]
        if (!pos) return null
        const s = TYPE_STYLE[n.data?.type] || TYPE_STYLE.default
        const y = pos.y + offsetY
        return (
          <g key={n.id}>
            <rect
              x={pos.x} y={y}
              width={NODE_W} height={NODE_H}
              rx="8" ry="8"
              fill={s.fill} stroke={s.stroke} strokeWidth="1.5"
              style={{ filter: 'drop-shadow(0 1px 3px rgba(0,0,0,0.08))' }}
            />
            <text x={pos.x + NODE_W / 2} y={y + 18} textAnchor="middle" fontSize="14">{s.icon}</text>
            <text
              x={pos.x + NODE_W / 2} y={y + 36}
              textAnchor="middle" fontSize="10" fontWeight="500"
              fill={s.text}
              style={{ fontFamily: 'ui-monospace, monospace' }}
            >
              {n.data?.label?.length > 16 ? n.data.label.slice(0, 15) + '…' : n.data?.label}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

export default function LineageModal({ initialDataset, onClose }) {
  const [input, setInput] = useState(initialDataset || '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [data, setData] = useState(null)

  const load = async (name) => {
    if (!name.trim()) return
    setLoading(true)
    setError(null)
    try {
      const result = await api.lineage(name.trim())
      setData(result)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  // Auto-load if opened with a dataset name already
  useEffect(() => { if (initialDataset) load(initialDataset) }, [])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative z-10 w-[90vw] max-w-5xl max-h-[90vh] bg-white rounded-2xl shadow-2xl flex flex-col overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 bg-gray-50/80">
          <div>
            <h2 className="text-lg font-bold text-gray-800">🔗 Data Lineage</h2>
            {data && (
              <div className="flex gap-2 mt-1">
                <span className="badge-blue text-[10px]">📦 {data.dataset}</span>
                <span className="badge-purple text-[10px]">
                  {data.source === 'openlineage' ? '🟢 OpenLineage events' : '🔵 Static pipeline graph'}
                </span>
                <span className="badge-green text-[10px]">{data.nodes.length} nodes · {data.edges.length} edges</span>
              </div>
            )}
          </div>
          <button onClick={onClose} className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors">✕</button>
        </div>

        {/* Search bar */}
        <div className="flex items-center gap-3 px-6 py-3 border-b border-gray-100">
          <input
            className="border border-gray-300 rounded-md px-3 py-1.5 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-indigo-300"
            placeholder="Dataset name (e.g. sensor_data)"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && load(input)}
          />
          <button
            onClick={() => load(input)}
            disabled={loading}
            className="px-4 py-1.5 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {loading ? '⏳ Loading…' : 'Show Lineage'}
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto p-6">
          {error && <div className="text-sm text-red-500 mb-4">❌ {error}</div>}

          {!data && !loading && (
            <div className="flex flex-col items-center justify-center h-48 text-gray-400 gap-2">
              <span className="text-4xl">🔗</span>
              <p className="text-sm">Enter a dataset name to view its lineage graph.</p>
            </div>
          )}

          {loading && (
            <div className="flex items-center justify-center h-48 text-gray-400 text-sm gap-2">
              <span className="animate-spin">⏳</span> Fetching lineage…
            </div>
          )}

          {data && !loading && (
            <>
              {/* Legend */}
              <div className="flex gap-3 mb-4 flex-wrap">
                {[
                  ['📂', 'Source / Landing', '#e0f2fe', '#0284c7'],
                  ['🗄️', 'Dataset / Table',  '#f0fdf4', '#16a34a'],
                  ['⚙️', 'Job / Transform',  '#faf5ff', '#7c3aed'],
                ].map(([icon, label, bg, border]) => (
                  <span key={label} className="flex items-center gap-1 px-2 py-0.5 rounded text-xs"
                    style={{ background: bg, border: `1px solid ${border}`, color: '#374151' }}>
                    {icon} {label}
                  </span>
                ))}
              </div>

              {/* Graph */}
              <div className="overflow-auto rounded-xl border border-gray-100 bg-gray-50 p-4">
                <LineageGraph nodes={data.nodes} edges={data.edges} />
              </div>

              {/* Node list */}
              <details className="mt-4">
                <summary className="text-xs text-gray-400 cursor-pointer hover:text-ontika-blue">
                  Show node details ({data.nodes.length})
                </summary>
                <div className="mt-2 grid grid-cols-3 gap-2">
                  {data.nodes.map(n => {
                    const s = TYPE_STYLE[n.data?.type] || TYPE_STYLE.default
                    return (
                      <div key={n.id} className="px-3 py-2 rounded-lg border text-xs font-mono"
                        style={{ background: s.fill, borderColor: s.stroke, color: s.text }}>
                        {s.icon} {n.data?.label}
                      </div>
                    )
                  })}
                </div>
              </details>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
