/**
 * Mini Chart — CSS-only chart utilities for dashboard widgets
 * No external deps, generates pure HTML/CSS charts
 */

/**
 * Horizontal bar chart
 * @param {Array<{label: string, value: number, max?: number, color?: string}>} data
 * @param {object} opts - { height: number, showValues: boolean }
 * @returns {string} HTML
 */
export function barChart(data, opts = {}) {
    const { height = 16, showValues = true } = opts;
    const maxVal = Math.max(...data.map(d => d.max || d.value), 0.01);

    return data.map(d => {
        const pct = Math.round((d.value / maxVal) * 100);
        const color = d.color || 'var(--accent-blue, #58a6ff)';
        return `<div class="mc-bar-row">
            <span class="mc-bar-label">${d.label}</span>
            <div class="mc-bar-track" style="height:${height}px">
                <div class="mc-bar-fill" style="width:${pct}%;background:${color}"></div>
            </div>
            ${showValues ? `<span class="mc-bar-val">${typeof d.value === 'number' ? d.value.toFixed(d.decimals ?? 2) : d.value}</span>` : ''}
        </div>`;
    }).join('');
}

/**
 * Sparkline — inline mini chart showing trend
 * @param {number[]} values
 * @param {object} opts - { width, height, color, fillColor }
 * @returns {string} SVG HTML
 */
export function sparkline(values, opts = {}) {
    if (!values || values.length < 2) return '';
    const { width = 120, height = 32, color = '#58a6ff', fillColor = 'rgba(88,166,255,0.1)' } = opts;

    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const step = width / (values.length - 1);

    const points = values.map((v, i) => {
        const x = i * step;
        const y = height - ((v - min) / range) * (height - 4) - 2;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    });

    const linePath = `M${points.join(' L')}`;
    const fillPath = `${linePath} L${width},${height} L0,${height} Z`;

    return `<svg class="mc-sparkline" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
        <path d="${fillPath}" fill="${fillColor}" />
        <path d="${linePath}" fill="none" stroke="${color}" stroke-width="1.5" />
        <circle cx="${(values.length - 1) * step}" cy="${height - ((values[values.length - 1] - min) / range) * (height - 4) - 2}" r="2.5" fill="${color}" />
    </svg>`;
}

/**
 * Donut/ring chart
 * @param {number} value - 0 to 1
 * @param {object} opts - { size, strokeWidth, color, bgColor, label }
 * @returns {string} SVG HTML
 */
export function donut(value, opts = {}) {
    const { size = 64, strokeWidth = 6, color = '#3fb950', bgColor = 'var(--border-color, #30363d)', label = '' } = opts;
    const radius = (size - strokeWidth) / 2;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference * (1 - Math.min(1, Math.max(0, value)));
    const pct = Math.round(value * 100);

    return `<svg class="mc-donut" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <circle cx="${size / 2}" cy="${size / 2}" r="${radius}" fill="none" stroke="${bgColor}" stroke-width="${strokeWidth}" />
        <circle cx="${size / 2}" cy="${size / 2}" r="${radius}" fill="none" stroke="${color}" stroke-width="${strokeWidth}"
            stroke-dasharray="${circumference}" stroke-dashoffset="${offset}"
            stroke-linecap="round" transform="rotate(-90 ${size / 2} ${size / 2})" />
        <text x="${size / 2}" y="${size / 2}" text-anchor="middle" dominant-baseline="central"
            fill="var(--text-primary, #e6edf3)" font-size="${size / 5}px" font-weight="600">${pct}%</text>
        ${label ? `<text x="${size / 2}" y="${size / 2 + size / 5}" text-anchor="middle"
            fill="var(--text-muted, #8b949e)" font-size="${size / 7}px">${label}</text>` : ''}
    </svg>`;
}

/**
 * Stat card
 * @param {string} label
 * @param {string|number} value
 * @param {object} opts - { icon, subtext, trend }
 * @returns {string} HTML
 */
export function statCard(label, value, opts = {}) {
    const { icon = '', subtext = '', trend = null } = opts;
    let trendHtml = '';
    if (trend != null) {
        const cls = trend > 0 ? 'mc-trend-up' : trend < 0 ? 'mc-trend-down' : 'mc-trend-flat';
        const arrow = trend > 0 ? '&#9650;' : trend < 0 ? '&#9660;' : '&#9644;';
        trendHtml = `<span class="mc-trend ${cls}">${arrow} ${Math.abs(trend).toFixed(1)}%</span>`;
    }
    return `<div class="mc-stat-card">
        ${icon ? `<span class="mc-stat-icon">${icon}</span>` : ''}
        <div class="mc-stat-body">
            <span class="mc-stat-value">${value}</span>
            <span class="mc-stat-label">${label}</span>
            ${subtext ? `<span class="mc-stat-sub">${subtext}</span>` : ''}
        </div>
        ${trendHtml}
    </div>`;
}
