/**
 * Rule Effectiveness Widget — per-rule catch rates
 */

import { barChart } from '../mini-chart.js';

export class RuleEffectiveness {
    constructor() {
        this._data = null;
    }

    async load() {
        try {
            const resp = await fetch('/api/analytics/rules');
            if (!resp.ok) return;
            this._data = await resp.json();
        } catch (e) {
            console.warn('[RuleEffectiveness] fetch error:', e);
        }
    }

    render() {
        if (!this._data || !this._data.rules) {
            return '<div class="db-widget"><div class="db-widget-title">Rule Effectiveness</div><div class="db-empty">No rule data</div></div>';
        }

        const rules = this._data.rules;
        const entries = Object.entries(rules);
        if (entries.length === 0) {
            return '<div class="db-widget"><div class="db-widget-title">Rule Effectiveness</div><div class="db-empty">No rules recorded</div></div>';
        }

        // Sort by fail rate (most problematic first)
        entries.sort((a, b) => b[1].fail_rate - a[1].fail_rate);

        // Bar chart of fail rates
        const barData = entries.map(([name, stats]) => ({
            label: name.replace('static_', '').replace('_validator', '').substring(0, 12),
            value: stats.fail_rate,
            max: 1.0,
            decimals: 0,
            color: stats.fail_rate > 0.3 ? 'rgba(248,81,73,0.5)' : stats.fail_rate > 0.1 ? 'rgba(210,153,34,0.5)' : 'rgba(63,185,80,0.5)',
        }));

        // Detailed table
        let rows = '';
        for (const [name, stats] of entries) {
            const failClass = stats.fail_rate > 0.3 ? 're-high' : stats.fail_rate > 0.1 ? 're-med' : 're-low';
            rows += `<div class="re-row">
                <span class="re-name">${name}</span>
                <span class="re-runs">${stats.times_run}</span>
                <span class="re-passed">${stats.times_passed}</span>
                <span class="re-failed">${stats.times_failed}</span>
                <span class="re-rate ${failClass}">${(stats.fail_rate * 100).toFixed(0)}%</span>
            </div>`;
        }

        return `<div class="db-widget">
            <div class="db-widget-title">Rule Effectiveness</div>
            <div class="re-chart">${barChart(barData, { height: 14 })}</div>
            <div class="re-table">
                <div class="re-header">
                    <span>Rule</span><span>Runs</span><span>Pass</span><span>Fail</span><span>Rate</span>
                </div>
                ${rows}
            </div>
        </div>`;
    }
}
