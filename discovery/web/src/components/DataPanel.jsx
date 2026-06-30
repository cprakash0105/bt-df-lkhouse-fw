import React from 'react'

export default function DataPanel({ suggestion, landingDatasets }) {
  if (!suggestion && !landingDatasets) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        <div className="text-center">
          <p className="text-4xl mb-4">🔍</p>
          <p className="text-lg">Semantic Discovery</p>
          <p className="text-sm mt-2">Start by telling me what to onboard in the chat →</p>
          <p className="text-xs mt-4 text-gray-600">
            Try: "What's available?" or "Onboard customer complaints"
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="p-4 h-full overflow-auto">
      {/* Landing datasets list */}
      {landingDatasets && !suggestion && (
        <div className="mb-6">
          <h2 className="text-lg font-bold text-white mb-3">Available in Landing ({landingDatasets.length})</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {landingDatasets.map((ds) => (
              <div key={ds} className="p-2 bg-gray-800 border border-gray-700 rounded text-sm text-gray-300">
                📁 {ds}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Discovery results */}
      {suggestion && (
        <>
          {/* Header */}
          <div className="mb-4">
            <h2 className="text-xl font-bold text-white">{suggestion.asset_name}</h2>
            <div className="flex gap-4 mt-1 text-sm text-gray-400">
              <span>📁 {suggestion.data_domain || '?'}</span>
              <span>🏢 {suggestion.business_application || '?'} ({Math.round(suggestion.app_confidence * 100)}%)</span>
              <span>🔑 {suggestion.primary_key}</span>
              <span>📊 {suggestion.fields.length} fields</span>
            </div>
          </div>

          {/* Field table */}
          <div className="overflow-x-auto border border-gray-700 rounded-lg">
            <table className="w-full text-sm">
              <thead className="bg-gray-800 border-b border-gray-700">
                <tr className="text-gray-400">
                  <th className="px-3 py-2 text-left">Field</th>
                  <th className="px-3 py-2 text-left">Type</th>
                  <th className="px-3 py-2 text-left">BDE Match</th>
                  <th className="px-3 py-2 text-center">Confidence</th>
                  <th className="px-3 py-2 text-center">PII</th>
                  <th className="px-3 py-2 text-left">Info Type</th>
                  <th className="px-3 py-2 text-left">DQ Rules</th>
                </tr>
              </thead>
              <tbody>
                {suggestion.fields.map((f, i) => (
                  <tr key={i} className={`border-b border-gray-700 hover:bg-gray-800/50 ${f.new_term ? 'bg-yellow-900/20' : ''}`}>
                    <td className="px-3 py-2 font-mono text-xs text-gray-200">
                      {f.name}
                      {f.is_key && <span className="ml-1 text-yellow-500">🔑</span>}
                    </td>
                    <td className="px-3 py-2 text-gray-400">{f.type}</td>
                    <td className="px-3 py-2 text-gray-300">
                      {f.linked_term_name || <span className="text-orange-400 text-xs">NEW TERM</span>}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <ConfidenceBadge value={f.confidence} />
                    </td>
                    <td className="px-3 py-2 text-center">
                      {f.is_pii ? <span className="text-red-400">🔴</span> : <span className="text-green-400">🟢</span>}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500">{f.information_type || '-'}</td>
                    <td className="px-3 py-2 text-xs">
                      {Object.entries(f.dq_rules || {}).map(([k, v]) => (
                        <span key={k} className="inline-block bg-blue-900/50 text-blue-300 px-1.5 py-0.5 rounded mr-1 mb-0.5 text-xs">
                          {k}
                        </span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Reasoning / Signals (collapsed by default) */}
          <details className="mt-4">
            <summary className="text-sm text-gray-400 cursor-pointer hover:text-gray-200">
              Show signal breakdown & reasoning
            </summary>
            <div className="mt-2 space-y-2">
              {suggestion.fields.filter(f => f.reasoning && f.reasoning.length > 0).map((f, i) => (
                <div key={i} className="p-2 bg-gray-800 rounded border border-gray-700">
                  <span className="text-xs font-mono text-blue-300">{f.name}</span>
                  <div className="mt-1 text-xs text-gray-400 space-y-0.5">
                    {f.reasoning.map((r, j) => (
                      <div key={j} className={r.startsWith('PROFILE') ? 'text-purple-300' : ''}>
                        {r}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </details>

          {/* New term proposals */}
          {suggestion.new_term_proposals?.length > 0 && (
            <div className="mt-4 p-3 bg-yellow-900/20 border border-yellow-700/50 rounded-lg">
              <h4 className="text-sm font-medium text-yellow-300 mb-2">
                🆕 New Terms to Create ({suggestion.new_term_proposals.length})
              </h4>
              <div className="flex flex-wrap gap-2">
                {suggestion.new_term_proposals.map((p, i) => (
                  <span key={i} className="px-2 py-1 text-xs bg-yellow-900/50 text-yellow-200 rounded border border-yellow-700/50">
                    {p.suggested_term_name}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* FK candidates */}
          {suggestion.fk_candidates?.length > 0 && (
            <div className="mt-4 p-3 bg-gray-800 rounded-lg border border-gray-700">
              <h4 className="text-sm font-medium text-gray-300 mb-2">🔗 Foreign Key Candidates</h4>
              {suggestion.fk_candidates.map((fk, i) => (
                <div key={i} className="text-xs text-gray-400">
                  {fk.field} → {fk.references} ({Math.round(fk.confidence * 100)}%)
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function ConfidenceBadge({ value }) {
  const pct = Math.round(value * 100)
  const color = pct >= 80 ? 'bg-green-900/50 text-green-300 border-green-700' :
                pct >= 50 ? 'bg-yellow-900/50 text-yellow-300 border-yellow-700' :
                pct > 0 ? 'bg-red-900/50 text-red-300 border-red-700' :
                'bg-gray-800 text-gray-500 border-gray-700'
  return <span className={`px-1.5 py-0.5 rounded text-xs font-medium border ${color}`}>{pct}%</span>
}
