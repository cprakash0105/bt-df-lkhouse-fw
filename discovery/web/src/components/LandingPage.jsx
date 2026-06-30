import React from 'react'

export default function LandingPage({ onStart }) {
  return (
    <div className="min-h-screen bg-[#0a0e1a] flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between px-8 py-4 border-b border-[#1e2a4a]">
        <div className="flex items-center gap-3">
          <AtomIcon />
          <div>
            <h1 className="text-xl font-bold text-white tracking-wide">ONTIKA</h1>
            <p className="text-[10px] text-gray-500 tracking-[3px]">INTELLIGENT DATA DISCOVERY</p>
          </div>
        </div>
        <div className="text-right">
          <p className="text-sm text-gray-400">BT Data Fabric</p>
          <p className="text-xs text-gray-600">GCP · europe-west2</p>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 flex flex-col items-center justify-center px-8 py-12">
        {/* Platform Landscape */}
        <div className="w-full max-w-5xl mb-12">
          <h2 className="text-sm font-medium text-gray-500 mb-4 tracking-wider">PLATFORM LANDSCAPE</h2>

          <div className="grid grid-cols-4 gap-4 mb-8">
            {/* Layer cards */}
            <LayerCard
              title="Landing Zone"
              subtitle="16 datasets"
              items={['CIBIL Bureau', 'e-KYC', 'UPI Txns', 'Complaints', 'Loan Repayment', 'Cards', 'Motor Policy', '+ 9 more']}
              color="border-red-500/30"
              dot="bg-red-500"
            />
            <LayerCard
              title="Reservoir"
              subtitle="Parquet (typed)"
              items={['Schema-on-read', 'ingestion_ts', 'Append-only', 'Type overrides']}
              color="border-blue-500/30"
              dot="bg-blue-500"
            />
            <LayerCard
              title="CCN (Iceberg)"
              subtitle="Governed"
              items={['DQ Validated', 'Deduplicated', 'Schema governed', 'Time-travel']}
              color="border-yellow-500/30"
              dot="bg-yellow-500"
            />
            <LayerCard
              title="Data Products"
              subtitle="BigQuery"
              items={['loan_eligibility_360', 'customer_spend_360', 'collections_priority', 'customer_health']}
              color="border-green-500/30"
              dot="bg-green-500"
            />
          </div>

          {/* Governance row */}
          <div className="grid grid-cols-3 gap-4 mb-8">
            <StatCard label="Business Data Elements" value="40+" icon="📖" />
            <StatCard label="Business Applications" value="14" icon="🏢" />
            <StatCard label="Data Domains" value="9" icon="📁" />
          </div>

          {/* Services row */}
          <div className="grid grid-cols-5 gap-3">
            <ServiceBadge name="Cloud Run" detail="SD + Profiler" />
            <ServiceBadge name="Dataproc" detail="Spark Processing" />
            <ServiceBadge name="BigQuery" detail="Data Products" />
            <ServiceBadge name="Dataplex" detail="Knowledge Catalog" />
            <ServiceBadge name="Cloud Functions" detail="Automation" />
          </div>
        </div>

        {/* CTA */}
        <div className="text-center">
          <button
            onClick={onStart}
            className="px-8 py-3 bg-gradient-to-r from-red-600 via-blue-600 to-yellow-500 text-white font-semibold rounded-lg hover:opacity-90 transition-opacity text-lg shadow-lg shadow-blue-500/20"
          >
            Launch Ontika →
          </button>
          <p className="mt-3 text-xs text-gray-500">
            Discover • Profile • Onboard • Govern
          </p>
        </div>
      </main>

      {/* Footer */}
      <footer className="px-8 py-3 border-t border-[#1e2a4a] flex justify-between text-xs text-gray-600">
        <span>bt-df-lkhouse · GCP Project 978009776592</span>
        <span>Ontika v1.0 · Profiler Service Active</span>
      </footer>
    </div>
  )
}

function LayerCard({ title, subtitle, items, color, dot }) {
  return (
    <div className={`p-4 rounded-lg border ${color} bg-[#0f1524]`}>
      <div className="flex items-center gap-2 mb-2">
        <div className={`w-2 h-2 rounded-full ${dot}`} />
        <h3 className="text-sm font-medium text-white">{title}</h3>
      </div>
      <p className="text-xs text-gray-500 mb-2">{subtitle}</p>
      <ul className="space-y-0.5">
        {items.map((item, i) => (
          <li key={i} className="text-xs text-gray-400">• {item}</li>
        ))}
      </ul>
    </div>
  )
}

function StatCard({ label, value, icon }) {
  return (
    <div className="p-4 rounded-lg border border-[#1e2a4a] bg-[#0f1524] flex items-center gap-3">
      <span className="text-2xl">{icon}</span>
      <div>
        <p className="text-xl font-bold text-white">{value}</p>
        <p className="text-xs text-gray-500">{label}</p>
      </div>
    </div>
  )
}

function ServiceBadge({ name, detail }) {
  return (
    <div className="p-2 rounded border border-[#1e2a4a] bg-[#0f1524] text-center">
      <p className="text-xs font-medium text-gray-300">{name}</p>
      <p className="text-[10px] text-gray-600">{detail}</p>
    </div>
  )
}

function AtomIcon() {
  return (
    <svg width="36" height="36" viewBox="0 0 64 64">
      <ellipse cx="32" cy="32" rx="28" ry="10" fill="none" stroke="#DC143C" strokeWidth="1.5" transform="rotate(-30, 32, 32)" opacity="0.9"/>
      <ellipse cx="32" cy="32" rx="28" ry="10" fill="none" stroke="#1E90FF" strokeWidth="1.5" transform="rotate(30, 32, 32)" opacity="0.9"/>
      <ellipse cx="32" cy="32" rx="28" ry="10" fill="none" stroke="#FFD700" strokeWidth="1.5" transform="rotate(90, 32, 32)" opacity="0.9"/>
      <circle cx="56" cy="22" r="3" fill="#DC143C"/>
      <circle cx="10" cy="26" r="3" fill="#1E90FF"/>
      <circle cx="32" cy="4" r="3" fill="#FFD700"/>
      <circle cx="32" cy="32" r="9" fill="#FFD700" opacity="0.3"/>
      <circle cx="32" cy="32" r="6" fill="#1a237e"/>
      <circle cx="32" cy="32" r="3" fill="#FFD700"/>
      <circle cx="32" cy="32" r="1.5" fill="#FFFFFF"/>
    </svg>
  )
}
