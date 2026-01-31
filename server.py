"""
Clawdbot Dashboard - Backend API Server
Phase 4: Agent Control Panel + Kanban Task Management
"""

import os
import json
import logging
import signal
import subprocess
import datetime
from pathlib import Path
from flask import Flask, jsonify, send_from_directory, render_template, request
from flask_cors import CORS

# Import Kanban module
from kanban import (
    create_task, update_task, delete_task, move_task,
    get_all_tasks_grouped, get_task, get_assignment_history,
    KANBAN_COLUMNS
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__, 
            template_folder='templates',
            static_folder='static')

# Enable CORS for local development
CORS(app)

# Configuration
STATE_FILE = '/home/chris/clawd/dashboard/current_state.json'
CONTROL_LOG_FILE = '/home/chris/clawd/dashboard/control_log.jsonl'
PORT = 5000
HOST = '0.0.0.0'

# Protected sessions that cannot be killed
PROTECTED_SESSIONS = ['agent:main:main']


@app.route('/')
def index():
    """Serve the main dashboard page."""
    logger.info("Serving index.html")
    return render_template('index.html')


@app.route('/api/state')
def get_state():
    """
    Return the contents of current_state.json.
    Returns empty state if file doesn't exist yet.
    """
    logger.info("GET /api/state requested")
    
    if not os.path.exists(STATE_FILE):
        logger.warning(f"State file not found: {STATE_FILE}")
        return jsonify({
            "status": "empty",
            "message": "No state file exists yet",
            "data": {}
        }), 200
    
    try:
        with open(STATE_FILE, 'r') as f:
            state_data = json.load(f)
        logger.info("State file loaded successfully")
        return jsonify({
            "status": "ok",
            "data": state_data
        }), 200
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in state file: {e}")
        return jsonify({
            "status": "error",
            "message": f"Invalid JSON in state file: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Error reading state file: {e}")
        return jsonify({
            "status": "error",
            "message": f"Error reading state file: {str(e)}"
        }), 500


@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files from the static folder."""
    logger.info(f"Serving static file: {filename}")
    return send_from_directory('static', filename)


# Control Log Functions
def log_control_action(action, session_key, success=True, details=None):
    """Log a control action to the control log file."""
    try:
        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "action": action,
            "session_key": session_key,
            "success": success,
            "details": details or {}
        }
        with open(CONTROL_LOG_FILE, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
        logger.info(f"Control action logged: {action} for {session_key}")
    except Exception as e:
        logger.error(f"Failed to log control action: {e}")


def get_agent_pid(session_key):
    """
    Find the PID of an agent process by session key.
    Searches for openclaw agent processes matching the session.
    """
    try:
        # Try to find process by session key in command line or environment
        # Openclaw agents run as part of the gateway, so we look for matching patterns
        
        # First, try to find any node processes with matching session info
        result = subprocess.run(
            ['pgrep', '-f', f'openclaw.*{session_key}'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            return int(pids[0])
        
        # Alternative: Check if there's a session file with PID info
        session_file = Path(f"~/.openclaw/agents/main/sessions/{session_key.split(':')[-1]}.pid").expanduser()
        if session_file.exists():
            return int(session_file.read_text().strip())
        
        return None
    except Exception as e:
        logger.error(f"Error finding PID for {session_key}: {e}")
        return None


def get_paused_agents():
    """Get list of paused agents from control log."""
    paused = set()
    if not os.path.exists(CONTROL_LOG_FILE):
        return paused
    
    try:
        with open(CONTROL_LOG_FILE, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get('action') == 'pause' and entry.get('success'):
                        paused.add(entry['session_key'])
                    elif entry.get('action') == 'resume' and entry.get('success'):
                        paused.discard(entry['session_key'])
                    elif entry.get('action') == 'kill' and entry.get('success'):
                        paused.discard(entry['session_key'])
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.error(f"Error reading control log: {e}")
    
    return paused


def send_signal_to_agent(session_key, signal_num, signal_name):
    """
    Send a signal to an agent process.
    Since agents run within openclaw-gateway, we use a signaling mechanism
    through the control log and attempt direct process signaling.
    """
    pid = get_agent_pid(session_key)
    
    if pid:
        try:
            os.kill(pid, signal_num)
            return True, f"Signal {signal_name} sent to PID {pid}"
        except ProcessLookupError:
            return False, f"Process {pid} not found"
        except PermissionError:
            return False, f"Permission denied to signal process {pid}"
        except Exception as e:
            return False, f"Error sending signal: {str(e)}"
    else:
        # No direct PID found - log the action for the data collector to pick up
        return True, f"Control action logged (no direct process control available for {session_key})"


# Control API Endpoints
@app.route('/api/control/pause', methods=['POST'])
def pause_agent():
    """Pause an agent (SIGSTOP)."""
    logger.info("POST /api/control/pause requested")
    
    data = request.get_json()
    if not data or 'session_key' not in data:
        return jsonify({
            "status": "error",
            "message": "Missing session_key in request body"
        }), 400
    
    session_key = data['session_key']
    
    # Check if already paused
    paused = get_paused_agents()
    if session_key in paused:
        return jsonify({
            "status": "ok",
            "message": f"Agent {session_key} is already paused",
            "paused": True
        }), 200
    
    # Send SIGSTOP
    success, details = send_signal_to_agent(session_key, signal.SIGSTOP, "SIGSTOP")
    
    # Log the action
    log_control_action('pause', session_key, success, {"details": details})
    
    if success:
        return jsonify({
            "status": "ok",
            "message": f"Agent {session_key} paused",
            "paused": True,
            "details": details
        }), 200
    else:
        return jsonify({
            "status": "error",
            "message": f"Failed to pause agent: {details}",
            "paused": False
        }), 500


@app.route('/api/control/resume', methods=['POST'])
def resume_agent():
    """Resume an agent (SIGCONT)."""
    logger.info("POST /api/control/resume requested")
    
    data = request.get_json()
    if not data or 'session_key' not in data:
        return jsonify({
            "status": "error",
            "message": "Missing session_key in request body"
        }), 400
    
    session_key = data['session_key']
    
    # Check if actually paused
    paused = get_paused_agents()
    if session_key not in paused:
        return jsonify({
            "status": "ok",
            "message": f"Agent {session_key} was not paused",
            "paused": False
        }), 200
    
    # Send SIGCONT
    success, details = send_signal_to_agent(session_key, signal.SIGCONT, "SIGCONT")
    
    # Log the action
    log_control_action('resume', session_key, success, {"details": details})
    
    if success:
        return jsonify({
            "status": "ok",
            "message": f"Agent {session_key} resumed",
            "paused": False,
            "details": details
        }), 200
    else:
        return jsonify({
            "status": "error",
            "message": f"Failed to resume agent: {details}",
            "paused": True
        }), 500


@app.route('/api/control/kill', methods=['POST'])
def kill_agent():
    """Kill an agent session."""
    logger.info("POST /api/control/kill requested")
    
    data = request.get_json()
    if not data or 'session_key' not in data:
        return jsonify({
            "status": "error",
            "message": "Missing session_key in request body"
        }), 400
    
    session_key = data['session_key']
    
    # Prevent killing protected sessions
    if session_key in PROTECTED_SESSIONS:
        log_control_action('kill', session_key, False, {"reason": "protected_session"})
        return jsonify({
            "status": "error",
            "message": f"Cannot kill protected session: {session_key}",
            "protected": True
        }), 403
    
    # Send SIGTERM first, then SIGKILL if needed
    success_term, details_term = send_signal_to_agent(session_key, signal.SIGTERM, "SIGTERM")
    
    if success_term:
        # Log the kill action
        log_control_action('kill', session_key, True, {"signal": "SIGTERM", "details": details_term})
        return jsonify({
            "status": "ok",
            "message": f"Agent {session_key} terminated",
            "killed": True,
            "details": details_term
        }), 200
    else:
        log_control_action('kill', session_key, False, {"error": details_term})
        return jsonify({
            "status": "error",
            "message": f"Failed to kill agent: {details_term}",
            "killed": False
        }), 500


@app.route('/api/control/stop_all', methods=['POST'])
def stop_all_agents():
    """Emergency stop all non-protected agents."""
    logger.info("POST /api/control/stop_all requested")
    
    results = []
    killed_count = 0
    
    # Read current state to get active sessions
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                sessions = state.get('sessions', {}).get('active_sessions', [])
                
                for session in sessions:
                    session_key = session.get('session_key')
                    if not session_key or session_key in PROTECTED_SESSIONS:
                        continue
                    
                    # Kill each agent
                    success, details = send_signal_to_agent(session_key, signal.SIGTERM, "SIGTERM")
                    log_control_action('kill', session_key, success, {
                        "emergency_stop": True,
                        "details": details
                    })
                    
                    results.append({
                        "session_key": session_key,
                        "success": success,
                        "details": details
                    })
                    if success:
                        killed_count += 1
    except Exception as e:
        logger.error(f"Error in stop_all: {e}")
        return jsonify({
            "status": "error",
            "message": f"Error during emergency stop: {str(e)}"
        }), 500
    
    return jsonify({
        "status": "ok",
        "message": f"Emergency stop completed. Killed {killed_count} agents.",
        "killed_count": killed_count,
        "results": results
    }), 200


# Global auto mode flag
auto_mode_enabled = True

@app.route('/api/control/auto', methods=['POST'])
def control_auto():
    """Enable or disable auto mode for agent assignment."""
    global auto_mode_enabled
    logger.info("POST /api/control/auto requested")
    
    data = request.get_json() or {}
    enabled = data.get('enabled', True)
    
    auto_mode_enabled = bool(enabled)
    log_control_action('auto_mode', None, success=True, details={'enabled': auto_mode_enabled})
    
    return jsonify({
        "status": "ok",
        "auto_mode": auto_mode_enabled,
        "message": f"Auto mode {'enabled' if auto_mode_enabled else 'disabled'}"
    }), 200

@app.route('/api/control/status', methods=['GET'])
def control_status():
    """Get control status - list of paused agents and recent control actions."""
    global auto_mode_enabled
    logger.info("GET /api/control/status requested")
    
    paused = get_paused_agents()
    recent_actions = []
    
    # Get recent control actions
    if os.path.exists(CONTROL_LOG_FILE):
        try:
            with open(CONTROL_LOG_FILE, 'r') as f:
                lines = f.readlines()
                # Get last 50 actions
                for line in lines[-50:]:
                    try:
                        recent_actions.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Error reading control log: {e}")
    
    return jsonify({
        "status": "ok",
        "auto_mode": auto_mode_enabled,
        "paused_agents": list(paused),
        "protected_sessions": PROTECTED_SESSIONS,
        "recent_actions": recent_actions
    }), 200


# =============================================================================
# KANBAN API ENDPOINTS
# =============================================================================

@app.route('/api/kanban', methods=['GET'])
def get_kanban_board():
    """
    Get all tasks grouped by status column.
    Returns tasks organized by Kanban columns.
    """
    logger.info("GET /api/kanban requested")
    
    try:
        board_data = get_all_tasks_grouped()
        return jsonify({
            "status": "ok",
            "data": board_data
        }), 200
    except Exception as e:
        logger.error(f"Error getting kanban board: {e}")
        return jsonify({
            "status": "error",
            "message": f"Error loading kanban board: {str(e)}"
        }), 500


@app.route('/api/kanban/tasks', methods=['POST'])
def create_kanban_task():
    """
    Create a new task.
    Required: title
    Optional: description, priority (low/medium/high/critical), status
    """
    logger.info("POST /api/kanban/tasks requested")
    
    data = request.get_json()
    if not data:
        return jsonify({
            "status": "error",
            "message": "Request body is required"
        }), 400
    
    title = data.get('title', '').strip()
    description = data.get('description', '').strip()
    priority = data.get('priority', 'medium').lower()
    status = data.get('status', 'Backlog')
    created_by = data.get('created_by', 'Jarvis')
    obsidian_link = data.get('obsidian_link')
    category = data.get('category', '').strip()
    
    success, task, message = create_task(
        title=title,
        description=description,
        priority=priority,
        status=status,
        created_by=created_by,
        obsidian_link=obsidian_link,
        category=category
    )
    
    if success:
        return jsonify({
            "status": "ok",
            "message": message,
            "task": task
        }), 201
    else:
        return jsonify({
            "status": "error",
            "message": message
        }), 400


@app.route('/api/kanban/tasks/<task_id>', methods=['GET'])
def get_kanban_task(task_id):
    """Get a single task by ID."""
    logger.info(f"GET /api/kanban/tasks/{task_id} requested")
    
    task = get_task(task_id)
    if task:
        return jsonify({
            "status": "ok",
            "task": task
        }), 200
    else:
        return jsonify({
            "status": "error",
            "message": f"Task {task_id} not found"
        }), 404


@app.route('/api/kanban/tasks/<task_id>', methods=['PUT'])
def update_kanban_task(task_id):
    """
    Update a task.
    Can update: title, description, priority
    """
    logger.info(f"PUT /api/kanban/tasks/{task_id} requested")
    
    data = request.get_json()
    if not data:
        return jsonify({
            "status": "error",
            "message": "Request body is required"
        }), 400
    
    # Build updates dict from allowed fields
    updates = {}
    for field in ['title', 'description', 'priority']:
        if field in data:
            updates[field] = data[field]
    
    if not updates:
        return jsonify({
            "status": "error",
            "message": "No valid fields to update. Allowed: title, description, priority"
        }), 400
    
    success, task, message = update_task(task_id, **updates)
    
    if success:
        return jsonify({
            "status": "ok",
            "message": message,
            "task": task
        }), 200
    else:
        if "not found" in message.lower():
            return jsonify({
                "status": "error",
                "message": message
            }), 404
        else:
            return jsonify({
                "status": "error",
                "message": message
            }), 400


@app.route('/api/kanban/tasks/<task_id>/move', methods=['PUT'])
def move_kanban_task(task_id):
    """
    Move a task to a new column/status.
    Auto-assigns agent when moving to 'In Progress'.
    """
    logger.info(f"PUT /api/kanban/tasks/{task_id}/move requested")
    
    data = request.get_json()
    if not data or 'status' not in data:
        return jsonify({
            "status": "error",
            "message": "Missing 'status' field in request body"
        }), 400
    
    new_status = data['status']
    auto_assign = data.get('auto_assign', True)
    
    success, task, message = move_task(task_id, new_status, auto_assign=auto_assign)
    
    if success:
        response = {
            "status": "ok",
            "message": message,
            "task": task
        }
        # Add agent assignment info if applicable
        if task.get('assigned_agent'):
            response['assigned_agent'] = task['assigned_agent']
            response['session_key'] = task.get('session_key')
        return jsonify(response), 200
    else:
        if "not found" in message.lower():
            return jsonify({
                "status": "error",
                "message": message
            }), 404
        else:
            return jsonify({
                "status": "error",
                "message": message
            }), 400


@app.route('/api/kanban/tasks/<task_id>', methods=['DELETE'])
def delete_kanban_task(task_id):
    """Delete a task."""
    logger.info(f"DELETE /api/kanban/tasks/{task_id} requested")
    
    success, message = delete_task(task_id)
    
    if success:
        return jsonify({
            "status": "ok",
            "message": message
        }), 200
    else:
        if "not found" in message.lower():
            return jsonify({
                "status": "error",
                "message": message
            }), 404
        else:
            return jsonify({
                "status": "error",
                "message": message
            }), 500


@app.route('/api/kanban/assignments', methods=['GET'])
def get_kanban_assignments():
    """Get agent assignment history."""
    logger.info("GET /api/kanban/assignments requested")
    
    task_id = request.args.get('task_id')
    limit = request.args.get('limit', 100, type=int)
    
    try:
        history = get_assignment_history(task_id=task_id, limit=limit)
        return jsonify({
            "status": "ok",
            "data": {
                "assignments": history,
                "count": len(history)
            }
        }), 200
    except Exception as e:
        logger.error(f"Error getting assignment history: {e}")
        return jsonify({
            "status": "error",
            "message": f"Error loading assignment history: {str(e)}"
        }), 500


@app.route('/api/kanban/columns', methods=['GET'])
def get_kanban_columns():
    """Get list of valid Kanban columns."""
    logger.info("GET /api/kanban/columns requested")
    
    return jsonify({
        "status": "ok",
        "data": {
            "columns": KANBAN_COLUMNS
        }
    }), 200


# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    logger.warning(f"404 error: {error}")
    return jsonify({
        "status": "error",
        "message": "Endpoint not found"
    }), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"500 error: {error}")
    return jsonify({
        "status": "error",
        "message": "Internal server error"
    }), 500


if __name__ == '__main__':
    logger.info(f"Starting Clawdbot Dashboard server on {HOST}:{PORT}")
    logger.info(f"State file: {STATE_FILE}")
    logger.info(f"Static folder: {app.static_folder}")
    logger.info(f"Template folder: {app.template_folder}")
    
    # Ensure directories exist
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    os.makedirs(app.static_folder, exist_ok=True)
    os.makedirs(app.template_folder, exist_ok=True)
    os.makedirs(os.path.dirname(CONTROL_LOG_FILE), exist_ok=True)
    
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
