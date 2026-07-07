import React from 'react'

export default function DataPanel({ suggestion, landingDatasets }) {
  if (!suggestion && !landingDatasets) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-indigo-50 to-purple-50 flex items-center justify-center">
            <span className="text-3xl">🔍</span>
          </div>
          <p className="text-lg font-semibold text-gray-700">Semantic Discovery</p>
          <p className="text-sm text-gray-400 mt-2">Start by telling me what to onboard in the chat →</p>
          <p className="text-xs mt-4 text-gray-400">
            Try: "What's available?" or "Onboard customer complaints"
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 h-full overflow-auto">
      {/* Landing datasets list */}
      {landingDatasets && !suggestion && (
        <div className="mb-6">
          <h2 className="text-lg font-bold text-gray-800 mb-3">Available in Landing ({landingDatasets.length})</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {landingDatasets.map((ds) => (
              <div key={ds} className="card p-3 text-sm text-gray-600 font-medium">
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
          <div className="card-static p-5 mb-5">
            <h2 className="text-xl font-bold text-gray-800">{suggestion.asset_name}</h2>
            <div className="flex gap-4 mt-2 text-sm text-gray-500 flex-wrap">
              <span className="badge-blue">📁 {suggestion.data_domain || '?'}</span>
              <span className="badge-purple">🏢 {suggestion.business_application || '?'} ({Math.round(suggestion.app_confidence * 100)}%)</span>
              <span className="badge-gold">🔑 {suggestion.primary_key}</span>
              <span className="badge-green">📊 {suggestion.fields.length} fields</span>
            </div>
          </div>

          {/* Field table */}
          <div className="card-static overflow-hidden">
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
                        <span key={k} className="badge-blue text-[9px] mr-1 mb-0.5">
                          {k}
                        </span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Reasoning */}
          <details className="mt-4">
            <summary className="text-xs text-gray-500 cursor-pointer hover:text-ontika-blue font-medium">
              Show signal breakdown & reasoning
            </summary>
            <div className="mt-3 space-y-2">
              {suggestion.fields.filter(f => f.reasoning && f.reasoning.length > 0).map((f, i) => (
                <div key={i} className="card-static p-3">
                  <span className="text-xs font-mono text-ontika-blue font-medium">{f.name}</span>
                  <div className="mt-1.5 text-xs text-gray-500 space-y-0.5">
                    {f.reasoning.map((r, j) => (
                      <div key={j} className={r.startsWith('PROFILE') ? 'text-ontika-purple' : ''}>
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
            <div className="mt-5 card-static p-4 border-amber-200 bg-amber-50/30">
              <h4 className="text-sm font-semibold text-amber-700 mb-2">
                🆕 New Terms to Create ({suggestion.new_term_proposals.length})
              </h4>
              <div className="flex flex-wrap gap-2">
                {suggestion.new_term_proposals.map((p, i) => (
                  <span key={i} className="badge-gold">
                    {p.suggested_term_name}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* FK candidates */}
          {suggestion.fk_candidates?.length > 0 && (
            <div className="mt-4 card-static p-4">
              <h4 className="text-sm font-semibold text-gray-700 mb-2">🔗 Foreign Key Candidates</h4>
              {suggestion.fk_candidates.map((fk, i) => (
                <div key={i} className="text-xs text-gray-500 py-0.5">
                  <span className="font-mono text-gray-700">{fk.field}</span> → {fk.references} ({Math.round(fk.confidence * 100)}%)
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
  const style = pct >= 80 ? 'bg-emerald-50 text-emerald-700 border-emerald-200' :
                pct >= 50 ? 'bg-amber-50 text-amber-700 border-amber-200' :
                pct > 0 ? 'bg-red-50 text-red-700 border-red-200' :
                'bg-gray-50 text-gray-400 border-gray-200'
  return <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold border ${style}`}>{pct}%</span>
}
