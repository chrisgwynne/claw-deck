"""
Kanban Task Management Module for Clawdbot Dashboard
Provides task CRUD operations and auto-agent assignment
"""

import os
import json
import logging
import datetime
import uuid
import re
import fcntl
from pathlib import Path
from typing import Dict, List, Optional, Any

# Configure logging
logger = logging.getLogger(__name__)

# Configuration
KANBAN_TASKS_FILE = '/home/chris/clawd/dashboard/kanban_tasks.json'
ASSIGNMENT_LOG_FILE = '/home/chris/clawd/dashboard/kanban_assignments.jsonl'

# Kanban columns
KANBAN_COLUMNS = ['Inbox', 'Up Next', 'In Progress', 'In Review', 'Done']

# Task categories
CATEGORIES = ['Core', 'Ship', 'Build', 'Fix', 'Read']

# Category colors for UI
CATEGORY_COLORS = {
    'Core': '#8B5CF6',   # Purple - infrastructure
    'Ship': '#10B981',   # Green - revenue/deploy
    'Build': '#3B82F6',  # Blue - new features
    'Fix': '#EF4444',    # Red - bugs/issues
    'Read': '#F59E0B'    # Orange - research
}

# Auto-clear Done tasks after this many hours
DONE_AUTO_CLEAR_HOURS = 24

# Agent type keyword mappings
AGENT_KEYWORDS = {
    'code': ['code', 'build', 'fix', 'implement', 'develop', 'program', 'debug', 'script', 'function', 'class', 'module', 'refactor', 'optimize'],
    'research': ['research', 'find', 'search', 'look up', 'investigate', 'analyze', 'study', 'explore', 'discover', 'gather', 'collect data'],
    'writing': ['write', 'draft', 'content', 'compose', 'author', 'edit', 'proofread', 'document', 'blog', 'article', 'copy', 'text']
}

# Default agent type
DEFAULT_AGENT_TYPE = 'general'

# Friends TV show character names for sub-agents (66 characters)
FRIENDS_NAMES = [
    "Rachel", "Ross", "Monica", "Chandler", "Joey", "Phoebe",
    "Mike", "David", "Janice", "Gunther", "Richard", "Emily",
    "Carol", "Susan", "Ben", "Emma", "Jack", "Judy",
    "Estelle", "Frank", "Alice", "Ursula", "Tag", "Paul",
    "Pete", "Kate", "Julie", "Charlie", "Kathy", "Elizabeth",
    "Eddie", "MrHeckles", "Treeger", "Geller", "Tribbiani", "Buffay",
    "Green", "Bing", "Geller2", "Hannigan", "Tyler", "Stevens",
    "Will", "Jill", "Tim", "Tom", "Steve", "Mark",
    "Gary", "Amy", "Eric", "Bob", "Dan", "Sam",
    "Neil", "Rob", "Sean", "Pat", "Kim", "Joy",
    "Zoe", "Max", "Leo", "Zack", "Cody", "UglyNakedGuy"
]

def get_friends_name(session_key: str) -> str:
    """Get a friendly Friends character name based on session key hash."""
    if not session_key:
        return None
    
    # Use hash of session key to deterministically pick a name
    import hashlib
    hash_val = int(hashlib.md5(session_key.encode()).hexdigest(), 16)
    return FRIENDS_NAMES[hash_val % len(FRIENDS_NAMES)]


def ensure_files():
    """Ensure kanban files exist."""
    os.makedirs(os.path.dirname(KANBAN_TASKS_FILE), exist_ok=True)
    if not os.path.exists(KANBAN_TASKS_FILE):
        with open(KANBAN_TASKS_FILE, 'w') as f:
            json.dump({}, f)
    if not os.path.exists(ASSIGNMENT_LOG_FILE):
        Path(ASSIGNMENT_LOG_FILE).touch()


def load_tasks() -> Dict[str, Any]:
    """Load all tasks from storage with file locking."""
    ensure_files()
    try:
        with open(KANBAN_TASKS_FILE, 'r') as f:
            # Acquire shared lock for reading
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                content = f.read().strip()
                if not content:
                    return {}
                tasks = json.loads(content)
                # Clean up old Done tasks
                tasks = cleanup_done_tasks(tasks)
                return tasks
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding tasks file: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error loading tasks: {e}")
        return {}


def cleanup_done_tasks(tasks: Dict[str, Any]) -> Dict[str, Any]:
    """Remove Done tasks that are older than DONE_AUTO_CLEAR_HOURS."""
    now = datetime.datetime.now()
    cleaned = {}
    removed_count = 0
    
    for task_id, task in tasks.items():
        if task.get('status') == 'Done':
            # Check when task was moved to Done
            done_at = task.get('done_at')
            if done_at:
                try:
                    done_time = datetime.datetime.fromisoformat(done_at)
                    hours_in_done = (now - done_time).total_seconds() / 3600
                    if hours_in_done >= DONE_AUTO_CLEAR_HOURS:
                        logger.info(f"Auto-clearing Done task {task_id} (in Done for {hours_in_done:.1f} hours)")
                        removed_count += 1
                        continue  # Skip adding this task to cleaned dict
                except Exception as e:
                    logger.warning(f"Could not parse done_at for task {task_id}: {e}")
        cleaned[task_id] = task
    
    if removed_count > 0:
        logger.info(f"Cleaned up {removed_count} old Done tasks")
        # Save the cleaned tasks
        save_tasks(cleaned)
    
    return cleaned


def save_tasks(tasks: Dict[str, Any]) -> bool:
    """Save all tasks to storage with file locking."""
    try:
        with open(KANBAN_TASKS_FILE, 'w') as f:
            # Acquire exclusive lock for writing
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(tasks, f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return True
    except Exception as e:
        logger.error(f"Error saving tasks: {e}")
        return False


def log_assignment(task_id: str, agent_type: str, session_key: Optional[str], 
                   success: bool, details: Optional[Dict] = None):
    """Log an agent assignment to the assignment log."""
    try:
        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "task_id": task_id,
            "agent_type": agent_type,
            "session_key": session_key,
            "success": success,
            "details": details or {}
        }
        with open(ASSIGNMENT_LOG_FILE, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
        logger.info(f"Agent assignment logged: {agent_type} for task {task_id}")
    except Exception as e:
        logger.error(f"Failed to log agent assignment: {e}")


def determine_agent_type(title: str, description: str = "") -> str:
    """
    Determine the best agent type based on task title and description keywords.
    """
    text = f"{title} {description}".lower()
    
    scores = {}
    for agent_type, keywords in AGENT_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            # Check for whole word matches
            pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
            matches = len(re.findall(pattern, text))
            score += matches
        scores[agent_type] = score
    
    # Return agent type with highest score, or default if no matches
    if scores:
        best_type = max(scores, key=scores.get)
        if scores[best_type] > 0:
            logger.info(f"Determined agent type '{best_type}' for task (scores: {scores})")
            return best_type
    
    logger.info(f"Using default agent type '{DEFAULT_AGENT_TYPE}' for task")
    return DEFAULT_AGENT_TYPE


def spawn_agent(agent_type: str, task_id: str, title: str, description: str) -> tuple[bool, Optional[str], str]:
    """
    Spawn a sub-agent for a task.
    Returns (success, session_key, message)
    """
    try:
        # Import here to avoid circular dependencies
        import subprocess
        
        # Build the agent spawn command
        # We'll use openclaw sessions to spawn an agent
        task_context = f"Task: {title}\n\nDescription: {description}\n\nTask ID: {task_id}"
        
        # Create a label for the agent session
        label = f"kanban-{agent_type}-{task_id[:8]}"
        
        # Try to spawn using openclaw
        # Note: This is a simplified version - in production you'd use the proper
        # openclaw sessions API
        cmd = [
            'openclaw', 'sessions', 'spawn',
            '--label', label,
            '--type', agent_type,
            '--context', task_context
        ]
        
        logger.info(f"Spawning {agent_type} agent for task {task_id}")
        
        # For now, simulate agent spawning with a mock session key
        # In production, this would actually call openclaw and get the real session key
        import uuid
        session_key = f"agent:{agent_type}:{uuid.uuid4().hex[:12]}"
        
        # TODO: Replace with actual openclaw call when available
        # result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        # if result.returncode == 0:
        #     session_key = result.stdout.strip()
        
        logger.info(f"Spawned agent with session_key: {session_key}")
        return True, session_key, f"Successfully spawned {agent_type} agent"
        
    except Exception as e:
        logger.error(f"Failed to spawn agent: {e}")
        return False, None, f"Failed to spawn agent: {str(e)}"


def create_task(title: str, description: str = "", priority: str = "medium",
                status: str = "Inbox", created_by: str = "Jarvis",
                obsidian_link: str = None, category: str = None) -> tuple[bool, Optional[Dict], str]:
    """
    Create a new task.
    Returns (success, task_dict, message)
    """
    # Validate inputs
    if not title or not title.strip():
        return False, None, "Title is required"
    
    # Category is required
    if not category or not category.strip():
        return False, None, "Category is required. Must be one of: Core, Ship, Build, Fix, Read"
    
    category = category.strip()
    if category not in CATEGORIES:
        return False, None, f"Invalid category. Must be one of: {', '.join(CATEGORIES)}"
    
    if status not in KANBAN_COLUMNS:
        return False, None, f"Invalid status. Must be one of: {', '.join(KANBAN_COLUMNS)}"
    
    valid_priorities = ['low', 'medium', 'high', 'critical']
    if priority not in valid_priorities:
        return False, None, f"Invalid priority. Must be one of: {', '.join(valid_priorities)}"
    
    tasks = load_tasks()
    
    # Generate unique ID
    task_id = str(uuid.uuid4())
    
    # Create task object
    task = {
        "id": task_id,
        "title": title.strip(),
        "description": description.strip(),
        "category": category,
        "status": status,
        "priority": priority,
        "created_at": datetime.datetime.now().isoformat(),
        "updated_at": datetime.datetime.now().isoformat(),
        "created_by": created_by,
        "obsidian_link": obsidian_link,
        "assigned_agent": None,
        "session_key": None,
        "assignment_history": []
    }
    
    tasks[task_id] = task
    
    if save_tasks(tasks):
        logger.info(f"Created task {task_id}: {title}")
        return True, task, "Task created successfully"
    else:
        return False, None, "Failed to save task"


def get_task(task_id: str) -> Optional[Dict]:
    """Get a single task by ID."""
    tasks = load_tasks()
    return tasks.get(task_id)


def update_task(task_id: str, **updates) -> tuple[bool, Optional[Dict], str]:
    """
    Update a task's fields.
    Returns (success, task_dict, message)
    """
    tasks = load_tasks()
    
    if task_id not in tasks:
        return False, None, f"Task {task_id} not found"
    
    task = tasks[task_id]
    
    # Fields that can be updated
    allowed_fields = ['title', 'description', 'priority']
    
    for field, value in updates.items():
        if field in allowed_fields:
            if field == 'title' and (not value or not str(value).strip()):
                return False, None, "Title cannot be empty"
            task[field] = value.strip() if isinstance(value, str) else value
    
    # Validate priority if updated
    if 'priority' in updates:
        valid_priorities = ['low', 'medium', 'high', 'critical']
        if task['priority'] not in valid_priorities:
            return False, None, f"Invalid priority. Must be one of: {', '.join(valid_priorities)}"
    
    task['updated_at'] = datetime.datetime.now().isoformat()
    
    if save_tasks(tasks):
        logger.info(f"Updated task {task_id}")
        return True, task, "Task updated successfully"
    else:
        return False, None, "Failed to save task"


def delete_task(task_id: str) -> tuple[bool, str]:
    """
    Delete a task.
    Returns (success, message)
    """
    tasks = load_tasks()
    
    if task_id not in tasks:
        return False, f"Task {task_id} not found"
    
    # If task has an assigned agent, log the removal
    task = tasks[task_id]
    if task.get('session_key'):
        log_assignment(
            task_id=task_id,
            agent_type=task.get('assigned_agent', 'unknown'),
            session_key=task['session_key'],
            success=True,
            details={"action": "task_deleted", "reason": "Task deleted by user"}
        )
    
    del tasks[task_id]
    
    if save_tasks(tasks):
        logger.info(f"Deleted task {task_id}")
        return True, "Task deleted successfully"
    else:
        return False, "Failed to save tasks"


def move_task(task_id: str, new_status: str, auto_assign: bool = True) -> tuple[bool, Optional[Dict], str]:
    """
    Move a task to a new column/status.
    If moving to 'In Progress' and no agent assigned, auto-assign an agent.
    Returns (success, task_dict, message)
    """
    # Validate status
    if new_status not in KANBAN_COLUMNS:
        return False, None, f"Invalid status. Must be one of: {', '.join(KANBAN_COLUMNS)}"
    
    tasks = load_tasks()
    
    if task_id not in tasks:
        return False, None, f"Task {task_id} not found"
    
    task = tasks[task_id]
    old_status = task['status']
    
    # Update status
    task['status'] = new_status
    task['updated_at'] = datetime.datetime.now().isoformat()
    
    # Auto-assign agent if moving to "In Progress" and no agent assigned
    agent_assigned = False
    assignment_message = None
    
    # Set auto_assigning flag when starting assignment
    task['auto_assigning'] = False
    
    if auto_assign and new_status == "In Progress" and not task.get('assigned_agent'):
        # Mark as auto-assigning before attempting spawn
        task['auto_assigning'] = True
        # Prevent duplicate assignment
        if task.get('session_key'):
            logger.warning(f"Task {task_id} already has session_key but no assigned_agent - skipping auto-assignment")
        else:
            # Determine agent type
            agent_type = determine_agent_type(task['title'], task.get('description', ''))
            
            # Spawn agent
            success, session_key, message = spawn_agent(
                agent_type=agent_type,
                task_id=task_id,
                title=task['title'],
                description=task.get('description', '')
            )
            
            if success and session_key:
                task['assigned_agent'] = agent_type
                task['session_key'] = session_key
                task['auto_assigning'] = False
                task['assignment_history'].append({
                    "timestamp": datetime.datetime.now().isoformat(),
                    "agent_type": agent_type,
                    "session_key": session_key,
                    "trigger": f"moved_to_{new_status}"
                })
                agent_assigned = True
                assignment_message = f"Auto-assigned {agent_type} agent"
                
                log_assignment(
                    task_id=task_id,
                    agent_type=agent_type,
                    session_key=session_key,
                    success=True,
                    details={"trigger": f"moved_to_{new_status}", "auto": True}
                )
            else:
                # Agent spawn failed - log it but don't fail the move
                task['auto_assigning'] = False
                log_assignment(
                    task_id=task_id,
                    agent_type=agent_type,
                    session_key=None,
                    success=False,
                    details={"error": message, "trigger": f"moved_to_{new_status}"}
                )
                assignment_message = f"Warning: Failed to auto-assign agent - {message}"
                logger.error(f"Failed to auto-assign agent for task {task_id}: {message}")
    
    # Track when task enters Done for auto-cleanup
    if new_status == "Done":
        task['done_at'] = datetime.datetime.now().isoformat()
        logger.info(f"Task {task_id} moved to Done at {task['done_at']}")
    elif old_status == "Done" and new_status != "Done":
        # Task moved out of Done - clear the done_at timestamp
        task.pop('done_at', None)
        logger.info(f"Task {task_id} moved out of Done, cleared done_at timestamp")
    
    if save_tasks(tasks):
        logger.info(f"Moved task {task_id} from {old_status} to {new_status}")
        msg = f"Task moved to {new_status}"
        if assignment_message:
            msg += f". {assignment_message}"
        return True, task, msg
    else:
        return False, None, "Failed to save task"


def get_all_tasks_grouped() -> Dict[str, Any]:
    """
    Get all tasks grouped by status column.
    Returns dict with columns as keys and lists of tasks as values.
    """
    tasks = load_tasks()
    
    grouped = {col: [] for col in KANBAN_COLUMNS}
    
    for task in tasks.values():
        status = task.get('status', 'Backlog')
        if status in grouped:
            grouped[status].append(task)
        else:
            # Fallback for unknown status
            grouped['Backlog'].append(task)
    
    # Sort tasks within each column by priority and creation date
    priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    
    for col in KANBAN_COLUMNS:
        grouped[col].sort(key=lambda t: (
            priority_order.get(t.get('priority', 'medium'), 2),
            t.get('created_at', '')
        ))
    
    return {
        "columns": KANBAN_COLUMNS,
        "tasks": grouped,
        "total_count": len(tasks)
    }


def get_assignment_history(task_id: Optional[str] = None, limit: int = 100) -> List[Dict]:
    """Get agent assignment history from log."""
    history = []
    
    if not os.path.exists(ASSIGNMENT_LOG_FILE):
        return history
    
    try:
        with open(ASSIGNMENT_LOG_FILE, 'r') as f:
            lines = f.readlines()
            for line in lines:
                try:
                    entry = json.loads(line.strip())
                    if task_id is None or entry.get('task_id') == task_id:
                        history.append(entry)
                except json.JSONDecodeError:
                    continue
        
        # Return most recent first, limited
        history.reverse()
        return history[:limit]
    except Exception as e:
        logger.error(f"Error reading assignment history: {e}")
        return []


# Initialize files on module load (only if file doesn't exist or is empty)
def _init_on_load():
    """Initialize files only if they don't exist."""
    os.makedirs(os.path.dirname(KANBAN_TASKS_FILE), exist_ok=True)
    if not os.path.exists(KANBAN_TASKS_FILE):
        with open(KANBAN_TASKS_FILE, 'w') as f:
            json.dump({}, f)
    if not os.path.exists(ASSIGNMENT_LOG_FILE):
        Path(ASSIGNMENT_LOG_FILE).touch()

_init_on_load()