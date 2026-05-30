import asyncio
import json
import logging
from typing import Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

# Phase 3: Observability Setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("MARK_XL")

app = FastAPI(title="MARK XL API")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global error: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"message": "Internal Server Error", "details": str(exc)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)
        for conn in dead_connections:
            self.disconnect(conn)


# Initialize manager BEFORE importing assistant (which needs it)
manager = ConnectionManager()

from core.assistant import HeadlessUI, AssistantLive
from core.orchestrator import register_actions

headless_ui = HeadlessUI(manager)
assistant_task = None


@app.on_event("startup")
async def startup_event():
    global assistant_task
    register_actions()
    logger.info("Orchestrator initialized. All tools registered.")
    logger.info("Starting MARK XL Headless Assistant Engine...")
    assistant = AssistantLive(headless_ui)
    assistant_task = asyncio.create_task(assistant.run())


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "MARK XL 2.0",
        "connections": len(manager.active_connections),
    }


# --- Workflow Persistence ---
workflows_db = {}

@app.post("/api/workflows")
async def save_workflow(workflow_data: dict):
    wid = str(len(workflows_db) + 1)
    workflows_db[wid] = workflow_data
    return {"id": wid, "status": "saved"}

@app.get("/api/workflows")
async def list_workflows():
    return {"workflows": workflows_db}


# --- Crypto Endpoint ---
@app.get("/api/crypto/{coin}")
async def get_crypto(coin: str, days: int = 7, currency: str = "usd"):
    """Fetch crypto price and history directly via API."""
    try:
        from actions.crypto_data import get_live_price, get_price_history
        price = get_live_price(coin, currency)
        history = get_price_history(coin, days, currency)
        return {"coin": coin, "live": price, "history": history}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# --- Weather Endpoint ---
@app.get("/api/weather/{city}")
async def get_weather(city: str):
    """Fetch weather data directly via API."""
    try:
        from actions.weather_report import weather_action
        result = weather_action({"city": city})
        return {"city": city, "summary": result}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# --- Top Crypto List ---
@app.get("/api/crypto/top/list")
async def get_top_crypto(limit: int = 10, currency: str = "usd"):
    try:
        from actions.crypto_data import get_top_coins
        return {"coins": get_top_coins(limit, currency)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# --- WebSocket Handler ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"event": "error", "data": "Invalid JSON"})
                continue

            msg_type = message.get("type", "")

            # Text command → send to assistant
            if msg_type == "text_command" and headless_ui.on_text_command:
                headless_ui.on_text_command(message.get("data", ""))
                await websocket.send_json({"event": "ack", "data": "Command received"})

            # Crypto widget request
            elif msg_type == "get_crypto":
                from actions.crypto_data import get_live_price, get_price_history, get_top_coins
                coin = message.get("coin", "bitcoin")
                days = message.get("days", 7)
                currency = message.get("currency", "usd")
                live = get_live_price(coin, currency)
                history = get_price_history(coin, days, currency)
                await websocket.send_json({
                    "type": "widget",
                    "widgetType": "crypto",
                    "coin": coin,
                    "live": live,
                    "history": history,
                    "currency": currency.upper(),
                })

            # Weather widget request
            elif msg_type == "get_weather":
                from actions.weather_report import _geocode, _fetch_weather, WMO_CODES, _wind_direction
                from datetime import datetime
                city = message.get("city", "London")
                try:
                    lat, lon, display_name = _geocode(city)
                    raw = _fetch_weather(lat, lon)
                    current = raw.get("current", {})
                    daily = raw.get("daily", {})
                    wcode = current.get("weather_code", 0)
                    condition, emoji = WMO_CODES.get(wcode, ("Unknown", "❓"))
                    forecast = []
                    for i, date in enumerate(daily.get("time", [])):
                        code = daily.get("weather_code", [])[i] if i < len(daily.get("weather_code", [])) else 0
                        cond, emo = WMO_CODES.get(code, ("Unknown", "❓"))
                        dt = datetime.strptime(date, "%Y-%m-%d")
                        forecast.append({
                            "day": dt.strftime("%a"),
                            "date": dt.strftime("%b %d"),
                            "high": daily.get("temperature_2m_max", [])[i] if i < len(daily.get("temperature_2m_max", [])) else "?",
                            "low": daily.get("temperature_2m_min", [])[i] if i < len(daily.get("temperature_2m_min", [])) else "?",
                            "condition": cond,
                            "emoji": emo,
                        })
                    await websocket.send_json({
                        "type": "widget",
                        "widgetType": "weather",
                        "city": display_name,
                        "current": {
                            "temp": current.get("temperature_2m"),
                            "feels_like": current.get("apparent_temperature"),
                            "humidity": current.get("relative_humidity_2m"),
                            "wind_speed": current.get("wind_speed_10m"),
                            "wind_dir": _wind_direction(current.get("wind_direction_10m", 0)),
                            "uv": current.get("uv_index", 0),
                            "condition": condition,
                            "emoji": emoji,
                            "is_day": current.get("is_day", 1),
                        },
                        "forecast": forecast,
                    })
                except Exception as e:
                    await websocket.send_json({"event": "error", "data": str(e)})

            # Top crypto list request
            elif msg_type == "get_top_crypto":
                from actions.crypto_data import get_top_coins
                top = get_top_coins(10, "usd")
                await websocket.send_json({
                    "type": "widget",
                    "widgetType": "crypto_top",
                    "data": top,
                })

            else:
                await manager.broadcast({"event": "ack", "data": message})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        manager.disconnect(websocket)
        logger.error(f"WebSocket error: {e}")


if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
