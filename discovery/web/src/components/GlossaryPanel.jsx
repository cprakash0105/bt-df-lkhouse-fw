import React, { useState, useEffect } from 'react'
import { api } from '../api'

export default function GlossaryPanel() {
  const [glossary, setGlossary] = useState(null)
  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.glossary().then(setGlossary).catch(() => {}).finally(() => setLoading(false))
  }, [])

  const handleSearch = async () => {
    if (!search.trim()) { setSearchResults(null); return }
    try {
      const results = await api.searchGlossary(search)
      setSearchResults(results)
    } catch (e) {
      setSearchResults([])
    }
  }

  if (loading) return <div className="p-6 text-gray-500">Loading glossary...</div>

  return (
    <div className="p-6 max-w-5xl">
      <h2 className="text-2xl font-bold mb-4">Business Glossary</h2>

      {/* Search */}
      <div className="flex gap-2 mb-6">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="Search terms (e.g., credit, phone, customer)..."
          className="flex-1 px-3 py-2 border rounded-lg text-sm"
        />
        <button onClick={handleSearch} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm">
          Search
        </button>
      </div>

      {/* Search results */}
      {searchResults && (
        <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <h3 className="text-sm font-medium mb-2">
            Search results for "{search}" ({searchResults.length} found)
          </h3>
          {searchResults.length === 0 ? (
            <p className="text-sm text-gray-500">No matches found.</p>
          ) : (
            <div className="space-y-2">
              {searchResults.map((r, i) => (
                <div key={i} className="flex justify-between items-center p-2 bg-white rounded border">
                  <div>
                    <span className="font-medium">{r.name}</span>
                    <span className="ml-2 text-xs text-gray-500">{r.domain}</span>
                    {r.is_pii && <span className="ml-2 text-xs text-red-500">PII</span>}
                  </div>
                  <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded">
                    {Math.round(r.confidence * 100)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Glossary by domain */}
      {glossary && Object.entries(glossary).map(([domain, terms]) => (
        <div key={domain} className="mb-6">
          <h3 className="text-lg font-semibold border-b pb-1 mb-3">{domain}</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {terms.map((t) => (
              <div key={t.id} className="p-3 border rounded-lg hover:bg-gray-50">
                <div className="flex justify-between items-start">
                  <div>
                    <span className="font-medium text-sm">{t.name}</span>
                    {t.is_pii && <span className="ml-1 text-xs text-red-500">🔴 PII</span>}
                  </div>
                  <span className="text-xs bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">
                    {t.information_type}
                  </span>
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  Synonyms: {t.synonyms.join(', ')}
                </div>
                {Object.keys(t.dq_rules || {}).length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {Object.entries(t.dq_rules).map(([k, v]) => (
                      <span key={k} className="text-xs bg-blue-50 text-blue-600 px-1 rounded">
                        {k}{typeof v !== 'boolean' ? `=${JSON.stringify(v)}` : ''}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
