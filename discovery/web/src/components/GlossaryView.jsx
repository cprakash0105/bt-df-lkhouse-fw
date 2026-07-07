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

  if (loading) return <div className="p-6 text-gray-400">Loading glossary...</div>

  return (
    <div className="flex h-full">
      {/* Left: terms list */}
      <div className="flex-1 p-6 overflow-auto">
        <h2 className="text-2xl font-bold text-gray-800 mb-1">Business Glossary</h2>
        <p className="text-sm text-gray-500 mb-5">Business Data Elements — define once, apply everywhere</p>

        {/* Search */}
        <div className="flex gap-2 mb-5">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="Search terms..."
            className="flex-1 px-4 py-2 bg-white border border-gray-200 rounded-lg text-sm text-gray-700 placeholder-gray-400 focus:ring-2 focus:ring-ontika-blue/20 focus:border-ontika-blue/40 outline-none"
          />
          <button onClick={handleSearch} className="px-4 py-2 bg-ontika-blue/10 border border-ontika-blue/20 rounded-lg text-xs text-ontika-blue font-medium hover:bg-ontika-blue/20 transition-colors">
            Search
          </button>
        </div>

        {/* Search results */}
        {searchResults && (
          <div className="mb-5 card-static p-4 border-indigo-100">
            <p className="text-xs text-gray-500 mb-2">{searchResults.length} results for "{search}"</p>
            {searchResults.map((r, i) => (
              <div key={i} className="text-xs text-gray-600 py-1.5 cursor-pointer hover:text-ontika-blue transition-colors" onClick={() => setSelected(r)}>
                📖 <span className="font-medium">{r.name}</span>
                <span className="text-gray-400 ml-2">[{r.domain}]</span>
                {r.is_pii && <span className="badge-red ml-1 text-[9px]">PII</span>}
              </div>
            ))}
          </div>
        )}

        {/* Terms by domain */}
        {glossary && Object.entries(glossary).map(([domain, terms]) => (
          <div key={domain} className="mb-6">
            <h3 className="text-sm font-semibold text-ontika-blue border-b border-gray-100 pb-2 mb-3">
              📁 {domain} <span className="text-gray-400 text-xs font-normal">({terms.length})</span>
            </h3>
            <div className="grid grid-cols-2 gap-1.5">
              {terms.map(t => (
                <div
                  key={t.id}
                  className="px-3 py-2 rounded-lg hover:bg-indigo-50/50 cursor-pointer flex items-center gap-2 transition-colors"
                  onClick={() => setSelected(t)}
                >
                  <span className="text-xs">📖</span>
                  <span className="text-xs text-gray-700 font-medium">{t.name}</span>
                  {t.is_pii && <span className="badge-red text-[9px]">PII</span>}
                  {t.dq_rules && Object.keys(t.dq_rules).length > 0 && <span className="badge-blue text-[9px]">DQ</span>}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Right: detail panel */}
      {selected && (
        <div className="w-[320px] border-l border-gray-200 p-5 overflow-auto bg-white shadow-elevated">
          <div className="flex justify-between items-start mb-4">
            <h3 className="text-sm font-bold text-gray-800">{selected.name}</h3>
            <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-600 text-xs p-1 hover:bg-gray-100 rounded">✕</button>
          </div>
          <div className="space-y-3 text-xs">
            <div className="flex justify-between py-1 border-b border-gray-50"><span className="text-gray-400">Domain</span><span className="text-gray-700 font-medium">{selected.domain}</span></div>
            <div className="flex justify-between py-1 border-b border-gray-50"><span className="text-gray-400">Type</span><span className="text-gray-700">{selected.information_type || '—'}</span></div>
            <div className="flex justify-between py-1 border-b border-gray-50"><span className="text-gray-400">PII</span><span className={selected.is_pii ? 'text-red-600 font-medium' : 'text-emerald-600'}>{selected.is_pii ? 'Yes 🔴' : 'No 🟢'}</span></div>
            {selected.synonyms && (
              <div><span className="text-gray-400">Synonyms:</span> <span className="text-gray-600">{selected.synonyms.join(', ')}</span></div>
            )}
            {selected.dq_rules && Object.keys(selected.dq_rules).length > 0 && (
              <div>
                <p className="text-gray-400 mb-1.5 uppercase tracking-wider text-[10px]">DQ Rules (inherited)</p>
                {Object.entries(selected.dq_rules).map(([k, v]) => (
                  <div key={k} className="bg-indigo-50 px-3 py-1.5 rounded-md text-ontika-blue mb-1">{k}: {JSON.stringify(v)}</div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
