/**
 * SSE client — parse streaming events, dispatch to EventBus
 */

import eventBus from './event-bus.js';

export function parseSSELine(line) {
    if (!line.startsWith('data: ')) return null;
    try {
        return JSON.parse(line.slice(6));
    } catch (e) {
        return null;
    }
}

/**
 * Stream SSE from fetch response, dispatching events to EventBus.
 * Returns when stream ends.
 * @param {Response} response
 * @param {AbortSignal} signal
 */
export async function processSSEStream(response, signal) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        if (signal && signal.aborted) break;

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop(); // Keep incomplete line

        for (const line of lines) {
            const event = parseSSELine(line);
            if (!event) continue;

            const eventType = event.event;
            // Dispatch to EventBus under the event type name
            eventBus.emit(`sse:${eventType}`, event);
            // Also dispatch generic event
            eventBus.emit('sse:*', event);
        }
    }
}
