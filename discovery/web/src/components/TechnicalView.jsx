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

  if (loading) return <div className="p-6 text-gray-500">Loading technical assets...</div>

  const layers = [
    { id: 'landing', name: 'Landing Zone', format: 'JSONL', storage: 'GCS', color: 'border-red-500/30', dot: 'bg-red-500', items: datasets },
    { id: 'reservoir', name: 'Reservoir', format: 'Parquet', storage: 'GCS', color: 'border-blue-500/30', dot: 'bg-blue-500', items: datasets },
    { id: 'ccn', name: 'CCN (Curated)', format: 'Iceberg', storage: 'GCS + BLMS', color: 'border-yellow-500/30', dot: 'bg-yellow-500', items: datasets },
    { id: 'dataproduct', name: 'Data Products', format: 'Native', storage: 'BigQuery', color: 'border-green-500/30', dot: 'bg-green-500',
      items: ['loan_eligibility_360', 'customer_spend_360', 'customer_health_score', 'collections_priority', 'pipeline_monitor'] },
  ]

  return (
    <div className="p-6 max-w-5xl">
      <h2 className="text-xl font-bold text-white mb-1">Technical Assets</h2>
      <p className="text-xs text-gray-500 mb-6">Physical data assets across lakehouse layers</p>

      {layers.map(layer => (
        <LayerSection key={layer.id} layer={layer} />
      ))}
    </div>
  )
}

function LayerSection({ layer }) {
  const [expanded, setExpanded] = useState(layer.id === 'landing' || layer.id === 'dataproduct')

  return (
    <div className={`mb-4 border ${layer.color} rounded-lg bg-[#0f1524]`}>
      <div
        className="flex items-center gap-2 p-3 cursor-pointer hover:bg-[#1a2035] rounded-t-lg"
        onClick={() => setExpanded(!expanded)}
      >
        <div className={`w-2.5 h-2.5 rounded-full ${layer.dot}`} />
        <span className="text-sm font-medium text-white flex-1">{layer.name}</span>
        <span className="text-[10px] text-gray-500">{layer.format} · {layer.storage}</span>
        <span className="text-[10px] text-gray-500">{layer.items.length} tables</span>
        <span className="text-xs text-gray-500">{expanded ? '▼' : '▶'}</span>
      </div>

      {expanded && (
        <div className="px-3 pb-3 grid grid-cols-3 gap-1.5">
          {layer.items.map((item, i) => (
            <div key={i} className="px-2 py-1.5 bg-[#0a0e1a] border border-[#1e2a4a] rounded text-xs text-gray-300 font-mono hover:border-blue-500/30 cursor-pointer">
              {typeof item === 'string' ? item : item.name || item}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
