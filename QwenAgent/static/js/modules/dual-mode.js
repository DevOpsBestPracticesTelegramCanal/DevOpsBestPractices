/**
 * Dual Mode — Phase 7
 *
 * Toggle between standard (terminal + collapsed sidebar) and dual layout
 * (terminal + pipeline monitor shown side-by-side, always expanded).
 *
 * Keyboard shortcut: Ctrl+Shift+D
 */

import eventBus from './event-bus.js';

class DualMode {
    constructor() {
        this._active = false;
    }

    init() {
        // Keyboard shortcut
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.shiftKey && e.key === 'D') {
                e.preventDefault();
                this.toggle();
            }
        });
    }

    get isActive() {
        return this._active;
    }

    toggle() {
        if (this._active) this.deactivate();
        else this.activate();
    }

    activate() {
        this._active = true;

        const monitor = document.getElementById('pipeline-monitor');
        const mainContent = document.querySelector('.main-content');
        const toggleBtn = document.getElementById('pipeline-toggle');

        if (monitor) {
            monitor.classList.remove('collapsed');
            monitor.classList.add('dual-mode-expanded');
        }
        if (mainContent) {
            mainContent.classList.add('dual-mode-active');
        }
        if (toggleBtn) {
            toggleBtn.style.display = 'none';
        }

        this._updateButton(true);
        eventBus.emit('dual:activated');
    }

    deactivate() {
        this._active = false;

        const monitor = document.getElementById('pipeline-monitor');
        const mainContent = document.querySelector('.main-content');
        const toggleBtn = document.getElementById('pipeline-toggle');

        if (monitor) {
            monitor.classList.remove('dual-mode-expanded');
            monitor.classList.add('collapsed');
        }
        if (mainContent) {
            mainContent.classList.remove('dual-mode-active');
        }
        if (toggleBtn) {
            toggleBtn.style.display = '';
        }

        this._updateButton(false);
        eventBus.emit('dual:deactivated');
    }

    _updateButton(active) {
        const btn = document.getElementById('dual-mode-btn');
        if (btn) {
            btn.classList.toggle('header-btn-active', active);
            btn.title = active ? 'Exit Dual Mode (Ctrl+Shift+D)' : 'Enter Dual Mode (Ctrl+Shift+D)';
        }
    }
}

export const dualMode = new DualMode();
export default dualMode;
