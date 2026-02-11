/**
 * timeout-menu.js — Timeout dropdown menu in header
 *
 * Shows current preset + max_wait in the header button.
 * Dropdown allows switching presets, adjusting max_wait,
 * and previewing computed TTFT/Idle/AbsMax values.
 */

const PRESETS = {
    speed:    { label: 'Speed',    icon: '\u26A1', ttft: 10, idle: 8,  maxCap: 60  },
    balanced: { label: 'Balanced', icon: '\u2696\uFE0F', ttft: 45, idle: 25, maxCap: 300 },
    quality:  { label: 'Quality',  icon: '\uD83D\uDC8E', ttft: 45, idle: 30, maxCap: 600 }
};

class TimeoutMenu {
    constructor() {
        this._el = null;
        this._dropdown = null;
        this._labelEl = null;
        this._state = { priority: 'balanced', max_wait: 120 };
    }

    init() {
        this._el = document.getElementById('timeout-selector');
        this._dropdown = document.getElementById('timeout-dropdown');
        this._labelEl = document.getElementById('timeout-label');
        const btn = document.getElementById('timeout-btn');

        if (!btn || !this._el || !this._dropdown) return;

        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (this._el.classList.contains('open')) {
                this.close();
            } else {
                this.open();
            }
        });

        document.addEventListener('click', (e) => {
            if (this._el && !this._el.contains(e.target)) {
                this.close();
            }
        });

        // Load initial label from server
        this._loadInitial();
    }

    async _loadInitial() {
        try {
            const res = await fetch('/api/timeout');
            if (res.ok) {
                const data = await res.json();
                if (data.success !== false) {
                    this._state.priority = data.priority || 'balanced';
                    this._state.max_wait = data.max_wait || 120;
                    this._updateLabel();
                }
            }
        } catch (_) {
            // Server not available yet; keep defaults
        }
    }

    async open() {
        try {
            const res = await fetch('/api/timeout');
            if (res.ok) {
                const data = await res.json();
                if (data.success !== false) {
                    this._state.priority = data.priority || 'balanced';
                    this._state.max_wait = data.max_wait || 120;
                }
            }
        } catch (_) { /* use cached state */ }

        this._render();
        this._el.classList.add('open');
    }

    close() {
        if (this._el) this._el.classList.remove('open');
    }

    _render() {
        const { priority, max_wait } = this._state;
        const computed = this._computeValues(priority, max_wait);

        this._dropdown.innerHTML = `
            <div class="tm-title">Timeout Settings</div>
            <div class="tm-presets">
                ${Object.entries(PRESETS).map(([key, p]) => `
                    <button class="tm-preset-btn ${key === priority ? 'active' : ''}"
                            data-preset="${key}">
                        ${p.icon} ${p.label}
                    </button>
                `).join('')}
            </div>
            <div class="tm-field">
                <label class="tm-label">Max Wait (seconds)</label>
                <input type="number" class="tm-input" id="tm-max-wait"
                       min="10" max="3600" step="10" value="${max_wait}">
            </div>
            <div class="tm-computed" id="tm-computed">
                <div class="tm-computed-item">
                    <div class="tm-computed-value" id="tm-ttft">${computed.ttft}s</div>
                    <div class="tm-computed-label">TTFT</div>
                </div>
                <div class="tm-computed-item">
                    <div class="tm-computed-value" id="tm-idle">${computed.idle}s</div>
                    <div class="tm-computed-label">Idle</div>
                </div>
                <div class="tm-computed-item">
                    <div class="tm-computed-value" id="tm-absmax">${computed.absMax}s</div>
                    <div class="tm-computed-label">Abs Max</div>
                </div>
            </div>
            <div class="tm-actions">
                <button class="tm-save-btn" id="tm-save">Save</button>
                <span class="tm-status" id="tm-status">Saved!</span>
            </div>
        `;

        this._bindEvents();
    }

    _bindEvents() {
        // Preset buttons
        this._dropdown.querySelectorAll('.tm-preset-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this._state.priority = btn.dataset.preset;
                this._dropdown.querySelectorAll('.tm-preset-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this._previewComputed();
            });
        });

        // Max wait input
        const input = this._dropdown.querySelector('#tm-max-wait');
        if (input) {
            input.addEventListener('input', () => {
                const val = parseFloat(input.value);
                if (!isNaN(val) && val >= 10 && val <= 3600) {
                    this._state.max_wait = val;
                    this._previewComputed();
                }
            });
        }

        // Save button
        const saveBtn = this._dropdown.querySelector('#tm-save');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => this._save());
        }
    }

    _computeValues(priority, maxWait) {
        const p = PRESETS[priority] || PRESETS.balanced;
        return {
            ttft: p.ttft,
            idle: p.idle,
            absMax: Math.min(maxWait, p.maxCap)
        };
    }

    _previewComputed() {
        const computed = this._computeValues(this._state.priority, this._state.max_wait);
        const ttft = this._dropdown.querySelector('#tm-ttft');
        const idle = this._dropdown.querySelector('#tm-idle');
        const absMax = this._dropdown.querySelector('#tm-absmax');
        if (ttft) ttft.textContent = computed.ttft + 's';
        if (idle) idle.textContent = computed.idle + 's';
        if (absMax) absMax.textContent = computed.absMax + 's';
    }

    async _save() {
        const statusEl = this._dropdown.querySelector('#tm-status');
        try {
            const res = await fetch('/api/timeout', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    priority: this._state.priority,
                    max_wait: this._state.max_wait
                })
            });
            const data = await res.json();
            if (data.success !== false) {
                this._state.priority = data.priority || this._state.priority;
                this._state.max_wait = data.max_wait || this._state.max_wait;
                this._updateLabel();
                if (statusEl) {
                    statusEl.classList.add('tm-status-visible');
                    setTimeout(() => statusEl.classList.remove('tm-status-visible'), 1500);
                }
            }
        } catch (err) {
            if (statusEl) {
                statusEl.textContent = 'Error!';
                statusEl.style.color = '#f85149';
                statusEl.classList.add('tm-status-visible');
                setTimeout(() => {
                    statusEl.classList.remove('tm-status-visible');
                    statusEl.textContent = 'Saved!';
                    statusEl.style.color = '';
                }, 2000);
            }
        }
    }

    _updateLabel() {
        if (!this._labelEl) return;
        const p = PRESETS[this._state.priority] || PRESETS.balanced;
        this._labelEl.textContent = `${p.label} ${Math.round(this._state.max_wait)}s`;
    }
}

export const timeoutMenu = new TimeoutMenu();
