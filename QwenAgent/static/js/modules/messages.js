/**
 * Message display — addMessage, addToolCall, addThinking, showLoading
 */

import { dom, scrollToBottom, escapeHtml } from './dom.js';
import { TOOL_ICONS, ROUTE_ICONS, ROUTE_LABELS } from './constants.js';
import { formatContent, formatToolResult } from './formatting.js';

// Week 20: Streaming message counter
let _streamMsgCounter = 0;

function countLines(str) {
    return (str.match(/\n/g) || []).length + 1;
}

function toggleCollapsible(element) {
    element.classList.toggle('collapsed');
}

// Expose globally for onclick in generated HTML
window.__toggleCollapsible = toggleCollapsible;

function createCollapsible(summary, content, startCollapsed = true) {
    const wrapper = document.createElement('div');
    wrapper.className = 'collapsible' + (startCollapsed ? ' collapsed' : '');

    const summaryEl = document.createElement('div');
    summaryEl.className = 'collapse-summary';
    summaryEl.innerHTML = `
        <span class="expand-btn"><span class="arrow">▼</span></span>
        <span>${summary}</span>
        <span class="expand-hint">(ctrl+o to expand)</span>
    `;
    summaryEl.onclick = () => toggleCollapsible(wrapper);

    const contentEl = document.createElement('div');
    contentEl.className = 'collapsible-content';
    if (typeof content === 'string') {
        contentEl.innerHTML = content;
    } else {
        contentEl.appendChild(content);
    }

    wrapper.appendChild(summaryEl);
    wrapper.appendChild(contentEl);
    return wrapper;
}

function getRouteIcon(routeMethod) {
    return ROUTE_ICONS[routeMethod] || '💬';
}

function getRouteLabel(routeMethod) {
    return ROUTE_LABELS[routeMethod] || 'Response';
}

export function addMessage(type, content, routeMethod = null) {
    const div = document.createElement('div');
    div.className = 'message';

    if (type === 'user') {
        const userContent = escapeHtml(content).replace(/\n/g, '<br>');
        div.innerHTML = `
            <div class="message-user">
                <span class="message-prompt">❯</span>
                <span class="message-content">${userContent}</span>
            </div>
        `;
    } else if (type === 'assistant') {
        const routeIcon = getRouteIcon(routeMethod);
        const routeLabel = getRouteLabel(routeMethod);
        const showHeader = routeMethod && routeMethod !== '';

        div.innerHTML = `
            <div class="message-assistant">
                ${showHeader ? `
                    <div class="message-header">
                        <span>${routeIcon}</span>
                        <span>${routeLabel}</span>
                    </div>
                ` : ''}
                <div class="message-body">
                    ${formatContent(content)}
                </div>
            </div>
        `;
    } else {
        div.innerHTML = `<div class="message-system">${content}</div>`;
    }

    dom.output.appendChild(div);
    scrollToBottom();

    // Highlight code blocks
    div.querySelectorAll('pre code').forEach(block => {
        hljs.highlightElement(block);
    });
    div.querySelectorAll('.code-block-content').forEach(block => {
        const lang = block.dataset.lang;
        if (lang && lang !== 'plaintext') {
            block.querySelectorAll('.code-line-content').forEach(lineEl => {
                const text = lineEl.textContent;
                try {
                    const result = hljs.highlight(text, { language: lang, ignoreIllegals: true });
                    lineEl.innerHTML = result.value;
                } catch (e) { /* Language not supported */ }
            });
        }
    });
}

export function addToolCall(tc) {
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

    const resultStr = isSuccess
        ? formatToolResult(tc.tool, tc.result)
        : `<span style="color: var(--accent-red)">Error: ${escapeHtml(tc.result.error)}</span>`;

    const resultText = tc.result.content || tc.result.output || JSON.stringify(tc.result);
    const lineCount = countLines(resultText);
    const shouldCollapse = lineCount > 10 || resultText.length > 500;

    const headerHtml = `
        <div class="tool-header">
            <span class="tool-icon">${icon}</span>
            <span class="tool-name">${tc.tool}</span>
            <span class="tool-params">(${params})</span>
            <span class="tool-status ${statusClass}">${statusIcon}</span>
        </div>
    `;

    if (shouldCollapse) {
        div.innerHTML = headerHtml;
        const summary = `${tc.tool} result: <span class="line-count">${lineCount} lines</span>`;
        const collapsible = createCollapsible(summary, `<div class="tool-result">${resultStr}</div>`, true);
        div.appendChild(collapsible);
    } else {
        div.innerHTML = headerHtml + `<div class="tool-result">${resultStr}</div>`;
    }

    dom.output.appendChild(div);
    scrollToBottom();
}

export function addThinking(thinking) {
    const div = document.createElement('div');
    div.className = 'thinking-block collapsible collapsed';

    const content = Array.isArray(thinking) ? thinking.join('\n') : thinking;
    const lineCount = countLines(content);

    div.innerHTML = `
        <div class="thinking-header collapse-summary" onclick="window.__toggleCollapsible(this.parentElement)">
            <span class="expand-btn"><span class="arrow">▼</span></span>
            <span>🧠</span>
            <span>Thinking</span>
            <span class="line-count">(${lineCount} lines)</span>
            <span class="expand-hint">(ctrl+o to expand)</span>
        </div>
        <div class="collapsible-content">
            <div class="thinking-content">${escapeHtml(content)}</div>
        </div>
    `;

    dom.output.appendChild(div);
    scrollToBottom();
}

export function showLoading(text = 'Processing...') {
    const id = 'loading-' + Date.now();
    const div = document.createElement('div');
    div.id = id;
    div.className = 'loading';
    div.innerHTML = `
        <div class="loading-spinner"></div>
        <span class="loading-dot"></span>
        <span class="loading-text status-executing">${escapeHtml(text)}</span>
    `;
    dom.output.appendChild(div);
    scrollToBottom();
    return id;
}

export function hideLoading(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

export function updateLoading(id, text) {
    const el = document.getElementById(id);
    if (el) {
        const textEl = el.querySelector('.loading-text');
        if (textEl) textEl.textContent = text;
    }
}

export function toggleAllCollapsed() {
    const collapsibles = document.querySelectorAll('.collapsible.collapsed');
    if (collapsibles.length > 0) {
        collapsibles.forEach(el => el.classList.remove('collapsed'));
    } else {
        const expandables = document.querySelectorAll('.collapsible:not(.collapsed)');
        expandables.forEach(el => el.classList.add('collapsed'));
    }
}

// Week 20: Streaming message support

/**
 * Create a streaming message element with blinking cursor.
 * @param {string} msgId - Unique message ID
 * @returns {HTMLElement} The created message element
 */
export function createStreamingMessage(msgId) {
    _streamMsgCounter++;
    const div = document.createElement('div');
    div.className = 'message streaming-message';
    div.id = `streaming-msg-${msgId || _streamMsgCounter}`;

    div.innerHTML = `
        <div class="message-assistant">
            <div class="message-body">
                <span class="streaming-text"></span><span class="streaming-cursor">|</span>
            </div>
        </div>
    `;

    dom.output.appendChild(div);
    scrollToBottom();
    return div;
}

/**
 * Append raw text to a streaming message element.
 * @param {HTMLElement} el - The streaming message element
 * @param {string} text - Text chunk to append
 */
export function appendToStreamingMessage(el, text) {
    if (!el) return;
    const span = el.querySelector('.streaming-text');
    if (span) {
        span.textContent += text;
    }
}

/**
 * Finalize a streaming message: remove cursor, apply formatting + highlighting.
 * @param {HTMLElement} el - The streaming message element
 * @param {string} fullContent - The complete response text
 */
export function finalizeStreamingMessage(el, fullContent) {
    if (!el) return;

    el.classList.remove('streaming-message');

    // Remove cursor
    const cursor = el.querySelector('.streaming-cursor');
    if (cursor) cursor.remove();

    // Replace raw text with formatted content
    const body = el.querySelector('.message-body');
    if (body) {
        body.innerHTML = formatContent(fullContent);

        // Syntax highlighting
        body.querySelectorAll('pre code').forEach(block => {
            hljs.highlightElement(block);
        });
        body.querySelectorAll('.code-block-content').forEach(block => {
            const lang = block.dataset.lang;
            if (lang && lang !== 'plaintext') {
                block.querySelectorAll('.code-line-content').forEach(lineEl => {
                    const text = lineEl.textContent;
                    try {
                        const result = hljs.highlight(text, { language: lang, ignoreIllegals: true });
                        lineEl.innerHTML = result.value;
                    } catch (e) { /* Language not supported */ }
                });
            }
        });
    }

    scrollToBottom();
}
