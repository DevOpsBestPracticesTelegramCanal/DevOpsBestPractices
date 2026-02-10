/**
 * Outcome Timeline Widget — shows recent pipeline runs
 */

import { sparkline } from '../mini-chart.js';

export class OutcomeTimeline {
    constructor() {
        this._data = null;
    }

    async load() {
        try {
            const resp = await fetch('/api/analytics/outcomes');
            if (!resp.ok) return;
            this._data = await resp.json();
        } catch (e) {
            console.warn('[OutcomeTimeline] fetch error:', e);
        }
    }

    render() {
        if (!this._data || !this._data.outcomes) {
            return '<div class="db-widget"><div class="db-widget-title">Outcome Timeline</div><div class="db-empty">No outcome data yet</div></div>';
        }

        const outcomes = this._data.outcomes;
        if (outcomes.length === 0) {
            return '<div class="db-widget"><div class="db-widget-title">Outcome Timeline</div><div class="db-empty">No pipeline runs recorded</div></div>';
        }

        // Score sparkline
        const scores = outcomes.slice().reverse().map(o => o.best_score);
        const spark = sparkline(scores, { width: 200, height: 36, color: '#58a6ff' });

        // Recent runs table (last 10)
        const recent = outcomes.slice(0, 10);
        let rows = '';
        for (const o of recent) {
            const date = new Date(o.timestamp * 1000);
            const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            const dateStr = date.toLocaleDateString([], { month: 'short', day: 'numeric' });
            const scoreClass = o.all_passed ? 'ot-score-pass' : o.best_score >= 0.5 ? 'ot-score-ok' : 'ot-score-fail';
            const passIcon = o.all_passed ? '&#10003;' : '&#10007;';

            rows += `<div class="ot-row">
                <span class="ot-time">${dateStr} ${timeStr}</span>
                <span class="ot-type">${o.task_type}</span>
                <span class="ot-profile">${o.validation_profile}</span>
                <span class="ot-score ${scoreClass}">${o.best_score.toFixed(2)} ${passIcon}</span>
                <span class="ot-time-val">${o.total_time.toFixed(1)}s</span>
            </div>`;
        }

        return `<div class="db-widget db-widget-wide">
            <div class="db-widget-title">Outcome Timeline <span class="db-widget-count">${outcomes.length} runs</span></div>
            <div class="ot-spark">${spark}</div>
            <div class="ot-table">
                <div class="ot-header">
                    <span>Time</span><span>Type</span><span>Profile</span><span>Score</span><span>Duration</span>
                </div>
                ${rows}
            </div>
        </div>`;
    }
}
