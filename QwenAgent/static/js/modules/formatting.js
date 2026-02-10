/**
 * Content formatting — markdown, code blocks, tables, diffs
 */

import { escapeHtml } from './dom.js';
import { EXT_TO_LANG } from './constants.js';

// ========== FORMAT CONTENT (with markdown tables) ==========
export function formatContent(content) {
    if (!content) return '';

    let text = content.replace(/\\n/g, '\n');

    // Extract code blocks first (preserve them)
    const codeBlocks = [];
    let processed = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (match, lang, code) => {
        const idx = codeBlocks.length;
        const langName = lang || 'plaintext';
        const codeBlockId = 'codeblock-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
        codeBlocks.push(renderCodeBlockWithLineNumbers(code.trim(), langName, codeBlockId));
        return `__CODEBLOCK_${idx}__`;
    });

    // Convert space/tab-separated tables to markdown
    processed = convertSpaceTableToMarkdown(processed);

    // Extract and render markdown tables
    const tables = [];
    const tableRegex = /(\|[^\n]+\|\n?)+/g;
    processed = processed.replace(tableRegex, (tableMatch) => {
        const tableHtml = renderMarkdownTable(tableMatch);
        if (tableHtml) {
            const idx = tables.length;
            tables.push(tableHtml);
            return `__TABLE_${idx}__`;
        }
        return tableMatch;
    });

    // Escape HTML
    let html = escapeHtml(processed);

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Bold
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    // Italic
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color:var(--accent-blue)">$1</a>');
    // Headers
    html = html.replace(/^### (.+)$/gm, '<strong style="color:var(--accent-cyan);font-size:14px">$1</strong>');
    html = html.replace(/^## (.+)$/gm, '<strong style="color:var(--accent-cyan);font-size:15px">$1</strong>');
    html = html.replace(/^# (.+)$/gm, '<strong style="color:var(--accent-cyan);font-size:16px">$1</strong>');
    // Bullet lists
    html = html.replace(/^- (.+)$/gm, '&bull; $1');
    // Line breaks
    html = html.replace(/\n/g, '<br>');

    // Restore tables
    tables.forEach((table, i) => {
        html = html.replace(`__TABLE_${i}__`, table);
    });
    // Restore code blocks
    codeBlocks.forEach((block, i) => {
        html = html.replace(`__CODEBLOCK_${i}__`, block);
    });

    return html;
}

// ========== CODE BLOCK WITH LINE NUMBERS ==========
export function renderCodeBlockWithLineNumbers(code, lang, blockId) {
    const lines = code.split('\n');
    const lineCount = lines.length;
    const lineNumWidth = Math.max(40, String(lineCount).length * 10 + 20);

    let linesHtml = '';
    lines.forEach((line, i) => {
        const lineNum = i + 1;
        const escapedLine = line
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
        linesHtml += `<div class="code-line">
            <span class="code-line-number">${lineNum}</span>
            <span class="code-line-content">${escapedLine || ' '}</span>
        </div>`;
    });

    return `
        <div class="code-block-wrapper" id="${blockId}">
            <div class="code-block-header">
                <span class="code-block-lang">${lang}</span>
                <button class="code-copy-btn" onclick="window.__copyCodeBlock('${blockId}')">Copy</button>
            </div>
            <div class="code-block-content" data-lang="${lang}">
                ${linesHtml}
            </div>
        </div>
    `;
}

// ========== COPY CODE ==========
export function copyCodeBlock(blockId) {
    const block = document.getElementById(blockId);
    if (!block) return;
    const lines = block.querySelectorAll('.code-line-content');
    const text = Array.from(lines).map(l => l.textContent).join('\n');
    navigator.clipboard.writeText(text).then(() => {
        const btn = block.querySelector('.code-copy-btn');
        if (btn) {
            btn.textContent = 'Copied!';
            btn.classList.add('copied');
            setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 2000);
        }
    });
}

// Expose globally for onclick handlers in generated HTML
window.__copyCodeBlock = copyCodeBlock;

// ========== SPACE/TAB TABLE TO MARKDOWN ==========
function convertSpaceTableToMarkdown(text) {
    const lines = text.split('\n');
    const result = [];
    let tableLines = [];
    let inTable = false;

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const hasMultipleCols = (line.match(/\s{4,}|\t/g) || []).length >= 2;
        const isTableRow = hasMultipleCols && line.trim().length > 15;

        if (isTableRow) {
            inTable = true;
            tableLines.push(line);
        } else {
            if (inTable && tableLines.length >= 2) {
                result.push(convertTableLinesToMarkdown(tableLines));
            } else if (tableLines.length > 0) {
                result.push(...tableLines);
            }
            tableLines = [];
            inTable = false;
            result.push(line);
        }
    }

    if (inTable && tableLines.length >= 2) {
        result.push(convertTableLinesToMarkdown(tableLines));
    } else {
        result.push(...tableLines);
    }

    return result.join('\n');
}

function convertTableLinesToMarkdown(lines) {
    if (lines.length < 2) return lines.join('\n');
    const rows = lines.map(line =>
        line.trim().split(/\s{4,}|\t+/).map(cell => cell.trim()).filter(cell => cell)
    );
    const maxCols = Math.max(...rows.map(r => r.length));
    if (maxCols < 2) return lines.join('\n');

    const mdLines = [];
    rows.forEach((row, idx) => {
        while (row.length < maxCols) row.push('');
        mdLines.push('| ' + row.join(' | ') + ' |');
        if (idx === 0) {
            mdLines.push('| ' + row.map(() => '---').join(' | ') + ' |');
        }
    });
    return mdLines.join('\n');
}

// ========== MARKDOWN TABLE RENDERER ==========
function renderMarkdownTable(tableText) {
    const lines = tableText.trim().split('\n').filter(l => l.trim());
    if (lines.length < 2) return null;

    const headerLine = lines[0];
    const separatorLine = lines[1];
    const isSeparator = separatorLine.includes('|') && separatorLine.includes('---');
    if (!isSeparator) return null;

    const headers = headerLine.split('|').map(h => h.trim()).filter(h => h);
    const bodyRows = [];
    for (let i = 2; i < lines.length; i++) {
        const cells = lines[i].split('|').map(c => c.trim()).filter(c => c !== '');
        if (cells.length > 0) bodyRows.push(cells);
    }

    let html = '<table class="md-table"><thead><tr>';
    headers.forEach(h => { html += `<th>${escapeHtml(h)}</th>`; });
    html += '</tr></thead><tbody>';
    bodyRows.forEach(row => {
        html += '<tr>';
        row.forEach(cell => { html += `<td>${escapeHtml(cell)}</td>`; });
        for (let i = row.length; i < headers.length; i++) html += '<td></td>';
        html += '</tr>';
    });
    html += '</tbody></table>';
    return html;
}

// ========== FORMAT TOOL RESULT ==========
export function formatToolResult(tool, result) {
    if (tool === 'ls') {
        const items = result.items || [];
        return items.slice(0, 30).map(item => {
            const icon = item.type === 'dir' ? '📁' : '📄';
            return `${icon} ${escapeHtml(item.name)}`;
        }).join('<br>') + (items.length > 30 ? `<br><span style="color:var(--text-muted)">... +${items.length - 30} more</span>` : '');
    }
    if (tool === 'read') {
        const content = result.content || '';
        const rawLines = content.split('\n').slice(0, 100);
        const lines = rawLines.map(l => l.replace(/^\s*\d+:\s?/, ''));
        const startLine = (result.offset || 0) + 1;
        return formatDiffView(result.file_path || 'file', lines, null, 'read', startLine);
    }
    if (tool === 'grep') {
        const matches = result.matches || [];
        return matches.slice(0, 20).map(m =>
            `<span style="color:var(--text-muted)">${escapeHtml(m.file)}:${m.line_number}:</span> ${escapeHtml(m.line)}`
        ).join('<br>');
    }
    if (tool === 'bash') {
        const stdout = result.stdout || '';
        const stderr = result.stderr || '';
        let html = stdout ? `<pre style="margin:0">${escapeHtml(stdout)}</pre>` : '';
        if (stderr) html += `<pre style="margin:0;color:var(--accent-red)">${escapeHtml(stderr)}</pre>`;
        return html || '<span style="color:var(--text-muted)">(no output)</span>';
    }
    if (tool === 'edit' || tool === 'write' || tool === 'code_inject') {
        const file = result.file_path || result.file || 'file';
        const oldContent = result.old_content || '';
        const newContent = result.new_content || '';
        const startLine = result.context_start_line || 1;
        if (oldContent || newContent) {
            return formatDiffView(file,
                newContent ? newContent.split('\n') : [],
                oldContent ? oldContent.split('\n') : [],
                tool, startLine
            );
        }
        const action = tool === 'write' ? 'written' : 'edited';
        return `<span style="color:var(--accent-green)">✓ File ${action}: ${escapeHtml(file)}</span>`;
    }
    return `<pre style="margin:0">${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
}

// ========== LCS DIFF ALGORITHM ==========
export function computeLCS(a, b) {
    const m = a.length, n = b.length;
    if (m * n > 500000) return null;

    const dp = Array.from({length: m + 1}, () => new Uint16Array(n + 1));
    for (let i = 1; i <= m; i++) {
        for (let j = 1; j <= n; j++) {
            dp[i][j] = a[i-1] === b[j-1]
                ? dp[i-1][j-1] + 1
                : Math.max(dp[i-1][j], dp[i][j-1]);
        }
    }
    const ops = [];
    let i = m, j = n;
    while (i > 0 || j > 0) {
        if (i > 0 && j > 0 && a[i-1] === b[j-1]) {
            ops.push({type: 'context', oldIdx: i-1, newIdx: j-1, text: a[i-1]});
            i--; j--;
        } else if (j > 0 && (i === 0 || dp[i][j-1] >= dp[i-1][j])) {
            ops.push({type: 'added', newIdx: j-1, text: b[j-1]});
            j--;
        } else {
            ops.push({type: 'removed', oldIdx: i-1, text: a[i-1]});
            i--;
        }
    }
    return ops.reverse();
}

function getLangFromFile(filePath) {
    if (!filePath) return null;
    const name = filePath.split(/[/\\]/).pop().toLowerCase();
    if (name === 'dockerfile' || name.startsWith('dockerfile.')) return 'dockerfile';
    if (name === 'makefile' || name === 'gnumakefile') return 'makefile';
    const ext = name.includes('.') ? name.split('.').pop() : '';
    return EXT_TO_LANG[ext] || null;
}

// ========== DIFF VIEW ==========
export function formatDiffView(file, newLines, oldLines, action, startLine) {
    startLine = startLine || 1;
    const lang = getLangFromFile(file);
    const diffId = 'diff-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
    let addedCount = 0, removedCount = 0;

    let html = `<div class="diff-container" id="${diffId}">
        <div class="diff-header">
            <span class="diff-header-icon">●</span>
            <span class="diff-header-text">${action === 'read' ? 'Read' : 'Edit'}</span>
            <span class="diff-header-file">${escapeHtml(file)}</span>
            <div class="diff-stats">__DIFF_STATS__</div>
        </div>
        <div class="diff-content">`;

    if (action === 'read') {
        newLines.forEach((line, i) => {
            html += `<div class="diff-line diff-context">
                <span class="diff-line-number">${startLine + i}</span>
                <span class="diff-line-content">${escapeHtml(line)}</span>
            </div>`;
        });
    } else {
        const ops = (oldLines && oldLines.length > 0) ? computeLCS(oldLines, newLines) : null;

        if (ops) {
            let lineNum = startLine;
            ops.forEach(op => {
                if (op.type === 'context') {
                    html += `<div class="diff-line diff-context"><span class="diff-line-number">${lineNum}</span><span class="diff-line-sign"> </span><span class="diff-line-content">${escapeHtml(op.text)}</span></div>`;
                    lineNum++;
                } else if (op.type === 'removed') {
                    removedCount++;
                    html += `<div class="diff-line diff-removed"><span class="diff-line-number">${lineNum}</span><span class="diff-line-sign">-</span><span class="diff-line-content">${escapeHtml(op.text)}</span></div>`;
                    lineNum++;
                } else if (op.type === 'added') {
                    addedCount++;
                    html += `<div class="diff-line diff-added"><span class="diff-line-number">${lineNum}</span><span class="diff-line-sign">+</span><span class="diff-line-content">${escapeHtml(op.text)}</span></div>`;
                    lineNum++;
                }
            });
        } else {
            newLines.forEach((line, i) => {
                addedCount++;
                html += `<div class="diff-line diff-added"><span class="diff-line-number">${startLine + i}</span><span class="diff-line-sign">+</span><span class="diff-line-content">${escapeHtml(line)}</span></div>`;
            });
        }
    }

    html += '</div></div>';

    if (action !== 'read') {
        const statsHtml =
            (addedCount ? `<span class="diff-stats-added">+${addedCount}</span> ` : '') +
            (removedCount ? `<span class="diff-stats-removed">-${removedCount}</span>` : '');
        html = html.replace('__DIFF_STATS__', statsHtml);
    } else {
        html = html.replace('__DIFF_STATS__', '');
    }

    // Schedule syntax highlighting after DOM insertion
    if (lang) {
        setTimeout(() => {
            const container = document.getElementById(diffId);
            if (!container) return;
            container.querySelectorAll('.diff-line-content').forEach(el => {
                const code = document.createElement('code');
                code.className = `language-${lang}`;
                code.textContent = el.textContent;
                el.textContent = '';
                el.appendChild(code);
                hljs.highlightElement(code);
            });
        }, 0);
    }

    return html;
}
