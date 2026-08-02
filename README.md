# AGY-Bridge 🌉🚀

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110.0-009688.svg)](https://fastapi.tiangolo.com/)

A sovereign, full-stack **Mobile Web PWA & Terminal Gateway** designed for pair-programming and interacting with local AI agents (Google Antigravity CLI) from any mobile or desktop browser over **Tailscale WireGuard**.

---

## 🏗️ Architecture & Ecosystem Integration

`AGY-Bridge` serves as the central user-facing hub for a modular, sovereign **Academic Knowledge & AI Platform**:

```
                  ┌─────────────────────────────────────┐
                  │          AGY-Bridge / PWA           │
                  │   (Mobile Hub & Speech-to-Text)    │
                  └──────────────────┬──────────────────┘
                                     │
                  ┌──────────────────┴──────────────────┐
                  │    Google Antigravity AI Engine     │
                  └─┬─────────────────┬───────────────┬─┘
                    │                 │               │
  ┌─────────────────▼───┐  ┌──────────▼──────────┐  ┌─▼──────────────────┐
  │ mcp-server-academic │  │ mcp-server-eduvpn   │  │ mcp-server-jupyter │
  │ (Dialnet/CSIC/Open) │  │ (EduVPN / Network)  │  │ (SageMath/Python)  │
  └─────────────────────┘  └─────────────────────┘  └────────────────────┘
```

### Integrated Ecosystem Repositories:
1. **[mcp-server-academic-spain](https://github.com/CasimirVictoria/mcp-server-academic-spain):** Unified scientific research across Spanish (Dialnet, Teseo, CSIC) and global (PubMed, OpenAlex) databases.
2. **[mcp-server-eduvpn](https://github.com/CasimirVictoria/mcp-server-eduvpn):** Automated NetworkManager EduVPN connection control and 7-day 2FA profile renewal.
3. **[mcp-server-jupyter](https://github.com/CasimirVictoria/mcp-server-jupyter):** Local JupyterLab & SageMath symbolic math computation and WebGL 3D plot rendering.

---

## ✨ Key Features

- **📱 Mobile PWA & Speech-to-Text:** Tokyo-Night styled progressive web app with native speech recognition (`ca-ES`, `es-ES`).
- **💻 1-Tap Live Tmux Inspection Modal:** Instant real-time view of background terminal panes (`tmux capture-pane`) at a single tap on status badges.
- **🌌 Inline 3D WebGL & KaTeX Math:** Embedded Three.js interactive 3D graphs, KaTeX LaTeX formulas, and HTML5 slider widgets.
- **🛡️ Tailscale Mesh Security:** Encrypted end-to-end communication across mobile devices and headless Linux workstations.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
