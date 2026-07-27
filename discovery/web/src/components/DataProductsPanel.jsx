import React, { useState, useEffect } from 'react'
import { api } from '../api'

export default function DataProductsPanel({ onChat }) {
  const [sources, setSources] = useState([])
  const [products, setProducts] = useState([])
  const [savedSpecs, setSavedSpecs] = useState([])
  const [loading, setLoading] = useState(true)
  const [building, setBuilding] = useState(false)
  const [parsing, setParsing] = useState(false)
  const [spec, setSpec] = useState('')
  const [brdText, setBrdText] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [rightTab, setRightTab] = useState('brd') // 'brd' | 'build'
  const [specYaml, setSpecYaml] = useState('')

  useEffect(() => {
    Promise.all([
      api.listLanding().then(r => setSources(r.datasets || [])),
      api.listBRDSpecs().then(r => setSavedSpecs(r.specs || [])).catch(() => {}),
    ]).catch(() => {}).finally(() => setLoading(false))
  }, [])

  const handleParseBRD = async () => {
    if (!brdText.trim()) return
    setParsing(true)
    setError(null)
    setSpecYaml('')
    try {
      const r = await api.parseBRD(brdText)
      setSpecYaml(r.spec_yaml)
      setSavedSpecs(prev => [
        { name: r.product_name, gcs_path: r.gcs_path, updated: new Date().toISOString() },
        ...prev.filter(s => s.name !== r.product_name),
      ])
    } catch (e) {
      setError(e.message)
    } finally {
      setParsing(false)
    }
  }

  const handleBuildFromSpec = () => {
    if (!specYaml.trim()) return
    setSpec(specYaml)
    setRightTab('build')
  }

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

  const handleLoadSpec = async (name) => {
    try {
      const r = await api.getBRDSpec(name)
      setSpecYaml(r.spec_yaml)
      setRightTab('brd')
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div className="flex h-full">
      {/* Left: products + sources + saved specs */}
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
                      <p className="text-[11px] text-gray-400 font-mono truncate">eastside_dataproduct.{p.table_name}</p>
                      {p.gcs_path && (
                        <p className="text-[10px] text-emerald-600 truncate mt-0.5">✓ {p.gcs_path}</p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Saved specs */}
        {savedSpecs.length > 0 && (
          <div className="mb-8">
            <h3 className="text-sm font-semibold text-gray-600 mb-3">Saved Product Specs ({savedSpecs.length})</h3>
            <div className="grid grid-cols-2 gap-3">
              {savedSpecs.map(s => (
                <div key={s.name}
                  className="card p-3 cursor-pointer hover:border-ontika-blue/30 hover:shadow-sm transition-all"
                  onClick={() => handleLoadSpec(s.name)}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-base">📋</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-semibold text-gray-700 truncate">{s.name}</p>
                      {s.updated && (
                        <p className="text-[10px] text-gray-400">{new Date(s.updated).toLocaleDateString()}</p>
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

      {/* Right: tabbed panel — BRD or Build */}
      <div className="w-[440px] border-l border-gray-200 flex flex-col bg-white">
        {/* Tab switcher */}
        <div className="flex gap-1 p-3 border-b border-gray-100 bg-gray-50">
          <button
            onClick={() => setRightTab('brd')}
            className={`flex-1 py-1.5 rounded-md text-xs font-medium transition-all ${
              rightTab === 'brd' ? 'bg-white text-ontika-blue shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            📄 BRD → Spec
          </button>
          <button
            onClick={() => setRightTab('build')}
            className={`flex-1 py-1.5 rounded-md text-xs font-medium transition-all ${
              rightTab === 'build' ? 'bg-white text-ontika-blue shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            🚀 Build Product
          </button>
        </div>

        {rightTab === 'brd' ? (
          <div className="flex-1 p-4 overflow-auto flex flex-col gap-3">
            <p className="text-[11px] text-gray-400">
              Paste your Business Requirements Document. Ontika will extract a structured YAML spec.
            </p>
            <textarea
              value={brdText}
              onChange={e => setBrdText(e.target.value)}
              placeholder={`We need a 360 view of customer offer uptake for the ET Group retail division.\n\nSources: dim_customer, dim_offer, fact_offer_subscription, fact_campaign_performance\n\nKey metrics:\n- Offer acceptance rate by customer segment\n- Campaign revenue by store region\n- Subscriber acquisition trend by month\n\nGrain: one row per customer per offer per month`}
              className="flex-1 min-h-[240px] p-3 border border-gray-200 rounded-lg text-xs text-gray-700 focus:ring-2 focus:ring-ontika-blue/20 focus:border-ontika-blue/40 outline-none resize-none"
            />
            <button
              onClick={handleParseBRD}
              disabled={parsing || !brdText.trim()}
              className="w-full py-2.5 bg-gradient-to-r from-ontika-blue to-ontika-purple text-white text-sm font-medium rounded-lg hover:shadow-md disabled:opacity-40 transition-all"
            >
              {parsing ? '⚙️ Parsing BRD...' : '✨ Generate Spec YAML'}
            </button>

            {error && (
              <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">{error}</div>
            )}

            {specYaml && (
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-600">Generated Spec</span>
                  <span className="text-[10px] text-emerald-600">✓ Saved to GCS</span>
                </div>
                <textarea
                  value={specYaml}
                  onChange={e => setSpecYaml(e.target.value)}
                  className="min-h-[200px] p-3 bg-gray-900 text-green-400 rounded-lg font-mono text-[10px] outline-none resize-none border-0"
                />
                <button
                  onClick={handleBuildFromSpec}
                  className="w-full py-2 bg-emerald-600 text-white text-xs font-medium rounded-lg hover:bg-emerald-700 transition-colors"
                >
                  🚀 Build Data Product from this Spec →
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="flex-1 p-4 overflow-auto flex flex-col gap-3">
            <p className="text-[11px] text-gray-400">
              Paste a full spec or use a generated one from the BRD tab.
            </p>
            <textarea
              value={spec}
              onChange={e => setSpec(e.target.value)}
              placeholder={`Build a data product called customer_360...`}
              className="flex-1 min-h-[280px] p-3 border border-gray-200 rounded-lg font-mono text-xs text-gray-700 focus:ring-2 focus:ring-ontika-blue/20 focus:border-ontika-blue/40 outline-none resize-none"
            />
            <button
              onClick={handleBuild}
              disabled={building || !spec.trim()}
              className="w-full py-2.5 bg-gradient-to-r from-ontika-blue to-ontika-purple text-white text-sm font-medium rounded-lg hover:shadow-md disabled:opacity-40 transition-all"
            >
              {building ? '⚙️ Generating SQL...' : '🚀 Build Data Product'}
            </button>

            {error && (
              <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">{error}</div>
            )}

            {result?.sql && (
              <div className="mt-1">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-semibold text-gray-600">Generated SQL</span>
                  <span className="text-[10px] text-emerald-600 font-medium">✓ {result.table_name}</span>
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
        )}
      </div>
    </div>
  )
}
