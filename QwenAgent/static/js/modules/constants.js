/**
 * Application constants
 */

export const TOOL_ICONS = {
    'read': '📖', 'write': '✏️', 'edit': '🔧', 'ls': '📁',
    'bash': '💻', 'grep': '🔍', 'glob': '🔍', 'search': '🔍',
    'git': '📦', 'web_fetch': '🌐', 'web_search': '🌐',
    'tree': '🌳', 'diff': '📊', 'notebook_read': '📓',
    'notebook_edit': '📓', 'default': '⚡'
};

export const TOOL_LABELS = {
    'read': 'Reading file',
    'write': 'Writing file',
    'edit': 'Editing file',
    'bash': 'Running command',
    'ls': 'Listing directory',
    'grep': 'Searching',
    'glob': 'Finding files',
    'git': 'Git operation',
    'tree': 'Showing tree',
    'web_fetch': 'Fetching URL',
    'web_search': 'Searching web',
    'diff': 'Comparing files'
};

export const MODE_CONFIG = {
    fast:       { icon: '⚡', label: 'Auto',       color: 'rgba(63, 185, 80, 0.3)' },
    deep3:      { icon: '🔬', label: 'Deep3',      color: 'rgba(57, 197, 207, 0.3)' },
    deep6:      { icon: '🧠', label: 'Deep6',      color: 'rgba(163, 113, 247, 0.3)' },
    search:     { icon: '🌐', label: 'Search',     color: 'rgba(88, 166, 255, 0.3)' },
    processing: { icon: '⏳', label: 'Thinking...', color: 'rgba(247, 129, 102, 0.3)' }
};

export const EXT_TO_LANG = {
    'py': 'python', 'js': 'javascript', 'ts': 'typescript', 'jsx': 'javascript',
    'tsx': 'typescript', 'go': 'go', 'rs': 'rust', 'rb': 'ruby', 'java': 'java',
    'c': 'c', 'cpp': 'cpp', 'h': 'c', 'hpp': 'cpp', 'cs': 'csharp',
    'sh': 'bash', 'bash': 'bash', 'zsh': 'bash', 'bat': 'dos', 'ps1': 'powershell',
    'sql': 'sql', 'html': 'xml', 'htm': 'xml', 'xml': 'xml', 'svg': 'xml',
    'css': 'css', 'scss': 'scss', 'less': 'less',
    'json': 'json', 'yaml': 'yaml', 'yml': 'yaml', 'toml': 'ini',
    'md': 'markdown', 'dockerfile': 'dockerfile', 'makefile': 'makefile',
    'tf': 'hcl', 'hcl': 'hcl', 'lua': 'lua', 'php': 'php', 'swift': 'swift',
    'kt': 'kotlin', 'r': 'r', 'pl': 'perl'
};

export const ROUTE_ICONS = {
    'pattern': '⚡',
    'llm': '🤖',
    'deep_search': '🌐',
    'pattern+llm_analysis': '🔍',
    'special_command': '⌘'
};

export const ROUTE_LABELS = {
    'pattern': 'Quick Response',
    'llm': 'AI Response',
    'deep_search': 'Web Search + Analysis',
    'pattern+llm_analysis': 'Search + AI Analysis',
    'special_command': 'Command'
};
