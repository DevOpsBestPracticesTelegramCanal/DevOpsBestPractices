/**
 * StreamingRenderer — batched token DOM updates via requestAnimationFrame
 * Week 20: Renders LLM tokens incrementally with cursor animation
 */

import eventBus from './event-bus.js';
import { createStreamingMessage, appendToStreamingMessage, finalizeStreamingMessage } from './messages.js';
import { scrollToBottom } from './dom.js';

class StreamingRenderer {
    constructor() {
        this._buffer = [];
        this._element = null;
        this._messageId = null;
        this._rafId = null;
        this._fullText = '';
        this._tokensPerFlush = 4; // Max tokens flushed per rAF frame
        this._active = false;
    }

    init() {
        eventBus.on('sse:response_start', (event) => this.start(event.message_id));
        eventBus.on('sse:response_token', (event) => this.appendToken(event.token));
        eventBus.on('sse:response_done', (event) => this.finalize(event));
    }

    /**
     * Start a new streaming message.
     * @param {string} msgId - Unique message ID for this stream
     */
    start(msgId) {
        // Clean up any previous stream
        if (this._active) {
            this._flush(true);
        }

        this._messageId = msgId;
        this._buffer = [];
        this._fullText = '';
        this._active = true;
        this._element = createStreamingMessage(msgId);
        this._scheduleFlush();
    }

    /**
     * Buffer a token for rendering.
     * @param {string} token
     */
    appendToken(token) {
        if (!this._active) return;
        this._buffer.push(token);
        this._fullText += token;
    }

    /**
     * Finalize the streaming message — flush buffer, apply formatting.
     * @param {object} event - response_done SSE event with { content, message_id }
     */
    finalize(event) {
        if (!this._active) return;

        // Cancel pending rAF
        if (this._rafId) {
            cancelAnimationFrame(this._rafId);
            this._rafId = null;
        }

        // Flush any remaining buffered tokens
        this._flush(true);

        // Apply full markdown formatting + syntax highlighting
        const fullContent = event.content || this._fullText;
        if (this._element) {
            finalizeStreamingMessage(this._element, fullContent);
        }

        this._active = false;
        this._element = null;
        this._messageId = null;
        this._buffer = [];
        this._fullText = '';
    }

    /**
     * Schedule a rAF-based flush loop.
     * @private
     */
    _scheduleFlush() {
        if (!this._active) return;

        this._rafId = requestAnimationFrame(() => {
            this._flush(false);
            if (this._active) {
                this._scheduleFlush();
            }
        });
    }

    /**
     * Flush buffered tokens to the DOM.
     * @param {boolean} all - If true, flush entire buffer; else up to _tokensPerFlush.
     * @private
     */
    _flush(all) {
        if (!this._element || this._buffer.length === 0) return;

        const count = all ? this._buffer.length : Math.min(this._buffer.length, this._tokensPerFlush);
        const chunk = this._buffer.splice(0, count).join('');

        if (chunk) {
            appendToStreamingMessage(this._element, chunk);
            scrollToBottom();
        }
    }

    /**
     * Check if currently streaming.
     * @returns {boolean}
     */
    get isStreaming() {
        return this._active;
    }
}

export const streamingRenderer = new StreamingRenderer();
