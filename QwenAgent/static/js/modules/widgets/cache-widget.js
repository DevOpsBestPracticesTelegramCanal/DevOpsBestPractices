/**
 * Cache Widget — validation cache + solution cache stats
 */

import { donut, statCard } from '../mini-chart.js';

export class CacheWidget {
    constructor() {
        this._data = null;
    }

    async load() {
        try {
            const resp = await fetch('/api/analytics/cache');
            if (!resp.ok) return;
            this._data = await resp.json();
        } catch (e) {
            console.warn('[CacheWidget] fetch error:', e);
        }
    }

    render() {
        if (!this._data) {
            return '<div class="db-widget"><div class="db-widget-title">Cache</div><div class="db-empty">No cache data</div></div>';
        }

        const d = this._data;
        let html = '<div class="db-widget"><div class="db-widget-title">Cache Performance</div>';

        // Validation cache
        const vc = d.validation_cache;
        if (vc) {
            const total = (vc.hits || 0) + (vc.misses || 0);
            const hitRate = total > 0 ? vc.hits / total : 0;
            const ring = donut(hitRate, { size: 52, color: '#58a6ff', label: 'V-Cache' });

            html += `<div class="cw-section">
                <div class="cw-section-title">Validation Cache</div>
                <div class="cw-row">
                    ${ring}
                    <div class="cw-stats">
                        ${statCard('Hits', vc.hits || 0, { icon: '&#9989;' })}
                        ${statCard('Misses', vc.misses || 0, { icon: '&#10060;' })}
                        ${statCard('Size', vc.size || 0, { icon: '&#128230;' })}
                    </div>
                </div>
            </div>`;
        }

        // Solution cache
        const sc = d.solution_cache;
        if (sc) {
            const total = (sc.cache_hits || 0) + (sc.cache_misses || 0);
            const hitRate = total > 0 ? sc.cache_hits / total : 0;
            const ring = donut(hitRate, { size: 52, color: '#d29922', label: 'S-Cache' });

            html += `<div class="cw-section">
                <div class="cw-section-title">Solution Cache</div>
                <div class="cw-row">
                    ${ring}
                    <div class="cw-stats">
                        ${statCard('Solutions', sc.total_solutions || 0, { icon: '&#128209;' })}
                        ${statCard('Hit Rate', (hitRate * 100).toFixed(0) + '%', { icon: '&#127919;' })}
                    </div>
                </div>
            </div>`;
        }

        // Timing stats from outcomes
        const ts = d.timing_stats;
        if (ts && ts.total_outcomes > 0) {
            html += `<div class="cw-section">
                <div class="cw-section-title">Timing (${ts.total_outcomes} runs)</div>
                <div class="cw-timing">
                    ${statCard('Avg Total', ts.avg_total_time.toFixed(1) + 's')}
                    ${statCard('Avg Gen', ts.avg_generation_time.toFixed(1) + 's')}
                    ${statCard('Avg Val', ts.avg_validation_time.toFixed(1) + 's')}
                </div>
            </div>`;
        }

        html += '</div>';
        return html;
    }
}
