import React, { useState, useEffect } from 'react'
import { api } from '../api'
import { LineageGraph } from './LineageModal'

const TABS = ['Details', 'Sample Data', 'Lineage', 'Data Quality']

const TRANSFORM_STYLE = {
  IDENTITY: { bg: '#f0fdf4', border: '#16a34a', text: '#14532d', label: 'pass-through' },
  HASH:     { bg: '#fef3c7', border: '#d97706', text: '#92400e', label: 'hashed' },
  DERIVED:  { bg: '#faf5ff', border: '#7c3aed', text: '#3b0764', label: 'derived' },
  MASKED:   { bg: '#fff1f2', border: '#e11d48', text: '#9f1239', label: 'masked' },
}

export default function CatalogDetailModal({ node, onClose }) {
  const [tab, setTab] = useState(0)
  const type = node.type || 'term'
  const isDataset = type === 'table' || type === 'dataset'
  const datasetId = node.id

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-[92vw] max-w-5xl max-h-[90vh] bg-white rounded-2xl shadow-2xl flex flex-col overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 bg-gray-50/80">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">
                {type === 'application' ? 'Business Application' : type === 'term' ? 'Business Data Element' : type === 'domain' ? 'Data Domain' : type}
              </span>
              {node.is_pii && <span className="badge-red text-[9px]">PII</span>}
              {node.dq_rules && Object.keys(node.dq_rules).length > 0 && <span className="badge-blue text-[9px]">DQ</span>}
            </div>
            <h2 className="text-lg font-bold text-gray-800">{node.name}</h2>
          </div>
          <button onClick={onClose} className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors">✕</button>
        </div>

        {/* Tab bar */}
        <div className="flex border-b border-gray-100 px-6 bg-white">
          {TABS.map((t, i) => (
            <button
              key={t}
              onClick={() => setTab(i)}
              className={`px-4 py-3 text-xs font-medium border-b-2 transition-colors ${
                tab === i
                  ? 'border-indigo-500 text-indigo-600'
                  : 'border-transparent text-gray-400 hover:text-gray-600'
              }`}
            >
              {['📋', '📊', '🔗', '✅'][i]} {t}
            </button>
          ))}
        </div>

        {/* Tab body */}
        <div className="flex-1 overflow-auto">
          {tab === 0 && <DetailsTab node={node} type={type} />}
          {tab === 1 && <SampleDataTab datasetId={datasetId} isDataset={isDataset} node={node} type={type} />}
          {tab === 2 && <LineageTab datasetId={datasetId} />}
          {tab === 3 && <DQTab datasetId={datasetId} isDataset={isDataset} node={node} />}
        </div>
      </div>
    </div>
  )
}

// ── Details Tab ───────────────────────────────────────────────────────────────

function DetailsTab({ node, type }) {
  return (
    <div className="p-6 space-y-5">
      {/* Core metadata */}
      <div className="card-static p-4">
        <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-3">Metadata</p>
        <div className="grid grid-cols-2 gap-x-8 gap-y-2">
          {node.domain && <Row label="Domain" value={node.domain} />}
          {node.data_type && <Row label="Data Type" value={node.data_type} />}
          {node.information_type && <Row label="Information Type" value={node.information_type} />}
          <Row label="PII" value={node.is_pii ? '🔴 Yes' : '🟢 No'} />
          <Row label="Description" value={node.description || generateDescription(node, type)} />
          {node.term_count > 0 && <Row label="BDE Count" value={node.term_count} />}
        </div>
      </div>

      {/* Synonyms */}
      {node.synonyms?.length > 0 && (
        <div className="card-static p-4">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-2">Synonyms</p>
          <div className="flex flex-wrap gap-1.5">
            {node.synonyms.map(s => (
              <span key={s} className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs font-mono">{s}</span>
            ))}
          </div>
        </div>
      )}

      {/* DQ Rules */}
      {node.dq_rules && Object.keys(node.dq_rules).length > 0 && (
        <div className="card-static p-4">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-3">DQ Rules (inherited by all tables using this BDE)</p>
          <div className="space-y-1.5">
            {Object.entries(node.dq_rules).map(([rule, val]) => (
              <div key={rule} className="flex items-center gap-2 px-3 py-2 bg-indigo-50 rounded-lg">
                <span className="text-indigo-600 font-mono text-xs font-medium">{rule}</span>
                <span className="text-gray-400 text-xs">→</span>
                <span className="text-gray-600 text-xs">{JSON.stringify(val)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Child BDEs (for BA nodes) */}
      {type === 'application' && node.children?.filter(c => c.type === 'term').length > 0 && (
        <div className="card-static p-4">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-3">
            Business Data Elements ({node.children.filter(c => c.type === 'term').length})
          </p>
          <div className="grid grid-cols-2 gap-1.5">
            {node.children.filter(c => c.type === 'term').map(t => (
              <div key={t.id} className="flex items-center gap-2 px-3 py-2 bg-gray-50 rounded-lg">
                <span className="text-sm">📖</span>
                <span className="text-xs text-gray-700 font-medium">{t.name}</span>
                {t.is_pii && <span className="badge-red text-[9px]">PII</span>}
                {t.dq_rules && Object.keys(t.dq_rules).length > 0 && <span className="badge-blue text-[9px]">DQ</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function generateDescription(node, type) {
  if (type === 'term') {
    const parts = []
    if (node.information_type) parts.push(`${node.information_type} data element`)
    if (node.domain) parts.push(`in the ${node.domain} domain`)
    if (node.is_pii) parts.push('— contains PII')
    if (node.synonyms?.length) parts.push(`(also known as: ${node.synonyms.join(', ')})`)
    return parts.length ? parts.join(' ') : `Business data element: ${node.name}`
  }
  if (type === 'application') {
    return `Business application managing data elements${node.domain ? ` in the ${node.domain} domain` : ''}.`
  }
  if (type === 'domain') {
    return `Data domain grouping ${node.term_count || 0} business data elements.`
  }
  return ''
}

function Row({ label, value }) {
  return (
    <div className="flex justify-between text-xs py-1 border-b border-gray-50">
      <span className="text-gray-400">{label}</span>
      <span className="text-gray-700 font-medium">{value}</span>
    </div>
  )
}

// ── Sample Data Tab ───────────────────────────────────────────────────────────

function SampleDataTab({ datasetId, isDataset, node, type }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!isDataset) { setLoading(false); return }
    api.profileDataset(datasetId)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [datasetId, isDataset])

  if (!isDataset) return <NonDatasetSampleView node={node} type={type} />
  if (loading) return <Loading text="Loading sample data…" />
  if (error) return <Err text={error} />
  if (!data) return <Empty text="No sample data available." />

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-sm font-semibold text-gray-800">{data.dataset_name || datasetId}</p>
          <p className="text-xs text-gray-400">{data.row_count?.toLocaleString()} rows · {data.column_count} columns</p>
        </div>
        {data.duration_seconds && (
          <span className="text-xs text-gray-400">profiled in {data.duration_seconds}s</span>
        )}
      </div>

      <div className="card-static overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr className="text-gray-500 uppercase tracking-wider text-[10px]">
              <th className="px-3 py-3 text-left font-semibold">Column</th>
              <th className="px-3 py-3 text-left font-semibold">Type</th>
              <th className="px-3 py-3 text-center font-semibold">Null %</th>
              <th className="px-3 py-3 text-center font-semibold">Distinct</th>
              <th className="px-3 py-3 text-center font-semibold">PII</th>
              <th className="px-3 py-3 text-center font-semibold">Key</th>
              <th className="px-3 py-3 text-left font-semibold">Sample Values</th>
            </tr>
          </thead>
          <tbody>
            {(data.fields || data.columns || []).map((f, i) => (
              <tr key={i} className="border-b border-gray-50 hover:bg-indigo-50/30 transition-colors">
                <td className="px-3 py-2.5 font-mono text-gray-800 font-medium">{f.name}</td>
                <td className="px-3 py-2.5 text-gray-500">{f.inferred_type || f.type || '—'}</td>
                <td className="px-3 py-2.5 text-center">
                  <NullBar value={f.null_pct ?? 0} />
                </td>
                <td className="px-3 py-2.5 text-center text-gray-500">{f.distinct_count ?? '—'}</td>
                <td className="px-3 py-2.5 text-center">{f.is_pii ? '🔴' : '🟢'}</td>
                <td className="px-3 py-2.5 text-center">{f.is_key ? '🔑' : '—'}</td>
                <td className="px-3 py-2.5 text-gray-400 font-mono">
                  {(f.sample_values || []).slice(0, 3).join(', ') || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function NullBar({ value }) {
  const pct = Math.round((value ?? 0) * 100)
  const color = pct === 0 ? 'bg-emerald-400' : pct < 10 ? 'bg-amber-400' : 'bg-red-400'
  return (
    <div className="flex items-center gap-1.5 justify-center">
      <div className="w-10 h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-gray-400 text-[10px] w-6">{pct}%</span>
    </div>
  )
}

// ── Lineage Tab ───────────────────────────────────────────────────────────────

function LineageTab({ datasetId }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [view, setView] = useState('table') // 'table' | 'attribute'
  const [hoveredCol, setHoveredCol] = useState(null)

  useEffect(() => {
    api.lineage(datasetId)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [datasetId])

  if (loading) return <Loading text="Loading lineage…" />
  if (error) return <Err text={error} />
  if (!data) return <Empty text="No lineage data available." />

  const hasColLineage = data.column_lineage && Object.keys(data.column_lineage).length > 0
  const hasRowStats = data.row_stats && Object.keys(data.row_stats).length > 0

  return (
    <div className="p-6 space-y-4">
      {/* Source badge */}
      <div className="flex items-center gap-3">
        <span className={`text-xs px-2 py-0.5 rounded-full border ${data.source === 'openlineage' ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-blue-50 border-blue-200 text-blue-700'}`}>
          {data.source === 'openlineage' ? '🟢 Live OpenLineage events' : '🔵 Static pipeline graph'}
        </span>
        <span className="text-xs text-gray-400">{data.nodes.length} nodes · {data.edges.length} edges</span>
      </div>

      {/* Row stats strip */}
      {hasRowStats && (
        <div className="grid grid-cols-3 gap-3">
          {['bronze', 'silver', 'gold'].map(stage => {
            const s = data.row_stats[stage]
            if (!s) return null
            return (
              <div key={stage} className="card-static p-3">
                <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-2">{stage}</p>
                <div className="space-y-1 text-xs">
                  {s.inputRows != null && <div className="flex justify-between"><span className="text-gray-400">Input</span><span className="font-medium">{s.inputRows?.toLocaleString()}</span></div>}
                  {s.outputRows != null && <div className="flex justify-between"><span className="text-gray-400">Output</span><span className="font-medium text-emerald-600">{s.outputRows?.toLocaleString()}</span></div>}
                  {s.rejectedRows > 0 && <div className="flex justify-between"><span className="text-gray-400">Rejected</span><span className="font-medium text-red-500">{s.rejectedRows?.toLocaleString()}</span></div>}
                  {s.quarantinedRows > 0 && <div className="flex justify-between"><span className="text-gray-400">Quarantined</span><span className="font-medium text-amber-500">{s.quarantinedRows?.toLocaleString()}</span></div>}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* View toggle */}
      {hasColLineage && (
        <div className="flex gap-1 p-1 bg-gray-100 rounded-lg w-fit">
          {['table', 'attribute'].map(v => (
            <button key={v} onClick={() => setView(v)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${view === v ? 'bg-white text-indigo-600 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
              {v === 'table' ? '🗄️ Table lineage' : '🔤 Attribute lineage'}
            </button>
          ))}
        </div>
      )}

      {/* Table lineage graph */}
      {view === 'table' && (
        <div className="overflow-auto rounded-xl border border-gray-100 bg-gray-50 p-4">
          <LineageGraph nodes={data.nodes} edges={data.edges} />
        </div>
      )}

      {/* Attribute lineage */}
      {view === 'attribute' && hasColLineage && (
        <div className="card-static overflow-hidden">
          <div className="bg-gray-50 border-b border-gray-100 px-4 py-2 text-[10px] text-gray-400 uppercase tracking-wider">
            Column-level lineage — hover a row to highlight the path
          </div>
          <div className="overflow-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr className="text-gray-500 uppercase tracking-wider text-[10px]">
                  <th className="px-4 py-3 text-left font-semibold">Column</th>
                  {['Landing', 'Bronze', 'Silver', 'Gold'].map(s => (
                    <th key={s} className="px-4 py-3 text-center font-semibold">{s}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.column_lineage).map(([col, stages]) => {
                  const stageMap = {}
                  stages.forEach(s => { stageMap[s.stage] = s })
                  const isHovered = hoveredCol === col
                  return (
                    <tr
                      key={col}
                      className={`border-b border-gray-50 transition-colors cursor-default ${isHovered ? 'bg-indigo-50/60' : 'hover:bg-gray-50'}`}
                      onMouseEnter={() => setHoveredCol(col)}
                      onMouseLeave={() => setHoveredCol(null)}
                    >
                      <td className="px-4 py-2.5 font-mono text-gray-800 font-medium">{col}</td>
                      {['landing', 'bronze', 'silver', 'gold'].map(stage => {
                        const s = stageMap[stage]
                        if (!s) return (
                          <td key={stage} className="px-4 py-2.5 text-center text-gray-200">—</td>
                        )
                        const ts = TRANSFORM_STYLE[s.transform] || TRANSFORM_STYLE.IDENTITY
                        return (
                          <td key={stage} className="px-4 py-2.5 text-center">
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium border"
                              style={{ background: ts.bg, borderColor: ts.border, color: ts.text }}>
                              {s.transform === 'IDENTITY' ? '→' : s.transform === 'HASH' ? '#' : s.transform === 'MASKED' ? '🔒' : '⚙'} {ts.label}
                            </span>
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Data Quality Tab ──────────────────────────────────────────────────────────

function DQTab({ datasetId, isDataset, node }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!isDataset) { setLoading(false); return }
    api.profileDataset(datasetId)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [datasetId, isDataset])

  if (!isDataset) return <NonDatasetDQView node={node} />
  if (loading) return <Loading text="Loading DQ scores…" />
  if (error) return <Err text={error} />

  const fields = data?.fields || data?.columns || []
  const dqRules = node.dq_rules || {}

  // Compute per-column DQ score from profile stats
  const scored = fields.map(f => {
    let score = 100
    const issues = []
    const nullPct = (f.null_pct ?? 0) * 100
    if (nullPct > 0) {
      score -= Math.min(40, nullPct * 2)
      issues.push(`${Math.round(nullPct)}% nulls`)
    }
    // Check against BDE-level DQ rules
    const rules = f.dq_rules || dqRules
    if (rules.not_null && nullPct > 0) {
      score -= 20
      issues.push('not_null violated')
    }
    if (rules.unique && f.cardinality_ratio != null && f.cardinality_ratio < 0.99) {
      score -= 15
      issues.push('uniqueness low')
    }
    return { ...f, dqScore: Math.max(0, Math.round(score)), issues }
  })

  const overallScore = scored.length
    ? Math.round(scored.reduce((s, f) => s + f.dqScore, 0) / scored.length)
    : null

  const scoreColor = (s) => s >= 80 ? 'text-emerald-600' : s >= 50 ? 'text-amber-500' : 'text-red-500'
  const barColor = (s) => s >= 80 ? 'bg-emerald-500' : s >= 50 ? 'bg-amber-400' : 'bg-red-400'

  return (
    <div className="p-6 space-y-5">
      {/* Overall score */}
      {overallScore !== null && (
        <div className="card-static p-5 flex items-center gap-6">
          <div className="text-center">
            <p className={`text-4xl font-bold ${scoreColor(overallScore)}`}>{overallScore}</p>
            <p className="text-[10px] text-gray-400 uppercase tracking-wider mt-1">Overall DQ Score</p>
          </div>
          <div className="flex-1">
            <div className="w-full h-3 bg-gray-100 rounded-full overflow-hidden">
              <div className={`h-full ${barColor(overallScore)} rounded-full transition-all`} style={{ width: `${overallScore}%` }} />
            </div>
            <div className="flex justify-between text-[10px] text-gray-400 mt-1">
              <span>0</span><span>50</span><span>100</span>
            </div>
          </div>
          <div className="text-right text-xs text-gray-400">
            <p>{scored.filter(f => f.dqScore >= 80).length} columns passing</p>
            <p>{scored.filter(f => f.dqScore < 80).length} columns need attention</p>
          </div>
        </div>
      )}

      {/* BDE-level rules */}
      {Object.keys(dqRules).length > 0 && (
        <div className="card-static p-4">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-3">Inherited DQ Rules</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(dqRules).map(([rule, val]) => (
              <span key={rule} className="px-3 py-1 bg-indigo-50 border border-indigo-100 text-indigo-700 rounded-lg text-xs font-medium">
                ✓ {rule}: {JSON.stringify(val)}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Per-column scores */}
      {scored.length > 0 && (
        <div className="card-static overflow-hidden">
          <div className="bg-gray-50 border-b border-gray-100 px-4 py-2 text-[10px] text-gray-400 uppercase tracking-wider">
            Per-column DQ scores
          </div>
          <table className="w-full text-xs">
            <thead className="border-b border-gray-100">
              <tr className="text-gray-500 uppercase tracking-wider text-[10px]">
                <th className="px-4 py-3 text-left font-semibold">Column</th>
                <th className="px-4 py-3 text-center font-semibold">Score</th>
                <th className="px-4 py-3 text-left font-semibold">Score bar</th>
                <th className="px-4 py-3 text-left font-semibold">Issues</th>
              </tr>
            </thead>
            <tbody>
              {scored.map((f, i) => (
                <tr key={i} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-2.5 font-mono text-gray-800 font-medium">
                    {f.name}
                    {f.is_pii && <span className="ml-1 badge-red text-[9px]">PII</span>}
                  </td>
                  <td className={`px-4 py-2.5 text-center font-bold ${scoreColor(f.dqScore)}`}>{f.dqScore}</td>
                  <td className="px-4 py-2.5">
                    <div className="w-24 h-2 bg-gray-100 rounded-full overflow-hidden">
                      <div className={`h-full ${barColor(f.dqScore)} rounded-full`} style={{ width: `${f.dqScore}%` }} />
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-gray-400">
                    {f.issues.length > 0
                      ? f.issues.map((iss, j) => <span key={j} className="mr-2 text-amber-600">⚠ {iss}</span>)
                      : <span className="text-emerald-500">✓ clean</span>
                    }
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!data && (
        <Empty text="Profiler service not available — DQ scores cannot be computed." />
      )}
    </div>
  )
}

// ── Non-dataset fallback views ───────────────────────────────────────────────

function NonDatasetSampleView({ node, type }) {
  const label = type === 'application' ? 'Business Application' : type === 'term' ? 'Business Data Element' : 'Data Domain'
  const fields = [
    node.information_type && { label: 'Information Type', value: node.information_type },
    node.domain && { label: 'Domain', value: node.domain },
    node.is_pii != null && { label: 'PII', value: node.is_pii ? 'Yes' : 'No' },
    node.synonyms?.length && { label: 'Synonyms', value: node.synonyms.join(', ') },
    node.keywords?.length && { label: 'Keywords', value: node.keywords.join(', ') },
    node.term_count > 0 && { label: 'BDE Count', value: node.term_count },
  ].filter(Boolean)

  return (
    <div className="p-6 space-y-4">
      <div className="p-4 bg-blue-50 border border-blue-100 rounded-xl text-blue-700 text-xs">
        ℹ️ {label} nodes are logical metadata — no physical sample data is available.
      </div>
      {fields.length > 0 && (
        <div className="card-static p-4">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-3">Metadata Summary</p>
          <div className="grid grid-cols-2 gap-x-8 gap-y-2">
            {fields.map(f => <Row key={f.label} label={f.label} value={f.value} />)}
          </div>
        </div>
      )}
    </div>
  )
}

function NonDatasetDQView({ node }) {
  const dqRules = node.dq_rules || {}
  const hasRules = Object.keys(dqRules).length > 0

  return (
    <div className="p-6 space-y-4">
      <div className="p-4 bg-blue-50 border border-blue-100 rounded-xl text-blue-700 text-xs">
        ℹ️ DQ scores are computed from physical dataset profiles. This node defines DQ rules that are inherited by all tables using this BDE.
      </div>
      {hasRules ? (
        <div className="card-static p-4">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-3">DQ Rules (inherited by physical tables)</p>
          <div className="space-y-1.5">
            {Object.entries(dqRules).map(([rule, val]) => (
              <div key={rule} className="flex items-center gap-2 px-3 py-2 bg-indigo-50 rounded-lg">
                <span className="text-indigo-600 font-mono text-xs font-medium">✓ {rule}</span>
                <span className="text-gray-400 text-xs">→</span>
                <span className="text-gray-600 text-xs">{JSON.stringify(val)}</span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <Empty text="No DQ rules defined for this element." />
      )}
    </div>
  )
}

// ── Shared helpers ────────────────────────────────────────────────────────────

function Loading({ text }) {
  return (
    <div className="flex items-center justify-center h-48 text-gray-400 text-sm gap-2">
      <span className="animate-spin inline-block">⏳</span> {text}
    </div>
  )
}

function Err({ text }) {
  return (
    <div className="p-6">
      <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-red-600 text-sm">❌ {text}</div>
    </div>
  )
}

function Empty({ text }) {
  return (
    <div className="flex items-center justify-center h-48 text-gray-400 text-sm">{text}</div>
  )
}
