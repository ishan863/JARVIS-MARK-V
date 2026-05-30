import { motion } from 'framer-motion'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid
} from 'recharts'
import { TrendingUp, TrendingDown, X, DollarSign, BarChart3 } from 'lucide-react'

/* ─── Types ─────────────────────────────────────── */
interface LiveData {
  id: string
  price: number
  change_24h: number
  market_cap: number
  volume_24h: number
  currency: string
}

interface HistoryPoint {
  date: string
  price: number
}

interface CryptoWidgetProps {
  data: {
    coin: string
    name?: string
    currency: string
    live?: LiveData
    history: HistoryPoint[]
    days?: number
  }
  onClose?: () => void
}

/* ─── Helpers ────────────────────────────────────── */
function fmt(n: number, decimals = 2): string {
  if (n === undefined || n === null) return '–'
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`
  if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`
  if (n >= 1e3) return `$${n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`
  if (n < 0.01) return `$${n.toFixed(6)}`
  return `$${n.toFixed(decimals)}`
}

/* ─── Custom Tooltip ─────────────────────────────── */
const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: 'rgba(13,15,26,0.95)',
      border: '1px solid rgba(91,141,238,0.3)',
      borderRadius: 8,
      padding: '8px 12px',
      backdropFilter: 'blur(12px)',
    }}>
      <p style={{ color: '#94a3b8', fontSize: 11, marginBottom: 3 }}>{label}</p>
      <p style={{ color: '#5b8dee', fontWeight: 700, fontSize: 14, fontFamily: 'JetBrains Mono, monospace' }}>
        {fmt(payload[0].value)}
      </p>
    </div>
  )
}

/* ─── CryptoWidget ───────────────────────────────── */
export function CryptoWidget({ data, onClose }: CryptoWidgetProps) {
  const { coin, live, history, days = 7, currency } = data
  const change = live?.change_24h ?? 0
  const isUp = change >= 0
  const color = isUp ? '#34d399' : '#f87171'

  // Normalize history
  const chartData = (history || []).filter(p => typeof p.price === 'number')
  const prices = chartData.map(p => p.price)
  const minPrice = Math.min(...prices) * 0.998
  const maxPrice = Math.max(...prices) * 1.002

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className="crypto-widget"
    >
      {/* Header row */}
      <div className="cw-header">
        <div className="cw-title-group">
          <h2 className="cw-coin-name">{coin?.toUpperCase()}</h2>
          <span className="cw-label">{days}-day chart • {currency}</span>
        </div>

        <div className="cw-price-group">
          <span className="cw-price">{live ? fmt(live.price) : '–'}</span>
          <motion.span
            key={change}
            initial={{ scale: 0.8 }}
            animate={{ scale: 1 }}
            className="cw-change"
            style={{ color, background: isUp ? 'rgba(52,211,153,0.1)' : 'rgba(248,113,113,0.1)' }}
          >
            {isUp ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
            {isUp ? '+' : ''}{change.toFixed(2)}%
          </motion.span>
        </div>

        {onClose && (
          <button onClick={onClose} className="cw-close" aria-label="Close">
            <X size={14} />
          </button>
        )}
      </div>

      {/* Chart */}
      <div className="cw-chart-wrap">
        {chartData.length > 1 ? (
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={chartData} margin={{ top: 10, right: 4, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id={`grad-${coin}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
              <XAxis
                dataKey="date"
                tick={{ fill: '#4b5563', fontSize: 10 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                domain={[minPrice, maxPrice]}
                tick={{ fill: '#4b5563', fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v) => {
                  if (v >= 1000) return `$${(v/1000).toFixed(0)}k`
                  if (v < 0.1) return `$${v.toFixed(4)}`
                  return `$${v.toFixed(1)}`
                }}
                width={55}
              />
              <Tooltip content={<CustomTooltip />} />
              <Area
                type="monotone"
                dataKey="price"
                stroke={color}
                strokeWidth={2}
                fill={`url(#grad-${coin})`}
                dot={false}
                activeDot={{ r: 4, fill: color, stroke: '#0d0f1a', strokeWidth: 2 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="cw-no-data">No chart data available</div>
        )}
      </div>

      {/* Stats row */}
      {live && (
        <div className="cw-stats">
          <StatCard label="Market Cap" value={fmt(live.market_cap)} icon={<BarChart3 size={12} />} />
          <StatCard label="24h Volume" value={fmt(live.volume_24h)} icon={<DollarSign size={12} />} />
          <StatCard label="24h Change" value={`${change >= 0 ? '+' : ''}${change.toFixed(2)}%`}
            icon={isUp ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
            color={color}
          />
        </div>
      )}
    </motion.div>
  )
}

function StatCard({ label, value, icon, color }: { label: string; value: string; icon: React.ReactNode; color?: string }) {
  return (
    <div className="cw-stat">
      <div className="cw-stat-label">
        <span style={{ color: color || '#94a3b8' }}>{icon}</span>
        {label}
      </div>
      <div className="cw-stat-val" style={color ? { color } : {}}>{value}</div>
    </div>
  )
}

/* ─── CryptoTopWidget ────────────────────────────── */
interface CoinData {
  rank: number
  symbol: string
  name: string
  price: number
  change_24h: number
  market_cap: number
  volume: number
  image?: string
}

export function CryptoTopWidget({ data }: { data: CoinData[] }) {
  if (!data?.length) return <div className="cw-no-data">No data</div>

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="cw-top-table"
    >
      <div className="cw-top-header">
        <span>#</span>
        <span>Coin</span>
        <span>Price</span>
        <span>24h %</span>
        <span>Market Cap</span>
        <span>Volume</span>
      </div>
      {data.map((coin, i) => {
        const isUp = coin.change_24h >= 0
        const color = isUp ? '#34d399' : '#f87171'
        return (
          <motion.div
            key={coin.symbol}
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.03 }}
            className="cw-top-row"
          >
            <span className="cw-rank">{coin.rank}</span>
            <div className="cw-coin-info">
              {coin.image && <img src={coin.image} alt={coin.name} className="coin-img" />}
              <div>
                <span className="coin-sym">{coin.symbol}</span>
                <span className="coin-name-sm">{coin.name}</span>
              </div>
            </div>
            <span className="cw-price-sm">{fmt(coin.price)}</span>
            <span className="cw-pct" style={{ color }}>
              {isUp ? '+' : ''}{coin.change_24h.toFixed(2)}%
            </span>
            <span className="cw-mcap">{fmt(coin.market_cap)}</span>
            <span className="cw-vol">{fmt(coin.volume)}</span>
          </motion.div>
        )
      })}
    </motion.div>
  )
}

/* ─── Component CSS (injected as style tag via module) ── */
const styleTag = document.createElement('style')
styleTag.textContent = `
.crypto-widget { padding: 0; }
.cw-header { display:flex; align-items:center; gap:12px; margin-bottom:16px; flex-wrap:wrap; }
.cw-title-group { flex:1; }
.cw-coin-name { font-size:20px; font-weight:700; letter-spacing:0.05em; color:#e2e8f0; }
.cw-label { font-size:11px; color:#4b5563; font-family:'JetBrains Mono',monospace; }
.cw-price-group { display:flex; align-items:center; gap:10px; }
.cw-price { font-size:24px; font-weight:700; color:#e2e8f0; font-family:'JetBrains Mono',monospace; }
.cw-change { display:flex; align-items:center; gap:4px; font-size:12px; font-weight:600; padding:4px 10px; border-radius:6px; font-family:'JetBrains Mono',monospace; }
.cw-close { padding:6px; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.08); border-radius:6px; color:#6b7280; cursor:pointer; display:flex; align-items:center; transition:all 0.15s; }
.cw-close:hover { background:rgba(248,113,113,0.1); color:#f87171; border-color:rgba(248,113,113,0.25); }
.cw-chart-wrap { border-radius:10px; overflow:hidden; background:rgba(0,0,0,0.2); padding:8px 0; margin-bottom:16px; }
.cw-no-data { text-align:center; padding:40px; color:#4b5563; font-size:13px; }
.cw-stats { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
.cw-stat { background:rgba(0,0,0,0.3); border:1px solid rgba(255,255,255,0.06); border-radius:10px; padding:12px; }
.cw-stat-label { display:flex; align-items:center; gap:5px; font-size:10px; color:#6b7280; margin-bottom:6px; text-transform:uppercase; letter-spacing:0.05em; }
.cw-stat-val { font-size:14px; font-weight:700; color:#e2e8f0; font-family:'JetBrains Mono',monospace; }
.cw-top-table { display:flex; flex-direction:column; gap:2px; }
.cw-top-header { display:grid; grid-template-columns:32px 180px 1fr 80px 1fr 1fr; gap:12px; padding:8px 12px; font-size:10px; color:#4b5563; text-transform:uppercase; letter-spacing:0.06em; border-bottom:1px solid rgba(255,255,255,0.06); }
.cw-top-row { display:grid; grid-template-columns:32px 180px 1fr 80px 1fr 1fr; gap:12px; padding:10px 12px; border-radius:8px; transition:background 0.15s; align-items:center; }
.cw-top-row:hover { background:rgba(255,255,255,0.03); }
.cw-rank { color:#4b5563; font-size:12px; font-family:'JetBrains Mono',monospace; }
.cw-coin-info { display:flex; align-items:center; gap:10px; }
.coin-img { width:24px; height:24px; border-radius:50%; }
.coin-sym { display:block; font-size:13px; font-weight:600; color:#e2e8f0; font-family:'JetBrains Mono',monospace; }
.coin-name-sm { display:block; font-size:10px; color:#6b7280; }
.cw-price-sm { font-size:13px; font-weight:600; color:#e2e8f0; font-family:'JetBrains Mono',monospace; }
.cw-pct { font-size:12px; font-weight:600; font-family:'JetBrains Mono',monospace; }
.cw-mcap,.cw-vol { font-size:12px; color:#94a3b8; font-family:'JetBrains Mono',monospace; }
`
if (!document.head.querySelector('#cw-styles')) {
  styleTag.id = 'cw-styles'
  document.head.appendChild(styleTag)
}
