import React, { useState } from 'react'
import { api } from '../api'

export default function DiscoveryModal({ suggestion, setSuggestion, onClose, onApproved }) {
  const [loading, setLoading] = useState(false)
  const [approveResult, setApproveResult] = useState(null)
  const [correcting, setCorrecting] = useState(null)

  if (!suggestion) return null

  const handleApprove = async () => {
    setLoading(true)
    try {
      const result = await api.approve()
      setApproveResult(result)
      onApproved?.(suggestion.asset_name, result)
    } catch (e) {
      alert(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleCorrection = async (field, action, values = null) => {
    try {
      await api.correct(field, action, values)
      const updated = await api.getSuggestion()
      setSuggestion(updated)
      setCorrecting(null)
    } catch (e) {
      alert(e.message)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={!approveResult ? onClose : undefined} />

      {/* Modal */}
      <div className="relative z-10 w-[90vw] max-w-5xl max-h-[90vh] bg-white rounded-2xl shadow-2xl flex flex-col overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 bg-gray-50/80">
          <div>
            <h2 className="text-lg font-bold text-gray-800">{suggestion.asset_name}</h2>
            <div className="flex gap-3 mt-1 flex-wrap">
              <span className="badge-blue text-[10px]">📁 {suggestion.data_domain || '?'}</span>
              <span className="badge-purple text-[10px]">🏢 {suggestion.business_application || '?'} ({Math.round(suggestion.app_confidence * 100)}%)</span>
              <span className="badge-gold text-[10px]">🔑 {suggestion.primary_key}</span>
              <span className="badge-green text-[10px]">📊 {suggestion.fields.length} fields</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {!approveResult && (
              <button
                onClick={handleApprove}
                disabled={loading}
                className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700 disabled:opacity-50 transition-colors"
              >
                {loading ? '⏳ Processing...' : '✅ Approve All'}
              </button>
            )}
            <button
              onClick={onClose}
              className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto p-6">

          {/* Approve success banner */}
          {approveResult && (
            <div className="mb-5 p-4 bg-emerald-50 border border-emerald-200 rounded-xl">
              <p className="text-sm font-semibold text-emerald-800 mb-1">✅ Onboarded successfully</p>
              <ul className="text-xs text-emerald-700 space-y-0.5">
                {approveResult.new_terms_created?.length > 0 && (
                  <li>• New BDEs: {approveResult.new_terms_created.join(', ')}</li>
                )}
                {approveResult.ba_linked && <li>• Linked to: {approveResult.ba_linked}</li>}
                {approveResult.config_gcs_path && <li>• Config: {approveResult.config_gcs_path}</li>}
              </ul>
              {approveResult.errors?.length > 0 && (
                <p className="mt-1 text-xs text-amber-600">⚠️ {approveResult.errors.join('; ')}</p>
              )}
            </div>
          )}

          {/* Field table */}
          <div className="card-static overflow-hidden mb-4">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr className="text-gray-500 uppercase tracking-wider text-[10px]">
                  <th className="px-3 py-3 text-left font-semibold">Field</th>
                  <th className="px-3 py-3 text-left font-semibold">Type</th>
                  <th className="px-3 py-3 text-left font-semibold">BDE Match</th>
                  <th className="px-3 py-3 text-center font-semibold">Confidence</th>
                  <th className="px-3 py-3 text-center font-semibold">PII</th>
                  <th className="px-3 py-3 text-left font-semibold">Info Type</th>
                  <th className="px-3 py-3 text-left font-semibold">DQ Rules</th>
                  {!approveResult && <th className="px-3 py-3 text-center font-semibold">Edit</th>}
                </tr>
              </thead>
              <tbody>
                {suggestion.fields.map((f, i) => (
                  <tr key={i} className={`border-b border-gray-50 hover:bg-indigo-50/30 transition-colors ${f.new_term ? 'bg-amber-50/30' : ''}`}>
                    <td className="px-3 py-2.5 font-mono text-xs text-gray-800 font-medium">
                      {f.name}
                      {f.is_key && <span className="ml-1 text-ontika-gold">🔑</span>}
                    </td>
                    <td className="px-3 py-2.5 text-gray-500 text-xs">{f.type}</td>
                    <td className="px-3 py-2.5 text-gray-700 text-xs">
                      {f.linked_term_name || <span className="badge-gold text-[9px]">NEW TERM</span>}
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      <ConfidenceBadge value={f.confidence} />
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      {f.is_pii ? <span className="text-red-500">🔴</span> : <span className="text-emerald-500">🟢</span>}
                    </td>
                    <td className="px-3 py-2.5 text-xs text-gray-400">{f.information_type || '-'}</td>
                    <td className="px-3 py-2.5 text-xs">
                      {Object.entries(f.dq_rules || {}).map(([k]) => (
                        <span key={k} className="badge-blue text-[9px] mr-1 mb-0.5">{k}</span>
                      ))}
                    </td>
                    {!approveResult && (
                      <td className="px-3 py-2.5 text-center">
                        <button
                          onClick={() => setCorrecting(correcting === f.name ? null : f.name)}
                          className="text-xs text-ontika-blue hover:underline"
                        >✏️</button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Correction panel */}
          {correcting && (
            <CorrectionPanel
              field={suggestion.fields.find(f => f.name === correcting)}
              onCorrect={handleCorrection}
              onClose={() => setCorrecting(null)}
            />
          )}

          {/* New term proposals */}
          {suggestion.new_term_proposals?.length > 0 && (
            <div className="card-static p-4 border-amber-200 bg-amber-50/30 mb-4">
              <h4 className="text-xs font-semibold text-amber-700 mb-2">
                🆕 New Terms to Create ({suggestion.new_term_proposals.length})
              </h4>
              <div className="flex flex-wrap gap-2">
                {suggestion.new_term_proposals.map((p, i) => (
                  <span key={i} className="badge-gold text-[10px]">{p.suggested_term_name}</span>
                ))}
              </div>
            </div>
          )}

          {/* Reasoning */}
          <details>
            <summary className="text-xs text-gray-400 cursor-pointer hover:text-ontika-blue">
              Show signal breakdown & reasoning
            </summary>
            <div className="mt-3 space-y-2">
              {suggestion.fields.filter(f => f.reasoning?.length > 0).map((f, i) => (
                <div key={i} className="card-static p-3">
                  <span className="text-xs font-mono text-ontika-blue font-medium">{f.name}</span>
                  <div className="mt-1 text-xs text-gray-500 space-y-0.5">
                    {f.reasoning.map((r, j) => (
                      <div key={j} className={r.startsWith('PROFILE') ? 'text-ontika-purple' : ''}>{r}</div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </details>
        </div>
      </div>
    </div>
  )
}

function ConfidenceBadge({ value }) {
  const pct = Math.round(value * 100)
  const style = pct >= 80 ? 'bg-emerald-50 text-emerald-700 border-emerald-200' :
                pct >= 50 ? 'bg-amber-50 text-amber-700 border-amber-200' :
                pct > 0   ? 'bg-red-50 text-red-700 border-red-200' :
                            'bg-gray-50 text-gray-400 border-gray-200'
  return <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold border ${style}`}>{pct}%</span>
}

function CorrectionPanel({ field, onCorrect, onClose }) {
  const [values, setValues] = useState('')
  if (!field) return null
  return (
    <div className="mb-4 p-4 border border-ontika-blue/20 bg-indigo-50/40 rounded-xl">
      <div className="flex justify-between items-center mb-3">
        <h4 className="text-xs font-semibold text-gray-700">Correct: <code className="font-mono">{field.name}</code></h4>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xs">✕</button>
      </div>
      <div className="flex flex-wrap gap-2 mb-3">
        {field.is_pii
          ? <button onClick={() => onCorrect(field.name, 'remove_pii')} className="px-2 py-1 text-xs bg-white border rounded hover:bg-red-50">Not PII</button>
          : <button onClick={() => onCorrect(field.name, 'add_pii')} className="px-2 py-1 text-xs bg-white border rounded hover:bg-red-50">Mark PII</button>
        }
        <button onClick={() => onCorrect(field.name, 'remove_not_null')} className="px-2 py-1 text-xs bg-white border rounded hover:bg-amber-50">Remove not_null</button>
        <button onClick={() => onCorrect(field.name, 'remove_unique')} className="px-2 py-1 text-xs bg-white border rounded hover:bg-amber-50">Remove unique</button>
        <button onClick={() => onCorrect(field.name, 'add_unique')} className="px-2 py-1 text-xs bg-white border rounded hover:bg-emerald-50">Add unique</button>
      </div>
      <div className="flex gap-2">
        <input
          value={values}
          onChange={e => setValues(e.target.value)}
          placeholder="Override accepted_values: val1, val2, val3"
          className="flex-1 px-2 py-1 text-xs border rounded outline-none focus:ring-1 focus:ring-ontika-blue/30"
        />
        <button
          onClick={() => { if (values.trim()) { onCorrect(field.name, 'set_accepted_values', values.split(',').map(v => v.trim())); setValues('') } }}
          className="px-2 py-1 text-xs bg-ontika-blue text-white rounded"
        >Set Values</button>
      </div>
    </div>
  )
}
