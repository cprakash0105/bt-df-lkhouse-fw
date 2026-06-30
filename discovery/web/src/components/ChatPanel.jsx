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
    <div className="flex flex-col h-full bg-gray-850">
      {/* Header */}
      <div className="p-3 border-b border-gray-700 bg-gray-800">
        <h2 className="text-sm font-bold text-white">🔍 Semantic Discovery</h2>
        <p className="text-xs text-gray-400">Talk naturally — I'll discover, profile, and onboard.</p>
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
      <form onSubmit={handleSubmit} className="p-3 border-t border-gray-700 bg-gray-800">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="e.g., Onboard customer complaints..."
            disabled={loading}
            className="flex-1 px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm text-white placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="px-3 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
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
              className="px-1.5 py-0.5 text-xs text-gray-400 bg-gray-700 rounded hover:bg-gray-600 hover:text-white"
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
