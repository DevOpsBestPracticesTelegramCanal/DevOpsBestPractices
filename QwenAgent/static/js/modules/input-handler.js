/**
 * Input handling — send message, stop request, keyboard shortcuts
 */

import { dom, scrollToBottom } from './dom.js';
import { TOOL_LABELS } from './constants.js';
import state from './state.js';
import eventBus from './event-bus.js';
import { updateAutoModeIndicator, detectModeFromQuery } from './mode-manager.js';
import { addMessage, addToolCall, addThinking, showLoading, hideLoading, updateLoading, toggleAllCollapsed } from './messages.js';
import { processSSEStream } from './sse-client.js';

export function initInputHandlers() {
    // Auto-resize textarea
    dom.input.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 300) + 'px';
    });

    // Enter to send
    dom.input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            sendMessage();
        } else if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    dom.sendBtn.addEventListener('click', sendMessage);
    dom.stopBtn.addEventListener('click', stopRequest);

    // Global keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && state.isProcessing && !state.pendingConfirmation) {
            e.preventDefault();
            stopRequest();
            return;
        }
        if ((e.ctrlKey || e.metaKey) && e.key === 'o') {
            e.preventDefault();
            toggleAllCollapsed();
            return;
        }
    });

    // Fullscreen
    if (dom.fullscreenBtn) {
        dom.fullscreenBtn.addEventListener('click', toggleFullscreen);
        document.addEventListener('fullscreenchange', () => {
            const isFS = !!document.fullscreenElement;
            dom.fullscreenBtn.textContent = isFS ? '\u2716' : '\u26F6';
            dom.fullscreenBtn.title = isFS ? 'Exit fullscreen (F11)' : 'Toggle fullscreen (F11)';
            document.body.classList.toggle('compact-mode', isFS);
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'F11') { e.preventDefault(); toggleFullscreen(); }
        });
    }

    // Search button
    if (dom.searchBtn) {
        dom.searchBtn.addEventListener('click', toggleSearchMode);
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.shiftKey && e.key === 'S') {
                e.preventDefault();
                dom.searchBtn.click();
            }
        });
    }

    // PWA install
    if (dom.installBtn) {
        window.addEventListener('beforeinstallprompt', (e) => {
            e.preventDefault();
            state.deferredPrompt = e;
            dom.installBtn.style.display = 'flex';
        });
        dom.installBtn.addEventListener('click', async () => {
            if (!state.deferredPrompt) return;
            state.deferredPrompt.prompt();
            const result = await state.deferredPrompt.userChoice;
            if (result.outcome === 'accepted') dom.installBtn.style.display = 'none';
            state.deferredPrompt = null;
        });
        window.addEventListener('appinstalled', () => {
            dom.installBtn.style.display = 'none';
            state.deferredPrompt = null;
        });
    }

    // Service worker
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/service-worker.js').catch(() => {});
    }

    // Standalone detection
    if (window.matchMedia('(display-mode: standalone)').matches ||
        window.navigator.standalone === true) {
        document.body.classList.add('compact-mode');
    }

    // Focus input
    dom.input.focus();

    // Auto-test
    runAutoTest();
}

export async function sendMessage() {
    const message = dom.input.value.trim();
    if (!message || state.isProcessing) return;

    state.isProcessing = true;
    dom.sendBtn.disabled = true;
    dom.stopBtn.classList.add('visible');
    dom.input.value = '';
    dom.input.style.height = '63px';

    state.abortController = new AbortController();

    const estimatedMode = detectModeFromQuery(message);
    updateAutoModeIndicator('processing');
    state.currentMode = estimatedMode;

    const finalMessage = message;
    addMessage('user', message);
    const loadingId = showLoading('Determining approach...');

    let stepCount = 0;
    let hasToolCalls = false;
    let lastRouteMethod = '';

    // Set up SSE event handlers for this request
    const unsubs = [];

    unsubs.push(eventBus.on('sse:status', (event) => {
        updateLoading(loadingId, event.text);
    }));

    unsubs.push(eventBus.on('sse:tool_start', (event) => {
        stepCount++;
        const label = TOOL_LABELS[event.tool] || event.tool;
        const fileHint = event.params?.file_path ? ` ${event.params.file_path}` : '';
        updateLoading(loadingId, `[${stepCount}] ${label}${fileHint}...`);
    }));

    unsubs.push(eventBus.on('sse:tool_result', (event) => {
        hasToolCalls = true;
        addToolCall({ tool: event.tool, params: event.params, result: event.result });
    }));

    unsubs.push(eventBus.on('sse:thinking', (event) => {
        if (event.steps && event.steps.length > 0) addThinking(event.steps);
    }));

    unsubs.push(eventBus.on('sse:mode_change', (event) => {
        const newMode = event.mode || 'fast';
        state.currentMode = newMode;
        updateAutoModeIndicator(newMode);
        updateLoading(loadingId, event.message || `Switched to ${newMode} mode`);
    }));

    unsubs.push(eventBus.on('sse:response', (event) => {
        lastRouteMethod = event.route_method || '';
        if (lastRouteMethod === 'deep_search' || lastRouteMethod === 'web_search') {
            state.currentMode = 'search'; updateAutoModeIndicator('search');
        } else if (lastRouteMethod === 'llm' || lastRouteMethod === 'deep') {
            state.currentMode = 'deep6'; updateAutoModeIndicator('deep6');
        } else if (lastRouteMethod === 'pattern' || lastRouteMethod === 'fast') {
            state.currentMode = 'fast'; updateAutoModeIndicator('fast');
        }
        hideLoading(loadingId);
        if (event.text) {
            const showResponse = !hasToolCalls ||
                lastRouteMethod === 'llm' ||
                lastRouteMethod === 'deep_search' ||
                lastRouteMethod === 'pattern+llm_analysis';
            if (showResponse) addMessage('assistant', event.text, lastRouteMethod);
        }
    }));

    // Week 20: Streaming token events
    unsubs.push(eventBus.on('sse:response_start', (event) => {
        hideLoading(loadingId);
    }));

    unsubs.push(eventBus.on('sse:response_done', (event) => {
        lastRouteMethod = 'llm';
        state.currentMode = 'deep6';
        updateAutoModeIndicator('deep6');
    }));

    unsubs.push(eventBus.on('sse:error', (event) => {
        hideLoading(loadingId);
        addMessage('system', `Error: ${event.text || 'Unknown error'}`);
    }));

    unsubs.push(eventBus.on('sse:done', (event) => {
        hideLoading(loadingId);
        if (event.swecas && event.swecas.category) {
            const swecasTag = document.createElement('div');
            swecasTag.className = 'swecas-tag';
            swecasTag.innerHTML = `<span class="swecas-badge">SWECAS-${event.swecas.category}</span> ${event.swecas.name}`;
            const lastMsg = dom.output.querySelector('.message:last-child .message-body');
            if (lastMsg) lastMsg.appendChild(swecasTag);
        }
    }));

    try {
        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: finalMessage }),
            signal: state.abortController.signal
        });

        await processSSEStream(response, state.abortController.signal);

        hideLoading(loadingId);
    } catch (error) {
        hideLoading(loadingId);
        if (error.name === 'AbortError') {
            addMessage('system', 'Request stopped by user');
        } else {
            console.warn('SSE failed, falling back to /api/chat:', error.message);
            await sendMessageFallback(finalMessage, message, loadingId);
        }
    }

    // Cleanup
    unsubs.forEach(unsub => unsub());
    state.isProcessing = false;
    dom.sendBtn.disabled = false;
    dom.stopBtn.classList.remove('visible');
    state.abortController = null;
    updateAutoModeIndicator(state.currentMode || 'fast');
    dom.input.focus();
}

async function sendMessageFallback(finalMessage, originalMessage, loadingId) {
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: finalMessage })
        });
        const data = await response.json();
        hideLoading(loadingId);
        if (data.success) {
            if (data.thinking && data.thinking.length > 0) addThinking(data.thinking);
            const hasTC = data.tool_calls && data.tool_calls.length > 0;
            if (hasTC) {
                for (const tc of data.tool_calls) addToolCall(tc);
            }
            if (!hasTC && data.response) {
                addMessage('assistant', data.response, data.route_method);
            } else if (hasTC && data.route_method === 'llm' && data.response) {
                addMessage('assistant', data.response, data.route_method);
            }
        } else {
            addMessage('system', `Error: ${data.error || 'Unknown error'}`);
        }
    } catch (e) {
        hideLoading(loadingId);
        addMessage('system', `Error: ${e.message}`);
    }
}

function stopRequest() {
    if (state.abortController) state.abortController.abort();
}

function toggleFullscreen() {
    if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {});
    } else {
        document.exitFullscreen();
    }
}

function toggleSearchMode() {
    state.searchModeActive = !state.searchModeActive;
    dom.searchBtn.classList.toggle('active', state.searchModeActive);

    if (state.searchModeActive) {
        dom.currentModeIcon.textContent = '🌐';
        dom.currentModeLabel.textContent = 'Search';
        dom.autoModeIndicator.setAttribute('data-mode', 'search');
        dom.input.placeholder = '🌐 Search mode: Enter your search query...';
        fetch('/api/mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: 'search' })
        });
        addMessage('system', '🌐 <strong>Search Mode Activated</strong> — Your query will be searched on the web');
    } else {
        dom.currentModeIcon.textContent = '⚡';
        dom.currentModeLabel.textContent = 'Auto';
        dom.autoModeIndicator.setAttribute('data-mode', 'fast');
        dom.input.placeholder = 'Type your message... (Ctrl+Enter to send)';
        fetch('/api/mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: 'fast' })
        });
        addMessage('system', '⚡ <strong>Auto Mode</strong> — Automatic mode selection restored');
    }
    dom.input.focus();
}

async function runAutoTest() {
    const params = new URLSearchParams(window.location.search);
    const testType = params.get('test');
    if (testType === 'multiline' || testType === 'nested') {
        const oldStr = testType === 'nested'
            ? "                    if check[\"type\"] == \"http\":\n                        container[\"health\"] = {\n                            \"endpoint\": check[\"path\"],\n                            \"interval\": 30\n                        }\n                    elif check[\"type\"] == \"tcp\":\n                        container[\"health\"] = {\n                            \"port\": check[\"port\"],\n                            \"timeout\": 10\n                        }"
            : "def hello():\n    \"\"\"Say hello\"\"\"\n    print(\"Hello World\")\n    return True";
        const newStr = testType === 'nested'
            ? "                    if check[\"type\"] == \"http\":\n                        container[\"health\"] = {\n                            \"endpoint\": check[\"path\"],\n                            \"interval\": check.get(\"interval\", 30),\n                            \"retries\": check.get(\"retries\", 3),\n                            \"timeout\": 5\n                        }\n                    elif check[\"type\"] == \"tcp\":\n                        container[\"health\"] = {\n                            \"port\": check[\"port\"],\n                            \"timeout\": check.get(\"timeout\", 10),\n                            \"retries\": 3\n                        }\n                    elif check[\"type\"] == \"exec\":\n                        container[\"health\"] = {\n                            \"command\": check[\"cmd\"],\n                            \"interval\": 60\n                        }"
            : "def hello(name=\"World\"):\n    \"\"\"Say hello to someone\"\"\"\n    greeting = f\"Hello {name}\"\n    print(greeting)\n    return greeting";
        const label = testType === 'nested'
            ? 'nested edit: replace health_check block'
            : 'multiline edit: replace hello() function';
        addMessage('user', label);
        const loadId = showLoading('Running edit test...');
        try {
            const r = await fetch('/api/test-multiline-edit', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ file_path: '_test_diff.py', old_string: oldStr, new_string: newStr })
            });
            const d = await r.json();
            hideLoading(loadId);
            if (d.tool_calls) { for (const tc of d.tool_calls) addToolCall(tc); }
            setTimeout(() => {
                const dc = document.querySelector('.diff-content');
                if (dc) dc.scrollTop = 0;
                window.scrollTo(0, 0);
            }, 200);
        } catch(e) {
            hideLoading(loadId);
            addMessage('system', 'Test error: ' + e.message);
        }
    }
}
