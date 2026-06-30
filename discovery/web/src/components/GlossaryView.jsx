import React, { useState, useEffect } from 'react'
import { api } from '../api'

export default function GlossaryView() {
  const [glossary, setGlossary] = useState(null)
  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.glossary().then(setGlossary).catch(() => {}).finally(() => setLoading(false))
  }, [])

  const handleSearch = async () => {
    if (!search.trim()) { setSearchResults(null); return }
    const results = await api.searchGlossary(search)
    setSearchResults(results)
  }

  if (loading) return <div className="p-6 text-gray-500">Loading glossary...</div>

  return (
    <div className="flex h-full">
      {/* Left: terms list */}
      <div className="flex-1 p-6 overflow-auto">
        <h2 className="text-xl font-bold text-white mb-1">Business Glossary</h2>
        <p className="text-xs text-gray-500 mb-4">Business Data Elements — define once, apply everywhere</p>

        {/* Search */}
        <div className="flex gap-2 mb-4">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="Search terms..."
            className="flex-1 px-3 py-1.5 bg-[#1a2035] border border-[#2a3a5a] rounded text-sm text-white placeholder-gray-500"
          />
          <button onClick={handleSearch} className="px-3 py-1.5 bg-blue-600/20 border border-blue-500/30 rounded text-xs text-blue-300">
            Search
          </button>
        </div>

        {/* Search results */}
        {searchResults && (
          <div className="mb-4 p-3 bg-blue-900/10 border border-blue-500/20 rounded">
            <p className="text-xs text-gray-400 mb-2">{searchResults.length} results for "{search}"</p>
            {searchResults.map((r, i) => (
              <div key={i} className="text-xs text-gray-300 py-1 cursor-pointer hover:text-white" onClick={() => setSelected(r)}>
                📖 <span className="text-blue-300">{r.name}</span>
                <span className="text-gray-600 ml-2">[{r.domain}]</span>
                {r.is_pii && <span className="text-red-400 ml-1">PII</span>}
              </div>
            ))}
          </div>
        )}

        {/* Terms by domain */}
        {glossary && Object.entries(glossary).map(([domain, terms]) => (
          <div key={domain} className="mb-5">
            <h3 className="text-sm font-medium text-blue-300 border-b border-[#1e2a4a] pb-1 mb-2">
              📁 {domain} <span className="text-gray-500 text-xs">({terms.length})</span>
            </h3>
            <div className="grid grid-cols-2 gap-1">
              {terms.map(t => (
                <div
                  key={t.id}
                  className="px-2 py-1.5 rounded hover:bg-[#1a2035] cursor-pointer flex items-center gap-1.5"
                  onClick={() => setSelected(t)}
                >
                  <span className="text-xs">📖</span>
                  <span className="text-xs text-gray-300">{t.name}</span>
                  {t.is_pii && <span className="text-[9px] text-red-400">🔴</span>}
                  {t.dq_rules && Object.keys(t.dq_rules).length > 0 && <span className="text-[9px] text-blue-400">DQ</span>}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Right: detail panel */}
      {selected && (
        <div className="w-[300px] border-l border-[#1e2a4a] p-4 overflow-auto bg-[#0f1524]">
          <div className="flex justify-between items-start mb-3">
            <h3 className="text-sm font-bold text-white">{selected.name}</h3>
            <button onClick={() => setSelected(null)} className="text-gray-500 hover:text-white text-xs">✕</button>
          </div>
          <div className="space-y-2 text-xs">
            <div className="flex justify-between"><span className="text-gray-500">Domain</span><span className="text-gray-300">{selected.domain}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Type</span><span className="text-gray-300">{selected.information_type || '—'}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">PII</span><span className={selected.is_pii ? 'text-red-400' : 'text-green-400'}>{selected.is_pii ? 'Yes 🔴' : 'No 🟢'}</span></div>
            {selected.synonyms && (
              <div><span className="text-gray-500">Synonyms:</span> <span className="text-gray-400">{selected.synonyms.join(', ')}</span></div>
            )}
            {selected.dq_rules && Object.keys(selected.dq_rules).length > 0 && (
              <div>
                <p className="text-gray-500 mb-1">DQ Rules (inherited):</p>
                {Object.entries(selected.dq_rules).map(([k, v]) => (
                  <div key={k} className="bg-blue-900/20 px-2 py-0.5 rounded text-blue-300 mb-0.5">{k}: {JSON.stringify(v)}</div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
