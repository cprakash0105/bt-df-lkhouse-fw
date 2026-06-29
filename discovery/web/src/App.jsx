import React, { useState } from 'react'
import DiscoverPanel from './components/DiscoverPanel'
import ResultsPanel from './components/ResultsPanel'
import GlossaryPanel from './components/GlossaryPanel'
import ProfilePanel from './components/ProfilePanel'

const TABS = ['Discover', 'Results', 'Profile', 'Glossary']

export default function App() {
  const [tab, setTab] = useState('Discover')
  const [suggestion, setSuggestion] = useState(null)
  const [profileData, setProfileData] = useState(null)

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className="w-56 bg-gray-900 text-white flex flex-col">
        <div className="p-4 border-b border-gray-700">
          <h1 className="text-lg font-bold">🔍 Semantic Discovery</h1>
          <p className="text-xs text-gray-400 mt-1">AI-Powered Data Onboarding</p>
        </div>
        <nav className="flex-1 p-2">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`w-full text-left px-3 py-2 rounded text-sm mb-1 ${
                tab === t ? 'bg-blue-600' : 'hover:bg-gray-800'
              }`}
            >
              {t}
            </button>
          ))}
        </nav>
        <div className="p-3 border-t border-gray-700 text-xs text-gray-500">
          v1.0 • FastAPI + React
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        {tab === 'Discover' && (
          <DiscoverPanel onResult={setSuggestion} onSwitchTab={setTab} />
        )}
        {tab === 'Results' && (
          <ResultsPanel suggestion={suggestion} setSuggestion={setSuggestion} />
        )}
        {tab === 'Profile' && (
          <ProfilePanel profileData={profileData} setProfileData={setProfileData} />
        )}
        {tab === 'Glossary' && <GlossaryPanel />}
      </main>
    </div>
  )
}
