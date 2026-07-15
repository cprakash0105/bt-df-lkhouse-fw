import React, { useState, useEffect } from 'react'
import { api } from '../api'

export default function HomePage() {
  const [tree, setTree] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selectedNode, setSelectedNode] = useState(null)
  const [viewMode, setViewMode] = useState('business')
  const [techTree, setTechTree] = useState(null)

  useEffect(() => {
    loadCatalog()
  }, [])

  const loadCatalog = () => {
    setLoading(true)
    // Primary: use /glossary/hierarchy (works without Firestore)
    // Fallback: /catalog/tree (Firestore-backed)
    api.glossaryHierarchy()
      .then(data => setTree(data.hierarchy))
      .catch(() => {
        api.catalogTree()
          .then(data => setTree(data.hierarchy))
          .catch(() => { buildFallbackTree().then(setTree) })
      })
      .finally(() => setLoading(false))

    loadTechTree().then(setTechTree)
  }

  const handleRefresh = async () => {
    setLoading(true)
    try {
      await api.catalogSync().catch(() => {})
      await loadCatalog()
    } catch (e) {
      loadCatalog()
    }
  }

  return (
    <div className="flex h-full">
      {/* Left: Hierarchy tree */}
      <div className="flex-1 p-6 overflow-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-800">Enterprise Catalog</h1>
            <p className="text-sm text-gray-500 mt-0.5">Find, understand and explore your data estate</p>
          </div>
          <div className="flex gap-3 items-center">
            <Stat label="BDEs" value="40+" color="blue" />
            <Stat label="BAs" value="14" color="purple" />
            <Stat label="Domains" value="9" color="gold" />
            <button
              onClick={handleRefresh}
              disabled={loading}
              className="px-3 py-2 text-xs bg-white border border-gray-200 rounded-lg text-gray-500 hover:text-ontika-blue hover:border-ontika-blue/30 hover:shadow-sm disabled:opacity-50 transition-all"
              title="Sync catalog from glossary"
            >
              {loading ? '⏳' : '🔄'} Refresh
            </button>
          </div>
        </div>

        {/* Quick Links */}
        <div className="grid grid-cols-3 gap-4 mb-8">
          <QuickLinkGroup title="Business Glossary" icon="📖" color="blue" links={[
            'Find Business Terms',
            'Find BDEs with DQ Rules',
            'Find PII Fields',
          ]} />
          <QuickLinkGroup title="Technical Assets" icon="💾" color="purple" links={[
            'Find Datasets in Landing',
            'Find Data Products',
            'Find Tables in CCN',
          ]} />
          <QuickLinkGroup title="Governance" icon="🛡️" color="gold" links={[
            'Show all Domains',
            'List Business Applications',
            'DQ Rules by Domain',
          ]} />
        </div>

        {/* View toggle */}
        <div className="flex gap-1 mb-5 p-1 bg-gray-100 rounded-lg w-fit">
          <button
            onClick={() => setViewMode('business')}
            className={`px-4 py-2 rounded-md text-xs font-medium transition-all ${
              viewMode === 'business'
                ? 'bg-white text-ontika-blue shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            🏢 Business Semantic
          </button>
          <button
            onClick={() => setViewMode('technical')}
            className={`px-4 py-2 rounded-md text-xs font-medium transition-all ${
              viewMode === 'technical'
                ? 'bg-white text-emerald-600 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            💾 Technical Assets
          </button>
        </div>

        {loading ? (
          <div className="text-gray-400 text-sm p-4">Loading catalog hierarchy...</div>
        ) : viewMode === 'business' ? (
          tree && tree.length > 0 ? (
            <div className="card-static p-4">
              <OrgRoot tree={tree} onSelect={setSelectedNode} />
            </div>
          ) : (
            <FallbackView onSelect={setSelectedNode} />
          )
        ) : (
          <div className="card-static p-4">
            <TechnicalTree techTree={techTree} onSelect={setSelectedNode} />
          </div>
        )}
      </div>

      {/* Right: Detail panel */}
      {selectedNode && (
        <div className="w-[340px] border-l border-gray-200 p-5 overflow-auto bg-white shadow-elevated">
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
        className="flex items-center gap-2 py-2 px-3 rounded-lg cursor-pointer hover:bg-gray-50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="text-xs text-gray-400 w-4">{expanded ? '▼' : '▶'}</span>
        <span className="text-lg">🏛️</span>
        <span className="text-sm font-semibold text-gray-800">BT Group</span>
        <span className="text-[10px] text-gray-400 ml-2">Organization</span>
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
    cfu: { icon: '🏢', color: 'text-amber-600', label: 'CFU' },
    domain: { icon: '📁', color: 'text-ontika-blue', label: 'Domain' },
    application: { icon: '⚙️', color: 'text-emerald-600', label: 'BA' },
    term: { icon: '📖', color: 'text-gray-700', label: 'BDE' },
    dataset: { icon: '📊', color: 'text-ontika-purple', label: 'Dataset' },
    column: { icon: '▸', color: 'text-gray-500', label: 'Field' },
  }[node.type] || { icon: '•', color: 'text-gray-500', label: '' }

  return (
    <div>
      <div
        className="flex items-center gap-1.5 py-1.5 px-2 rounded-lg cursor-pointer hover:bg-indigo-50/50 group transition-colors"
        style={{ paddingLeft: `${depth * 12}px` }}
      >
        {hasChildren ? (
          <button onClick={() => setExpanded(!expanded)} className="text-xs text-gray-400 w-4 hover:text-ontika-blue">
            {expanded ? '▼' : '▶'}
          </button>
        ) : (
          <span className="w-4" />
        )}

        <div className="flex items-center gap-1.5 flex-1" onClick={() => onSelect(node)}>
          <span className="text-sm">{config.icon}</span>
          <span className={`text-sm font-medium ${config.color}`}>{node.name}</span>

          {node.is_pii && <span className="badge-red text-[9px]">PII</span>}
          {node.dq_rules && Object.keys(node.dq_rules).length > 0 && (
            <span className="badge-blue text-[9px]">DQ</span>
          )}
          {node.term_count > 0 && (
            <span className="text-[10px] text-gray-400">({node.term_count})</span>
          )}
        </div>

        <span className="text-[9px] text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity">
          {config.label}
        </span>
      </div>

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
    cfu: { title: 'Customer Facing Unit', color: 'text-amber-600' },
    domain: { title: 'Data Domain', color: 'text-ontika-blue' },
    application: { title: 'Business Application', color: 'text-emerald-600' },
    term: { title: 'Business Data Element', color: 'text-gray-700' },
    dataset: { title: 'Dataset', color: 'text-ontika-purple' },
    column: { title: 'Field', color: 'text-gray-500' },
  }[node.type] || { title: 'Entity', color: 'text-gray-600' }

  return (
    <div>
      <div className="flex justify-between items-start mb-4">
        <div>
          <p className={`text-xs font-medium ${config.color}`}>{config.title}</p>
          <h3 className="text-lg font-bold text-gray-800">{node.name}</h3>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-sm p-1 hover:bg-gray-100 rounded">✕</button>
      </div>

      {node.description && (
        <p className="text-xs text-gray-500 mb-4 leading-relaxed">{node.description}</p>
      )}

      {node.type === 'dataset' && (
        <div className="space-y-2">
          {node.domain && <Field label="Domain" value={node.domain} />}
          {node.primary_key && <Field label="Primary Key" value={node.primary_key} />}
          {node.field_count > 0 && <Field label="Fields" value={node.field_count} />}
          {node.pii_fields?.length > 0 && (
            <div>
              <p className="text-[10px] text-gray-400 mb-1 uppercase tracking-wider">PII Fields</p>
              {node.pii_fields.map(f => (
                <div key={f} className="text-xs text-red-600 py-0.5">🔴 {f}</div>
              ))}
            </div>
          )}
        </div>
      )}

      {node.type === 'term' && (
        <div className="space-y-2">
          {node.data_type && <Field label="Data Type" value={node.data_type} />}
          {node.is_pii && <Field label="Classification" value="🔴 PII" />}
          {node.dq_rules && Object.keys(node.dq_rules).length > 0 && (
            <div>
              <p className="text-[10px] text-gray-400 mb-1 uppercase tracking-wider">DQ Rules</p>
              {Object.entries(node.dq_rules).map(([k, v]) => (
                <div key={k} className="text-xs text-ontika-blue bg-indigo-50 px-2 py-1 rounded-md mb-1">
                  {k}: {JSON.stringify(v)}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {node.type === 'application' && node.children && (
        <div>
          <p className="text-[10px] text-gray-400 mb-1 uppercase tracking-wider">BDEs ({node.children.filter(c => c.type === 'term').length})</p>
          {node.children.filter(c => c.type === 'term').map(t => (
            <div key={t.id} className="text-xs text-gray-600 py-0.5 flex items-center gap-1">
              <span>📖</span> {t.name}
              {t.is_pii && <span className="badge-red text-[9px]">PII</span>}
            </div>
          ))}
        </div>
      )}

      {node.type === 'domain' && (
        <div>
          <Field label="Terms" value={`${node.term_count || 0} BDEs`} />
          {node.children && node.children.length > 0 && (
            <>
              <p className="text-[10px] text-gray-400 mt-3 mb-1 uppercase tracking-wider">Business Applications</p>
              {node.children.map(a => (
                <div key={a.id} className="text-xs text-emerald-600 py-0.5">⚙️ {a.name}</div>
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
    <div className="flex justify-between text-xs py-1 border-b border-gray-50">
      <span className="text-gray-400">{label}</span>
      <span className="text-gray-700 font-medium">{value}</span>
    </div>
  )
}

function Stat({ label, value, color }) {
  const colors = {
    blue: 'border-indigo-100 bg-indigo-50/50',
    purple: 'border-purple-100 bg-purple-50/50',
    gold: 'border-amber-100 bg-amber-50/50',
  }
  const textColors = {
    blue: 'text-ontika-blue',
    purple: 'text-ontika-purple',
    gold: 'text-ontika-gold',
  }
  return (
    <div className={`px-3 py-1.5 border rounded-lg text-center ${colors[color]}`}>
      <p className={`text-sm font-bold ${textColors[color]}`}>{value}</p>
      <p className="text-[9px] text-gray-400 uppercase tracking-wider">{label}</p>
    </div>
  )
}

function QuickLinkGroup({ title, icon, color, links }) {
  const borderColors = { blue: 'hover:border-indigo-200', purple: 'hover:border-purple-200', gold: 'hover:border-amber-200' }
  return (
    <div className={`card p-4 ${borderColors[color]}`}>
      <h4 className="text-xs font-semibold text-gray-600 mb-3 flex items-center gap-1.5">
        <span>{icon}</span> {title}
      </h4>
      {links.map((link, i) => (
        <div key={i} className="text-xs text-ontika-blue py-1 cursor-pointer hover:text-ontika-purple transition-colors">
          → {link}
        </div>
      ))}
    </div>
  )
}

function FallbackView({ onSelect }) {
  return (
    <div className="card p-6 text-center">
      <p className="text-sm text-gray-500">
        Catalog tree not loaded. Use the assistant to ask:
      </p>
      <ul className="mt-3 text-xs text-gray-400 space-y-1">
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
    // Build domain→apps mapping from the enriched apps response
    const domainApps = {}
    apps.forEach(a => {
      const d = a.domain
      if (d) {
        if (!domainApps[d]) domainApps[d] = []
        domainApps[d].push(a)
      }
    })

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
        children: (domainApps[d.id] || []).map(a => ({
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

    return [{
      id: 'project',
      name: 'bt-df-lkhouse',
      type: 'project',
      children: [
        { id: 'landing', name: 'Landing Zone (GCS/JSONL)', type: 'layer', layer: 'landing', children: datasets.map(d => ({ id: d, name: d, type: 'table', children: [] })) },
        { id: 'reservoir', name: 'Reservoir (GCS/Parquet)', type: 'layer', layer: 'reservoir', children: [] },
        { id: 'ccn', name: 'CCN (Iceberg/BLMS)', type: 'layer', layer: 'ccn', children: [] },
        { id: 'dataproduct', name: 'Data Products (BigQuery)', type: 'layer', layer: 'dataproduct', children: [
          { id: 'dp_loan', name: 'loan_eligibility_360', type: 'table', children: [] },
          { id: 'dp_spend', name: 'customer_spend_360', type: 'table', children: [] },
          { id: 'dp_health', name: 'customer_health_score', type: 'table', children: [] },
          { id: 'dp_monitor', name: 'pipeline_monitor', type: 'table', children: [] },
        ]},
      ],
    }]
  } catch {
    return null
  }
}

function TechnicalTree({ techTree, onSelect }) {
  if (!techTree || techTree.length === 0) {
    return <div className="text-gray-400 text-sm">Loading technical assets...</div>
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
    project: { icon: '☁️', color: 'text-gray-800' },
    layer: { icon: '🗂️', color: layerColor(node.layer) },
    table: { icon: '📊', color: 'text-gray-600' },
  }[node.type] || { icon: '•', color: 'text-gray-500' }

  return (
    <div>
      <div
        className="flex items-center gap-1.5 py-1.5 px-2 rounded-lg cursor-pointer hover:bg-gray-50 group transition-colors"
        style={{ paddingLeft: `${depth * 14}px` }}
      >
        {hasChildren ? (
          <button onClick={() => setExpanded(!expanded)} className="text-xs text-gray-400 w-4 hover:text-ontika-blue">
            {expanded ? '▼' : '▶'}
          </button>
        ) : (
          <span className="w-4" />
        )}
        <div className="flex items-center gap-1.5 flex-1" onClick={() => onSelect(node)}>
          <span className="text-sm">{config.icon}</span>
          <span className={`text-sm font-mono ${config.color}`}>{node.name}</span>
          {node.type === 'layer' && node.children && (
            <span className="text-[9px] text-gray-400">({node.children.length})</span>
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
    case 'landing': return 'text-red-500'
    case 'reservoir': return 'text-ontika-blue'
    case 'ccn': return 'text-ontika-gold'
    case 'dataproduct': return 'text-emerald-600'
    default: return 'text-gray-500'
  }
}
