import React, { useState, useEffect } from 'react'
import { api } from '../api'

export default function HomePage() {
  const [tree, setTree] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selectedNode, setSelectedNode] = useState(null)
  const [viewMode, setViewMode] = useState('business') // business | technical
  const [techTree, setTechTree] = useState(null)

  useEffect(() => {
    // Load business hierarchy
    api.catalogTree()
      .then(data => setTree(data.hierarchy))
      .catch(() => {
        buildFallbackTree().then(setTree)
      })
      .finally(() => setLoading(false))

    // Load technical hierarchy (from landing datasets + profiles)
    loadTechTree().then(setTechTree)
  }, [])

  return (
    <div className="flex h-full">
      {/* Left: Hierarchy tree */}
      <div className="flex-1 p-6 overflow-auto">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-xl font-bold text-white">BT Group — Data Estate</h1>
            <p className="text-xs text-gray-500 mt-0.5">Knowledge Catalog · Ontika</p>
          </div>
          <div className="flex gap-2">
            <Stat label="BDEs" value="40+" />
            <Stat label="BAs" value="14" />
            <Stat label="Domains" value="9" />
          </div>
        </div>

        {/* View toggle */}
        <div className="flex gap-1 mb-4 p-0.5 bg-[#0f1524] rounded-lg border border-[#1e2a4a] w-fit">
          <button
            onClick={() => setViewMode('business')}
            className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
              viewMode === 'business'
                ? 'bg-gradient-to-r from-blue-600/30 to-blue-500/20 text-blue-300 border border-blue-500/30'
                : 'text-gray-500 hover:text-gray-300'
            }`}
          >
            🏢 Business Semantic
          </button>
          <button
            onClick={() => setViewMode('technical')}
            className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
              viewMode === 'technical'
                ? 'bg-gradient-to-r from-green-600/30 to-green-500/20 text-green-300 border border-green-500/30'
                : 'text-gray-500 hover:text-gray-300'
            }`}
          >
            💾 Technical Assets
          </button>
        </div>

        {loading ? (
          <div className="text-gray-500 text-sm">Loading catalog hierarchy...</div>
        ) : viewMode === 'business' ? (
          tree && tree.length > 0 ? (
            <div className="space-y-0.5">
              <OrgRoot tree={tree} onSelect={setSelectedNode} />
            </div>
          ) : (
            <FallbackView onSelect={setSelectedNode} />
          )
        ) : (
          <TechnicalTree techTree={techTree} onSelect={setSelectedNode} />
        )}
      </div>

      {/* Right: Detail panel */}
      {selectedNode && (
        <div className="w-[320px] border-l border-[#1e2a4a] p-4 overflow-auto bg-[#0f1524]">
          <DetailPanel node={selectedNode} onClose={() => setSelectedNode(null)} />
        </div>
      )}
    </div>
  )
}

function OrgRoot({ tree, onSelect }) {
  const [expanded, setExpanded] = useState(true)

  return (
    <div>
      <div
        className="flex items-center gap-2 py-2 px-3 rounded cursor-pointer hover:bg-[#1a2035]"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="text-xs text-gray-500 w-4">{expanded ? '▼' : '▶'}</span>
        <span className="text-lg">🏛️</span>
        <span className="text-sm font-bold text-white">BT Group</span>
        <span className="text-[10px] text-gray-500 ml-2">Organization</span>
      </div>
      {expanded && (
        <div className="ml-4">
          {tree.map(node => (
            <TreeNode key={node.id} node={node} depth={1} onSelect={onSelect} />
          ))}
        </div>
      )}
    </div>
  )
}

function TreeNode({ node, depth, onSelect }) {
  const [expanded, setExpanded] = useState(depth < 2)
  const hasChildren = node.children && node.children.length > 0

  const config = {
    cfu: { icon: '🏢', color: 'text-yellow-300', label: 'CFU' },
    domain: { icon: '📁', color: 'text-blue-300', label: 'Domain' },
    application: { icon: '⚙️', color: 'text-green-300', label: 'BA' },
    term: { icon: '📖', color: 'text-gray-200', label: 'BDE' },
    dataset: { icon: '📊', color: 'text-purple-300', label: 'Dataset' },
  }[node.type] || { icon: '•', color: 'text-gray-400', label: '' }

  return (
    <div>
      <div
        className={`flex items-center gap-1.5 py-1.5 px-2 rounded cursor-pointer hover:bg-[#1a2035] group`}
        style={{ paddingLeft: `${depth * 12}px` }}
      >
        {/* Expand toggle */}
        {hasChildren ? (
          <button onClick={() => setExpanded(!expanded)} className="text-xs text-gray-500 w-4 hover:text-white">
            {expanded ? '▼' : '▶'}
          </button>
        ) : (
          <span className="w-4" />
        )}

        {/* Icon + Name (clickable for detail) */}
        <div className="flex items-center gap-1.5 flex-1" onClick={() => onSelect(node)}>
          <span className="text-sm">{config.icon}</span>
          <span className={`text-sm font-medium ${config.color}`}>{node.name}</span>

          {/* Badges */}
          {node.is_pii && <span className="text-[9px] bg-red-900/50 text-red-300 px-1 rounded">PII</span>}
          {node.dq_rules && Object.keys(node.dq_rules).length > 0 && (
            <span className="text-[9px] bg-blue-900/50 text-blue-300 px-1 rounded">DQ</span>
          )}
          {node.term_count > 0 && (
            <span className="text-[9px] text-gray-500">({node.term_count})</span>
          )}
          {node.field_count > 0 && (
            <span className="text-[9px] text-gray-500">{node.field_count} fields</span>
          )}
        </div>

        {/* Type label (on hover) */}
        <span className="text-[9px] text-gray-600 opacity-0 group-hover:opacity-100 transition-opacity">
          {config.label}
        </span>
      </div>

      {/* Children */}
      {expanded && hasChildren && (
        <div>
          {node.children.map(child => (
            <TreeNode key={child.id} node={child} depth={depth + 1} onSelect={onSelect} />
          ))}
        </div>
      )}
    </div>
  )
}

function DetailPanel({ node, onClose }) {
  const config = {
    cfu: { title: 'Customer Facing Unit', color: 'text-yellow-300' },
    domain: { title: 'Data Domain', color: 'text-blue-300' },
    application: { title: 'Business Application', color: 'text-green-300' },
    term: { title: 'Business Data Element', color: 'text-gray-200' },
    dataset: { title: 'Dataset', color: 'text-purple-300' },
  }[node.type] || { title: 'Entity', color: 'text-gray-300' }

  return (
    <div>
      <div className="flex justify-between items-start mb-4">
        <div>
          <p className={`text-xs font-medium ${config.color}`}>{config.title}</p>
          <h3 className="text-lg font-bold text-white">{node.name}</h3>
        </div>
        <button onClick={onClose} className="text-gray-500 hover:text-white text-sm">✕</button>
      </div>

      {node.description && (
        <p className="text-xs text-gray-400 mb-3">{node.description}</p>
      )}

      {/* BDE specific */}
      {node.type === 'term' && (
        <div className="space-y-2">
          {node.data_type && (
            <Field label="Data Type" value={node.data_type} />
          )}
          {node.is_pii && <Field label="Classification" value="🔴 PII" />}
          {node.dq_rules && Object.keys(node.dq_rules).length > 0 && (
            <div>
              <p className="text-[10px] text-gray-500 mb-1">DQ Rules (inherited by all linked fields)</p>
              {Object.entries(node.dq_rules).map(([k, v]) => (
                <div key={k} className="text-xs text-blue-300 bg-blue-900/20 px-2 py-0.5 rounded mb-0.5">
                  {k}: {JSON.stringify(v)}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* BA specific */}
      {node.type === 'application' && node.children && (
        <div>
          <p className="text-[10px] text-gray-500 mb-1">BDEs used ({node.children.filter(c => c.type === 'term').length})</p>
          {node.children.filter(c => c.type === 'term').map(t => (
            <div key={t.id} className="text-xs text-gray-300 py-0.5 flex items-center gap-1">
              <span>📖</span> {t.name}
              {t.is_pii && <span className="text-red-400 text-[9px]">PII</span>}
            </div>
          ))}
          {node.children.filter(c => c.type === 'dataset').length > 0 && (
            <>
              <p className="text-[10px] text-gray-500 mt-3 mb-1">Datasets</p>
              {node.children.filter(c => c.type === 'dataset').map(d => (
                <div key={d.id} className="text-xs text-purple-300 py-0.5">
                  📊 {d.name}
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {/* Domain specific */}
      {node.type === 'domain' && (
        <div>
          <Field label="Terms" value={`${node.term_count || 0} BDEs`} />
          {node.children && node.children.length > 0 && (
            <>
              <p className="text-[10px] text-gray-500 mt-3 mb-1">Business Applications</p>
              {node.children.map(a => (
                <div key={a.id} className="text-xs text-green-300 py-0.5">
                  ⚙️ {a.name}
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function Field({ label, value }) {
  return (
    <div className="flex justify-between text-xs py-0.5">
      <span className="text-gray-500">{label}</span>
      <span className="text-gray-300">{value}</span>
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div className="px-2 py-1 bg-[#0f1524] border border-[#1e2a4a] rounded text-center">
      <p className="text-sm font-bold text-white">{value}</p>
      <p className="text-[9px] text-gray-500">{label}</p>
    </div>
  )
}

function FallbackView({ onSelect }) {
  // When Firestore isn't available, show a message
  return (
    <div className="p-4 bg-[#0f1524] border border-[#1e2a4a] rounded-lg">
      <p className="text-sm text-gray-400">
        Catalog tree not loaded. Use the assistant to ask:
      </p>
      <ul className="mt-2 text-xs text-gray-500 space-y-1">
        <li>• "Show me the domains"</li>
        <li>• "List all business applications"</li>
        <li>• "What BDEs are in the Customer domain?"</li>
      </ul>
    </div>
  )
}

async function buildFallbackTree() {
  try {
    const [glossary, apps, domains] = await Promise.all([
      api.glossary(),
      api.applications(),
      api.domains(),
    ])
    const tree = [{
      id: 'bt_group',
      name: 'BT Group',
      type: 'cfu',
      children: domains.map(d => ({
        id: d.id,
        name: d.name,
        type: 'domain',
        description: d.description,
        term_count: d.term_count,
        children: apps
          .filter(a => a.keywords?.some(k => k.includes(d.id) || d.id.includes(k)))
          .map(a => ({
            id: a.id,
            name: a.name,
            type: 'application',
            description: a.description,
            children: (glossary[d.name] || []).slice(0, 10).map(t => ({
              id: t.id,
              name: t.name,
              type: 'term',
              is_pii: t.is_pii,
              dq_rules: t.dq_rules,
              data_type: t.information_type,
            }))
          }))
      }))
    }]
    return tree
  } catch {
    return []
  }
}

async function loadTechTree() {
  try {
    const result = await api.listLanding()
    const datasets = result.datasets || []

    // Try to load profiles for each dataset
    const layers = {
      landing: [],
      ccn: [],
      dataproduct: [],
    }

    for (const ds of datasets) {
      layers.landing.push({ id: ds, name: ds, type: 'table', children: [] })
    }

    // Build technical tree
    return [
      {
        id: 'project',
        name: 'bt-df-lkhouse',
        type: 'project',
        children: [
          {
            id: 'landing',
            name: 'Landing Zone (GCS/JSONL)',
            type: 'layer',
            layer: 'landing',
            children: layers.landing,
          },
          {
            id: 'reservoir',
            name: 'Reservoir (GCS/Parquet)',
            type: 'layer',
            layer: 'reservoir',
            children: [], // populated after ingest
          },
          {
            id: 'ccn',
            name: 'CCN (Iceberg/BLMS)',
            type: 'layer',
            layer: 'ccn',
            children: [], // populated after curate
          },
          {
            id: 'dataproduct',
            name: 'Data Products (BigQuery)',
            type: 'layer',
            layer: 'dataproduct',
            children: [
              { id: 'dp_loan', name: 'loan_eligibility_360', type: 'table', children: [] },
              { id: 'dp_spend', name: 'customer_spend_360', type: 'table', children: [] },
              { id: 'dp_health', name: 'customer_health_score', type: 'table', children: [] },
              { id: 'dp_monitor', name: 'pipeline_monitor', type: 'table', children: [] },
            ],
          },
        ],
      },
    ]
  } catch {
    return null
  }
}

function TechnicalTree({ techTree, onSelect }) {
  if (!techTree || techTree.length === 0) {
    return <div className="text-gray-500 text-sm">Loading technical assets...</div>
  }

  return (
    <div className="space-y-0.5">
      {techTree.map(node => (
        <TechNode key={node.id} node={node} depth={0} onSelect={onSelect} />
      ))}
    </div>
  )
}

function TechNode({ node, depth, onSelect }) {
  const [expanded, setExpanded] = useState(depth < 2)
  const hasChildren = node.children && node.children.length > 0

  const config = {
    project: { icon: '☁️', color: 'text-white' },
    layer: { icon: '🗂️', color: layerColor(node.layer) },
    table: { icon: '📊', color: 'text-gray-300' },
    column: { icon: '│', color: 'text-gray-400' },
  }[node.type] || { icon: '•', color: 'text-gray-400' }

  return (
    <div>
      <div
        className={`flex items-center gap-1.5 py-1.5 px-2 rounded cursor-pointer hover:bg-[#1a2035] group`}
        style={{ paddingLeft: `${depth * 14}px` }}
      >
        {hasChildren ? (
          <button onClick={() => setExpanded(!expanded)} className="text-xs text-gray-500 w-4 hover:text-white">
            {expanded ? '▼' : '▶'}
          </button>
        ) : (
          <span className="w-4" />
        )}

        <div className="flex items-center gap-1.5 flex-1" onClick={() => onSelect(node)}>
          <span className="text-sm">{config.icon}</span>
          <span className={`text-sm font-mono ${config.color}`}>{node.name}</span>
          {node.type === 'layer' && node.children && (
            <span className="text-[9px] text-gray-500">({node.children.length})</span>
          )}
          {node.type === 'column' && (
            <>
              <span className="text-[9px] text-gray-600">{node.data_type}</span>
              {node.is_pii && <span className="text-[9px] text-red-400">PII</span>}
              {node.is_key && <span className="text-[9px] text-yellow-400">🔑</span>}
            </>
          )}
        </div>
      </div>

      {expanded && hasChildren && (
        <div>
          {node.children.map(child => (
            <TechNode key={child.id} node={child} depth={depth + 1} onSelect={onSelect} />
          ))}
        </div>
      )}
    </div>
  )
}

function layerColor(layer) {
  switch (layer) {
    case 'landing': return 'text-red-300'
    case 'reservoir': return 'text-blue-300'
    case 'ccn': return 'text-yellow-300'
    case 'dataproduct': return 'text-green-300'
    default: return 'text-gray-300'
  }
}
