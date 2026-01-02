import { create } from 'zustand';
import type { AgentRuntime, RuntimeModel } from '../../shared/types';
import { getRuntimeConfig } from '../../shared/constants';

type RuntimeAvailability = { [runtime in AgentRuntime]: boolean };

interface RuntimeState {
  availability: RuntimeAvailability | null;
  modelsByRuntime: Record<AgentRuntime, RuntimeModel[]>;
  isLoadingAvailability: boolean;
  isLoadingModels: Record<AgentRuntime, boolean>;
  lastFetched: Record<AgentRuntime, number | null>;

  setAvailability: (availability: RuntimeAvailability) => void;
  setModels: (runtime: AgentRuntime, models: RuntimeModel[]) => void;
  setLoadingAvailability: (loading: boolean) => void;
  setLoadingModels: (runtime: AgentRuntime, loading: boolean) => void;
}

const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

export const useRuntimeStore = create<RuntimeState>((set) => ({
  availability: null,
  modelsByRuntime: {
    'claude-code': [],
    opencode: [],
  },
  isLoadingAvailability: false,
  isLoadingModels: {
    'claude-code': false,
    opencode: false,
  },
  lastFetched: {
    'claude-code': null,
    opencode: null,
  },

  setAvailability: (availability) => set({ availability }),

  setModels: (runtime, models) =>
    set((state) => ({
      modelsByRuntime: { ...state.modelsByRuntime, [runtime]: models },
      lastFetched: { ...state.lastFetched, [runtime]: Date.now() },
    })),

  setLoadingAvailability: (isLoadingAvailability) => set({ isLoadingAvailability }),

  setLoadingModels: (runtime, loading) =>
    set((state) => ({
      isLoadingModels: { ...state.isLoadingModels, [runtime]: loading },
    })),
}));

export async function loadRuntimeAvailability(): Promise<void> {
  const store = useRuntimeStore.getState();
  if (store.availability !== null) return;

  store.setLoadingAvailability(true);
  try {
    const result = await window.electronAPI.getAvailableRuntimes();
    if (result.success && result.data) {
      store.setAvailability(result.data);
    }
  } catch (error) {
    console.error('Failed to fetch runtime availability:', error);
  } finally {
    store.setLoadingAvailability(false);
  }
}

export async function loadRuntimeModels(runtime: AgentRuntime, force = false): Promise<void> {
  const config = getRuntimeConfig(runtime);
  if (!config.hasDynamicModels) return;

  const store = useRuntimeStore.getState();
  const lastFetched = store.lastFetched[runtime];
  const isCacheValid = lastFetched && Date.now() - lastFetched < CACHE_TTL_MS;

  if (!force && isCacheValid && store.modelsByRuntime[runtime].length > 0) {
    return;
  }

  if (store.isLoadingModels[runtime]) return;

  store.setLoadingModels(runtime, true);
  try {
    const result = await window.electronAPI.getRuntimeModels(runtime);
    if (result.success && result.data) {
      store.setModels(runtime, result.data);
    }
  } catch (error) {
    console.error(`Failed to fetch models for ${runtime}:`, error);
  } finally {
    store.setLoadingModels(runtime, false);
  }
}

export function getRuntimeModels(runtime: AgentRuntime): RuntimeModel[] {
  return useRuntimeStore.getState().modelsByRuntime[runtime];
}

export function isRuntimeModelsLoading(runtime: AgentRuntime): boolean {
  return useRuntimeStore.getState().isLoadingModels[runtime];
}
