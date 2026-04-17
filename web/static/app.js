'use strict';

// Load server-side defaults (LLM_URL / LLM_MODEL from env) on page load
(async () => {
    try {
        const res = await fetch('/api/config');
        if (!res.ok) return;
        const cfg = await res.json();
        const urlEl   = document.getElementById('llm-url');
        const modelEl = document.getElementById('llm-model');
        if (urlEl   && cfg.llm_url)   urlEl.value   = cfg.llm_url;
        if (modelEl && cfg.llm_model) modelEl.value = cfg.llm_model;
    } catch { /* server not yet ready — keep HTML defaults */ }
})();

// ─────────────────────────────────────────────────────────────
// STATE
// ─────────────────────────────────────────────────────────────

const AGENT_COLORS = {
    idle:  '#8b949e',
    busy:  '#238636',
    error: '#b62324',
};

const AGENT_NAME_COLORS = {
    Derick: '#388bfd',
    Jef:    '#d2a8ff',
    Zed:    '#3fb950',
    Earl:   '#e3b341',
    Chris:  '#f78166',
};

let running          = false;
let eventOffset      = 0;
let pollTimer        = null;
let activeStreamAgent = null;   // which agent's stream is displayed


// ─────────────────────────────────────────────────────────────
// LAUNCH / STOP / RESET
// ─────────────────────────────────────────────────────────────

function toggleRun() {
    if (running) doStop();
    else         doLaunch();
}

async function doLaunch() {
    const description = document.getElementById('description').value.trim();
    if (!description) {
        alert('Décris le projet avant de lancer.');
        return;
    }

    const config = {
        description,
        arch: document.querySelector('input[name="arch"]:checked').value,
        components: Object.fromEntries(
            [...document.querySelectorAll('input[name="comp"]')]
                .map(el => [el.value, el.checked])
        ),
        db:         document.querySelector('input[name="db"]:checked').value,
        llm_url:    document.getElementById('llm-url').value,
        llm_model:  document.getElementById('llm-model').value,
        max_cycles: parseInt(document.getElementById('max-cycles').value, 10),
    };

    const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
    });

    if (res.status === 409) {
        appendMsg('System', 'Un run est déjà en cours — ignoré.');
        return;
    }

    if (res.ok) {
        setRunning(true);
        appendSep();
        appendMsg('System', `Démarrage — objectif : ${description.slice(0, 80)}`);
        startPolling();
    }
}

async function doStop() {
    await fetch('/api/stop', { method: 'POST' });
    setRunning(false);
    setStatusBadge('● ARRÊTÉ', 'var(--btn-red)');
}

async function doReset() {
    await fetch('/api/reset', { method: 'POST' });
    stopPolling();
    setRunning(false);
    clearLog();
    eventOffset = 0;
    resetAgents();
    setStats(0, 0, 0);
    setStatusBadge('● EN ATTENTE', 'var(--dim)');
}

function setRunning(value) {
    running = value;
    const btn = document.getElementById('launch-btn');
    if (value) {
        btn.textContent = '■\u00a0 ARRÊTER';
        btn.className   = 'btn-red';
        setStatusBadge('● EN COURS', '#238636');
    } else {
        btn.textContent = '▶\u00a0 LANCER LES AGENTS';
        btn.className   = 'btn-green';
    }
}


// ─────────────────────────────────────────────────────────────
// POLLING
// ─────────────────────────────────────────────────────────────

function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(poll, 500);
}

function stopPolling() {
    clearInterval(pollTimer);
    pollTimer = null;
}

async function poll() {
    try {
        const res = await fetch(`/api/status?since=${eventOffset}`);
        if (!res.ok) return;
        const data = await res.json();

        // Agent cards
        for (const [agent, info] of Object.entries(data.agent_status)) {
            updateAgentCard(agent, info.status, info.task);
        }

        // Stats
        setStats(data.stats.cycle, data.stats.completed, data.stats.blocked);

        // Stream panel
        updateStreamPanel(data.agent_stream);

        // New events / messages
        for (const ev of data.events) {
            if (ev._msg) appendMsg(ev.agent, ev.msg);
            else         renderEvent(ev);
        }
        eventOffset = data.total_events;

        // Terminal states
        if (!data.running && data.status !== 'idle' && data.status !== 'running') {
            stopPolling();
            setRunning(false);
            resetAgents();
            if (data.status === 'done')    setStatusBadge('● TERMINÉ',  '#3fb950');
            if (data.status === 'stopped') setStatusBadge('● ARRÊTÉ',   '#b62324');
            if (data.status === 'error')   setStatusBadge('● ERREUR',   '#f85149');
        }
    } catch {
        // Network hiccup — ignore
    }
}


// ─────────────────────────────────────────────────────────────
// EVENT LOG RENDERING
// ─────────────────────────────────────────────────────────────

function renderEvent(ev) {
    const agent     = ev.agent      || 'System';
    const evType    = ev.event_type || '';
    const target    = ev.target     || '';
    const payload   = ev.payload    || {};
    const cycle     = ev.cycle      ?? 0;
    const ts        = (ev.timestamp || '').slice(11, 23);

    const line = document.createElement('div');
    line.className = 'log-line';

    line.appendChild(span(`[${ts}] C${String(cycle).padStart(2, '0')}  `, 'log-ts'));
    line.appendChild(span(agent.padEnd(8),    `log-agent-${agent}`));
    line.appendChild(span(`  ${evType.padEnd(22)}`, `log-evt-${evType}`));

    if (target && target !== 'system') {
        line.appendChild(span(`  → ${target}`, 'log-ts'));
    }

    const hint = payloadHint(payload);
    if (hint) line.appendChild(span(`  ${hint}`, 'log-payload'));

    appendLine(line);
}

function appendMsg(agent, msg) {
    const ts   = new Date().toISOString().slice(11, 23);
    const line = document.createElement('div');
    line.className = 'log-line';
    line.appendChild(span(`[${ts}] `, 'log-ts'));
    line.appendChild(span(agent.padEnd(8), `log-agent-${agent}`));
    line.appendChild(span(`  ${msg}`, 'log-payload'));
    appendLine(line);
}

function appendSep() {
    const line = document.createElement('div');
    line.className = 'log-line';
    line.appendChild(span('─'.repeat(72), 'log-sep'));
    appendLine(line);
}

function appendLine(el) {
    const area = document.getElementById('log-area');
    area.appendChild(el);
    area.scrollTop = area.scrollHeight;
}

function clearLog() {
    document.getElementById('log-area').innerHTML = '';
}

function payloadHint(payload) {
    for (const key of ['reason', 'summary', 'feedback', 'error', 'files', 'issues']) {
        const val = payload[key];
        if (val) {
            const text = typeof val === 'string' ? val : JSON.stringify(val);
            return text.length > 60 ? `(${text.slice(0, 60)}…)` : `(${text})`;
        }
    }
    return '';
}

function span(text, className) {
    const el = document.createElement('span');
    el.className  = className;
    el.textContent = text;
    return el;
}


// ─────────────────────────────────────────────────────────────
// AGENT CARDS
// ─────────────────────────────────────────────────────────────

function updateAgentCard(agent, status, task) {
    const card = document.getElementById(`agent-${agent}`);
    if (!card) return;
    card.querySelector('.agent-dot').style.color  = AGENT_COLORS[status] || AGENT_COLORS.idle;
    card.querySelector('.agent-task').textContent = task ? task.slice(0, 18) : status;
}

function resetAgents() {
    for (const agent of ['Derick', 'Jef', 'Zed', 'Earl', 'Chris']) {
        updateAgentCard(agent, 'idle', null);
    }
}

// ── Stream panel ─────────────────────────────────────────────

function toggleStream(agent) {
    if (activeStreamAgent === agent) {
        closeStream();
    } else {
        openStream(agent);
    }
}

function openStream(agent) {
    if (activeStreamAgent) {
        document.getElementById(`agent-${activeStreamAgent}`)?.classList.remove('stream-active');
    }
    activeStreamAgent = agent;
    document.getElementById(`agent-${agent}`)?.classList.add('stream-active');

    const color = AGENT_NAME_COLORS[agent] || '#c9d1d9';
    document.getElementById('stream-panel-title').innerHTML =
        `<span style="color:${color};font-weight:bold">${agent}</span>&nbsp;— STREAM LLM`;
    document.getElementById('stream-panel').classList.add('open');
}

function closeStream() {
    if (activeStreamAgent) {
        document.getElementById(`agent-${activeStreamAgent}`)?.classList.remove('stream-active');
        activeStreamAgent = null;
    }
    document.getElementById('stream-panel').classList.remove('open');
}

function updateStreamPanel(streamMap) {
    if (!activeStreamAgent) return;
    const body = document.getElementById('stream-body');
    const text = (streamMap?.[activeStreamAgent] || '').trim();

    if (!text) { body.innerHTML = ''; return; }

    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
    body.innerHTML = escapeHtml(text) + '<span class="stream-cursor"></span>';
    if (atBottom) body.scrollTop = body.scrollHeight;
}

function escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}


// ─────────────────────────────────────────────────────────────
// STATS / STATUS BADGE
// ─────────────────────────────────────────────────────────────

function setStats(cycle, completed, blocked) {
    document.getElementById('stat-cycle').textContent     = cycle;
    document.getElementById('stat-completed').textContent = completed;
    document.getElementById('stat-blocked').textContent   = blocked;
}

function setStatusBadge(text, color) {
    const badge   = document.getElementById('status-badge');
    badge.textContent = text;
    badge.style.color = color;
}
