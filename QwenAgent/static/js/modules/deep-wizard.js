/**
 * Deep Wizard — 6-step inline wizard for Minsky Deep Mode
 *
 * Listens for deep_step SSE events and renders a visual step-by-step wizard
 * inline in the chat output area, showing:
 * - Step progress indicator (1-6)
 * - Per-step input/output data
 * - Approach comparison cards (Step 3)
 * - Constraint evaluation (Step 4)
 * - Chosen approach highlight (Step 5)
 * - Final solution (Step 6)
 */

import { dom, escapeHtml } from './dom.js';
import state from './state.js';
import eventBus from './event-bus.js';
import { renderApproachCards } from './widgets/approach-cards.js';

const STEPS = [
    { num: 1, name: 'understanding', label: 'Understanding',  icon: '1' },
    { num: 2, name: 'challenges',    label: 'Challenges',     icon: '2' },
    { num: 3, name: 'approaches',    label: 'Approaches',     icon: '3' },
    { num: 4, name: 'constraints',   label: 'Constraints',    icon: '4' },
    { num: 5, name: 'choose',        label: 'Choose',         icon: '5' },
    { num: 6, name: 'solution',      label: 'Solution',       icon: '6' },
];

class DeepWizard {
    constructor() {
        this._active = false;
        this._steps = {};    // name → { status, data }
        this._el = null;
    }

    init() {
        this._listenSSE();
    }

    _listenSSE() {
        eventBus.on('sse:deep_step', (event) => {
            const { step, name, status, data } = event;
            if (!name) return;

            if (!this._active) {
                this._active = true;
                this._steps = {};
                this._createContainer();
            }

            // Update step state
            if (!this._steps[name]) {
                this._steps[name] = { status: 'pending', data: {} };
            }
            this._steps[name].status = status;
            if (data && status === 'complete') {
                this._steps[name].data = data;
            }
            if (data && data.description && status === 'starting') {
                this._steps[name].description = data.description;
            }

            this._render();
        });

        // Reset on done
        eventBus.on('sse:done', () => {
            // Keep visible but mark inactive
            setTimeout(() => {
                this._active = false;
            }, 500);
        });
    }

    _createContainer() {
        if (this._el) return;

        const output = dom.output;
        if (!output) return;

        this._el = document.createElement('div');
        this._el.className = 'dw-wizard';
        this._el.id = 'deep-wizard-' + Date.now();
        output.appendChild(this._el);

        // Scroll into view
        this._el.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }

    _render() {
        if (!this._el) return;

        let html = '<div class="dw-header">Deep Mode &mdash; 6-Step Minsky Pipeline</div>';

        // Step progress bar
        html += '<div class="dw-progress">';
        for (const step of STEPS) {
            const s = this._steps[step.name];
            const status = s ? s.status : 'pending';
            const cls = status === 'complete' ? 'dw-step-done'
                      : status === 'starting' ? 'dw-step-active'
                      : 'dw-step-pending';
            const icon = status === 'complete' ? '&#10003;'
                       : status === 'starting' ? '&#9675;'
                       : step.icon;

            const connector = step.num < 6 ? '<span class="dw-connector"></span>' : '';

            html += `<div class="dw-step ${cls}" title="${step.label}">
                <span class="dw-step-icon">${icon}</span>
                <span class="dw-step-label">${step.label}</span>
            </div>${connector}`;
        }
        html += '</div>';

        // Step details (only for completed steps)
        html += '<div class="dw-details">';
        for (const step of STEPS) {
            const s = this._steps[step.name];
            if (!s) continue;

            const isActive = s.status === 'starting';
            const isDone = s.status === 'complete';
            const cls = isDone ? 'dw-detail-done' : isActive ? 'dw-detail-active' : '';

            html += `<div class="dw-detail ${cls}">`;
            html += `<div class="dw-detail-title">Step ${step.num}: ${step.label}</div>`;

            if (isActive) {
                html += `<div class="dw-detail-loading">${s.description || 'Processing...'}</div>`;
            } else if (isDone) {
                html += this._renderStepData(step.name, s.data);
            }

            html += '</div>';
        }
        html += '</div>';

        this._el.innerHTML = html;

        // Scroll to latest step
        const activeStep = this._el.querySelector('.dw-detail-active, .dw-detail-done:last-child');
        if (activeStep) {
            activeStep.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }

    _renderStepData(name, data) {
        if (!data || Object.keys(data).length === 0) return '<div class="dw-empty">No data</div>';

        switch (name) {
            case 'understanding':
                return this._renderUnderstanding(data);
            case 'challenges':
                return this._renderChallenges(data);
            case 'approaches':
                return this._renderApproaches(data);
            case 'constraints':
                return this._renderConstraints(data);
            case 'choose':
                return this._renderChoose(data);
            case 'solution':
                return this._renderSolution(data);
            default:
                return `<pre class="dw-raw">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
        }
    }

    _renderUnderstanding(data) {
        const tt = data.task_type;
        const typeName = tt && typeof tt === 'object' ? (tt.value || tt) : (tt || '?');
        return `<div class="dw-kv-grid">
            <div class="dw-kv"><span>Task Type</span><span class="dw-val">${escapeHtml(String(typeName))}</span></div>
            ${data.current_state ? `<div class="dw-kv"><span>Current State</span><span class="dw-val">${escapeHtml(data.current_state)}</span></div>` : ''}
            ${data.target_state ? `<div class="dw-kv"><span>Target State</span><span class="dw-val">${escapeHtml(data.target_state)}</span></div>` : ''}
        </div>`;
    }

    _renderChallenges(data) {
        const challenges = data.challenges || [];
        if (challenges.length === 0) return '<div class="dw-empty">No challenges identified</div>';

        return `<div class="dw-challenge-list">
            ${challenges.map(c => {
                const sevCls = c.severity === 'high' ? 'dw-sev-high' : c.severity === 'medium' ? 'dw-sev-med' : 'dw-sev-low';
                return `<div class="dw-challenge">
                    <span class="dw-challenge-sev ${sevCls}">${c.severity || '?'}</span>
                    <span class="dw-challenge-type">${escapeHtml(c.type || '')}</span>
                    <span class="dw-challenge-desc">${escapeHtml(c.desc || '')}</span>
                </div>`;
            }).join('')}
        </div>`;
    }

    _renderApproaches(data) {
        const approaches = data.approaches || [];
        // Check if we have a chosen index from step 5
        const chooseStep = this._steps['choose'];
        const chosenIdx = chooseStep && chooseStep.status === 'complete'
            ? chooseStep.data.chosen_index : null;
        return `<div class="dw-approaches">${renderApproachCards(approaches, chosenIdx)}</div>`;
    }

    _renderConstraints(data) {
        const evaluated = data.evaluated || [];
        if (evaluated.length === 0) return '<div class="dw-empty">No constraints evaluated</div>';

        return `<div class="dw-constraint-list">
            ${evaluated.map(e => {
                const fPct = Math.round(e.feasibility * 100);
                const cls = e.constraints_met ? 'dw-feasible' : 'dw-infeasible';
                return `<div class="dw-constraint ${cls}">
                    <span class="dw-constraint-name">${escapeHtml(e.name)}</span>
                    <div class="dw-constraint-bar">
                        <div class="dw-constraint-fill" style="width:${fPct}%"></div>
                    </div>
                    <span class="dw-constraint-pct">${fPct}%</span>
                </div>`;
            }).join('')}
        </div>`;
    }

    _renderChoose(data) {
        const rejected = data.rejected || [];
        return `<div class="dw-choose">
            <div class="dw-chosen">
                <span class="dw-chosen-icon">&#9733;</span>
                <span class="dw-chosen-name">${escapeHtml(data.chosen_name || '?')}</span>
                <span class="dw-chosen-score">${data.score != null ? (data.score * 100).toFixed(0) + '%' : ''}</span>
            </div>
            ${data.reason ? `<div class="dw-chosen-reason">${escapeHtml(data.reason)}</div>` : ''}
            ${rejected.length > 0 ? `<div class="dw-rejected">Rejected: ${rejected.map(r => escapeHtml(r)).join(', ')}</div>` : ''}
        </div>`;
    }

    _renderSolution(data) {
        return `<div class="dw-solution">
            ${data.approach_used ? `<div class="dw-kv"><span>Approach</span><span class="dw-val">${escapeHtml(data.approach_used)}</span></div>` : ''}
            ${data.verified != null ? `<div class="dw-kv"><span>Verified</span><span class="dw-val">${data.verified ? '&#10003; Yes' : '&#10007; No'}</span></div>` : ''}
        </div>`;
    }
}

export const deepWizard = new DeepWizard();
export default deepWizard;
