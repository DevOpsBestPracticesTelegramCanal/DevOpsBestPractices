/**
 * Settings Panel — Interactive pipeline configuration overlay
 *
 * Sections:
 * 1. Pipeline Config (n_candidates, workers, cache, fail_fast)
 * 2. Scoring Weights (per-rule weight editor)
 * 3. Validation Profiles (view/select profile)
 */

import { renderSlider, bindSlider } from './widgets/slider-control.js';
import { renderWeightEditor, collectWeights } from './widgets/weight-editor.js';

class SettingsPanel {
    constructor() {
        this._visible = false;
        this._config = null;
        this._weights = null;
        this._profiles = null;
        this._dirty = false;
    }

    async open() {
        this._visible = true;
        const el = document.getElementById('settings-panel');
        if (!el) return;
        el.classList.remove('hidden');

        // Load all data in parallel
        await Promise.all([
            this._loadConfig(),
            this._loadWeights(),
            this._loadProfiles(),
        ]);

        this._dirty = false;
        this._render();
    }

    close() {
        this._visible = false;
        const el = document.getElementById('settings-panel');
        if (el) el.classList.add('hidden');
    }

    async _loadConfig() {
        try {
            const resp = await fetch('/api/pipeline/config');
            if (resp.ok) this._config = await resp.json();
        } catch (e) {
            console.warn('[Settings] config fetch error:', e);
        }
    }

    async _loadWeights() {
        try {
            const resp = await fetch('/api/pipeline/weights');
            if (resp.ok) this._weights = await resp.json();
        } catch (e) {
            console.warn('[Settings] weights fetch error:', e);
        }
    }

    async _loadProfiles() {
        try {
            const resp = await fetch('/api/pipeline/profiles');
            if (resp.ok) this._profiles = await resp.json();
        } catch (e) {
            console.warn('[Settings] profiles fetch error:', e);
        }
    }

    async _saveConfig() {
        if (!this._config) return;
        const el = document.getElementById('settings-panel');
        if (!el) return;

        // Collect slider values
        const data = {};
        const fields = ['n_candidates', 'max_validation_workers', 'max_validation_cache_size'];
        for (const f of fields) {
            const input = el.querySelector(`#sp-${f}`);
            if (input) data[f] = parseInt(input.value, 10);
        }

        // Collect toggles
        const toggles = ['parallel_candidate_validation', 'validation_cache_enabled', 'fail_fast'];
        for (const t of toggles) {
            const input = el.querySelector(`#sp-${t}`);
            if (input) data[t] = input.checked;
        }

        try {
            const resp = await fetch('/api/pipeline/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            if (resp.ok) {
                this._showStatus('Config saved');
                this._dirty = false;
            }
        } catch (e) {
            this._showStatus('Save failed: ' + e.message);
        }
    }

    async _saveWeights() {
        const el = document.getElementById('settings-panel');
        if (!el) return;

        const weightsSection = el.querySelector('.sp-weights-section');
        if (!weightsSection) return;

        const collected = collectWeights(weightsSection);

        try {
            const resp = await fetch('/api/pipeline/weights', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(collected),
            });
            if (resp.ok) {
                this._showStatus('Weights saved');
            }
        } catch (e) {
            this._showStatus('Save failed: ' + e.message);
        }
    }

    _showStatus(msg) {
        const el = document.getElementById('sp-status');
        if (el) {
            el.textContent = msg;
            el.classList.add('sp-status-visible');
            setTimeout(() => el.classList.remove('sp-status-visible'), 2000);
        }
    }

    _render() {
        const el = document.getElementById('settings-panel');
        if (!el) return;

        el.innerHTML = `
        <div class="sp-overlay">
            <div class="sp-panel">
                <div class="sp-header">
                    <span class="sp-title">Settings</span>
                    <div class="sp-actions">
                        <span class="sp-status" id="sp-status"></span>
                        <button class="sp-save-btn" id="sp-save-all" title="Save all changes">Save</button>
                        <button class="sp-close-btn" id="sp-close-btn" title="Close (Esc)">&times;</button>
                    </div>
                </div>
                <div class="sp-body">
                    ${this._renderConfig()}
                    ${this._renderWeights()}
                    ${this._renderProfiles()}
                </div>
            </div>
        </div>`;

        this._bindEvents(el);
    }

    _renderConfig() {
        if (!this._config) {
            return '<div class="sp-section"><div class="sp-section-title">Pipeline Configuration</div><div class="sp-empty">Pipeline not available</div></div>';
        }

        const c = this._config;

        return `<div class="sp-section">
            <div class="sp-section-title">Pipeline Configuration</div>
            <div class="sp-sliders">
                ${renderSlider({
                    id: 'sp-n_candidates',
                    label: 'Candidates',
                    value: c.n_candidates || 2,
                    min: 1, max: 5, step: 1,
                    description: 'Number of code candidates to generate per request',
                })}
                ${renderSlider({
                    id: 'sp-max_validation_workers',
                    label: 'Validation Workers',
                    value: c.max_validation_workers || 4,
                    min: 1, max: 8, step: 1,
                    description: 'Max parallel threads for candidate validation',
                })}
                ${renderSlider({
                    id: 'sp-max_validation_cache_size',
                    label: 'Cache Size',
                    value: c.max_validation_cache_size || 256,
                    min: 32, max: 1024, step: 32,
                    description: 'Max entries in the validation result LRU cache',
                })}
            </div>
            <div class="sp-toggles">
                <label class="sp-toggle">
                    <input type="checkbox" id="sp-parallel_candidate_validation" ${c.parallel_candidate_validation ? 'checked' : ''} />
                    <span>Parallel Validation</span>
                </label>
                <label class="sp-toggle">
                    <input type="checkbox" id="sp-validation_cache_enabled" ${c.validation_cache_enabled ? 'checked' : ''} />
                    <span>Validation Cache</span>
                </label>
                <label class="sp-toggle">
                    <input type="checkbox" id="sp-fail_fast" ${c.fail_fast ? 'checked' : ''} />
                    <span>Fail Fast</span>
                </label>
            </div>
        </div>`;
    }

    _renderWeights() {
        if (!this._weights || !this._weights.weights) {
            return '<div class="sp-section sp-weights-section"><div class="sp-section-title">Scoring Weights</div><div class="sp-empty">Weights not available</div></div>';
        }

        const w = this._weights;
        return `<div class="sp-section sp-weights-section">
            <div class="sp-section-title">Scoring Weights
                <button class="sp-save-section-btn" id="sp-save-weights">Save Weights</button>
            </div>
            ${renderWeightEditor(w.weights, { bonus: w.all_passed_bonus, penalty: w.critical_error_penalty })}
        </div>`;
    }

    _renderProfiles() {
        if (!this._profiles || !this._profiles.profiles) {
            return '<div class="sp-section"><div class="sp-section-title">Validation Profiles</div><div class="sp-empty">Profiles not available</div></div>';
        }

        const profiles = this._profiles.profiles;
        let cards = '';

        for (const p of profiles) {
            const ruleCount = p.rule_names ? p.rule_names.length : 0;
            const flags = [];
            if (p.fail_fast) flags.push('fail-fast');
            if (p.parallel === false) flags.push('sequential');
            else flags.push('parallel');

            cards += `<div class="sp-profile-card">
                <div class="sp-profile-name">${p.name}</div>
                <div class="sp-profile-rules">${ruleCount} rules</div>
                <div class="sp-profile-flags">${flags.join(' | ')}</div>
                ${p.rule_names ? `<div class="sp-profile-rulelist">${p.rule_names.join(', ')}</div>` : ''}
            </div>`;
        }

        return `<div class="sp-section">
            <div class="sp-section-title">Validation Profiles</div>
            <div class="sp-profiles">${cards}</div>
        </div>`;
    }

    _bindEvents(el) {
        // Close
        const closeBtn = el.querySelector('#sp-close-btn');
        if (closeBtn) closeBtn.addEventListener('click', () => this.close());

        // ESC
        el.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') this.close();
        });

        // Save all (config)
        const saveAll = el.querySelector('#sp-save-all');
        if (saveAll) saveAll.addEventListener('click', () => this._saveConfig());

        // Save weights
        const saveWeights = el.querySelector('#sp-save-weights');
        if (saveWeights) saveWeights.addEventListener('click', (e) => {
            e.stopPropagation();
            this._saveWeights();
        });

        // Bind sliders
        bindSlider(el, 'sp-n_candidates', { onChange: () => this._dirty = true });
        bindSlider(el, 'sp-max_validation_workers', { onChange: () => this._dirty = true });
        bindSlider(el, 'sp-max_validation_cache_size', { onChange: () => this._dirty = true });
    }
}

export const settingsPanel = new SettingsPanel();
export default settingsPanel;
