# Claw Deck

Web dashboard for Clawdbot agent monitoring and task management.

## Features

- 📊 **System Health Monitoring** — Context usage, active models, token counts
- 📋 **Kanban Task Board** — Inbox, Up Next, In Progress, In Review, Done
- 🤖 **Agent Control Panel** — Monitor and manage active AI agents
- 💬 **Agent Communication** — Real-time message stream between agents
- 📦 **Git Activity** — Track commits and uncommitted changes

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Start the dashboard
python server.py

# Start data collector (in another terminal)
python data_collector.py
```

Then open http://localhost:5000

## Architecture

- **Flask backend** — API server (`server.py`)
- **Data collector** — Background process gathering metrics (`data_collector.py`)
- **Kanban module** — Task management (`kanban.py`)
- **Message collector** — Parses agent communication logs (`message_collector.py`)
- **Vanilla JS frontend** — Real-time dashboard UI

## License

MIT
