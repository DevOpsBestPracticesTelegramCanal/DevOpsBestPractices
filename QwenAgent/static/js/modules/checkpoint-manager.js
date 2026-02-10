/**
 * Checkpoint Manager — Phase 7
 *
 * Save and restore pipeline/memory state checkpoints.
 * - Save current working memory state as a named checkpoint
 * - List saved checkpoints with timestamp and stats
 * - Restore/inspect a checkpoint
 * - Delete checkpoints
 */

import { escapeHtml } from './dom.js';
import eventBus from './event-bus.js';

class CheckpointManager {
    constructor() {
        this._el = null;
        this._visible = false;
        this._checkpoints = [];
        this._selectedId = null;
        this._selectedDetail = null;
    }

    init() {
        eventBus.on('sse:checkpoint_saved', (evt) => {
            // Auto-refresh if visible
            if (this._visible) this._loadCheckpoints();
        });
    }

    open() {
        this._ensureContainer();
        this._visible = true;
        this._el.classList.remove('hidden');
        this._loadCheckpoints();
    }

    close() {
        this._visible = false;
        if (this._el) this._el.classList.add('hidden');
    }

    async save(description) {
        try {
            const res = await fetch('/api/checkpoints', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ description: description || `Checkpoint at ${new Date().toLocaleTimeString()}` }),
            });
            const data = await res.json();
            if (data.success) {
                await this._loadCheckpoints();
            }
            return data;
        } catch (e) {
            console.error('[CheckpointManager] save error:', e);
            return { success: false, error: e.message };
        }
    }

    async _loadCheckpoints() {
        try {
            const res = await fetch('/api/checkpoints');
            this._checkpoints = await res.json();
        } catch (e) {
            this._checkpoints = [];
        }
        this._render();
    }

    async _loadDetail(id) {
        try {
            const res = await fetch(`/api/checkpoints/${id}`);
            this._selectedDetail = await res.json();
            this._selectedId = id;
        } catch (e) {
            this._selectedDetail = null;
        }
        this._render();
    }

    async _deleteCheckpoint(id) {
        try {
            await fetch(`/api/checkpoints/${id}`, { method: 'DELETE' });
            if (this._selectedId === id) {
                this._selectedId = null;
                this._selectedDetail = null;
            }
            await this._loadCheckpoints();
        } catch (e) {
            console.error('[CheckpointManager] delete error:', e);
        }
    }

    _ensureContainer() {
        this._el = document.getElementById('checkpoint-manager');
        if (!this._el) {
            this._el = document.createElement('div');
            this._el.id = 'checkpoint-manager';
            this._el.className = 'hidden';
            document.body.appendChild(this._el);
        }
    }

    _render() {
        if (!this._el) return;

        let html = `<div class="ckm-overlay" onclick="window.__ckmClose()">
            <div class="ckm-panel" onclick="event.stopPropagation()">
                <div class="ckm-header">
                    <span class="ckm-title">Checkpoints</span>
                    <div class="ckm-actions">
                        <button class="ckm-save-btn" onclick="window.__ckmSave()">&#128190; Save</button>
                        <button class="ckm-close" onclick="window.__ckmClose()">&times;</button>
                    </div>
                </div>
                <div class="ckm-body">`;

        if (this._checkpoints.length === 0) {
            html += '<div class="ckm-empty">No checkpoints saved. Click "Save" to create one from the current working memory state.</div>';
        } else {
            html += '<div class="ckm-layout">';

            // List
            html += '<div class="ckm-list">';
            for (const cp of this._checkpoints) {
                const selected = cp.id === this._selectedId ? ' ckm-item-selected' : '';
                const ts = cp.timestamp ? new Date(cp.timestamp).toLocaleTimeString() : '';
                html += `<div class="ckm-item${selected}" onclick="window.__ckmSelect('${cp.id}')">
                    <div class="ckm-item-desc">${escapeHtml(cp.description)}</div>
                    <div class="ckm-item-meta">
                        <span>${ts}</span>
                        <span>${cp.facts_count || 0} facts</span>
                        <span>${cp.tool_log_length || 0} tools</span>
                    </div>
                    <button class="ckm-item-delete" onclick="event.stopPropagation(); window.__ckmDelete('${cp.id}')" title="Delete">&times;</button>
                </div>`;
            }
            html += '</div>';

            // Detail
            html += '<div class="ckm-detail">';
            if (this._selectedDetail) {
                const sd = this._selectedDetail;
                const state = sd.state || {};
                html += `<div class="ckm-detail-header">${escapeHtml(sd.description)}</div>
                    <div class="ckm-detail-time">${sd.timestamp ? new Date(sd.timestamp).toLocaleString() : ''}</div>`;

                // Goal
                if (state.goal) {
                    html += `<div class="ckm-detail-section">
                        <div class="ckm-detail-label">Goal</div>
                        <div class="ckm-detail-val">${escapeHtml(state.goal)}</div>
                    </div>`;
                }

                // Facts
                const facts = state.facts || {};
                if (Object.keys(facts).length > 0) {
                    html += `<div class="ckm-detail-section">
                        <div class="ckm-detail-label">Facts (${Object.keys(facts).length})</div>`;
                    for (const [k, v] of Object.entries(facts)) {
                        html += `<div class="ckm-fact">
                            <span class="ckm-fact-key">${escapeHtml(k)}</span>
                            <span class="ckm-fact-val">${escapeHtml(String(v).substring(0, 150))}</span>
                        </div>`;
                    }
                    html += '</div>';
                }

                // Tool log
                const toolLog = state.tool_log || [];
                if (toolLog.length > 0) {
                    html += `<div class="ckm-detail-section">
                        <div class="ckm-detail-label">Tool Log (${toolLog.length})</div>`;
                    for (const t of toolLog) {
                        const icon = t.success ? '&#10003;' : '&#10007;';
                        const cls = t.success ? 'ckm-tool-ok' : 'ckm-tool-fail';
                        html += `<div class="ckm-tool ${cls}">
                            <span>${icon}</span>
                            <span>${escapeHtml(t.tool)}</span>
                            <span>${escapeHtml(t.summary || '')}</span>
                        </div>`;
                    }
                    html += '</div>';
                }

                // Decisions
                const decisions = state.decisions || [];
                if (decisions.length > 0) {
                    html += `<div class="ckm-detail-section">
                        <div class="ckm-detail-label">Decisions (${decisions.length})</div>`;
                    for (const d of decisions) {
                        html += `<div class="ckm-decision">${escapeHtml(d)}</div>`;
                    }
                    html += '</div>';
                }
            } else {
                html += '<div class="ckm-empty">Select a checkpoint to inspect</div>';
            }
            html += '</div>';
            html += '</div>'; // ckm-layout
        }

        html += '</div></div></div>';
        this._el.innerHTML = html;

        // Wire up global handlers
        window.__ckmClose = () => this.close();
        window.__ckmSave = () => {
            const desc = prompt('Checkpoint description:');
            if (desc !== null) this.save(desc);
        };
        window.__ckmSelect = (id) => this._loadDetail(id);
        window.__ckmDelete = (id) => this._deleteCheckpoint(id);
    }
}

export const checkpointManager = new CheckpointManager();
export default checkpointManager;
