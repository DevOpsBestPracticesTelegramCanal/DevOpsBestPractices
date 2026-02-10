/**
 * ValidationMatrix — heatmap grid showing validators × candidates
 */

import { escapeHtml } from './dom.js';

export class ValidationMatrix {
    constructor(containerEl) {
        this._container = containerEl;
    }

    /**
     * Render matrix from candidate comparison data.
     * @param {Array} candidates — array of { id, score, all_passed, validators: { name: { passed, score, errors } } }
     */
    render(candidates) {
        if (!this._container || !candidates || candidates.length === 0) {
            if (this._container) this._container.innerHTML = '<div class="vm-empty">No validation data</div>';
            return;
        }

        // Collect all unique validator names across all candidates
        const validatorSet = new Set();
        for (const c of candidates) {
            if (c.validators) {
                for (const name of Object.keys(c.validators)) {
                    validatorSet.add(name);
                }
            }
        }
        const validators = Array.from(validatorSet).sort();

        if (validators.length === 0) {
            this._container.innerHTML = '<div class="vm-empty">No validators ran</div>';
            return;
        }

        let html = '<div class="vm-grid">';

        // Header row
        html += '<div class="vm-row vm-header-row">';
        html += '<div class="vm-cell vm-corner"></div>';
        for (const c of candidates) {
            const cls = c.id === candidates[0].id ? 'vm-cell vm-col-header vm-best' : 'vm-cell vm-col-header';
            html += `<div class="${cls}" title="Score: ${(c.score || 0).toFixed(2)}">#${c.id}</div>`;
        }
        html += '</div>';

        // One row per validator
        for (const vName of validators) {
            html += '<div class="vm-row">';
            html += `<div class="vm-cell vm-row-header" title="${escapeHtml(vName)}">${this._shortName(vName)}</div>`;
            for (const c of candidates) {
                const v = c.validators ? c.validators[vName] : null;
                if (!v) {
                    html += '<div class="vm-cell vm-na">—</div>';
                    continue;
                }
                const passed = v.passed;
                const score = v.score || 0;
                const errCount = (v.errors || []).length;
                const cls = passed ? (score >= 0.9 ? 'vm-pass-high' : 'vm-pass') : (errCount > 0 ? 'vm-fail-err' : 'vm-fail');
                const icon = passed ? '&#10003;' : '&#10007;';
                const title = `${vName}: ${passed ? 'PASS' : 'FAIL'} (${score.toFixed(2)})${errCount ? ` — ${errCount} error(s)` : ''}`;
                html += `<div class="vm-cell ${cls}" title="${escapeHtml(title)}">${icon}</div>`;
            }
            html += '</div>';
        }

        html += '</div>';

        // Legend
        html += '<div class="vm-legend">';
        html += '<span class="vm-legend-item"><span class="vm-swatch vm-pass-high"></span>Pass (high)</span>';
        html += '<span class="vm-legend-item"><span class="vm-swatch vm-pass"></span>Pass</span>';
        html += '<span class="vm-legend-item"><span class="vm-swatch vm-fail"></span>Fail</span>';
        html += '<span class="vm-legend-item"><span class="vm-swatch vm-fail-err"></span>Fail + errors</span>';
        html += '</div>';

        this._container.innerHTML = html;
    }

    _shortName(name) {
        // Shorten validator names for column display
        const map = {
            'ast_syntax': 'AST',
            'static_ruff': 'Ruff',
            'static_mypy': 'Mypy',
            'static_bandit': 'Bandit',
            'complexity': 'Cmplx',
            'style': 'Style',
            'docstring': 'Doc',
            'oss_patterns': 'OSS',
            'kubeval': 'K8s',
            'kube_linter': 'KLint',
            'tflint': 'TFLint',
            'checkov': 'Checkov',
            'actionlint': 'GHA',
            'yamllint': 'YAML',
            'ansible_lint': 'Ansible',
            'shellcheck': 'Shell',
            'helm_lint': 'Helm',
            'docker_compose': 'Compose',
        };
        return map[name] || name.replace(/^(static_|external_)/, '').slice(0, 8);
    }
}
