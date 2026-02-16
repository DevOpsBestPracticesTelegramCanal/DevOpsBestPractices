/**
 * Trinity Panel — Multi-model pipeline status and control overlay
 *
 * Sections:
 * 1. Status — enabled/disabled, strategy, model count
 * 2. Model Cards — 3 models with roles, names, stats
 * 3. Strategy Selector — rotate / role_based / risk_based
 * 4. Statistics — per-model selection counts, pipeline usage
 */

class TrinityPanel {
    constructor() {
        this._visible = false;
        this._status = null;
    }

    async open() {
        this._visible = true;
        const el = document.getElementById('trinity-panel');
        if (!el) return;
        el.classList.remove('hidden');
        await this._loadStatus();
        this._render();
    }

    close() {
        this._visible = false;
        const el = document.getElementById('trinity-panel');
        if (el) el.classList.add('hidden');
    }

    async _loadStatus() {
        try {
            const resp = await fetch('/api/trinity/status');
            if (resp.ok) this._status = await resp.json();
        } catch (e) {
            console.warn('[Trinity] status fetch error:', e);
        }
    }

    async _toggle() {
        try {
            const resp = await fetch('/api/trinity/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({}),
            });
            if (resp.ok) {
                const data = await resp.json();
                this._status = { ...this._status, enabled: data.enabled };
                this._render();
                this._showMsg(data.enabled ? 'Trinity enabled' : 'Trinity disabled');
            }
        } catch (e) {
            this._showMsg('Toggle failed: ' + e.message);
        }
    }

    async _changeStrategy(strategy) {
        try {
            const resp = await fetch('/api/trinity/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ strategy }),
            });
            if (resp.ok) {
                const data = await resp.json();
                if (this._status) this._status.strategy = data.strategy || strategy;
                this._render();
                this._showMsg('Strategy: ' + strategy);
            }
        } catch (e) {
            this._showMsg('Strategy change failed: ' + e.message);
        }
    }

    _showMsg(msg) {
        const el = document.getElementById('tp-msg');
        if (el) {
            el.textContent = msg;
            el.classList.add('tp-msg-visible');
            setTimeout(() => el.classList.remove('tp-msg-visible'), 2000);
        }
    }

    _render() {
        const el = document.getElementById('trinity-panel');
        if (!el) return;

        el.innerHTML = `
        <div class="tp-overlay">
            <div class="tp-panel">
                <div class="tp-header">
                    <span class="tp-title">Trinity Pipeline</span>
                    <div class="tp-actions">
                        <span class="tp-msg" id="tp-msg"></span>
                        <button class="tp-close-btn" id="tp-close-btn" title="Close (Esc)">&times;</button>
                    </div>
                </div>
                <div class="tp-body">
                    ${this._renderStatus()}
                    ${this._renderModels()}
                    ${this._renderStrategy()}
                    ${this._renderStats()}
                </div>
            </div>
        </div>`;

        this._bindEvents(el);
    }

    _renderStatus() {
        if (!this._status) {
            return `<div class="tp-section">
                <div class="tp-section-title">Status</div>
                <div class="tp-empty">Trinity Pipeline not available. Set QWEN_TRINITY_ENABLED=true to activate.</div>
            </div>`;
        }

        const s = this._status;
        const badge = s.enabled
            ? '<span class="tp-badge tp-badge-on">ENABLED</span>'
            : '<span class="tp-badge tp-badge-off">DISABLED</span>';

        return `<div class="tp-section">
            <div class="tp-section-title">Status</div>
            <div class="tp-status-row">
                <div class="tp-status-item">
                    <span class="tp-label">Pipeline</span>
                    ${badge}
                </div>
                <div class="tp-status-item">
                    <span class="tp-label">Models</span>
                    <span class="tp-value">${s.model_count || 0} distinct</span>
                </div>
                <div class="tp-status-item">
                    <span class="tp-label">Strategy</span>
                    <span class="tp-value tp-value-mono">${s.strategy || 'rotate'}</span>
                </div>
                <button class="tp-toggle-btn" id="tp-toggle-btn">
                    ${s.enabled ? 'Disable' : 'Enable'} Trinity
                </button>
            </div>
        </div>`;
    }

    _renderModels() {
        if (!this._status || !this._status.models) {
            return '';
        }

        const models = this._status.models;
        const roleIcons = {
            architect: '\u{1F3D7}',
            developer: '\u{1F4BB}',
            reviewer: '\u{1F50D}',
        };
        const roleDesc = {
            architect: 'CoT reasoning, planning, decomposition',
            developer: 'Code generation, implementation',
            reviewer: 'Code review, bug detection, cross-arch',
        };
        const roleOrder = this._status.role_order || ['developer', 'reviewer', 'architect'];

        let cards = '';
        for (const role of roleOrder) {
            const model = models[role];
            if (!model) continue;
            const icon = roleIcons[role] || '\u{2699}';
            const desc = roleDesc[role] || '';
            const perModel = this._status.stats?.per_model?.[model] || 0;

            cards += `<div class="tp-model-card">
                <div class="tp-model-icon">${icon}</div>
                <div class="tp-model-info">
                    <div class="tp-model-role">${role.charAt(0).toUpperCase() + role.slice(1)}</div>
                    <div class="tp-model-name">${model}</div>
                    <div class="tp-model-desc">${desc}</div>
                </div>
                <div class="tp-model-stat">${perModel} runs</div>
            </div>`;
        }

        return `<div class="tp-section">
            <div class="tp-section-title">Models</div>
            <div class="tp-models">${cards}</div>
        </div>`;
    }

    _renderStrategy() {
        if (!this._status) return '';

        const current = this._status.strategy || 'rotate';
        const strategies = [
            { id: 'rotate', label: 'Rotate', desc: 'Round-robin across all models' },
            { id: 'role_based', label: 'Role-Based', desc: 'Developer first, then reviewer, then architect' },
            { id: 'risk_based', label: 'Risk-Based', desc: 'Simple tasks use developer only, complex use all 3' },
        ];

        let items = '';
        for (const s of strategies) {
            const active = s.id === current ? ' tp-strategy-active' : '';
            items += `<button class="tp-strategy-btn${active}" data-strategy="${s.id}">
                <div class="tp-strategy-label">${s.label}</div>
                <div class="tp-strategy-desc">${s.desc}</div>
            </button>`;
        }

        return `<div class="tp-section">
            <div class="tp-section-title">Strategy</div>
            <div class="tp-strategies">${items}</div>
        </div>`;
    }

    _renderStats() {
        if (!this._status || !this._status.stats) return '';

        const stats = this._status.stats;
        return `<div class="tp-section">
            <div class="tp-section-title">Statistics</div>
            <div class="tp-stats-grid">
                <div class="tp-stat-card">
                    <div class="tp-stat-value">${stats.selections || 0}</div>
                    <div class="tp-stat-label">Total Selections</div>
                </div>
                <div class="tp-stat-card">
                    <div class="tp-stat-value">${stats.full_pipeline_used || 0}</div>
                    <div class="tp-stat-label">Full Pipeline</div>
                </div>
                <div class="tp-stat-card">
                    <div class="tp-stat-value">${stats.developer_only_used || 0}</div>
                    <div class="tp-stat-label">Developer Only</div>
                </div>
                <div class="tp-stat-card">
                    <div class="tp-stat-value">${this._pipelineRate(stats)}%</div>
                    <div class="tp-stat-label">Multi-Model Rate</div>
                </div>
            </div>
        </div>`;
    }

    _pipelineRate(stats) {
        const total = stats.selections || 0;
        if (total === 0) return 0;
        return Math.round((stats.full_pipeline_used / total) * 100);
    }

    _bindEvents(el) {
        // Close
        const closeBtn = el.querySelector('#tp-close-btn');
        if (closeBtn) closeBtn.addEventListener('click', () => this.close());

        // Click overlay to close
        const overlay = el.querySelector('.tp-overlay');
        if (overlay) {
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) this.close();
            });
        }

        // ESC
        const handler = (e) => {
            if (e.key === 'Escape' && this._visible) {
                this.close();
                document.removeEventListener('keydown', handler);
            }
        };
        document.addEventListener('keydown', handler);

        // Toggle
        const toggleBtn = el.querySelector('#tp-toggle-btn');
        if (toggleBtn) toggleBtn.addEventListener('click', () => this._toggle());

        // Strategy buttons
        const strategyBtns = el.querySelectorAll('.tp-strategy-btn');
        strategyBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const strategy = btn.dataset.strategy;
                if (strategy) this._changeStrategy(strategy);
            });
        });
    }
}

export const trinityPanel = new TrinityPanel();
export default trinityPanel;
