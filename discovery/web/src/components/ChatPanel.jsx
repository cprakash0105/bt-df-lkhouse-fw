import React, { useState, useRef, useEffect } from 'react'

export default function ChatPanel({ messages, onSend, loading }) {
  const [input, setInput] = useState('')
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!input.trim() || loading) return
    onSend(input.trim())
    setInput('')
  }

  return (
    <div className="flex flex-col h-full bg-gray-50/50">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-100 bg-white">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-ontika-blue to-ontika-purple flex items-center justify-center">
            <span className="text-white text-sm font-bold">O</span>
          </div>
          <div>
            <h2 className="text-sm font-semibold text-gray-800">Ontika Assistant</h2>
            <p className="text-[10px] text-gray-400">Intelligent Data Discovery</p>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-auto px-4 py-4 space-y-3">
        {messages.filter(m => m.type !== 'loading').map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
              msg.role === 'user'
                ? 'bg-ontika-blue text-white rounded-br-md shadow-sm'
                : msg.type === 'error'
                ? 'bg-red-50 text-red-700 border border-red-200 rounded-bl-md'
                : 'bg-white text-gray-700 border border-gray-100 shadow-card rounded-bl-md'
            }`}>
              <MessageContent content={msg.content} />
              {msg.chart && <ChartView chart={msg.chart} />}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-white border border-gray-100 shadow-card text-gray-500 px-4 py-2.5 rounded-2xl rounded-bl-md text-sm">
              <span className="inline-flex gap-1">
                <span className="w-2 h-2 bg-ontika-blue/40 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-2 h-2 bg-ontika-purple/40 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-2 h-2 bg-ontika-gold/40 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </span>
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="p-3 border-t border-gray-100 bg-white shadow-chat">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask anything or onboard a dataset..."
            disabled={loading}
            className="flex-1 px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-800 placeholder-gray-400 focus:ring-2 focus:ring-ontika-blue/20 focus:border-ontika-blue/40 focus:bg-white transition-all disabled:opacity-50 outline-none"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="px-4 py-2.5 bg-gradient-to-r from-ontika-blue to-ontika-purple text-white rounded-xl text-sm font-medium hover:shadow-md hover:-translate-y-0.5 transition-all disabled:opacity-40 disabled:hover:translate-y-0 disabled:hover:shadow-none"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
        <div className="mt-2 flex gap-1.5 flex-wrap">
          {['approve', 'show config', "what's available?"].map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => { setInput(q); }}
              className="px-2.5 py-1 text-xs text-gray-500 bg-gray-50 border border-gray-200 rounded-lg hover:bg-white hover:border-ontika-blue/30 hover:text-ontika-blue transition-all"
            >
              {q}
            </button>
          ))}
        </div>
      </form>
    </div>
  )
}

function MessageContent({ content }) {
  const lines = content.split('\n')
  return (
    <>
      {lines.map((line, i) => {
        // Unescape HTML entities that may come from the backend
        line = line.replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>')
        // Bold
        line = line.replace(/\*\*(.+?)\*\*/g, '<strong class="font-semibold">$1</strong>')
        // Code
        line = line.replace(/`(.+?)`/g, '<code class="bg-gray-100 text-indigo-600 px-1.5 py-0.5 rounded text-xs font-mono">$1</code>')
        // Bullet
        if (line.startsWith('• ') || line.startsWith('- ')) {
          return <div key={i} className="ml-2 py-0.5" dangerouslySetInnerHTML={{ __html: line }} />
        }
        return <div key={i} dangerouslySetInnerHTML={{ __html: line }} />
      })}
    </>
  )
}

function ChartView({ chart }) {
  if (!chart || !chart.labels || !chart.values) return null

  const maxVal = Math.max(...chart.values)

  const colors = [
    'bg-ontika-blue', 'bg-ontika-purple', 'bg-ontika-gold',
    'bg-emerald-500', 'bg-rose-500', 'bg-cyan-500',
    'bg-indigo-400', 'bg-amber-400', 'bg-teal-400', 'bg-pink-400',
  ]

  return (
    <div className="mt-3 pt-3 border-t border-gray-100">
      <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-2 font-semibold">
        {chart.value_axis || 'Value'} by {chart.label_axis || 'Category'}
      </p>
      <div className="space-y-1.5">
        {chart.labels.map((label, i) => {
          const pct = maxVal > 0 ? (chart.values[i] / maxVal) * 100 : 0
          return (
            <div key={i} className="flex items-center gap-2">
              <span className="text-[10px] text-gray-600 w-24 truncate text-right" title={label}>{label}</span>
              <div className="flex-1 h-5 bg-gray-50 rounded-md overflow-hidden relative">
                <div
                  className={`h-full ${colors[i % colors.length]} rounded-md transition-all duration-500`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-[10px] text-gray-700 font-semibold w-14 text-right">
                {typeof chart.values[i] === 'number'
                  ? chart.values[i] >= 1000
                    ? `${(chart.values[i] / 1000).toFixed(1)}k`
                    : chart.values[i].toLocaleString()
                  : chart.values[i]}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
