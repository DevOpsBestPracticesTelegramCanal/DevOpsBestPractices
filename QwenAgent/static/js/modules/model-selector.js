/**
 * Model selector — load models, switch model
 */

import { dom, escapeHtml } from './dom.js';
import state from './state.js';
import { addMessage } from './messages.js';

export function initModelSelector() {
    if (!dom.modelBadgeBtn) return;

    dom.modelBadgeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = dom.modelSelector.classList.toggle('open');
        if (isOpen) loadModels();
    });

    document.addEventListener('click', (e) => {
        if (dom.modelSelector && !dom.modelSelector.contains(e.target)) {
            dom.modelSelector.classList.remove('open');
        }
    });
}

async function loadModels() {
    dom.modelList.innerHTML = '<div class="model-dropdown-loading">Loading...</div>';
    try {
        const r = await fetch('/api/models');
        const data = await r.json();
        state.availableModels = data.models || [];
        const current = data.current || '';

        if (state.availableModels.length === 0) {
            dom.modelList.innerHTML = '<div class="model-dropdown-loading">No models found</div>';
            return;
        }

        const ollama = state.availableModels.filter(m => m.provider === 'ollama');
        const claude = state.availableModels.filter(m => m.provider === 'anthropic');

        let html = '';
        if (ollama.length > 0) {
            html += '<div class="model-dropdown-header">🖥️ Ollama (Local)</div>';
            html += ollama.map(m => renderModelItem(m, current)).join('');
        }
        if (claude.length > 0) {
            html += '<div class="model-dropdown-header">☁️ Claude (Anthropic API)</div>';
            html += claude.map(m => renderModelItem(m, current)).join('');
        }
        dom.modelList.innerHTML = html;
    } catch (e) {
        dom.modelList.innerHTML = '<div class="model-dropdown-loading">Failed to load models</div>';
    }
}

function renderModelItem(m, current) {
    const isActive = m.name === current;
    const sizeMB = m.size ? (m.size / 1024 / 1024 / 1024).toFixed(1) + ' GB' : '';
    const params = m.params || '';
    const providerIcon = m.provider === 'anthropic' ? '☁️' : '';
    const meta = [params, sizeMB].filter(Boolean).join(' • ');
    const escapedName = m.name.replace(/'/g, "\\'");
    return `
        <div class="model-item ${isActive ? 'active' : ''}"
             data-model="${m.name}"
             onclick="window.__selectModel('${escapedName}')">
            <span class="model-item-check">${isActive ? '✓' : providerIcon}</span>
            <div class="model-item-info">
                <div class="model-item-name">${m.name}</div>
                ${meta ? `<div class="model-item-meta">${meta}</div>` : ''}
            </div>
        </div>
    `;
}

async function selectModel(name) {
    dom.modelSelector.classList.remove('open');
    try {
        const r = await fetch('/api/models/switch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: name })
        });
        const data = await r.json();
        if (data.success) {
            dom.modelNameSpan.textContent = name.split(':')[0];
            addMessage('system', `Model switched: ${data.old_model} → ${data.new_model}`);
        }
    } catch (e) {
        addMessage('system', `Failed to switch model: ${e.message}`);
    }
}

// Expose globally for onclick in generated HTML
window.__selectModel = selectModel;

export async function checkHealth() {
    try {
        const r = await fetch('/api/health');
        const data = await r.json();
        if (data.ollama) {
            dom.statusDot.classList.remove('offline');
            dom.statusText.textContent = 'Connected';
            dom.modelBadge.textContent = data.model;
        } else {
            dom.statusDot.classList.add('offline');
            dom.statusText.textContent = 'Ollama offline';
        }
    } catch (e) {
        dom.statusDot.classList.add('offline');
        dom.statusText.textContent = 'Disconnected';
    }
}
