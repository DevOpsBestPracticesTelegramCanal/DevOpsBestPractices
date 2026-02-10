/**
 * Dashboard — Full analytics overlay
 * Orchestrates all widget modules, handles open/close, refresh
 */

import { OutcomeTimeline } from './widgets/outcome-timeline.js';
import { ProfileStats } from './widgets/profile-stats.js';
import { CacheWidget } from './widgets/cache-widget.js';
import { RuleEffectiveness } from './widgets/rule-effectiveness.js';
import { MetricsWidget } from './widgets/metrics-widget.js';

class Dashboard {
    constructor() {
        this._visible = false;
        this._loading = false;
        this._widgets = {
            outcomes: new OutcomeTimeline(),
            profiles: new ProfileStats(),
            cache: new CacheWidget(),
            rules: new RuleEffectiveness(),
            metrics: new MetricsWidget(),
        };
    }

    async open() {
        this._visible = true;
        const el = document.getElementById('dashboard');
        if (!el) return;
        el.classList.remove('hidden');

        // Show loading state
        this._loading = true;
        this._renderShell();

        // Load all widgets in parallel
        await Promise.all(
            Object.values(this._widgets).map(w => w.load())
        );

        this._loading = false;
        this._render();
    }

    close() {
        this._visible = false;
        const el = document.getElementById('dashboard');
        if (el) el.classList.add('hidden');
    }

    async refresh() {
        if (!this._visible) return;
        this._loading = true;
        this._renderShell();

        await Promise.all(
            Object.values(this._widgets).map(w => w.load())
        );

        this._loading = false;
        this._render();
    }

    _renderShell() {
        const el = document.getElementById('dashboard');
        if (!el) return;

        el.innerHTML = `
        <div class="db-overlay">
            <div class="db-panel">
                <div class="db-header">
                    <span class="db-title">Dashboard</span>
                    <div class="db-actions">
                        <button class="db-refresh-btn" id="db-refresh-btn" title="Refresh data">&#8635;</button>
                        <button class="db-close-btn" id="db-close-btn" title="Close (Esc)">&times;</button>
                    </div>
                </div>
                <div class="db-body" id="db-body">
                    ${this._loading ? '<div class="db-loading">Loading analytics...</div>' : ''}
                </div>
            </div>
        </div>`;

        this._bindButtons(el);
    }

    _render() {
        const body = document.getElementById('db-body');
        if (!body) {
            this._renderShell();
            const newBody = document.getElementById('db-body');
            if (!newBody) return;
            this._fillBody(newBody);
            return;
        }
        this._fillBody(body);
    }

    _fillBody(body) {
        const w = this._widgets;
        body.innerHTML = `
            <div class="db-grid">
                ${w.metrics.render()}
                ${w.outcomes.render()}
                ${w.profiles.render()}
                ${w.rules.render()}
                ${w.cache.render()}
            </div>
        `;
    }

    _bindButtons(el) {
        const closeBtn = el.querySelector('#db-close-btn');
        if (closeBtn) closeBtn.addEventListener('click', () => this.close());

        const refreshBtn = el.querySelector('#db-refresh-btn');
        if (refreshBtn) refreshBtn.addEventListener('click', () => this.refresh());

        // ESC key
        el.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') this.close();
        });
    }
}

export const dashboard = new Dashboard();
export default dashboard;
