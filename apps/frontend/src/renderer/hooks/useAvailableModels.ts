import { useEffect, useMemo } from 'react';
import { AVAILABLE_MODELS_BY_BACKEND } from '../../shared/constants';
import type { AppSettings } from '../../shared/types';
import { useRuntimeStore, loadRuntimeModels } from '../stores/runtime-store';

export function useAvailableModels(settings: AppSettings) {
  const runtime = settings.agentRuntime || 'claude-code';
  const runtimeModels = useRuntimeStore((state) => state.modelsByRuntime[runtime]);
  const isLoading = useRuntimeStore((state) => state.isLoadingModels[runtime]);

  useEffect(() => {
    loadRuntimeModels(runtime);
  }, [runtime]);

  const models = useMemo(() => {
    if (runtimeModels.length > 0) {
      return runtimeModels.map((m) => ({ value: m.id, label: m.name }));
    }
    return AVAILABLE_MODELS_BY_BACKEND[runtime as keyof typeof AVAILABLE_MODELS_BY_BACKEND] || AVAILABLE_MODELS_BY_BACKEND['claude-code'];
  }, [runtime, runtimeModels]);

  return { models, isLoading };
}
