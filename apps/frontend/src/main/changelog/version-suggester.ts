import { spawn } from 'child_process';
import * as path from 'path';
import * as os from 'os';
import type { GitCommit, AgentRuntime } from '../../shared/types';
import { getProfileEnv } from '../rate-limit-detector';
import { parsePythonCommand } from '../python-detector';
import { DEFAULT_FEATURE_MODELS_BY_BACKEND } from '../../shared/constants';

interface VersionSuggestion {
  version: string;
  reason: string;
  bumpType: 'major' | 'minor' | 'patch';
}

/**
 * AI-powered version bump suggester using Claude SDK with haiku model
 * Analyzes commits to intelligently suggest semantic version bumps
 */
export class VersionSuggester {
  private debugEnabled: boolean;
  private runtime: AgentRuntime;

  constructor(
    private pythonPath: string,
    private claudePath: string,
    private autoBuildSourcePath: string,
    debugEnabled: boolean,
    runtime: AgentRuntime = 'claude-code'
  ) {
    this.debugEnabled = debugEnabled;
    this.runtime = runtime;
  }

  private debug(...args: unknown[]): void {
    if (this.debugEnabled) {
      console.warn('[VersionSuggester]', ...args);
    }
  }

  /**
   * Suggest version bump using AI analysis of commits
   */
  async suggestVersionBump(
    commits: GitCommit[],
    currentVersion: string
  ): Promise<VersionSuggestion> {
    this.debug('suggestVersionBump called', {
      commitCount: commits.length,
      currentVersion
    });

    // Build prompt for Claude to analyze commits
    const prompt = this.buildPrompt(commits, currentVersion);
    const script = this.createAnalysisScript(prompt);

    // Build environment
    const spawnEnv = this.buildSpawnEnvironment();

    return new Promise((resolve, _reject) => {
      // Parse Python command to handle space-separated commands like "py -3"
      const [pythonCommand, pythonBaseArgs] = parsePythonCommand(this.pythonPath);
      const childProcess = spawn(pythonCommand, [...pythonBaseArgs, '-c', script], {
        cwd: this.autoBuildSourcePath,
        env: spawnEnv
      });

      let output = '';
      let errorOutput = '';

      childProcess.stdout?.on('data', (data: Buffer) => {
        output += data.toString();
      });

      childProcess.stderr?.on('data', (data: Buffer) => {
        errorOutput += data.toString();
      });

      childProcess.on('exit', (code: number | null) => {
        if (code === 0 && output.trim()) {
          try {
            const result = this.parseAIResponse(output.trim(), currentVersion);
            this.debug('AI suggestion parsed', result);
            resolve(result);
          } catch (error) {
            this.debug('Failed to parse AI response', error);
            // Fallback to simple bump
            resolve(this.fallbackSuggestion(currentVersion));
          }
        } else {
          this.debug('AI analysis failed', { code, error: errorOutput });
          // Fallback to simple bump
          resolve(this.fallbackSuggestion(currentVersion));
        }
      });

      childProcess.on('error', (err: Error) => {
        this.debug('Process error', err);
        resolve(this.fallbackSuggestion(currentVersion));
      });
    });
  }

  /**
   * Build prompt for Claude to analyze commits and suggest version bump
   */
  private buildPrompt(commits: GitCommit[], currentVersion: string): string {
    const commitSummary = commits
      .map((c, i) => `${i + 1}. ${c.hash} - ${c.subject}`)
      .join('\n');

    return `You are a semantic versioning expert analyzing git commits to suggest the appropriate version bump.

Current version: ${currentVersion}

Analyze these ${commits.length} commits and determine the appropriate semantic version bump:

${commitSummary}

Consider:
- MAJOR (X.0.0): Breaking changes, API changes, removed features, architectural changes
- MINOR (0.X.0): New features, enhancements, additions that maintain backward compatibility
- PATCH (0.0.X): Bug fixes, small tweaks, documentation updates, refactoring without new features

Respond with ONLY a JSON object in this exact format (no markdown, no extra text):
{
  "bumpType": "major|minor|patch",
  "reason": "Brief explanation of the decision"
}`;
  }

  /**
   * Create Python script to run Claude analysis
   */
  private createAnalysisScript(prompt: string): string {
    const escapedPrompt = JSON.stringify(prompt);
    const model = DEFAULT_FEATURE_MODELS_BY_BACKEND[this.runtime].utility;

    return `
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

async def analyze_version():
    try:
        from core.runtime import create_agent_runtime, BlockType

        prompt = ${escapedPrompt}
        runtime_type = "${this.runtime}"
        model = "${model}"

        runtime = create_agent_runtime(
            project_dir=Path("."),
            spec_dir=Path("."),
            model=model,
            agent_type="coder",
            runtime=runtime_type,
        )

        async with runtime:
            await runtime.query(prompt)

            response_text = ""
            async for msg in runtime.receive_response():
                msg_type = type(msg).__name__
                if msg_type == "AgentMessage":
                    for block in msg.content:
                        if block.type == BlockType.TEXT and block.text:
                            response_text += block.text
                elif msg_type == "AssistantMessage" and hasattr(msg, "content"):
                    for block in msg.content:
                        block_type = type(block).__name__
                        if block_type == "TextBlock" and hasattr(block, "text"):
                            response_text += block.text

            if response_text:
                print(response_text)
                sys.exit(0)

        sys.exit(1)

    except ImportError as e:
        print(f"Import error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

asyncio.run(analyze_version())
`;
  }

  /**
   * Parse AI response to extract version suggestion
   */
  private parseAIResponse(output: string, currentVersion: string): VersionSuggestion {
    // Extract JSON from output (Claude might wrap it in markdown or other text)
    const jsonMatch = output.match(/\{[\s\S]*"bumpType"[\s\S]*"reason"[\s\S]*\}/);
    if (!jsonMatch) {
      throw new Error('No JSON found in AI response');
    }

    const parsed = JSON.parse(jsonMatch[0]);
    const bumpType = parsed.bumpType as 'major' | 'minor' | 'patch';
    const reason = parsed.reason || 'AI analysis of commits';

    // Calculate new version
    const [major, minor, patch] = currentVersion.split('.').map(Number);

    let newVersion: string;
    switch (bumpType) {
      case 'major':
        newVersion = `${major + 1}.0.0`;
        break;
      case 'minor':
        newVersion = `${major}.${minor + 1}.0`;
        break;
      case 'patch':
      default:
        newVersion = `${major}.${minor}.${patch + 1}`;
        break;
    }

    return {
      version: newVersion,
      reason,
      bumpType
    };
  }

  /**
   * Fallback suggestion if AI analysis fails
   */
  private fallbackSuggestion(currentVersion: string): VersionSuggestion {
    const [major, minor, patch] = currentVersion.split('.').map(Number);
    return {
      version: `${major}.${minor}.${patch + 1}`,
      reason: 'Patch version bump (default)',
      bumpType: 'patch'
    };
  }

  /**
   * Build spawn environment with proper PATH and auth settings
   */
  private buildSpawnEnvironment(): Record<string, string> {
    const homeDir = os.homedir();
    const isWindows = process.platform === 'win32';

    // Build PATH with platform-appropriate separator and locations
    const pathAdditions = isWindows
      ? [
          path.join(homeDir, 'AppData', 'Local', 'Programs', 'claude'),
          path.join(homeDir, 'AppData', 'Roaming', 'npm'),
          path.join(homeDir, '.local', 'bin'),
          'C:\\Program Files\\Claude',
          'C:\\Program Files (x86)\\Claude'
        ]
      : [
          '/usr/local/bin',
          '/opt/homebrew/bin',
          path.join(homeDir, '.local', 'bin'),
          path.join(homeDir, 'bin')
        ];

    // Get active Claude profile environment
    const profileEnv = getProfileEnv();

    const spawnEnv: Record<string, string> = {
      ...process.env as Record<string, string>,
      ...profileEnv,
      ...(isWindows ? { USERPROFILE: homeDir } : { HOME: homeDir }),
      USER: process.env.USER || process.env.USERNAME || 'user',
      PATH: [process.env.PATH || '', ...pathAdditions].filter(Boolean).join(path.delimiter),
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
      PYTHONUTF8: '1'
    };

    return spawnEnv;
  }
}
