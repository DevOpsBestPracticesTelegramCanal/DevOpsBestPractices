/**
 * ValidationForm — Manual code validation overlay
 *
 * Lets users paste code, pick a validation profile, and see
 * rule-by-rule results from the backend RuleRunner.
 */

import { escapeHtml } from './dom.js';

class ValidationForm {
    constructor() {
        this._visible = false;
        this._profiles = null;
    }

    async open() {
        this._visible = true;
        const el = document.getElementById('validation-form');
        if (!el) return;
        el.classList.remove('hidden');

        if (!this._profiles) {
            await this._loadProfiles();
        }

        this._render();
    }

    close() {
        this._visible = false;
        const el = document.getElementById('validation-form');
        if (el) el.classList.add('hidden');
    }

    async _loadProfiles() {
        try {
            const resp = await fetch('/api/pipeline/profiles');
            if (resp.ok) {
                const data = await resp.json();
                this._profiles = data.profiles || [];
            }
        } catch (e) {
            console.warn('[ValidationForm] profiles fetch error:', e);
        }
    }

    _render() {
        const el = document.getElementById('validation-form');
        if (!el) return;

        const profileOptions = (this._profiles || [])
            .map(p => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)} (${p.rule_names.length} rules)</option>`)
            .join('');

        // Fallback if no profiles loaded
        const selectHtml = profileOptions
            ? profileOptions
            : '<option value="balanced">balanced</option>';

        el.innerHTML = `
            <div class="vf-overlay" id="vf-overlay">
                <div class="vf-panel">
                    <div class="vf-header">
                        <span class="vf-title">Manual Code Validation</span>
                        <button class="vf-close-btn" id="vf-close-btn">&times;</button>
                    </div>
                    <div class="vf-body">
                        <div>
                            <label class="vf-label">Code</label>
                            <textarea class="vf-code-input" id="vf-code"
                                placeholder="Paste Python code here..."
                                spellcheck="false"></textarea>
                        </div>
                        <div class="vf-controls">
                            <select class="vf-profile-select" id="vf-profile">
                                ${selectHtml}
                            </select>
                            <button class="vf-run-btn" id="vf-run-btn">Run Validation</button>
                        </div>
                        <div id="vf-results"></div>
                    </div>
                </div>
            </div>
        `;

        // Select balanced by default if available
        const selectEl = el.querySelector('#vf-profile');
        if (selectEl) {
            for (const opt of selectEl.options) {
                if (opt.value.toLowerCase() === 'balanced') {
                    opt.selected = true;
                    break;
                }
            }
        }

        // Bind events
        el.querySelector('#vf-close-btn').addEventListener('click', () => this.close());
        el.querySelector('#vf-overlay').addEventListener('click', (e) => {
            if (e.target.id === 'vf-overlay') this.close();
        });
        el.querySelector('#vf-run-btn').addEventListener('click', () => this._runValidation());

        // Escape to close
        this._escHandler = (e) => {
            if (e.key === 'Escape' && this._visible) this.close();
        };
        document.addEventListener('keydown', this._escHandler);
    }

    async _runValidation() {
        const codeEl = document.getElementById('vf-code');
        const profileEl = document.getElementById('vf-profile');
        const runBtn = document.getElementById('vf-run-btn');
        const resultsEl = document.getElementById('vf-results');

        if (!codeEl || !resultsEl) return;

        const code = codeEl.value.trim();
        if (!code) {
            resultsEl.innerHTML = '<div class="vf-empty">Paste some code first.</div>';
            return;
        }

        const profile = profileEl ? profileEl.value : 'balanced';

        runBtn.disabled = true;
        runBtn.textContent = 'Running...';
        resultsEl.innerHTML = '<div class="vf-empty">Validating...</div>';

        try {
            const resp = await fetch('/api/validate/code', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code, profile }),
            });
            const data = await resp.json();

            if (data.error && (!data.results || data.results.length === 0)) {
                resultsEl.innerHTML = `<div class="vf-empty">Error: ${escapeHtml(data.error)}</div>`;
            } else {
                this._renderResults(data, resultsEl);
            }
        } catch (e) {
            resultsEl.innerHTML = `<div class="vf-empty">Request failed: ${escapeHtml(e.message)}</div>`;
        } finally {
            runBtn.disabled = false;
            runBtn.textContent = 'Run Validation';
        }
    }

    _renderResults(data, container) {
        const score = data.score || 0;
        const scoreClass = data.failed === 0 ? 'pass' : (score >= 0.5 ? 'mixed' : 'fail');
        const pct = (score * 100).toFixed(1);

        let html = `
            <div class="vf-summary">
                <span class="vf-summary-score ${scoreClass}">${pct}%</span>
                <span class="vf-summary-stat">Profile: <b>${escapeHtml(data.profile)}</b></span>
                <span class="vf-summary-stat">Rules: <b>${data.rules_count}</b></span>
                <span class="vf-summary-stat" style="color: var(--accent-green)">Passed: <b>${data.passed}</b></span>
                <span class="vf-summary-stat" style="color: var(--accent-red)">Failed: <b>${data.failed}</b></span>
            </div>
            <div class="vf-results">
        `;

        for (const r of (data.results || [])) {
            const cls = r.passed ? 'pass' : 'fail';
            const icon = r.passed ? '&#10003;' : '&#10007;';
            const scorePct = (r.score * 100).toFixed(0);

            let messagesHtml = '';
            if (r.messages && r.messages.length > 0) {
                const items = r.messages.map(m => `<li>${escapeHtml(m)}</li>`).join('');
                messagesHtml = `<ul class="vf-rule-messages">${items}</ul>`;
            }

            html += `
                <div class="vf-rule-card ${cls}">
                    <span class="vf-rule-icon ${cls}">${icon}</span>
                    <div class="vf-rule-body">
                        <div class="vf-rule-name">${escapeHtml(r.rule_name)}</div>
                        <div class="vf-rule-meta">${escapeHtml(r.severity)} &middot; ${r.duration}ms</div>
                        ${messagesHtml}
                    </div>
                    <span class="vf-score-badge ${cls}">${scorePct}%</span>
                </div>
            `;
        }

        html += '</div>';
        container.innerHTML = html;
    }
}

export const validationForm = new ValidationForm();
