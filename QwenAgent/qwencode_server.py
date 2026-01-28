"""
QwenCode Server - Claude Code Clone Interface
Terminal-style web interface
"""

import os
import sys
import json
import time
from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS
import requests
from datetime import datetime

from core.qwencode_agent import QwenCodeAgent, QwenCodeConfig

app = Flask(__name__, template_folder='templates')
CORS(app)

# Configuration
config = QwenCodeConfig(
    ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
    model=os.environ.get("QWEN_MODEL", "qwen2.5-coder:3b"),  # 3b faster on CPU
    max_iterations=10,
    deep_mode=False
)

# Global agent instance
agent = QwenCodeAgent(config)


def warmup_model():
    """
    Прогрев модели - загружает модель в память перед стартом
    Это предотвращает timeout на первом запросе
    """
    print()
    print("  [WARMUP] Прогрев модели...")
    print(f"  [WARMUP] Модель: {config.model}")

    start_time = time.time()

    try:
        # Простой запрос для загрузки модели в память
        response = requests.post(
            f"{config.ollama_url}/api/generate",
            json={
                "model": config.model,
                "prompt": "Say OK",
                "stream": False,
                "options": {
                    "num_predict": 5  # Минимальный ответ
                }
            },
            timeout=120  # 2 минуты на первую загрузку
        )

        elapsed = time.time() - start_time

        if response.status_code == 200:
            result = response.json().get("response", "")
            print(f"  [WARMUP] Модель загружена за {elapsed:.1f} сек")
            print(f"  [WARMUP] Тест: '{result.strip()}'")
            print(f"  [WARMUP] Статус: ГОТОВО")
            return True
        else:
            print(f"  [WARMUP] Ошибка: HTTP {response.status_code}")
            return False

    except requests.exceptions.Timeout:
        print(f"  [WARMUP] Timeout - модель загружается слишком долго")
        print(f"  [WARMUP] Попробуйте: ollama pull {config.model}")
        return False
    except requests.exceptions.ConnectionError:
        print(f"  [WARMUP] Ollama не запущен!")
        print(f"  [WARMUP] Запустите: ollama serve")
        return False
    except Exception as e:
        print(f"  [WARMUP] Ошибка: {e}")
        return False


@app.route('/')
def index():
    """Serve terminal interface"""
    return render_template('qwencode_terminal.html')


@app.route('/api/test-multiline-edit', methods=['POST'])
def test_multiline_edit():
    """Test endpoint: execute a real multiline edit and return result"""
    from core.tools_extended import ExtendedTools
    data = request.json or {}
    result = ExtendedTools.edit(
        file_path=data.get('file_path', '_test_diff.py'),
        old_string=data.get('old_string', ''),
        new_string=data.get('new_string', '')
    )
    return jsonify({
        "success": True,
        "response": "",
        "tool_calls": [{
            "tool": "edit",
            "params": {"file_path": data.get('file_path'), "old_string": "(multiline)", "new_string": "(multiline)"},
            "result": result
        }],
        "thinking": [],
        "route_method": "pattern",
        "iterations": 0,
        "plan_mode": False,
        "mode": "fast",
        "mode_icon": ""
    })


@app.route('/api/chat', methods=['POST'])
def chat():
    """Process chat message with mode support"""
    data = request.json
    message = data.get('message', '')

    if not message:
        return jsonify({"error": "No message provided"}), 400

    print(f"[DEBUG] Received: {message[:100]}...")
    print(f"[DEBUG] Model: {agent.config.model}")

    try:
        # Use process_with_mode for automatic mode detection and escalation
        result = agent.process_with_mode(message)

        response_text = result.get('response', '')
        print(f"[DEBUG] Response length: {len(response_text)}")
        print(f"[DEBUG] Has real newlines: {'\\n' in response_text}")
        print(f"[DEBUG] Newline count: {response_text.count(chr(10))}")
        print(f"[DEBUG] Response preview: {repr(response_text[:300])}...")

        return jsonify({
            "success": True,
            "response": result.get("response", ""),
            "tool_calls": result.get("tool_calls", []),
            "thinking": result.get("thinking", []),
            "route_method": result.get("route_method", ""),
            "iterations": result.get("iterations", 0),
            "plan_mode": result.get("plan_mode", False),
            # Mode fields
            "mode": result.get("mode", "fast"),
            "mode_icon": result.get("mode_icon", ""),
            # DUCS classification fields
            "ducs_code": result.get("ducs_code"),
            "ducs_category": result.get("ducs_category"),
            "ducs_confidence": result.get("ducs_confidence")
        })

    except Exception as e:
        print(f"[DEBUG] Exception: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get agent statistics"""
    return jsonify(agent.get_stats())


@app.route('/api/mode', methods=['GET', 'POST'])
def mode_endpoint():
    """Get or switch execution mode"""
    from core.qwencode_agent import ExecutionMode

    if request.method == 'GET':
        return jsonify(agent.get_mode_status())

    elif request.method == 'POST':
        data = request.json
        new_mode = data.get('mode', '').lower()

        mode_map = {
            'fast': ExecutionMode.FAST,
            'deep': ExecutionMode.DEEP,
            'search': ExecutionMode.DEEP_SEARCH,
            'deep_search': ExecutionMode.DEEP_SEARCH
        }

        if new_mode not in mode_map:
            return jsonify({
                "success": False,
                "error": f"Invalid mode: {new_mode}. Use: fast, deep, search"
            }), 400

        result = agent.switch_mode(mode_map[new_mode], reason="api")
        return jsonify(result)


@app.route('/api/config', methods=['GET', 'POST'])
def config_endpoint():
    """Get or update configuration"""
    if request.method == 'GET':
        return jsonify({
            "model": agent.config.model,
            "ollama_url": agent.config.ollama_url,
            "deep_mode": agent.config.deep_mode,
            "max_iterations": agent.config.max_iterations
        })

    elif request.method == 'POST':
        data = request.json
        if 'model' in data:
            agent.config.model = data['model']
        if 'deep_mode' in data:
            agent.config.deep_mode = data['deep_mode']
        if 'ollama_url' in data:
            agent.config.ollama_url = data['ollama_url']

        return jsonify({
            "success": True,
            "model": agent.config.model,
            "deep_mode": agent.config.deep_mode
        })


@app.route('/api/models', methods=['GET'])
def list_models():
    """List available models: Ollama (local) + Claude (API)"""
    model_list = []

    # 1. Ollama models
    try:
        r = requests.get(f"{agent.config.ollama_url}/api/tags", timeout=5)
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

    if not model_list:
        return jsonify({"success": False, "error": "No models available"})

    return jsonify({
        "success": True,
        "models": model_list,
        "current": agent.config.model
    })


@app.route('/api/models/switch', methods=['POST'])
def switch_model():
    """Switch active Ollama model"""
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


@app.route('/api/health', methods=['GET'])
def health():
    """Health check"""
    ollama_ok = False
    try:
        r = requests.get(f"{agent.config.ollama_url}/api/tags", timeout=3)
        ollama_ok = r.status_code == 200
    except:
        pass

    return jsonify({
        "status": "ok" if ollama_ok else "degraded",
        "ollama": ollama_ok,
        "model": agent.config.model,
        "version": QwenCodeAgent.VERSION
    })


@app.route('/api/clear', methods=['POST'])
def clear_history():
    """Clear conversation history"""
    agent.conversation_history.clear()
    return jsonify({"success": True, "message": "History cleared"})


# Pending confirmations storage
pending_confirmations = {}
allow_all_edits = False  # Session-wide flag


@app.route('/api/confirm', methods=['POST'])
def confirm_action():
    """Handle user confirmation for edit/write actions"""
    global allow_all_edits

    data = request.json
    message_id = data.get('message_id')
    choice_id = data.get('choice_id')
    choice_text = data.get('choice_text', '')

    print(f"[CONFIRM] message_id={message_id}, choice_id={choice_id}, text={choice_text}")

    # Handle "allow all edits" choice
    if choice_id == 2:
        allow_all_edits = True
        return jsonify({
            "success": True,
            "response": "✓ All edits will be auto-approved for this session.",
            "allow_all": True
        })

    # Handle "No" / Cancel
    if choice_id == 3:
        return jsonify({
            "success": True,
            "response": "Action cancelled.",
            "cancelled": True
        })

    # Handle "Yes" - execute pending action
    if message_id in pending_confirmations:
        action = pending_confirmations.pop(message_id)
        try:
            # Execute the pending action
            result = agent.execute_tool(action['tool'], action['params'])
            return jsonify({
                "success": True,
                "response": f"✓ {action['tool']} completed successfully.",
                "result": result
            })
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            })

    return jsonify({
        "success": True,
        "response": "Confirmed."
    })


def main():
    """Run server"""
    port = int(os.environ.get("PORT", 5002))

    print("=" * 60)
    print("  QwenCode - Claude Code Clone")
    print("  Powered by Qwen LLM (LOCAL)")
    print("=" * 60)
    print(f"  URL:    http://localhost:{port}")
    print(f"  Model:  {config.model}")
    print(f"  Ollama: {config.ollama_url}")
    print("=" * 60)
    print()
    print("  MODE SYSTEM:")
    print("  [FAST]   Quick queries (default)")
    print("  [DEEP]   CoT reasoning for complex tasks")
    print("  [SEARCH] Web search integration")
    print()
    print("  Auto-escalation: FAST -> DEEP -> SEARCH")
    print("=" * 60)

    # Прогрев модели перед стартом
    warmup_success = warmup_model()

    if not warmup_success:
        print()
        print("  [WARNING] Модель не прогрета - первый запрос будет медленным")
        print()

    print()
    print("=" * 60)
    print("  ГОТОВО! Откройте в браузере:")
    print(f"  http://localhost:{port}")
    print("=" * 60)
    print()
    print("  Команды:")
    print("    /help              - Справка")
    print("    /mode              - Текущий режим")
    print("    /mode fast|deep|search - Переключить режим")
    print("    /plan              - План-режим")
    print("    /stats             - Статистика")
    print("    /search <query>    - Веб-поиск")
    print()
    print("  Префиксы в запросах:")
    print("    [DEEP] query       - Выполнить в DEEP mode")
    print("    [SEARCH] query     - Выполнить веб-поиск")
    print()

    app.run(host='0.0.0.0', port=port, debug=False)


if __name__ == '__main__':
    main()
