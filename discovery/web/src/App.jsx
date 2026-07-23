import React, { useState } from 'react'
import { api } from './api'
import ChatPanel from './components/ChatPanel'
import HomePage from './components/HomePage'
import DataPanel from './components/DataPanel'
import ProfilerPanel from './components/ProfilerPanel'
import DataProductsPanel from './components/DataProductsPanel'
import GlossaryView from './components/GlossaryView'
import TechnicalView from './components/TechnicalView'

const VIEWS = {
  HOME: 'home',
  DATA_PRODUCTS: 'dataproducts',
  GLOSSARY: 'glossary',
  TECHNICAL: 'technical',
  PROFILER: 'profiler',
  RESULTS: 'results',
}

export default function App() {
  const [view, setView] = useState(VIEWS.HOME)
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Welcome to **Ontika**. I can help you onboard datasets, browse the catalog, run profiling, or answer questions about your data estate.\n\nTry: "What is available?" or "Onboard customer complaints"', type: 'text' }
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
      // Questions about current results — only when a discovery is active
      else if (suggestion && _isQuestion(lower)) {
        const answer = _answerQuestion(lower, suggestion)
        addMessage({ role: 'assistant', content: answer, type: 'text' })
      }
      // Onboard intent — explicit trigger words only
      else if (_isOnboardRequest(lower)) {
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
      // Catch-all — EVERYTHING else goes to the LLM
      else {
        const result = await _askLLM(text)
        if (typeof result === 'object' && result.chart) {
          addMessage({ role: 'assistant', content: result.text, type: 'text', chart: result.chart })
        } else {
          addMessage({ role: 'assistant', content: result, type: 'text' })
        }
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
      case VIEWS.DATA_PRODUCTS:
        return <DataProductsPanel />
      case VIEWS.GLOSSARY:
        return <GlossaryView />
      case VIEWS.TECHNICAL:
        return <TechnicalView />
      case VIEWS.RESULTS:
        return <DataPanel suggestion={suggestion} landingDatasets={landingDatasets} />
      case VIEWS.PROFILER:
        return <ProfilerPanel profileResult={profileResult} setProfileResult={setProfileResult} />
      case VIEWS.HOME:
        return <HomePage onChat={handleSend} />
    }
  }

  return (
    <div className="flex flex-col h-screen bg-ontika-light">
      {/* Top Nav */}
      <header className="flex items-center justify-between px-6 py-3 bg-white border-b border-gray-200 shadow-sm">
        <div className="flex items-center gap-3">
          <OntikaLogo />
          <div>
            <span className="text-lg font-semibold text-ontika-navy tracking-tight">Ontika</span>
            <span className="text-[10px] text-gray-400 ml-2 tracking-wide hidden sm:inline">INTELLIGENT DATA DISCOVERY</span>
          </div>
        </div>

        {/* Nav buttons */}
        <nav className="flex items-center gap-1 bg-gray-50 rounded-lg p-1">
          {[
            { id: VIEWS.HOME, label: 'Home', icon: '🏠' },
            { id: VIEWS.DATA_PRODUCTS, label: 'Data Products', icon: '📦' },
            { id: VIEWS.GLOSSARY, label: 'Glossary', icon: '📖' },
            { id: VIEWS.TECHNICAL, label: 'Technical', icon: '💾' },
            { id: VIEWS.PROFILER, label: 'Profiler', icon: '📊' },
            { id: VIEWS.RESULTS, label: 'Results', icon: '🔍' },
          ].map(({ id, label, icon }) => (
            <button
              key={id}
              onClick={() => setView(id)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-150 ${
                view === id
                  ? 'bg-white text-ontika-blue shadow-sm border border-indigo-100'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-white/60'
              }`}
            >
              {icon} {label}
            </button>
          ))}
        </nav>

        <div className="text-right hidden sm:block">
          <p className="text-xs text-gray-500 font-medium">BT Data Fabric</p>
          <p className="text-[10px] text-gray-400">GCP · europe-west2</p>
        </div>
      </header>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Main Panel */}
        <div className="flex-1 overflow-auto">
          {renderMainPanel()}
        </div>

        {/* Right: Assistant (always visible) */}
        <div className="w-[400px] border-l border-gray-200 flex flex-col bg-white">
          <ChatPanel messages={messages} onSend={handleSend} loading={loading} />
        </div>
      </div>
    </div>
  )
}

// --- Ontika Logo (stylised O with orbital ring + data node) ---
function OntikaLogo() {
  return (
    <svg width="32" height="32" viewBox="0 0 64 64" fill="none">
      {/* Outer ring — indigo gradient */}
      <circle cx="32" cy="32" r="26" stroke="url(#grad1)" strokeWidth="3" fill="none" />
      {/* Inner orbital path */}
      <ellipse cx="32" cy="32" rx="18" ry="8" stroke="#7C3AED" strokeWidth="1.5" fill="none" transform="rotate(-20, 32, 32)" opacity="0.7" />
      {/* Core circle */}
      <circle cx="32" cy="32" r="8" fill="url(#grad2)" />
      {/* Data node accent (gold) */}
      <circle cx="48" cy="22" r="4" fill="#F59E0B" />
      <circle cx="48" cy="22" r="2" fill="#FFFFFF" />
      {/* Small accent nodes */}
      <circle cx="16" cy="40" r="2.5" fill="#7C3AED" opacity="0.6" />
      <circle cx="44" cy="46" r="2" fill="#4F46E5" opacity="0.4" />
      <defs>
        <linearGradient id="grad1" x1="0" y1="0" x2="64" y2="64">
          <stop offset="0%" stopColor="#4F46E5" />
          <stop offset="100%" stopColor="#7C3AED" />
        </linearGradient>
        <linearGradient id="grad2" x1="24" y1="24" x2="40" y2="40">
          <stop offset="0%" stopColor="#4F46E5" />
          <stop offset="100%" stopColor="#7C3AED" />
        </linearGradient>
      </defs>
    </svg>
  )
}

// --- Intent Helpers ---

// Only trigger landing list for explicit requests
function _isLandingRequest(text) {
  return text === "what's available" || text === "what's available?" || text === 'whats available' ||
    (text.includes('landing') && (text.includes('list') || text.includes('show') || text.includes('what'))) ||
    (text.includes('available') && text.includes('dataset')) ||
    (text.includes('available') && text.includes('landing'))
}

// Only trigger discover for explicit onboard/load/ingest intent
function _isOnboardRequest(text) {
  return /\b(onboard|ingest|load|discover|add|register|bring in)\b/.test(text) &&
    !text.includes('how') && !text.includes('what') && !text.includes('why')
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

// Catalog/glossary questions — must NOT match onboard intent
function _isGlossaryQuestion(text) {
  if (_isOnboardRequest(text)) return false
  if (text.includes('business application') || text.includes('business app') ||
    text.includes('bde') || text.includes('glossary') ||
    text.includes('dq rule') || text.includes('data quality') ||
    text.includes('who owns') || text.includes('relationship') || text.includes('linked') ||
    text.includes('catalog') || text.includes('search for') ||
    text.includes('data product') || text.includes('curated') || text.includes('curate') ||
    (text.includes('how many') && (text.includes('term') || text.includes('domain') || text.includes('application') || text.includes('bde') || text.includes('pii'))) ||
    (text.includes('domain') && (text.includes('what') || text.includes('which') || text.includes('tell') || text.includes('show') || text.includes('list'))) ||
    (text.includes('list') && (text.includes('application') || text.includes('domain') || text.includes('term'))) ||
    (text.includes('pii') && (text.includes('which') || text.includes('what') || text.includes('list') || text.includes('show')))) {
    return true
  }
  const knownEntities = [
    'credit risk', 'customer management', 'marketing', 'billing', 'finance',
    'order management', 'product catalog', 'core banking', 'payments hub',
    'card management', 'loan origination', 'loan management', 'crm', 'aml',
    'risk engine', 'credit score', 'customer id', 'pan number',
    'retail', 'commerce', 'pos', 'online orders', 'returns', 'inventory'
  ]
  return knownEntities.some(e => text.includes(e))
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
    if (e.message?.includes('503') || e.message?.includes('unavailable')) {
      return `LLM is temporarily unavailable. Try again shortly.`
    }
    return `Could not query catalog: ${e.message}`
  }
}

// Questions about the current discovery result
function _isQuestion(text) {
  if (_isOnboardRequest(text)) return false
  const qw = ['what is', 'what are', 'why is', 'why did', 'how did', 'which field',
    'show me', 'explain', 'tell me about', 'what happened', 'what went wrong',
    'fingerprint', 'confidence', 'reasoning']
  return qw.some(q => text.includes(q)) || (text.endsWith('?') && text.length < 60)
}

function _answerQuestion(text, suggestion) {
  if (text.includes('what happened') || text.includes('what went wrong') || text.includes('why this error') || text.includes('why the error')) {
    return `Last discovery: **${suggestion.asset_name}** — ${suggestion.fields.length} fields detected.\n\n` +
      `• Domain: ${suggestion.data_domain || '?'}\n` +
      `• PII fields: ${suggestion.fields.filter(f => f.is_pii).map(f => f.name).join(', ') || 'none'}\n\n` +
      `Say **approve** to proceed or correct anything.`
  }
  if (text.includes('profile') || text.includes('fingerprint')) {
    const pf = suggestion.fields.filter(f => f.reasoning?.some(r => r.startsWith('PROFILE')))
    if (pf.length > 0)
      return `Profiled ${pf.length} fields:\n\n` + pf.map(f => `• **${f.name}**: ${f.reasoning.find(r => r.startsWith('PROFILE'))}`).join('\n')
    return 'No profile evidence found for this dataset.'
  }
  if (text.includes('pii')) {
    const pii = suggestion.fields.filter(f => f.is_pii)
    return pii.length > 0
      ? `PII fields:\n\n${pii.map(f => `• **${f.name}**`).join('\n')}\n\nTo remove: "field_name is not PII"`
      : 'No PII fields detected.'
  }
  if (text.includes('confidence') || text.includes('reasoning')) {
    const low = suggestion.fields.filter(f => f.confidence < 0.5)
    return low.length > 0
      ? `Low confidence fields:\n\n${low.map(f => `• **${f.name}** (${Math.round(f.confidence * 100)}%)`).join('\n')}\n\nYou can correct these.`
      : `All fields matched with good confidence.`
  }
  return `Viewing **${suggestion.asset_name}** (${suggestion.fields.length} fields).\n\nSay **approve** or correct anything, e.g. "nomination_flag is not PII".`
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

// Catch-all: pass to LLM via /ask endpoint
async function _askLLM(text) {
  try {
    const result = await api.askCatalog(text)
    // If chart data is returned, format it for display
    if (result.chart) {
      return { text: result.answer, chart: result.chart }
    }
    return result.answer
  } catch (e) {
    if (e.message?.includes('503') || e.message?.includes('unavailable')) {
      return `LLM is temporarily unavailable. Try again in a moment, or ask something specific like:\n\n• "What domains exist?"\n• "Show me all applications"\n• "Onboard pos_transactions"`
    }
    return `I couldn't process that: ${e.message}`
  }
}
