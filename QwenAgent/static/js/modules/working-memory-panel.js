/**
 * Working Memory Panel — Phase 7
 *
 * Real-time visualization of agent's working memory:
 * - Goal & plan progress
 * - Discovered facts (key-value)
 * - Decision log
 * - Tool call history with success/failure
 * - Iteration counter
 */

import { dom, escapeHtml } from './dom.js';
import eventBus from './event-bus.js';

class WorkingMemoryPanel {
    constructor() {
        this._el = null;
        this._visible = false;
        this._state = null;
        this._history = []; // last N snapshots
        this._maxHistory = 30;
    }

    init() {
        this._listenSSE();
    }

    _listenSSE() {
        eventBus.on('sse:working_memory', (evt) => {
            this._state = evt;
            this._history.push({
                iteration: evt.iteration,
                facts_count: Object.keys(evt.facts || {}).length,
                tool_log_length: (evt.tool_log || []).length,
                tool: evt.tool_just_executed || '',
            });
            if (this._history.length > this._maxHistory) {
                this._history = this._history.slice(-this._maxHistory);
            }
            if (this._visible) {
                this._render();
            }
        });

        // Reset on new request
        eventBus.on('sse:done', () => {
            // Keep last state visible but stop updating
        });
    }

    open() {
        this._ensureContainer();
        this._visible = true;
        this._el.classList.remove('hidden');
        this._render();
    }

    close() {
        this._visible = false;
        if (this._el) {
            this._el.classList.add('hidden');
        }
    }

    toggle() {
        if (this._visible) this.close();
        else this.open();
    }

    _ensureContainer() {
        this._el = document.getElementById('working-memory-panel');
        if (!this._el) {
            this._el = document.createElement('div');
            this._el.id = 'working-memory-panel';
            this._el.className = 'hidden';
            document.body.appendChild(this._el);
        }
    }

    _render() {
        if (!this._el) return;
        const s = this._state;

        if (!s) {
            this._el.innerHTML = `<div class="wm-overlay" onclick="window.__wmClose()">
                <div class="wm-panel" onclick="event.stopPropagation()">
                    <div class="wm-header">
                        <span class="wm-title">Working Memory</span>
                        <button class="wm-close" onclick="window.__wmClose()">&times;</button>
                    </div>
                    <div class="wm-body">
                        <div class="wm-empty">No working memory data yet. Send a query that triggers the agentic loop.</div>
                    </div>
                </div>
            </div>`;
            window.__wmClose = () => this.close();
            return;
        }

        const facts = s.facts || {};
        const decisions = s.decisions || [];
        const toolLog = s.tool_log || [];
        const plan = s.plan || [];

        let html = `<div class="wm-overlay" onclick="window.__wmClose()">
            <div class="wm-panel" onclick="event.stopPropagation()">
                <div class="wm-header">
                    <span class="wm-title">Working Memory</span>
                    <span class="wm-iter">Iteration ${s.iteration || 0}</span>
                    <button class="wm-close" onclick="window.__wmClose()">&times;</button>
                </div>
                <div class="wm-body">`;

        // Goal
        html += `<div class="wm-section">
            <div class="wm-section-title">Goal</div>
            <div class="wm-goal">${escapeHtml(s.goal || '(none)')}</div>
        </div>`;

        // Plan
        if (plan.length > 0) {
            html += `<div class="wm-section">
                <div class="wm-section-title">Plan</div>
                <div class="wm-plan">`;
            for (const step of plan) {
                const statusIcon = step.status === 'done' ? '&#10003;'
                    : step.status === 'active' ? '&#9675;'
                    : step.status === 'skipped' ? '&#8212;'
                    : '&#9679;';
                const cls = step.status === 'done' ? 'wm-plan-done'
                    : step.status === 'active' ? 'wm-plan-active'
                    : step.status === 'skipped' ? 'wm-plan-skipped'
                    : 'wm-plan-pending';
                html += `<div class="wm-plan-step ${cls}">
                    <span class="wm-plan-icon">${statusIcon}</span>
                    <span class="wm-plan-desc">${escapeHtml(step.desc)}</span>
                </div>`;
            }
            html += '</div></div>';
        }

        // Facts
        html += `<div class="wm-section">
            <div class="wm-section-title">Facts <span class="wm-badge">${Object.keys(facts).length}</span></div>`;
        if (Object.keys(facts).length === 0) {
            html += '<div class="wm-empty">No facts discovered yet</div>';
        } else {
            html += '<div class="wm-facts">';
            for (const [key, value] of Object.entries(facts)) {
                html += `<div class="wm-fact">
                    <span class="wm-fact-key">${escapeHtml(key)}</span>
                    <span class="wm-fact-val">${escapeHtml(String(value).substring(0, 200))}</span>
                </div>`;
            }
            html += '</div>';
        }
        html += '</div>';

        // Decisions
        if (decisions.length > 0) {
            html += `<div class="wm-section">
                <div class="wm-section-title">Decisions <span class="wm-badge">${decisions.length}</span></div>
                <div class="wm-decisions">`;
            for (const d of decisions) {
                html += `<div class="wm-decision">${escapeHtml(d)}</div>`;
            }
            html += '</div></div>';
        }

        // Tool Log
        html += `<div class="wm-section">
            <div class="wm-section-title">Tool Log <span class="wm-badge">${toolLog.length}</span></div>`;
        if (toolLog.length === 0) {
            html += '<div class="wm-empty">No tool calls yet</div>';
        } else {
            html += '<div class="wm-toollog">';
            for (const t of toolLog) {
                const cls = t.success ? 'wm-tool-ok' : 'wm-tool-fail';
                const icon = t.success ? '&#10003;' : '&#10007;';
                html += `<div class="wm-tool ${cls}">
                    <span class="wm-tool-icon">${icon}</span>
                    <span class="wm-tool-name">${escapeHtml(t.tool)}</span>
                    <span class="wm-tool-summary">${escapeHtml(t.summary)}</span>
                </div>`;
            }
            html += '</div>';
        }
        html += '</div>';

        // Iteration mini-chart
        if (this._history.length > 1) {
            html += `<div class="wm-section">
                <div class="wm-section-title">Knowledge Growth</div>
                <div class="wm-growth">`;
            for (const h of this._history) {
                const height = Math.min(100, (h.facts_count || 0) * 10);
                html += `<div class="wm-growth-bar" style="height:${height}%" title="Iter ${h.iteration}: ${h.facts_count} facts, tool: ${h.tool}"></div>`;
            }
            html += '</div></div>';
        }

        html += '</div></div></div>';
        this._el.innerHTML = html;
        window.__wmClose = () => this.close();
    }
}

export const workingMemoryPanel = new WorkingMemoryPanel();
export default workingMemoryPanel;
