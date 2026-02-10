/**
 * Shared application state
 */

export const state = {
    isProcessing: false,
    currentMode: 'fast',
    pendingConfirmation: null,
    selectedChoiceIndex: 0,
    abortController: null,
    searchModeActive: false,
    availableModels: [],
    deferredPrompt: null,

    // Pipeline data (populated by SSE events)
    pipelineData: {
        active: false,
        taskContext: null,
        candidates: [],
        validationStats: null,
        correctionData: null,
        result: null,
        stages: [],
        candidateComparison: null, // Phase 2: full comparison from pipeline_validation event
    },
};

export default state;
