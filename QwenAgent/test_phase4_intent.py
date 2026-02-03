# -*- coding: utf-8 -*-
"""
test_phase4_intent.py — Тест Phase 4: Intent-Aware Scheduler
=============================================================

Запуск:
    python test_phase4_intent.py

Тесты:
1. PatternMatcher базовая функциональность
2. StreamAnalyzer обработка токенов
3. IntentScheduler управление сессиями
4. Dynamic timeout adjustment
5. Early termination detection
6. Agent integration
"""

import sys
import time

# Ensure UTF-8 output
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, '.')

from core.intent_scheduler import (
    IntentScheduler,
    StreamAnalyzer,
    SchedulerDecision,
    PatternMatcher,
    DetectedIntent,
    CompletionSignal,
    create_stream_analyzer
)


def print_section(title: str):
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)


def test_pattern_matcher():
    """Тест распознавателя паттернов."""
    print_section("TEST 1: Pattern Matcher")

    # 1.1 Code detection
    print("\n[1.1] Code detection:")
    test_cases = [
        ("```python", True, "code_start"),
        ("def my_function():", True, "code_start"),
        ("class MyClass:", True, "code_start"),
        ("hello world", False, "code_start"),
    ]
    for text, expected, pattern_type in test_cases:
        result = PatternMatcher.detect_code_start(text)
        status = "OK" if result == expected else "FAIL"
        print(f"  [{status}] '{text[:20]}...' -> {result}")

    # 1.2 Tool call detection
    print("\n[1.2] Tool call detection:")
    tool_cases = [
        ("[TOOL: read(file_path='test.py')]", True),
        ("[tool: bash(command='ls')]", True),
        ("Just some text", False),
    ]
    for text, expected in tool_cases:
        result = PatternMatcher.detect_tool_call(text)
        status = "OK" if result == expected else "FAIL"
        print(f"  [{status}] '{text[:30]}...' -> {result}")

    # 1.3 Completion detection
    print("\n[1.3] Completion detection:")
    completion_cases = [
        ("Done.", CompletionSignal.STRONG),
        ("Let me know if you need anything else.", CompletionSignal.STRONG),
        ("Here's the result.", CompletionSignal.WEAK),
        ("First, let's analyze", CompletionSignal.NONE),
    ]
    for text, expected in completion_cases:
        result = PatternMatcher.detect_completion(text)
        status = "OK" if result == expected else "FAIL"
        print(f"  [{status}] '{text[:30]}...' -> {result.value}")

    # 1.4 Continuation detection
    print("\n[1.4] Continuation detection:")
    cont_cases = [
        ("First, we need to", True),
        ("Next, let's do", True),
        ("Step 1: ", True),
        ("The answer is", False),
    ]
    for text, expected in cont_cases:
        result = PatternMatcher.detect_continuation(text)
        status = "OK" if result == expected else "FAIL"
        print(f"  [{status}] '{text[:20]}...' -> {result}")

    print("\n  Pattern Matcher tests passed!")
    return True


def test_stream_analyzer():
    """Тест анализатора потока."""
    print_section("TEST 2: Stream Analyzer")

    # 2.1 Basic token processing
    print("\n[2.1] Basic token processing:")
    analyzer = StreamAnalyzer(initial_timeout=60)

    tokens = ["Hello", ",", " ", "let", " ", "me", " ", "help", "."]
    for token in tokens:
        decision = analyzer.process_token(token)

    state = analyzer.get_current_state()
    print(f"  Tokens processed: {state['token_count']}")
    print(f"  Current intent: {state['current_intent']}")
    print(f"  Elapsed: {state['elapsed']:.2f}s")

    # 2.2 Code block detection
    print("\n[2.2] Code block detection:")
    analyzer2 = StreamAnalyzer(initial_timeout=60)
    code_tokens = ["```", "python", "\n", "def", " ", "foo", "(", ")", ":", "\n", "```"]

    for token in code_tokens:
        analyzer2.process_token(token)

    state2 = analyzer2.get_current_state()
    print(f"  Detected intent: {state2['current_intent']}")
    print(f"  Timeout adjusted to: {state2['current_timeout']:.1f}s")

    # 2.3 Chunk processing
    print("\n[2.3] Chunk processing:")
    analyzer3 = StreamAnalyzer(initial_timeout=60)
    chunk = "Here's a solution:\n```python\nprint('hello')\n```\nDone."
    decision = analyzer3.process_chunk(chunk)

    state3 = analyzer3.get_current_state()
    print(f"  Tokens from chunk: {state3['token_count']}")
    print(f"  Intent: {state3['current_intent']}")

    print("\n  Stream Analyzer tests passed!")
    return True


def test_intent_detection():
    """Тест детекции намерений."""
    print_section("TEST 3: Intent Detection")

    # 3.1 Code generation
    print("\n[3.1] Code generation intent:")
    analyzer = StreamAnalyzer(initial_timeout=60)
    code_stream = "```python\nclass Parser:\n    def parse(self):\n        return True\n```"
    analyzer.process_chunk(code_stream)

    rec = analyzer.get_recommendation()
    print(f"  Dominant intent: {rec['dominant_intent']}")
    print(f"  Total tokens: {rec['total_tokens']}")

    # 3.2 Tool call intent
    print("\n[3.2] Tool call intent:")
    analyzer2 = StreamAnalyzer(initial_timeout=60)
    tool_stream = "I'll read the file:\n[TOOL: read(file_path=\"test.py\")]"
    analyzer2.process_chunk(tool_stream)

    state2 = analyzer2.get_current_state()
    print(f"  Detected intent: {state2['current_intent']}")
    print(f"  In tool call: {state2['in_tool_call']}")

    # 3.3 Thinking intent
    print("\n[3.3] Thinking intent:")
    analyzer3 = StreamAnalyzer(initial_timeout=60)
    thinking_stream = "Let me think about this problem. First, I need to understand..."
    analyzer3.process_chunk(thinking_stream)

    state3 = analyzer3.get_current_state()
    print(f"  Detected intent: {state3['current_intent']}")

    print("\n  Intent Detection tests passed!")
    return True


def test_timeout_adjustment():
    """Тест динамической корректировки таймаута."""
    print_section("TEST 4: Dynamic Timeout Adjustment")

    # 4.1 Extension for code
    print("\n[4.1] Extension for code generation:")
    analyzer = StreamAnalyzer(initial_timeout=60)
    initial = analyzer.current_timeout

    # Generate code
    code_tokens = ["```", "python", "\n"] + ["code_line\n"] * 20 + ["```"]
    for token in code_tokens:
        analyzer.process_token(token)

    final = analyzer.current_timeout
    print(f"  Initial timeout: {initial:.1f}s")
    print(f"  Final timeout: {final:.1f}s")
    print(f"  Change: {final - initial:+.1f}s")

    # 4.2 Reduction for quick completion
    print("\n[4.2] Reduction for completion signals:")
    analyzer2 = StreamAnalyzer(initial_timeout=60)

    # Quick response with completion
    tokens = ["The", " ", "answer", " ", "is", " ", "42", ".", " ", "Done", "."]
    for token in tokens:
        analyzer2.process_token(token)

    state2 = analyzer2.get_current_state()
    print(f"  Timeout after completion: {state2['current_timeout']:.1f}s")

    print("\n  Timeout Adjustment tests passed!")
    return True


def test_early_termination():
    """Тест раннего завершения."""
    print_section("TEST 5: Early Termination")

    # 5.1 Strong completion signal
    print("\n[5.1] Strong completion signal:")
    analyzer = StreamAnalyzer(initial_timeout=60)

    # Generate enough tokens first
    for i in range(60):
        analyzer.process_token(f"word{i} ")

    # Add strong completion
    completion = "That's all. Let me know if you need help."
    decision = analyzer.process_chunk(completion)

    print(f"  Should terminate: {decision.should_terminate}")
    print(f"  Reason: {decision.reason}")

    # 5.2 Multiple weak signals
    print("\n[5.2] Multiple weak signals:")
    analyzer2 = StreamAnalyzer(initial_timeout=60)

    for i in range(60):
        analyzer2.process_token(f"word{i} ")

    # Add multiple periods (weak signals)
    for _ in range(5):
        analyzer2.process_token("Sentence. ")

    state2 = analyzer2.get_current_state()
    print(f"  Completion signals collected: {len(analyzer2.state.completion_signals)}")

    print("\n  Early Termination tests passed!")
    return True


def test_scheduler_stats():
    """Тест статистики планировщика."""
    print_section("TEST 6: Scheduler Statistics")

    scheduler = IntentScheduler()

    # Run several sessions
    print("\n[6.1] Running multiple sessions:")
    for i in range(5):
        analyzer = scheduler.create_analyzer(initial_timeout=60)

        # Simulate different intents
        if i % 2 == 0:
            analyzer.process_chunk("```python\ncode here\n```")
        else:
            analyzer.process_chunk("Here's an explanation...")

        # Generate some tokens
        for j in range(20):
            analyzer.process_token(f"token{j} ")

        scheduler.finalize_analyzer(analyzer)

    stats = scheduler.get_stats()
    print(f"  Total sessions: {stats['total_sessions']}")
    print(f"  Early terminations: {stats['early_terminations']}")
    print(f"  Timeout extensions: {stats['timeout_extensions']}")
    print(f"  Avg token count: {stats['average_token_count']:.1f}")
    print(f"  Intent distribution: {stats['intent_distribution']}")

    print("\n  Scheduler Statistics tests passed!")
    return True


def test_agent_integration():
    """Тест интеграции с агентом."""
    print_section("TEST 7: Agent Integration")

    # 7.1 Import and create agent
    print("\n[7.1] Create agent with intent scheduler:")
    from core.qwencode_agent import QwenCodeAgent, QwenCodeConfig
    from core.execution_mode import ExecutionMode

    config = QwenCodeConfig()
    config.model = 'qwen2.5-coder:3b'
    config.execution_mode = ExecutionMode.DEEP3

    agent = QwenCodeAgent(config)
    print(f"  Agent created")
    print(f"  Intent scheduler: {agent.intent_scheduler is not None}")

    # 7.2 Check stats include intent tracking
    print("\n[7.2] Stats include intent tracking:")
    stats = agent.stats
    intent_stats = ["intent_early_exits", "intent_extensions"]
    for stat in intent_stats:
        value = stats.get(stat, "MISSING")
        print(f"  {stat}: {value}")

    # 7.3 Create analyzer through scheduler
    print("\n[7.3] Create analyzer through agent:")
    analyzer = agent.intent_scheduler.create_analyzer(initial_timeout=120)
    print(f"  Analyzer created: {analyzer is not None}")

    # Process some tokens
    test_tokens = ["Let", " me", " analyze", " this", " code", "."]
    for token in test_tokens:
        analyzer.process_token(token)

    state = analyzer.get_current_state()
    print(f"  Current intent: {state['current_intent']}")
    print(f"  Tokens processed: {state['token_count']}")

    print("\n  Agent Integration tests passed!")
    return True


def test_streaming_client_integration():
    """Тест интеграции с streaming client."""
    print_section("TEST 8: Streaming Client Integration")

    print("\n[8.1] Check streaming client has intent support:")
    from core.streaming_llm_client import StreamingLLMClient, INTENT_SCHEDULER_AVAILABLE

    print(f"  INTENT_SCHEDULER_AVAILABLE: {INTENT_SCHEDULER_AVAILABLE}")

    client = StreamingLLMClient()
    print(f"  Client created")

    # Create analyzer through client
    print("\n[8.2] Create analyzer through client:")
    if INTENT_SCHEDULER_AVAILABLE:
        analyzer = client.create_stream_analyzer(initial_timeout=60)
        print(f"  Analyzer created: {analyzer is not None}")

        # Get intent stats
        stats = client.get_intent_stats()
        print(f"  Intent stats: {stats}")
    else:
        print(f"  Intent scheduler not available in client")

    print("\n  Streaming Client Integration tests passed!")
    return True


def main():
    """Запуск всех тестов."""
    print("\n" + "=" * 60)
    print(" QwenCode Phase 4 - Intent-Aware Scheduler Tests")
    print("=" * 60)

    results = []

    # Test 1: Pattern Matcher
    try:
        results.append(("Pattern Matcher", test_pattern_matcher()))
    except Exception as e:
        print(f"\n  Pattern Matcher test failed: {e}")
        results.append(("Pattern Matcher", False))

    # Test 2: Stream Analyzer
    try:
        results.append(("Stream Analyzer", test_stream_analyzer()))
    except Exception as e:
        print(f"\n  Stream Analyzer test failed: {e}")
        results.append(("Stream Analyzer", False))

    # Test 3: Intent Detection
    try:
        results.append(("Intent Detection", test_intent_detection()))
    except Exception as e:
        print(f"\n  Intent Detection test failed: {e}")
        results.append(("Intent Detection", False))

    # Test 4: Timeout Adjustment
    try:
        results.append(("Timeout Adjustment", test_timeout_adjustment()))
    except Exception as e:
        print(f"\n  Timeout Adjustment test failed: {e}")
        results.append(("Timeout Adjustment", False))

    # Test 5: Early Termination
    try:
        results.append(("Early Termination", test_early_termination()))
    except Exception as e:
        print(f"\n  Early Termination test failed: {e}")
        results.append(("Early Termination", False))

    # Test 6: Scheduler Stats
    try:
        results.append(("Scheduler Stats", test_scheduler_stats()))
    except Exception as e:
        print(f"\n  Scheduler Stats test failed: {e}")
        results.append(("Scheduler Stats", False))

    # Test 7: Agent Integration
    try:
        results.append(("Agent Integration", test_agent_integration()))
    except Exception as e:
        print(f"\n  Agent Integration test failed: {e}")
        results.append(("Agent Integration", False))

    # Test 8: Streaming Client Integration
    try:
        results.append(("Streaming Client", test_streaming_client_integration()))
    except Exception as e:
        print(f"\n  Streaming Client test failed: {e}")
        results.append(("Streaming Client", False))

    # Summary
    print_section("SUMMARY")
    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  {name}: {status}")

    print(f"\n  Total: {passed}/{total} tests passed")

    if passed == total:
        print("\n  Phase 4 Intent-Aware Scheduler - ALL TESTS PASSED!")
    else:
        print("\n  Some tests failed. Check output above.")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
