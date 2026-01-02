import { IPC_CHANNELS } from '../../../shared/constants';
import type { IPCResult, AgentRuntime } from '../../../shared/types';
import { invokeIpc } from './ipc-utils';

export interface RuntimeAvailability {
  'claude-code': boolean;
  opencode: boolean;
}

export interface RuntimeModel {
  id: string;
  provider: string;
  name: string;
}

export interface BackendAPI {
  getAvailableRuntimes: () => Promise<IPCResult<RuntimeAvailability>>;
  getRuntimeModels: (runtime: AgentRuntime) => Promise<IPCResult<RuntimeModel[]>>;
}

export const createBackendAPI = (): BackendAPI => ({
  getAvailableRuntimes: () => invokeIpc(IPC_CHANNELS.RUNTIME_GET_AVAILABLE),
  getRuntimeModels: (runtime: AgentRuntime) => invokeIpc(IPC_CHANNELS.RUNTIME_GET_MODELS, runtime),
});
