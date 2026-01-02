import { ipcMain } from 'electron';
import { IPC_CHANNELS } from '../../shared/constants';
import type { IPCResult, AgentRuntime } from '../../shared/types';
import { promisify } from 'util';
import { exec } from 'child_process';

const execAsync = promisify(exec);

export interface RuntimeAvailability {
  'claude-code': boolean;
  opencode: boolean;
}

export interface RuntimeModel {
  id: string;
  provider: string;
  name: string;
}

async function checkCommandExists(command: string): Promise<boolean> {
  try {
    const { stdout } = await execAsync(
      process.platform === 'win32' ? `where ${command}` : `which ${command}`
    );
    return stdout.trim().length > 0;
  } catch {
    return false;
  }
}

async function fetchOpenCodeModels(): Promise<RuntimeModel[]> {
  try {
    const { stdout } = await execAsync('opencode models', { timeout: 10000 });
    const lines = stdout.trim().split('\n').filter(line => line.trim());

    return lines.map(line => {
      const trimmed = line.trim();
      const parts = trimmed.split('/');
      return {
        id: trimmed,
        provider: parts[0] || 'unknown',
        name: parts.slice(1).join('/') || trimmed,
      };
    });
  } catch {
    return [];
  }
}

async function fetchClaudeCodeModels(): Promise<RuntimeModel[]> {
  return [
    { id: 'claude-sonnet-4-20250514', provider: 'anthropic', name: 'Claude Sonnet 4' },
    { id: 'claude-opus-4-20250514', provider: 'anthropic', name: 'Claude Opus 4' },
  ];
}

async function fetchRuntimeModels(runtime: AgentRuntime): Promise<RuntimeModel[]> {
  switch (runtime) {
    case 'opencode':
      return fetchOpenCodeModels();
    case 'claude-code':
      return fetchClaudeCodeModels();
    default:
      return [];
  }
}

export function registerBackendHandlers(): void {
  ipcMain.handle(
    IPC_CHANNELS.RUNTIME_GET_AVAILABLE,
    async (): Promise<IPCResult<RuntimeAvailability>> => {
      try {
        const [claudeCode, opencode] = await Promise.all([
          checkCommandExists('claude'),
          checkCommandExists('opencode'),
        ]);

        return {
          success: true,
          data: {
            'claude-code': claudeCode,
            opencode,
          },
        };
      } catch (error) {
        return {
          success: false,
          error: error instanceof Error ? error.message : 'Failed to check runtime availability',
        };
      }
    }
  );

  ipcMain.handle(
    IPC_CHANNELS.RUNTIME_GET_MODELS,
    async (_, runtime: AgentRuntime): Promise<IPCResult<RuntimeModel[]>> => {
      try {
        const models = await fetchRuntimeModels(runtime);
        return {
          success: true,
          data: models,
        };
      } catch (error) {
        return {
          success: false,
          error: error instanceof Error ? error.message : 'Failed to fetch runtime models',
        };
      }
    }
  );
}
