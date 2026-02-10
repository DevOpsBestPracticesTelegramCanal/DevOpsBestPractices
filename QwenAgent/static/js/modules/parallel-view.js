/**
 * Parallel View — Phase 7
 *
 * Split terminal view for comparing concurrent or sequential tasks.
 * Left pane shows the main chat; right pane shows a secondary output
 * (e.g., pipeline monitor expanded, working memory, or a second query).
 *
 * This is a UI layout manager — it restructures the main content area
 * into two side-by-side panels with adjustable split.
 */

import { dom } from './dom.js';
import eventBus from './event-bus.js';

class ParallelView {
    constructor() {
        this._active = false;
        this._splitRatio = 0.5;
        this._rightContent = 'pipeline'; // 'pipeline' | 'memory' | 'empty'
    }

    init() {
        // Listen for keyboard shortcut
        document.addEventListener('keydown', (e) => {
            // Ctrl+Shift+P to toggle parallel view
            if (e.ctrlKey && e.shiftKey && e.key === 'P') {
                e.preventDefault();
                this.toggle();
            }
        });
    }

    get isActive() {
        return this._active;
    }

    toggle() {
        if (this._active) this.deactivate();
        else this.activate();
    }

    activate(rightContent) {
        if (rightContent) this._rightContent = rightContent;
        this._active = true;
        this._applyLayout();
        eventBus.emit('parallel:activated', { rightContent: this._rightContent });
    }

    deactivate() {
        this._active = false;
        this._removeLayout();
        eventBus.emit('parallel:deactivated');
    }

    setRightContent(type) {
        this._rightContent = type;
        if (this._active) this._applyLayout();
    }

    _applyLayout() {
        const mainContent = document.querySelector('.main-content');
        if (!mainContent) return;

        mainContent.classList.add('parallel-active');

        // Create or get right pane
        let rightPane = document.getElementById('parallel-right');
        if (!rightPane) {
            rightPane = document.createElement('div');
            rightPane.id = 'parallel-right';
            rightPane.className = 'parallel-right-pane';
            mainContent.appendChild(rightPane);
        }

        // Create or get divider
        let divider = document.getElementById('parallel-divider');
        if (!divider) {
            divider = document.createElement('div');
            divider.id = 'parallel-divider';
            divider.className = 'parallel-divider';
            divider.title = 'Drag to resize';
            // Insert before right pane
            mainContent.insertBefore(divider, rightPane);
            this._initDrag(divider, mainContent);
        }

        this._updateRightContent(rightPane);
        this._applySplitRatio(mainContent);
    }

    _removeLayout() {
        const mainContent = document.querySelector('.main-content');
        if (!mainContent) return;

        mainContent.classList.remove('parallel-active');

        const rightPane = document.getElementById('parallel-right');
        const divider = document.getElementById('parallel-divider');
        if (rightPane) rightPane.remove();
        if (divider) divider.remove();

        // Reset terminal container width
        const terminal = mainContent.querySelector('.terminal-container');
        if (terminal) terminal.style.flex = '';
    }

    _updateRightContent(pane) {
        let html = '<div class="pv-header">';
        html += '<div class="pv-tabs">';
        html += `<button class="pv-tab${this._rightContent === 'pipeline' ? ' pv-tab-active' : ''}" onclick="window.__pvTab('pipeline')">Pipeline</button>`;
        html += `<button class="pv-tab${this._rightContent === 'memory' ? ' pv-tab-active' : ''}" onclick="window.__pvTab('memory')">Memory</button>`;
        html += '</div>';
        html += '<button class="pv-close" onclick="window.__pvClose()" title="Close parallel view">&times;</button>';
        html += '</div>';

        html += '<div class="pv-content" id="pv-content">';
        if (this._rightContent === 'pipeline') {
            // Clone pipeline monitor content
            const pmContent = document.querySelector('.pm-content');
            if (pmContent) {
                html += pmContent.innerHTML;
            } else {
                html += '<div class="pv-empty">Pipeline monitor not available</div>';
            }
        } else if (this._rightContent === 'memory') {
            html += '<div class="pv-empty">Working memory updates will appear here during agent execution</div>';
        } else {
            html += '<div class="pv-empty">Select a panel to display</div>';
        }
        html += '</div>';

        pane.innerHTML = html;

        // Wire global handlers
        window.__pvClose = () => this.deactivate();
        window.__pvTab = (type) => this.setRightContent(type);

        // If memory tab, listen for updates
        if (this._rightContent === 'memory') {
            this._listenMemoryUpdates(pane);
        }
    }

    _listenMemoryUpdates(pane) {
        const handler = (evt) => {
            if (!this._active || this._rightContent !== 'memory') {
                eventBus.off('sse:working_memory', handler);
                return;
            }
            const content = pane.querySelector('#pv-content');
            if (!content) return;

            const facts = evt.facts || {};
            const toolLog = evt.tool_log || [];
            let html = `<div class="pv-mem-iter">Iteration ${evt.iteration || 0}</div>`;

            if (evt.goal) {
                html += `<div class="pv-mem-goal">${this._esc(evt.goal)}</div>`;
            }

            html += '<div class="pv-mem-section"><strong>Facts (${Object.keys(facts).length})</strong>';
            for (const [k, v] of Object.entries(facts)) {
                html += `<div class="pv-mem-fact"><span>${this._esc(k)}</span><span>${this._esc(String(v).substring(0, 120))}</span></div>`;
            }
            html += '</div>';

            html += `<div class="pv-mem-section"><strong>Tools (${toolLog.length})</strong>`;
            for (const t of toolLog) {
                const icon = t.success ? '&#10003;' : '&#10007;';
                html += `<div class="pv-mem-tool">${icon} ${this._esc(t.tool)}: ${this._esc(t.summary || '')}</div>`;
            }
            html += '</div>';

            content.innerHTML = html;
        };

        eventBus.on('sse:working_memory', handler);
    }

    _esc(s) {
        const div = document.createElement('div');
        div.textContent = s;
        return div.innerHTML;
    }

    _applySplitRatio(mainContent) {
        const terminal = mainContent.querySelector('.terminal-container');
        const rightPane = document.getElementById('parallel-right');
        if (terminal && rightPane) {
            terminal.style.flex = `0 0 ${this._splitRatio * 100}%`;
            rightPane.style.flex = `0 0 ${(1 - this._splitRatio) * 100 - 1}%`;
        }
    }

    _initDrag(divider, container) {
        let isDragging = false;

        divider.addEventListener('mousedown', (e) => {
            isDragging = true;
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });

        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            const rect = container.getBoundingClientRect();
            const ratio = (e.clientX - rect.left) / rect.width;
            this._splitRatio = Math.max(0.25, Math.min(0.75, ratio));
            this._applySplitRatio(container);
        });

        document.addEventListener('mouseup', () => {
            if (isDragging) {
                isDragging = false;
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            }
        });
    }
}

export const parallelView = new ParallelView();
export default parallelView;
