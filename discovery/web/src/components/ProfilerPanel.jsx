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
      <h2 className="text-2xl font-bold text-gray-800 mb-1">Data Profiler</h2>
      <p className="text-sm text-gray-500 mb-5">Profile any dataset — fingerprinting, PII detection, composite confidence scoring</p>

      {/* Input */}
      <div className="flex gap-3 mb-5">
        <input
          value={datasetName}
          onChange={(e) => setDatasetName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleProfile()}
          placeholder="Dataset name (e.g., customer_complaints)"
          className="flex-1 px-4 py-2.5 bg-white border border-gray-200 rounded-xl text-sm text-gray-700 placeholder-gray-400 focus:ring-2 focus:ring-ontika-blue/20 focus:border-ontika-blue/40 outline-none"
        />
        <button
          onClick={handleProfile}
          disabled={loading || !datasetName.trim()}
          className="px-5 py-2.5 bg-gradient-to-r from-ontika-blue to-ontika-purple text-white rounded-xl text-sm font-medium hover:shadow-md hover:-translate-y-0.5 transition-all disabled:opacity-40"
        >
          {loading ? '⏳ Profiling...' : '📊 Run Profile'}
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-xl text-red-600 text-sm">{error}</div>
      )}

      {/* Results */}
      {profileResult && (
        <div>
          <div className="card-static p-4 mb-5 flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-gray-800">{profileResult.dataset_name}</p>
              <p className="text-xs text-gray-400 font-mono">{profileResult.source_path}</p>
            </div>
            <div className="text-right">
              <p className="text-sm font-semibold text-gray-800">{profileResult.row_count} rows × {profileResult.column_count} cols</p>
              <p className="text-xs text-gray-400">{profileResult.duration_seconds}s</p>
            </div>
          </div>

          {/* Field table */}
          <div className="card-static overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr className="text-gray-500 uppercase tracking-wider text-[10px]">
                  <th className="px-3 py-3 text-left font-semibold">Field</th>
                  <th className="px-3 py-3 text-left font-semibold">Type</th>
                  <th className="px-3 py-3 text-center font-semibold">Null%</th>
                  <th className="px-3 py-3 text-center font-semibold">Distinct</th>
                  <th className="px-3 py-3 text-center font-semibold">PII</th>
                  <th className="px-3 py-3 text-center font-semibold">Key</th>
                  <th className="px-3 py-3 text-center font-semibold">Ref</th>
                  <th className="px-3 py-3 text-left font-semibold">Fingerprint</th>
                  <th className="px-3 py-3 text-center font-semibold">Composite</th>
                </tr>
              </thead>
              <tbody>
                {profileResult.fields.map((f, i) => (
                  <tr key={i} className="border-b border-gray-50 hover:bg-indigo-50/30 transition-colors">
                    <td className="px-3 py-2.5 font-mono text-gray-800 font-medium">{f.name}</td>
                    <td className="px-3 py-2.5 text-gray-500">{f.inferred_type}</td>
                    <td className="px-3 py-2.5 text-center text-gray-500">{Math.round(f.null_pct * 100)}%</td>
                    <td className="px-3 py-2.5 text-center text-gray-500">{f.distinct_count}</td>
                    <td className="px-3 py-2.5 text-center">{f.is_pii ? '🔴' : '🟢'}</td>
                    <td className="px-3 py-2.5 text-center">{f.is_key ? '🔑' : '—'}</td>
                    <td className="px-3 py-2.5 text-center">{f.is_reference ? '📋' : '—'}</td>
                    <td className="px-3 py-2.5">
                      {f.signals?.fingerprint_set ? (
                        <span className="text-ontika-gold font-medium">{f.signals.fingerprint_set} ({Math.round(f.signals.fingerprint_score * 100)}%)</span>
                      ) : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      <CompositeBar value={f.signals?.composite_score || 0} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Signal breakdown */}
          <details className="mt-4">
            <summary className="text-xs text-gray-500 cursor-pointer hover:text-ontika-blue font-medium">Show signal breakdown per field</summary>
            <div className="mt-3 space-y-1.5">
              {profileResult.fields.filter(f => f.signals?.composite_score > 0).map((f, i) => (
                <div key={i} className="flex items-center gap-2 text-[10px] text-gray-500 p-2 bg-gray-50 rounded-lg">
                  <span className="font-mono text-gray-700 w-32 font-medium">{f.name}</span>
                  <SignalBar label="KW" value={f.signals.keyword_score} color="bg-ontika-blue" />
                  <SignalBar label="PT" value={f.signals.pattern_score} color="bg-ontika-purple" />
                  <SignalBar label="FP" value={f.signals.fingerprint_score} color="bg-ontika-gold" />
                  <SignalBar label="ST" value={f.signals.stat_score} color="bg-emerald-500" />
                  <span className="text-gray-800 font-semibold">{Math.round(f.signals.composite_score * 100)}%</span>
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
  const color = pct >= 60 ? 'bg-emerald-500' : pct >= 30 ? 'bg-ontika-gold' : pct > 0 ? 'bg-red-400' : 'bg-gray-200'
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-12 h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-gray-500 text-[10px]">{pct}%</span>
    </div>
  )
}

function SignalBar({ label, value, color }) {
  const pct = Math.round(value * 100)
  return (
    <div className="flex items-center gap-0.5">
      <span className="text-gray-400 w-5">{label}</span>
      <div className="w-8 h-1.5 bg-gray-200 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
