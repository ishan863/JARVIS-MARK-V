import { motion } from 'framer-motion'
import { X, Droplets, Wind, Eye, Gauge, Thermometer, Sun } from 'lucide-react'

/* ─── Types ─────────────────────────────────────── */
interface CurrentWeather {
  temp: number
  feels_like: number
  humidity: number
  wind_speed: number
  wind_dir: string
  uv: number
  condition: string
  emoji: string
  is_day: number
  cloud_cover?: number
  precip?: number
  pressure?: number
  visibility?: number
  unit?: string
}

interface ForecastDay {
  day: string
  date: string
  high: number
  low: number
  condition: string
  emoji: string
  precip?: number
  sunrise?: string
  sunset?: string
}

interface WeatherWidgetProps {
  data: {
    city: string
    current: CurrentWeather
    forecast: ForecastDay[]
    timestamp?: string
  }
  onClose?: () => void
}

/* ─── UV Index helper ────────────────────────────── */
function uvLevel(uv: number): { label: string; color: string } {
  if (uv <= 2) return { label: 'Low', color: '#34d399' }
  if (uv <= 5) return { label: 'Moderate', color: '#fbbf24' }
  if (uv <= 7) return { label: 'High', color: '#f97316' }
  if (uv <= 10) return { label: 'Very High', color: '#f87171' }
  return { label: 'Extreme', color: '#a78bfa' }
}

/* ─── WeatherWidget ──────────────────────────────── */
export function WeatherWidget({ data, onClose }: WeatherWidgetProps) {
  if (!data?.current) return null

  const { city, current, forecast } = data
  const unit = current.unit ?? '°C'
  const uv = uvLevel(current.uv ?? 0)
  const isDay = current.is_day !== 0

  const bgGradient = isDay
    ? 'linear-gradient(135deg, rgba(56,189,248,0.08), rgba(14,165,233,0.04))'
    : 'linear-gradient(135deg, rgba(91,141,238,0.06), rgba(167,139,250,0.04))'

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className="weather-widget"
      style={{ background: bgGradient }}
    >
      {/* Close */}
      {onClose && (
        <button onClick={onClose} className="ww-close" aria-label="Close">
          <X size={14} />
        </button>
      )}

      {/* Header */}
      <div className="ww-header">
        <motion.div
          className="ww-emoji"
          animate={{ rotate: isDay ? [0, 5, 0] : 0, scale: [1, 1.05, 1] }}
          transition={{ repeat: Infinity, duration: 4, ease: 'easeInOut' }}
        >
          {current.emoji}
        </motion.div>

        <div className="ww-main-info">
          <div className="ww-city">{city}</div>
          <div className="ww-condition">{current.condition}</div>
        </div>

        <div className="ww-temp-group">
          <motion.div
            className="ww-temp"
            key={current.temp}
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
          >
            {current.temp}{unit}
          </motion.div>
          <div className="ww-feels">
            Feels like {current.feels_like}{unit}
          </div>
        </div>
      </div>

      {/* Stats grid */}
      <div className="ww-stats">
        <WeatherStat icon={<Droplets size={14} />} label="Humidity" value={`${current.humidity}%`} color="#38bdf8" />
        <WeatherStat icon={<Wind size={14} />} label="Wind" value={`${current.wind_speed} km/h ${current.wind_dir}`} color="#94a3b8" />
        <WeatherStat icon={<Eye size={14} />} label="Visibility" value={`${current.visibility ?? '–'} km`} color="#a78bfa" />
        <WeatherStat icon={<Gauge size={14} />} label="Pressure" value={`${current.pressure ?? '–'} hPa`} color="#fbbf24" />
        <WeatherStat
          icon={<Sun size={14} />}
          label={`UV — ${uv.label}`}
          value={`${current.uv ?? 0}`}
          color={uv.color}
        />
        <WeatherStat icon={<Thermometer size={14} />} label="Precip." value={`${current.precip ?? 0} mm`} color="#6ee7b7" />
      </div>

      {/* 7-day forecast */}
      {forecast && forecast.length > 0 && (
        <div className="ww-forecast-section">
          <div className="ww-forecast-title">7-Day Forecast</div>
          <div className="ww-forecast-row">
            {forecast.slice(0, 7).map((day, i) => (
              <motion.div
                key={day.date}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                className={`ww-day ${i === 0 ? 'ww-day-today' : ''}`}
              >
                <div className="ww-day-name">{i === 0 ? 'Today' : day.day}</div>
                <div className="ww-day-emoji" title={day.condition}>{day.emoji}</div>
                <div className="ww-day-temps">
                  <span className="ww-day-high">{day.high}°</span>
                  <span className="ww-day-low">{day.low}°</span>
                </div>
                {day.precip !== undefined && day.precip > 0 && (
                  <div className="ww-day-precip">
                    <Droplets size={9} style={{ color: '#38bdf8' }} />
                    {day.precip}mm
                  </div>
                )}
              </motion.div>
            ))}
          </div>
        </div>
      )}

      {/* Sunrise / Sunset */}
      {forecast?.[0]?.sunrise && (
        <div className="ww-sun-row">
          <div className="ww-sun-item">
            <span className="ww-sun-icon">🌅</span>
            <span className="ww-sun-label">Sunrise</span>
            <span className="ww-sun-time">{forecast[0].sunrise}</span>
          </div>
          <div className="ww-sun-divider" />
          <div className="ww-sun-item">
            <span className="ww-sun-icon">🌇</span>
            <span className="ww-sun-label">Sunset</span>
            <span className="ww-sun-time">{forecast[0].sunset}</span>
          </div>
        </div>
      )}
    </motion.div>
  )
}

function WeatherStat({
  icon, label, value, color
}: { icon: React.ReactNode; label: string; value: string; color: string }) {
  return (
    <div className="ww-stat">
      <div className="ww-stat-icon" style={{ color }}>{icon}</div>
      <div className="ww-stat-content">
        <div className="ww-stat-label">{label}</div>
        <div className="ww-stat-val">{value}</div>
      </div>
    </div>
  )
}

/* ─── Inject styles ─────────────────────────────── */
const styleTag = document.createElement('style')
styleTag.id = 'ww-styles'
styleTag.textContent = `
.weather-widget { position:relative; padding:0; border-radius:12px; }
.ww-close { position:absolute; top:0; right:0; padding:6px; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.08); border-radius:6px; color:#6b7280; cursor:pointer; display:flex; align-items:center; transition:all 0.15s; z-index:2; }
.ww-close:hover { background:rgba(248,113,113,0.1); color:#f87171; border-color:rgba(248,113,113,0.25); }
.ww-header { display:flex; align-items:center; gap:16px; padding:16px; background:rgba(0,0,0,0.2); border-radius:12px; margin-bottom:16px; border:1px solid rgba(255,255,255,0.06); }
.ww-emoji { font-size:52px; line-height:1; flex-shrink:0; filter:drop-shadow(0 4px 12px rgba(0,0,0,0.3)); }
.ww-main-info { flex:1; }
.ww-city { font-size:18px; font-weight:700; color:#e2e8f0; }
.ww-condition { font-size:13px; color:#94a3b8; margin-top:2px; }
.ww-temp-group { text-align:right; }
.ww-temp { font-size:42px; font-weight:700; color:#e2e8f0; font-family:'JetBrains Mono',monospace; line-height:1; }
.ww-feels { font-size:12px; color:#6b7280; margin-top:4px; }
.ww-stats { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-bottom:16px; }
.ww-stat { background:rgba(0,0,0,0.25); border:1px solid rgba(255,255,255,0.06); border-radius:10px; padding:10px 12px; display:flex; align-items:center; gap:10px; transition:border-color 0.15s; }
.ww-stat:hover { border-color:rgba(255,255,255,0.1); }
.ww-stat-icon { flex-shrink:0; }
.ww-stat-content { min-width:0; }
.ww-stat-label { font-size:10px; color:#6b7280; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ww-stat-val { font-size:13px; font-weight:600; color:#e2e8f0; font-family:'JetBrains Mono',monospace; white-space:nowrap; }
.ww-forecast-section { margin-bottom:12px; }
.ww-forecast-title { font-size:10px; text-transform:uppercase; letter-spacing:0.08em; color:#4b5563; margin-bottom:10px; padding-left:2px; }
.ww-forecast-row { display:grid; grid-template-columns:repeat(7,1fr); gap:6px; }
.ww-day { background:rgba(0,0,0,0.25); border:1px solid rgba(255,255,255,0.06); border-radius:10px; padding:10px 6px; display:flex; flex-direction:column; align-items:center; gap:6px; text-align:center; transition:all 0.15s; cursor:default; }
.ww-day:hover { border-color:rgba(56,189,248,0.25); background:rgba(56,189,248,0.05); }
.ww-day-today { border-color:rgba(56,189,248,0.3); background:rgba(56,189,248,0.08); }
.ww-day-name { font-size:10px; font-weight:600; color:#94a3b8; }
.ww-day-emoji { font-size:20px; line-height:1; }
.ww-day-temps { display:flex; flex-direction:column; gap:1px; }
.ww-day-high { font-size:13px; font-weight:700; color:#e2e8f0; font-family:'JetBrains Mono',monospace; }
.ww-day-low  { font-size:11px; color:#6b7280; font-family:'JetBrains Mono',monospace; }
.ww-day-precip { display:flex; align-items:center; gap:2px; font-size:9px; color:#38bdf8; font-family:'JetBrains Mono',monospace; }
.ww-sun-row { display:flex; align-items:center; background:rgba(0,0,0,0.2); border-radius:10px; border:1px solid rgba(255,255,255,0.06); overflow:hidden; }
.ww-sun-item { flex:1; display:flex; align-items:center; gap:8px; padding:10px 16px; }
.ww-sun-divider { width:1px; height:32px; background:rgba(255,255,255,0.08); }
.ww-sun-icon { font-size:18px; }
.ww-sun-label { font-size:10px; text-transform:uppercase; letter-spacing:0.06em; color:#6b7280; }
.ww-sun-time { font-size:14px; font-weight:600; color:#fbbf24; font-family:'JetBrains Mono',monospace; margin-left:auto; }
`
if (!document.head.querySelector('#ww-styles')) {
  document.head.appendChild(styleTag)
}
