#!/usr/bin/env python3
"""
Clawdbot Dashboard - Agent Message Collector

Parses session transcript files to detect and log inter-agent communication.
- Reads session JSONL files from ~/.clawdbot/agents/main/sessions/
- Detects agent-to-agent communication patterns
- Maintains position tracking for incremental parsing
- Keeps only last 100 messages to avoid bloat

Output format:
{"timestamp": "ISO", "from": "agent-name", "to": "agent-name", "message": "text", "type": "delegate|question|answer|spawn"}
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Configuration
CONFIG = {
    "sessions_dir": os.path.expanduser("~/.clawdbot/agents/main/sessions"),
    "sessions_file": os.path.expanduser("~/.clawdbot/agents/main/sessions/sessions.json"),
    "output_file": "/home/chris/clawd/dashboard/agent_messages.jsonl",
    "state_file": "/home/chris/clawd/dashboard/message_collector_state.json",
    "max_messages": 100,
}

# Communication patterns to detect
COMMUNICATION_PATTERNS = {
    "delegate": [
        r"(?:delegat|assign|hand off|pass)\s+(?:to|this)\s+(?:agent|sub-agent|subagent)",
        r"(?:spawn|create)\s+(?:a\s+)?(?:sub-agent|subagent|new\s+agent)",
        r"(?:ask|have)\s+(?:agent|sub-agent|subagent)\s+(?:to|for)",
    ],
    "question": [
        r"(?:need|want)\s+(?:to\s+)?ask\s+(?:another\s+)?agent",
        r"(?:can|could)\s+(?:some)?one\s+(?:help|assist)",
        r"(?:question|help)\s+(?:for|about)",
    ],
    "answer": [
        r"(?:sub-agent|subagent)\s+(?:says?|respond|replied|report)",
        r"(?:agent)\s+(?:responded|replied|said)",
        r"(?:completed|finished|done)\s+(?:by|from)\s+(?:agent|sub-agent|subagent)",
    ],
    "spawn": [
        r"sessions?_spawn",
        r"spawn.*agent",
        r"subagent.*spawned",
        r"(?:child|sub).*session.*started",
    ]
}


def get_timestamp() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def load_collector_state() -> dict[str, Any]:
    """Load the collector state (last read positions per file)."""
    state = {
        "files": {},  # filename -> {"last_position": int, "last_modified": float}
        "version": 1,
    }
    
    try:
        if os.path.exists(CONFIG["state_file"]):
            with open(CONFIG["state_file"], 'r') as f:
                state = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"[MessageCollector] Warning: Could not load state file: {e}")
    
    return state


def save_collector_state(state: dict[str, Any]) -> None:
    """Save the collector state."""
    try:
        os.makedirs(os.path.dirname(CONFIG["state_file"]), exist_ok=True)
        with open(CONFIG["state_file"], 'w') as f:
            json.dump(state, f, indent=2)
    except IOError as e:
        print(f"[MessageCollector] Error saving state: {e}")


def load_existing_messages() -> list[dict]:
    """Load existing messages from the output file."""
    messages = []
    
    try:
        if os.path.exists(CONFIG["output_file"]):
            with open(CONFIG["output_file"], 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            messages.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
    except IOError as e:
        print(f"[MessageCollector] Error loading existing messages: {e}")
    
    return messages


def save_messages(messages: list[dict]) -> None:
    """Save messages to the output file (keep only last max_messages)."""
    try:
        os.makedirs(os.path.dirname(CONFIG["output_file"]), exist_ok=True)
        
        # Keep only the last max_messages
        messages_to_keep = messages[-CONFIG["max_messages"]:]
        
        with open(CONFIG["output_file"], 'w') as f:
            for msg in messages_to_keep:
                f.write(json.dumps(msg) + '\n')
                
    except IOError as e:
        print(f"[MessageCollector] Error saving messages: {e}")


def get_session_info() -> dict[str, dict]:
    """Get session metadata from sessions.json."""
    sessions_info = {}
    
    try:
        if os.path.exists(CONFIG["sessions_file"]):
            with open(CONFIG["sessions_file"], 'r') as f:
                data = json.load(f)
            
            for session_key, session_data in data.items():
                session_id = session_data.get("sessionId", "")
                sessions_info[session_id] = {
                    "key": session_key,
                    "label": session_data.get("label", session_key.split(":")[-1] if ":" in session_key else session_key),
                    "spawned_by": session_data.get("spawnedBy"),
                    "channel": session_data.get("lastChannel", "unknown"),
                    "model": session_data.get("model", "unknown"),
                }
    except (json.JSONDecodeError, IOError) as e:
        print(f"[MessageCollector] Error reading sessions.json: {e}")
    
    return sessions_info


def detect_communication_type(text: str) -> str | None:
    """Detect the type of communication based on patterns."""
    text_lower = text.lower()
    
    for msg_type, patterns in COMMUNICATION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return msg_type
    
    return None


def extract_agent_name_from_session_key(session_key: str) -> str:
    """Extract a readable agent name from session key."""
    if not session_key:
        return "unknown"
    
    # Handle different session key formats
    if "subagent" in session_key:
        # agent:main:subagent:xxx -> subagent-xxx
        parts = session_key.split(":")
        if len(parts) >= 4:
            return f"subagent-{parts[3][:8]}"
    
    if "cron" in session_key:
        # agent:main:cron:xxx -> cron-xxx
        parts = session_key.split(":")
        if len(parts) >= 4:
            return f"cron-{parts[3][:8]}"
    
    if "main:main" in session_key:
        return "main-agent"
    
    # Default: return last part or truncated key
    parts = session_key.split(":")
    return parts[-1][:20] if parts else session_key[:20]


def parse_session_file(
    filepath: Path,
    file_state: dict,
    sessions_info: dict[str, dict]
) -> list[dict]:
    """
    Parse a session transcript file and extract communication messages.
    Returns list of new messages found.
    """
    new_messages = []
    
    try:
        # Get current file stats
        stat = filepath.stat()
        current_size = stat.st_size
        current_mtime = stat.st_mtime
        
        # Check if file has been modified since last read
        last_position = file_state.get("last_position", 0)
        last_mtime = file_state.get("last_modified", 0)
        
        # If file was modified or rotated (smaller than before), reset position
        if current_mtime < last_mtime or current_size < last_position:
            last_position = 0
            print(f"[MessageCollector] File rotated or modified: {filepath.name}")
        
        # If no new content, skip
        if current_size <= last_position:
            return new_messages
        
        # Get session info for this file
        session_id = filepath.stem.replace(".jsonl", "")
        session_info = sessions_info.get(session_id, {})
        session_key = session_info.get("key", "unknown")
        agent_name = extract_agent_name_from_session_key(session_key)
        
        # Read new lines from the file
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            # Seek to last position
            f.seek(last_position)
            
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                # Parse different message types
                messages = extract_messages_from_entry(msg, agent_name, session_key, sessions_info)
                new_messages.extend(messages)
            
            # Update position to current end of file
            new_position = f.tell()
        
        # Update file state
        file_state["last_position"] = new_position
        file_state["last_modified"] = current_mtime
        
    except IOError as e:
        print(f"[MessageCollector] Error reading {filepath}: {e}")
    
    return new_messages


def extract_messages_from_entry(
    msg: dict,
    agent_name: str,
    session_key: str,
    sessions_info: dict[str, dict]
) -> list[dict]:
    """Extract communication messages from a single transcript entry."""
    messages = []
    
    msg_type = msg.get("type", "")
    timestamp = msg.get("timestamp", get_timestamp())
    
    # Handle session spawn events (custom type in session transcripts)
    if msg_type == "custom" and msg.get("customType") == "model-snapshot":
        # This is a session start/spawn event
        parent_id = msg.get("parentId")
        if parent_id:
            messages.append({
                "timestamp": timestamp,
                "from": agent_name,
                "to": "subagent",
                "message": f"Spawned new subagent session",
                "type": "spawn"
            })
    
    # Handle regular messages
    if msg_type == "message":
        message_data = msg.get("message", {})
        content = message_data.get("content", [])
        
        # Extract text from content
        full_text = ""
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    full_text += item.get("text", "")
                elif item.get("type") == "thinking":
                    full_text += item.get("thinking", "")
        
        if not full_text:
            return messages
        
        # Detect communication patterns
        comm_type = detect_communication_type(full_text)
        
        if comm_type:
            # Determine target agent
            to_agent = "unknown"
            
            # Try to extract target from text
            target_match = re.search(
                r"(?:to|from|ask|delegate)\s+(?:agent|sub[-]?agent)?\s*['\"]?([a-zA-Z0-9_-]+)['\"]?",
                full_text.lower()
            )
            if target_match:
                to_agent = target_match.group(1)
            else:
                to_agent = "subagent" if comm_type in ["delegate", "spawn"] else "another-agent"
            
            # Create message (truncate if too long)
            summary = full_text[:200] + "..." if len(full_text) > 200 else full_text
            
            messages.append({
                "timestamp": timestamp,
                "from": agent_name,
                "to": to_agent,
                "message": summary,
                "type": comm_type
            })
        
        # Also check for explicit subagent references in tool calls
        for item in content:
            if isinstance(item, dict) and item.get("type") == "toolCall":
                tool_name = item.get("name", "")
                if tool_name == "sessions_spawn":
                    args = item.get("arguments", {})
                    task = args.get("task", "")[:100]
                    label = args.get("label", "subagent")
                    
                    messages.append({
                        "timestamp": timestamp,
                        "from": agent_name,
                        "to": label,
                        "message": f"Spawned subagent: {task}" if task else "Spawned subagent",
                        "type": "spawn"
                    })
    
    return messages


def detect_spawn_relationships(sessions_info: dict[str, dict]) -> list[dict]:
    """Detect agent spawn relationships from sessions.json."""
    messages = []
    
    for session_id, info in sessions_info.items():
        spawned_by = info.get("spawned_by")
        if spawned_by:
            # Find the parent session
            parent_info = sessions_info.get(spawned_by, {})
            parent_name = extract_agent_name_from_session_key(
                parent_info.get("key", spawned_by)
            )
            child_name = extract_agent_name_from_session_key(
                info.get("key", session_id)
            )
            
            messages.append({
                "timestamp": get_timestamp(),
                "from": parent_name,
                "to": child_name,
                "message": f"Spawned subagent for task: {info.get('label', 'unknown task')}",
                "type": "spawn"
            })
    
    return messages


def collect_messages() -> list[dict]:
    """Main collection function - gather all agent messages."""
    print(f"[{get_timestamp()}] MessageCollector: Starting collection...")
    
    # Load state and existing messages
    state = load_collector_state()
    existing_messages = load_existing_messages()
    
    # Get session metadata
    sessions_info = get_session_info()
    
    # Track new messages
    all_new_messages = []
    
    # Parse all session transcript files
    sessions_dir = Path(CONFIG["sessions_dir"])
    if sessions_dir.exists():
        for jsonl_file in sessions_dir.glob("*.jsonl"):
            # Skip lock files and deleted files (files with multiple suffixes like .jsonl.lock or .jsonl.deleted)
            if len(jsonl_file.suffixes) > 1 or ".deleted" in jsonl_file.name or ".lock" in jsonl_file.name:
                continue
            
            file_state = state["files"].get(jsonl_file.name, {})
            new_messages = parse_session_file(jsonl_file, file_state, sessions_info)
            
            if new_messages:
                all_new_messages.extend(new_messages)
                print(f"[MessageCollector] {jsonl_file.name}: {len(new_messages)} new messages")
            
            # Update state for this file
            state["files"][jsonl_file.name] = file_state
    
    # Add spawn relationships from sessions.json
    spawn_messages = detect_spawn_relationships(sessions_info)
    
    # Filter out duplicates (same from/to/message within last minute)
    seen = set()
    unique_spawn_messages = []
    for msg in spawn_messages:
        key = (msg["from"], msg["to"], msg["message"][:50])
        if key not in seen:
            seen.add(key)
            unique_spawn_messages.append(msg)
    
    all_new_messages.extend(unique_spawn_messages)
    
    # Combine with existing messages
    all_messages = existing_messages + all_new_messages
    
    # Trim to max size
    if len(all_messages) > CONFIG["max_messages"]:
        all_messages = all_messages[-CONFIG["max_messages"]:]
    
    # Save updated messages and state
    save_messages(all_messages)
    save_collector_state(state)
    
    print(f"[{get_timestamp()}] MessageCollector: Collected {len(all_new_messages)} new messages, total {len(all_messages)}")
    
    return all_messages


def get_messages_for_api() -> list[dict]:
    """Get current messages for the API response."""
    return load_existing_messages()


if __name__ == "__main__":
    # Run once when called directly
    collect_messages()
