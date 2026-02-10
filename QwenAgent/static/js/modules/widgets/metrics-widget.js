/**
 * Metrics Widget — Prometheus counters/histograms + agent stats
 */

import { statCard } from '../mini-chart.js';

export class MetricsWidget {
    constructor() {
        this._data = null;
    }

    async load() {
        try {
            const resp = await fetch('/api/analytics/metrics');
            if (!resp.ok) return;
            this._data = await resp.json();
        } catch (e) {
            console.warn('[MetricsWidget] fetch error:', e);
        }
    }

    render() {
        if (!this._data) {
            return '<div class="db-widget"><div class="db-widget-title">Metrics</div><div class="db-empty">No metrics data</div></div>';
        }

        const d = this._data;
        let html = '<div class="db-widget db-widget-wide"><div class="db-widget-title">System Metrics</div>';

        // Agent stats (primary)
        const as = d.agent_stats;
        if (as) {
            html += '<div class="mw-grid">';
            html += statCard('Requests', as.total_requests || 0, { icon: '&#128172;' });
            html += statCard('Pipeline Runs', as.multi_candidate_runs || 0, { icon: '&#9881;' });
            html += statCard('Corrections', as.correction_runs || 0, { icon: '&#128260;' });
            html += statCard('All Passed', as.outcomes_all_passed || 0, { icon: '&#10003;' });
            html += statCard('No-LLM', as.no_llm_responses || 0, { icon: '&#9889;' });
            html += statCard('Outcomes', as.outcomes_recorded || 0, { icon: '&#128202;' });
            html += '</div>';
        }

        // Prometheus metrics
        const pm = d.prometheus;
        if (pm) {
            // Counters
            const counters = pm.counters || {};
            const counterEntries = Object.entries(counters);
            if (counterEntries.length > 0) {
                html += '<div class="mw-section"><div class="mw-section-title">Counters</div><div class="mw-grid">';
                for (const [name, samples] of counterEntries) {
                    const total = Array.isArray(samples) ? samples.reduce((s, x) => s + (x.value || 0), 0) : 0;
                    html += statCard(name.replace(/_/g, ' '), total.toFixed(0));
                }
                html += '</div></div>';
            }

            // Histograms
            const histograms = pm.histograms || {};
            const histEntries = Object.entries(histograms);
            if (histEntries.length > 0) {
                html += '<div class="mw-section"><div class="mw-section-title">Histograms</div>';
                for (const [name, hist] of histEntries) {
                    html += `<div class="mw-hist">
                        <span class="mw-hist-name">${name.replace(/_/g, ' ')}</span>
                        <span class="mw-hist-vals">count: ${hist.count || 0} | avg: ${(hist.avg || 0).toFixed(3)} | sum: ${(hist.sum || 0).toFixed(1)}</span>
                    </div>`;
                }
                html += '</div>';
            }
        }

        // Summary stats
        const ss = d.summary;
        if (ss) {
            html += `<div class="mw-section"><div class="mw-section-title">Summary</div>
                <div class="mw-grid">
                    ${statCard('Avg Score', (ss.overall_avg_score || 0).toFixed(2), { icon: '&#127942;' })}
                    ${statCard('Success Rate', ((ss.overall_success_rate || 0) * 100).toFixed(0) + '%', { icon: '&#128175;' })}
                    ${statCard('Total Outcomes', ss.total_outcomes || 0, { icon: '&#128200;' })}
                </div>
            </div>`;
        }

        html += '</div>';
        return html;
    }
}
