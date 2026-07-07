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

  if (loading) return <div className="p-6 text-gray-400">Loading data products...</div>

  return (
    <div className="p-6 max-w-4xl">
      <h2 className="text-2xl font-bold text-gray-800 mb-1">Data Products</h2>
      <p className="text-sm text-gray-500 mb-6">Onboarded datasets available as BigQuery data products</p>

      <div className="grid grid-cols-2 gap-4">
        {['loan_eligibility_360', 'customer_spend_360', 'customer_health_score', 'collections_priority', 'fraud_risk_indicators'].map(dp => (
          <div key={dp} className="card p-4 group cursor-pointer">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-emerald-50 to-emerald-100 flex items-center justify-center group-hover:from-emerald-100 group-hover:to-emerald-200 transition-colors">
                <span className="text-emerald-600 text-lg">📦</span>
              </div>
              <div>
                <span className="text-sm font-semibold text-gray-800">{dp}</span>
                <p className="text-[11px] text-gray-400 font-mono">lakehouse_dataproduct.{dp}</p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Source datasets */}
      <h3 className="text-sm font-semibold text-gray-600 mt-10 mb-3">Source Datasets (Landing Zone)</h3>
      <div className="grid grid-cols-3 gap-3">
        {datasets?.map(ds => (
          <div key={ds} className="card p-3 text-xs text-gray-600 font-medium hover:text-ontika-blue cursor-pointer">
            📁 {ds}
          </div>
        ))}
      </div>
    </div>
  )
}
