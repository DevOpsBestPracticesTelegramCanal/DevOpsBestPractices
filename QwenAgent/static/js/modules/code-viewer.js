/**
 * CodeViewer — tabbed code view (Code / Diff / Report) for candidate inspection
 */

import { escapeHtml } from './dom.js';

export class CodeViewer {
    constructor(containerEl) {
        this._container = containerEl;
        this._activeTab = 'code';
        this._candidate = null;
        this._compareCandidate = null;
    }

    setCandidate(candidate, compareCandidate = null) {
        this._candidate = candidate;
        this._compareCandidate = compareCandidate;
        this.render();
    }

    render() {
        if (!this._container || !this._candidate) return;

        const c = this._candidate;
        const tabs = [
            { id: 'code', label: 'Code' },
            { id: 'diff', label: 'Diff', disabled: !this._compareCandidate },
            { id: 'report', label: 'Report' },
        ];

        let html = '<div class="cv-tabs">';
        for (const tab of tabs) {
            const cls = tab.id === this._activeTab ? 'cv-tab cv-tab-active' : 'cv-tab';
            const disabled = tab.disabled ? ' cv-tab-disabled' : '';
            html += `<button class="${cls}${disabled}" data-tab="${tab.id}">${tab.label}</button>`;
        }
        html += '</div>';
        html += '<div class="cv-body">';

        if (this._activeTab === 'code') {
            html += this._renderCode(c);
        } else if (this._activeTab === 'diff' && this._compareCandidate) {
            html += this._renderDiff(c, this._compareCandidate);
        } else if (this._activeTab === 'report') {
            html += this._renderReport(c);
        }

        html += '</div>';

        this._container.innerHTML = html;
        this._bindTabs();
        this._highlightCode();
    }

    _bindTabs() {
        this._container.querySelectorAll('.cv-tab:not(.cv-tab-disabled)').forEach(btn => {
            btn.addEventListener('click', () => {
                this._activeTab = btn.dataset.tab;
                this.render();
            });
        });
    }

    _highlightCode() {
        if (typeof hljs !== 'undefined') {
            this._container.querySelectorAll('pre code').forEach(block => {
                hljs.highlightElement(block);
            });
        }
    }

    _renderCode(c) {
        const code = c.code || '';
        const lines = code.split('\n');
        let html = '<div class="cv-code-block">';
        html += '<div class="cv-code-header">';
        html += `<span class="cv-code-lang">python</span>`;
        html += `<span class="cv-code-lines">${lines.length} lines</span>`;
        html += `<button class="cv-copy-btn" data-code-id="cv-code-${c.id}">Copy</button>`;
        html += '</div>';
        html += `<div class="cv-code-content" id="cv-code-${c.id}">`;
        for (let i = 0; i < lines.length; i++) {
            html += `<div class="cv-line"><span class="cv-line-num">${i + 1}</span><span class="cv-line-code">${escapeHtml(lines[i])}</span></div>`;
        }
        html += '</div></div>';

        // Bind copy after next tick
        setTimeout(() => {
            const copyBtn = this._container.querySelector('.cv-copy-btn');
            if (copyBtn) {
                copyBtn.addEventListener('click', () => {
                    navigator.clipboard.writeText(code).then(() => {
                        copyBtn.textContent = 'Copied!';
                        setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
                    });
                });
            }
        }, 0);

        return html;
    }

    _renderDiff(a, b) {
        const aLines = (a.code || '').split('\n');
        const bLines = (b.code || '').split('\n');
        const ops = this._simpleDiff(aLines, bLines);

        let html = `<div class="cv-diff-header">Comparing #${a.id} vs #${b.id}</div>`;
        html += '<div class="cv-diff-content">';
        for (const op of ops) {
            const cls = op.type === 'add' ? 'cv-diff-add' : op.type === 'del' ? 'cv-diff-del' : 'cv-diff-ctx';
            const prefix = op.type === 'add' ? '+' : op.type === 'del' ? '-' : ' ';
            html += `<div class="cv-diff-line ${cls}"><span class="cv-diff-prefix">${prefix}</span><span>${escapeHtml(op.text)}</span></div>`;
        }
        html += '</div>';
        return html;
    }

    _simpleDiff(aLines, bLines) {
        // Simple line-by-line diff using LCS
        const n = aLines.length, m = bLines.length;
        const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
        for (let i = 1; i <= n; i++) {
            for (let j = 1; j <= m; j++) {
                dp[i][j] = aLines[i-1] === bLines[j-1] ? dp[i-1][j-1] + 1 : Math.max(dp[i-1][j], dp[i][j-1]);
            }
        }
        const ops = [];
        let i = n, j = m;
        while (i > 0 || j > 0) {
            if (i > 0 && j > 0 && aLines[i-1] === bLines[j-1]) {
                ops.unshift({ type: 'ctx', text: aLines[i-1] });
                i--; j--;
            } else if (j > 0 && (i === 0 || dp[i][j-1] >= dp[i-1][j])) {
                ops.unshift({ type: 'add', text: bLines[j-1] });
                j--;
            } else {
                ops.unshift({ type: 'del', text: aLines[i-1] });
                i--;
            }
        }
        return ops;
    }

    _renderReport(c) {
        let html = '<div class="cv-report">';

        // Score overview
        const score = c.score != null ? c.score : (c.total_score != null ? c.total_score : 0);
        const pct = Math.round(score * 100);
        html += `<div class="cv-report-score">
            <span class="cv-score-value">${score.toFixed(2)}</span>
            <span class="cv-score-pct">(${pct}%)</span>
            <span class="cv-score-label">${c.all_passed ? 'All Passed' : 'Has Failures'}</span>
        </div>`;

        // Metadata
        html += '<div class="cv-report-meta">';
        html += `<div class="pm-kv"><span>Temperature</span><span class="pm-val">${(c.temperature || 0).toFixed(2)}</span></div>`;
        html += `<div class="pm-kv"><span>Gen Time</span><span class="pm-val">${(c.generation_time || 0).toFixed(1)}s</span></div>`;
        if (c.code_lines) html += `<div class="pm-kv"><span>Lines</span><span class="pm-val">${c.code_lines}</span></div>`;
        html += '</div>';

        // Validation results
        if (c.validators && Object.keys(c.validators).length > 0) {
            html += '<div class="cv-report-validators">';
            html += '<div class="pm-section-title">Validators</div>';
            for (const [name, v] of Object.entries(c.validators)) {
                const icon = v.passed ? '<span class="cv-v-pass">&#10003;</span>' : '<span class="cv-v-fail">&#10007;</span>';
                html += `<div class="cv-validator-row">
                    ${icon}
                    <span class="cv-v-name">${escapeHtml(name)}</span>
                    <span class="cv-v-score">${(v.score || 0).toFixed(2)}</span>
                </div>`;
                if (v.errors && v.errors.length > 0) {
                    for (const err of v.errors.slice(0, 3)) {
                        html += `<div class="cv-v-error">${escapeHtml(err)}</div>`;
                    }
                }
            }
            html += '</div>';
        }

        html += '</div>';
        return html;
    }
}
