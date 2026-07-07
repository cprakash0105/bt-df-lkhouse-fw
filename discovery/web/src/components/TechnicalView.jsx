import React, { useState, useEffect } from 'react'
import { api } from '../api'

export default function TechnicalView() {
  const [datasets, setDatasets] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.listLanding()
      .then(r => setDatasets(r.datasets || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-6 text-gray-400">Loading technical assets...</div>

  const layers = [
    { id: 'landing', name: 'Landing Zone', format: 'JSONL', storage: 'GCS', color: 'border-l-red-400', bg: 'bg-red-50/30', dot: 'bg-red-400', items: datasets },
    { id: 'reservoir', name: 'Reservoir', format: 'Parquet', storage: 'GCS', color: 'border-l-indigo-400', bg: 'bg-indigo-50/30', dot: 'bg-indigo-400', items: datasets },
    { id: 'ccn', name: 'CCN (Curated)', format: 'Iceberg', storage: 'GCS + BLMS', color: 'border-l-amber-400', bg: 'bg-amber-50/30', dot: 'bg-amber-400', items: datasets },
    { id: 'dataproduct', name: 'Data Products', format: 'Native', storage: 'BigQuery', color: 'border-l-emerald-400', bg: 'bg-emerald-50/30', dot: 'bg-emerald-400',
      items: ['loan_eligibility_360', 'customer_spend_360', 'customer_health_score', 'collections_priority', 'pipeline_monitor'] },
  ]

  return (
    <div className="p-6 max-w-5xl">
      <h2 className="text-2xl font-bold text-gray-800 mb-1">Technical Assets</h2>
      <p className="text-sm text-gray-500 mb-6">Physical data assets across lakehouse layers</p>

      {layers.map(layer => (
        <LayerSection key={layer.id} layer={layer} />
      ))}
    </div>
  )
}

function LayerSection({ layer }) {
  const [expanded, setExpanded] = useState(layer.id === 'landing' || layer.id === 'dataproduct')

  return (
    <div className={`mb-4 card-static border-l-4 ${layer.color} overflow-hidden`}>
      <div
        className={`flex items-center gap-3 p-4 cursor-pointer hover:bg-gray-50 transition-colors`}
        onClick={() => setExpanded(!expanded)}
      >
        <div className={`w-3 h-3 rounded-full ${layer.dot}`} />
        <span className="text-sm font-semibold text-gray-800 flex-1">{layer.name}</span>
        <span className="text-[11px] text-gray-400">{layer.format} · {layer.storage}</span>
        <span className="badge-blue text-[10px]">{layer.items.length} tables</span>
        <span className="text-xs text-gray-400">{expanded ? '▼' : '▶'}</span>
      </div>

      {expanded && (
        <div className={`px-4 pb-4 grid grid-cols-3 gap-2 ${layer.bg}`}>
          {layer.items.map((item, i) => (
            <div key={i} className="px-3 py-2 bg-white border border-gray-100 rounded-lg text-xs text-gray-700 font-mono hover:border-ontika-blue/30 hover:shadow-sm cursor-pointer transition-all">
              {typeof item === 'string' ? item : item.name || item}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
