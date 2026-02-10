/**
 * EventBus — Pub/Sub for module decoupling
 * Usage: eventBus.on('pipeline_start', handler); eventBus.emit('pipeline_start', data);
 */
class EventBus {
    constructor() {
        this._listeners = {};
    }

    on(event, fn) {
        if (!this._listeners[event]) this._listeners[event] = [];
        this._listeners[event].push(fn);
        return () => this.off(event, fn);
    }

    off(event, fn) {
        const list = this._listeners[event];
        if (!list) return;
        this._listeners[event] = list.filter(f => f !== fn);
    }

    emit(event, data) {
        const list = this._listeners[event];
        if (!list) return;
        for (const fn of list) {
            try {
                fn(data);
            } catch (e) {
                console.error(`[EventBus] Error in handler for "${event}":`, e);
            }
        }
    }

    once(event, fn) {
        const wrapper = (data) => {
            this.off(event, wrapper);
            fn(data);
        };
        return this.on(event, wrapper);
    }
}

export const eventBus = new EventBus();
export default eventBus;
