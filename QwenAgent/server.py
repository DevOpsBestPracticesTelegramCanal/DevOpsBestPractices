# -*- coding: utf-8 -*-
"""
QwenAgent Server - Terminal Interface
Like Claude Code but in browser
"""

import sys
import os

# Add core to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import json

from core.agent import QwenAgent, AgentConfig
from core.tools import TOOL_REGISTRY

app = Flask(__name__)
CORS(app)

# Initialize agent
config = AgentConfig(
    model="qwen2.5-coder:3b",
    deep_mode=False,
    max_iterations=5
)
agent = QwenAgent(config)

@app.route('/')
def index():
    return render_template('qwencode_terminal.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    """Process chat message through agent"""
    data = request.json
    message = data.get('message', '')
    deep_mode = data.get('deep_mode', False)

    # Update config
    agent.config.deep_mode = deep_mode

    # Process through agent
    result = agent.process(message)

    return jsonify({
        'success': True,
        'response': result['response'],
        'tool_calls': result['tool_calls'],
        'thinking': result['thinking'],
        'route_method': result['route_method'],
        'iterations': result['iterations']
    })

@app.route('/api/tool', methods=['POST'])
def direct_tool():
    """Execute tool directly"""
    data = request.json
    tool_name = data.get('tool')
    params = data.get('params', {})

    if tool_name not in TOOL_REGISTRY:
        return jsonify({'error': f'Unknown tool: {tool_name}'}), 400

    from core.tools import execute_tool
    result = execute_tool(tool_name, **params)
    return jsonify(result)

@app.route('/api/status')
def status():
    """Get agent status"""
    import requests
    try:
        r = requests.get(f"{agent.config.ollama_url}/api/tags", timeout=5)
        if r.status_code == 200:
            models = [m['name'] for m in r.json().get('models', [])]
            return jsonify({
                'status': 'ok',
                'model': agent.config.model,
                'models': models,
                'tools': list(TOOL_REGISTRY.keys()),
                'stats': agent.get_stats()
            })
    except:
        pass
    return jsonify({'status': 'offline'}), 503

@app.route('/api/config', methods=['GET', 'POST'])
def config_endpoint():
    """Get/set agent config"""
    if request.method == 'POST':
        data = request.json
        if 'model' in data:
            agent.config.model = data['model']
        if 'deep_mode' in data:
            agent.config.deep_mode = data['deep_mode']
        if 'max_iterations' in data:
            agent.config.max_iterations = data['max_iterations']

    return jsonify({
        'model': agent.config.model,
        'deep_mode': agent.config.deep_mode,
        'max_iterations': agent.config.max_iterations,
        'ollama_url': agent.config.ollama_url
    })

@app.route('/api/health')
def health():
    """Health check - used by frontend"""
    import requests as req
    try:
        r = req.get(f"{agent.config.ollama_url}/api/tags", timeout=5)
        if r.status_code == 200:
            models = [m['name'] for m in r.json().get('models', [])]
            return jsonify({
                'ollama': True,
                'model': agent.config.model,
                'models': models
            })
    except:
        pass
    return jsonify({'ollama': False, 'model': agent.config.model, 'models': []})

@app.route('/api/models')
def models():
    """List available models: Ollama + Claude"""
    import requests as req

    model_list = []

    # 1. Ollama models
    try:
        r = req.get(f"{agent.config.ollama_url}/api/tags", timeout=5)
        if r.status_code == 200:
            for m in r.json().get('models', []):
                model_list.append({
                    'name': m['name'],
                    'size': m.get('size', 0),
                    'modified': m.get('modified_at', ''),
                    'family': m.get('details', {}).get('family', ''),
                    'params': m.get('details', {}).get('parameter_size', ''),
                    'provider': 'ollama'
                })
    except:
        pass

    # 2. Claude models (if API key is configured)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        claude_models = [
            {'name': 'claude-sonnet-4-20250514', 'params': 'Cloud', 'provider': 'anthropic', 'family': 'Claude 4'},
            {'name': 'claude-3-5-sonnet-20241022', 'params': 'Cloud', 'provider': 'anthropic', 'family': 'Claude 3.5'},
            {'name': 'claude-3-5-haiku-20241022', 'params': 'Cloud', 'provider': 'anthropic', 'family': 'Claude 3.5'},
        ]
        model_list.extend([{**m, 'size': 0, 'modified': ''} for m in claude_models])

    return jsonify({
        'models': model_list,
        'current': agent.config.model
    })

@app.route('/api/models/switch', methods=['POST'])
def switch_model():
    """Switch active model"""
    data = request.json
    new_model = data.get('model', '')
    if not new_model:
        return jsonify({'success': False, 'error': 'No model specified'}), 400

    old_model = agent.config.model
    agent.config.model = new_model
    print(f"  Model switched: {old_model} -> {new_model}")
    return jsonify({
        'success': True,
        'old_model': old_model,
        'new_model': new_model
    })

@app.route('/api/mode', methods=['POST'])
def set_mode():
    """Set agent mode"""
    data = request.json
    mode = data.get('mode', 'fast')
    agent.config.deep_mode = (mode == 'deep')
    return jsonify({'success': True, 'mode': mode})

@app.route('/api/confirm', methods=['POST'])
def confirm():
    """Handle confirmation choices"""
    data = request.json
    return jsonify({'success': True, 'response': f"Choice confirmed: {data.get('choice_text', '')}"})

if __name__ == '__main__':
    print("=" * 60)
    print("  QwenAgent - Autonomous Code Agent")
    print("=" * 60)
    print(f"  URL: http://localhost:5002")
    print(f"  Model: {config.model}")
    print(f"  Tools: {', '.join(TOOL_REGISTRY.keys())}")
    print("=" * 60)
    print("  Features:")
    print("    - NO-LLM routing (85%+ pattern match)")
    print("    - Chain-of-Thought reasoning")
    print("    - Self-correction")
    print("    - All Claude Code tools")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5002, debug=True)
