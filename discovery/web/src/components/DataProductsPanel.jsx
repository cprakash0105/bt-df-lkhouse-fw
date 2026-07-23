import React, { useState, useEffect } from 'react'
import { api } from '../api'

export default function DataProductsPanel({ onChat }) {
  const [sources, setSources] = useState([])
  const [products, setProducts] = useState([])
  const [loading, setLoading] = useState(true)
  const [building, setBuilding] = useState(false)
  const [spec, setSpec] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([
      api.listLanding().then(r => setSources(r.datasets || [])),
    ]).catch(() => {}).finally(() => setLoading(false))
  }, [])

  const handleBuild = async () => {
    if (!spec.trim()) return
    setBuilding(true)
    setError(null)
    setResult(null)
    try {
      const r = await api.generateDataProduct(spec)
      setResult(r)
      setProducts(prev => prev.find(p => p.table_name === r.table_name)
        ? prev : [...prev, r])
    } catch (e) {
      setError(e.message)
    } finally {
      setBuilding(false)
    }
  }

  return (
    <div className="flex h-full">
      {/* Left: products + sources */}
      <div className="flex-1 p-6 overflow-auto">
        <h2 className="text-2xl font-bold text-gray-800 mb-1">Data Products</h2>
        <p className="text-sm text-gray-500 mb-6">
          Build BigQuery data products from silver layer sources
        </p>

        {/* Built this session */}
        {products.length > 0 && (
          <div className="mb-8">
            <h3 className="text-sm font-semibold text-gray-600 mb-3">Built This Session</h3>
            <div className="grid grid-cols-2 gap-4">
              {products.map(p => (
                <div key={p.table_name} className="card p-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-emerald-50 to-emerald-100 flex items-center justify-center">
                      <span className="text-emerald-600 text-lg">📦</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-semibold text-gray-800">{p.table_name}</span>
                      <p className="text-[11px] text-gray-400 font-mono truncate">
                        eastside_dataproduct.{p.table_name}
                      </p>
                      {p.gcs_path && (
                        <p className="text-[10px] text-emerald-600 truncate mt-0.5">
                          ✓ {p.gcs_path}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Source datasets */}
        <h3 className="text-sm font-semibold text-gray-600 mb-3">
          Source Datasets — Landing Zone ({sources.length})
        </h3>
        {loading ? (
          <div className="text-gray-400 text-sm">Loading...</div>
        ) : (
          <div className="grid grid-cols-3 gap-3">
            {sources.map(ds => (
              <div key={ds} className="card p-3 text-xs text-gray-600 font-medium hover:text-ontika-blue cursor-pointer"
                onClick={() => onChat?.(`Onboard ${ds}`)}>
                📁 {ds}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Right: build panel */}
      <div className="w-[420px] border-l border-gray-200 flex flex-col bg-white">
        <div className="px-5 py-4 border-b border-gray-100">
          <h3 className="text-sm font-bold text-gray-800">Build Data Product</h3>
          <p className="text-[11px] text-gray-400 mt-0.5">
            Paste a full spec — sources, schemas, output columns, business rules
          </p>
        </div>

        <div className="flex-1 p-4 overflow-auto flex flex-col gap-3">
          <textarea
            value={spec}
            onChange={e => setSpec(e.target.value)}
            placeholder={`Build a data product called customer_360 for EastSide Apparel.\n\n## Source Datasets\n  gs://eastside-lakehouse/landing/customer_profiles/\n  gs://eastside-lakehouse/landing/pos_transactions/\n\n## Output Columns\ncustomer_id, loyalty_tier, total_spend, rfm_segment...`}
            className="flex-1 min-h-[320px] p-3 border border-gray-200 rounded-lg font-mono text-xs text-gray-700 focus:ring-2 focus:ring-ontika-blue/20 focus:border-ontika-blue/40 outline-none resize-none"
          />

          <button
            onClick={handleBuild}
            disabled={building || !spec.trim()}
            className="w-full py-2.5 bg-gradient-to-r from-ontika-blue to-ontika-purple text-white text-sm font-medium rounded-lg hover:shadow-md disabled:opacity-40 transition-all"
          >
            {building ? '⚙️ Generating SQL...' : '🚀 Build Data Product'}
          </button>

          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">
              {error}
            </div>
          )}

          {result?.sql && (
            <div className="mt-1">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-semibold text-gray-600">Generated SQL</span>
                <span className="text-[10px] text-emerald-600 font-medium">
                  ✓ {result.table_name}
                </span>
              </div>
              <pre className="p-3 bg-gray-900 text-green-400 rounded-lg text-[10px] overflow-auto max-h-64 leading-relaxed">
                {result.sql}
              </pre>
              {result.gcs_path && (
                <p className="mt-2 text-[10px] text-gray-400">
                  Pushed to: <span className="text-emerald-600 font-mono">{result.gcs_path}</span>
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
