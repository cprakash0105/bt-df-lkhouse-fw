import React, { useState, useEffect } from 'react'
import { api } from '../api'

export default function CatalogPanel() {
  const [tree, setTree] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState(null)

  useEffect(() => {
    api.catalogTree()
      .then(data => setTree(data.hierarchy))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const handleSearch = async () => {
    if (!searchQuery.trim()) { setSearchResults(null); return }
    try {
      const result = await api.catalogSearch(searchQuery)
      setSearchResults(result.results)
    } catch (e) {
      setSearchResults([])
    }
  }

  if (loading) return <div className="p-6 text-gray-500">Loading catalog...</div>
  if (error) return <div className="p-6 text-red-400">Catalog unavailable: {error}</div>

  return (
    <div className="p-6 max-w-4xl">
      <h2 className="text-xl font-bold text-white mb-1">Knowledge Catalog</h2>
      <p className="text-xs text-gray-500 mb-4">Interactive hierarchy: CFU → Domain → Business Application → BDE</p>

      {/* Search */}
      <div className="flex gap-2 mb-4">
        <input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="Search catalog..."
          className="flex-1 px-3 py-1.5 bg-[#1a2035] border border-[#2a3a5a] rounded text-sm text-white placeholder-gray-500"
        />
        <button onClick={handleSearch} className="px-3 py-1.5 bg-blue-600/20 border border-blue-500/30 rounded text-xs text-blue-300 hover:bg-blue-600/30">
          Search
        </button>
      </div>

      {/* Search results */}
      {searchResults && (
        <div className="mb-4 p-3 bg-[#0f1524] border border-[#1e2a4a] rounded">
          <p className="text-xs text-gray-400 mb-2">{searchResults.length} results</p>
          {searchResults.map((r, i) => (
            <div key={i} className="text-xs text-gray-300 py-1 border-b border-[#1e2a4a] last:border-0">
              <span className="text-blue-300">{r.name}</span>
              <span className="text-gray-600 ml-2">[{r.collection?.split('/').pop()}]</span>
              {r.is_pii && <span className="text-red-400 ml-1">🔴PII</span>}
            </div>
          ))}
        </div>
      )}

      {/* Tree */}
      {tree && tree.length > 0 ? (
        <div className="space-y-1">
          {tree.map(node => <TreeNode key={node.id} node={node} depth={0} />)}
        </div>
      ) : (
        <div className="text-gray-500 text-sm">
          No catalog data loaded. Click "Sync" or ask the assistant to sync the catalog.
        </div>
      )}
    </div>
  )
}

function TreeNode({ node, depth }) {
  const [expanded, setExpanded] = useState(depth < 2)
  const hasChildren = node.children && node.children.length > 0
  const indent = depth * 16

  const typeIcons = {
    cfu: '🏛️',
    domain: '📁',
    application: '🏢',
    term: '📖',
    dataset: '📊',
  }

  const typeColors = {
    cfu: 'text-yellow-300',
    domain: 'text-blue-300',
    application: 'text-green-300',
    term: 'text-gray-300',
    dataset: 'text-purple-300',
  }

  return (
    <div>
      <div
        className={`flex items-center gap-1 py-1 px-2 rounded cursor-pointer hover:bg-[#1a2035] ${typeColors[node.type] || 'text-gray-300'}`}
        style={{ paddingLeft: `${indent + 8}px` }}
        onClick={() => setExpanded(!expanded)}
      >
        {/* Expand/collapse */}
        {hasChildren ? (
          <span className="text-xs text-gray-500 w-4">{expanded ? '▼' : '▶'}</span>
        ) : (
          <span className="w-4" />
        )}

        {/* Icon + name */}
        <span className="text-sm">{typeIcons[node.type] || '•'}</span>
        <span className="text-sm font-medium">{node.name}</span>

        {/* Badges */}
        {node.is_pii && <span className="text-[10px] text-red-400 ml-1">PII</span>}
        {node.dq_rules && Object.keys(node.dq_rules).length > 0 && (
          <span className="text-[10px] text-blue-400 ml-1">DQ</span>
        )}
        {node.data_type && <span className="text-[10px] text-gray-500 ml-2">{node.data_type}</span>}
        {node.field_count && <span className="text-[10px] text-gray-500 ml-2">{node.field_count} fields</span>}
        {node.term_count > 0 && <span className="text-[10px] text-gray-500 ml-2">({node.term_count} terms)</span>}
      </div>

      {/* Children */}
      {expanded && hasChildren && (
        <div>
          {node.children.map(child => <TreeNode key={child.id} node={child} depth={depth + 1} />)}
        </div>
      )}
    </div>
  )
}
