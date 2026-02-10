/**
 * DOM element references and utility functions
 */

// Lazily populated after DOMContentLoaded
export const dom = {
    output: null,
    input: null,
    sendBtn: null,
    stopBtn: null,
    statusDot: null,
    statusText: null,
    modelBadge: null,
    modeBanner: null,
    modeBannerIcon: null,
    modeBannerText: null,
    autoModeIndicator: null,
    currentModeIcon: null,
    currentModeLabel: null,
    modelSelector: null,
    modelBadgeBtn: null,
    modelDropdown: null,
    modelList: null,
    modelNameSpan: null,
    fullscreenBtn: null,
    searchBtn: null,
    installBtn: null,
    pipelineMonitor: null,
    pipelineToggle: null,
};

export function initDom() {
    dom.output = document.getElementById('output');
    dom.input = document.getElementById('input');
    dom.sendBtn = document.getElementById('send-btn');
    dom.stopBtn = document.getElementById('stop-btn');
    dom.statusDot = document.getElementById('status-dot');
    dom.statusText = document.getElementById('status-text');
    dom.modelBadge = document.getElementById('model-badge');
    dom.modeBanner = document.getElementById('mode-banner');
    dom.modeBannerIcon = document.getElementById('mode-banner-icon');
    dom.modeBannerText = document.getElementById('mode-banner-text');
    dom.autoModeIndicator = document.getElementById('auto-mode-indicator');
    dom.currentModeIcon = document.getElementById('current-mode-icon');
    dom.currentModeLabel = document.getElementById('current-mode-label');
    dom.modelSelector = document.getElementById('model-selector');
    dom.modelBadgeBtn = document.getElementById('model-badge');
    dom.modelDropdown = document.getElementById('model-dropdown');
    dom.modelList = document.getElementById('model-list');
    dom.modelNameSpan = document.getElementById('model-name');
    dom.fullscreenBtn = document.getElementById('fullscreen-btn');
    dom.searchBtn = document.getElementById('search-btn');
    dom.installBtn = document.getElementById('install-btn');
    dom.pipelineMonitor = document.getElementById('pipeline-monitor');
    dom.pipelineToggle = document.getElementById('pipeline-toggle');
}

export function scrollToBottom() {
    if (dom.output) dom.output.scrollTop = dom.output.scrollHeight;
}

export function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
