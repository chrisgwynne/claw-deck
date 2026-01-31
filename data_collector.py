#!/usr/bin/env python3
"""
Clawdbot Dashboard Data Collector

Collects and aggregates data from various sources for the Clawdbot dashboard.
Outputs to JSON format for easy web frontend consumption.
"""

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Configuration
CONFIG = {
    "update_interval": 10,  # seconds
    "sessions_dir": os.path.expanduser("~/.clawdbot/agents/main/sessions"),
    "sessions_file": os.path.expanduser("~/.clawdbot/agents/main/sessions/sessions.json"),
    "memory_dir": "/home/chris/clawd/memory",
    "repo_dir": "/home/chris/clawd",
    "output_file": "/home/chris/clawd/dashboard/current_state.json",
    "control_log_file": "/home/chris/clawd/dashboard/control_log.jsonl",
    "max_git_commits": 10,
    "max_memory_files": 20,
}

# Project repos to track for Git Activity
PROJECT_REPOS = [
    {"name": "Claw Deck", "path": "/home/chris/clawd/dashboard", "repo_name": "claw-deck"},
    {"name": "Website", "path": "/home/chris/clawd/website", "repo_name": "website"},
]

# Success tracking
SUCCESS_LOG_FILE = '/home/chris/clawd/dashboard/agent_success_log.jsonl'
IDLE_TIMEOUT_MINUTES = 30


def get_timestamp() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def get_paused_agents() -> set:
    """Read control log to determine which agents are currently paused."""
    paused = set()
    control_log_file = CONFIG.get("control_log_file")
    
    if not control_log_file or not os.path.exists(control_log_file):
        return paused
    
    try:
        with open(control_log_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get('success'):
                        action = entry.get('action')
                        session_key = entry.get('session_key')
                        if action == 'pause' and session_key:
                            paused.add(session_key)
                        elif action in ('resume', 'kill') and session_key:
                            paused.discard(session_key)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"[{get_timestamp()}] Error reading control log: {e}")
    
    return paused


def read_sessions() -> dict[str, Any]:
    """Read active sessions from sessions.json."""
    sessions_data = {
        "timestamp": get_timestamp(),
        "active_sessions": [],
        "total_sessions": 0,
        "total_tokens": 0,
        "errors": []
    }
    
    # Get paused agents status
    paused_agents = get_paused_agents()
    sessions_data["paused_agents"] = list(paused_agents)
    
    try:
        if not os.path.exists(CONFIG["sessions_file"]):
            sessions_data["errors"].append("Sessions file not found")
            return sessions_data
        
        with open(CONFIG["sessions_file"], 'r') as f:
            data = json.load(f)
        
        sessions = []
        total_tokens = 0
        
        for session_key, session_info in data.items():
            session_data = {
                "session_key": session_key,
                "session_id": session_info.get("sessionId", "unknown"),
                "model": session_info.get("model", "unknown"),
                "model_provider": session_info.get("modelProvider", "unknown"),
                "channel": session_info.get("lastChannel", "unknown"),
                "label": session_info.get("label", None),
                "spawned_by": session_info.get("spawnedBy", None),
                "total_tokens": session_info.get("totalTokens", 0),
                "input_tokens": session_info.get("inputTokens", 0),
                "output_tokens": session_info.get("outputTokens", 0),
                "context_tokens": session_info.get("contextTokens", 200000),
                "compaction_count": session_info.get("compactionCount", 0),
                "last_updated": datetime.fromtimestamp(
                    session_info.get("updatedAt", 0) / 1000, 
                    timezone.utc
                ).isoformat() if session_info.get("updatedAt") else None,
                "paused": session_key in paused_agents,
            }
            
            # Calculate context usage percentage
            if session_data["context_tokens"] > 0:
                session_data["context_usage_percent"] = round(
                    (session_data["total_tokens"] / session_data["context_tokens"]) * 100, 2
                )
            else:
                session_data["context_usage_percent"] = 0
            
            sessions.append(session_data)
            total_tokens += session_data["total_tokens"]
        
        sessions_data["active_sessions"] = sessions
        sessions_data["total_sessions"] = len(sessions)
        sessions_data["total_tokens"] = total_tokens
        
    except json.JSONDecodeError as e:
        sessions_data["errors"].append(f"Invalid JSON in sessions file: {str(e)}")
    except Exception as e:
        sessions_data["errors"].append(f"Error reading sessions: {str(e)}")
    
    return sessions_data


def parse_memory_files() -> dict[str, Any]:
    """Parse memory files for task status and recent activity."""
    memory_data = {
        "timestamp": get_timestamp(),
        "recent_files": [],
        "total_memory_files": 0,
        "task_summary": {
            "total_tasks": 0,
            "completed_tasks": 0,
            "in_progress_tasks": 0
        },
        "errors": []
    }
    
    try:
        if not os.path.exists(CONFIG["memory_dir"]):
            memory_data["errors"].append("Memory directory not found")
            return memory_data
        
        # Get all .md files in memory directory
        memory_files = []
        for f in os.listdir(CONFIG["memory_dir"]):
            if f.endswith('.md'):
                filepath = os.path.join(CONFIG["memory_dir"], f)
                try:
                    stat = os.stat(filepath)
                    memory_files.append({
                        "filename": f,
                        "path": filepath,
                        "modified": stat.st_mtime,
                        "size": stat.st_size
                    })
                except Exception:
                    continue
        
        # Sort by modification time (newest first)
        memory_files.sort(key=lambda x: x["modified"], reverse=True)
        memory_data["total_memory_files"] = len(memory_files)
        
        # Parse recent files
        recent_files = []
        for mem_file in memory_files[:CONFIG["max_memory_files"]]:
            try:
                with open(mem_file["path"], 'r') as f:
                    content = f.read()
                
                file_data = {
                    "filename": mem_file["filename"],
                    "modified": datetime.fromtimestamp(
                        mem_file["modified"], timezone.utc
                    ).isoformat(),
                    "size_bytes": mem_file["size"],
                    "task_count": content.lower().count("- [ ]") + content.lower().count("- [x]"),
                    "completed_count": content.lower().count("- [x]"),
                    "summary": ""
                }
                
                # Extract summary (first line or first header)
                lines = content.split('\n')
                for line in lines[:5]:
                    if line.startswith('# ') or line.startswith('## '):
                        file_data["summary"] = line.lstrip('# ').strip()[:100]
                        break
                
                if not file_data["summary"] and lines:
                    file_data["summary"] = lines[0].strip()[:100]
                
                # Look for "Summary" or "Notes" section
                summary_match = re.search(r'(?:Summary|Notes):?\s*\n([^\n#]+)', content, re.IGNORECASE)
                if summary_match:
                    file_data["summary"] = summary_match.group(1).strip()[:200]
                
                recent_files.append(file_data)
                
                # Update task counts
                memory_data["task_summary"]["total_tasks"] += file_data["task_count"]
                memory_data["task_summary"]["completed_tasks"] += file_data["completed_count"]
                memory_data["task_summary"]["in_progress_tasks"] += (
                    file_data["task_count"] - file_data["completed_count"]
                )
                
            except Exception as e:
                memory_data["errors"].append(f"Error reading {mem_file['filename']}: {str(e)}")
        
        memory_data["recent_files"] = recent_files
        memory_data["total_memory_files"] = len(memory_files)
        
    except Exception as e:
        memory_data["errors"].append(f"Error scanning memory directory: {str(e)}")
    
    return memory_data


def get_project_git_activity() -> dict[str, Any]:
    """Get git activity from project repos (dashboard, website)."""
    git_data = {
        "timestamp": get_timestamp(),
        "projects": [],
        "errors": []
    }
    
    for project in PROJECT_REPOS:
        project_data = {
            "name": project["name"],
            "repo_name": project["repo_name"],
            "path": project["path"],
            "commits": [],
            "uncommitted_changes": 0,
            "uncommitted_files": [],
            "branch": None
        }
        
        if not os.path.exists(os.path.join(project["path"], ".git")):
            project_data["error"] = "Not a git repository"
            git_data["projects"].append(project_data)
            continue
        
        try:
            # Get current branch
            result = subprocess.run(
                ["git", "-C", project["path"], "branch", "--show-current"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                project_data["branch"] = result.stdout.strip()
            
            # Get recent commits with file stats
            result = subprocess.run(
                [
                    "git", "-C", project["path"], "log",
                    "-10",
                    "--format=%H|%h|%s|%an|%at|%ar",
                    "--stat"
                ],
                capture_output=True, text=True, timeout=5
            )
            
            if result.returncode == 0:
                commits = []
                current_commit = None
                
                for line in result.stdout.strip().split('\n'):
                    if '|' in line and len(line.split('|')) >= 6 and not line.startswith(' '):
                        # New commit line
                        if current_commit:
                            commits.append(current_commit)
                        parts = line.split('|')
                        current_commit = {
                            "hash": parts[0],
                            "short_hash": parts[1],
                            "message": parts[2],
                            "author": parts[3],
                            "timestamp": datetime.fromtimestamp(
                                int(parts[4]), timezone.utc
                            ).isoformat(),
                            "relative_time": parts[5],
                            "files_changed": 0,
                            "insertions": 0,
                            "deletions": 0
                        }
                    elif current_commit and ('files changed' in line or 'file changed' in line):
                        # Parse file stats line
                        files_match = re.search(r'(\d+)\s+files?\s+changed', line)
                        insertions_match = re.search(r'(\d+)\s+insertions?', line)
                        deletions_match = re.search(r'(\d+)\s+deletions?', line)
                        
                        if files_match:
                            current_commit["files_changed"] = int(files_match.group(1))
                        if insertions_match:
                            current_commit["insertions"] = int(insertions_match.group(1))
                        if deletions_match:
                            current_commit["deletions"] = int(deletions_match.group(1))
                
                if current_commit:
                    commits.append(current_commit)
                
                project_data["commits"] = commits
            
            # Check for uncommitted changes
            result = subprocess.run(
                ["git", "-C", project["path"], "status", "--porcelain"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
                changes = [c for c in lines if c]
                project_data["uncommitted_changes"] = len(changes)
                
                uncommitted_files = []
                for line in changes:
                    status = line[:2].strip()
                    filename = line[3:].strip()
                    status_desc = {
                        'M': 'modified', 'A': 'added', 'D': 'deleted',
                        'R': 'renamed', 'C': 'copied', 'U': 'updated', '??': 'untracked'
                    }.get(status, status)
                    uncommitted_files.append({"filename": filename, "status": status_desc})
                project_data["uncommitted_files"] = uncommitted_files
            
            # Get total commit count
            result = subprocess.run(
                ["git", "-C", project["path"], "rev-list", "--count", "HEAD"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                project_data["total_commit_count"] = int(result.stdout.strip())
                
        except Exception as e:
            project_data["error"] = str(e)
        
        git_data["projects"].append(project_data)
    
    return git_data


def get_system_metrics() -> dict[str, Any]:
    """Collect basic system metrics (CPU, memory, disk)."""
    metrics = {
        "timestamp": get_timestamp(),
        "cpu": {},
        "memory": {},
        "disk": {},
        "errors": []
    }
    
    # Read uptime first for uptime_seconds
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_line = f.readline()
            uptime_seconds = float(uptime_line.split()[0])
            metrics["uptime_seconds"] = uptime_seconds
    except Exception:
        metrics["uptime_seconds"] = 0
    
    try:
        # CPU usage (try multiple methods)
        cpu_percent = None
        
        # Try /proc/stat first
        try:
            with open('/proc/stat', 'r') as f:
                line = f.readline()
                if line.startswith('cpu '):
                    fields = list(map(int, line.split()[1:]))
                    idle = fields[3]
                    total = sum(fields)
                    cpu_percent = 100 * (1 - idle / total) if total > 0 else 0
                    metrics["cpu"]["percent"] = round(cpu_percent, 1)
        except Exception:
            pass
        
        # Fallback to top command
        if cpu_percent is None:
            try:
                result = subprocess.run(
                    ["top", "-bn1"],
                    capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'Cpu(s)' in line or '%Cpu' in line:
                            # Parse CPU line
                            match = re.search(r'(\d+\.?\d*)\s*%?\s*id', line)
                            if match:
                                idle = float(match.group(1))
                                cpu_percent = 100 - idle
                                metrics["cpu"]["percent"] = round(cpu_percent, 1)
                                break
            except Exception:
                pass
        
        if cpu_percent is None:
            metrics["cpu"]["percent"] = 0
            
    except Exception as e:
        metrics["errors"].append(f"Error reading CPU metrics: {str(e)}")
    
    # Memory metrics
    try:
        mem_info = {}
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    mem_info['total_kb'] = int(line.split()[1])
                elif line.startswith('MemAvailable:'):
                    mem_info['available_kb'] = int(line.split()[1])
                elif line.startswith('MemFree:'):
                    mem_info['free_kb'] = int(line.split()[1])
                elif line.startswith('Buffers:'):
                    mem_info['buffers_kb'] = int(line.split()[1])
                elif line.startswith('Cached:'):
                    mem_info['cached_kb'] = int(line.split()[1])
        
        if mem_info:
            total = mem_info.get('total_kb', 0)
            available = mem_info.get('available_kb', mem_info.get('free_kb', 0))
            used = total - available
            
            total_gb = round(total / (1024 * 1024), 1)
            used_gb = round(used / (1024 * 1024), 1)
            
            metrics["memory"] = {
                "total_mb": round(total / 1024, 2),
                "used_mb": round(used / 1024, 2),
                "available_mb": round(available / 1024, 2),
                "percent_used": round((used / total) * 100, 2) if total > 0 else 0,
                "total_gb": total_gb,
                "used_gb": used_gb
            }
            
    except Exception as e:
        metrics["errors"].append(f"Error reading memory metrics: {str(e)}")
    
    # Disk metrics
    try:
        result = subprocess.run(
            ["df", "-k", CONFIG["repo_dir"]],
            capture_output=True, text=True, timeout=5
        )
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 6:
                    total_kb = int(parts[1])
                    used_kb = int(parts[2])
                    available_kb = int(parts[3])
                    percent_used = int(parts[4].rstrip('%'))
                    
                    metrics["disk"] = {
                        "total_gb": round(total_kb / (1024 * 1024), 2),
                        "used_gb": round(used_kb / (1024 * 1024), 2),
                        "available_gb": round(available_kb / (1024 * 1024), 2),
                        "percent_used": percent_used,
                        "filesystem": parts[0] if len(parts) > 0 else "unknown",
                        "mount_point": parts[5] if len(parts) > 5 else "unknown"
                    }
                    
    except Exception as e:
        metrics["errors"].append(f"Error reading disk metrics: {str(e)}")
    
    return metrics


def get_skills_info() -> dict[str, Any]:
    """Get information about installed skills."""
    skills_data = {
        "timestamp": get_timestamp(),
        "bundled_count": 0,
        "workspace_count": 0,
        "total_count": 0,
        "skills": [],
        "errors": []
    }
    
    try:
        # Read from sessions.json to get skills snapshot
        if os.path.exists(CONFIG["sessions_file"]):
            with open(CONFIG["sessions_file"], 'r') as f:
                data = json.load(f)
            
            # Get skills from main session
            main_session = data.get("agent:main:main", {})
            skills_snapshot = main_session.get("skillsSnapshot", {})
            resolved_skills = skills_snapshot.get("resolvedSkills", [])
            
            skills = []
            bundled_count = 0
            workspace_count = 0
            
            for skill in resolved_skills:
                skill_data = {
                    "name": skill.get("name", "unknown"),
                    "description": skill.get("description", ""),
                    "source": skill.get("source", "unknown"),
                    "path": skill.get("filePath", "")
                }
                skills.append(skill_data)
                
                if skill.get("source") == "openclaw-bundled":
                    bundled_count += 1
                elif skill.get("source") == "openclaw-workspace":
                    workspace_count += 1
            
            skills_data["skills"] = skills
            skills_data["bundled_count"] = bundled_count
            skills_data["workspace_count"] = workspace_count
            skills_data["total_count"] = len(skills)
            
    except Exception as e:
        skills_data["errors"].append(f"Error reading skills: {str(e)}")
    
    return skills_data


# ==================== Agent Success Tracking ====================

def load_success_history() -> dict[str, Any]:
    """Load agent success/failure history from log file."""
    history = {
        "total_completed": 0,
        "total_failed": 0,
        "total_killed": 0,
        "recent_events": []
    }
    
    if not os.path.exists(SUCCESS_LOG_FILE):
        return history
    
    try:
        with open(SUCCESS_LOG_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    event_type = entry.get('event_type')
                    
                    if event_type == 'complete':
                        history["total_completed"] += 1
                    elif event_type == 'fail':
                        history["total_failed"] += 1
                    elif event_type == 'kill':
                        history["total_killed"] += 1
                    
                    # Keep last 50 events
                    history["recent_events"].append(entry)
                    if len(history["recent_events"]) > 50:
                        history["recent_events"].pop(0)
                        
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"[{get_timestamp()}] Error loading success history: {e}")
    
    return history


def log_agent_event(event_type: str, session_key: str, details: dict = None):
    """Log an agent completion, failure, or kill event."""
    try:
        entry = {
            "timestamp": get_timestamp(),
            "event_type": event_type,
            "session_key": session_key,
            "details": details or {}
        }
        with open(SUCCESS_LOG_FILE, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception as e:
        print(f"[{get_timestamp()}] Error logging agent event: {e}")


def calculate_success_rate() -> dict[str, Any]:
    """Calculate real success rate from agent history."""
    history = load_success_history()
    
    total = history["total_completed"] + history["total_failed"] + history["total_killed"]
    
    if total == 0:
        return {
            "rate": None,
            "total": 0,
            "completed": 0,
            "failed": 0,
            "killed": 0,
            "message": "No data yet"
        }
    
    # Success = completed / total (kills count as neither success nor failure)
    success_rate = round((history["total_completed"] / total) * 100)
    
    return {
        "rate": success_rate,
        "total": total,
        "completed": history["total_completed"],
        "failed": history["total_failed"],
        "killed": history["total_killed"],
        "message": f"{success_rate}% ({history['total_completed']}/{total})"
    }


# ==================== Agent Cleanup ====================

def kill_idle_agents(sessions: list) -> list[dict]:
    """Kill agents that have been idle for too long or have completed tasks."""
    killed = []
    
    # Load kanban tasks to check which agents have done tasks
    try:
        kanban_file = '/home/chris/clawd/dashboard/kanban_tasks.json'
        done_session_keys = set()
        
        if os.path.exists(kanban_file):
            with open(kanban_file, 'r') as f:
                tasks = json.load(f)
            
            for task_id, task in tasks.items():
                if task.get('status') == 'Done' and task.get('session_key'):
                    done_session_keys.add(task['session_key'])
    except Exception as e:
        print(f"[{get_timestamp()}] Error loading kanban tasks: {e}")
        tasks = {}
    
    for session in sessions:
        session_key = session.get("session_key")
        label = session.get("label", "")
        
        # Skip protected sessions
        if session_key == "agent:main:main" or not session_key:
            continue
        
        # Check if agent has a done task
        if session_key in done_session_keys:
            print(f"[{get_timestamp()}] Killing agent {session_key[:30]}... - task is Done")
            if kill_agent_session(session_key):
                killed.append({
                    "session_key": session_key,
                    "reason": "task_done",
                    "label": label
                })
                log_agent_event("kill", session_key, {"reason": "task_done"})
            continue
        
        # Check idle timeout
        last_updated = session.get("last_updated")
        if last_updated:
            try:
                last_time = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                idle_minutes = (datetime.now(timezone.utc) - last_time).total_seconds() / 60
                
                if idle_minutes > IDLE_TIMEOUT_MINUTES:
                    # Check if tokens are still 0 (truly idle)
                    if session.get("total_tokens", 0) == 0:
                        print(f"[{get_timestamp()}] Killing idle agent {session_key[:30]}... - idle {idle_minutes:.0f}m")
                        if kill_agent_session(session_key):
                            killed.append({
                                "session_key": session_key,
                                "reason": "idle_timeout",
                                "label": label,
                                "idle_minutes": round(idle_minutes)
                            })
                            log_agent_event("kill", session_key, {"reason": "idle_timeout", "idle_minutes": round(idle_minutes)})
            except Exception as e:
                print(f"[{get_timestamp()}] Error checking idle time: {e}")
    
    return killed


def kill_agent_session(session_key: str) -> bool:
    """Kill a specific agent session using openclaw CLI."""
    try:
        result = subprocess.run(
            ["openclaw", "sessions", "kill", session_key, "--force"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[{get_timestamp()}] Error killing session {session_key}: {e}")
        return False


# ==================== Main Loop ====================

def collect_all_data() -> dict[str, Any]:
    """Collect all data sources and combine into single structure."""
    # Import here to avoid circular dependency issues
    try:
        import message_collector
        # Collect new messages from session files
        message_collector.collect_messages()
        # Load current messages for output
        agent_messages = message_collector.get_messages_for_api()
    except Exception as e:
        agent_messages = [{"error": f"Failed to collect messages: {str(e)}"}]
    
    # Read sessions first for cleanup
    sessions_data = read_sessions()
    active_sessions = sessions_data.get("active_sessions", [])
    
    # Kill idle agents (with done tasks or idle timeout)
    killed_agents = kill_idle_agents(active_sessions)
    
    # Get success rate
    success_rate = calculate_success_rate()
    
    # Get main session context usage
    main_context_usage = 0
    for session in active_sessions:
        if session.get("session_key") == "agent:main:main":
            main_context_usage = session.get("context_usage_percent", 0)
            break
    
    data = {
        "timestamp": get_timestamp(),
        "collector_version": "1.0.0",
        "context_usage_percent": main_context_usage,
        "sessions": sessions_data,
        "memory": parse_memory_files(),
        "git": get_project_git_activity(),
        "system": get_system_metrics(),
        "skills": get_skills_info(),
        "messages": agent_messages,
        "success_rate": success_rate,
        "agent_cleanup": {
            "killed_count": len(killed_agents),
            "killed_agents": killed_agents,
            "idle_timeout_minutes": IDLE_TIMEOUT_MINUTES
        }
    }
    
    return data


def main():
    """Main loop - continuously collect and write data."""
    print(f"Clawdbot Dashboard Data Collector v1.0.0")
    print(f"Update interval: {CONFIG['update_interval']} seconds")
    print(f"Output file: {CONFIG['output_file']}")
    print("-" * 50)
    
    while True:
        try:
            # Collect all data
            data = collect_all_data()
            
            # Write to output file
            with open(CONFIG["output_file"], 'w') as f:
                json.dump(data, f, indent=2)
            
            print(f"[{get_timestamp()}] Data updated successfully")
            
        except Exception as e:
            print(f"[{get_timestamp()}] Error: {str(e)}")
        
        # Wait for next update
        time.sleep(CONFIG["update_interval"])


if __name__ == "__main__":
    main()
