/**
 * ==========================================================================
 * QWENCODE TERMINAL - JavaScript
 * ==========================================================================
 * Phase 5 Refactoring: Extracted from monolithic HTML template
 * Version: 2.2.0
 */

// ========== DOM ELEMENTS ==========
const output = document.getElementById('output');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send-btn');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const modelBadge = document.getElementById('model-badge');
const modeBanner = document.getElementById('mode-banner');
const modeBannerIcon = document.getElementById('mode-banner-icon');
const modeBannerText = document.getElementById('mode-banner-text');

// Mode buttons
const modeFast = document.getElementById('mode-fast');
const modeDeep3 = document.getElementById('mode-deep3');
const modeDeep6 = document.getElementById('mode-deep6');
const modeSearch = document.getElementById('mode-search');
const modeAiSearch = document.getElementById('mode-aisearch');

// ========== STATE ==========
let isProcessing = false;
let currentMode = 'fast';
let pendingConfirmation = null;
let selectedChoiceIndex = 0;
let abortController = null;

// Stop button
const stopBtn = document.getElementById('stop-btn');

// ========== TOOL ICONS ==========
const TOOL_ICONS = {
    'read': '📖', 'write': '✏️', 'edit': '🔧', 'ls': '📁',
    'bash': '💻', 'grep': '🔍', 'glob': '🔍', 'search': '🔍',
    'git': '📦', 'web_fetch': '🌐', 'web_search': '🌐',
    'tree': '🌳', 'diff': '📊', 'notebook_read': '📓',
    'notebook_edit': '📓', 'default': '⚡'
};

// ========== TOOL LABELS (for live activity) ==========
const TOOL_LABELS = {
    'read': 'Reading file',
    'write': 'Writing file',
    'edit': 'Editing file',
    'bash': 'Running command',
    'ls': 'Listing directory',
    'grep': 'Searching',
    'glob': 'Finding files',
    'git': 'Git operation',
    'tree': 'Showing tree',
    'web_fetch': 'Fetching URL',
    'web_search': 'Searching web',
    'diff': 'Comparing files'
};

// ========== INPUT HANDLING ==========
input.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 200) + 'px';
});

input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        sendMessage();
    } else if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

sendBtn.addEventListener('click', sendMessage);

// ========== MODE SWITCHING ==========
modeFast.addEventListener('click', () => switchMode('fast'));
modeDeep3.addEventListener('click', () => switchMode('deep3'));
modeDeep6.addEventListener('click', () => switchMode('deep6'));
modeSearch.addEventListener('click', () => switchMode('search'));
modeAiSearch.addEventListener('click', () => switchMode('aisearch'));

function switchMode(mode) {
    currentMode = mode;

    // Update buttons
    document.querySelectorAll('.mode-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById(`mode-${mode}`).classList.add('active');

    // Update banner
    if (mode === 'fast') {
        modeBanner.classList.remove('active');
    } else {
        modeBanner.classList.add('active');
        modeBanner.className = `mode-banner active ${mode}`;

        if (mode === 'deep3') {
            modeBannerIcon.textContent = '🔬';
            modeBannerText.textContent = 'Deep3 Mode — 3-step lightweight CoT reasoning';
        } else if (mode === 'deep6') {
            modeBannerIcon.textContent = '🧠';
            modeBannerText.textContent = 'Deep6 Mode — Full 6-step Chain-of-Thought (Minsky)';
        } else if (mode === 'search') {
            modeBannerIcon.textContent = '🌐';
            modeBannerText.textContent = 'Search Mode — Fast web search (direct results, ~3 sec)';
        } else if (mode === 'aisearch') {
            modeBannerIcon.textContent = '🔍';
            modeBannerText.textContent = 'AI+Search Mode — Web search + LLM analysis';
        }
    }

    // Always sync mode with backend
    const modeMap = { 'fast': 'fast', 'deep3': 'deep3', 'deep6': 'deep', 'search': 'fast', 'aisearch': 'search' };
    fetch('/api/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: modeMap[mode] || 'fast' })
    }).catch(() => {});
}

// ========== UPDATE LOADING ==========
function updateLoading(id, text) {
    const el = document.getElementById(id);
    if (el) {
        const textEl = el.querySelector('.loading-text');
        if (textEl) textEl.textContent = text;
    }
}

// ========== SEND MESSAGE (SSE STREAMING) ==========
async function sendMessage() {
    const message = input.value.trim();
    if (!message || isProcessing) return;

    isProcessing = true;
    sendBtn.disabled = true;
    stopBtn.classList.add('visible');
    input.value = '';
    input.style.height = 'auto';

    // Create AbortController for this request
    abortController = new AbortController();

    // Add mode prefix if needed
    let finalMessage = message;
    if (currentMode === 'deep3' && !message.toUpperCase().startsWith('[DEEP3]')) {
        finalMessage = `[DEEP3] ${message}`;
    } else if (currentMode === 'deep6' && !message.toUpperCase().startsWith('[DEEP]')) {
        finalMessage = `[DEEP] ${message}`;
    } else if (currentMode === 'search' && !message.startsWith('/search ')) {
        finalMessage = `/search ${message}`;
    } else if (currentMode === 'aisearch' && !message.toUpperCase().startsWith('[SEARCH]')) {
        finalMessage = `[SEARCH] ${message}`;
    }

    addMessage('user', message);
    const loadingId = showLoading('Processing...');

    let stepCount = 0;
    let totalSteps = 0;
    let hasToolCalls = false;
    let lastRouteMethod = '';

    try {
        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: finalMessage }),
            signal: abortController.signal
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // Process complete SSE lines
            const lines = buffer.split('\n');
            buffer = lines.pop(); // Keep incomplete line in buffer

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;

                let event;
                try {
                    event = JSON.parse(line.slice(6));
                } catch (e) {
                    continue;
                }

                switch (event.event) {
                    case 'status':
                        updateLoading(loadingId, event.text);
                        break;

                    case 'tool_start':
                        stepCount++;
                        totalSteps++;
                        const label = TOOL_LABELS[event.tool] || event.tool;
                        const fileHint = event.params?.file_path
                            ? ` ${event.params.file_path}` : '';
                        updateLoading(loadingId,
                            `[${stepCount}] ${label}${fileHint}...`);
                        break;

                    case 'tool_result':
                        hasToolCalls = true;
                        addToolCall({
                            tool: event.tool,
                            params: event.params,
                            result: event.result
                        });
                        break;

                    case 'thinking':
                        if (event.steps && event.steps.length > 0) {
                            addThinking(event.steps);
                        }
                        break;

                    case 'response':
                        lastRouteMethod = event.route_method || '';
                        hideLoading(loadingId);
                        if (event.text) {
                            // Show response for: no tools, llm, deep_search, pattern+llm_analysis
                            const showResponse = !hasToolCalls ||
                                lastRouteMethod === 'llm' ||
                                lastRouteMethod === 'deep_search' ||
                                lastRouteMethod === 'pattern+llm_analysis';
                            if (showResponse) {
                                addMessage('assistant', event.text, lastRouteMethod);
                            }
                        }
                        break;

                    case 'error':
                        hideLoading(loadingId);
                        addMessage('system', `Error: ${event.text || 'Unknown error'}`);
                        break;

                    case 'done':
                        hideLoading(loadingId);
                        break;
                }
            }
        }

        // Ensure loading is hidden
        hideLoading(loadingId);

    } catch (error) {
        hideLoading(loadingId);
        if (error.name === 'AbortError') {
            addMessage('system', 'Request stopped by user');
        } else {
            // Fallback to non-streaming API
            console.warn('SSE failed, falling back to /api/chat:', error.message);
            await sendMessageFallback(finalMessage, message, loadingId);
        }
    }

    isProcessing = false;
    sendBtn.disabled = false;
    stopBtn.classList.remove('visible');
    abortController = null;
    input.focus();
}

// ========== FALLBACK (non-streaming) ==========
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
            if (data.thinking && data.thinking.length > 0) {
                addThinking(data.thinking);
            }

            const hasToolCalls = data.tool_calls && data.tool_calls.length > 0;
            if (hasToolCalls) {
                for (const tc of data.tool_calls) {
                    addToolCall(tc);
                }
            }

            if (!hasToolCalls && data.response) {
                addMessage('assistant', data.response, data.route_method);
            } else if (hasToolCalls && data.route_method === 'llm' && data.response) {
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

// ========== STOP REQUEST ==========
function stopRequest() {
    if (abortController) {
        abortController.abort();
    }
}

stopBtn.addEventListener('click', stopRequest);

// ========== ADD MESSAGE ==========
function addMessage(type, content, routeMethod = null) {
    const div = document.createElement('div');
    div.className = 'message';

    if (type === 'user') {
        div.innerHTML = `
            <div class="message-user">
                <span class="message-prompt">❯</span>
                <span class="message-content">${escapeHtml(content)}</span>
            </div>
        `;
    } else if (type === 'assistant') {
        const routeBadge = routeMethod ?
            `<span class="route-badge ${routeMethod}">${routeMethod === 'pattern' ? '⚡ pattern' : '🤖 llm'}</span>` : '';

        div.innerHTML = `
            <div class="message-assistant">
                ${formatContent(content)}
                ${routeBadge}
            </div>
        `;
    } else {
        div.innerHTML = `<div class="message-system">${content}</div>`;
    }

    output.appendChild(div);
    scrollToBottom();

    // Highlight code & add copy buttons
    div.querySelectorAll('pre code').forEach(block => {
        hljs.highlightElement(block);
    });
    addCopyButtons(div);
}

// ========== ADD TOOL CALL ==========
function addToolCall(tc) {
    const div = document.createElement('div');
    div.className = 'tool-call';

    const icon = TOOL_ICONS[tc.tool] || TOOL_ICONS.default;
    const truncate = (str, len = 50) => {
        if (typeof str !== 'string') str = String(str);
        return str.length > len ? str.substring(0, len) + '...' : str;
    };

    const params = Object.entries(tc.params || {})
        .map(([k, v]) => `${k}="${truncate(v)}"`)
        .join(', ');

    const isSuccess = tc.result.success !== false;
    const statusClass = isSuccess ? 'success' : 'error';
    const statusIcon = isSuccess ? '✓' : '✗';

    const resultStr = isSuccess ?
        formatToolResult(tc.tool, tc.result) :
        `<span style="color: var(--accent-red)">Error: ${escapeHtml(tc.result.error)}</span>`;

    div.innerHTML = `
        <div class="tool-header">
            <span class="tool-icon">${icon}</span>
            <span class="tool-name">${tc.tool}</span>
            <span class="tool-params">(${params})</span>
            <span class="tool-status ${statusClass}">${statusIcon}</span>
        </div>
        <div class="tool-result">${resultStr}</div>
    `;

    output.appendChild(div);
    scrollToBottom();
}

// ========== ADD THINKING ==========
function addThinking(thinking) {
    const div = document.createElement('div');
    div.className = 'thinking-block';

    const content = Array.isArray(thinking) ? thinking.join('\n') : thinking;

    div.innerHTML = `
        <div class="thinking-header">
            <span>🧠</span>
            <span>Thinking</span>
        </div>
        <div class="thinking-content">${escapeHtml(content)}</div>
    `;

    output.appendChild(div);
    scrollToBottom();
}

// ========== LOADING ==========
function showLoading(text = 'Processing...') {
    const id = 'loading-' + Date.now();
    const div = document.createElement('div');
    div.id = id;
    div.className = 'loading';
    div.innerHTML = `
        <div class="loading-spinner"></div>
        <span class="loading-dot"></span>
        <span class="loading-text status-executing">${escapeHtml(text)}</span>
    `;
    output.appendChild(div);
    scrollToBottom();
    return id;
}

function hideLoading(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

// ========== FORMAT CONTENT ==========
function formatContent(content) {
    if (!content) return '';

    // Convert escaped newlines
    let text = content.replace(/\\n/g, '\n');

    // Extract code blocks
    const codeBlocks = [];
    let processed = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (match, lang, code) => {
        const idx = codeBlocks.length;
        const langName = lang || 'plaintext';
        const escapedCode = code
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .trim();

        codeBlocks.push(`
            <div class="code-block-wrapper">
                <div class="code-block-header">
                    <span class="code-block-lang">${langName}</span>
                    <button class="code-copy-btn" onclick="copyCode(this)">Copy</button>
                </div>
                <pre><code class="language-${langName}">${escapedCode}</code></pre>
            </div>
        `);
        return `__CODEBLOCK_${idx}__`;
    });

    // Escape HTML
    let html = escapeHtml(processed);

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bold
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Line breaks
    html = html.replace(/\n/g, '<br>');

    // Restore code blocks
    codeBlocks.forEach((block, i) => {
        html = html.replace(`__CODEBLOCK_${i}__`, block);
    });

    return html;
}

// ========== FORMAT TOOL RESULT ==========
function formatToolResult(tool, result) {
    if (tool === 'ls') {
        const items = result.items || [];
        return items.slice(0, 30).map(item => {
            const icon = item.type === 'dir' ? '📁' : '📄';
            return `${icon} ${escapeHtml(item.name)}`;
        }).join('<br>') + (items.length > 30 ? `<br><span style="color:var(--text-muted)">... +${items.length - 30} more</span>` : '');
    }

    if (tool === 'read') {
        const content = result.content || '';
        // Backend returns "     N: content" format — strip the line-number prefix
        const rawLines = content.split('\n').slice(0, 100);
        const lines = rawLines.map(l => l.replace(/^\s*\d+:\s?/, ''));
        const startLine = (result.offset || 0) + 1;
        return formatDiffView(result.file_path || 'file', lines, null, 'read', startLine);
    }

    if (tool === 'grep') {
        const matches = result.matches || [];
        return matches.slice(0, 20).map(m =>
            `<span style="color:var(--text-muted)">${escapeHtml(m.file)}:${m.line_number}:</span> ${escapeHtml(m.line)}`
        ).join('<br>');
    }

    if (tool === 'bash') {
        const stdout = result.stdout || '';
        const stderr = result.stderr || '';
        let html = stdout ? `<pre style="margin:0">${escapeHtml(stdout)}</pre>` : '';
        if (stderr) {
            html += `<pre style="margin:0;color:var(--accent-red)">${escapeHtml(stderr)}</pre>`;
        }
        return html || '<span style="color:var(--text-muted)">(no output)</span>';
    }

    if (tool === 'edit' || tool === 'write' || tool === 'code_inject') {
        const file = result.file_path || result.file || 'file';
        const oldContent = result.old_content || '';
        const newContent = result.new_content || '';
        const startLine = result.context_start_line || 1;

        if (oldContent || newContent) {
            return formatDiffView(file,
                newContent ? newContent.split('\n') : [],
                oldContent ? oldContent.split('\n') : [],
                tool, startLine
            );
        }
        const action = tool === 'write' ? 'written' : 'edited';
        return `<span style="color:var(--accent-green)">✓ File ${action}: ${escapeHtml(file)}</span>`;
    }

    return `<pre style="margin:0">${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
}

// ========== LCS DIFF ALGORITHM ==========
function computeLCS(a, b) {
    const m = a.length, n = b.length;
    // For very large files, skip LCS and fall back to naive
    if (m * n > 500000) return null;

    const dp = Array.from({length: m + 1}, () => new Uint16Array(n + 1));
    for (let i = 1; i <= m; i++) {
        for (let j = 1; j <= n; j++) {
            dp[i][j] = a[i-1] === b[j-1]
                ? dp[i-1][j-1] + 1
                : Math.max(dp[i-1][j], dp[i][j-1]);
        }
    }

    // Backtrack to produce diff ops
    const ops = [];
    let i = m, j = n;
    while (i > 0 || j > 0) {
        if (i > 0 && j > 0 && a[i-1] === b[j-1]) {
            ops.push({type: 'context', oldIdx: i-1, newIdx: j-1, text: a[i-1]});
            i--; j--;
        } else if (j > 0 && (i === 0 || dp[i][j-1] >= dp[i-1][j])) {
            ops.push({type: 'added', newIdx: j-1, text: b[j-1]});
            j--;
        } else {
            ops.push({type: 'removed', oldIdx: i-1, text: a[i-1]});
            i--;
        }
    }
    return ops.reverse();
}

// ========== FILE EXT → HLJS LANGUAGE ==========
const EXT_TO_LANG = {
    'py': 'python', 'js': 'javascript', 'ts': 'typescript', 'jsx': 'javascript',
    'tsx': 'typescript', 'go': 'go', 'rs': 'rust', 'rb': 'ruby', 'java': 'java',
    'c': 'c', 'cpp': 'cpp', 'h': 'c', 'hpp': 'cpp', 'cs': 'csharp',
    'sh': 'bash', 'bash': 'bash', 'zsh': 'bash', 'bat': 'dos', 'ps1': 'powershell',
    'sql': 'sql', 'html': 'xml', 'htm': 'xml', 'xml': 'xml', 'svg': 'xml',
    'css': 'css', 'scss': 'scss', 'less': 'less',
    'json': 'json', 'yaml': 'yaml', 'yml': 'yaml', 'toml': 'ini',
    'md': 'markdown', 'dockerfile': 'dockerfile', 'makefile': 'makefile',
    'tf': 'hcl', 'hcl': 'hcl', 'lua': 'lua', 'php': 'php', 'swift': 'swift',
    'kt': 'kotlin', 'r': 'r', 'pl': 'perl'
};

function getLangFromFile(filePath) {
    if (!filePath) return null;
    const name = filePath.split(/[/\\]/).pop().toLowerCase();
    if (name === 'dockerfile' || name.startsWith('dockerfile.')) return 'dockerfile';
    if (name === 'makefile' || name === 'gnumakefile') return 'makefile';
    const ext = name.includes('.') ? name.split('.').pop() : '';
    return EXT_TO_LANG[ext] || null;
}

// ========== DIFF VIEW ==========
function formatDiffView(file, newLines, oldLines, action, startLine) {
    startLine = startLine || 1;
    const lang = getLangFromFile(file);
    const diffId = 'diff-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
    let addedCount = 0, removedCount = 0;

    let html = `<div class="diff-container" id="${diffId}">
        <div class="diff-header">
            <span class="diff-header-icon">●</span>
            <span class="diff-header-text">${action === 'read' ? 'Read' : 'Edit'}</span>
            <span class="diff-header-file">${escapeHtml(file)}</span>
            <div class="diff-stats">__DIFF_STATS__</div>
        </div>
        <div class="diff-content">`;

    if (action === 'read') {
        // Read mode: single line-number column, no sign column
        newLines.forEach((line, i) => {
            html += `<div class="diff-line diff-context">
                <span class="diff-line-number">${startLine + i}</span>
                <span class="diff-line-content" style="padding-left:12px">${escapeHtml(line)}</span>
            </div>`;
        });
    } else {
        // Diff mode: LCS-based
        const ops = (oldLines && oldLines.length > 0)
            ? computeLCS(oldLines, newLines)
            : null;

        if (ops) {
            // Proper LCS diff with dual line numbers
            let oldNum = startLine, newNum = startLine;
            ops.forEach(op => {
                if (op.type === 'context') {
                    html += `<div class="diff-line diff-context">
                        <span class="diff-line-number">${oldNum}</span>
                        <span class="diff-line-number">${newNum}</span>
                        <span class="diff-line-sign"> </span>
                        <span class="diff-line-content">${escapeHtml(op.text)}</span>
                    </div>`;
                    oldNum++; newNum++;
                } else if (op.type === 'removed') {
                    removedCount++;
                    html += `<div class="diff-line diff-removed">
                        <span class="diff-line-number">${oldNum}</span>
                        <span class="diff-line-number"></span>
                        <span class="diff-line-sign">-</span>
                        <span class="diff-line-content">${escapeHtml(op.text)}</span>
                    </div>`;
                    oldNum++;
                } else if (op.type === 'added') {
                    addedCount++;
                    html += `<div class="diff-line diff-added">
                        <span class="diff-line-number"></span>
                        <span class="diff-line-number">${newNum}</span>
                        <span class="diff-line-sign">+</span>
                        <span class="diff-line-content">${escapeHtml(op.text)}</span>
                    </div>`;
                    newNum++;
                }
            });
        } else {
            // Fallback for very large diffs or new files (no old content)
            newLines.forEach((line, i) => {
                addedCount++;
                html += `<div class="diff-line diff-added">
                    <span class="diff-line-number"></span>
                    <span class="diff-line-number">${startLine + i}</span>
                    <span class="diff-line-sign">+</span>
                    <span class="diff-line-content">${escapeHtml(line)}</span>
                </div>`;
            });
        }
    }

    html += '</div></div>';

    // Insert stats
    if (action !== 'read') {
        const statsHtml =
            (addedCount ? `<span class="diff-stats-added">+${addedCount}</span> ` : '') +
            (removedCount ? `<span class="diff-stats-removed">-${removedCount}</span>` : '');
        html = html.replace('__DIFF_STATS__', statsHtml);
    } else {
        html = html.replace('__DIFF_STATS__', '');
    }

    // Schedule syntax highlighting after DOM insertion
    if (lang) {
        setTimeout(() => {
            const container = document.getElementById(diffId);
            if (!container) return;
            container.querySelectorAll('.diff-line-content').forEach(el => {
                const code = document.createElement('code');
                code.className = `language-${lang}`;
                code.textContent = el.textContent;
                el.textContent = '';
                el.appendChild(code);
                hljs.highlightElement(code);
            });
        }, 0);
    }

    return html;
}

// ========== COPY CODE ==========
function copyCode(btn) {
    const pre = btn.closest('.code-block-wrapper').querySelector('pre code');
    const text = pre.textContent;

    navigator.clipboard.writeText(text).then(() => {
        btn.textContent = 'Copied!';
        btn.classList.add('copied');
        setTimeout(() => {
            btn.textContent = 'Copy';
            btn.classList.remove('copied');
        }, 2000);
    });
}

function addCopyButtons(container) {
    // Already handled in formatContent
}

// ========== UTILITY ==========
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function scrollToBottom() {
    output.scrollTop = output.scrollHeight;
}

// ========== HEALTH CHECK ==========
async function checkHealth() {
    try {
        const r = await fetch('/api/health');
        const data = await r.json();

        if (data.ollama) {
            statusDot.classList.remove('offline');
            statusText.textContent = 'Connected';
            modelBadge.textContent = data.model;
        } else {
            statusDot.classList.add('offline');
            statusText.textContent = 'Ollama offline';
        }
    } catch (e) {
        statusDot.classList.add('offline');
        statusText.textContent = 'Disconnected';
    }
}

checkHealth();
setInterval(checkHealth, 30000);

// ========== CONFIRMATION SYSTEM ==========
function renderChoices(choices, messageId, question) {
    pendingConfirmation = { choices, messageId };
    selectedChoiceIndex = choices.findIndex(c => c.default) || 0;

    const div = document.createElement('div');
    div.id = `choices-${messageId}`;
    div.className = 'choices-container';

    div.innerHTML = `
        <div class="choices-question">${escapeHtml(question || 'Do you want to proceed?')}</div>
        <div class="choices-list">
            ${choices.map((choice, i) => `
                <div class="choice-item ${i === selectedChoiceIndex ? 'choice-active' : ''}"
                     data-index="${i}" data-id="${choice.id}">
                    <span class="choice-marker">${i === selectedChoiceIndex ? '>' : ' '}</span>
                    <span class="choice-number">${choice.id}.</span>
                    <span>${escapeHtml(choice.text)}</span>
                    <span class="choice-shortcut">${choice.shortcut}</span>
                </div>
            `).join('')}
        </div>
        <div class="choices-hint">↑↓ navigate • Enter select • Esc cancel • 1-3 quick select</div>
    `;

    setTimeout(() => {
        div.querySelectorAll('.choice-item').forEach(item => {
            item.addEventListener('click', () => confirmChoice(parseInt(item.dataset.index)));
        });
    }, 0);

    output.appendChild(div);
    scrollToBottom();
}

function updateChoiceSelection() {
    if (!pendingConfirmation) return;
    const container = document.getElementById(`choices-${pendingConfirmation.messageId}`);
    if (!container) return;

    container.querySelectorAll('.choice-item').forEach((item, i) => {
        const isActive = i === selectedChoiceIndex;
        item.classList.toggle('choice-active', isActive);
        item.querySelector('.choice-marker').textContent = isActive ? '>' : ' ';
    });
}

async function confirmChoice(index) {
    if (!pendingConfirmation) return;

    const choice = pendingConfirmation.choices[index !== undefined ? index : selectedChoiceIndex];
    const messageId = pendingConfirmation.messageId;

    const container = document.getElementById(`choices-${messageId}`);
    if (container) {
        container.innerHTML = `<div style="color:var(--accent-green)">✓ Selected: ${escapeHtml(choice.text)}</div>`;
    }

    try {
        const response = await fetch('/api/confirm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message_id: messageId,
                choice_id: choice.id,
                choice_text: choice.text
            })
        });

        const data = await response.json();
        if (data.success && data.response) {
            addMessage('assistant', data.response);
        }
    } catch (e) {
        console.error('Confirmation error:', e);
    }

    pendingConfirmation = null;
}

// Global keyboard handler
document.addEventListener('keydown', (e) => {
    // Escape to stop request
    if (e.key === 'Escape' && isProcessing && !pendingConfirmation) {
        e.preventDefault();
        stopRequest();
        return;
    }

    if (!pendingConfirmation) return;

    if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedChoiceIndex = Math.max(0, selectedChoiceIndex - 1);
        updateChoiceSelection();
    } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedChoiceIndex = Math.min(pendingConfirmation.choices.length - 1, selectedChoiceIndex + 1);
        updateChoiceSelection();
    } else if (e.key === 'Enter') {
        e.preventDefault();
        confirmChoice();
    } else if (e.key === 'Escape') {
        e.preventDefault();
        const container = document.getElementById(`choices-${pendingConfirmation.messageId}`);
        if (container) container.innerHTML = `<div style="color:var(--accent-red)">✗ Cancelled</div>`;
        pendingConfirmation = null;
    } else if (e.key >= '1' && e.key <= '9') {
        const idx = parseInt(e.key) - 1;
        if (idx < pendingConfirmation.choices.length) {
            e.preventDefault();
            confirmChoice(idx);
        }
    }
});

// ========== MODEL SELECTOR ==========
const modelSelector = document.getElementById('model-selector');
const modelBadgeBtn = document.getElementById('model-badge');
const modelDropdown = document.getElementById('model-dropdown');
const modelList = document.getElementById('model-list');
const modelNameSpan = document.getElementById('model-name');

let availableModels = [];

modelBadgeBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const isOpen = modelSelector.classList.toggle('open');
    if (isOpen) loadModels();
});

document.addEventListener('click', (e) => {
    if (!modelSelector.contains(e.target)) {
        modelSelector.classList.remove('open');
    }
});

async function loadModels() {
    modelList.innerHTML = '<div class="model-dropdown-loading">Loading...</div>';
    try {
        const r = await fetch('/api/models');
        const data = await r.json();
        availableModels = data.models || [];
        const current = data.current || '';

        if (availableModels.length === 0) {
            modelList.innerHTML = '<div class="model-dropdown-loading">No models found</div>';
            return;
        }

        // Group by provider
        const ollama = availableModels.filter(m => m.provider === 'ollama');
        const claude = availableModels.filter(m => m.provider === 'anthropic');

        let html = '';

        if (ollama.length > 0) {
            html += '<div class="model-dropdown-header">🖥️ Ollama (Local)</div>';
            html += ollama.map(m => renderModelItem(m, current)).join('');
        }

        if (claude.length > 0) {
            html += '<div class="model-dropdown-header">☁️ Claude (Anthropic API)</div>';
            html += claude.map(m => renderModelItem(m, current)).join('');
        }

        modelList.innerHTML = html;
    } catch (e) {
        modelList.innerHTML = '<div class="model-dropdown-loading">Failed to load models</div>';
    }
}

function renderModelItem(m, current) {
    const isActive = m.name === current;
    const sizeMB = m.size ? (m.size / 1024 / 1024 / 1024).toFixed(1) + ' GB' : '';
    const params = m.params || '';
    const providerIcon = m.provider === 'anthropic' ? '☁️' : '';
    const meta = [params, sizeMB].filter(Boolean).join(' • ');
    const escapedName = m.name.replace(/'/g, "\\'");
    return `
        <div class="model-item ${isActive ? 'active' : ''}"
             data-model="${m.name}"
             onclick="selectModel('${escapedName}')">
            <span class="model-item-check">${isActive ? '✓' : providerIcon}</span>
            <div class="model-item-info">
                <div class="model-item-name">${m.name}</div>
                ${meta ? `<div class="model-item-meta">${meta}</div>` : ''}
            </div>
        </div>
    `;
}

async function selectModel(name) {
    modelSelector.classList.remove('open');

    try {
        const r = await fetch('/api/models/switch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: name })
        });
        const data = await r.json();

        if (data.success) {
            modelNameSpan.textContent = name.split(':')[0];
            addMessage('system', `Model switched: ${data.old_model} → ${data.new_model}`);
        }
    } catch (e) {
        addMessage('system', `Failed to switch model: ${e.message}`);
    }
}

// ========== FULLSCREEN API ==========
const fullscreenBtn = document.getElementById('fullscreen-btn');

function toggleFullscreen() {
    if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {});
    } else {
        document.exitFullscreen();
    }
}

fullscreenBtn.addEventListener('click', toggleFullscreen);

document.addEventListener('fullscreenchange', () => {
    const isFS = !!document.fullscreenElement;
    fullscreenBtn.textContent = isFS ? '\u2716' : '\u26F6';
    fullscreenBtn.title = isFS ? 'Exit fullscreen (F11)' : 'Toggle fullscreen (F11)';
    document.body.classList.toggle('compact-mode', isFS);
});

// F11 override — use Fullscreen API instead of browser default
document.addEventListener('keydown', (e) => {
    if (e.key === 'F11') {
        e.preventDefault();
        toggleFullscreen();
    }
});

// ========== PWA INSTALL ==========
const installBtn = document.getElementById('install-btn');
let deferredPrompt = null;

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    installBtn.style.display = 'flex';
});

installBtn.addEventListener('click', async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const result = await deferredPrompt.userChoice;
    if (result.outcome === 'accepted') {
        installBtn.style.display = 'none';
    }
    deferredPrompt = null;
});

window.addEventListener('appinstalled', () => {
    installBtn.style.display = 'none';
    deferredPrompt = null;
});

// ========== SERVICE WORKER REGISTRATION ==========
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/service-worker.js').catch(() => {});
}

// ========== STANDALONE DETECTION ==========
if (window.matchMedia('(display-mode: standalone)').matches ||
    window.navigator.standalone === true) {
    document.body.classList.add('compact-mode');
}

// Focus input
input.focus();

// ========== AUTO-TEST ==========
(async function autoTest() {
    const params = new URLSearchParams(window.location.search);
    const testType = params.get('test');
    if (testType === 'multiline' || testType === 'nested') {
        // Nested indentation test: replace 4-level deep block (lines 22-31)
        const oldStr = testType === 'nested'
            ? "                    if check[\"type\"] == \"http\":\n                        container[\"health\"] = {\n                            \"endpoint\": check[\"path\"],\n                            \"interval\": 30\n                        }\n                    elif check[\"type\"] == \"tcp\":\n                        container[\"health\"] = {\n                            \"port\": check[\"port\"],\n                            \"timeout\": 10\n                        }"
            : "def hello():\n    \"\"\"Say hello\"\"\"\n    print(\"Hello World\")\n    return True";
        const newStr = testType === 'nested'
            ? "                    if check[\"type\"] == \"http\":\n                        container[\"health\"] = {\n                            \"endpoint\": check[\"path\"],\n                            \"interval\": check.get(\"interval\", 30),\n                            \"retries\": check.get(\"retries\", 3),\n                            \"timeout\": 5\n                        }\n                    elif check[\"type\"] == \"tcp\":\n                        container[\"health\"] = {\n                            \"port\": check[\"port\"],\n                            \"timeout\": check.get(\"timeout\", 10),\n                            \"retries\": 3\n                        }\n                    elif check[\"type\"] == \"exec\":\n                        container[\"health\"] = {\n                            \"command\": check[\"cmd\"],\n                            \"interval\": 60\n                        }"
            : "def hello(name=\"World\"):\n    \"\"\"Say hello to someone\"\"\"\n    greeting = f\"Hello {name}\"\n    print(greeting)\n    return greeting";
        const label = testType === 'nested'
            ? 'nested edit: replace health_check block (10 lines → 18 lines, 4-level indent)'
            : 'multiline edit: replace hello() function (4→5 lines)';
        addMessage('user', label);
        const loadId = showLoading('Running edit test...');
        try {
            const r = await fetch('/api/test-multiline-edit', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    file_path: '_test_diff.py',
                    old_string: oldStr,
                    new_string: newStr
                })
            });
            const d = await r.json();
            hideLoading(loadId);
            if (d.tool_calls) {
                for (const tc of d.tool_calls) addToolCall(tc);
            }
            // Scroll diff container to top so full diff is visible
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
})();
