import React, { useState } from 'react'
import { api } from '../api'

export default function ResultsPanel({ suggestion, setSuggestion }) {
  const [configYaml, setConfigYaml] = useState(null)
  const [approveResult, setApproveResult] = useState(null)
  const [correcting, setCorrecting] = useState(null) // field name being corrected
  const [loading, setLoading] = useState(false)

  if (!suggestion) {
    return (
      <div className="p-6 text-gray-500">
        No discovery results yet. Go to <strong>Discover</strong> tab to analyse a dataset.
      </div>
    )
  }

  const handleApprove = async () => {
    setLoading(true)
    try {
      const result = await api.approve()
      setApproveResult(result)
    } catch (e) {
      alert(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleGenerateConfig = async () => {
    try {
      const result = await api.generateConfig()
      setConfigYaml(result.yaml)
    } catch (e) {
      alert(e.message)
    }
  }

  const handleCorrection = async (field, action, values = null) => {
    try {
      await api.correct(field, action, values)
      // Refresh suggestion
      const updated = await api.getSuggestion()
      setSuggestion(updated)
      setCorrecting(null)
    } catch (e) {
      alert(e.message)
    }
  }

  return (
    <div className="p-6 max-w-6xl">
      {/* Header */}
      <div className="flex justify-between items-start mb-6">
        <div>
          <h2 className="text-2xl font-bold">{suggestion.asset_name}</h2>
          <div className="flex gap-4 mt-1 text-sm text-gray-600">
            <span>📁 {suggestion.data_domain || 'Unknown'}</span>
            <span>🏢 {suggestion.business_application || 'Unknown'} ({Math.round(suggestion.app_confidence * 100)}%)</span>
            <span>🔑 PK: <code className="bg-gray-100 px-1 rounded">{suggestion.primary_key}</code></span>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={handleGenerateConfig} className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-100">
            📄 Config
          </button>
          <button onClick={handleApprove} disabled={loading}
            className="px-4 py-1.5 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50">
            {loading ? 'Processing...' : '✅ Approve All'}
          </button>
        </div>
      </div>

      {/* Field table */}
      <div className="overflow-x-auto border rounded-lg">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-3 py-2 text-left">Field</th>
              <th className="px-3 py-2 text-left">Type</th>
              <th className="px-3 py-2 text-left">BDE Match</th>
              <th className="px-3 py-2 text-center">Confidence</th>
              <th className="px-3 py-2 text-center">PII</th>
              <th className="px-3 py-2 text-left">Info Type</th>
              <th className="px-3 py-2 text-left">DQ Rules</th>
              <th className="px-3 py-2 text-center">Actions</th>
            </tr>
          </thead>
          <tbody>
            {suggestion.fields.map((f, i) => (
              <tr key={i} className={`border-b hover:bg-gray-50 ${f.new_term ? 'bg-yellow-50' : ''}`}>
                <td className="px-3 py-2 font-mono text-xs">
                  {f.name}
                  {f.is_key && <span className="ml-1 text-yellow-600">🔑</span>}
                </td>
                <td className="px-3 py-2 text-gray-600">{f.type}</td>
                <td className="px-3 py-2">
                  {f.linked_term_name || <span className="text-orange-500 text-xs">NEW TERM</span>}
                </td>
                <td className="px-3 py-2 text-center">
                  <ConfidenceBadge value={f.confidence} />
                </td>
                <td className="px-3 py-2 text-center">
                  {f.is_pii ? <span className="text-red-500">🔴</span> : <span className="text-green-500">🟢</span>}
                </td>
                <td className="px-3 py-2 text-xs text-gray-500">{f.information_type || '-'}</td>
                <td className="px-3 py-2 text-xs">
                  {Object.entries(f.dq_rules || {}).map(([k, v]) => (
                    <span key={k} className="inline-block bg-blue-100 text-blue-700 px-1 rounded mr-1 mb-0.5">
                      {k}
                    </span>
                  ))}
                </td>
                <td className="px-3 py-2 text-center">
                  <button
                    onClick={() => setCorrecting(correcting === f.name ? null : f.name)}
                    className="text-xs text-blue-600 hover:underline"
                  >
                    ✏️
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Correction panel */}
      {correcting && (
        <CorrectionPanel
          field={suggestion.fields.find((f) => f.name === correcting)}
          onCorrect={handleCorrection}
          onClose={() => setCorrecting(null)}
        />
      )}

      {/* Config output */}
      {configYaml && (
        <div className="mt-6">
          <h3 className="font-medium mb-2">Generated Pipeline Config</h3>
          <pre className="p-4 bg-gray-900 text-green-400 rounded-lg text-xs overflow-auto max-h-80">
            {configYaml}
          </pre>
        </div>
      )}

      {/* Approve result */}
      {approveResult && (
        <div className="mt-6 p-4 bg-green-50 border border-green-200 rounded-lg">
          <h3 className="font-medium text-green-800 mb-2">✅ Approved Successfully</h3>
          <ul className="text-sm text-green-700 space-y-1">
            {approveResult.new_terms_created?.length > 0 && (
              <li>New BDEs: {approveResult.new_terms_created.join(', ')}</li>
            )}
            {approveResult.ba_linked && <li>Linked to: {approveResult.ba_linked}</li>}
            {approveResult.config_gcs_path && <li>Config: {approveResult.config_gcs_path}</li>}
            {approveResult.contract_path && <li>Contract: {approveResult.contract_path}</li>}
          </ul>
          {approveResult.errors?.length > 0 && (
            <div className="mt-2 text-sm text-orange-600">
              Warnings: {approveResult.errors.join('; ')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ConfidenceBadge({ value }) {
  const pct = Math.round(value * 100)
  const color = pct >= 80 ? 'bg-green-100 text-green-700' :
                pct >= 50 ? 'bg-yellow-100 text-yellow-700' :
                'bg-red-100 text-red-700'
  return <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${color}`}>{pct}%</span>
}

function CorrectionPanel({ field, onCorrect, onClose }) {
  const [values, setValues] = useState('')

  if (!field) return null

  return (
    <div className="mt-4 p-4 border border-blue-200 bg-blue-50 rounded-lg">
      <div className="flex justify-between items-center mb-3">
        <h4 className="font-medium">Correct: <code>{field.name}</code></h4>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
      </div>
      <div className="flex flex-wrap gap-2">
        {field.is_pii ? (
          <button onClick={() => onCorrect(field.name, 'remove_pii')}
            className="px-2 py-1 text-xs bg-white border rounded hover:bg-red-50">
            Not PII
          </button>
        ) : (
          <button onClick={() => onCorrect(field.name, 'add_pii')}
            className="px-2 py-1 text-xs bg-white border rounded hover:bg-red-50">
            Mark as PII
          </button>
        )}
        <button onClick={() => onCorrect(field.name, 'remove_not_null')}
          className="px-2 py-1 text-xs bg-white border rounded hover:bg-yellow-50">
          Remove not_null
        </button>
        <button onClick={() => onCorrect(field.name, 'remove_unique')}
          className="px-2 py-1 text-xs bg-white border rounded hover:bg-yellow-50">
          Remove unique
        </button>
        <button onClick={() => onCorrect(field.name, 'add_unique')}
          className="px-2 py-1 text-xs bg-white border rounded hover:bg-green-50">
          Add unique
        </button>
      </div>
      <div className="mt-3 flex gap-2">
        <input
          value={values}
          onChange={(e) => setValues(e.target.value)}
          placeholder="Override accepted_values: val1, val2, val3"
          className="flex-1 px-2 py-1 text-xs border rounded"
        />
        <button
          onClick={() => {
            if (values.trim()) {
              onCorrect(field.name, 'set_accepted_values', values.split(',').map((v) => v.trim()))
              setValues('')
            }
          }}
          className="px-2 py-1 text-xs bg-blue-600 text-white rounded"
        >
          Set Values
        </button>
      </div>
    </div>
  )
}
