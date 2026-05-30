import { useEffect, useState, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Mic, Terminal, Activity, Brain, Server, Bitcoin,
  CloudSun, BarChart3, Code2, Globe, X, MicOff,
  Wifi, WifiOff, ChevronRight, Zap, Send
} from 'lucide-react'
import './App.css'
import { CryptoWidget, CryptoTopWidget } from './components/CryptoWidget'
import { WeatherWidget } from './components/WeatherWidget'

/* ─── Types ──────────────────────────────────────────────── */
type LogEntry = { id: number; text: string; type: 'log' | 'input' | 'state' | 'system' }
type Widget = { id: string; type: string; data: any }
type NavItem = { icon: typeof Terminal; label: string; id: string }

const NAV_ITEMS: NavItem[] = [
  { icon: Terminal, label: 'Workspace', id: 'workspace' },
  { icon: Activity, label: 'Activity', id: 'activity' },
  { icon: Bitcoin, label: 'Crypto', id: 'crypto' },
  { icon: CloudSun, label: 'Weather', id: 'weather' },
  { icon: Code2, label: 'Dev Agent', id: 'dev' },
  { icon: Globe, label: 'Browser', id: 'browser' },
  { icon: Server, label: 'System', id: 'system' },
]

function App() {
  const [status, setStatus] = useState<'Connected' | 'Disconnected' | 'Reconnecting'>('Disconnected')
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [widgets, setWidgets] = useState<Widget[]>([])
  const [activeNav, setActiveNav] = useState('workspace')
  const [inputText, setInputText] = useState('')
  const [jarvisState, setJarvisState] = useState('OFFLINE')
  const [isMuted, setIsMuted] = useState(false)
  const [textInput, setTextInput] = useState('')
  const wsRef = useRef<WebSocket | null>(null)
  const logEndRef = useRef<HTMLDivElement>(null)
  const logIdRef = useRef(0)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const addLog = useCallback((text: string, type: LogEntry['type'] = 'log') => {
    setLogs(prev => {
      const newLog: LogEntry = { id: ++logIdRef.current, text, type }
      return [...prev.slice(-200), newLog] // keep last 200 lines
    })
  }, [])

  const connectWS = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket('ws://127.0.0.1:8000/ws')
    wsRef.current = ws

    ws.onopen = () => {
      setStatus('Connected')
      addLog('SYS: Backend connected ✓', 'system')
      ws.send(JSON.stringify({ type: 'handshake', data: 'Hello from MARK XL Frontend' }))
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)

        if (msg.type === 'log') {
          addLog(msg.data, 'log')
        } else if (msg.type === 'state') {
          setJarvisState(msg.data)
        } else if (msg.type === 'input') {
          setInputText(msg.data)
        } else if (msg.type === 'widget') {
          handleWidget(msg)
        } else if (msg.event === 'ack') {
          // silent ack
        } else {
          addLog(JSON.stringify(msg), 'log')
        }
      } catch (e) {
        addLog(`RAW: ${event.data}`, 'log')
      }
    }

    ws.onclose = () => {
      setStatus('Disconnected')
      setJarvisState('OFFLINE')
      addLog('SYS: Backend disconnected. Reconnecting...', 'system')
      reconnectTimer.current = setTimeout(connectWS, 3000)
    }

    ws.onerror = () => {
      setStatus('Reconnecting')
    }
  }, [addLog])

  const handleWidget = (msg: any) => {
    const widgetType = msg.widgetType
    setWidgets(prev => {
      const filtered = prev.filter(w => w.id !== widgetType)
      return [...filtered, { id: widgetType, type: widgetType, data: msg }]
    })
    // Auto-navigate to relevant panel
    if (widgetType === 'crypto' || widgetType === 'crypto_top') setActiveNav('crypto')
    if (widgetType === 'weather') setActiveNav('weather')
  }

  useEffect(() => {
    connectWS()
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connectWS])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const sendCommand = () => {
    if (!textInput.trim() || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    wsRef.current.send(JSON.stringify({ type: 'text_command', data: textInput }))
    addLog(`You: ${textInput}`, 'input')
    setTextInput('')
  }

  const requestCrypto = (coin: string) => {
    wsRef.current?.send(JSON.stringify({ type: 'get_crypto', coin, days: 7, currency: 'usd' }))
    addLog(`[Crypto] Fetching ${coin} data...`, 'system')
  }

  const requestWeather = (city: string) => {
    wsRef.current?.send(JSON.stringify({ type: 'get_weather', city }))
    addLog(`[Weather] Fetching weather for ${city}...`, 'system')
  }

  const requestTopCrypto = () => {
    wsRef.current?.send(JSON.stringify({ type: 'get_top_crypto' }))
    addLog('[Crypto] Fetching top coins...', 'system')
  }

  const removeWidget = (id: string) => {
    setWidgets(prev => prev.filter(w => w.id !== id))
  }

  const cryptoWidget = widgets.find(w => w.id === 'crypto')
  const cryptoTopWidget = widgets.find(w => w.id === 'crypto_top')
  const weatherWidget = widgets.find(w => w.id === 'weather')

  const stateColors: Record<string, string> = {
    LISTENING: 'text-green-400',
    SPEAKING: 'text-blue-400',
    THINKING: 'text-yellow-400',
    OFFLINE: 'text-gray-500',
  }
  const stateColor = stateColors[jarvisState] || 'text-gray-400'

  return (
    <div className="app-shell">
      {/* ── Sidebar ── */}
      <motion.aside
        initial={{ x: -100, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        transition={{ type: 'spring', stiffness: 200, damping: 25 }}
        className="sidebar"
      >
        {/* Logo */}
        <div className="sidebar-logo">
          <div className="logo-orb">
            <Brain className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="logo-title">MARK XL</h1>
            <p className="logo-sub">AI Platform</p>
          </div>
        </div>

        {/* Jarvis State */}
        <div className="state-badge">
          <motion.div
            className={`state-dot ${jarvisState === 'LISTENING' ? 'dot-listening' : jarvisState === 'SPEAKING' ? 'dot-speaking' : jarvisState === 'THINKING' ? 'dot-thinking' : 'dot-offline'}`}
            animate={{ scale: jarvisState === 'LISTENING' ? [1, 1.3, 1] : 1 }}
            transition={{ repeat: Infinity, duration: 1.5 }}
          />
          <span className={`state-label ${stateColor}`}>{jarvisState}</span>
        </div>

        {/* Nav */}
        <nav className="sidebar-nav">
          {NAV_ITEMS.map((item) => (
            <motion.button
              key={item.id}
              id={`nav-${item.id}`}
              onClick={() => setActiveNav(item.id)}
              className={`nav-item ${activeNav === item.id ? 'nav-item-active' : ''}`}
              whileHover={{ x: 4 }}
              whileTap={{ scale: 0.97 }}
            >
              <item.icon className="w-4 h-4" />
              <span>{item.label}</span>
              {activeNav === item.id && (
                <motion.div layoutId="nav-indicator" className="nav-indicator" />
              )}
            </motion.button>
          ))}
        </nav>

        {/* Connection status */}
        <div className="sidebar-footer">
          <div className={`conn-badge ${status === 'Connected' ? 'conn-ok' : 'conn-err'}`}>
            {status === 'Connected' ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
            <span>{status}</span>
          </div>
          <button
            id="mute-btn"
            onClick={() => setIsMuted(m => !m)}
            className={`mute-btn ${isMuted ? 'muted' : ''}`}
            title={isMuted ? 'Unmute mic' : 'Mute mic'}
          >
            {isMuted ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
          </button>
        </div>
      </motion.aside>

      {/* ── Main Content ── */}
      <main className="main-content">
        {/* Header */}
        <header className="top-bar">
          <div className="top-bar-left">
            <ChevronRight className="w-4 h-4 text-primary opacity-60" />
            <h2 className="panel-title">
              {NAV_ITEMS.find(n => n.id === activeNav)?.label ?? 'Workspace'}
            </h2>
          </div>
          <div className="top-bar-right">
            <div className="top-bar-status">
              <Zap className="w-3.5 h-3.5 text-yellow-400" />
              <span>Gemini 2.5 Flash</span>
            </div>
          </div>
        </header>

        {/* Live voice input display */}
        <AnimatePresence>
          {inputText && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="voice-input-bar"
            >
              <div className="voice-wave">
                {[...Array(4)].map((_, i) => (
                  <motion.div
                    key={i}
                    className="voice-bar"
                    animate={{ scaleY: [1, 1.8, 1] }}
                    transition={{ repeat: Infinity, duration: 0.6, delay: i * 0.1 }}
                  />
                ))}
              </div>
              <span className="voice-text">{inputText}</span>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Panel Content */}
        <div className="panel-body">
          <AnimatePresence mode="wait">
            {/* ── Workspace ── */}
            {activeNav === 'workspace' && (
              <motion.div key="workspace" className="panel-grid" {...panelAnim}>
                {/* Activity log card */}
                <div className="card col-span-2">
                  <div className="card-header">
                    <Activity className="w-4 h-4 text-primary" />
                    <h3>Activity Feed</h3>
                    <button className="ml-auto text-xs text-gray-500 hover:text-gray-300" onClick={() => setLogs([])}>
                      Clear
                    </button>
                  </div>
                  <div className="log-box">
                    {logs.length === 0 && (
                      <p className="log-empty">Waiting for JARVIS...</p>
                    )}
                    {logs.map(l => (
                      <motion.div
                        key={l.id}
                        initial={{ opacity: 0, x: -8 }}
                        animate={{ opacity: 1, x: 0 }}
                        className={`log-line ${l.type === 'input' ? 'log-input' : l.type === 'system' ? 'log-system' : 'log-default'}`}
                      >
                        {l.text}
                      </motion.div>
                    ))}
                    <div ref={logEndRef} />
                  </div>
                </div>

                {/* Quick actions */}
                <div className="card">
                  <div className="card-header">
                    <Zap className="w-4 h-4 text-yellow-400" />
                    <h3>Quick Actions</h3>
                  </div>
                  <div className="quick-actions">
                    {[
                      { label: 'Bitcoin', action: () => requestCrypto('bitcoin') },
                      { label: 'Ethereum', action: () => requestCrypto('ethereum') },
                      { label: 'Top Coins', action: requestTopCrypto },
                      { label: 'Weather: London', action: () => requestWeather('London') },
                      { label: 'Weather: New York', action: () => requestWeather('New York') },
                    ].map(({ label, action }) => (
                      <button key={label} onClick={action} className="quick-btn">
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              </motion.div>
            )}

            {/* ── Crypto Panel ── */}
            {activeNav === 'crypto' && (
              <motion.div key="crypto" className="panel-grid" {...panelAnim}>
                <div className="card col-span-3">
                  <div className="card-header">
                    <Bitcoin className="w-4 h-4 text-yellow-400" />
                    <h3>Crypto Dashboard</h3>
                    <div className="ml-auto flex gap-2">
                      {['bitcoin','ethereum','solana','dogecoin'].map(c => (
                        <button key={c} onClick={() => requestCrypto(c)} className="crypto-btn">
                          {c.slice(0,3).toUpperCase()}
                        </button>
                      ))}
                    </div>
                  </div>
                  {cryptoWidget ? (
                    <CryptoWidget data={cryptoWidget.data} onClose={() => removeWidget('crypto')} />
                  ) : (
                    <div className="widget-placeholder">
                      <Bitcoin className="w-12 h-12 text-yellow-400/30 mx-auto mb-3" />
                      <p className="text-gray-500">Click a coin button or say <em>"Show me the Bitcoin chart"</em></p>
                    </div>
                  )}
                </div>

                {cryptoTopWidget && (
                  <div className="card col-span-3">
                    <div className="card-header">
                      <BarChart3 className="w-4 h-4 text-primary" />
                      <h3>Top 10 by Market Cap</h3>
                      <button onClick={() => removeWidget('crypto_top')} className="ml-auto text-gray-500 hover:text-white">
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                    <CryptoTopWidget data={cryptoTopWidget.data.data} />
                  </div>
                )}

                {!cryptoWidget && !cryptoTopWidget && (
                  <div className="card col-span-3 flex items-center gap-4">
                    <button onClick={requestTopCrypto} className="quick-btn">
                      Load Top 10 Coins
                    </button>
                  </div>
                )}
              </motion.div>
            )}

            {/* ── Weather Panel ── */}
            {activeNav === 'weather' && (
              <motion.div key="weather" className="panel-grid" {...panelAnim}>
                <div className="card col-span-3">
                  <div className="card-header">
                    <CloudSun className="w-4 h-4 text-sky-400" />
                    <h3>Weather Dashboard</h3>
                    <div className="ml-auto flex gap-2">
                      {['London','New York','Tokyo','Dubai','Mumbai'].map(c => (
                        <button key={c} onClick={() => requestWeather(c)} className="crypto-btn">
                          {c.split(' ')[0]}
                        </button>
                      ))}
                    </div>
                  </div>
                  {weatherWidget ? (
                    <WeatherWidget data={weatherWidget.data} onClose={() => removeWidget('weather')} />
                  ) : (
                    <div className="widget-placeholder">
                      <CloudSun className="w-12 h-12 text-sky-400/30 mx-auto mb-3" />
                      <p className="text-gray-500">Click a city or say <em>"What's the weather in Tokyo?"</em></p>
                    </div>
                  )}
                </div>
              </motion.div>
            )}

            {/* ── Activity Panel ── */}
            {activeNav === 'activity' && (
              <motion.div key="activity" className="panel-grid" {...panelAnim}>
                <div className="card col-span-3">
                  <div className="card-header">
                    <Activity className="w-4 h-4 text-primary" />
                    <h3>Full Activity Log</h3>
                    <button className="ml-auto text-xs text-gray-500 hover:text-gray-300" onClick={() => setLogs([])}>
                      Clear All
                    </button>
                  </div>
                  <div className="log-box log-box-tall">
                    {logs.length === 0 && <p className="log-empty">No activity yet.</p>}
                    {logs.map(l => (
                      <div key={l.id} className={`log-line ${l.type === 'input' ? 'log-input' : l.type === 'system' ? 'log-system' : 'log-default'}`}>
                        {l.text}
                      </div>
                    ))}
                    <div ref={logEndRef} />
                  </div>
                </div>
              </motion.div>
            )}

            {/* ── Dev Agent / Browser / System panels ── */}
            {['dev', 'browser', 'system'].includes(activeNav) && (
              <motion.div key={activeNav} className="panel-grid" {...panelAnim}>
                <div className="card col-span-3">
                  <div className="card-header">
                    {activeNav === 'dev' && <Code2 className="w-4 h-4 text-green-400" />}
                    {activeNav === 'browser' && <Globe className="w-4 h-4 text-blue-400" />}
                    {activeNav === 'system' && <Server className="w-4 h-4 text-gray-400" />}
                    <h3>{NAV_ITEMS.find(n => n.id === activeNav)?.label} Panel</h3>
                  </div>
                  <div className="widget-placeholder">
                    <p className="text-gray-500 text-sm">
                      Use voice or text commands to control this module.
                    </p>
                    <p className="text-gray-600 text-xs mt-2">
                      {activeNav === 'dev' && 'Try: "Write a Python snake game and run it"'}
                      {activeNav === 'browser' && 'Try: "Search for best laptops 2025 and scroll down"'}
                      {activeNav === 'system' && 'Try: "Set volume to 50" or "Open Task Manager"'}
                    </p>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* ── Text Input Bar ── */}
        <div className="input-bar">
          <input
            id="text-command-input"
            type="text"
            value={textInput}
            onChange={e => setTextInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && sendCommand()}
            placeholder="Type a command or question..."
            className="text-input"
          />
          <button
            id="send-btn"
            onClick={sendCommand}
            disabled={!textInput.trim() || status !== 'Connected'}
            className="send-btn"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </main>
    </div>
  )
}

const panelAnim = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
  transition: { duration: 0.2 },
}

export default App
