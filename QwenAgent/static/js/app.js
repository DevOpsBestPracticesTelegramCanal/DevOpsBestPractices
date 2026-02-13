/**
 * QwenCode App — Entry point
 * Imports all ES6 modules, initializes the application
 */

import { initDom } from './modules/dom.js';
import { initInputHandlers } from './modules/input-handler.js';
import { initModelSelector, checkHealth } from './modules/model-selector.js';
import { initChoiceKeyboardHandlers } from './modules/choices.js';
import { pipelineMonitor } from './modules/pipeline-monitor.js';
import { candidatePanel } from './modules/candidate-panel.js';
import { correctionTracker } from './modules/correction-tracker.js';
import { dashboard } from './modules/dashboard.js';
import { settingsPanel } from './modules/settings-panel.js';
import { deepWizard } from './modules/deep-wizard.js';
import { workingMemoryPanel } from './modules/working-memory-panel.js';
import { checkpointManager } from './modules/checkpoint-manager.js';
import { parallelView } from './modules/parallel-view.js';
import { dualMode } from './modules/dual-mode.js';
import { streamingRenderer } from './modules/streaming-renderer.js';
import { timeoutMenu } from './modules/timeout-menu.js';
import { validationForm } from './modules/validation-form.js';
import eventBus from './modules/event-bus.js';

// Wire SSE events to choice/approval handlers
import { renderChoicePrompt, renderApprovalPrompt, hideApprovalPrompt } from './modules/choices.js';
import { hideLoading } from './modules/messages.js';

function initSSEChoiceHandlers() {
    eventBus.on('sse:choice_request', (event) => {
        renderChoicePrompt(event);
    });
    eventBus.on('sse:approval_required', (event) => {
        renderApprovalPrompt(event);
    });
    eventBus.on('sse:approval_resolved', (event) => {
        hideApprovalPrompt(event.request_id);
    });
}

function initDashboard() {
    const btn = document.getElementById('dashboard-btn');
    if (btn) {
        btn.addEventListener('click', () => dashboard.open());
    }
}

function initSettings() {
    const btn = document.getElementById('settings-btn');
    if (btn) {
        btn.addEventListener('click', () => settingsPanel.open());
    }
}

function initValidationForm() {
    const btn = document.getElementById('validate-btn');
    if (btn) {
        btn.addEventListener('click', () => validationForm.open());
    }
}

function initPhase7Buttons() {
    const wmBtn = document.getElementById('wm-btn');
    if (wmBtn) {
        wmBtn.addEventListener('click', () => workingMemoryPanel.toggle());
    }
    const cpBtn = document.getElementById('checkpoint-btn');
    if (cpBtn) {
        cpBtn.addEventListener('click', () => checkpointManager.open());
    }
    const dualBtn = document.getElementById('dual-mode-btn');
    if (dualBtn) {
        dualBtn.addEventListener('click', () => dualMode.toggle());
    }
}

// ========== INIT ==========
document.addEventListener('DOMContentLoaded', () => {
    // 1. Initialize DOM references
    initDom();

    // 2. Input handlers (send, stop, keyboard shortcuts)
    initInputHandlers();

    // 3. Model selector
    initModelSelector();

    // 4. Choice/Approval keyboard handlers
    initChoiceKeyboardHandlers();

    // 5. SSE → Choice wiring
    initSSEChoiceHandlers();

    // 6. Pipeline Monitor
    pipelineMonitor.init();

    // 7. Dashboard
    initDashboard();

    // 8. Settings
    initSettings();

    // 8b. Validation Form
    initValidationForm();

    // 9. Deep Wizard (Minsky 6-step)
    deepWizard.init();

    // 10. Phase 7: Working Memory, Checkpoints, Parallel View, Dual Mode
    workingMemoryPanel.init();
    checkpointManager.init();
    parallelView.init();
    dualMode.init();
    initPhase7Buttons();

    // 11. Streaming Renderer (Week 20)
    streamingRenderer.init();

    // 12. Timeout Menu (Week 21)
    timeoutMenu.init();

    // 13. Health check
    checkHealth();
    setInterval(checkHealth, 30000);

    console.log('[QwenCode] App initialized (ES6 modules)');
});
