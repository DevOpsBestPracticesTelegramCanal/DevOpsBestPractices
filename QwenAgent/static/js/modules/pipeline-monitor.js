/**
 * Pipeline Monitor — collapsible sidebar showing pipeline stages, candidates, validation
 */

import { dom, escapeHtml } from './dom.js';
import state from './state.js';
import eventBus from './event-bus.js';
import { candidatePanel } from './candidate-panel.js';
import { correctionTracker } from './correction-tracker.js';

const STAGES = [
    { id: 'classify',  label: 'Classify',  icon: '①' },
    { id: 'generate',  label: 'Generate',  icon: '②' },
    { id: 'validate',  label: 'Validate',  icon: '③' },
    { id: 'select',    label: 'Select',    icon: '④' },
    { id: 'correct',   label: 'Correct',   icon: '⑤' },
    { id: 'output',    label: 'Output',    icon: '⑥' },
];

class PipelineMonitor {
    constructor() {
        this.collapsed = true;
        this._startTime = null;
        this._stageTimers = {};
    }

    init() {
        this._bindToggle();
        this._listenSSE();
        this._render();
    }

    _bindToggle() {
        if (dom.pipelineToggle) {
            dom.pipelineToggle.addEventListener('click', () => this.toggle());
        }
    }

    toggle() {
        this.collapsed = !this.collapsed;
        const panel = dom.pipelineMonitor;
        if (!panel) return;
        panel.classList.toggle('collapsed', this.collapsed);
        if (dom.pipelineToggle) {
            dom.pipelineToggle.textContent = this.collapsed ? '◀' : '▶';
            dom.pipelineToggle.title = this.collapsed ? 'Show Pipeline Monitor' : 'Hide Pipeline Monitor';
        }
    }

    _listenSSE() {
        // Task classification
        eventBus.on('sse:task_context', (event) => {
            state.pipelineData.taskContext = event;
            state.pipelineData.active = true;
            this._setStageStatus('classify', 'done', event);
            this._render();
            // Auto-expand on pipeline activity
            if (this.collapsed) this.toggle();
        });

        // Pipeline start
        eventBus.on('sse:pipeline_start', (event) => {
            state.pipelineData.candidates = [];
            state.pipelineData.result = null;
            state.pipelineData.correctionData = null;
            state.pipelineData.stages = [];
            this._startTime = performance.now();
            this._setStageStatus('generate', 'active', event);
            this._render();
        });

        // Per-candidate progress
        eventBus.on('sse:pipeline_candidate', (event) => {
            state.pipelineData.candidates.push(event);
            this._render();
        });

        // Phase 2: Full candidate comparison data (pipeline_validation)
        eventBus.on('sse:pipeline_validation', (event) => {
            if (event.candidates) {
                state.pipelineData.candidateComparison = event.candidates;
                // Store full data so candidate panel can use it
                if (state.pipelineData.result) {
                    state.pipelineData.result._fullCandidates = event.candidates;
                }
            }
        });

        // Pipeline result
        eventBus.on('sse:pipeline_result', (event) => {
            state.pipelineData.result = event;
            state.pipelineData.validationStats = event.validation_stats || null;
            this._setStageStatus('generate', 'done');
            this._setStageStatus('validate', 'done');
            this._setStageStatus('select', 'done');
            this._setStageStatus('output', 'done');
            this._render();
        });

        // Self-correction events
        eventBus.on('sse:correction_start', (event) => {
            state.pipelineData.correctionData = { ...event, iterations: [] };
            this._setStageStatus('correct', 'active');
            this._render();
        });

        eventBus.on('sse:correction_iteration', (event) => {
            if (state.pipelineData.correctionData) {
                state.pipelineData.correctionData.iterations.push(event);
            }
            this._render();
            correctionTracker.update();
        });

        eventBus.on('sse:correction_result', (event) => {
            if (state.pipelineData.correctionData) {
                state.pipelineData.correctionData.result = event;
            }
            this._setStageStatus('correct', 'done');
            this._render();
            correctionTracker.update();
        });

        // Reset on done
        eventBus.on('sse:done', () => {
            // Keep data visible but mark inactive
            setTimeout(() => {
                state.pipelineData.active = false;
                this._render();
            }, 500);
        });
    }

    _setStageStatus(stageId, status, data = null) {
        const existing = state.pipelineData.stages.find(s => s.id === stageId);
        if (existing) {
            existing.status = status;
            if (data) existing.data = data;
            if (status === 'active') existing.startTime = performance.now();
            if (status === 'done' && existing.startTime) {
                existing.duration = ((performance.now() - existing.startTime) / 1000).toFixed(1);
            }
        } else {
            state.pipelineData.stages.push({
                id: stageId,
                status,
                data,
                startTime: status === 'active' ? performance.now() : null,
                duration: null,
            });
        }
    }

    _render() {
        const panel = dom.pipelineMonitor;
        if (!panel) return;

        const pd = state.pipelineData;
        const tc = pd.taskContext;

        let html = '<div class="pm-header">Pipeline Monitor</div>';

        // Task context
        if (tc) {
            html += `<div class="pm-section">
                <div class="pm-section-title">Task</div>
                <div class="pm-kv"><span>Type</span><span class="pm-val">${escapeHtml(tc.task_type || '—')}</span></div>
                <div class="pm-kv"><span>Risk</span><span class="pm-val pm-risk-${tc.risk_level || 'medium'}">${escapeHtml(tc.risk_level || '—')}</span></div>
                <div class="pm-kv"><span>Profile</span><span class="pm-val">${escapeHtml(tc.validation_profile || '—')}</span></div>
                ${tc.complexity ? `<div class="pm-kv"><span>Complexity</span><span class="pm-val">${escapeHtml(tc.complexity)}</span></div>` : ''}
                ${tc.swecas_code ? `<div class="pm-kv"><span>SWECAS</span><span class="pm-val">${tc.swecas_code}</span></div>` : ''}
                ${tc.ducs_code ? `<div class="pm-kv"><span>DUCS</span><span class="pm-val">${tc.ducs_code}</span></div>` : ''}
            </div>`;
        }

        // Pipeline stages
        html += '<div class="pm-section"><div class="pm-section-title">Stage</div>';
        for (const stage of STAGES) {
            const s = pd.stages.find(x => x.id === stage.id);
            const status = s ? s.status : 'pending';
            const icon = status === 'done' ? '✓' : status === 'active' ? '◉' : '○';
            const duration = s && s.duration ? `${s.duration}s` : '';
            html += `<div class="pm-stage pm-stage-${status}">
                <span class="pm-stage-icon">${stage.icon}</span>
                <span class="pm-stage-label">${stage.label}</span>
                <span class="pm-stage-status">${icon}</span>
                <span class="pm-stage-time">${duration}</span>
            </div>`;
        }
        html += '</div>';

        // Candidates
        if (pd.candidates.length > 0) {
            html += '<div class="pm-section"><div class="pm-section-title">Candidates <button class="pm-expand-btn" id="pm-expand-candidates" title="Open comparison view">Expand</button></div>';
            for (const c of pd.candidates) {
                const score = c.score != null ? c.score.toFixed(2) : '—';
                const pct = c.score != null ? Math.round(c.score * 100) : 0;
                const barClass = pct >= 80 ? 'pm-bar-good' : pct >= 50 ? 'pm-bar-ok' : 'pm-bar-bad';
                html += `<div class="pm-candidate">
                    <span class="pm-cand-id">#${c.id || pd.candidates.indexOf(c) + 1}</span>
                    <span class="pm-cand-temp">T=${(c.temperature || 0).toFixed(1)}</span>
                    <span class="pm-cand-bar ${barClass}" style="--pct:${pct}%"></span>
                    <span class="pm-cand-score">${score}</span>
                </div>`;
            }
            html += '</div>';
        }

        // Validation stats
        const vs = pd.validationStats;
        if (vs) {
            const hitRate = vs.cache_hits != null && (vs.cache_hits + vs.cache_misses) > 0
                ? Math.round(vs.cache_hits / (vs.cache_hits + vs.cache_misses) * 100)
                : null;
            html += '<div class="pm-section"><div class="pm-section-title">Validation</div>';
            if (hitRate != null) html += `<div class="pm-kv"><span>Cache</span><span class="pm-val">${hitRate}% hit</span></div>`;
            if (vs.speedup) html += `<div class="pm-kv"><span>Speedup</span><span class="pm-val">${vs.speedup.toFixed(1)}x</span></div>`;
            if (vs.parallel != null) html += `<div class="pm-kv"><span>Parallel</span><span class="pm-val">${vs.parallel ? 'Yes' : 'No'}</span></div>`;
            html += '</div>';
        }

        // Correction
        if (pd.correctionData) {
            const cd = pd.correctionData;
            html += '<div class="pm-section"><div class="pm-section-title">Self-Correction <button class="pm-expand-btn" id="pm-expand-correction" title="Open correction details">Expand</button></div>';
            if (cd.iterations && cd.iterations.length > 0) {
                html += '<div class="pm-correction-timeline">';
                for (const iter of cd.iterations) {
                    const icon = iter.all_passed ? '✓' : '✗';
                    const cls = iter.all_passed ? 'pm-iter-pass' : 'pm-iter-fail';
                    html += `<span class="pm-iter ${cls}" title="Score: ${(iter.score || 0).toFixed(2)}">${icon}</span>`;
                }
                html += '</div>';
                // Mini score progression
                const scores = cd.iterations.map(it => (it.score || 0).toFixed(2));
                html += `<div class="pm-kv"><span>Scores</span><span class="pm-val">${scores.join(' → ')}</span></div>`;
            }
            if (cd.result) {
                const imp = cd.result.initial_score && cd.result.final_score
                    ? Math.round((cd.result.final_score - cd.result.initial_score) / Math.max(cd.result.initial_score, 0.01) * 100)
                    : null;
                if (imp != null) html += `<div class="pm-kv"><span>Improvement</span><span class="pm-val">${imp > 0 ? '+' : ''}${imp}%</span></div>`;
                html += `<div class="pm-kv"><span>Status</span><span class="pm-val">${cd.result.all_passed ? '✓ Passed' : '✗ Failed'}</span></div>`;
            }
            html += '</div>';
        }

        // Update only the content area (not the toggle)
        const contentEl = panel.querySelector('.pm-content');
        if (contentEl) {
            contentEl.innerHTML = html;
        }

        // Bind expand buttons
        const expandBtn = panel.querySelector('#pm-expand-candidates');
        if (expandBtn) {
            expandBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                candidatePanel.open();
            });
        }
        const corrBtn = panel.querySelector('#pm-expand-correction');
        if (corrBtn) {
            corrBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                correctionTracker.open();
            });
        }
    }
}

export const pipelineMonitor = new PipelineMonitor();
export default pipelineMonitor;
