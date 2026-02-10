/**
 * Approach Cards — Step 3 approach comparison cards for Deep Mode wizard
 */

import { escapeHtml } from '../dom.js';

/**
 * Render approach comparison cards
 * @param {Array<{name, description, pros, cons, complexity, risk}>} approaches
 * @param {number|null} chosenIndex - Index of the chosen approach (from Step 5)
 * @returns {string} HTML
 */
export function renderApproachCards(approaches, chosenIndex = null) {
    if (!approaches || approaches.length === 0) {
        return '<div class="ac-empty">No approaches generated</div>';
    }

    return approaches.map((a, i) => {
        const isChosen = chosenIndex === i;
        const chosenCls = isChosen ? ' ac-card-chosen' : '';
        const riskCls = a.risk === 'high' ? 'ac-risk-high' : a.risk === 'medium' ? 'ac-risk-med' : 'ac-risk-low';
        const complexCls = a.complexity === 'high' ? 'ac-cx-high' : a.complexity === 'medium' ? 'ac-cx-med' : 'ac-cx-low';

        const pros = (a.pros || []).map(p => `<li class="ac-pro">&#10003; ${escapeHtml(p)}</li>`).join('');
        const cons = (a.cons || []).map(c => `<li class="ac-con">&#10007; ${escapeHtml(c)}</li>`).join('');

        return `<div class="ac-card${chosenCls}">
            ${isChosen ? '<span class="ac-chosen-badge">&#9733; Chosen</span>' : ''}
            <div class="ac-card-header">
                <span class="ac-card-num">#${i + 1}</span>
                <span class="ac-card-name">${escapeHtml(a.name)}</span>
            </div>
            <div class="ac-card-desc">${escapeHtml(a.description)}</div>
            <div class="ac-card-tags">
                <span class="ac-tag ${riskCls}">Risk: ${a.risk || '?'}</span>
                <span class="ac-tag ${complexCls}">Complexity: ${a.complexity || '?'}</span>
            </div>
            <div class="ac-card-lists">
                <ul class="ac-pros">${pros}</ul>
                <ul class="ac-cons">${cons}</ul>
            </div>
        </div>`;
    }).join('');
}
