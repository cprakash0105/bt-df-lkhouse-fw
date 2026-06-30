import React, { useState, useRef, useEffect } from 'react'
import { api } from './api'
import DataPanel from './components/DataPanel'
import ChatPanel from './components/ChatPanel'

export default function App() {
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Hi! I\'m Semantic Discovery. Tell me what you\'d like to onboard — just say the dataset name or ask what\'s available in landing.', type: 'text' }
  ])
  const [suggestion, setSuggestion] = useState(null)
  const [profileData, setProfileData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [landingDatasets, setLandingDatasets] = useState(null)

  const addMessage = (msg) => setMessages(prev => [...prev, msg])

  const handleSend = async (text) => {
    if (!text.trim()) return
    addMessage({ role: 'user', content: text, type: 'text' })
    setLoading(true)

    const lower = text.toLowerCase().trim()

    try {
      // Command: list landing / what's available
      if ((lower.includes('available') || lower.includes('landing')) ||
          (lower.includes('list') && lower.includes('landing'))) {
        const result = await api.listLanding()
        setLandingDatasets(result.datasets)
        addMessage({
          role: 'assistant',
          content: `Found **${result.count} datasets** in landing:\n\n${result.datasets.map(d => `• ${d}`).join('\n')}\n\nWhich one would you like to onboard?`,
          type: 'text'
        })
      }
      // Command: approve
      else if (lower === 'approve' || lower === 'approve all' || lower.includes('approve')) {
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
        }
      }
      // Command: generate config
      else if (lower.includes('config') || lower.includes('yaml') || lower.includes('generate')) {
        if (!suggestion) {
          addMessage({ role: 'assistant', content: 'No active discovery. Tell me what to onboard first.', type: 'text' })
        } else {
          const result = await api.generateConfig()
          addMessage({ role: 'assistant', content: `Generated pipeline config:\n\`\`\`yaml\n${result.yaml}\n\`\`\``, type: 'text' })
        }
      }
      // Command: correction patterns
      else if (suggestion && _isCorrection(lower)) {
        const correction = _parseCorrection(lower)
        if (correction) {
          await api.correct(correction.field, correction.action, correction.values)
          const updated = await api.getSuggestion()
          setSuggestion(updated)
          addMessage({ role: 'assistant', content: `✅ Done — ${correction.field}: ${correction.action}`, type: 'text' })
        } else {
          addMessage({ role: 'assistant', content: 'I didn\'t understand that correction. Try: "status is not PII" or "priority values are low, medium, high, critical"', type: 'text' })
        }
      }
      // Questions about glossary/domains/BAs (can answer anytime)
      else if (_isGlossaryQuestion(lower)) {
        const answer = await _answerGlossaryQuestion(lower)
        addMessage({ role: 'assistant', content: answer, type: 'text' })
      }
      // Questions about current results (don't trigger discovery)
      else if (_isQuestion(lower)) {
        if (suggestion) {
          const answer = _answerQuestion(lower, suggestion)
          addMessage({ role: 'assistant', content: answer, type: 'text' })
        } else {
          addMessage({ role: 'assistant', content: 'No active discovery yet. Try: "What\'s available?" or "Onboard <dataset_name>"', type: 'text' })
        }
      }
      // Default: discover
      else {
        addMessage({ role: 'assistant', content: 'Discovering...', type: 'loading' })
        const result = await api.discover({ text })
        setSuggestion(result)
        // Remove the loading message
        setMessages(prev => prev.filter(m => m.type !== 'loading'))
        addMessage({
          role: 'assistant',
          content: `Discovered **${result.asset_name}** — ${result.fields.length} fields.\n\n` +
            `• Domain: ${result.data_domain || '?'}\n` +
            `• Business App: ${result.business_application || '?'} (${Math.round(result.app_confidence * 100)}%)\n` +
            `• Primary Key: \`${result.primary_key}\`\n` +
            `• PII fields: ${result.fields.filter(f => f.is_pii).map(f => f.name).join(', ') || 'none'}\n\n` +
            `Review the results on the left. Say **approve** when ready, or correct anything (e.g., "status is not PII").`,
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

  return (
    <div className="flex h-screen bg-gray-900">
      {/* Left: Data Panel (wide) */}
      <div className="flex-1 overflow-auto border-r border-gray-700">
        <DataPanel suggestion={suggestion} landingDatasets={landingDatasets} />
      </div>

      {/* Right: Chat Panel (narrow) */}
      <div className="w-[400px] flex flex-col">
        <ChatPanel messages={messages} onSend={handleSend} loading={loading} />
      </div>
    </div>
  )
}

function _isQuestion(text) {
  const questionWords = ['did you', 'can you tell', 'what is', 'what are', 'why', 'how', 'which', 'show me', 'explain', 'tell me', 'is there', 'was the', 'were the', 'has the', 'profile', 'fingerprint', 'confidence', 'reasoning', 'why did']
  return questionWords.some(q => text.includes(q)) || text.endsWith('?')
}

function _answerQuestion(text, suggestion) {
  if (text.includes('profile') || text.includes('fingerprint')) {
    const profiledFields = suggestion.fields.filter(f => f.reasoning?.some(r => r.startsWith('PROFILE')))
    if (profiledFields.length > 0) {
      return `Yes, I profiled the data from GCS landing. ${profiledFields.length} fields had profile evidence:\n\n` +
        profiledFields.map(f => {
          const profileReasoning = f.reasoning.filter(r => r.startsWith('PROFILE'))
          return `• **${f.name}**: ${profileReasoning[0]}`
        }).join('\n')
    } else {
      return 'No profile evidence was found for this dataset. This could mean:\n• No landing data exists at `gs://bucket/landing/' + suggestion.asset_name + '/`\n• The GCS client couldn\'t connect\n\nThe discovery used KG synonym match + rules + embeddings only.'
    }
  }
  if (text.includes('pii')) {
    const piiFields = suggestion.fields.filter(f => f.is_pii)
    if (piiFields.length > 0) {
      return `PII fields detected:\n\n` + piiFields.map(f => {
        const reason = f.reasoning?.find(r => r.toLowerCase().includes('pii')) || 'matched PII BDE'
        return `• **${f.name}**: ${reason}`
      }).join('\n') + '\n\nTo correct: say "<field_name> is not PII"'
    }
    return 'No PII fields detected in this dataset.'
  }
  if (text.includes('confidence') || text.includes('why')) {
    const field = suggestion.fields.find(f => text.includes(f.name))
    if (field) {
      return `**${field.name}** (confidence: ${Math.round(field.confidence * 100)}%):\n\n` +
        (field.reasoning || []).map(r => `• ${r}`).join('\n')
    }
    return 'Ask about a specific field, e.g., "why did you mark resolution_date as PII?"'
  }
  if (text.includes('domain') || text.includes('business app')) {
    return `• Domain: **${suggestion.data_domain || 'unknown'}**\n• Business Application: **${suggestion.business_application || 'unknown'}** (${Math.round(suggestion.app_confidence * 100)}% confidence)\n\nThis was inferred from field names and dataset name matching against known application keywords.`
  }
  return `Currently viewing **${suggestion.asset_name}** (${suggestion.fields.length} fields). You can:\n• Ask: "why is X marked as PII?"\n• Correct: "X is not PII" or "X values are a, b, c"\n• Approve: "approve"\n• Move on: "onboard <next dataset>"`
}

function _isGlossaryQuestion(text) {
  return text.includes('business application') || text.includes('business app') ||
    text.includes('how many') || text.includes('bde') || text.includes('glossary') ||
    (text.includes('domain') && (text.includes('how') || text.includes('what') || text.includes('which') || text.includes('tell') || text.includes('show') || text.includes('list'))) ||
    (text.includes('terms') && (text.includes('how many') || text.includes('list') || text.includes('show'))) ||
    text.includes('pii') || text.includes('dq rule') || text.includes('data quality') ||
    text.includes('who owns') || text.includes('relationship') || text.includes('linked') ||
    text.includes('catalog') || text.includes('search for') ||
    (text.includes('list') && (text.includes('application') || text.includes('domain') || text.includes('term') || text.includes('dataset')))
}

async function _answerGlossaryQuestion(text) {
  try {
    const result = await api.askCatalog(text)
    return result.answer
  } catch (e) {
    return `Could not query catalog: ${e.message}`
  }
}

function _isCorrection(text) {
  return text.includes('is not pii') || text.includes('is pii') ||
    text.includes('is not unique') || text.includes('is unique') ||
    text.includes('is nullable') || text.includes('not null') ||
    text.includes('values are') || text.includes('values should') ||
    text.includes('maps to') || text.includes('remove ')
}

function _parseCorrection(text) {
  let m
  m = text.match(/[`]?([\w]+)[`]?\s+is\s+not\s+pii/)
  if (m) return { field: m[1], action: 'remove_pii' }
  m = text.match(/[`]?([\w]+)[`]?\s+is\s+pii/)
  if (m) return { field: m[1], action: 'add_pii' }
  m = text.match(/[`]?([\w]+)[`]?\s+is\s+not\s+unique/)
  if (m) return { field: m[1], action: 'remove_unique' }
  m = text.match(/[`]?([\w]+)[`]?\s+is\s+unique/)
  if (m) return { field: m[1], action: 'add_unique' }
  m = text.match(/[`]?([\w]+)[`]?\s+(?:values?|accepted.values?)\s+(?:are|should be)\s+(.+)/)
  if (m) return { field: m[1], action: 'set_accepted_values', values: m[2].split(',').map(v => v.trim()) }
  m = text.match(/remove\s+[`]?([\w]+)[`]?\s+from\s+not.null/)
  if (m) return { field: m[1], action: 'remove_not_null' }
  m = text.match(/[`]?([\w]+)[`]?\s+is\s+nullable/)
  if (m) return { field: m[1], action: 'remove_not_null' }
  return null
}
