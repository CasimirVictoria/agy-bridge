#!/usr/bin/env python3
"""
Antigravity Master Hub Bridge Server (server.py)
Clean, lightweight FastAPI + WebSocket server capturing tmux tfm:0.0 session.

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
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
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

CONV_FILE = "/home/casimir/.gemini/antigravity-cli/bridge/conversations.json"
UPLOAD_DIR = "/home/casimir/.gemini/antigravity-cli/brain/52a230fd-4cc6-4e23-9da2-545421935271/.user_uploaded"

def load_conversations() -> dict:
    if os.path.exists(CONV_FILE):
        try:
            with open(CONV_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading conversations: {e}")
    return {
        "active_id": "default",
        "chats": {
            "default": {
                "id": "default",
                "title": "Xat Principal",
                "created_at": datetime.now().strftime("%d/%m %H:%M"),
                "messages": [
                    {
                        "sender": "⚡ Antigravity AI",
                        "text": "¡Hola Casimir! Soc el teu Antigravity Master Hub. Connectat en temps real des del teu ordinador casalap. Com et puc ajudar?",
                        "timestamp": datetime.now().strftime("%H:%M")
                    }
                ]
            }
        }
    }

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

TRANSCRIPT_PATH = "/home/casimir/.gemini/antigravity-cli/brain/52a230fd-4cc6-4e23-9da2-545421935271/.system_generated/logs/transcript.jsonl"

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
    """Wait for tmux to finish generating, then read raw Markdown from transcript.jsonl."""
    try:
        await manager.broadcast({"type": "ai_status", "status": "thinking"})

        # 1. Escape special shell characters and send to tmux pane
        safe_prompt = prompt.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
        cmd = f'tmux send-keys -t tfm:0.0 "{safe_prompt}" Enter'
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()

        await asyncio.sleep(1.5)
        interactive_notified = False

        # 2. Poll tmux pane to check when AGY finishes
        for attempt in range(600):  # Poll up to 5 minutes
            await asyncio.sleep(0.5)

            out_proc = await asyncio.create_subprocess_shell(
                "tmux capture-pane -t tfm:0.0 -p -S -500",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await out_proc.communicate()
            pane = stdout.decode('utf-8', errors='ignore')

            lines = [l.strip() for l in pane.split('\n') if l.strip()]
            if not lines:
                continue

            # Check if AGY is currently generating (spinners or 'esc to cancel' in bottom 5 lines)
            tail_lines = [l for l in lines if l and "esc to cancel" not in l][-5:]
            tail_text = '\n'.join(tail_lines)
            
            is_busy = "Generating..." in pane or "Waiting..." in tail_text
            if not is_busy:
                for char in tail_text:
                    if '\u2800' <= char <= '\u28ff':
                        is_busy = True
                        break

            # Interactive prompt notification
            if ("Do you want to proceed?" in pane or "Requesting permission" in pane):
                if not interactive_notified:
                    interactive_notified = True
                    await manager.broadcast({
                        "type": "chat_message",
                        "sender": "⚡ Antigravity AI",
                        "text": "ℹ️ *S'espera la teua resposta o confirmació a la consola / terminal.*",
                        "timestamp": datetime.now().strftime("%H:%M")
                    })

            if is_busy:
                continue  # AGY is still generating

            # Check if bare prompt '>' exists near bottom
            bare_prompt_exists = any(lines[idx] in (">", "> ") for idx in range(len(lines) - 1, max(-1, len(lines) - 10), -1))
            if not bare_prompt_exists:
                continue

            # 3. Read raw untouched Markdown response directly from transcript.jsonl
            candidate = get_latest_ai_response_from_transcript()
            if not candidate:
                continue

            # Send final clean raw markdown response
            await manager.broadcast({"type": "ai_status", "status": "idle"})
            await manager.broadcast({
                "type": "chat_message",
                "sender": "⚡ Antigravity AI",
                "text": candidate,
                "timestamp": datetime.now().strftime("%H:%M")
            })

            # Save to conversations file
            convs = load_conversations()
            act_id = convs.get("active_id", "default")
            if act_id in convs["chats"]:
                convs["chats"][act_id]["messages"].append({
                    "sender": "⚡ Antigravity AI",
                    "text": candidate,
                    "timestamp": datetime.now().strftime("%H:%M")
                })
                save_conversations(convs)
            break

        await manager.broadcast({"type": "ai_status", "status": "idle"})

    except Exception as e:
        print(f"Error processing AI response: {e}")
        await manager.broadcast({"type": "ai_status", "status": "idle"})

        await manager.broadcast({"type": "ai_status", "status": "idle"})

    except Exception as e:
        print(f"Error processing AI response: {e}")
        await manager.broadcast({"type": "ai_status", "status": "idle"})

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
@app.get("/api/conversations")
def get_conversations():
    convs = load_conversations()
    chats_list = []
    for c_id, chat in convs["chats"].items():
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

class MessageRequest(BaseModel):
    text: str
    client_id: str = "👤 Tu"

@app.post("/api/send_message")
async def send_message_api(req: MessageRequest):
    text = req.text
    convs = load_conversations()
    act_id = convs.get("active_id", "default")
    if act_id in convs["chats"]:
        convs["chats"][act_id]["messages"].append({
            "sender": "👤 Tu",
            "text": text,
            "timestamp": datetime.now().strftime("%H:%M")
        })
        save_conversations(convs)

    await manager.broadcast({
        "type": "chat_message",
        "sender": "👤 Tu",
        "text": text,
        "timestamp": datetime.now().strftime("%H:%M")
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
                act_id = convs.get("active_id", "default")
                if act_id in convs["chats"]:
                    convs["chats"][act_id]["messages"].append({
                        "sender": "👤 Tu",
                        "text": text,
                        "timestamp": datetime.now().strftime("%H:%M")
                    })
                    save_conversations(convs)

                await manager.broadcast({
                    "type": "chat_message",
                    "sender": "👤 Tu",
                    "text": text,
                    "timestamp": datetime.now().strftime("%H:%M")
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
        @keyframes pulse-dot {
            0%, 80%, 100% { transform: scale(0.3); opacity: 0.3; }
            40% { transform: scale(1); opacity: 1; }
        }

    </style>
</head>
<body>
    <div class="app-container">
        <main>
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
            return txt.replace(/\[?Imatge enganxada:\s*\/[^\s\]]+\.png\]?/gi, '📷 *[Imatge]*')
                      .replace(/[0-9a-f-]{20,}\/\.user_uploaded\/[^\s\]]+/gi, '')
                      .replace(/\/home\/[^\s]+\/uploaded_media_[0-9]+\.png/gi, '')
                      .replace(/uploaded_media_[0-9]+\.png/gi, '')
                      .replace(/cli\/brain\/[^\s]+/gi, '');
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

        function appendMsg(cls, sender, txt) {
            const box = document.getElementById('chat-messages');
            if (!box) return;
            const div = document.createElement('div');
            div.className = `msg ${cls}`;
            div.innerHTML = renderMarkdownWithMath(sender, txt);
            enhanceCodeBlocks(div);
            box.appendChild(div);
            box.scrollTop = box.scrollHeight;
        }

        async function loadInitialChat() {
            try {
                const r = await fetch('/api/conversations/default');
                const chat = await r.json();
                const box = document.getElementById('chat-messages');
                box.innerHTML = '';
                (chat.messages || []).forEach(m => {
                    appendMsg(m.sender.includes('Tu') ? 'user' : 'bot', m.sender, m.text);
                });
            } catch(e) { console.error(e); }
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
                        appendMsg('bot', data.sender, data.text);
                    }
                }
            };

            ws.onclose = () => setTimeout(initWS, 2000);
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
                ws.send(JSON.stringify({ type: 'user_message', text: fullText }));
            } else {
                try {
                    await fetch('/api/send_message', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ text: fullText })
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
    uvicorn.run(app, host="0.0.0.0", port=8000)
