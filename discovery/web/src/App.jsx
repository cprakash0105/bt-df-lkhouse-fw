import React, { useState } from 'react'
import { api } from './api'
import ChatPanel from './components/ChatPanel'
import HomePage from './components/HomePage'
import DataPanel from './components/DataPanel'
import CatalogPanel from './components/CatalogPanel'
import ProfilerPanel from './components/ProfilerPanel'

const VIEWS = {
  HOME: 'home',
  RESULTS: 'results',
  CATALOG: 'catalog',
  PROFILER: 'profiler',
}

export default function App() {
  const [view, setView] = useState(VIEWS.HOME)
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Welcome to **Ontika**. I can help you onboard datasets, browse the catalog, run profiling, or answer questions about your data estate.\n\nTry: "What\\'s available?" or "Onboard customer complaints"', type: 'text' }
  ])
  const [suggestion, setSuggestion] = useState(null)
  const [profileResult, setProfileResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [landingDatasets, setLandingDatasets] = useState(null)

  const addMessage = (msg) => setMessages(prev => [...prev, msg])

  const handleSend = async (text) => {
    if (!text.trim()) return
    addMessage({ role: 'user', content: text, type: 'text' })
    setLoading(true)

    const lower = text.toLowerCase().trim()

    try {
      // Landing list
      if (_isLandingRequest(lower)) {
        const result = await api.listLanding()
        setLandingDatasets(result.datasets)
        addMessage({
          role: 'assistant',
          content: `Found **${result.count} datasets** in landing:\n\n${result.datasets.map(d => `• ${d}`).join('\n')}\n\nWhich one would you like to onboard?`,
          type: 'text'
        })
      }
      // Profile request
      else if (lower.includes('profile') && (lower.includes('run') || lower.includes('start') || lower.includes('execute'))) {
        const datasetName = _extractDatasetFromText(lower)
        if (datasetName) {
          addMessage({ role: 'assistant', content: `Profiling **${datasetName}**...`, type: 'loading' })
          const result = await api.profileDataset(datasetName)
          setProfileResult(result)
          setView(VIEWS.PROFILER)
          setMessages(prev => prev.filter(m => m.type !== 'loading'))
          addMessage({
            role: 'assistant',
            content: `Profiled **${result.dataset_name}** — ${result.column_count} fields, ${result.row_count} rows (${result.duration_seconds}s).\n\nView results in the Profiler panel.`,
            type: 'text'
          })
        } else {
          addMessage({ role: 'assistant', content: 'Which dataset? Say "run profile on customer_complaints" or use the Profiler panel.', type: 'text' })
          setView(VIEWS.PROFILER)
        }
      }
      // Approve
      else if (lower === 'approve' || lower === 'approve all' || (lower.includes('approve') && !lower.includes('business'))) {
        if (!suggestion) {
          addMessage({ role: 'assistant', content: 'Nothing to approve yet. Discover a dataset first.', type: 'text' })
        } else {
          addMessage({ role: 'assistant', content: 'Processing approval...', type: 'text' })
          const result = await api.approve()
          addMessage({
            role: 'assistant',
            content: `✅ **Approved: ${suggestion.asset_name}**\n\n` +
              (result.new_terms_created?.length ? `• New BDEs: ${result.new_terms_created.join(', ')}\n` : '') +
              (result.ba_linked ? `• Linked to: ${result.ba_linked}\n` : '') +
              (result.config_gcs_path ? `• Config: ${result.config_gcs_path}\n` : '') +
              (result.contract_path ? `• Contract: ${result.contract_path}\n` : '') +
              (result.errors?.length ? `\n⚠️ ${result.errors.join('; ')}` : '') +
              '\n\nPipeline will trigger automatically. What\'s next?',
            type: 'text'
          })
          setSuggestion(null)
          setView(VIEWS.HOME)
        }
      }
      // Generate config
      else if (lower === 'show config' || lower === 'generate config' || lower === 'generate the yaml') {
        if (!suggestion) {
          addMessage({ role: 'assistant', content: 'No active discovery. Tell me what to onboard first.', type: 'text' })
        } else {
          const result = await api.generateConfig()
          addMessage({ role: 'assistant', content: `\`\`\`yaml\n${result.yaml}\n\`\`\``, type: 'text' })
        }
      }
      // Corrections
      else if (suggestion && _isCorrection(lower)) {
        const correction = _parseCorrection(lower)
        if (correction) {
          await api.correct(correction.field, correction.action, correction.values)
          const updated = await api.getSuggestion()
          setSuggestion(updated)
          addMessage({ role: 'assistant', content: `✅ ${correction.field}: ${correction.action}`, type: 'text' })
        } else {
          addMessage({ role: 'assistant', content: 'Try: "status is not PII" or "priority values are low, medium, high"', type: 'text' })
        }
      }
      // Catalog/glossary questions
      else if (_isGlossaryQuestion(lower) && !_isFieldSpecificQuestion(lower)) {
        const answer = await _answerGlossaryQuestion(lower)
        addMessage({ role: 'assistant', content: answer, type: 'text' })
      }
      // Questions about current results
      else if (_isQuestion(lower)) {
        if (suggestion) {
          const answer = _answerQuestion(lower, suggestion)
          addMessage({ role: 'assistant', content: answer, type: 'text' })
        } else {
          addMessage({ role: 'assistant', content: 'No active discovery. Try onboarding a dataset first.', type: 'text' })
        }
      }
      // Default: discover
      else {
        addMessage({ role: 'assistant', content: 'Discovering...', type: 'loading' })
        const result = await api.discover({ text })
        setSuggestion(result)
        setView(VIEWS.RESULTS)
        setMessages(prev => prev.filter(m => m.type !== 'loading'))
        addMessage({
          role: 'assistant',
          content: `Discovered **${result.asset_name}** — ${result.fields.length} fields.\n\n` +
            `• Domain: ${result.data_domain || '?'}\n` +
            `• Business App: ${result.business_application || '?'} (${Math.round(result.app_confidence * 100)}%)\n` +
            `• Primary Key: \`${result.primary_key}\`\n` +
            `• PII: ${result.fields.filter(f => f.is_pii).map(f => f.name).join(', ') || 'none'}\n\n` +
            `Say **approve** when ready, or correct anything.`,
          type: 'text'
        })
      }
    } catch (e) {
      setMessages(prev => prev.filter(m => m.type !== 'loading'))
      addMessage({ role: 'assistant', content: `❌ ${e.message}`, type: 'error' })
    } finally {
      setLoading(false)
    }
  }

  // Render main panel based on current view
  const renderMainPanel = () => {
    switch (view) {
      case VIEWS.RESULTS:
        return <DataPanel suggestion={suggestion} landingDatasets={landingDatasets} />
      case VIEWS.CATALOG:
        return <CatalogPanel />
      case VIEWS.PROFILER:
        return <ProfilerPanel profileResult={profileResult} setProfileResult={setProfileResult} />
      default:
        return <HomePage landingDatasets={landingDatasets} />
    }
  }

  return (
    <div className="flex flex-col h-screen bg-[#0a0e1a]">
      {/* Top Nav */}
      <header className="flex items-center justify-between px-4 py-2 border-b border-[#1e2a4a] bg-[#0f1524]">
        <div className="flex items-center gap-3">
          <AtomIcon />
          <span className="text-lg font-bold text-white tracking-wider">ONTIKA</span>
          <span className="text-[10px] text-gray-500 tracking-[2px] hidden sm:inline">INTELLIGENT DATA DISCOVERY</span>
        </div>

        {/* Nav buttons */}
        <nav className="flex items-center gap-1">
          {[
            { id: VIEWS.HOME, label: 'Home', icon: '🏠' },
            { id: VIEWS.CATALOG, label: 'Catalog', icon: '📖' },
            { id: VIEWS.PROFILER, label: 'Profiler', icon: '📊' },
            { id: VIEWS.RESULTS, label: 'Results', icon: '🔍' },
          ].map(({ id, label, icon }) => (
            <button
              key={id}
              onClick={() => setView(id)}
              className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
                view === id
                  ? 'bg-gradient-to-r from-red-600/20 to-blue-600/20 text-white border border-blue-500/30'
                  : 'text-gray-400 hover:text-white hover:bg-[#1a2035]'
              }`}
            >
              {icon} {label}
            </button>
          ))}
        </nav>

        <div className="text-right hidden sm:block">
          <p className="text-xs text-gray-500">BT Data Fabric</p>
          <p className="text-[10px] text-gray-600">GCP · europe-west2</p>
        </div>
      </header>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Main Panel */}
        <div className="flex-1 overflow-auto">
          {renderMainPanel()}
        </div>

        {/* Right: Assistant (always visible) */}
        <div className="w-[380px] border-l border-[#1e2a4a] flex flex-col">
          <ChatPanel messages={messages} onSend={handleSend} loading={loading} />
        </div>
      </div>
    </div>
  )
}

// --- Atom Icon ---
function AtomIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 64 64">
      <ellipse cx="32" cy="32" rx="28" ry="10" fill="none" stroke="#DC143C" strokeWidth="1.8" transform="rotate(-30, 32, 32)" opacity="0.9"/>
      <ellipse cx="32" cy="32" rx="28" ry="10" fill="none" stroke="#1E90FF" strokeWidth="1.8" transform="rotate(30, 32, 32)" opacity="0.9"/>
      <ellipse cx="32" cy="32" rx="28" ry="10" fill="none" stroke="#FFD700" strokeWidth="1.8" transform="rotate(90, 32, 32)" opacity="0.9"/>
      <circle cx="32" cy="32" r="6" fill="#1a237e"/>
      <circle cx="32" cy="32" r="3" fill="#FFD700"/>
      <circle cx="32" cy="32" r="1.5" fill="#FFFFFF"/>
    </svg>
  )
}

// --- Intent Helpers ---

function _isLandingRequest(text) {
  return ((text.includes('available') && text.includes('landing')) ||
    (text.includes('landing') && text.includes('list')) ||
    text === "what's available" || text === "what's available?" || text === 'whats available' ||
    (text.includes('available') && text.includes('dataset')) ||
    (text.includes('available') && !text.includes('business app') && !text.includes('business application') && !text.includes('domain') && !text.includes('bde') && !text.includes('term')))
}

function _extractDatasetFromText(text) {
  const patterns = [
    /profile\s+(?:on\s+)?(?:the\s+)?([a-z_]+)/,
    /run\s+profile\s+(?:on\s+)?(?:the\s+)?([a-z_]+)/,
    /profile\s+(.+?)(?:\s+data|\s+dataset)?$/,
  ]
  for (const p of patterns) {
    const m = text.match(p)
    if (m) return m[1].trim().replace(/\s+/g, '_')
  }
  return null
}

function _isGlossaryQuestion(text) {
  if (text.includes('business application') || text.includes('business app') ||
    text.includes('how many') || text.includes('bde') || text.includes('glossary') ||
    (text.includes('domain') && (text.includes('how') || text.includes('what') || text.includes('which') || text.includes('tell') || text.includes('show') || text.includes('list'))) ||
    (text.includes('terms') && (text.includes('how many') || text.includes('list') || text.includes('show'))) ||
    text.includes('pii') || text.includes('dq rule') || text.includes('data quality') ||
    text.includes('who owns') || text.includes('relationship') || text.includes('linked') ||
    text.includes('catalog') || text.includes('search for') ||
    (text.includes('list') && (text.includes('application') || text.includes('domain') || text.includes('term') || text.includes('dataset')))) {
    return true
  }
  const knownEntities = [
    'credit risk', 'customer management', 'marketing', 'billing', 'finance',
    'order management', 'product catalog', 'core banking', 'payments hub',
    'card management', 'loan origination', 'loan management', 'crm', 'aml',
    'risk engine', 'credit score', 'customer id', 'pan number'
  ]
  if (knownEntities.some(e => text.includes(e))) return true
  if (text.includes('inside') || text.includes('contents') || text.includes('contain') ||
      text.includes('belongs to') || text.includes('part of') || text.includes('under')) {
    return true
  }
  return false
}

function _isFieldSpecificQuestion(text) {
  return (text.includes('marked') || text.includes('why is') || text.includes('why did')) &&
    (text.includes('pii') || text.includes('unique') || text.includes('key') || text.includes('null'))
}

async function _answerGlossaryQuestion(text) {
  try {
    const result = await api.askCatalog(text)
    return result.answer
  } catch (e) {
    return `Could not query catalog: ${e.message}`
  }
}

function _isQuestion(text) {
  const qw = ['did you', 'can you tell', 'what is', 'what are', 'why', 'how', 'which', 'show me', 'explain', 'tell me', 'is there', 'profile', 'fingerprint', 'confidence', 'reasoning', 'why did']
  if (text.includes('what about') || text.includes('how about')) return false
  return qw.some(q => text.includes(q)) || text.endsWith('?')
}

function _answerQuestion(text, suggestion) {
  if (text.includes('profile') || text.includes('fingerprint')) {
    const pf = suggestion.fields.filter(f => f.reasoning?.some(r => r.startsWith('PROFILE')))
    if (pf.length > 0) {
      return `Profiled ${pf.length} fields:\n\n` + pf.map(f => `• **${f.name}**: ${f.reasoning.find(r => r.startsWith('PROFILE'))}`).join('\n')
    }
    return 'No profile evidence found for this dataset.'
  }
  if (text.includes('pii')) {
    const pii = suggestion.fields.filter(f => f.is_pii)
    return pii.length > 0
      ? `PII fields:\n\n${pii.map(f => `• **${f.name}**`).join('\n')}\n\nTo fix: "field_name is not PII"`
      : 'No PII fields detected.'
  }
  return `Viewing **${suggestion.asset_name}** (${suggestion.fields.length} fields). Say "approve" or ask about specific fields.`
}

function _isCorrection(text) {
  return text.includes('is not pii') || text.includes('is pii') ||
    text.includes('is not unique') || text.includes('is unique') ||
    text.includes('is nullable') || text.includes('values are') ||
    text.includes('values should') || text.includes('maps to') || text.includes('remove ')
}

function _parseCorrection(text) {
  let m
  if ((m = text.match(/(\w+)\s+is\s+not\s+pii/))) return { field: m[1], action: 'remove_pii' }
  if ((m = text.match(/(\w+)\s+is\s+pii/))) return { field: m[1], action: 'add_pii' }
  if ((m = text.match(/(\w+)\s+is\s+not\s+unique/))) return { field: m[1], action: 'remove_unique' }
  if ((m = text.match(/(\w+)\s+is\s+unique/))) return { field: m[1], action: 'add_unique' }
  if ((m = text.match(/(\w+)\s+values?\s+(?:are|should be)\s+(.+)/))) return { field: m[1], action: 'set_accepted_values', values: m[2].split(',').map(v => v.trim()) }
  if ((m = text.match(/(\w+)\s+is\s+nullable/))) return { field: m[1], action: 'remove_not_null' }
  return null
}
