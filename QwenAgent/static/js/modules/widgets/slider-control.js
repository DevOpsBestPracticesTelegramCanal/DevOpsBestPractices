/**
 * Slider Control — reusable range slider with label, value display, and change callback
 */

/**
 * Render a slider control
 * @param {object} opts
 * @param {string} opts.id - Unique id for the input
 * @param {string} opts.label - Display label
 * @param {number} opts.value - Current value
 * @param {number} opts.min - Minimum
 * @param {number} opts.max - Maximum
 * @param {number} opts.step - Step increment
 * @param {string} [opts.unit] - Optional unit suffix (e.g. "ms", "x")
 * @param {string} [opts.description] - Help text
 * @returns {string} HTML
 */
export function renderSlider(opts) {
    const { id, label, value, min, max, step, unit = '', description = '' } = opts;
    const pct = ((value - min) / (max - min)) * 100;

    return `<div class="sc-slider">
        <div class="sc-slider-header">
            <label class="sc-slider-label" for="${id}">${label}</label>
            <span class="sc-slider-value" id="${id}-val">${value}${unit}</span>
        </div>
        ${description ? `<div class="sc-slider-desc">${description}</div>` : ''}
        <input type="range" class="sc-slider-input" id="${id}"
            min="${min}" max="${max}" step="${step}" value="${value}"
            style="--pct: ${pct}%"
        />
        <div class="sc-slider-range">
            <span>${min}${unit}</span>
            <span>${max}${unit}</span>
        </div>
    </div>`;
}

/**
 * Bind live update to a slider: updates value display and calls onChange
 * @param {HTMLElement} container - Parent element to search in
 * @param {string} id - Slider id
 * @param {object} opts - { unit, onChange }
 */
export function bindSlider(container, id, opts = {}) {
    const { unit = '', onChange = null } = opts;
    const input = container.querySelector(`#${id}`);
    const valEl = container.querySelector(`#${id}-val`);
    if (!input) return;

    input.addEventListener('input', () => {
        const v = parseFloat(input.value);
        if (valEl) valEl.textContent = `${v}${unit}`;
        // Update track fill
        const pct = ((v - input.min) / (input.max - input.min)) * 100;
        input.style.setProperty('--pct', `${pct}%`);
        if (onChange) onChange(v);
    });
}
