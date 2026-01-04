import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { EventEmitter } from 'events';

type MockChildProcess = {
  stdout: EventEmitter;
  stderr: EventEmitter;
  on: ReturnType<typeof vi.fn>;
  kill: ReturnType<typeof vi.fn>;
};

function createMockChildProcess(): MockChildProcess {
  return {
    stdout: new EventEmitter(),
    stderr: new EventEmitter(),
    on: vi.fn((event: string, callback: (code: number | null) => void) => {
      if (event === 'close') {
        setTimeout(() => callback(0), 10);
      }
    }),
    kill: vi.fn()
  };
}

function createMockConfig() {
  return {
    getAutoBuildSourcePath: vi.fn(() => '/fake/auto-claude'),
    getProcessEnv: vi.fn(() => ({})),
    getPythonPath: vi.fn(() => 'python')
  };
}

vi.mock('child_process', async (importOriginal) => {
  const actual = await importOriginal<typeof import('child_process')>();
  return {
    ...actual,
    spawn: vi.fn(() => createMockChildProcess())
  };
});

vi.mock('fs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('fs')>();
  return {
    ...actual,
    existsSync: vi.fn(() => true),
    writeFileSync: vi.fn(),
    unlinkSync: vi.fn()
  };
});

vi.mock('../rate-limit-detector', () => ({
  detectRateLimit: vi.fn(() => ({ isRateLimited: false })),
  createSDKRateLimitInfo: vi.fn()
}));

describe('InsightsExecutor Line Buffering', () => {
  let InsightsExecutor: typeof import('./insights-executor').InsightsExecutor;
  let executor: InstanceType<typeof InsightsExecutor>;
  let spawn: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    vi.clearAllMocks();
    const mod = await import('./insights-executor');
    InsightsExecutor = mod.InsightsExecutor;
    executor = new InsightsExecutor(createMockConfig() as never);
    spawn = (await import('child_process')).spawn as ReturnType<typeof vi.fn>;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('Line buffering for chunked stdout', () => {
    it('should handle complete lines arriving in single chunks', async () => {
      const mockProc = createMockChildProcess();
      spawn.mockReturnValue(mockProc);

      const chunks: string[] = [];
      executor.on('stream-chunk', (_projectId, chunk) => {
        if (chunk.type === 'text') {
          chunks.push(chunk.content);
        }
      });

      const executePromise = executor.execute(
        'test-project',
        '/fake/project',
        'test message',
        [],
        undefined,
        'claude-code'
      );

      mockProc.stdout.emit('data', Buffer.from('First line\nSecond line\n'));
      mockProc.on.mock.calls.find((call: [string, () => void]) => call[0] === 'close')?.[1](0);

      await executePromise;

      expect(chunks).toContain('First line\n');
      expect(chunks).toContain('Second line\n');
    });

    it('should buffer partial lines until newline arrives', async () => {
      const mockProc = createMockChildProcess();
      spawn.mockReturnValue(mockProc);

      const chunks: string[] = [];
      executor.on('stream-chunk', (_projectId, chunk) => {
        if (chunk.type === 'text') {
          chunks.push(chunk.content);
        }
      });

      const executePromise = executor.execute(
        'test-project',
        '/fake/project',
        'test message',
        [],
        undefined,
        'claude-code'
      );

      mockProc.stdout.emit('data', Buffer.from('This is a partial'));
      mockProc.stdout.emit('data', Buffer.from(' line that continues\n'));
      mockProc.on.mock.calls.find((call: [string, () => void]) => call[0] === 'close')?.[1](0);

      await executePromise;

      expect(chunks).toContain('This is a partial line that continues\n');
    });

    it('should handle special markers split across chunks', async () => {
      const mockProc = createMockChildProcess();
      spawn.mockReturnValue(mockProc);

      const toolEvents: Array<{ name: string }> = [];
      executor.on('stream-chunk', (_projectId, chunk) => {
        if (chunk.type === 'tool_start') {
          toolEvents.push({ name: chunk.tool.name });
        }
      });

      const executePromise = executor.execute(
        'test-project',
        '/fake/project',
        'test message',
        [],
        undefined,
        'claude-code'
      );

      mockProc.stdout.emit('data', Buffer.from('__TOOL_START_'));
      mockProc.stdout.emit('data', Buffer.from('_:{"name":"Read",'));
      mockProc.stdout.emit('data', Buffer.from('"input":"file.py"}\n'));
      mockProc.on.mock.calls.find((call: [string, () => void]) => call[0] === 'close')?.[1](0);

      await executePromise;

      expect(toolEvents).toHaveLength(1);
      expect(toolEvents[0].name).toBe('Read');
    });

    it('should process remaining buffer on close', async () => {
      const mockProc = createMockChildProcess();
      spawn.mockReturnValue(mockProc);

      const chunks: string[] = [];
      executor.on('stream-chunk', (_projectId, chunk) => {
        if (chunk.type === 'text') {
          chunks.push(chunk.content);
        }
      });

      const executePromise = executor.execute(
        'test-project',
        '/fake/project',
        'test message',
        [],
        undefined,
        'claude-code'
      );

      mockProc.stdout.emit('data', Buffer.from('Complete line\n'));
      mockProc.stdout.emit('data', Buffer.from('Incomplete without newline'));
      mockProc.on.mock.calls.find((call: [string, () => void]) => call[0] === 'close')?.[1](0);

      await executePromise;

      expect(chunks).toContain('Complete line\n');
      expect(chunks).toContain('Incomplete without newline\n');
    });

    it('should handle JSON-RPC like chunking (arbitrary byte boundaries)', async () => {
      const mockProc = createMockChildProcess();
      spawn.mockReturnValue(mockProc);

      const chunks: string[] = [];
      executor.on('stream-chunk', (_projectId, chunk) => {
        if (chunk.type === 'text') {
          chunks.push(chunk.content);
        }
      });

      const executePromise = executor.execute(
        'test-project',
        '/fake/project',
        'test message',
        [],
        undefined,
        'claude-code'
      );

      const fullMessage = 'Hello, this is a complete message from the AI\n';
      const bytes = Buffer.from(fullMessage);
      for (let i = 0; i < bytes.length; i += 7) {
        mockProc.stdout.emit('data', bytes.subarray(i, Math.min(i + 7, bytes.length)));
      }
      mockProc.on.mock.calls.find((call: [string, () => void]) => call[0] === 'close')?.[1](0);

      await executePromise;

      expect(chunks).toContain('Hello, this is a complete message from the AI\n');
    });

    it('should handle multiple lines in single chunk', async () => {
      const mockProc = createMockChildProcess();
      spawn.mockReturnValue(mockProc);

      const chunks: string[] = [];
      executor.on('stream-chunk', (_projectId, chunk) => {
        if (chunk.type === 'text') {
          chunks.push(chunk.content);
        }
      });

      const executePromise = executor.execute(
        'test-project',
        '/fake/project',
        'test message',
        [],
        undefined,
        'claude-code'
      );

      mockProc.stdout.emit('data', Buffer.from('Line 1\nLine 2\nLine 3\n'));
      mockProc.on.mock.calls.find((call: [string, () => void]) => call[0] === 'close')?.[1](0);

      await executePromise;

      expect(chunks).toContain('Line 1\n');
      expect(chunks).toContain('Line 2\n');
      expect(chunks).toContain('Line 3\n');
    });

    it('should handle task suggestion markers split across chunks', async () => {
      const mockProc = createMockChildProcess();
      spawn.mockReturnValue(mockProc);

      let suggestedTask: { title?: string } | undefined;
      executor.on('stream-chunk', (_projectId, chunk) => {
        if (chunk.type === 'task_suggestion') {
          suggestedTask = chunk.suggestedTask;
        }
      });

      const executePromise = executor.execute(
        'test-project',
        '/fake/project',
        'test message',
        [],
        undefined,
        'claude-code'
      );

      mockProc.stdout.emit('data', Buffer.from('__TASK_SUG'));
      mockProc.stdout.emit('data', Buffer.from('GESTION__:{"title":"Add tests"'));
      mockProc.stdout.emit('data', Buffer.from(',"description":"Write unit tests"}\n'));
      mockProc.on.mock.calls.find((call: [string, () => void]) => call[0] === 'close')?.[1](0);

      await executePromise;

      expect(suggestedTask).toBeDefined();
      expect(suggestedTask?.title).toBe('Add tests');
    });

    it('should handle empty lines correctly', async () => {
      const mockProc = createMockChildProcess();
      spawn.mockReturnValue(mockProc);

      const chunks: string[] = [];
      executor.on('stream-chunk', (_projectId, chunk) => {
        if (chunk.type === 'text') {
          chunks.push(chunk.content);
        }
      });

      const executePromise = executor.execute(
        'test-project',
        '/fake/project',
        'test message',
        [],
        undefined,
        'claude-code'
      );

      mockProc.stdout.emit('data', Buffer.from('First line\n\n\nSecond line\n'));
      mockProc.on.mock.calls.find((call: [string, () => void]) => call[0] === 'close')?.[1](0);

      await executePromise;

      expect(chunks.filter(c => c.trim() === '')).toHaveLength(0);
      expect(chunks).toContain('First line\n');
      expect(chunks).toContain('Second line\n');
    });

    it('should handle Unicode characters split at byte boundaries', async () => {
      const mockProc = createMockChildProcess();
      spawn.mockReturnValue(mockProc);

      const chunks: string[] = [];
      executor.on('stream-chunk', (_projectId, chunk) => {
        if (chunk.type === 'text') {
          chunks.push(chunk.content);
        }
      });

      const executePromise = executor.execute(
        'test-project',
        '/fake/project',
        'test message',
        [],
        undefined,
        'claude-code'
      );

      mockProc.stdout.emit('data', Buffer.from('Hello '));
      mockProc.stdout.emit('data', Buffer.from([0xF0, 0x9F]));
      mockProc.stdout.emit('data', Buffer.from([0x91, 0x8D]));
      mockProc.stdout.emit('data', Buffer.from(' World\n'));
      mockProc.on.mock.calls.find((call: [string, () => void]) => call[0] === 'close')?.[1](0);

      await executePromise;

      const fullContent = chunks.join('');
      expect(fullContent).toContain('World');
    });
  });

  describe('Runtime parameter handling', () => {
    it('should pass runtime parameter to Python script', async () => {
      const mockProc = createMockChildProcess();
      spawn.mockReturnValue(mockProc);

      const executePromise = executor.execute(
        'test-project',
        '/fake/project',
        'test message',
        [],
        undefined,
        'opencode'
      );

      mockProc.on.mock.calls.find((call: [string, () => void]) => call[0] === 'close')?.[1](0);

      await executePromise;

      const spawnCall = spawn.mock.calls[0];
      const args = spawnCall[1] as string[];
      expect(args).toContain('--runtime');
      expect(args).toContain('opencode');
    });

    it('should default to claude-code runtime when not specified', async () => {
      const mockProc = createMockChildProcess();
      spawn.mockReturnValue(mockProc);

      const executePromise = executor.execute(
        'test-project',
        '/fake/project',
        'test message',
        []
      );

      mockProc.on.mock.calls.find((call: [string, () => void]) => call[0] === 'close')?.[1](0);

      await executePromise;

      const spawnCall = spawn.mock.calls[0];
      const args = spawnCall[1] as string[];
      expect(args).toContain('--runtime');
      expect(args).toContain('claude-code');
    });
  });
});
