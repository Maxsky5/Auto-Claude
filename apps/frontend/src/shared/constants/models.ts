/**
 * Model and agent profile constants
 * Claude models, thinking levels, memory backends, and agent profiles
 */

import type { AgentProfile, PhaseModelConfig, FeatureModelConfig, FeatureThinkingConfig } from '../types/settings';
import type { AgentRuntime } from '../types';

// ============================================
// Runtime Configuration
// ============================================

export interface RuntimeConfig {
  id: AgentRuntime;
  name: string;
  hasDynamicModels: boolean;      // true = fetch models from API, false = use static list
  supportsThinking: boolean;      // true = show thinking level selector in UI
  requiresAuth: boolean;          // true = requires authentication before running tasks
  modelPrefix: string;            // prefix for model IDs (e.g., 'anthropic/' for OpenCode)
  fastModel: string;              // fast model for quick tasks (terminal naming, utilities)
}

export const RUNTIME_CONFIGS: Record<AgentRuntime, RuntimeConfig> = {
  'claude-code': {
    id: 'claude-code',
    name: 'Claude Code',
    hasDynamicModels: false,
    supportsThinking: true,
    requiresAuth: true,
    modelPrefix: '',
    fastModel: 'claude-haiku-4-5',
  },
  opencode: {
    id: 'opencode',
    name: 'OpenCode',
    hasDynamicModels: true,
    supportsThinking: false,
    requiresAuth: false,
    modelPrefix: 'anthropic/',
    fastModel: 'opencode/grok-code',
  },
};

export function getRuntimeConfig(runtime: AgentRuntime): RuntimeConfig {
  return RUNTIME_CONFIGS[runtime] || RUNTIME_CONFIGS['claude-code'];
}

// ============================================
// Available Models
// ============================================

// Claude Code backend models
export const CLAUDE_CODE_AVAILABLE_MODELS = [
  { value: 'claude-opus-4-5-20251101', label: 'Claude Opus 4.5' },
  { value: 'claude-sonnet-4-5-20250929', label: 'Claude Sonnet 4.5' },
  { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5' }
] as const;

// OpenCode backend default models (free tier)
export const OPENCODE_AVAILABLE_MODELS = [
  { value: 'opencode/big-pickle', label: 'Big Pickle' },
  { value: 'opencode/grok-code', label: 'Grok Code' },
  { value: 'opencode/glm-4.7-free', label: 'GLM 4.7 Free' },
  { value: 'opencode/gpt-5-nano', label: 'GPT-5 Nano' },
  { value: 'opencode/minimax-m2.1-free', label: 'MiniMax M2.1 Free' }
] as const;

export const AVAILABLE_MODELS_BY_BACKEND = {
  'claude-code': CLAUDE_CODE_AVAILABLE_MODELS,
  'opencode': OPENCODE_AVAILABLE_MODELS
} as const;

// Maps thinking levels to budget tokens (null = no extended thinking)
export const THINKING_BUDGET_MAP: Record<string, number | null> = {
  none: null,
  low: 1024,
  medium: 4096,
  high: 16384,
  ultrathink: 65536
} as const;

// ============================================
// Thinking Levels
// ============================================

// Thinking levels for Claude model (budget token allocation)
export const THINKING_LEVELS = [
  { value: 'none', label: 'None', description: 'No extended thinking' },
  { value: 'low', label: 'Low', description: 'Brief consideration' },
  { value: 'medium', label: 'Medium', description: 'Moderate analysis' },
  { value: 'high', label: 'High', description: 'Deep thinking' },
  { value: 'ultrathink', label: 'Ultra Think', description: 'Maximum reasoning depth' }
] as const;

// ============================================
// Agent Profiles
// ============================================

// Default phase model configuration for Auto profile
// Uses Opus across all phases for maximum quality
export const CLAUDE_CODE_DEFAULT_PHASE_MODELS: PhaseModelConfig = {
  spec: 'claude-opus-4-5-20251101',       // Best quality for spec creation
  planning: 'claude-opus-4-5-20251101',   // Complex architecture decisions benefit from Opus
  coding: 'claude-opus-4-5-20251101',     // Highest quality implementation
  qa: 'claude-opus-4-5-20251101'          // Thorough QA review
};

// OpenCode default phase models (using free tier models)
export const OPENCODE_DEFAULT_PHASE_MODELS: PhaseModelConfig = {
  spec: 'opencode/big-pickle',
  planning: 'opencode/big-pickle',
  coding: 'opencode/grok-code',
  qa: 'opencode/glm-4.7-free'
};

export const DEFAULT_PHASE_MODELS_BY_BACKEND: Record<string, PhaseModelConfig> = {
  'claude-code': CLAUDE_CODE_DEFAULT_PHASE_MODELS,
  'opencode': OPENCODE_DEFAULT_PHASE_MODELS
};

// Default phase thinking configuration for Auto profile
export const DEFAULT_PHASE_THINKING: import('../types/settings').PhaseThinkingConfig = {
  spec: 'ultrathink',   // Deep thinking for comprehensive spec creation
  planning: 'high',     // High thinking for planning complex features
  coding: 'low',        // Faster coding iterations
  qa: 'low'             // Efficient QA review
};

// ============================================
// Feature Settings (Non-Pipeline Features)
// ============================================

// Default feature model configuration (for insights, ideation, roadmap, github, utility)
export const CLAUDE_CODE_DEFAULT_FEATURE_MODELS: FeatureModelConfig = {
  insights: 'claude-sonnet-4-5-20250929',     // Fast, responsive chat
  ideation: 'claude-opus-4-5-20251101',       // Creative ideation benefits from Opus
  roadmap: 'claude-opus-4-5-20251101',        // Strategic planning benefits from Opus
  githubIssues: 'claude-opus-4-5-20251101',   // Issue triage and analysis benefits from Opus
  githubPrs: 'claude-opus-4-5-20251101',      // PR review benefits from thorough Opus analysis
  utility: 'claude-haiku-4-5-20251001'        // Fast utility operations (commit messages, merge resolution)
};

// OpenCode default feature models (using free tier models)
export const OPENCODE_DEFAULT_FEATURE_MODELS: FeatureModelConfig = {
  insights: 'opencode/glm-4.7-free',
  ideation: 'opencode/big-pickle',
  roadmap: 'opencode/big-pickle',
  githubIssues: 'opencode/grok-code',
  githubPrs: 'opencode/grok-code',
  utility: 'opencode/gpt-5-nano'
};

export const DEFAULT_FEATURE_MODELS_BY_BACKEND: Record<string, FeatureModelConfig> = {
  'claude-code': CLAUDE_CODE_DEFAULT_FEATURE_MODELS,
  'opencode': OPENCODE_DEFAULT_FEATURE_MODELS
};

// Default feature thinking configuration
export const DEFAULT_FEATURE_THINKING: FeatureThinkingConfig = {
  insights: 'medium',     // Balanced thinking for chat
  ideation: 'high',       // Deep thinking for creative ideas
  roadmap: 'high',        // Strategic thinking for roadmap
  githubIssues: 'medium', // Moderate thinking for issue analysis
  githubPrs: 'medium',    // Moderate thinking for PR review
  utility: 'low'          // Fast thinking for utility operations
};

// Feature labels for UI display
export const FEATURE_LABELS: Record<keyof FeatureModelConfig, { label: string; description: string }> = {
  insights: { label: 'Insights Chat', description: 'Ask questions about your codebase' },
  ideation: { label: 'Ideation', description: 'Generate feature ideas and improvements' },
  roadmap: { label: 'Roadmap', description: 'Create strategic feature roadmaps' },
  githubIssues: { label: 'GitHub Issues', description: 'Automated issue triage and labeling' },
  githubPrs: { label: 'GitHub PR Review', description: 'AI-powered pull request reviews' },
  utility: { label: 'Utility', description: 'Commit messages and merge conflict resolution' }
};

// Default agent profiles for preset model/thinking configurations
export const CLAUDE_CODE_AGENT_PROFILES: AgentProfile[] = [
  {
    id: 'auto',
    name: 'Auto (Optimized)',
    description: 'Uses Opus across all phases with optimized thinking levels',
    model: 'claude-opus-4-5-20251101',  // Fallback/default model
    thinkingLevel: 'high',
    icon: 'Sparkles',
    isAutoProfile: true,
    phaseModels: CLAUDE_CODE_DEFAULT_PHASE_MODELS,
    phaseThinking: DEFAULT_PHASE_THINKING
  },
  {
    id: 'complex',
    name: 'Complex Tasks',
    description: 'For intricate, multi-step implementations requiring deep analysis',
    model: 'claude-opus-4-5-20251101',
    thinkingLevel: 'ultrathink',
    icon: 'Brain'
  },
  {
    id: 'balanced',
    name: 'Balanced',
    description: 'Good balance of speed and quality for most tasks',
    model: 'claude-sonnet-4-5-20250929',
    thinkingLevel: 'medium',
    icon: 'Scale'
  },
  {
    id: 'quick',
    name: 'Quick Edits',
    description: 'Fast iterations for simple changes and quick fixes',
    model: 'claude-haiku-4-5-20251001',
    thinkingLevel: 'low',
    icon: 'Zap'
  }
];

export const OPENCODE_AGENT_PROFILES: AgentProfile[] = [
  {
    id: 'auto',
    name: 'Auto (Optimized)',
    description: 'Uses optimal models for each phase',
    model: 'opencode/big-pickle',
    thinkingLevel: 'high',
    icon: 'Sparkles',
    isAutoProfile: true,
    phaseModels: OPENCODE_DEFAULT_PHASE_MODELS,
    phaseThinking: DEFAULT_PHASE_THINKING
  },
  {
    id: 'complex',
    name: 'Complex Tasks',
    description: 'Uses larger reasoning models',
    model: 'opencode/big-pickle',
    thinkingLevel: 'ultrathink',
    icon: 'Brain'
  },
  {
    id: 'balanced',
    name: 'Balanced',
    description: 'Balance of speed and intelligence',
    model: 'opencode/glm-4.7-free',
    thinkingLevel: 'medium',
    icon: 'Scale'
  },
  {
    id: 'quick',
    name: 'Quick Edits',
    description: 'Fastest models for simple changes',
    model: 'opencode/minimax-m2.1-free',
    thinkingLevel: 'low',
    icon: 'Zap'
  }
];

export const AGENT_PROFILES_BY_BACKEND: Record<string, AgentProfile[]> = {
  'claude-code': CLAUDE_CODE_AGENT_PROFILES,
  'opencode': OPENCODE_AGENT_PROFILES
};

// ============================================
// Memory Backends
// ============================================

export const MEMORY_BACKENDS = [
  { value: 'file', label: 'File-based (default)' },
  { value: 'graphiti', label: 'Graphiti (LadybugDB)' }
] as const;
