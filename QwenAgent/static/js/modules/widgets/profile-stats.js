/**
 * Profile Stats Widget — per-profile success rates and performance
 */

import { barChart, donut } from '../mini-chart.js';

export class ProfileStats {
    constructor() {
        this._data = null;
    }

    async load() {
        try {
            const resp = await fetch('/api/analytics/profiles');
            if (!resp.ok) return;
            this._data = await resp.json();
        } catch (e) {
            console.warn('[ProfileStats] fetch error:', e);
        }
    }

    render() {
        if (!this._data || !this._data.profiles) {
            return '<div class="db-widget"><div class="db-widget-title">Profile Performance</div><div class="db-empty">No profile data</div></div>';
        }

        const profiles = this._data.profiles;
        const entries = Object.entries(profiles);
        if (entries.length === 0) {
            return '<div class="db-widget"><div class="db-widget-title">Profile Performance</div><div class="db-empty">No profiles recorded</div></div>';
        }

        // Donut rings for each profile
        let cards = '';
        for (const [name, stats] of entries) {
            const successColor = stats.success_rate >= 0.8 ? '#3fb950' : stats.success_rate >= 0.5 ? '#d29922' : '#f85149';
            const ring = donut(stats.success_rate, { size: 56, color: successColor, label: name });

            cards += `<div class="ps-card">
                ${ring}
                <div class="ps-card-info">
                    <span class="ps-card-name">${name}</span>
                    <span class="ps-card-detail">${stats.count} runs | avg ${stats.avg_score.toFixed(2)} | ${stats.avg_time.toFixed(1)}s</span>
                </div>
            </div>`;
        }

        // Score comparison bar chart
        const barData = entries.map(([name, stats]) => ({
            label: name.substring(0, 8),
            value: stats.avg_score,
            max: 1.0,
            color: stats.success_rate >= 0.8 ? 'rgba(63,185,80,0.5)' : stats.success_rate >= 0.5 ? 'rgba(210,153,34,0.5)' : 'rgba(248,81,73,0.5)',
        }));

        return `<div class="db-widget">
            <div class="db-widget-title">Profile Performance</div>
            <div class="ps-cards">${cards}</div>
            <div class="ps-bars">${barChart(barData)}</div>
        </div>`;
    }
}
