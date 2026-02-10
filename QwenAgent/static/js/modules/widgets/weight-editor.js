/**
 * Weight Editor — visual editor for ScoringWeights
 * Each weight shown as a labeled slider with color intensity
 */

/**
 * Render the weight editor
 * @param {Object<string, number>} weights - validator_name → weight
 * @param {object} opts - { bonus, penalty }
 * @returns {string} HTML
 */
export function renderWeightEditor(weights, opts = {}) {
    const { bonus = 0.15, penalty = 0.5 } = opts;
    const entries = Object.entries(weights).sort((a, b) => b[1] - a[1]);
    const maxWeight = Math.max(...entries.map(([, w]) => w), 1);

    let rows = '';
    for (const [name, weight] of entries) {
        const pct = Math.round((weight / maxWeight) * 100);
        const color = weight >= 5 ? 'rgba(248,81,73,0.4)' : weight >= 3 ? 'rgba(210,153,34,0.4)' : 'rgba(63,185,80,0.4)';
        rows += `<div class="we-row">
            <span class="we-name">${name}</span>
            <div class="we-bar-track">
                <div class="we-bar-fill" style="width:${pct}%;background:${color}"></div>
            </div>
            <input type="number" class="we-input" data-rule="${name}"
                value="${weight}" min="0" max="20" step="0.5" />
        </div>`;
    }

    return `<div class="we-editor">
        <div class="we-weights">${rows}</div>
        <div class="we-extras">
            <div class="we-extra-row">
                <span>All-passed bonus</span>
                <input type="number" class="we-input" id="we-bonus" value="${bonus}" min="0" max="1" step="0.05" />
            </div>
            <div class="we-extra-row">
                <span>Critical fail penalty</span>
                <input type="number" class="we-input" id="we-penalty" value="${penalty}" min="0" max="1" step="0.05" />
            </div>
        </div>
    </div>`;
}

/**
 * Collect current weights from the editor DOM
 * @param {HTMLElement} container
 * @returns {{ weights: Object<string, number>, bonus: number, penalty: number }}
 */
export function collectWeights(container) {
    const weights = {};
    container.querySelectorAll('.we-input[data-rule]').forEach(input => {
        weights[input.dataset.rule] = parseFloat(input.value) || 1.0;
    });

    const bonusEl = container.querySelector('#we-bonus');
    const penaltyEl = container.querySelector('#we-penalty');

    return {
        weights,
        bonus: bonusEl ? parseFloat(bonusEl.value) || 0.15 : 0.15,
        penalty: penaltyEl ? parseFloat(penaltyEl.value) || 0.5 : 0.5,
    };
}
