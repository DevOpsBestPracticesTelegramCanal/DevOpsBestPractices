/**
 * Choice & Approval prompts — Claude Code style (y/a/n)
 */

import { dom, scrollToBottom, escapeHtml } from './dom.js';
import state from './state.js';
import { addMessage } from './messages.js';

let activeChoicePrompt = null;
let activeApprovalPrompt = null;
const pendingApprovals = new Map();

// ========== CHOICES ==========
export function renderChoices(choices, messageId, question) {
    state.pendingConfirmation = { choices, messageId };
    state.selectedChoiceIndex = choices.findIndex(c => c.default) || 0;

    const div = document.createElement('div');
    div.id = `choices-${messageId}`;
    div.className = 'choices-container';
    div.innerHTML = `
        <div class="choices-question">${escapeHtml(question || 'Do you want to proceed?')}</div>
        <div class="choices-list">
            ${choices.map((choice, i) => `
                <div class="choice-item ${i === state.selectedChoiceIndex ? 'choice-active' : ''}"
                     data-index="${i}" data-id="${choice.id}">
                    <span class="choice-marker">${i === state.selectedChoiceIndex ? '>' : ' '}</span>
                    <span class="choice-number">${choice.id}.</span>
                    <span>${escapeHtml(choice.text)}</span>
                    <span class="choice-shortcut">${choice.shortcut}</span>
                </div>
            `).join('')}
        </div>
        <div class="choices-hint">↑↓ navigate • Enter select • Esc cancel • 1-3 quick select</div>
    `;
    setTimeout(() => {
        div.querySelectorAll('.choice-item').forEach(item => {
            item.addEventListener('click', () => confirmChoice(parseInt(item.dataset.index)));
        });
    }, 0);
    dom.output.appendChild(div);
    scrollToBottom();
}

// ========== CLAUDE CODE STYLE CHOICE PROMPT ==========
export function renderChoicePrompt(event) {
    const promptId = 'choice-' + Date.now();
    const context = event.context || event.question || 'Apply changes?';

    const div = document.createElement('div');
    div.id = promptId;
    div.className = 'choice-container';
    div.innerHTML = `
        <div class="choice-context">${escapeHtml(context)}</div>
        <div class="choice-options">
            <div class="choice-option" data-key="y" data-action="approve">
                <span class="choice-key">y</span><span>Yes</span>
            </div>
            <div class="choice-option" data-key="a" data-action="approve_with_input">
                <span class="choice-key">a</span><span>Yes, and...</span>
            </div>
            <div class="choice-option" data-key="n" data-action="reject">
                <span class="choice-key">n</span><span>No</span>
            </div>
        </div>
        <div class="choice-input-area" style="display:none">
            <textarea placeholder="Add your instructions..."></textarea>
            <div class="choice-buttons">
                <button class="choice-submit">Submit</button>
                <button class="choice-cancel">Cancel</button>
            </div>
        </div>
        <div class="choice-hint">Press y (yes), a (yes, and...), or n (no)</div>
    `;

    dom.output.appendChild(div);
    scrollToBottom();

    activeChoicePrompt = { id: promptId, event: event, selectedKey: null, instruction: '' };

    div.querySelectorAll('.choice-option').forEach(opt => {
        opt.addEventListener('click', () => handleChoiceClick(opt.dataset.key, opt.dataset.action));
    });

    const submitBtn = div.querySelector('.choice-submit');
    const cancelBtn = div.querySelector('.choice-cancel');
    const textarea = div.querySelector('textarea');

    submitBtn.addEventListener('click', () => submitChoicePrompt('yes', textarea.value.trim()));
    cancelBtn.addEventListener('click', () => {
        div.querySelector('.choice-input-area').style.display = 'none';
        div.querySelectorAll('.choice-option').forEach(o => o.classList.remove('choice-selected'));
        activeChoicePrompt.selectedKey = null;
    });
}

function handleChoiceClick(key, action) {
    if (!activeChoicePrompt) return;
    const container = document.getElementById(activeChoicePrompt.id);
    if (!container) return;

    container.querySelectorAll('.choice-option').forEach(o => o.classList.remove('choice-selected'));
    const selected = container.querySelector(`[data-key="${key}"]`);
    if (selected) selected.classList.add('choice-selected');

    if (action === 'approve_with_input') {
        const inputArea = container.querySelector('.choice-input-area');
        inputArea.style.display = 'block';
        inputArea.querySelector('textarea').focus();
        activeChoicePrompt.selectedKey = key;
    } else if (action === 'approve') {
        submitChoicePrompt('yes', '');
    } else if (action === 'reject') {
        submitChoicePrompt('no', '');
    }
}

async function submitChoicePrompt(choice, instruction) {
    if (!activeChoicePrompt) return;
    const container = document.getElementById(activeChoicePrompt.id);
    if (container) {
        const resultText = choice === 'yes'
            ? (instruction ? `✓ Yes, and: "${instruction}"` : '✓ Yes')
            : '✗ No';
        container.innerHTML = `<div style="color: ${choice === 'yes' ? 'var(--accent-green)' : 'var(--accent-red)'}">${resultText}</div>`;
    }
    try {
        await fetch('/api/choice', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                choice: choice,
                instruction: instruction,
                event_id: activeChoicePrompt.event.event_id || null
            })
        });
    } catch (e) {
        console.error('Choice submit error:', e);
    }
    activeChoicePrompt = null;
}

// ========== APPROVAL PROMPT ==========
export function renderApprovalPrompt(event) {
    const requestId = event.id || ('approval-' + Date.now());
    const tool = event.tool || 'unknown';
    const description = event.description || 'Execute operation?';
    const riskLevel = event.risk_level || 'moderate';
    const params = event.params || {};

    const div = document.createElement('div');
    div.id = `approval-${requestId}`;
    div.className = 'approval-container';
    div.dataset.requestId = requestId;

    const riskColors = {
        'safe': 'var(--accent-green)', 'low': 'var(--accent-blue)',
        'moderate': 'var(--accent-yellow)', 'high': 'var(--accent-orange)',
        'dangerous': 'var(--accent-red)', 'critical': 'var(--accent-red)'
    };
    const riskColor = riskColors[riskLevel] || riskColors.moderate;

    div.innerHTML = `
        <div class="approval-header">
            <span class="approval-icon">⚠️</span>
            <span class="approval-title">Approval Required</span>
            <span class="approval-risk" style="color: ${riskColor}; border-color: ${riskColor}">${riskLevel.toUpperCase()}</span>
        </div>
        <div class="approval-description">${escapeHtml(description)}</div>
        <div class="approval-tool">Tool: <code>${escapeHtml(tool)}</code></div>
        ${Object.keys(params).length > 0 ? `
            <div class="approval-params"><details><summary>Parameters</summary><pre>${escapeHtml(JSON.stringify(params, null, 2))}</pre></details></div>
        ` : ''}
        <div class="approval-options">
            <div class="approval-option approval-yes" data-action="yes"><span class="approval-key">y</span><span>Yes, execute</span></div>
            <div class="approval-option approval-yes-and" data-action="yes_and"><span class="approval-key">a</span><span>Yes, and...</span></div>
            <div class="approval-option approval-no" data-action="no"><span class="approval-key">n</span><span>No, skip</span></div>
            ${riskLevel === 'dangerous' || riskLevel === 'critical' ? `
                <div class="approval-option approval-abort" data-action="abort"><span class="approval-key">x</span><span>Abort all</span></div>
            ` : ''}
        </div>
        <div class="approval-input-area" style="display:none">
            <textarea placeholder="Add modifications or instructions..."></textarea>
            <div class="approval-buttons"><button class="approval-submit">Submit</button><button class="approval-cancel">Cancel</button></div>
        </div>
        <div class="approval-hint">Press y/a/n${riskLevel === 'dangerous' || riskLevel === 'critical' ? '/x' : ''} or click to respond</div>
    `;

    dom.output.appendChild(div);
    scrollToBottom();

    activeApprovalPrompt = { id: requestId, element: div, event: event };
    pendingApprovals.set(requestId, activeApprovalPrompt);

    div.querySelectorAll('.approval-option').forEach(opt => {
        opt.addEventListener('click', () => handleApprovalClick(requestId, opt.dataset.action));
    });

    const submitBtn = div.querySelector('.approval-submit');
    const cancelBtn = div.querySelector('.approval-cancel');
    const textarea = div.querySelector('textarea');

    if (submitBtn) submitBtn.addEventListener('click', () => submitApproval(requestId, 'yes_and', textarea.value.trim()));
    if (cancelBtn) cancelBtn.addEventListener('click', () => {
        div.querySelector('.approval-input-area').style.display = 'none';
        div.querySelectorAll('.approval-option').forEach(o => o.classList.remove('approval-selected'));
    });
}

function handleApprovalClick(requestId, action) {
    const approval = pendingApprovals.get(requestId);
    if (!approval) return;
    const container = approval.element;
    container.querySelectorAll('.approval-option').forEach(o => o.classList.remove('approval-selected'));
    const selected = container.querySelector(`[data-action="${action}"]`);
    if (selected) selected.classList.add('approval-selected');
    if (action === 'yes_and') {
        const inputArea = container.querySelector('.approval-input-area');
        inputArea.style.display = 'block';
        inputArea.querySelector('textarea').focus();
    } else {
        submitApproval(requestId, action);
    }
}

async function submitApproval(requestId, choice, userInput = '') {
    const approval = pendingApprovals.get(requestId);
    if (!approval) return;
    const container = approval.element;
    const resultIcons = { 'yes': '✓', 'yes_and': '✓', 'no': '✗', 'skip': '⏭', 'abort': '⛔' };
    const resultColors = { 'yes': 'var(--accent-green)', 'yes_and': 'var(--accent-green)', 'no': 'var(--accent-red)', 'skip': 'var(--accent-yellow)', 'abort': 'var(--accent-red)' };
    const resultText = userInput ? `${resultIcons[choice]} ${choice}: "${userInput}"` : `${resultIcons[choice]} ${choice}`;
    container.innerHTML = `<div class="approval-result" style="color: ${resultColors[choice]}">${resultText}</div>`;
    try {
        await fetch('/api/approval/respond', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ request_id: requestId, choice: choice, user_input: userInput })
        });
    } catch (e) { console.error('Approval submit error:', e); }
    pendingApprovals.delete(requestId);
    if (activeApprovalPrompt && activeApprovalPrompt.id === requestId) activeApprovalPrompt = null;
}

export function hideApprovalPrompt(requestId) {
    const container = document.getElementById(`approval-${requestId}`);
    if (container) container.innerHTML = '<div class="approval-result" style="color: var(--text-muted)">Resolved externally</div>';
    pendingApprovals.delete(requestId);
    if (activeApprovalPrompt && activeApprovalPrompt.id === requestId) activeApprovalPrompt = null;
}

export function updateChoiceSelection() {
    if (!state.pendingConfirmation) return;
    const container = document.getElementById(`choices-${state.pendingConfirmation.messageId}`);
    if (!container) return;
    container.querySelectorAll('.choice-item').forEach((item, i) => {
        const isActive = i === state.selectedChoiceIndex;
        item.classList.toggle('choice-active', isActive);
        item.querySelector('.choice-marker').textContent = isActive ? '>' : ' ';
    });
}

export async function confirmChoice(index) {
    if (!state.pendingConfirmation) return;
    const choice = state.pendingConfirmation.choices[index !== undefined ? index : state.selectedChoiceIndex];
    const messageId = state.pendingConfirmation.messageId;
    const container = document.getElementById(`choices-${messageId}`);
    if (container) container.innerHTML = `<div style="color:var(--accent-green)">✓ Selected: ${escapeHtml(choice.text)}</div>`;
    try {
        const response = await fetch('/api/confirm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message_id: messageId, choice_id: choice.id, choice_text: choice.text })
        });
        const data = await response.json();
        if (data.success && data.response) addMessage('assistant', data.response);
    } catch (e) { console.error('Confirmation error:', e); }
    state.pendingConfirmation = null;
}

// ========== KEYBOARD HANDLERS ==========
export function initChoiceKeyboardHandlers() {
    document.addEventListener('keydown', (e) => {
        // Approval prompts first
        if (activeApprovalPrompt) {
            const container = activeApprovalPrompt.element;
            if (!container) return;
            if (document.activeElement.tagName === 'TEXTAREA') {
                if (e.key === 'Escape') {
                    const inputArea = container.querySelector('.approval-input-area');
                    if (inputArea) { inputArea.style.display = 'none'; container.querySelectorAll('.approval-option').forEach(o => o.classList.remove('approval-selected')); }
                }
                return;
            }
            const requestId = activeApprovalPrompt.id;
            if (e.key === 'y' || e.key === 'Y') { e.preventDefault(); handleApprovalClick(requestId, 'yes'); }
            else if (e.key === 'a' || e.key === 'A') { e.preventDefault(); handleApprovalClick(requestId, 'yes_and'); }
            else if (e.key === 'n' || e.key === 'N') { e.preventDefault(); handleApprovalClick(requestId, 'no'); }
            else if (e.key === 's' || e.key === 'S') { e.preventDefault(); handleApprovalClick(requestId, 'skip'); }
            else if (e.key === 'x' || e.key === 'X') { e.preventDefault(); handleApprovalClick(requestId, 'abort'); }
            else if (e.key === 'Escape') { e.preventDefault(); submitApproval(requestId, 'no'); }
            return;
        }

        // Choice prompts
        if (activeChoicePrompt) {
            const container = document.getElementById(activeChoicePrompt.id);
            if (!container) return;
            if (document.activeElement.tagName === 'TEXTAREA') {
                if (e.key === 'Escape') {
                    container.querySelector('.choice-input-area').style.display = 'none';
                    container.querySelectorAll('.choice-option').forEach(o => o.classList.remove('choice-selected'));
                    activeChoicePrompt.selectedKey = null;
                }
                return;
            }
            if (e.key === 'y' || e.key === 'Y') { e.preventDefault(); handleChoiceClick('y', 'approve'); }
            else if (e.key === 'a' || e.key === 'A') { e.preventDefault(); handleChoiceClick('a', 'approve_with_input'); }
            else if (e.key === 'n' || e.key === 'N') { e.preventDefault(); handleChoiceClick('n', 'reject'); }
            else if (e.key === 'Escape') { e.preventDefault(); submitChoicePrompt('no', ''); }
        }

        // Confirmation choices
        if (!state.pendingConfirmation) return;
        if (e.key === 'ArrowUp') { e.preventDefault(); state.selectedChoiceIndex = Math.max(0, state.selectedChoiceIndex - 1); updateChoiceSelection(); }
        else if (e.key === 'ArrowDown') { e.preventDefault(); state.selectedChoiceIndex = Math.min(state.pendingConfirmation.choices.length - 1, state.selectedChoiceIndex + 1); updateChoiceSelection(); }
        else if (e.key === 'Enter') { e.preventDefault(); confirmChoice(); }
        else if (e.key === 'Escape') {
            e.preventDefault();
            const c = document.getElementById(`choices-${state.pendingConfirmation.messageId}`);
            if (c) c.innerHTML = `<div style="color:var(--accent-red)">✗ Cancelled</div>`;
            state.pendingConfirmation = null;
        } else if (e.key >= '1' && e.key <= '9') {
            const idx = parseInt(e.key) - 1;
            if (idx < state.pendingConfirmation.choices.length) { e.preventDefault(); confirmChoice(idx); }
        }
    });
}
