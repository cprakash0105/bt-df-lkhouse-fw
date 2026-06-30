import React, { useState, useEffect } from 'react'
import { api } from '../api'

export default function HomePage({ landingDatasets }) {
  const [stats, setStats] = useState(null)

  useEffect(() => {
    api.health().then(setStats).catch(() => {})
  }, [])

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Platform header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white mb-1">BT Data Fabric</h1>
        <p className="text-sm text-gray-500">GCP Native Lakehouse · europe-west2 · bt-df-lkhouse</p>
      </div>

      {/* Layer cards */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        <LayerCard title="Landing Zone" count={landingDatasets?.length || '—'} subtitle="Raw JSONL" color="border-red-500/40" dot="bg-red-500" />
        <LayerCard title="Reservoir" count="—" subtitle="Parquet (typed)" color="border-blue-500/40" dot="bg-blue-500" />
        <LayerCard title="CCN (Iceberg)" count="—" subtitle="Governed" color="border-yellow-500/40" dot="bg-yellow-500" />
        <LayerCard title="Data Products" count="—" subtitle="BigQuery" color="border-green-500/40" dot="bg-green-500" />
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        <StatCard label="Business Data Elements" value={stats?.glossary_terms || '—'} icon="📖" />
        <StatCard label="Landing Datasets" value={landingDatasets?.length || '—'} icon="📁" />
        <StatCard label="Profiler Service" value="Active" icon="📊" status="ok" />
      </div>

      {/* Landing datasets */}
      {landingDatasets && (
        <div className="mb-6">
          <h3 className="text-sm font-medium text-gray-400 mb-3">DATASETS IN LANDING ZONE</h3>
          <div className="grid grid-cols-3 gap-2">
            {landingDatasets.map(ds => (
              <div key={ds} className="p-2 bg-[#0f1524] border border-[#1e2a4a] rounded text-xs text-gray-300 hover:border-blue-500/50 cursor-pointer">
                📁 {ds}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Services */}
      <div className="mb-6">
        <h3 className="text-sm font-medium text-gray-400 mb-3">PLATFORM SERVICES</h3>
        <div className="grid grid-cols-5 gap-2">
          <ServiceBadge name="Cloud Run" detail="Ontika + Profiler" status="ok" />
          <ServiceBadge name="Dataproc" detail="Spark Processing" status="ok" />
          <ServiceBadge name="BigQuery" detail="Data Products" status="ok" />
          <ServiceBadge name="Dataplex" detail="Knowledge Catalog" status="ok" />
          <ServiceBadge name="Firestore" detail="Catalog Cache" status="ok" />
        </div>
      </div>

      {/* Quick actions */}
      <div className="p-4 bg-[#0f1524] border border-[#1e2a4a] rounded-lg">
        <h3 className="text-sm font-medium text-gray-400 mb-2">QUICK START</h3>
        <p className="text-xs text-gray-500">
          Use the assistant on the right to: onboard datasets, browse the catalog, run profiling, or ask questions about your data estate.
        </p>
      </div>
    </div>
  )
}

function LayerCard({ title, count, subtitle, color, dot }) {
  return (
    <div className={`p-3 rounded-lg border ${color} bg-[#0f1524]`}>
      <div className="flex items-center gap-2 mb-1">
        <div className={`w-2 h-2 rounded-full ${dot}`} />
        <span className="text-xs font-medium text-white">{title}</span>
      </div>
      <p className="text-xl font-bold text-white">{count}</p>
      <p className="text-[10px] text-gray-500">{subtitle}</p>
    </div>
  )
}

function StatCard({ label, value, icon, status }) {
  return (
    <div className="p-3 rounded-lg border border-[#1e2a4a] bg-[#0f1524] flex items-center gap-3">
      <span className="text-xl">{icon}</span>
      <div>
        <p className={`text-lg font-bold ${status === 'ok' ? 'text-green-400' : 'text-white'}`}>{value}</p>
        <p className="text-[10px] text-gray-500">{label}</p>
      </div>
    </div>
  )
}

function ServiceBadge({ name, detail, status }) {
  return (
    <div className="p-2 rounded border border-[#1e2a4a] bg-[#0f1524] text-center">
      <div className={`w-1.5 h-1.5 rounded-full mx-auto mb-1 ${status === 'ok' ? 'bg-green-400' : 'bg-gray-600'}`} />
      <p className="text-[11px] font-medium text-gray-300">{name}</p>
      <p className="text-[9px] text-gray-600">{detail}</p>
    </div>
  )
}
