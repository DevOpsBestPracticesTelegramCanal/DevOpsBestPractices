/**
 * Correction Tracker — Self-Correction Visualization overlay
 *
 * Shows iteration timeline, score progression, error lists,
 * recurring issue detection, and before/after code diffs.
 */

import { dom, escapeHtml } from './dom.js';
import state from './state.js';
import eventBus from './event-bus.js';

class CorrectionTracker {
    constructor() {
        this._visible = false;
        this._selectedIteration = null;
    }

    /** Open the correction overlay */
    open() {
        const cd = state.pipelineData.correctionData;
        if (!cd) return;
        this._visible = true;
        this._selectedIteration = null;
        this._render();
        const el = document.getElementById('correction-tracker');
        if (el) {
            el.classList.remove('hidden');
            el.addEventListener('keydown', this._onKeydown);
        }
    }

    /** Close the overlay */
    close() {
        this._visible = false;
        const el = document.getElementById('correction-tracker');
        if (el) {
            el.classList.add('hidden');
            el.removeEventListener('keydown', this._onKeydown);
        }
    }

    _onKeydown = (e) => {
        if (e.key === 'Escape') this.close();
    };

    /** Re-render when new SSE data arrives (called by pipeline-monitor) */
    update() {
        if (this._visible) this._render();
    }

    _render() {
        const el = document.getElementById('correction-tracker');
        if (!el) return;

        const cd = state.pipelineData.correctionData;
        if (!cd) {
            el.innerHTML = '';
            return;
        }

        const iterations = cd.iterations || [];
        const result = cd.result || null;
        const maxIter = cd.max_iterations || 3;
        const initialScore = cd.initial_score || 0;

        let html = `
        <div class="ct-overlay">
            <div class="ct-panel">
                <div class="ct-header">
                    <span class="ct-title">Self-Correction</span>
                    <button class="ct-close" id="ct-close-btn" title="Close (Esc)">&times;</button>
                </div>

                <div class="ct-body">
                    ${this._renderTimeline(iterations, maxIter, initialScore)}
                    ${this._renderScoreChart(iterations, initialScore, result)}
                    ${this._renderErrorList(iterations)}
                    ${this._renderRecurringIssues(iterations)}
                    ${this._renderSummary(result)}
                    ${this._renderCodeDiff(iterations)}
                </div>
            </div>
        </div>`;

        el.innerHTML = html;

        // Bind close
        const closeBtn = el.querySelector('#ct-close-btn');
        if (closeBtn) closeBtn.addEventListener('click', () => this.close());

        // Bind iteration clicks
        el.querySelectorAll('.ct-node').forEach(node => {
            node.addEventListener('click', () => {
                const idx = parseInt(node.dataset.idx, 10);
                this._selectedIteration = this._selectedIteration === idx ? null : idx;
                this._render();
            });
        });
    }

    /** Timeline: ①──②──③ with status icons */
    _renderTimeline(iterations, maxIter, initialScore) {
        if (iterations.length === 0) {
            return `<div class="ct-section">
                <div class="ct-section-title">Timeline</div>
                <div class="ct-empty">Waiting for correction iterations...</div>
            </div>`;
        }

        let nodes = '';
        for (let i = 0; i < iterations.length; i++) {
            const it = iterations[i];
            const passed = it.all_passed;
            const score = (it.score || 0).toFixed(2);
            const cls = passed ? 'ct-node-pass' : 'ct-node-fail';
            const selected = this._selectedIteration === i ? ' ct-node-selected' : '';
            const icon = passed ? '&#10003;' : '&#10007;';
            const connector = i < iterations.length - 1 ? '<span class="ct-connector"></span>' : '';

            nodes += `<div class="ct-node ${cls}${selected}" data-idx="${i}" title="Iteration ${i + 1}: score ${score}">
                <span class="ct-node-num">${i + 1}</span>
                <span class="ct-node-icon">${icon}</span>
                <span class="ct-node-score">${score}</span>
            </div>${connector}`;
        }

        // Show remaining slots as pending
        for (let i = iterations.length; i < maxIter; i++) {
            const connector = i < maxIter - 1 ? '<span class="ct-connector ct-connector-pending"></span>' : '';
            nodes += `<div class="ct-node ct-node-pending" title="Pending">
                <span class="ct-node-num">${i + 1}</span>
                <span class="ct-node-icon">&#9675;</span>
                <span class="ct-node-score">—</span>
            </div>${connector}`;
        }

        return `<div class="ct-section">
            <div class="ct-section-title">Timeline</div>
            <div class="ct-timeline">${nodes}</div>
        </div>`;
    }

    /** Score progression bar chart */
    _renderScoreChart(iterations, initialScore, result) {
        if (iterations.length === 0) return '';

        const scores = iterations.map(it => it.score || 0);
        const maxScore = Math.max(...scores, initialScore, 0.01);
        const finalScore = result ? (result.final_score || scores[scores.length - 1]) : scores[scores.length - 1];
        const improvement = result
            ? result.final_score - result.initial_score
            : finalScore - initialScore;
        const improvementPct = initialScore > 0.01
            ? Math.round(improvement / initialScore * 100)
            : 0;

        let bars = '';

        // Initial score bar (from pipeline_result before correction)
        const initPct = Math.round((initialScore / 1.0) * 100);
        bars += `<div class="ct-bar-row">
            <span class="ct-bar-label">Initial</span>
            <div class="ct-bar-track">
                <div class="ct-bar-fill ct-bar-initial" style="width: ${initPct}%"></div>
            </div>
            <span class="ct-bar-value">${initialScore.toFixed(2)}</span>
        </div>`;

        for (let i = 0; i < iterations.length; i++) {
            const score = scores[i];
            const pct = Math.round((score / 1.0) * 100);
            const cls = iterations[i].all_passed ? 'ct-bar-pass' : 'ct-bar-fail';
            bars += `<div class="ct-bar-row">
                <span class="ct-bar-label">Iter ${i + 1}</span>
                <div class="ct-bar-track">
                    <div class="ct-bar-fill ${cls}" style="width: ${pct}%"></div>
                </div>
                <span class="ct-bar-value">${score.toFixed(2)}</span>
            </div>`;
        }

        const sign = improvementPct >= 0 ? '+' : '';
        const impClass = improvement > 0.01 ? 'ct-imp-positive' : improvement < -0.01 ? 'ct-imp-negative' : 'ct-imp-neutral';

        return `<div class="ct-section">
            <div class="ct-section-title">Score Progression</div>
            <div class="ct-chart">${bars}</div>
            <div class="ct-improvement ${impClass}">
                ${initialScore.toFixed(2)} &rarr; ${finalScore.toFixed(2)} (${sign}${improvementPct}%)
            </div>
        </div>`;
    }

    /** Per-iteration error list */
    _renderErrorList(iterations) {
        if (iterations.length === 0) return '';

        const idx = this._selectedIteration;
        const showAll = idx === null;
        const iters = showAll ? iterations : [iterations[idx]];
        const title = showAll ? 'Errors (All Iterations)' : `Errors (Iteration ${idx + 1})`;

        let rows = '';
        for (const it of iters) {
            const errors = it.errors || [];
            if (errors.length === 0) {
                rows += `<div class="ct-error-row ct-error-none">Iter ${it.iteration || '?'}: No errors &#10003;</div>`;
            } else {
                for (const err of errors) {
                    const escaped = escapeHtml(typeof err === 'string' ? err : JSON.stringify(err));
                    rows += `<div class="ct-error-row">
                        <span class="ct-error-iter">Iter ${it.iteration || '?'}</span>
                        <span class="ct-error-msg">${escaped}</span>
                    </div>`;
                }
            }
        }

        return `<div class="ct-section">
            <div class="ct-section-title">${title}</div>
            <div class="ct-error-list">${rows}</div>
        </div>`;
    }

    /** Recurring issues ("cognitive blindness") */
    _renderRecurringIssues(iterations) {
        if (iterations.length < 2) return '';

        // Count error patterns across iterations
        const errorCounts = {};
        for (const it of iterations) {
            const seenInIter = new Set();
            for (const err of (it.errors || [])) {
                const errStr = typeof err === 'string' ? err : JSON.stringify(err);
                // Extract validator name from "[validator_name] message"
                const match = errStr.match(/^\[([^\]]+)\]/);
                const key = match ? match[1] : 'unknown';
                if (!seenInIter.has(key)) {
                    errorCounts[key] = (errorCounts[key] || 0) + 1;
                    seenInIter.add(key);
                }
            }
        }

        const recurring = Object.entries(errorCounts)
            .filter(([_, count]) => count >= 2)
            .sort((a, b) => b[1] - a[1]);

        if (recurring.length === 0) return '';

        let items = '';
        for (const [name, count] of recurring) {
            items += `<div class="ct-recurring-item">
                <span class="ct-recurring-icon">&#9888;</span>
                <span class="ct-recurring-name">${escapeHtml(name)}</span>
                <span class="ct-recurring-count">failed ${count}/${iterations.length} attempts</span>
            </div>`;
        }

        return `<div class="ct-section">
            <div class="ct-section-title">Recurring Issues</div>
            <div class="ct-recurring">${items}</div>
        </div>`;
    }

    /** Final summary */
    _renderSummary(result) {
        if (!result) return '';

        const rows = [];
        rows.push(`<div class="ct-kv"><span>Total Iterations</span><span>${result.total_iterations || '—'}</span></div>`);
        rows.push(`<div class="ct-kv"><span>All Passed</span><span class="${result.all_passed ? 'ct-val-pass' : 'ct-val-fail'}">${result.all_passed ? 'Yes' : 'No'}</span></div>`);
        rows.push(`<div class="ct-kv"><span>Corrected</span><span>${result.corrected ? 'Yes' : 'No'}</span></div>`);

        return `<div class="ct-section">
            <div class="ct-section-title">Result</div>
            ${rows.join('')}
        </div>`;
    }

    /** Before/After code diff (first vs last iteration) */
    _renderCodeDiff(iterations) {
        if (iterations.length < 2) return '';

        // Only show if we have code in the iterations
        const first = iterations[0];
        const last = iterations[iterations.length - 1];
        if (!first.code && !last.code) return '';

        const firstCode = first.code || '(no code)';
        const lastCode = last.code || '(no code)';

        if (firstCode === lastCode) return '';

        // Simple line-by-line diff
        const oldLines = firstCode.split('\n');
        const newLines = lastCode.split('\n');
        const maxLen = Math.max(oldLines.length, newLines.length);

        let diffHtml = '';
        for (let i = 0; i < maxLen; i++) {
            const oldLine = i < oldLines.length ? oldLines[i] : '';
            const newLine = i < newLines.length ? newLines[i] : '';
            if (oldLine === newLine) {
                diffHtml += `<div class="ct-diff-line ct-diff-same"><span class="ct-diff-num">${i + 1}</span><span class="ct-diff-code"> ${escapeHtml(oldLine)}</span></div>`;
            } else {
                if (i < oldLines.length) {
                    diffHtml += `<div class="ct-diff-line ct-diff-del"><span class="ct-diff-num">${i + 1}</span><span class="ct-diff-code">-${escapeHtml(oldLine)}</span></div>`;
                }
                if (i < newLines.length) {
                    diffHtml += `<div class="ct-diff-line ct-diff-add"><span class="ct-diff-num">${i + 1}</span><span class="ct-diff-code">+${escapeHtml(newLine)}</span></div>`;
                }
            }
        }

        return `<div class="ct-section">
            <div class="ct-section-title">Code Changes (Iter 1 &rarr; ${iterations.length})</div>
            <div class="ct-diff">${diffHtml}</div>
        </div>`;
    }
}

export const correctionTracker = new CorrectionTracker();
export default correctionTracker;
