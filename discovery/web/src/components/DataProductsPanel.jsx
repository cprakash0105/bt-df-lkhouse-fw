import React, { useState, useEffect } from 'react'
import { api } from '../api'

export default function DataProductsPanel() {
  const [datasets, setDatasets] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.listLanding()
      .then(r => setDatasets(r.datasets))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-6 text-gray-500">Loading data products...</div>

  return (
    <div className="p-6 max-w-4xl">
      <h2 className="text-xl font-bold text-white mb-1">Data Products</h2>
      <p className="text-xs text-gray-500 mb-6">Onboarded datasets available as BigQuery data products</p>

      <div className="grid grid-cols-2 gap-3">
        {/* Known data products */}
        {['loan_eligibility_360', 'customer_spend_360', 'customer_health_score', 'collections_priority', 'fraud_risk_indicators'].map(dp => (
          <div key={dp} className="p-3 bg-[#0f1524] border border-green-500/20 rounded-lg">
            <div className="flex items-center gap-2">
              <span className="text-green-400">📦</span>
              <span className="text-sm font-medium text-white">{dp}</span>
            </div>
            <p className="text-[10px] text-gray-500 mt-1">lakehouse_dataproduct.{dp}</p>
          </div>
        ))}
      </div>

      {/* Source datasets */}
      <h3 className="text-sm font-medium text-gray-400 mt-8 mb-3">Source Datasets (Landing Zone)</h3>
      <div className="grid grid-cols-3 gap-2">
        {datasets?.map(ds => (
          <div key={ds} className="p-2 bg-[#0f1524] border border-[#1e2a4a] rounded text-xs text-gray-300 hover:border-blue-500/30 cursor-pointer">
            📁 {ds}
          </div>
        ))}
      </div>
    </div>
  )
}
