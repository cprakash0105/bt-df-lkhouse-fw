import React, { useState } from 'react'
import { api } from '../api'

export default function ProfilePanel({ profileData, setProfileData }) {
  const [input, setInput] = useState('')
  const [datasetName, setDatasetName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleProfile = async () => {
    if (!input.trim()) return
    setLoading(true)
    setError(null)
    try {
      const result = await api.profile(input, 'csv', datasetName || null)
      setProfileData(result)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-6 max-w-6xl">
      <h2 className="text-2xl font-bold mb-4">Data Profiler</h2>
      <p className="text-sm text-gray-600 mb-4">
        Paste CSV data to profile. Detects types, PII patterns, cardinality, and suggests DQ rules.
      </p>

      <div className="flex gap-3 mb-3">
        <input
          value={datasetName}
          onChange={(e) => setDatasetName(e.target.value)}
          placeholder="Dataset name (optional)"
          className="px-3 py-1.5 border rounded text-sm w-64"
        />
        <button
          onClick={handleProfile}
          disabled={loading || !input.trim()}
          className="px-4 py-1.5 bg-purple-600 text-white rounded text-sm hover:bg-purple-700 disabled:opacity-50"
        >
          {loading ? 'Profiling...' : '📊 Profile Data'}
        </button>
      </div>

      <textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder="customer_id,pan_number,cibil_score,enquiry_date&#10;CUST001,ABCPD1234F,750,2024-01-15&#10;CUST002,XYZPQ5678R,680,2024-01-16"
        className="w-full h-48 p-3 border rounded-lg font-mono text-xs focus:ring-2 focus:ring-purple-500"
      />

      {error && (
        <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>
      )}

      {/* Profile results */}
      {profileData && (
        <div className="mt-6">
          <h3 className="font-medium mb-3">
            Profile Results — {profileData.row_count} rows × {profileData.column_count} columns
          </h3>
          <div className="overflow-x-auto border rounded-lg">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-3 py-2 text-left">Column</th>
                  <th className="px-3 py-2 text-left">Type</th>
                  <th className="px-3 py-2 text-center">Null%</th>
                  <th className="px-3 py-2 text-center">Distinct</th>
                  <th className="px-3 py-2 text-center">PII</th>
                  <th className="px-3 py-2 text-center">Key?</th>
                  <th className="px-3 py-2 text-left">Patterns</th>
                  <th className="px-3 py-2 text-left">Suggested DQ</th>
                </tr>
              </thead>
              <tbody>
                {profileData.columns.map((col, i) => (
                  <tr key={i} className="border-b hover:bg-gray-50">
                    <td className="px-3 py-2 font-mono text-xs">{col.name}</td>
                    <td className="px-3 py-2 text-gray-600">{col.type}</td>
                    <td className="px-3 py-2 text-center">{Math.round(col.null_pct * 100)}%</td>
                    <td className="px-3 py-2 text-center">{col.distinct_count}</td>
                    <td className="px-3 py-2 text-center">
                      {col.is_pii ? '🔴' : '🟢'}
                    </td>
                    <td className="px-3 py-2 text-center">
                      {col.is_key ? '🔑' : col.is_reference ? 'REF' : '-'}
                    </td>
                    <td className="px-3 py-2 text-xs">{col.patterns?.join(', ') || '-'}</td>
                    <td className="px-3 py-2 text-xs">
                      {Object.keys(col.suggested_dq || {}).map((k) => (
                        <span key={k} className="inline-block bg-purple-100 text-purple-700 px-1 rounded mr-1">
                          {k}
                        </span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Reference fields */}
          {profileData.columns.filter((c) => c.is_reference && c.distinct_values).length > 0 && (
            <div className="mt-4">
              <h4 className="text-sm font-medium mb-2">Reference Fields (low cardinality)</h4>
              <div className="flex flex-wrap gap-3">
                {profileData.columns
                  .filter((c) => c.is_reference && c.distinct_values)
                  .map((col) => (
                    <div key={col.name} className="p-2 bg-gray-50 border rounded text-xs">
                      <span className="font-medium">{col.name}:</span>{' '}
                      {col.distinct_values.join(', ')}
                    </div>
                  ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
