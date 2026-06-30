import React, { useState } from 'react'
import { api } from '../api'

export default function ProfilerPanel({ profileResult, setProfileResult }) {
  const [datasetName, setDatasetName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleProfile = async () => {
    if (!datasetName.trim()) return
    setLoading(true)
    setError(null)
    try {
      const result = await api.profileDataset(datasetName.trim().replace(/\s+/g, '_'))
      setProfileResult(result)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-6 max-w-5xl">
      <h2 className="text-xl font-bold text-white mb-1">Data Profiler</h2>
      <p className="text-xs text-gray-500 mb-4">Profile any dataset from the landing zone — fingerprinting, PII detection, composite confidence scoring.</p>

      {/* Input */}
      <div className="flex gap-2 mb-4">
        <input
          value={datasetName}
          onChange={(e) => setDatasetName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleProfile()}
          placeholder="Dataset name (e.g., customer_complaints)"
          className="flex-1 px-3 py-2 bg-[#1a2035] border border-[#2a3a5a] rounded text-sm text-white placeholder-gray-500"
        />
        <button
          onClick={handleProfile}
          disabled={loading || !datasetName.trim()}
          className="px-4 py-2 bg-gradient-to-r from-red-600 to-blue-600 text-white rounded text-sm font-medium hover:opacity-90 disabled:opacity-50"
        >
          {loading ? 'Profiling...' : '📊 Run Profile'}
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-900/20 border border-red-700/30 rounded text-red-300 text-sm">{error}</div>
      )}

      {/* Results */}
      {profileResult && (
        <div>
          <div className="flex items-center gap-4 mb-4 p-3 bg-[#0f1524] border border-[#1e2a4a] rounded">
            <div>
              <p className="text-sm font-medium text-white">{profileResult.dataset_name}</p>
              <p className="text-xs text-gray-500">{profileResult.source_path}</p>
            </div>
            <div className="text-right ml-auto">
              <p className="text-sm text-white">{profileResult.row_count} rows × {profileResult.column_count} cols</p>
              <p className="text-xs text-gray-500">{profileResult.duration_seconds}s</p>
            </div>
          </div>

          {/* Field table */}
          <div className="overflow-x-auto border border-[#1e2a4a] rounded-lg">
            <table className="w-full text-xs">
              <thead className="bg-[#0f1524] border-b border-[#1e2a4a]">
                <tr className="text-gray-400">
                  <th className="px-2 py-2 text-left">Field</th>
                  <th className="px-2 py-2 text-left">Type</th>
                  <th className="px-2 py-2 text-center">Null%</th>
                  <th className="px-2 py-2 text-center">Distinct</th>
                  <th className="px-2 py-2 text-center">PII</th>
                  <th className="px-2 py-2 text-center">Key</th>
                  <th className="px-2 py-2 text-center">Ref</th>
                  <th className="px-2 py-2 text-left">Fingerprint</th>
                  <th className="px-2 py-2 text-center">Composite</th>
                </tr>
              </thead>
              <tbody>
                {profileResult.fields.map((f, i) => (
                  <tr key={i} className="border-b border-[#1e2a4a] hover:bg-[#1a2035]">
                    <td className="px-2 py-1.5 font-mono text-gray-200">{f.name}</td>
                    <td className="px-2 py-1.5 text-gray-400">{f.inferred_type}</td>
                    <td className="px-2 py-1.5 text-center text-gray-400">{Math.round(f.null_pct * 100)}%</td>
                    <td className="px-2 py-1.5 text-center text-gray-400">{f.distinct_count}</td>
                    <td className="px-2 py-1.5 text-center">{f.is_pii ? '🔴' : '🟢'}</td>
                    <td className="px-2 py-1.5 text-center">{f.is_key ? '🔑' : '—'}</td>
                    <td className="px-2 py-1.5 text-center">{f.is_reference ? '📋' : '—'}</td>
                    <td className="px-2 py-1.5">
                      {f.signals?.fingerprint_set ? (
                        <span className="text-yellow-300">{f.signals.fingerprint_set} ({Math.round(f.signals.fingerprint_score * 100)}%)</span>
                      ) : '—'}
                    </td>
                    <td className="px-2 py-1.5 text-center">
                      <CompositeBar value={f.signals?.composite_score || 0} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Signal breakdown */}
          <details className="mt-4">
            <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-200">Signal breakdown per field</summary>
            <div className="mt-2 space-y-1">
              {profileResult.fields.filter(f => f.signals?.composite_score > 0).map((f, i) => (
                <div key={i} className="flex items-center gap-2 text-[10px] text-gray-400 p-1 bg-[#0f1524] rounded">
                  <span className="font-mono text-gray-300 w-32">{f.name}</span>
                  <SignalBar label="KW" value={f.signals.keyword_score} color="bg-blue-500" />
                  <SignalBar label="PT" value={f.signals.pattern_score} color="bg-purple-500" />
                  <SignalBar label="FP" value={f.signals.fingerprint_score} color="bg-yellow-500" />
                  <SignalBar label="ST" value={f.signals.stat_score} color="bg-green-500" />
                  <span className="text-white font-medium">{Math.round(f.signals.composite_score * 100)}%</span>
                </div>
              ))}
            </div>
          </details>
        </div>
      )}
    </div>
  )
}

function CompositeBar({ value }) {
  const pct = Math.round(value * 100)
  const color = pct >= 60 ? 'bg-green-500' : pct >= 30 ? 'bg-yellow-500' : pct > 0 ? 'bg-red-500' : 'bg-gray-700'
  return (
    <div className="flex items-center gap-1">
      <div className="w-12 h-2 bg-[#1a2035] rounded overflow-hidden">
        <div className={`h-full ${color} rounded`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-gray-400">{pct}%</span>
    </div>
  )
}

function SignalBar({ label, value, color }) {
  const pct = Math.round(value * 100)
  return (
    <div className="flex items-center gap-0.5">
      <span className="text-gray-600">{label}</span>
      <div className="w-8 h-1.5 bg-[#1a2035] rounded overflow-hidden">
        <div className={`h-full ${color} rounded`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
