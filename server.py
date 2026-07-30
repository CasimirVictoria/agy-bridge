#!/usr/bin/env python3
"""
Antigravity Master Hub Bridge Server (server.py)
Clean, lightweight FastAPI + WebSocket server capturing tmux brain:0.0 session.

- Clean modern glassmorphism web UI (full width, no sidebars)
- Robust response extraction algorithm from tmux pane
- Direct image paste support and Markdown formatting
"""

import os
import sys
import json
import asyncio
import base64
import subprocess
from typing import List, Optional
from datetime import datetime, timedelta

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="Antigravity Master Hub", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

USER_HOME = os.path.expanduser("~")
CONV_FILE = os.path.join(USER_HOME, ".gemini/antigravity-cli/bridge/conversations.json")
UPLOAD_DIR = os.path.join(USER_HOME, ".gemini/antigravity-cli/brain/52a230fd-4cc6-4e23-9da2-545421935271/.user_uploaded")

DEFAULT_CHATS = {
    "default": "🌐 Xat General (Tots)",
    "salut": "🩺 Salut i Suplements",
    "tfm": "🔬 TFM i Ciència",
    "gestio": "📧 Gestions i Correus"
}

def load_conversations() -> dict:
    data = {"active_id": "default", "chats": {}}
    if os.path.exists(CONV_FILE):
        try:
            with open(CONV_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error loading conversations: {e}")
            
    if "chats" not in data or not isinstance(data["chats"], dict):
        data["chats"] = {}
    if "active_id" not in data:
        data["active_id"] = "default"

    # Ensure all default thematic chats exist
    for cid, ctitle in DEFAULT_CHATS.items():
        if cid not in data["chats"]:
            data["chats"][cid] = {
                "id": cid,
                "title": ctitle,
                "created_at": datetime.now().strftime("%d/%m %H:%M"),
                "messages": []
            }
    return data

def save_conversations(data: dict):
    try:
        os.makedirs(os.path.dirname(CONV_FILE), exist_ok=True)
        with open(CONV_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving conversations: {e}")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()

TRANSCRIPT_PATH = os.path.join(USER_HOME, ".gemini/antigravity-cli/brain/52a230fd-4cc6-4e23-9da2-545421935271/.system_generated/logs/transcript.jsonl")

def get_latest_ai_response_from_transcript() -> Optional[str]:
    """Extract raw markdown response directly from transcript log."""
    if not os.path.exists(TRANSCRIPT_PATH):
        return None
    try:
        with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in reversed(lines):
            line_str = line.strip()
            if not line_str:
                continue
            data = json.loads(line_str)
            if data.get("type") == "PLANNER_RESPONSE" and data.get("content"):
                return data.get("content").strip()
    except Exception as e:
        print(f"Error reading transcript: {e}")
    return None

async def process_ai_response(prompt: str):
    """Send prompt to tmux session and set status to thinking."""
    try:
        await manager.broadcast({"type": "ai_status", "status": "thinking"})

        # Escape special shell characters and send to tmux pane
        safe_prompt = prompt.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
        cmd = f'tmux send-keys -t brain:0.0 "{safe_prompt}" Enter'
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
    except Exception as e:
        print(f"Error sending prompt to tmux: {e}")
        await manager.broadcast({"type": "ai_status", "status": "idle"})

last_broadcast_content = ""

async def watch_transcript_loop():
    """Background task: Single Source of Truth for broadcasting AI responses from transcript.jsonl."""
    global last_broadcast_content
    while True:
        try:
            await asyncio.sleep(1.0)
            candidate = get_latest_ai_response_from_transcript()
            if candidate and candidate != last_broadcast_content:
                last_broadcast_content = candidate
                convs = load_conversations()
                act_id = convs.get("active_id", "default")
                ts_now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                ai_msg = {
                    "sender": "⚡ Antigravity AI",
                    "text": candidate,
                    "timestamp": ts_now
                }
                if act_id in convs["chats"]:
                    msgs = convs["chats"][act_id]["messages"]
                    if not msgs or msgs[-1].get("text") != candidate:
                        msgs.append(ai_msg)
                if act_id != "default" and "default" in convs["chats"]:
                    def_msgs = convs["chats"]["default"]["messages"]
                    if not def_msgs or def_msgs[-1].get("text") != candidate:
                        def_msgs.append(ai_msg)
                save_conversations(convs)

                await manager.broadcast({"type": "ai_status", "status": "idle"})
                await manager.broadcast({
                    "type": "chat_message",
                    "sender": "⚡ Antigravity AI",
                    "text": candidate,
                    "timestamp": ts_now,
                    "chat_id": act_id
                })
        except Exception as e:
            pass

@app.on_event("startup")
def start_background_watcher():
    asyncio.create_task(watch_transcript_loop())

# --- Image Upload Endpoint ---
class ImageUploadRequest(BaseModel):
    image_base64: str
    filename: Optional[str] = "pasted_image.png"

@app.post("/api/upload_image")
def upload_image(req: ImageUploadRequest):
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        b64_data = req.image_base64
        if "," in b64_data:
            b64_data = b64_data.split(",")[1]
            
        timestamp = int(datetime.now().timestamp() * 1000)
        filepath = os.path.join(UPLOAD_DIR, f"uploaded_media_{timestamp}.png")
        
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(b64_data))
            
        return {"status": "success", "filepath": filepath}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Conversations Endpoints ---
@app.get("/api/antigravity/status")
def get_antigravity_status():
    """Retrieve runtime model quota, context size, and session status."""
    active_model = "Gemini 3.6 Flash (High)"
    try:
        res = subprocess.run(["tmux", "capture-pane", "-pt", "brain:0.0"], capture_output=True, text=True)
        pane_lines = res.stdout.splitlines()
        for l in reversed(pane_lines):
            if any(m in l for m in ["Gemini", "Claude", "GPT", "Flash", "Pro", "Opus"]):
                parts = l.strip().split()
                if len(parts) >= 2:
                    active_model = " ".join(parts[-4:])
                break
    except Exception:
        pass

    # Calculate active context window from last 100 conversation steps
    active_tokens = 245000
    if os.path.exists(TRANSCRIPT_PATH):
        try:
            with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
            recent_lines = lines[-120:] if len(lines) > 120 else lines
            sample_text = "".join(recent_lines)
            active_tokens = int(len(sample_text) / 3.2)
        except Exception:
            pass

    max_context_tokens = 1000000
    used_pct = round(min(100.0, (active_tokens / max_context_tokens) * 100), 1)
    rem_pct = round(max(0.0, 100.0 - used_pct), 1)

    now = datetime.now()
    next_reset = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).strftime("%H:00:00")

    return {
        "active_model": active_model,
        "session_id": "52a230fd-4cc6-4e23-9da2-545421935271",
        "context_max_tokens": "1.000.000",
        "estimated_tokens_used": f"{active_tokens:,}",
        "used_pct": used_pct,
        "rem_pct": rem_pct,
        "next_reset_time": next_reset,
        "models": [
            {"name": "Gemini 3.6 Flash (High)", "status": "Actiu", "quota": "100% Capacitat Reial", "type": "Principal (Velocitat & Codi)"},
            {"name": "Gemini 3.1 Pro (High)", "status": "Disponible", "quota": "Finestra 1M Tokens", "type": "Raonament Científic & TFM"},
            {"name": "Claude Sonnet 4.6", "status": "Disponible", "quota": "Pensament Complex", "type": "Refactorització & Anàlisi"},
            {"name": "Claude Opus 4.6", "status": "Disponible", "quota": "Alta Visió & Raonament", "type": "Tasques de Codi Gran Escala"},
            {"name": "GPT-OSS 120B", "status": "Disponible", "quota": "Model Alternatiu", "type": "Avaluació Multimodel"}
        ]
    }

@app.get("/api/conversations")
def get_conversations():
    convs = load_conversations()
    chats_list = []
    for c_id, chat in convs.get("chats", {}).items():
        chats_list.append({
            "id": c_id,
            "title": chat.get("title", "Sense títol"),
            "created_at": chat.get("created_at", ""),
            "msg_count": len(chat.get("messages", []))
        })
    return {
        "active_id": convs.get("active_id", "default"),
        "chats": chats_list
    }

@app.get("/api/conversations/{chat_id}")
def get_chat_detail(chat_id: str):
    convs = load_conversations()
    if chat_id not in convs["chats"]:
        raise HTTPException(status_code=404, detail="Conversa no trobada")
    return convs["chats"][chat_id]

class SelectChatRequest(BaseModel):
    chat_id: str

@app.post("/api/conversations/select")
def select_chat_api(req: SelectChatRequest):
    convs = load_conversations()
    cid = req.chat_id
    if cid not in convs["chats"]:
        title = DEFAULT_CHATS.get(cid, f"📌 {cid}")
        convs["chats"][cid] = {
            "id": cid,
            "title": title,
            "created_at": datetime.now().strftime("%d/%m %H:%M"),
            "messages": []
        }
    convs["active_id"] = cid
    save_conversations(convs)
    return {"status": "ok", "active_id": cid}

class ClearChatRequest(BaseModel):
    chat_id: str

@app.post("/api/conversations/clear")
def clear_chat_api(req: ClearChatRequest):
    convs = load_conversations()
    if req.chat_id in convs["chats"]:
        convs["chats"][req.chat_id]["messages"] = []
        save_conversations(convs)
        return {"status": "ok", "cleared_id": req.chat_id}
    raise HTTPException(status_code=404, detail="Chat ID no trobat")

class CreateChatRequest(BaseModel):
    id: str
    title: str

@app.get("/api/media/{file_path:path}")
def get_media_file_api(file_path: str):
    base_brain = os.path.join(USER_HOME, ".gemini/antigravity-cli/brain")
    full_path = os.path.normpath(os.path.join(base_brain, file_path))
    if not full_path.startswith(base_brain):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.exists(full_path):
        # Try checking in active conversation folder
        conv_path = os.path.join(base_brain, "52a230fd-4cc6-4e23-9da2-545421935271", file_path)
        if os.path.exists(conv_path):
            return FileResponse(conv_path)
        raise HTTPException(status_code=404, detail="Media file not found")
    return FileResponse(full_path)

@app.post("/api/conversations/create")
def create_chat_api(req: CreateChatRequest):
    convs = load_conversations()
    if req.id not in convs["chats"]:
        convs["chats"][req.id] = {
            "id": req.id,
            "title": req.title,
            "created_at": datetime.now().strftime("%d/%m %H:%M"),
            "messages": []
        }
    convs["active_id"] = req.id
    save_conversations(convs)
    return {"status": "ok", "chat": convs["chats"][req.id]}

class MessageRequest(BaseModel):
    text: str
    client_id: str = "👤 Tu"
    chat_id: Optional[str] = None

@app.post("/api/send_message")
async def send_message_api(req: MessageRequest):
    text = req.text
    convs = load_conversations()
    act_id = req.chat_id or convs.get("active_id", "default")
    ts_now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    msg_obj = {"sender": "👤 Tu", "text": text, "timestamp": ts_now}
    if act_id in convs["chats"]:
        convs["chats"][act_id]["messages"].append(msg_obj)
    if act_id != "default" and "default" in convs["chats"]:
        convs["chats"]["default"]["messages"].append(msg_obj)
    save_conversations(convs)

    await manager.broadcast({
        "type": "chat_message",
        "sender": "👤 Tu",
        "text": text,
        "timestamp": ts_now,
        "chat_id": act_id
    })
    asyncio.create_task(process_ai_response(text))
    return {"status": "ok"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            message_type = data.get("type", "message")

            if message_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif message_type == "user_message":
                text = data.get("text", "")
                convs = load_conversations()
                act_id = data.get("chat_id") or convs.get("active_id", "default")
                ts_now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

                msg_obj = {"sender": "👤 Tu", "text": text, "timestamp": ts_now}
                if act_id in convs["chats"]:
                    convs["chats"][act_id]["messages"].append(msg_obj)
                if act_id != "default" and "default" in convs["chats"]:
                    convs["chats"]["default"]["messages"].append(msg_obj)
                save_conversations(convs)

                await manager.broadcast({
                    "type": "chat_message",
                    "sender": "👤 Tu",
                    "text": text,
                    "timestamp": ts_now,
                    "chat_id": act_id
                })
                asyncio.create_task(process_ai_response(text))
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/", response_class=HTMLResponse)
def get_pwa():
    return HTML_PWA_TEMPLATE

HTML_PWA_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ca">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="theme-color" content="#0d1117">
    <title>Antigravity Master Hub</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.css">
    <script src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.8.0/styles/tokyo-night-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.8.0/highlight.min.js"></script>
    <style>
        :root {
            --bg: #0d1117;
            --card-bg: rgba(22, 27, 34, 0.85);
            --border: rgba(48, 54, 61, 0.6);
            --primary: #38bdf8;
            --primary-glow: rgba(56, 189, 248, 0.25);
            --accent: #a855f7;
            --text: #f0f6fc;
            --text-dim: #8b949e;
            --success: #3fb950;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Outfit', sans-serif; }
        body { background: var(--bg); color: var(--text); display: flex; height: 100vh; height: 100dvh; overflow: hidden; }

        .app-container { flex: 1; display: flex; flex-direction: column; height: 100vh; height: 100dvh; overflow: hidden; position: relative; width: 100%; }

        main { flex: 1; overflow-y: auto; padding: 6px 16px 12px 16px; display: flex; flex-direction: column; gap: 12px; max-width: 950px; margin: 0 auto; width: 100%; }

        @media (max-width: 768px) {
            main { padding: 4px 8px 8px 8px; }
        }
        .chat-box { flex: 1; display: flex; flex-direction: column; gap: 14px; overflow-y: auto; padding-right: 4px; }
        
        .msg { padding: 14px 18px; border-radius: 14px; max-width: 92%; font-size: 0.96rem; line-height: 1.6; }
        .msg.user { background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.35); align-self: flex-end; color: var(--text); border-bottom-right-radius: 2px; }
        .msg.bot { background: var(--card-bg); border: 1px solid var(--border); backdrop-filter: blur(12px); align-self: flex-start; width: 100%; border-bottom-left-radius: 2px; }

        .msg h1, .msg h2, .msg h3, .msg h4 { color: var(--primary); margin: 12px 0 8px 0; font-size: 1.1rem; }
        .msg p { margin-bottom: 10px; }
        .msg ul, .msg ol { margin-left: 22px; margin-bottom: 10px; }
        .msg table { width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 0.9rem; background: rgba(13, 17, 23, 0.6); border-radius: 10px; overflow: hidden; border: 1px solid var(--border); }
        .msg th, .msg td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); }
        .msg th { color: var(--primary); background: rgba(56, 189, 248, 0.12); font-weight: 600; }
        .msg code { font-family: 'JetBrains Mono', monospace; font-size: 0.9rem; line-height: 1.5; }
        .msg pre { background: transparent !important; padding: 14px !important; margin: 0 !important; overflow-x: auto; border: none !important; }
        .msg code:not(pre code) { background: rgba(56, 189, 248, 0.12); padding: 3px 6px; border-radius: 4px; color: var(--primary); font-size: 0.88rem; }

        /* Pretty Code Block Cards with Header & Copy Button */
        .code-container {
            background: #161b22;
            border: 1px solid rgba(56, 189, 248, 0.25);
            border-radius: 12px;
            margin: 14px 0;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35);
        }
        .code-header {
            background: rgba(13, 17, 23, 0.9);
            padding: 8px 14px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(48, 54, 61, 0.6);
            font-size: 0.78rem;
            font-weight: 600;
            color: var(--primary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .btn-copy-code {
            background: rgba(56, 189, 248, 0.12);
            border: 1px solid rgba(56, 189, 248, 0.3);
            color: var(--primary);
            padding: 3px 10px;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .btn-copy-code:hover {
            background: var(--primary);
            color: #0d1117;
        }

        footer {
            background: rgba(13, 17, 23, 0.95); border-top: 1px solid var(--border);
            padding: 12px 16px; padding-bottom: max(12px, env(safe-area-inset-bottom));
            display: flex; justify-content: center; position: relative; z-index: 10;
        }

        .input-container { display: flex; gap: 8px; width: 100%; max-width: 950px; align-items: center; }
        input {
            flex: 1; min-width: 0; padding: 14px 16px; background: #161b22; border: 1px solid var(--border); color: var(--text); border-radius: 12px; font-size: 1rem; outline: none; transition: border 0.2s, box-shadow 0.2s;
        }
        input:focus { border-color: var(--primary); box-shadow: 0 0 12px var(--primary-glow); }

        button.btn-action {
            padding: 14px 18px; background: linear-gradient(135deg, var(--primary), #0284c7); color: #fff; font-weight: 600; font-size: 1.2rem; border: none; border-radius: 12px; cursor: pointer; transition: transform 0.1s, opacity 0.2s; white-space: nowrap; flex-shrink: 0; display: flex; align-items: center; justify-content: center;
        }
        button.btn-action:hover { opacity: 0.95; }
        button.btn-action:active { transform: scale(0.96); }

        button.btn-attach {
            padding: 14px 16px; background: #161b22; border: 1px solid var(--border); color: var(--text); font-size: 1.2rem; border-radius: 12px; cursor: pointer; transition: background 0.2s, border 0.2s, transform 0.1s; display: flex; align-items: center; justify-content: center; flex-shrink: 0;
        }
        button.btn-attach:hover { background: rgba(56, 189, 248, 0.15); border-color: var(--primary); }
        button.btn-attach:active { transform: scale(0.95); }

        button.btn-attach.recording {
            background: rgba(239, 68, 68, 0.25) !important;
            border-color: #ef4444 !important;
            color: #ef4444 !important;
            animation: pulse-red 1.2s infinite ease-in-out;
        }
        @keyframes pulse-red {
            0%, 100% { transform: scale(1); box-shadow: 0 0 4px rgba(239,68,68,0.4); }
            50% { transform: scale(1.08); box-shadow: 0 0 14px rgba(239,68,68,0.8); }
        }

        .action-menu {
            position: absolute; bottom: 65px; left: 0;
            background: #161b22; border: 1px solid var(--border);
            border-radius: 14px; padding: 6px; box-shadow: 0 10px 25px rgba(0,0,0,0.5);
            display: flex; flex-direction: column; gap: 4px; z-index: 100; min-width: 170px;
            backdrop-filter: blur(12px); animation: fadeIn 0.15s ease-out;
        }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

        .action-item {
            display: flex; align-items: center; gap: 10px; padding: 10px 14px;
            color: var(--text); border-radius: 10px; font-size: 0.92rem; font-weight: 500;
            cursor: pointer; transition: background 0.15s;
        }
        .action-item:hover, .action-item:active { background: rgba(56, 189, 248, 0.15); color: var(--primary); }

        .thinking-badge {
            display: flex; align-items: center; gap: 6px; padding: 10px 16px;
            background: rgba(56, 189, 248, 0.08); border: 1px solid rgba(56, 189, 248, 0.3);
            border-radius: 12px; align-self: flex-start; font-size: 0.88rem; backdrop-filter: blur(8px); margin-top: 8px;
        }
        .spinner-dot {
            width: 7px; height: 7px; background-color: var(--primary); border-radius: 50%; display: inline-block; animation: pulse-dot 1.4s infinite ease-in-out both;
        }
        .spinner-dot:nth-child(1) { animation-delay: -0.32s; }
        .spinner-dot:nth-child(2) { animation-delay: -0.16s; }
        /* Side Drawer Styling */
        .drawer-overlay {
            position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
            background: rgba(0,0,0,0.6); backdrop-filter: blur(3px);
            z-index: 999; display: none; opacity: 0; transition: opacity 0.25s ease;
        }
        .drawer-overlay.active { display: block; opacity: 1; }

        .drawer {
            position: fixed; top: 0; left: -300px; width: 270px; height: 100%;
            background: #161b22; border-right: 1px solid var(--border);
            z-index: 1000; transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1);
            display: flex; flex-direction: column; padding: 20px 16px;
            box-shadow: 6px 0 25px rgba(0,0,0,0.6); transform: translateX(0);
        }
        .drawer.active { transform: translateX(300px); }

        .drawer-header {
            display: flex; align-items: center; justify-content: space-between;
            padding-bottom: 16px; border-bottom: 1px solid var(--border); margin-bottom: 16px;
        }
        .drawer-title { font-size: 1.05rem; font-weight: 700; color: var(--primary); display: flex; align-items: center; gap: 8px; }
        .btn-close-drawer { background: none; border: none; color: var(--text-muted); font-size: 1.2rem; cursor: pointer; padding: 4px; }

        .session-card {
            background: rgba(56, 189, 248, 0.06); border: 1px solid rgba(56, 189, 248, 0.2);
            border-radius: 12px; padding: 12px; margin-bottom: 20px;
        }
        .session-item { display: flex; align-items: center; justify-content: space-between; font-size: 0.82rem; margin-bottom: 6px; color: var(--text-muted); }
        .session-item:last-child { margin-bottom: 0; }
        .session-val { font-weight: 600; color: var(--text); }

        .drawer-section-title { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 1px; color: var(--text-muted); margin-bottom: 10px; font-weight: 700; }

        .drawer-menu { display: flex; flex-direction: column; gap: 6px; }
        .drawer-item {
            display: flex; align-items: center; gap: 12px; padding: 12px 14px;
            border-radius: 10px; color: var(--text); font-size: 0.88rem; font-weight: 500;
            cursor: pointer; transition: background 0.15s; background: rgba(255,255,255,0.02);
        }
        .drawer-item:hover, .drawer-item:active { background: rgba(56, 189, 248, 0.15); color: var(--primary); }

        .btn-hamburger {
            position: fixed; top: 10px; left: 10px; z-index: 99;
            background: rgba(22, 27, 34, 0.88); border: 1px solid var(--border);
            color: var(--text); border-radius: 10px; padding: 6px 12px; font-size: 1.1rem;
            cursor: pointer; backdrop-filter: blur(8px); box-shadow: 0 4px 12px rgba(0,0,0,0.4);
            transition: background 0.2s, transform 0.1s;
        }
        .btn-hamburger:active { transform: scale(0.95); }

        /* Topic Filter Bar */
        .topic-bar {
            display: flex; align-items: center; justify-content: space-between;
            padding: 8px 14px; background: rgba(56, 189, 248, 0.12);
            border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 10px;
            margin-bottom: 12px; font-size: 0.85rem; font-weight: 600; color: var(--primary);
            backdrop-filter: blur(8px); animation: fadeIn 0.2s ease-out;
        }
        .btn-clear-topic {
            background: none; border: none; color: var(--text-muted); font-size: 0.8rem;
            cursor: pointer; padding: 2px 6px; border-radius: 6px; font-weight: 600;
        }
        .btn-clear-topic:hover { background: rgba(239, 68, 68, 0.2); color: #ef4444; }

        .drawer-item.active-topic {
            background: rgba(56, 189, 248, 0.2) !important;
            color: var(--primary) !important;
            border-left: 3px solid var(--primary);
        }

    </style>
</head>
<body>
    <div style="position:fixed; top:12px; left:12px; z-index:900; display:flex; gap:8px;">
        <button type="button" class="btn-hamburger" style="position:static;" onclick="toggleDrawer()" title="Obrir menú de la sessió">☰</button>
        <button type="button" id="btn-tts-toggle" class="btn-hamburger" style="position:static; background:rgba(22,27,34,0.75); border:1px solid var(--border); font-size:1.1rem; width:38px; height:38px; border-radius:10px; display:flex; align-items:center; justify-content:center;" onclick="toggleTTS()" title="Activar/Desactivar lectura automàtica per veu">🔇</button>
    </div>

    <div id="drawer-overlay" class="drawer-overlay" onclick="closeDrawer()"></div>

    <div id="drawer" class="drawer">
        <div class="drawer-header">
            <div class="drawer-title">🧠 Sovereign Hub</div>
            <button type="button" class="btn-close-drawer" onclick="closeDrawer()">✕</button>
        </div>

        <div class="session-card">
            <div class="session-item">
                <span>Sessió Tmux</span>
                <span class="session-val" style="color:var(--primary);">tfm:0.0</span>
            </div>
            <div class="session-item">
                <span>Estat Daemon</span>
                <span class="session-val" style="color:#4ade80;">● Active</span>
            </div>
            <div class="session-item">
                <span>Model AI</span>
                <span class="session-val">Gemini 3.6</span>
            </div>
        </div>

        <div class="drawer-section-title">💬 Converses Independents</div>
        <div class="drawer-menu" id="drawer-topics-list" style="margin-bottom: 20px;">
            <div class="drawer-item active-topic" id="topic-item-default" onclick="selectChat('default', '🌐 Xat General (Tots)')">
                <span>🌐</span> Xat General (Tots)
            </div>
            <div class="drawer-item" id="topic-item-salut" onclick="selectChat('salut', '🩺 Salut i Suplements')">
                <span>🩺</span> Salut i Suplements
            </div>
            <div class="drawer-item" id="topic-item-tfm" onclick="selectChat('tfm', '🔬 TFM i Ciència')">
                <span>🔬</span> TFM i Ciència
            </div>
            <div class="drawer-item" id="topic-item-gestio" onclick="selectChat('gestio', '📧 Gestions i Correus')">
                <span>📧</span> Gestions i Correus
            </div>
            <div class="drawer-item" onclick="promptNewChat()">
                <span>➕</span> Nova Conversa...
            </div>
        </div>

        <div class="drawer-section-title">Accions Ràpides</div>
        <div class="drawer-menu">
            <div class="drawer-item" onclick="showAntigravityStatus()">
                <span>⚡</span> Estat d'Antigravity
            </div>
            <div class="drawer-item" onclick="clearActiveChat()">
                <span>🗑️</span> Netejar Conversa Actual
            </div>
            <div class="drawer-item" onclick="triggerQuickAction('Resum de correus')">
                <span>📧</span> Resum de Correus
            </div>
            <div class="drawer-item" onclick="triggerQuickAction('Mostra les tasques de tasks.org')">
                <span>📝</span> Tasques Org-Mode
            </div>
            <div class="drawer-item" onclick="triggerQuickAction('Estat del servidor casalap (RAM, disc, CPU)')">
                <span>📊</span> Estat del Servidor
            </div>
            <div class="drawer-item" onclick="syncChatUI()">
                <span>🔄</span> Re-sincronitzar Xat
            </div>
        </div>
    </div>

    <div class="app-container">
        <main>
            <div id="topic-bar" class="topic-bar" style="display:none;">
                <span id="topic-bar-label">🔬 Vista: TFM i Ciència</span>
                <button type="button" class="btn-clear-topic" onclick="selectChat('default', '🌐 Xat General (Tots)')">✕ Mostra tot</button>
            </div>
            <div class="chat-box" id="chat-messages"></div>
            <div id="thinking-indicator" class="thinking-badge" style="display:none;">
                <span class="spinner-dot"></span>
                <span class="spinner-dot"></span>
                <span class="spinner-dot"></span>
                <span style="margin-left:6px; font-weight:600; color:var(--primary);">⚡ L'IA està pensant i processant...</span>
            </div>
        </main>

        <footer>
            <div class="input-container" style="position:relative;">
                <button type="button" id="btn-plus" class="btn-attach" onclick="toggleActionMenu(event)" title="Opcions (📷 🎙️)">➕</button>
                <div id="action-menu" class="action-menu" style="display:none;">
                    <div class="action-item" onclick="triggerFileInput()">
                        <span>📷</span> Adjuntar Foto
                    </div>
                    <div class="action-item" onclick="toggleSpeechFromMenu()">
                        <span>🎙️</span> Dictar per Veu
                    </div>
                </div>
                <input type="file" id="file-input" accept="image/*" style="display:none;" onchange="handleFileSelect(event)">
                <div id="image-preview-container" style="display:none; align-items:center; gap:8px; padding:4px 10px; background:#161b22; border:1px solid var(--border); border-radius:8px;">
                    <img id="img-preview" src="" style="max-height:40px; border-radius:4px;">
                    <button type="button" onclick="clearPastedImage()" style="background:none; border:none; color:#f87171; font-weight:bold; font-size:1.1rem; cursor:pointer;">✕</button>
                </div>
                <input type="text" id="chat-input" placeholder="Escriu o parla pel micròfon (➕)..." onkeypress="if(event.key==='Enter') sendChat()">
                <button type="button" class="btn-action" onclick="sendChat()" ontouchstart="sendChat()" title="Enviar instrucció">✈</button>
            </div>
        </footer>
    </div>

    <script>
        let ws;
        let pastedImageBase64 = null;

        function cleanImagePaths(txt) {
            if (!txt) return '';
            let cleaned = txt.replace(/\[?Imatge enganxada:\s*\/[^\s\]]+\.png\]?/gi, '📷 *[Imatge]*');
            
            // Convert file:///.../brain/.../image.png into working HTML <img> tags pointing to /api/media/
            cleaned = cleaned.replace(/!\[([^\]]*)\]\((?:file:\/\/\/[^\s\)]*?brain\/)?([^\s\)]+)\)/gi, (match, alt, imgPath) => {
                let filename = imgPath.split('/').pop();
                return `<img src="/api/media/${filename}" alt="${alt || 'Imatge'}" style="max-width:100%; border-radius:12px; margin:12px 0; display:block; box-shadow:0 8px 25px rgba(0,0,0,0.5);" />`;
            });
            return cleaned;
        }

        function renderMarkdownWithMath(sender, txt) {
            let displayTxt = cleanImagePaths(txt);
            let rawText = displayTxt;
            if (typeof marked === 'undefined') return rawText;

            let mathBlocks = [];

            // Protect block math $$...$$ and \[...\]
            rawText = rawText.replace(/\$\$([\s\S]+?)\$\$/g, (m, p1) => {
                mathBlocks.push({ type: 'block', code: p1 });
                return `<math-block-placeholder id="${mathBlocks.length - 1}"></math-block-placeholder>`;
            }).replace(/\\\[([\s\S]+?)\\\]/g, (m, p1) => {
                mathBlocks.push({ type: 'block', code: p1 });
                return `<math-block-placeholder id="${mathBlocks.length - 1}"></math-block-placeholder>`;
            });

            // Protect inline math \(...\) and $...$
            rawText = rawText.replace(/\\\(([\s\S]+?)\\\)/g, (m, p1) => {
                mathBlocks.push({ type: 'inline', code: p1 });
                return `<math-inline-placeholder id="${mathBlocks.length - 1}"></math-inline-placeholder>`;
            }).replace(/\$([^\$\n]+)\$/g, (m, p1) => {
                mathBlocks.push({ type: 'inline', code: p1 });
                return `<math-inline-placeholder id="${mathBlocks.length - 1}"></math-inline-placeholder>`;
            });

            let html = marked.parse(rawText);

            // Restore & render KaTeX math
            html = html.replace(/<math-block-placeholder id="(\d+)"><\/math-block-placeholder>/g, (m, idx) => {
                let item = mathBlocks[parseInt(idx)];
                if (item && typeof katex !== 'undefined') {
                    try {
                        return katex.renderToString(item.code, { displayMode: true, throwOnError: false });
                    } catch(e) { return item.code; }
                }
                return m;
            }).replace(/<math-inline-placeholder id="(\d+)"><\/math-inline-placeholder>/g, (m, idx) => {
                let item = mathBlocks[parseInt(idx)];
                if (item && typeof katex !== 'undefined') {
                    try {
                        return katex.renderToString(item.code, { displayMode: false, throwOnError: false });
                    } catch(e) { return item.code; }
                }
                return m;
            });

            return html;
        }

        function enhanceCodeBlocks(element) {
            if (!element) return;
            element.querySelectorAll('pre').forEach(pre => {
                if (pre.parentNode && pre.parentNode.classList && pre.parentNode.classList.contains('code-container')) return;
                
                const code = pre.querySelector('code');
                let lang = 'CODE';
                if (code) {
                    const match = (code.className || '').match(/language-(\w+)/);
                    if (match) lang = match[1].toUpperCase();
                }

                const wrapper = document.createElement('div');
                wrapper.className = 'code-container';

                const header = document.createElement('div');
                header.className = 'code-header';
                header.innerHTML = `<span>💻 ${lang}</span><button type="button" class="btn-copy-code" onclick="copyCode(this)">📋 Copiar</button>`;

                pre.parentNode.insertBefore(wrapper, pre);
                wrapper.appendChild(header);
                wrapper.appendChild(pre);

                if (code && typeof hljs !== 'undefined') {
                    try { hljs.highlightElement(code); } catch(e) {}
                }
            });
        }

        function copyCode(btn) {
            const container = btn.closest('.code-container');
            const code = container ? container.querySelector('code') : null;
            if (code) {
                navigator.clipboard.writeText(code.innerText).then(() => {
                    const orig = btn.innerHTML;
                    btn.innerHTML = '✅ Copiat!';
                    setTimeout(() => btn.innerHTML = orig, 2000);
                });
            }
        }

        let activeChatId = 'default';

        async function selectChat(chatId, label) {
            activeChatId = chatId;
            closeDrawer();

            // Set active drawer item styling
            document.querySelectorAll('#drawer-topics-list .drawer-item').forEach(el => el.classList.remove('active-topic'));
            const activeEl = document.getElementById(`topic-item-${chatId}`);
            if (activeEl) activeEl.classList.add('active-topic');

            // Show/hide topic header bar
            const bar = document.getElementById('topic-bar');
            const barLabel = document.getElementById('topic-bar-label');
            if (chatId === 'default') {
                if (bar) bar.style.display = 'none';
            } else {
                if (bar) bar.style.display = 'flex';
                if (barLabel) barLabel.innerHTML = label || `💬 ${chatId}`;
            }

            try {
                await fetch('/api/conversations/select', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ chat_id: chatId })
                });
            } catch(e) {}

            await loadChatMessages(chatId);
        }

        async function loadChatMessages(chatId) {
            try {
                const targetId = chatId || activeChatId;
                const r = await fetch(`/api/conversations/${targetId}`);
                const chat = await r.json();
                const box = document.getElementById('chat-messages');
                box.innerHTML = '';
                (chat.messages || []).forEach(m => {
                    appendMsg(m.sender.includes('Tu') ? 'user' : 'bot', m.sender, m.text, m.timestamp);
                });
            } catch(e) { console.error(e); }
        }

        async function clearActiveChat() {
            closeDrawer();
            if (!confirm(`Confirmes que vols esborrar l'historial d'aquesta conversa?`)) return;
            try {
                await fetch('/api/conversations/clear', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ chat_id: activeChatId })
                });
                const box = document.getElementById('chat-messages');
                if (box) box.innerHTML = '';
            } catch(e) { console.error(e); }
        }

        async function promptNewChat() {
            const name = prompt("Nom de la nova conversa (p. ex. Receptes, Viatges, Projectes):");
            if (!name) return;
            const chatId = name.toLowerCase().replace(/[^a-z0-9]/g, '_');
            try {
                await fetch('/api/conversations/create', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ id: chatId, title: name })
                });
                const list = document.getElementById('drawer-topics-list');
                if (list) {
                    const newItem = document.createElement('div');
                    newItem.className = 'drawer-item';
                    newItem.id = `topic-item-${chatId}`;
                    newItem.onclick = () => selectChat(chatId, `📌 ${name}`);
                    newItem.innerHTML = `<span>📌</span> ${name}`;
                    list.insertBefore(newItem, list.lastElementChild);
                }
                selectChat(chatId, `📌 ${name}`);
            } catch(e) { console.error(e); }
        }

        let isTTSEnabled = false;

        function toggleTTS() {
            isTTSEnabled = !isTTSEnabled;
            const btn = document.getElementById('btn-tts-toggle');
            if (btn) {
                btn.innerHTML = isTTSEnabled ? '🔊' : '🔇';
                btn.style.background = isTTSEnabled ? 'rgba(56,189,248,0.25)' : 'rgba(22,27,34,0.75)';
                btn.style.borderColor = isTTSEnabled ? 'var(--primary)' : 'var(--border)';
            }
            if (isTTSEnabled && typeof window.speechSynthesis !== 'undefined') {
                loadVoices();
                try {
                    if (window.speechSynthesis.paused) window.speechSynthesis.resume();
                } catch(e) {}
                const testUtt = new SpeechSynthesisUtterance("Veu activada");
                testUtt.lang = 'ca-ES';
                testUtt.volume = 1.0;
                window.speechSynthesis.speak(testUtt);
            } else if (!isTTSEnabled && typeof window.speechSynthesis !== 'undefined') {
                window.speechSynthesis.cancel();
            }
        }

        let availableVoices = [];

        function loadVoices() {
            if (typeof window.speechSynthesis !== 'undefined') {
                availableVoices = window.speechSynthesis.getVoices() || [];
            }
        }
        if (typeof window.speechSynthesis !== 'undefined') {
            loadVoices();
            if (window.speechSynthesis.onvoiceschanged !== undefined) {
                window.speechSynthesis.onvoiceschanged = loadVoices;
            }
        }

        function speakText(text) {
            if (typeof window.speechSynthesis === 'undefined') {
                alert("🔒 Connexió No Segura (HTTP): Els navegadors bloquegen la veu i el micròfon en adreces http://. Accedeix per HTTPS (https://100.80.29.31:8000) o afegeix l'origen a chrome://flags/#unsafely-treat-insecure-origin-as-secure");
                return;
            }

            try {
                window.speechSynthesis.cancel();
                if (window.speechSynthesis.paused) {
                    window.speechSynthesis.resume();
                }
            } catch(e) {}
            
            let clean = (text || '')
                .replace(/```[\s\S]*?```/g, ' Codi en pantalla. ')
                .replace(/`([^`]+)`/g, '$1')
                .replace(/!\[([^\]]*)\]\([^)]+\)/g, '')
                .replace(/<[^>]+>/g, '')
                .replace(/\\\[[\s\S]*?\\\]/g, ' Fòrmula matemàtica en pantalla. ')
                .replace(/\\\([\s\S]*?\\\)/g, ' Fòrmula. ')
                .replace(/\$\$[\s\S]*?\$\$/g, ' Fòrmula. ')
                .replace(/\$([^\$\n]+)\$/g, '$1')
                .replace(/[*#_~]/g, '')
                .replace(/https?:\/\/\S+/g, ' enllaç ');
                
            if (!clean.trim()) return;

            const utterance = new SpeechSynthesisUtterance(clean);
            utterance.rate = 1.0;
            utterance.pitch = 1.0;
            utterance.lang = 'ca-ES';

            let voices = availableVoices.length > 0 ? availableVoices : (window.speechSynthesis.getVoices() || []);
            let caVoice = voices.find(v => (v.lang || '').toLowerCase().startsWith('ca'));
            let esVoice = voices.find(v => (v.lang || '').toLowerCase().startsWith('es'));
            
            if (caVoice) {
                utterance.voice = caVoice;
                utterance.lang = caVoice.lang || 'ca-ES';
            } else if (esVoice) {
                utterance.voice = esVoice;
                utterance.lang = esVoice.lang || 'es-ES';
            }

            utterance.onerror = (e) => {
                console.error("Speech error:", e);
            };

            window.speechSynthesis.speak(utterance);
        }

        function appendMsg(cls, sender, txt, timeStr) {
            const box = document.getElementById('chat-messages');
            if (!box) return;
            const div = document.createElement('div');
            div.className = `msg ${cls}`;
            let html = renderMarkdownWithMath(sender, txt);
            if (cls === 'user') {
                const now = timeStr || new Date().toLocaleString('ca-ES', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
                html += `<div style="text-align:right; font-size:0.68rem; opacity:0.5; margin-top:6px; font-weight:400; letter-spacing:0.2px;">${now}</div>`;
            } else if (cls === 'bot') {
                const escapedTxt = (txt || '').replace(/"/g, '&quot;').replace(/'/g, "\\'");
                html += `<div style="display:flex; justify-content:flex-end; align-items:center; margin-top:10px; border-top:1px solid rgba(255,255,255,0.06); padding-top:6px;">
                    <button type="button" onclick="speakText('${escapedTxt}')" style="background:rgba(56,189,248,0.1); border:1px solid rgba(56,189,248,0.25); color:var(--primary); padding:3px 10px; border-radius:6px; font-size:0.75rem; cursor:pointer; font-weight:600; display:flex; align-items:center; gap:4px;">
                        🔊 Escolta
                    </button>
                </div>`;
            }
            div.innerHTML = html;
            enhanceCodeBlocks(div);
            box.appendChild(div);
            box.scrollTop = box.scrollHeight;
        }

        async function loadInitialChat() {
            await loadChatMessages(activeChatId);
        }

        // --- Side Drawer Functions ---
        function toggleDrawer() {
            const drawer = document.getElementById('drawer');
            const overlay = document.getElementById('drawer-overlay');
            if (drawer && overlay) {
                drawer.classList.toggle('active');
                overlay.classList.toggle('active');
            }
        }

        function closeDrawer() {
            const drawer = document.getElementById('drawer');
            const overlay = document.getElementById('drawer-overlay');
            if (drawer && overlay) {
                drawer.classList.remove('active');
                overlay.classList.remove('active');
            }
        }

        function syncChatUI() {
            closeDrawer();
            loadChatMessages(activeChatId);
        }

        async function showAntigravityStatus() {
            closeDrawer();
            try {
                const res = await fetch('/api/antigravity/status');
                const data = await res.json();

                let modelsHtml = '';
                (data.models || []).forEach(m => {
                    modelsHtml += `
                        <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 0; border-bottom:1px solid rgba(48,54,61,0.4); font-size:0.86rem;">
                            <div>
                                <span style="font-weight:600; color:var(--text);">${m.name}</span>
                                <div style="font-size:0.72rem; color:var(--text-dim);">${m.type}</div>
                            </div>
                            <div style="text-align:right;">
                                <span style="background:rgba(56,189,248,0.15); color:var(--primary); padding:2px 8px; border-radius:6px; font-size:0.75rem; font-weight:600;">${m.status}</span>
                                <div style="font-size:0.72rem; color:var(--text-dim); margin-top:2px;">${m.quota}</div>
                            </div>
                        </div>
                    `;
                });

                const modalHtml = `
                    <div style="background:linear-gradient(135deg, rgba(22,27,34,0.95), rgba(13,17,23,0.98)); border:1px solid rgba(56,189,248,0.3); border-radius:16px; padding:20px; max-width:520px; width:92%; box-shadow:0 12px 35px rgba(0,0,0,0.6); color:var(--text);">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; border-bottom:1px solid var(--border); padding-bottom:10px;">
                            <div style="font-size:1.1rem; font-weight:700; color:var(--primary); display:flex; align-items:center; gap:8px;">
                                ⚡ Estat d'Antigravity AI
                            </div>
                            <button onclick="closeStatusModal()" style="background:none; border:none; color:var(--text-dim); font-size:1.2rem; cursor:pointer;">✕</button>
                        </div>

                        <div style="margin-bottom:16px;">
                            <div style="font-size:0.82rem; color:var(--text-dim); margin-bottom:4px;">🤖 Model Actiu a Tmux:</div>
                            <div style="font-size:1rem; font-weight:700; color:var(--primary);">${data.active_model}</div>
                        </div>

                        <div style="margin-bottom:18px; background:rgba(56,189,248,0.06); padding:12px; border-radius:12px; border:1px solid rgba(56,189,248,0.18);">
                            <div style="display:flex; justify-content:space-between; font-size:0.84rem; font-weight:600; margin-bottom:6px;">
                                <span>📊 Capàcitats de Context:</span>
                                <span style="color:var(--success);">${data.rem_pct}% Disponible</span>
                            </div>
                            <div style="width:100%; background:rgba(255,255,255,0.1); height:10px; border-radius:6px; overflow:hidden; margin-bottom:8px;">
                                <div style="width:${data.used_pct}%; background:linear-gradient(90deg, var(--primary), var(--accent)); height:100%;"></div>
                            </div>
                            <div style="display:flex; justify-content:space-between; font-size:0.75rem; color:var(--text-dim);">
                                <span>Tokens emprats: ~${data.estimated_tokens_used}</span>
                                <span>Màx: ${data.context_max_tokens}</span>
                            </div>
                        </div>

                        <div style="margin-bottom:18px; font-size:0.82rem; background:rgba(168,85,247,0.08); padding:10px 12px; border-radius:10px; border:1px solid rgba(168,85,247,0.25);">
                            <div style="display:flex; justify-content:space-between; font-weight:600; color:var(--accent);">
                                <span>🔄 Pròxim Restablit de Finestra:</span>
                                <span>${data.next_reset_time}</span>
                            </div>
                            <div style="color:var(--text-dim); font-size:0.75rem; margin-top:2px;">
                                Finestra lliscant automàtica de renovació de quota.
                            </div>
                        </div>

                        <div style="font-size:0.8rem; font-weight:700; color:var(--primary); margin-bottom:8px; text-transform:uppercase; letter-spacing:0.5px;">
                            📋 Models i Capàcitats Disponibles
                        </div>
                        <div style="max-height:180px; overflow-y:auto; padding-right:4px;">
                            ${modelsHtml}
                        </div>
                    </div>
                `;

                let modal = document.getElementById('status-modal-overlay');
                if (!modal) {
                    modal = document.createElement('div');
                    modal.id = 'status-modal-overlay';
                    modal.style.position = 'fixed';
                    modal.style.top = '0'; modal.style.left = '0';
                    modal.style.width = '100vw'; modal.style.height = '100vh';
                    modal.style.background = 'rgba(0,0,0,0.65)';
                    modal.style.backdropFilter = 'blur(8px)';
                    modal.style.zIndex = '1000';
                    modal.style.display = 'flex'; modal.style.alignItems = 'center'; modal.style.justifyContent = 'center';
                    document.body.appendChild(modal);
                }
                modal.innerHTML = modalHtml;
                modal.style.display = 'flex';
            } catch(e) {
                alert("Error obtenint l'estat d'Antigravity AI: " + e);
            }
        }

        function closeStatusModal() {
            const modal = document.getElementById('status-modal-overlay');
            if (modal) modal.style.display = 'none';
        }

        function triggerQuickAction(txt) {
            closeDrawer();
            document.getElementById('chat-input').value = txt;
            sendChat();
        }

        function initWS() {
            const loc = window.location;
            const wsProtocol = loc.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${wsProtocol}//${loc.host}/ws`);

            ws.onmessage = (evt) => {
                const data = JSON.parse(evt.data);
                if (data.type === 'ai_status') {
                    const ind = document.getElementById('thinking-indicator');
                    if (ind) ind.style.display = (data.status === 'thinking' ? 'flex' : 'none');
                } else if (data.type === 'chat_message') {
                    const ind = document.getElementById('thinking-indicator');
                    if (ind) ind.style.display = 'none';
                    if (!data.sender.includes('Tu')) {
                        if (activeChatId === 'default' || data.chat_id === activeChatId || !data.chat_id) {
                            appendMsg('bot', data.sender, data.text, data.timestamp);
                            if (isTTSEnabled) {
                                speakText(data.text);
                            }
                        }
                    }
                }
            };

            ws.onclose = () => setTimeout(initWS, 2000);
        }

        function checkForInteractiveQuestion(txt) {
            if (!txt) return;
            
            const lines = txt.split('\n').map(l => l.trim()).filter(l => l.length > 0);
            const questionLines = lines.filter(l => l.includes('?'));
            
            let options = [];
            lines.forEach(l => {
                const match = l.match(/^(?:[0-9]+[\.\)]|\*|\-|\•)\s+(.+)/);
                if (match && match[1] && match[1].length < 100) {
                    options.push(match[1].trim());
                }
            });

            // Trigger modal if text contains a question mark
            if (questionLines.length > 0) {
                showQuestionModal({ question: txt, options: options });
            }
        }

        function showQuestionModal(data) {
            let optionsHtml = '';
            (data.options || []).forEach((opt, idx) => {
                optionsHtml += `
                    <button type="button" onclick="submitQuestionAnswer('${opt.replace(/'/g, "\\'")}')" 
                            style="background:rgba(56,189,248,0.12); border:1px solid rgba(56,189,248,0.3); color:var(--primary); padding:10px 14px; border-radius:10px; font-size:0.92rem; font-weight:600; text-align:left; cursor:pointer; transition:all 0.15s ease;">
                        ${idx + 1}. ${opt}
                    </button>
                `;
            });

            const modalHtml = `
                <div style="background:linear-gradient(135deg, rgba(22,27,34,0.96), rgba(13,17,23,0.98)); border:1px solid rgba(56,189,248,0.4); border-radius:18px; padding:22px; max-width:540px; width:92%; box-shadow:0 15px 40px rgba(0,0,0,0.7); color:var(--text);">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; border-bottom:1px solid var(--border); padding-bottom:10px;">
                        <div style="font-size:1.1rem; font-weight:700; color:var(--primary); display:flex; align-items:center; gap:8px;">
                            ❓ Pregunta d'Antigravity AI
                        </div>
                        <button onclick="closeQuestionModal()" style="background:none; border:none; color:var(--text-dim); font-size:1.2rem; cursor:pointer;">✕</button>
                    </div>

                    <div style="font-size:0.96rem; line-height:1.5; margin-bottom:16px; max-height:220px; overflow-y:auto; color:var(--text);">
                        ${renderMarkdownWithMath('⚡ Antigravity AI', data.question || '')}
                    </div>

                    ${optionsHtml ? `
                        <div style="display:flex; flex-direction:column; gap:8px; margin-bottom:16px;">
                            <div style="font-size:0.75rem; font-weight:700; color:var(--text-dim); text-transform:uppercase; letter-spacing:0.5px;">Tria una opció:</div>
                            ${optionsHtml}
                        </div>
                    ` : ''}

                    <div style="display:flex; gap:8px; align-items:center; margin-top:12px;">
                        <input type="text" id="modal-answer-input" placeholder="Escriu la teua resposta personalitzada..." 
                               onkeydown="if(event.key==='Enter') submitCustomQuestionAnswer()"
                               style="flex:1; padding:12px; background:#161b22; border:1px solid var(--border); color:var(--text); border-radius:10px; outline:none; font-size:0.92rem;">
                        <button type="button" onclick="submitCustomQuestionAnswer()" 
                                style="padding:12px 18px; background:linear-gradient(135deg, var(--primary), #0284c7); color:#fff; font-weight:600; border:none; border-radius:10px; cursor:pointer; font-size:0.92rem;">
                            Enviar
                        </button>
                    </div>
                </div>
            `;

            let modal = document.getElementById('question-modal-overlay');
            if (!modal) {
                modal = document.createElement('div');
                modal.id = 'question-modal-overlay';
                modal.style.position = 'fixed';
                modal.style.top = '0'; modal.style.left = '0';
                modal.style.width = '100vw'; modal.style.height = '100vh';
                modal.style.background = 'rgba(0,0,0,0.7)';
                modal.style.backdropFilter = 'blur(10px)';
                modal.style.zIndex = '1000';
                modal.style.display = 'flex'; modal.style.alignItems = 'center'; modal.style.justifyContent = 'center';
                document.body.appendChild(modal);
            }
            modal.innerHTML = modalHtml;
            modal.style.display = 'flex';
            setTimeout(() => {
                const inp = document.getElementById('modal-answer-input');
                if (inp) inp.focus();
            }, 100);
        }

        function closeQuestionModal() {
            const modal = document.getElementById('question-modal-overlay');
            if (modal) modal.style.display = 'none';
        }

        function submitQuestionAnswer(answerTxt) {
            closeQuestionModal();
            appendMsg('user', '👤 Tu', answerTxt);
            sendPayload(answerTxt);
        }

        function submitCustomQuestionAnswer() {
            const inp = document.getElementById('modal-answer-input');
            if (inp && inp.value.trim()) {
                submitQuestionAnswer(inp.value.trim());
            }
        }

        // --- Action Dropdown Menu (Gemini Style ➕) ---
        function toggleActionMenu(evt) {
            if (evt) evt.stopPropagation();
            const menu = document.getElementById('action-menu');
            if (!menu) return;
            menu.style.display = (menu.style.display === 'none' || !menu.style.display) ? 'flex' : 'none';
        }

        function closeActionMenu() {
            const menu = document.getElementById('action-menu');
            if (menu) menu.style.display = 'none';
        }

        function triggerFileInput() {
            closeActionMenu();
            document.getElementById('file-input').click();
        }

        function toggleSpeechFromMenu() {
            closeActionMenu();
            toggleSpeech();
        }

        document.addEventListener('click', (e) => {
            const menu = document.getElementById('action-menu');
            const btn = document.getElementById('btn-plus');
            if (menu && !menu.contains(e.target) && e.target !== btn) {
                menu.style.display = 'none';
            }
        });

        // --- Speech Recognition (STT - Dictat de veu) ---
        let recognition = null;
        let isRecording = false;

        if ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window) {
            const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
            recognition = new SpeechRec();
            recognition.continuous = true;
            recognition.interimResults = true;
            recognition.lang = 'ca-ES';

            recognition.onresult = (evt) => {
                let transcript = '';
                for (let i = evt.resultIndex; i < evt.results.length; ++i) {
                    transcript += evt.results[i][0].transcript;
                }
                if (transcript) {
                    document.getElementById('chat-input').value = transcript;
                }
            };

            recognition.onerror = (evt) => {
                console.warn('Speech recognition error:', evt.error);
                stopSpeech();
            };

            recognition.onend = () => {
                if (isRecording) stopSpeech();
            };
        }

        function toggleSpeech() {
            if (!recognition) {
                alert('El teu navegador no suporta el dictat directe per micròfon. Fes servir la icona de micròfon del teu teclat mòbil!');
                return;
            }
            if (isRecording) {
                stopSpeech();
            } else {
                startSpeech();
            }
        }

        function startSpeech() {
            if (!recognition) return;
            try {
                recognition.lang = 'ca-ES';
                recognition.start();
                isRecording = true;
                const btn = document.getElementById('btn-plus');
                if (btn) {
                    btn.innerHTML = '🎙️';
                    btn.classList.add('recording');
                    btn.title = 'Escoltant... Prems per a aturar';
                }
            } catch(e) { console.error(e); }
        }

        function stopSpeech() {
            if (!recognition) return;
            try { recognition.stop(); } catch(e) {}
            isRecording = false;
            const btn = document.getElementById('btn-plus');
            if (btn) {
                btn.innerHTML = '➕';
                btn.classList.remove('recording');
                btn.title = 'Opcions (📷 🎙️)';
            }
        }

        async function sendPayload(fullText) {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'user_message', text: fullText, chat_id: activeChatId }));
            } else {
                try {
                    await fetch('/api/send_message', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ text: fullText, chat_id: activeChatId })
                    });
                } catch(e) { console.error('Send error:', e); }
            }
        }

        async function sendChat() {
            const inp = document.getElementById('chat-input');
            if (!inp) return;
            let txt = inp.value.trim();
            if (!txt && !pastedImageBase64) return;

            const ind = document.getElementById('thinking-indicator');
            if (ind) ind.style.display = 'flex';

            let userDisplayText = txt;

            if (pastedImageBase64) {
                userDisplayText = (txt ? txt + ' ' : '') + '📷 *[Imatge enganxada]*';
                const b64 = pastedImageBase64;
                clearPastedImage();
                inp.value = '';
                appendMsg('user', '👤 Tu', userDisplayText);

                try {
                    const r = await fetch('/api/upload_image', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ image_base64: b64 })
                    });
                    const res = await r.json();
                    if (res.filepath) {
                        const fullText = (txt ? txt + ' ' : '') + `[Imatge enganxada: ${res.filepath}]`;
                        await sendPayload(fullText);
                    }
                } catch(e) { console.error(e); }
            } else {
                appendMsg('user', '👤 Tu', userDisplayText);
                inp.value = '';
                await sendPayload(txt);
            }
        }

        function showImagePreview(src) {
            const container = document.getElementById('image-preview-container');
            const img = document.getElementById('img-preview');
            img.src = src;
            container.style.display = 'flex';
        }

        function clearPastedImage() {
            pastedImageBase64 = null;
            document.getElementById('image-preview-container').style.display = 'none';
            const fi = document.getElementById('file-input');
            if (fi) fi.value = '';
        }

        function handleFileSelect(evt) {
            const file = evt.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (e) => {
                pastedImageBase64 = e.target.result;
                showImagePreview(pastedImageBase64);
            };
            reader.readAsDataURL(file);
        }

        document.addEventListener('paste', async (e) => {
            const items = (e.clipboardData || e.originalEvent.clipboardData).items;
            for (let item of items) {
                if (item.type.indexOf('image') === 0) {
                    const blob = item.getAsFile();
                    const reader = new FileReader();
                    reader.onload = function(event) {
                        pastedImageBase64 = event.target.result;
                        showImagePreview(pastedImageBase64);
                    };
                    reader.readAsDataURL(blob);
                }
            }
        });

        window.onload = () => {
            initWS();
            loadInitialChat();
        };
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import threading
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cert_file = os.path.join(base_dir, "certs", "cert.pem")
    key_file = os.path.join(base_dir, "certs", "key.pem")
    
    if os.path.exists(cert_file) and os.path.exists(key_file):
        def run_http():
            uvicorn.run(app, host="0.0.0.0", port=8000)

        def run_https():
            uvicorn.run(app, host="0.0.0.0", port=8443, ssl_certfile=cert_file, ssl_keyfile=key_file)

        t_http = threading.Thread(target=run_http, daemon=True)
        t_https = threading.Thread(target=run_https, daemon=True)
        
        t_http.start()
        t_https.start()
        
        print(f"🌐 HTTP Server active on http://0.0.0.0:8000")
        print(f"🔒 HTTPS Server active on https://0.0.0.0:8443")
        
        t_http.join()
        t_https.join()
    else:
        print(f"🌐 HTTP Mode active on http://0.0.0.0:8000")
        uvicorn.run(app, host="0.0.0.0", port=8000)
