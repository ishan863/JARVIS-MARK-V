"""
crypto_data.py — MARK XL Crypto Data Module
Fetches live prices, OHLC history, and market data from CoinGecko.
Pushes widget data to the React frontend via WebSocket broadcast.
"""

import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path


COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Map common names/symbols to CoinGecko IDs
COIN_ID_MAP = {
    "bitcoin": "bitcoin", "btc": "bitcoin",
    "ethereum": "ethereum", "eth": "ethereum",
    "solana": "solana", "sol": "solana",
    "cardano": "cardano", "ada": "cardano",
    "dogecoin": "dogecoin", "doge": "dogecoin",
    "xrp": "ripple", "ripple": "ripple",
    "bnb": "binancecoin", "binance": "binancecoin",
    "polkadot": "polkadot", "dot": "polkadot",
    "polygon": "matic-network", "matic": "matic-network",
    "shiba": "shiba-inu", "shib": "shiba-inu",
    "avalanche": "avalanche-2", "avax": "avalanche-2",
    "chainlink": "chainlink", "link": "chainlink",
    "litecoin": "litecoin", "ltc": "litecoin",
    "uniswap": "uniswap", "uni": "uniswap",
    "pepe": "pepe", "floki": "floki",
}

TOP_COINS = [
    "bitcoin", "ethereum", "binancecoin", "solana", "ripple",
    "cardano", "dogecoin", "avalanche-2", "polkadot", "chainlink"
]


def _fetch_json(url: str, timeout: int = 10) -> dict | list:
    """Fetch JSON from a URL with error handling."""
    req = urllib.request.Request(url, headers={"User-Agent": "MARKXL-Assistant/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _resolve_coin_id(name: str) -> str:
    """Resolve user-provided coin name/symbol to CoinGecko ID."""
    clean = name.strip().lower()
    return COIN_ID_MAP.get(clean, clean)


def get_live_price(coin_id: str, vs_currency: str = "usd") -> dict:
    """Get current price, 24h change, market cap, volume for a coin."""
    url = (f"{COINGECKO_BASE}/simple/price"
           f"?ids={coin_id}"
           f"&vs_currencies={vs_currency}"
           f"&include_market_cap=true"
           f"&include_24hr_vol=true"
           f"&include_24hr_change=true"
           f"&include_last_updated_at=true")
    try:
        data = _fetch_json(url)
        if coin_id not in data:
            return {"error": f"Coin '{coin_id}' not found on CoinGecko."}
        d = data[coin_id]
        return {
            "id": coin_id,
            "price": d.get(vs_currency, 0),
            "change_24h": round(d.get(f"{vs_currency}_24h_change", 0), 2),
            "market_cap": d.get(f"{vs_currency}_market_cap", 0),
            "volume_24h": d.get(f"{vs_currency}_24h_vol", 0),
            "last_updated": d.get("last_updated_at", 0),
            "currency": vs_currency.upper(),
        }
    except Exception as e:
        return {"error": str(e)}


def get_price_history(coin_id: str, days: int = 7, vs_currency: str = "usd") -> list[dict]:
    """Get OHLC/price history for chart rendering."""
    # Use market_chart for granular data
    url = (f"{COINGECKO_BASE}/coins/{coin_id}/market_chart"
           f"?vs_currency={vs_currency}&days={days}&interval=daily")
    try:
        data = _fetch_json(url)
        prices = data.get("prices", [])
        # Format for recharts: [{date, price}, ...]
        result = []
        for ts, price in prices:
            dt = datetime.utcfromtimestamp(ts / 1000)
            result.append({
                "date": dt.strftime("%b %d"),
                "price": round(price, 2),
                "timestamp": ts,
            })
        return result
    except Exception as e:
        return [{"error": str(e)}]


def get_top_coins(limit: int = 10, vs_currency: str = "usd") -> list[dict]:
    """Get top coins by market cap."""
    url = (f"{COINGECKO_BASE}/coins/markets"
           f"?vs_currency={vs_currency}"
           f"&order=market_cap_desc"
           f"&per_page={limit}"
           f"&page=1"
           f"&sparkline=false"
           f"&price_change_percentage=24h")
    try:
        data = _fetch_json(url)
        return [
            {
                "id": c["id"],
                "symbol": c["symbol"].upper(),
                "name": c["name"],
                "price": c["current_price"],
                "change_24h": round(c.get("price_change_percentage_24h", 0) or 0, 2),
                "market_cap": c["market_cap"],
                "volume": c["total_volume"],
                "image": c["image"],
                "rank": c["market_cap_rank"],
            }
            for c in data
        ]
    except Exception as e:
        return [{"error": str(e)}]


def crypto_data(parameters: dict, player=None, speak=None, broadcast=None) -> str:
    """
    Main action handler for crypto data requests.
    
    parameters:
      - coin: str (e.g., "bitcoin", "eth")  
      - action: str ("price" | "chart" | "top" | "all")
      - days: int (for chart, default 7)
      - currency: str (default "usd")
    """
    coin_name = parameters.get("coin", "bitcoin").strip()
    action = parameters.get("action", "all").lower().strip()
    days = int(parameters.get("days", 7))
    currency = parameters.get("currency", "usd").lower()

    coin_id = _resolve_coin_id(coin_name)

    def _log(msg):
        print(f"[Crypto] {msg}")
        if player:
            try:
                player.write_log(f"[Crypto] {msg}")
            except Exception:
                pass

    _log(f"Fetching {action} for {coin_id} ({currency})")

    result_text = ""
    widget_data = None

    if action in ("price", "all"):
        price_data = get_live_price(coin_id, currency)
        if "error" in price_data:
            result_text = f"Could not fetch price for {coin_name}: {price_data['error']}"
        else:
            p = price_data["price"]
            chg = price_data["change_24h"]
            direction = "up" if chg >= 0 else "down"
            result_text = (
                f"{coin_id.title()} is at ${p:,.2f} {currency.upper()}, "
                f"{direction} {abs(chg):.2f}% in the last 24 hours."
            )

    chart_points = []
    if action in ("chart", "all"):
        chart_points = get_price_history(coin_id, days, currency)

    if action == "top":
        top = get_top_coins(10, currency)
        if top and "error" not in top[0]:
            lines = [f"Top {len(top)} cryptos by market cap:"]
            for c in top:
                chg = c["change_24h"]
                sign = "+" if chg >= 0 else ""
                lines.append(f"  #{c['rank']} {c['name']} ({c['symbol']}): ${c['price']:,.4f} ({sign}{chg:.1f}%)")
            result_text = "\n".join(lines)
            widget_data = {
                "type": "widget",
                "widgetType": "crypto_top",
                "data": top,
                "coin": coin_id,
                "currency": currency.upper(),
                "timestamp": datetime.utcnow().isoformat(),
            }
        else:
            result_text = "Failed to fetch top coins."

    # Build widget payload for "all" or "chart"
    if action in ("chart", "all") and chart_points and "error" not in chart_points[0]:
        live = get_live_price(coin_id, currency) if action == "chart" else price_data
        widget_data = {
            "type": "widget",
            "widgetType": "crypto",
            "coin": coin_id,
            "name": coin_name.title(),
            "currency": currency.upper(),
            "live": live,
            "history": chart_points,
            "days": days,
            "timestamp": datetime.utcnow().isoformat(),
        }

    # Broadcast to frontend if broadcast callback provided
    if widget_data and broadcast:
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(broadcast(widget_data))
                )
        except Exception as e:
            _log(f"Broadcast error: {e}")

    _log(result_text)
    return result_text or f"Crypto data for {coin_name} fetched successfully."
