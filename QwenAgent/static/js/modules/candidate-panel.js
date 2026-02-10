/**
 * CandidatePanel — two-panel overlay for comparing pipeline candidates
 *
 * Layout:
 *   ┌─ List ─────────┐ ┌─ Detail ──────────────────┐
 *   │ #1 ★ 0.91      │ │ [Code] [Diff] [Report]    │
 *   │ #2   0.72      │ │                            │
 *   │ #3   0.45      │ │   <code or diff or report> │
 *   └────────────────┘ └────────────────────────────┘
 *   ┌─ Validation Matrix ───────────────────────────┐
 *   │       #1   #2   #3                            │
 *   │ AST   ✓    ✓    ✓                             │
 *   │ Ruff  ✓    ✗    ✓                             │
 *   └───────────────────────────────────────────────┘
 */

import { dom, escapeHtml } from './dom.js';
import state from './state.js';
import eventBus from './event-bus.js';
import { CodeViewer } from './code-viewer.js';
import { ValidationMatrix } from './validation-matrix.js';

class CandidatePanel {
    constructor() {
        this._visible = false;
        this._candidates = [];
        this._selectedIdx = 0;
        this._compareIdx = -1;  // -1 = no diff
        this._codeViewer = null;
        this._validationMatrix = null;
    }

    open() {
        this._loadCandidates();
        this._visible = true;
        const panel = document.getElementById('candidate-panel');
        if (panel) {
            panel.classList.remove('hidden');
            this._render();
        }
    }

    close() {
        this._visible = false;
        const panel = document.getElementById('candidate-panel');
        if (panel) panel.classList.add('hidden');
    }

    toggle() {
        this._visible ? this.close() : this.open();
    }

    isVisible() { return this._visible; }

    _loadCandidates() {
        // Try to get from SSE state first (fast, no network)
        const pd = state.pipelineData;
        if (pd.result && pd.result._fullCandidates) {
            this._candidates = pd.result._fullCandidates;
            return;
        }

        // Fetch full candidate data from server
        fetch('/api/pipeline/candidates')
            .then(r => r.json())
            .then(data => {
                if (data.candidates && data.candidates.length > 0) {
                    this._candidates = data.candidates;
                    if (this._visible) this._render();
                }
            })
            .catch(() => {
                // Use lightweight SSE data as fallback
                this._candidates = pd.candidates.map((c, i) => ({
                    id: c.id || i + 1,
                    score: c.score || 0,
                    temperature: c.temperature || 0,
                    status: c.status || 'unknown',
                    all_passed: c.status === 'passed',
                    code: c.code || '',
                    code_lines: c.code_lines || 0,
                    generation_time: c.generation_time || 0,
                    validators: c.validators || {},
                }));
                if (this._visible) this._render();
            });
    }

    _render() {
        const panel = document.getElementById('candidate-panel');
        if (!panel || !this._visible) return;

        const cands = this._candidates;
        if (cands.length === 0) {
            panel.innerHTML = `
                <div class="cp-overlay">
                    <div class="cp-container">
                        <div class="cp-header">
                            <span class="cp-title">Candidate Comparison</span>
                            <button class="cp-close">&times;</button>
                        </div>
                        <div class="cp-empty">No candidate data available. Run a code generation query first.</div>
                    </div>
                </div>`;
            panel.querySelector('.cp-close').addEventListener('click', () => this.close());
            return;
        }

        const selected = cands[this._selectedIdx] || cands[0];
        const compare = this._compareIdx >= 0 ? cands[this._compareIdx] : null;

        let html = '<div class="cp-overlay"><div class="cp-container">';

        // Header
        html += `<div class="cp-header">
            <span class="cp-title">Candidate Comparison</span>
            <span class="cp-subtitle">${cands.length} candidates generated</span>
            <button class="cp-close">&times;</button>
        </div>`;

        // Main area: list + detail
        html += '<div class="cp-main">';

        // Left: candidate list
        html += '<div class="cp-list">';
        for (let i = 0; i < cands.length; i++) {
            const c = cands[i];
            const isSelected = i === this._selectedIdx;
            const isBest = i === 0;
            const score = (c.score || c.total_score || 0);
            const pct = Math.round(score * 100);
            const barCls = pct >= 80 ? 'cp-bar-good' : pct >= 50 ? 'cp-bar-ok' : 'cp-bar-bad';
            const selCls = isSelected ? ' cp-card-active' : '';

            html += `<div class="cp-card${selCls}" data-idx="${i}">
                <div class="cp-card-top">
                    <span class="cp-card-id">#${c.id || i + 1}${isBest ? ' &#9733;' : ''}</span>
                    <span class="cp-card-temp">T=${(c.temperature || 0).toFixed(1)}</span>
                    <span class="cp-card-score">${score.toFixed(2)}</span>
                </div>
                <div class="cp-card-bar ${barCls}" style="--pct:${pct}%"></div>
                <div class="cp-card-meta">
                    <span>${c.all_passed ? '&#10003; passed' : '&#10007; failed'}</span>
                    <span>${c.code_lines || '?'} lines</span>
                </div>
                ${i !== this._selectedIdx ? `<button class="cp-diff-btn" data-compare="${i}" title="Compare with selected">Diff</button>` : ''}
            </div>`;
        }
        html += '</div>';

        // Right: detail (code viewer)
        html += '<div class="cp-detail"><div id="cp-code-viewer"></div></div>';

        html += '</div>'; // .cp-main

        // Bottom: validation matrix
        html += '<div class="cp-matrix-section">';
        html += '<div class="cp-matrix-title">Validation Matrix</div>';
        html += '<div id="cp-validation-matrix"></div>';
        html += '</div>';

        html += '</div></div>'; // .cp-container, .cp-overlay
        panel.innerHTML = html;

        // Initialize sub-components
        const codeViewerEl = document.getElementById('cp-code-viewer');
        this._codeViewer = new CodeViewer(codeViewerEl);
        this._codeViewer.setCandidate(selected, compare);

        const matrixEl = document.getElementById('cp-validation-matrix');
        this._validationMatrix = new ValidationMatrix(matrixEl);
        this._validationMatrix.render(cands);

        // Bind events
        panel.querySelector('.cp-close').addEventListener('click', () => this.close());

        panel.querySelectorAll('.cp-card').forEach(card => {
            card.addEventListener('click', (e) => {
                if (e.target.classList.contains('cp-diff-btn')) return;
                this._selectedIdx = parseInt(card.dataset.idx);
                this._compareIdx = -1;
                this._render();
            });
        });

        panel.querySelectorAll('.cp-diff-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._compareIdx = parseInt(btn.dataset.compare);
                this._render();
            });
        });

        // ESC to close
        this._escHandler = (e) => {
            if (e.key === 'Escape' && this._visible) {
                e.preventDefault();
                this.close();
                document.removeEventListener('keydown', this._escHandler);
            }
        };
        document.addEventListener('keydown', this._escHandler);
    }
}

export const candidatePanel = new CandidatePanel();
export default candidatePanel;
