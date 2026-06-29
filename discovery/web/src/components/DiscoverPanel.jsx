import React, { useState } from 'react'
import { api } from '../api'

export default function DiscoverPanel({ onResult, onSwitchTab }) {
  const [input, setInput] = useState('')
  const [mode, setMode] = useState('natural') // natural, yaml, multi
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleDiscover = async () => {
    if (!input.trim()) return
    setLoading(true)
    setError(null)

    try {
      let result
      if (mode === 'multi') {
        result = await api.discoverMulti(input)
        // For multi, take the first dataset
        if (result.datasets && result.datasets.length > 0) {
          onResult(result.datasets[0])
        }
      } else if (mode === 'yaml') {
        result = await api.discover({ yaml_content: input })
        onResult(result)
      } else {
        result = await api.discover({ text: input })
        onResult(result)
      }
      onSwitchTab('Results')
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-6 max-w-4xl">
      <h2 className="text-2xl font-bold mb-4">Discover Dataset</h2>

      {/* Mode selector */}
      <div className="flex gap-2 mb-4">
        {[
          ['natural', 'Natural Language'],
          ['yaml', 'YAML/JSON'],
          ['multi', 'Multi-Feed (Domain)'],
        ].map(([m, label]) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-3 py-1.5 rounded text-sm border ${
              mode === m ? 'bg-blue-600 text-white border-blue-600' : 'border-gray-300 hover:bg-gray-100'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Input area */}
      <textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder={
          mode === 'natural'
            ? 'e.g., I have a new CIBIL bureau feed with customer_id, pan_number, cibil_score, enquiry_date, loan_amount...'
            : mode === 'yaml'
            ? 'name: cibil_bureau_feed\nfields:\n  - name: customer_id\n    type: string\n  - name: cibil_score\n    type: integer'
            : 'discover domain Insurance:\n1. motor_policy: policy_id, customer_id, vehicle_reg, premium_amount, start_date, status\n2. motor_claims: claim_id, policy_id, claim_date, claim_amount, status'
        }
        className="w-full h-64 p-3 border border-gray-300 rounded-lg font-mono text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
      />

      {/* Actions */}
      <div className="mt-4 flex gap-3 items-center">
        <button
          onClick={handleDiscover}
          disabled={loading || !input.trim()}
          className="px-5 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? 'Discovering...' : '🔍 Run Discovery'}
        </button>

        {loading && (
          <span className="text-sm text-gray-500 animate-pulse">
            Analyzing fields against knowledge graph...
          </span>
        )}
      </div>

      {error && (
        <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* Quick examples */}
      <div className="mt-6 p-4 bg-gray-50 rounded-lg">
        <h3 className="text-sm font-medium text-gray-600 mb-2">Quick Examples</h3>
        <div className="flex flex-wrap gap-2">
          {[
            'New e-KYC feed with customer_id, aadhaar_number, kyc_status, full_name, address, consent_timestamp',
            'UPI transactions: transaction_id, payer_vpa, payee_vpa, amount, transaction_date, status, device_id',
            'Customer complaints with complaint_id, customer_id, channel, category, priority, status, csat_score',
          ].map((ex, i) => (
            <button
              key={i}
              onClick={() => { setInput(ex); setMode('natural') }}
              className="px-2 py-1 text-xs bg-white border border-gray-200 rounded hover:bg-blue-50 text-left"
            >
              {ex.slice(0, 60)}...
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
