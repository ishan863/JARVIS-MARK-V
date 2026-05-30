"""
weather_report.py — MARK XL Weather Module (upgraded)
Fetches real weather data from Open-Meteo (free, no key needed)
and pushes a rich widget payload to the React frontend via WebSocket.
"""

import json
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path


GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

WMO_CODES = {
    0: ("Clear Sky", "☀️"),
    1: ("Mainly Clear", "🌤️"),
    2: ("Partly Cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Foggy", "🌫️"),
    48: ("Icy Fog", "🌫️"),
    51: ("Light Drizzle", "🌦️"),
    53: ("Moderate Drizzle", "🌦️"),
    55: ("Dense Drizzle", "🌧️"),
    61: ("Slight Rain", "🌧️"),
    63: ("Moderate Rain", "🌧️"),
    65: ("Heavy Rain", "🌧️"),
    71: ("Slight Snow", "🌨️"),
    73: ("Moderate Snow", "❄️"),
    75: ("Heavy Snow", "❄️"),
    77: ("Snow Grains", "🌨️"),
    80: ("Light Showers", "🌦️"),
    81: ("Moderate Showers", "🌧️"),
    82: ("Violent Showers", "⛈️"),
    85: ("Slight Snow Showers", "🌨️"),
    86: ("Heavy Snow Showers", "❄️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm w/ Hail", "⛈️"),
    99: ("Thunderstorm w/ Heavy Hail", "⛈️"),
}


def _fetch_json(url: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "MARKXL-Assistant/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _geocode(city: str) -> tuple[float, float, str]:
    """Get (lat, lon, display_name) for a city name."""
    params = urllib.parse.urlencode({"name": city, "count": 1, "language": "en", "format": "json"})
    data = _fetch_json(f"{GEOCODE_URL}?{params}")
    results = data.get("results", [])
    if not results:
        raise ValueError(f"City '{city}' not found.")
    r = results[0]
    return r["latitude"], r["longitude"], f"{r['name']}, {r.get('country', '')}"


def _fetch_weather(lat: float, lon: float) -> dict:
    """Fetch detailed weather data from Open-Meteo."""
    params = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "current": ",".join([
            "temperature_2m", "apparent_temperature", "relative_humidity_2m",
            "precipitation", "weather_code", "wind_speed_10m", "wind_direction_10m",
            "uv_index", "is_day", "cloud_cover", "pressure_msl", "visibility"
        ]),
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,uv_index_max,sunrise,sunset",
        "timezone": "auto",
        "forecast_days": 7,
    })
    return _fetch_json(f"{WEATHER_URL}?{params}")


def _wind_direction(degrees: float) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(degrees / 45) % 8]


def weather_action(parameters: dict, player=None, speak=None, broadcast=None) -> str:
    """
    Main action handler for weather requests.
    
    parameters:
      - city: str (required)
      - time: str (optional, ignored — always live)
    """
    city = (parameters.get("city") or "").strip()
    if not city:
        return "Sir, please specify a city for the weather report."

    def _log(msg):
        print(f"[Weather] {msg}")
        if player:
            try:
                player.write_log(f"[Weather] {msg}")
            except Exception:
                pass

    try:
        # 1. Geocode
        lat, lon, display_name = _geocode(city)
        _log(f"Geocoded: {display_name} ({lat}, {lon})")

        # 2. Fetch weather
        raw = _fetch_weather(lat, lon)
        current = raw.get("current", {})
        daily = raw.get("daily", {})
        hourly = raw.get("hourly", {})

        # Parse current
        temp = current.get("temperature_2m", "?")
        feels_like = current.get("apparent_temperature", "?")
        humidity = current.get("relative_humidity_2m", "?")
        wind_speed = current.get("wind_speed_10m", "?")
        wind_dir = _wind_direction(current.get("wind_direction_10m", 0))
        uv = current.get("uv_index", 0)
        wcode = current.get("weather_code", 0)
        condition, emoji = WMO_CODES.get(wcode, ("Unknown", "❓"))
        is_day = current.get("is_day", 1)
        cloud = current.get("cloud_cover", 0)
        precip = current.get("precipitation", 0)
        pressure = current.get("pressure_msl", 0)
        visibility = current.get("visibility", 0)

        # Parse 7-day forecast
        forecast = []
        dates = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        daily_codes = daily.get("weather_code", [])
        precip_sums = daily.get("precipitation_sum", [])
        sunrises = daily.get("sunrise", [])
        sunsets = daily.get("sunset", [])

        for i, date in enumerate(dates):
            code = daily_codes[i] if i < len(daily_codes) else 0
            cond, emo = WMO_CODES.get(code, ("Unknown", "❓"))
            dt = datetime.strptime(date, "%Y-%m-%d")
            forecast.append({
                "day": dt.strftime("%a"),
                "date": dt.strftime("%b %d"),
                "high": max_temps[i] if i < len(max_temps) else "?",
                "low": min_temps[i] if i < len(min_temps) else "?",
                "condition": cond,
                "emoji": emo,
                "precip": precip_sums[i] if i < len(precip_sums) else 0,
                "sunrise": sunrises[i].split("T")[-1][:5] if i < len(sunrises) else "",
                "sunset": sunsets[i].split("T")[-1][:5] if i < len(sunsets) else "",
            })

        # Build widget payload
        widget_data = {
            "type": "widget",
            "widgetType": "weather",
            "city": display_name,
            "current": {
                "temp": temp,
                "feels_like": feels_like,
                "humidity": humidity,
                "wind_speed": wind_speed,
                "wind_dir": wind_dir,
                "uv": uv,
                "condition": condition,
                "emoji": emoji,
                "is_day": is_day,
                "cloud_cover": cloud,
                "precip": precip,
                "pressure": pressure,
                "visibility": round(visibility / 1000, 1),  # km
                "unit": "°C",
            },
            "forecast": forecast,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Broadcast to React frontend
        if broadcast:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.call_soon_threadsafe(
                        lambda: asyncio.ensure_future(broadcast(widget_data))
                    )
            except Exception as e:
                _log(f"Broadcast error: {e}")

        result = (
            f"{emoji} {display_name}: {temp}°C, {condition}. "
            f"Feels like {feels_like}°C. Humidity: {humidity}%, Wind: {wind_speed} km/h {wind_dir}. "
            f"UV Index: {uv}. {forecast[0]['day']} high/low: {max_temps[0]}/{min_temps[0]}°C."
        )
        _log(result)
        return result

    except ValueError as e:
        msg = f"Sir, {e}"
        _log(msg)
        return msg
    except Exception as e:
        msg = f"Sir, I couldn't fetch the weather data: {e}"
        _log(msg)
        return msg
