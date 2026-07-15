import React, { useState, useEffect } from 'react'
import { api } from '../api'

export default function GlossaryView() {
  const [glossary, setGlossary] = useState(null)
  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [domains, setDomains] = useState([])

  useEffect(() => {
    Promise.all([
      api.glossary().then(setGlossary),
      api.domains().then(setDomains),
    ]).catch(() => {}).finally(() => setLoading(false))
  }, [])

  const handleSearch = async () => {
    if (!search.trim()) { setSearchResults(null); return }
    const results = await api.searchGlossary(search)
    setSearchResults(results)
  }

  const handleCreate = async (data) => {
    try {
      await api.createBDE(data)
      setShowCreate(false)
      // Refresh glossary
      const updated = await api.glossary()
      setGlossary(updated)
    } catch (e) {
      alert(e.message)
    }
  }

  if (loading) return <div className="p-6 text-gray-400">Loading glossary...</div>

  return (
    <div className="flex h-full">
      {/* Left: terms list */}
      <div className="flex-1 p-6 overflow-auto">
        <h2 className="text-2xl font-bold text-gray-800 mb-1">Business Glossary</h2>
        <div className="flex items-center justify-between mb-5">
          <p className="text-sm text-gray-500">Business Data Elements — define once, apply everywhere</p>
          <button
            onClick={() => setShowCreate(true)}
            className="px-3 py-1.5 bg-ontika-blue text-white text-xs font-medium rounded-lg hover:bg-indigo-700 transition-colors"
          >
            + New BDE
          </button>
        </div>

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

      {/* Right: detail panel or create form */}
      {showCreate && (
        <CreateBDEPanel domains={domains} onCreate={handleCreate} onClose={() => setShowCreate(false)} />
      )}
      {!showCreate && selected && (
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

function CreateBDEPanel({ domains, onCreate, onClose }) {
  const [form, setForm] = useState({
    name: '', domain: domains[0]?.id || '', data_type: 'string',
    information_type: 'Dimension', is_pii: false, synonyms: '',
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!form.name.trim() || !form.domain) return
    onCreate({
      ...form,
      synonyms: form.synonyms ? form.synonyms.split(',').map(s => s.trim()).filter(Boolean) : null,
    })
  }

  return (
    <div className="w-[320px] border-l border-gray-200 p-5 overflow-auto bg-white shadow-elevated">
      <div className="flex justify-between items-start mb-4">
        <h3 className="text-sm font-bold text-gray-800">Create New BDE</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xs p-1 hover:bg-gray-100 rounded">✕</button>
      </div>
      <form onSubmit={handleSubmit} className="space-y-3">
        <Field label="Name" value={form.name} onChange={v => setForm({...form, name: v})} placeholder="e.g. Nomination Flag" />
        <div>
          <label className="text-[10px] text-gray-400 uppercase tracking-wider">Domain</label>
          <select value={form.domain} onChange={e => setForm({...form, domain: e.target.value})} className="w-full mt-1 px-3 py-1.5 border border-gray-200 rounded-md text-xs">
            {domains.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[10px] text-gray-400 uppercase tracking-wider">Data Type</label>
          <select value={form.data_type} onChange={e => setForm({...form, data_type: e.target.value})} className="w-full mt-1 px-3 py-1.5 border border-gray-200 rounded-md text-xs">
            {['string', 'integer', 'double', 'date', 'timestamp', 'boolean'].map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[10px] text-gray-400 uppercase tracking-wider">Information Type</label>
          <select value={form.information_type} onChange={e => setForm({...form, information_type: e.target.value})} className="w-full mt-1 px-3 py-1.5 border border-gray-200 rounded-md text-xs">
            {['Dimension', 'Measure', 'Identifier', 'Reference', 'Temporal'].map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <Field label="Synonyms (comma-separated)" value={form.synonyms} onChange={v => setForm({...form, synonyms: v})} placeholder="e.g. nom_flag, nominated" />
        <div className="flex items-center gap-2">
          <input type="checkbox" checked={form.is_pii} onChange={e => setForm({...form, is_pii: e.target.checked})} className="rounded" />
          <span className="text-xs text-gray-600">Contains PII</span>
        </div>
        <button type="submit" className="w-full py-2 bg-ontika-blue text-white text-xs font-medium rounded-lg hover:bg-indigo-700 transition-colors">
          Create BDE
        </button>
      </form>
    </div>
  )
}

function Field({ label, value, onChange, placeholder }) {
  return (
    <div>
      <label className="text-[10px] text-gray-400 uppercase tracking-wider">{label}</label>
      <input
        value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        className="w-full mt-1 px-3 py-1.5 border border-gray-200 rounded-md text-xs focus:ring-1 focus:ring-ontika-blue/30 outline-none"
      />
    </div>
  )
}
