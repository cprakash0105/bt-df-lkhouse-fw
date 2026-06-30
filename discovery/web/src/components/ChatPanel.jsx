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
    <div className="flex flex-col h-full bg-[#0a0e1a]">
      {/* Header */}
      <div className="p-3 border-b border-[#1e2a4a] bg-[#0f1524]">
        <div className="flex items-center gap-2">
          <svg width="20" height="20" viewBox="0 0 64 64">
            <ellipse cx="32" cy="32" rx="28" ry="10" fill="none" stroke="#DC143C" strokeWidth="2" transform="rotate(-30, 32, 32)" opacity="0.9"/>
            <ellipse cx="32" cy="32" rx="28" ry="10" fill="none" stroke="#1E90FF" strokeWidth="2" transform="rotate(30, 32, 32)" opacity="0.9"/>
            <ellipse cx="32" cy="32" rx="28" ry="10" fill="none" stroke="#FFD700" strokeWidth="2" transform="rotate(90, 32, 32)" opacity="0.9"/>
            <circle cx="32" cy="32" r="6" fill="#1a237e"/>
            <circle cx="32" cy="32" r="3" fill="#FFD700"/>
          </svg>
          <h2 className="text-sm font-bold text-white">Ontika</h2>
        </div>
        <p className="text-xs text-gray-500 mt-0.5">Intelligent Data Discovery · BT Data Fabric</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-auto p-3 space-y-3">
        {messages.filter(m => m.type !== 'loading').map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[90%] px-3 py-2 rounded-lg text-sm whitespace-pre-wrap ${
              msg.role === 'user'
                ? 'bg-blue-600 text-white'
                : msg.type === 'error'
                ? 'bg-red-900/50 text-red-200 border border-red-700'
                : 'bg-gray-700 text-gray-100'
            }`}>
              <MessageContent content={msg.content} />
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-700 text-gray-300 px-3 py-2 rounded-lg text-sm animate-pulse">
              Thinking...
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="p-3 border-t border-[#1e2a4a] bg-[#0f1524]">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask anything or onboard a dataset..."
            disabled={loading}
            className="flex-1 px-3 py-2 bg-[#1a2035] border border-[#2a3a5a] rounded-lg text-sm text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="px-3 py-2 bg-gradient-to-r from-red-600 to-blue-600 text-white rounded-lg text-sm hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            →
          </button>
        </div>
        <div className="mt-1 flex gap-1 flex-wrap">
          {['approve', 'show config', "what's available?"].map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => { setInput(q); }}
              className="px-1.5 py-0.5 text-xs text-gray-500 bg-[#1a2035] border border-[#2a3a5a] rounded hover:bg-[#1e2a4a] hover:text-white"
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
  // Simple markdown-like rendering
  const lines = content.split('\n')
  return (
    <>
      {lines.map((line, i) => {
        // Bold
        line = line.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        // Code
        line = line.replace(/`(.+?)`/g, '<code class="bg-gray-600 px-1 rounded text-xs">$1</code>')
        // Bullet
        if (line.startsWith('• ') || line.startsWith('- ')) {
          return <div key={i} className="ml-2" dangerouslySetInnerHTML={{ __html: line }} />
        }
        return <div key={i} dangerouslySetInnerHTML={{ __html: line }} />
      })}
    </>
  )
}
