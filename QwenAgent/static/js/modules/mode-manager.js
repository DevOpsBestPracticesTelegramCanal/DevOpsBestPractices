/**
 * Mode management — auto-detect mode, update indicators
 */

import { dom } from './dom.js';
import { MODE_CONFIG } from './constants.js';
import state from './state.js';

export function updateAutoModeIndicator(mode) {
    const config = MODE_CONFIG[mode] || MODE_CONFIG.fast;
    if (dom.currentModeIcon) dom.currentModeIcon.textContent = config.icon;
    if (dom.currentModeLabel) dom.currentModeLabel.textContent = config.label;
    if (dom.autoModeIndicator) dom.autoModeIndicator.setAttribute('data-mode', mode);

    // Update banner
    if (mode === 'fast') {
        dom.modeBanner.classList.remove('active');
    } else {
        dom.modeBanner.classList.add('active');
        dom.modeBanner.className = `mode-banner active ${mode}`;
        if (mode === 'deep3') {
            dom.modeBannerIcon.textContent = '🔬';
            dom.modeBannerText.textContent = 'Auto: Deep3 Mode — 3-step reasoning';
        } else if (mode === 'deep6') {
            dom.modeBannerIcon.textContent = '🧠';
            dom.modeBannerText.textContent = 'Auto: Deep6 Mode — 6-step Minsky CoT';
        } else if (mode === 'search') {
            dom.modeBannerIcon.textContent = '🌐';
            dom.modeBannerText.textContent = 'Auto: Search Mode — Web search active';
        } else if (mode === 'processing') {
            dom.modeBannerIcon.textContent = '⏳';
            dom.modeBannerText.textContent = 'Processing — Determining optimal approach...';
        }
    }
}

export function detectModeFromQuery(query) {
    const q = query.toLowerCase().trim();

    if (q.startsWith('[deep6]') || q.startsWith('--deep')) return 'deep6';
    if (q.startsWith('[deep3]')) return 'deep3';
    if (q.startsWith('[search]') || q.startsWith('/search')) return 'search';

    const searchKeywords = ['cve', 'latest', 'новости', 'update', 'version', 'release', 'documentation', 'docs'];
    if (searchKeywords.some(kw => q.includes(kw))) return 'search';

    const deepKeywords = ['refactor', 'architect', 'design', 'implement', 'critical', 'bug', 'fix', 'analyze'];
    if (deepKeywords.some(kw => q.includes(kw))) return 'deep3';

    return 'fast';
}
