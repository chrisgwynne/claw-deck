// Clawdbot Dashboard Frontend - Modo Lite UI
const API_URL = '/api/state';
const CONTROL_API_URL = '/api/control';
const KANBAN_API_URL = '/api/kanban';

let allTasks = [];
let draggedTask = null;
let dragSourceElement = null;
let deleteTaskId = null;
let autoModeEnabled = true;

// Status mapping between frontend and backend
const STATUS_MAP = {
    'inbox': 'Inbox',
    'up_next': 'Up Next',
    'in_progress': 'In Progress',
    'in_review': 'In Review',
    'done': 'Done'
};

const STATUS_MAP_REVERSE = {
    'Inbox': 'inbox',
    'Up Next': 'up_next',
    'In Progress': 'in_progress',
    'In Review': 'in_review',
    'Done': 'done'
};

// Initialize dashboard
document.addEventListener('DOMContentLoaded', initDashboard);

async function initDashboard() {
    console.log('[Dashboard] Initializing Modo Lite UI...');
    
    // Check if refresh indicator exists
    const refreshEl = document.getElementById('refresh-indicator');
    const lastRefreshedEl = document.getElementById('last-refreshed');
    console.log('[Dashboard] Refresh indicator:', refreshEl ? 'found' : 'NOT FOUND');
    console.log('[Dashboard] Last refreshed element:', lastRefreshedEl ? 'found' : 'NOT FOUND');
    
    // Load both views
    await Promise.all([
        loadDashboardData(),
        loadKanbanTasks()
    ]);
    
    setupDragAndDrop();
    setupKeyboardShortcuts();
    setupAutoToggle();
    
    // Auto-refresh every 5 seconds
    setInterval(() => {
        loadDashboardData();
        loadKanbanTasks();
        updateLastRefreshed();
    }, 5000);
    
    // Update refresh indicator
    updateLastRefreshed();
    
    console.log('[Dashboard] Initialization complete');
}

// ==================== Tab Switching ====================
function switchTab(tab) {
    const dashboardView = document.getElementById('dashboard-view');
    const kanbanView = document.getElementById('kanban-view');
    const dashboardTab = document.getElementById('tab-dashboard');
    const kanbanTab = document.getElementById('tab-kanban');
    
    if (tab === 'dashboard') {
        dashboardView.classList.remove('hidden');
        kanbanView.classList.add('hidden');
        dashboardTab.classList.add('border-modo-blue', 'text-white');
        dashboardTab.classList.remove('border-transparent', 'text-modo-gray');
        kanbanTab.classList.remove('border-modo-blue', 'text-white');
        kanbanTab.classList.add('border-transparent', 'text-modo-gray');
    } else {
        dashboardView.classList.add('hidden');
        kanbanView.classList.remove('hidden');
        kanbanTab.classList.add('border-modo-blue', 'text-white');
        kanbanTab.classList.remove('border-transparent', 'text-modo-gray');
        dashboardTab.classList.remove('border-modo-blue', 'text-white');
        dashboardTab.classList.add('border-transparent', 'text-modo-gray');
    }
}

// ==================== Dashboard Data Loading ====================
async function loadDashboardData() {
    try {
        const response = await fetch(API_URL);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const result = await response.json();
        const data = result.data || result;
        
        console.log('[Dashboard] Data loaded, messages count:', data.messages?.length || 0);
        
        renderDashboard(data);
    } catch (err) {
        console.error('[Dashboard] Error loading data:', err);
    }
}

function renderDashboard(data) {
    // System Health
    renderSystemHealth(data.system, data);
    
    // Agents
    renderAgents(data.sessions?.active_sessions || []);
    
    // Messages
    renderAgentMessages(data.messages || []);
    
    // Git Activity
    renderGitActivity(data.git?.commits || []);
    
    // Success Rate (real agent completion rate)
    updateSuccessRate(data);
    
    // Update Kanban alerts (context, killed agents)
    updateKanbanAlerts(data);
    
    // Show agent cleanup info if any agents were killed
    if (data.agent_cleanup && data.agent_cleanup.killed_count > 0) {
        console.log(`[Dashboard] Agent cleanup: ${data.agent_cleanup.killed_count} agents killed`);
    }
}

function updateKanbanAlerts(data) {
    const alertsContainer = document.getElementById('kanban-alerts');
    const contextAlert = document.getElementById('alert-context');
    const killedAlert = document.getElementById('alert-killed');
    
    let hasAlerts = false;
    
    // Context warning (>70%)
    const contextPct = data.context_usage_percent || 0;
    if (contextPct > 70) {
        document.getElementById('alert-context-pct').textContent = Math.round(contextPct);
        contextAlert.classList.remove('hidden');
        hasAlerts = true;
    } else {
        contextAlert.classList.add('hidden');
    }
    
    // Killed agents alert
    const killedCount = data.agent_cleanup?.killed_count || 0;
    if (killedCount > 0) {
        document.getElementById('alert-killed-count').textContent = killedCount;
        killedAlert.classList.remove('hidden');
        hasAlerts = true;
    } else {
        killedAlert.classList.add('hidden');
    }
    
    // Show/hide alerts container
    if (hasAlerts || !document.getElementById('alert-stuck').classList.contains('hidden')) {
        alertsContainer.classList.remove('hidden');
    } else {
        alertsContainer.classList.add('hidden');
    }
}

function updateSuccessRate(data) {
    const successEl = document.getElementById('success-rate');
    if (!successEl) return;
    
    // Use real success rate from API if available
    if (data && data.success_rate && data.success_rate.rate !== null) {
        successEl.textContent = `${data.success_rate.rate}%`;
        successEl.title = `Completed: ${data.success_rate.completed}, Failed: ${data.success_rate.failed}, Killed: ${data.success_rate.killed}`;
        return;
    }
    
    // Fallback: calculate based on task distribution
    const inbox = allTasks.filter(t => t.status === 'inbox').length;
    const upNext = allTasks.filter(t => t.status === 'up_next').length;
    const inProgress = allTasks.filter(t => t.status === 'in_progress').length;
    const inReview = allTasks.filter(t => t.status === 'in_review').length;
    const done = allTasks.filter(t => t.status === 'done').length;
    
    const total = allTasks.length;
    if (total === 0) {
        successEl.textContent = '--';
        return;
    }
    
    const doneWeight = done;
    const progressWeight = (inProgress * 0.5) + (inReview * 0.8);
    const successRate = Math.round(((doneWeight + progressWeight) / total) * 100);
    
    successEl.textContent = `${successRate}%`;
    successEl.title = 'Task-based rate (no agent completion data yet)';
}

function renderSystemHealth(sys, data) {
    // Context Usage (from main session)
    const contextEl = document.getElementById('sys-context');
    const contextBar = document.getElementById('context-bar');
    const contextPct = data?.context_usage_percent || 0;
    if (contextEl) {
        contextEl.textContent = `${contextPct.toFixed(1)}%`;
        if (contextBar) {
            contextBar.style.width = `${Math.min(100, contextPct)}%`;
            contextBar.className = `h-1.5 rounded transition-all ${contextPct > 80 ? 'bg-red-500' : contextPct > 60 ? 'bg-yellow-500' : 'bg-green-500'}`;
        }
    }
    
    // Active Model Mix
    const modelsEl = document.getElementById('sys-models');
    const sessions = data?.sessions?.active_sessions || [];
    if (modelsEl) {
        // Count models by provider
        const modelCounts = {};
        sessions.forEach(s => {
            const provider = s.model_provider || s.model?.split('/')[0] || 'unknown';
            modelCounts[provider] = (modelCounts[provider] || 0) + 1;
        });
        
        // Format: "kimi-code×2, google×1" or just provider names
        const modelMix = Object.entries(modelCounts)
            .map(([provider, count]) => count > 1 ? `${provider}×${count}` : provider)
            .join(', ');
        modelsEl.textContent = modelMix || '--';
    }
    
    // Total Tokens
    const tokensEl = document.getElementById('sys-tokens');
    if (tokensEl) {
        const totalTokens = sessions.reduce((sum, s) => sum + (s.total_tokens || 0), 0);
        if (totalTokens > 1000000) {
            tokensEl.textContent = `${(totalTokens / 1000000).toFixed(2)}M`;
        } else if (totalTokens > 1000) {
            tokensEl.textContent = `${Math.round(totalTokens / 1000)}K`;
        } else {
            tokensEl.textContent = totalTokens.toString();
        }
    }
    
    // Success Rate
    const successEl = document.getElementById('sys-success');
    const successRate = data?.success_rate;
    if (successEl && successRate?.rate !== null) {
        successEl.textContent = `${successRate.rate}%`;
    } else {
        successEl.textContent = '--';
    }
}

function renderAgents(sessions) {
    const container = document.getElementById('agent-cards');
    if (!container) return;
    
    // Update counts
    const totalEl = document.getElementById('agent-total');
    const activeEl = document.getElementById('agent-active');
    if (totalEl) totalEl.textContent = sessions.length;
    if (activeEl) activeEl.textContent = sessions.filter(s => s.total_tokens > 0 || s.channel !== 'unknown').length;
    
    if (sessions.length === 0) {
        container.innerHTML = '<p class="text-modo-gray col-span-2">No active sessions</p>';
        return;
    }
    
    container.innerHTML = sessions.map(s => {
        const status = s.total_tokens > 100 ? 'ACTIVE' : 'IDLE';
        const statusColor = status === 'ACTIVE' ? 'bg-green-600' : 'bg-gray-600';
        const model = s.model || 'unknown';
        const channel = s.channel || 'unknown';
        const label = s.label || 'main';
        
        return `
        <div class="bg-modo-card rounded-lg p-4 border border-white/5">
            <div class="flex justify-between items-start mb-2">
                <div>
                    <h3 class="font-bold text-white">${escapeHtml(label)}</h3>
                    <span class="text-xs text-modo-gray">${escapeHtml(model)} • ${escapeHtml(channel)}</span>
                </div>
                <span class="px-2 py-1 rounded text-xs ${statusColor}">${status}</span>
            </div>
            <div class="text-xs text-modo-gray space-y-1">
                <p>ID: ${s.session_id?.slice(0, 8) || '???'}...</p>
                <p>Tokens: ${(s.total_tokens || 0).toLocaleString()}</p>
                ${s.context_usage_percent ? `<p>Context: ${s.context_usage_percent.toFixed(1)}%</p>` : ''}
            </div>
        </div>
        `;
    }).join('');
}

function renderAgentMessages(messages) {
    const container = document.getElementById('agent-messages');
    if (!container) return;
    
    // Ensure messages is an array
    if (!Array.isArray(messages)) {
        console.error('[Dashboard] messages is not an array:', messages);
        container.innerHTML = '<p class="text-modo-gray text-sm">Error: Invalid messages data</p>';
        return;
    }
    
    if (messages.length === 0) {
        container.innerHTML = '<p class="text-modo-gray text-sm">No messages</p>';
        return;
    }
    
    console.log(`[Dashboard] Rendering ${messages.length} messages`);
    
    try {
        container.innerHTML = messages.slice(-20).map((msg, index) => {
            // Validate message fields
            if (!msg || typeof msg !== 'object') {
                console.warn(`[Dashboard] Invalid message at index ${index}:`, msg);
                return '';
            }
            
            const timestamp = msg.timestamp || null;
            const from = msg.from || 'unknown';
            const to = msg.to || 'unknown';
            const message = msg.message || '';
            
            return `
                <div class="mb-3 pb-3 border-b border-white/5 last:border-0">
                    <div class="flex items-center gap-2 mb-1">
                        <span class="text-xs text-modo-gray">${formatTime(timestamp)}</span>
                        <span class="font-semibold text-modo-purple">${escapeHtml(from)}</span>
                        <span class="text-modo-gray">→</span>
                        <span class="font-semibold text-modo-blue">${escapeHtml(to)}</span>
                    </div>
                    <p class="text-sm text-modo-text">${escapeHtml(message)}</p>
                </div>
            `;
        }).join('');
    } catch (err) {
        console.error('[Dashboard] Error rendering messages:', err);
        container.innerHTML = '<p class="text-modo-gray text-sm">Error rendering messages</p>';
    }
}

function renderGitActivity(commits) {
    const container = document.getElementById('git-activity');
    if (!container) return;
    
    if (commits.length === 0) {
        container.innerHTML = '<p class="text-modo-gray text-sm">No recent commits</p>';
        return;
    }
    
    container.innerHTML = commits.slice(0, 10).map(c => `
        <div class="mb-3 pb-3 border-b border-white/5 last:border-0">
            <div class="flex items-center gap-2 mb-1">
                <span class="font-mono text-xs bg-modo-nav px-2 py-0.5 rounded text-modo-text">${c.short_hash || c.hash?.slice(0,7) || '????'}</span>
                <span class="text-xs text-modo-purple">${escapeHtml(c.author || 'Unknown')}</span>
                <span class="text-xs text-modo-gray">${c.relative_time || ''}</span>
            </div>
            <p class="text-sm text-modo-text">${escapeHtml(c.message || 'No message')}</p>
        </div>
    `).join('');
}

function formatTime(dateStr) {
    if (!dateStr) return '--:--';
    const date = new Date(dateStr);
    return date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// ==================== Refresh Indicator ====================
let lastRefreshTime = Date.now();

function updateLastRefreshed() {
    lastRefreshTime = Date.now();
    const el = document.getElementById('last-refreshed');
    if (el) {
        el.textContent = 'Just now';
    }
}

function formatRelativeTimeShort(timestamp) {
    const now = Date.now();
    const diff = Math.floor((now - timestamp) / 1000);
    
    if (diff < 5) return 'Just now';
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return `${Math.floor(diff / 3600)}h ago`;
}

// Update the indicator text every second
setInterval(() => {
    const el = document.getElementById('last-refreshed');
    if (el) {
        el.textContent = formatRelativeTimeShort(lastRefreshTime);
    }
}, 1000);

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ==================== Auto Toggle ====================
function setupAutoToggle() {
    const toggle = document.getElementById('auto-toggle');
    if (toggle) {
        toggle.addEventListener('change', async (e) => {
            autoModeEnabled = e.target.checked;
            
            // Call API to enable/disable auto mode
            try {
                const response = await fetch(`${CONTROL_API_URL}/auto`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled: autoModeEnabled })
                });
                
                if (response.ok) {
                    showNotification(autoModeEnabled ? '✅ Auto mode enabled' : '⏸️ Auto mode paused', 
                                   autoModeEnabled ? 'success' : 'warning');
                } else {
                    showNotification('Failed to toggle auto mode', 'error');
                    // Revert toggle if failed
                    toggle.checked = !autoModeEnabled;
                    autoModeEnabled = !autoModeEnabled;
                }
            } catch (err) {
                console.error('[Dashboard] Auto toggle error:', err);
                showNotification('Network error toggling auto mode', 'error');
                toggle.checked = !autoModeEnabled;
                autoModeEnabled = !autoModeEnabled;
            }
        });
    }
}

// ==================== Keyboard Shortcuts ====================
function setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Ignore if typing in an input
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
            if (e.key === 'Escape') {
                closeTaskModal();
                closeDeleteModal();
            }
            return;
        }
        
        switch(e.key.toLowerCase()) {
            case 'n':
                e.preventDefault();
                openTaskModal();
                break;
            case 'escape':
                closeTaskModal();
                closeDeleteModal();
                break;
        }
    });
}

// ==================== Kanban API Functions ====================
async function loadKanbanTasks() {
    try {
        const response = await fetch(`${KANBAN_API_URL}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const result = await response.json();
        if (result.status === 'ok' && result.data && result.data.tasks) {
            // Convert backend grouped format to flat array with frontend status
            const grouped = result.data.tasks;
            allTasks = [];
            Object.keys(grouped).forEach(backendStatus => {
                const frontendStatus = toFrontendStatus(backendStatus);
                grouped[backendStatus].forEach(task => {
                    allTasks.push({
                        ...task,
                        status: frontendStatus
                    });
                });
            });
            renderKanban(allTasks);
            
            // Update dashboard task counts
            updateDashboardTaskCounts(grouped);
        }
    } catch (err) {
        console.error('[Dashboard] Error loading tasks:', err);
    }
}

function updateDashboardTaskCounts(grouped) {
    const pendingEl = document.getElementById('task-pending');
    const activeEl = document.getElementById('task-active');
    const completedEl = document.getElementById('task-completed');
    
    const inboxCount = (grouped['Inbox'] || []).length;
    const upNextCount = (grouped['Up Next'] || []).length;
    const inProgressCount = (grouped['In Progress'] || []).length;
    const inReviewCount = (grouped['In Review'] || []).length;
    const doneCount = (grouped['Done'] || []).length;
    
    if (pendingEl) pendingEl.textContent = inboxCount + upNextCount;
    if (activeEl) activeEl.textContent = inProgressCount + inReviewCount;
    if (completedEl) completedEl.textContent = doneCount;
    
    // Update board header counts
    const inboxHeaderEl = document.getElementById('inbox-count');
    const inProgressHeaderEl = document.getElementById('inprogress-count');
    if (inboxHeaderEl) inboxHeaderEl.textContent = inboxCount;
    if (inProgressHeaderEl) inProgressHeaderEl.textContent = inProgressCount;
    
    // Update Kanban stats bar
    const inboxStatEl = document.getElementById('kanban-stat-inbox');
    const upNextStatEl = document.getElementById('kanban-stat-upnext');
    const progressStatEl = document.getElementById('kanban-stat-progress');
    if (inboxStatEl) inboxStatEl.textContent = inboxCount;
    if (upNextStatEl) upNextStatEl.textContent = upNextCount;
    if (progressStatEl) progressStatEl.textContent = inProgressCount;
    
    // Check for stuck tasks (>24h in progress)
    const stuckTasks = (grouped['In Progress'] || []).filter(task => {
        if (!task.updated_at) return false;
        const updated = new Date(task.updated_at);
        const now = new Date();
        const hours = (now - updated) / (1000 * 60 * 60);
        return hours > 24;
    });
    
    const stuckAlert = document.getElementById('alert-stuck');
    const stuckList = document.getElementById('alert-stuck-list');
    const alertsContainer = document.getElementById('kanban-alerts');
    
    if (stuckTasks.length > 0) {
        stuckList.innerHTML = stuckTasks.map(t => `<li>• ${escapeHtml(t.title)}</li>`).join('');
        stuckAlert.classList.remove('hidden');
        alertsContainer.classList.remove('hidden');
    } else {
        stuckAlert.classList.add('hidden');
    }
}

async function createTask(taskData) {
    try {
        const backendData = {
            ...taskData,
            status: toBackendStatus(taskData.status || 'Inbox')
        };
        
        const response = await fetch(`${KANBAN_API_URL}/tasks`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(backendData)
        });
        
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const result = await response.json();
        if (result.status === 'ok') {
            showNotification('Task created successfully', 'success');
            await loadKanbanTasks();
            return true;
        } else {
            throw new Error(result.message || 'Failed to create task');
        }
    } catch (err) {
        console.error('[Dashboard] Error creating task:', err);
        showNotification(`Error: ${err.message}`, 'error');
        return false;
    }
}

async function updateTaskStatus(taskId, newStatus) {
    try {
        const backendStatus = toBackendStatus(newStatus);
        
        const response = await fetch(`${KANBAN_API_URL}/tasks/${taskId}/move`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: backendStatus, auto_assign: autoModeEnabled })
        });
        
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const result = await response.json();
        if (result.status === 'ok') {
            const msg = result.assigned_agent 
                ? `Task moved. Auto-assigned ${result.assigned_agent} agent.` 
                : 'Task moved successfully';
            showNotification(msg, 'success');
            await loadKanbanTasks();
            return true;
        } else {
            throw new Error(result.message || 'Failed to update task');
        }
    } catch (err) {
        console.error('[Dashboard] Error updating task:', err);
        showNotification(`Error: ${err.message}`, 'error');
        renderKanban(allTasks);
        return false;
    }
}

async function deleteTask(taskId) {
    try {
        const response = await fetch(`${KANBAN_API_URL}/tasks/${taskId}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const result = await response.json();
        if (result.status === 'ok') {
            showNotification('Task deleted', 'success');
            await loadKanbanTasks();
            return true;
        } else {
            throw new Error(result.message || 'Failed to delete task');
        }
    } catch (err) {
        console.error('[Dashboard] Error deleting task:', err);
        showNotification(`Error: ${err.message}`, 'error');
        return false;
    }
}

// ==================== Helper Functions ====================
function toBackendStatus(frontendStatus) {
    return STATUS_MAP[frontendStatus] || frontendStatus;
}

function toFrontendStatus(backendStatus) {
    return STATUS_MAP_REVERSE[backendStatus] || backendStatus.toLowerCase().replace(' ', '_');
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatRelativeTime(timestamp) {
    if (!timestamp) return '';
    
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffSecs = Math.floor(diffMs / 1000);
    const diffMins = Math.floor(diffSecs / 60);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);
    
    if (diffSecs < 60) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    
    return date.toLocaleDateString();
}

// ==================== Kanban Rendering ====================
function renderKanban(tasks) {
    const columns = {
        inbox: [],
        up_next: [],
        in_progress: [],
        in_review: [],
        done: []
    };
    
    // Sort tasks into columns
    tasks.forEach(task => {
        const status = task.status || 'inbox';
        if (columns.hasOwnProperty(status)) {
            columns[status].push(task);
        } else {
            columns.inbox.push(task);
        }
    });
    
    // Update column counts
    Object.keys(columns).forEach(status => {
        const countEl = document.getElementById(`count-${status}`);
        if (countEl) countEl.textContent = columns[status].length;
    });
    
    // Update board header counts
    const inboxCountEl = document.getElementById('inbox-count');
    const inProgressEl = document.getElementById('inprogress-count');
    if (inboxCountEl) inboxCountEl.textContent = columns.inbox.length;
    if (inProgressEl) inProgressEl.textContent = columns.in_progress.length;
    
    // Render each column
    Object.keys(columns).forEach(status => {
        const container = document.getElementById(`col-${status}`);
        if (container) {
            container.innerHTML = columns[status].map(task => renderTaskCard(task)).join('');
        }
    });
}

function renderTaskCard(task) {
    // Task card styling per specification:
    // - Background: #1A1F2E (modo-card)
    // - Border-radius: 8px (rounded-lg)
    // - Padding: 12px 16px (p-3)
    // - Border: 1px solid rgba(255,255,255,0.05) (border-white/5)
    // - Text: #E5E7EB, 14px (text-modo-text text-sm)
    // - Status dots: orange (#F59E0B), yellow (#FBBF24), gray (#6B7280)
    
    // Determine status dot color based on task state
    let statusDotColor = 'bg-modo-gray'; // Default/idle
    let statusDotGlow = '';
    
    if (task.assigned_agent && ['in_progress', 'in_review'].includes(task.status)) {
        // Orange: Task has assigned agent and is active
        statusDotColor = 'bg-modo-orange';
        statusDotGlow = 'shadow-[0_0_8px_rgba(245,158,11,0.6)]';
    } else if (task.status === 'up_next' || task.warnings || task.priority === 'high') {
        // Yellow: Task in "Up Next" or has warnings
        statusDotColor = 'bg-modo-yellow';
        statusDotGlow = 'shadow-[0_0_8px_rgba(251,191,36,0.6)]';
    }
    
    // Agent assignment indicator
    let agentHtml = '';
    if (task.assigned_agent) {
        agentHtml = `
            <div class="flex items-center gap-1 text-emerald-400 text-xs" title="Assigned to: ${escapeHtml(task.assigned_agent)}">
                <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clip-rule="evenodd"/>
                </svg>
                <span class="truncate max-w-[60px]">${escapeHtml(task.assigned_agent)}</span>
            </div>
        `;
    } else if (task.auto_assigning) {
        agentHtml = `
            <div class="flex items-center gap-1 text-yellow-400 text-xs" title="Auto-assigning agent...">
                <svg class="w-3 h-3 animate-spin" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd"/>
                </svg>
                <span>Assigning...</span>
            </div>
        `;
    }
    
    return `
        <div class="kanban-card bg-modo-card rounded-lg p-3 border border-white/5 group cursor-pointer"
             draggable="true"
             data-task-id="${task.id}"
             data-task-status="${task.status || 'inbox'}"
             onclick="openTaskViewModal('${task.id}')">
            <div class="flex justify-between items-start mb-2">
                <h4 class="text-modo-text text-sm font-medium leading-snug flex-1 mr-2">${escapeHtml(task.title || 'Untitled')}</h4>
                <button onclick="event.stopPropagation(); confirmDeleteTask('${task.id}')" 
                        class="text-gray-500 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </div>
            ${task.description ? `<p class="text-gray-500 text-xs mb-3 line-clamp-2">${escapeHtml(task.description)}</p>` : ''}
            
            <!-- Status dot based on task state -->
            <div class="flex items-center gap-1.5">
                <span class="w-2 h-2 rounded-full ${statusDotColor} ${statusDotGlow}"></span>
                ${agentHtml || '<span class="text-xs text-gray-600">Unassigned</span>'}
            </div>
        </div>
    `;
}

// ==================== Drag and Drop ====================
function setupDragAndDrop() {
    document.addEventListener('dragstart', handleDragStart);
    document.addEventListener('dragend', handleDragEnd);
    document.addEventListener('dragover', handleDragOver);
    document.addEventListener('dragenter', handleDragEnter);
    document.addEventListener('dragleave', handleDragLeave);
    document.addEventListener('drop', handleDrop);
}

function handleDragStart(e) {
    const card = e.target.closest('.kanban-card');
    if (!card) return;
    
    draggedTask = {
        id: card.dataset.taskId,
        status: card.dataset.taskStatus
    };
    dragSourceElement = card;
    
    // Visual feedback: opacity 0.8, shadow
    card.classList.add('dragging');
    card.style.opacity = '0.8';
    card.style.boxShadow = '0 10px 30px rgba(0, 0, 0, 0.5)';
    
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', card.dataset.taskId);
    
    const rect = card.getBoundingClientRect();
    e.dataTransfer.setDragImage(card, rect.width / 2, 20);
}

function handleDragEnd(e) {
    const card = e.target.closest('.kanban-card');
    if (card) {
        card.classList.remove('dragging');
        card.style.opacity = '';
        card.style.boxShadow = '';
    }
    
    document.querySelectorAll('.kanban-dropzone').forEach(zone => {
        zone.classList.remove('drag-over');
    });
    
    draggedTask = null;
    dragSourceElement = null;
}

function handleDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
}

function handleDragEnter(e) {
    const dropzone = e.target.closest('.kanban-dropzone');
    if (dropzone && draggedTask) {
        dropzone.classList.add('drag-over');
    }
}

function handleDragLeave(e) {
    const dropzone = e.target.closest('.kanban-dropzone');
    if (dropzone) {
        if (!dropzone.contains(e.relatedTarget)) {
            dropzone.classList.remove('drag-over');
        }
    }
}

function handleDrop(e) {
    e.preventDefault();
    
    const dropzone = e.target.closest('.kanban-dropzone');
    if (!dropzone || !draggedTask) return;
    
    dropzone.classList.remove('drag-over');
    
    const newStatus = dropzone.dataset.status;
    if (newStatus && newStatus !== draggedTask.status) {
        if (dragSourceElement) {
            dragSourceElement.dataset.taskStatus = newStatus;
            dropzone.appendChild(dragSourceElement);
        }
        updateTaskStatus(draggedTask.id, newStatus);
    }
}

// ==================== Task View Modal ====================
let currentViewTaskId = null;

function openTaskViewModal(taskId) {
    const task = allTasks.find(t => t.id === taskId);
    if (!task) return;
    
    currentViewTaskId = taskId;
    
    // Task Name
    document.getElementById('view-task-title').textContent = task.title || 'Untitled';
    
    // Task Description
    const descContainer = document.getElementById('view-task-description-container');
    const descEl = document.getElementById('view-task-description');
    if (task.description) {
        descEl.textContent = task.description;
        descContainer.classList.remove('hidden');
    } else {
        descContainer.classList.add('hidden');
    }
    
    // Obsidian Link
    const obsidianContainer = document.getElementById('view-task-obsidian-container');
    const obsidianLink = document.getElementById('view-task-obsidian-link');
    if (task.obsidian_link) {
        obsidianLink.href = task.obsidian_link;
        obsidianContainer.classList.remove('hidden');
    } else {
        obsidianContainer.classList.add('hidden');
    }
    
    // Creator (Jarvis or Chris)
    const creatorEl = document.getElementById('view-task-creator');
    const createdBy = task.created_by || 'Jarvis';
    const creatorEmoji = createdBy === 'Chris' ? '👤' : '🤖';
    const creatorColor = createdBy === 'Chris' ? 'text-blue-400' : 'text-purple-400';
    creatorEl.innerHTML = `
        <span class="text-lg">${creatorEmoji}</span>
        <span class="${creatorColor} font-medium">${createdBy}</span>
    `;
    
    // Time Added (friendly format)
    document.getElementById('view-task-time').textContent = formatFriendlyTime(task.created_at);
    
    // Status
    document.getElementById('view-task-status').textContent = STATUS_MAP[task.status] || task.status || 'Inbox';
    
    // Priority
    document.getElementById('view-task-priority').textContent = task.priority || 'Medium';
    
    // Assigned Agent
    const assignedContainer = document.getElementById('view-task-assigned-container');
    const assignedEl = document.getElementById('view-task-assigned');
    if (task.assigned_agent) {
        assignedEl.innerHTML = `
            <span class="text-emerald-400">🤖</span>
            <span class="text-emerald-400 font-medium">${escapeHtml(task.assigned_agent)}</span>
        `;
        assignedContainer.classList.remove('hidden');
    } else {
        assignedContainer.classList.add('hidden');
    }
    
    // Show modal
    document.getElementById('task-view-modal').classList.remove('hidden');
}

function closeTaskViewModal() {
    document.getElementById('task-view-modal').classList.add('hidden');
    currentViewTaskId = null;
}

function editCurrentTask() {
    if (currentViewTaskId) {
        closeTaskViewModal();
        openTaskModal(currentViewTaskId);
    }
}

async function completeCurrentTask() {
    if (!currentViewTaskId) return;
    
    const success = await updateTaskStatus(currentViewTaskId, 'done');
    if (success) {
        closeTaskViewModal();
        showNotification('Task marked as complete', 'success');
    }
}

function formatFriendlyTime(timestamp) {
    if (!timestamp) return 'Unknown';
    
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffSecs = Math.floor(diffMs / 1000);
    const diffMins = Math.floor(diffSecs / 60);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);
    
    if (diffSecs < 5) return 'Just now';
    if (diffSecs < 60) return `${diffSecs} secs ago`;
    if (diffMins < 2) return '1 min ago';
    if (diffMins < 60) return `${diffMins} mins ago`;
    if (diffHours < 2) return '1 hour ago';
    if (diffHours < 24) return `${diffHours} hours ago`;
    if (diffDays < 2) return 'Yesterday';
    if (diffDays < 7) return `${diffDays} days ago`;
    
    return date.toLocaleDateString('en-GB', { 
        day: 'numeric', 
        month: 'short', 
        year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined 
    });
}

// ==================== Modal Functions ====================
function openTaskModal(taskId = null) {
    const modal = document.getElementById('task-modal');
    const titleEl = document.getElementById('modal-title');
    const form = document.getElementById('task-form');
    
    if (taskId) {
        const task = allTasks.find(t => t.id === taskId);
        if (task) {
            titleEl.textContent = 'Edit Task';
            document.getElementById('task-id').value = task.id;
            document.getElementById('task-title').value = task.title || '';
            document.getElementById('task-description').value = task.description || '';
            document.getElementById('task-priority').value = task.priority || 'medium';
        }
    } else {
        titleEl.textContent = 'New Task';
        form.reset();
        document.getElementById('task-id').value = '';
    }
    
    modal.classList.remove('hidden');
    document.getElementById('task-title').focus();
}

function closeTaskModal() {
    document.getElementById('task-modal').classList.add('hidden');
    document.getElementById('task-form').reset();
}

async function handleTaskSubmit(e) {
    e.preventDefault();

    const taskData = {
        title: document.getElementById('task-title').value.trim(),
        description: document.getElementById('task-description').value.trim(),
        priority: document.getElementById('task-priority').value,
        status: 'Inbox'
    };
    
    if (!taskData.title) {
        showNotification('Title is required', 'error');
        return;
    }
    
    const success = await createTask(taskData);
    if (success) {
        closeTaskModal();
    }
}

function confirmDeleteTask(taskId) {
    deleteTaskId = taskId;
    document.getElementById('delete-modal').classList.remove('hidden');
    
    const confirmBtn = document.getElementById('confirm-delete-btn');
    confirmBtn.onclick = async () => {
        if (deleteTaskId) {
            await deleteTask(deleteTaskId);
            closeDeleteModal();
        }
    };
}

function closeDeleteModal() {
    document.getElementById('delete-modal').classList.add('hidden');
    deleteTaskId = null;
}

// ==================== Notification System ====================
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `fixed bottom-4 right-4 px-4 py-3 rounded-lg shadow-lg z-50 transform transition-all duration-300 translate-y-10 opacity-0`;
    
    const colors = {
        success: 'bg-green-600',
        error: 'bg-red-600',
        info: 'bg-blue-600',
        warning: 'bg-yellow-600'
    };
    
    notification.classList.add(colors[type] || colors.info);
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    requestAnimationFrame(() => {
        notification.classList.remove('translate-y-10', 'opacity-0');
    });
    
    setTimeout(() => {
        notification.classList.add('translate-y-10', 'opacity-0');
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}
