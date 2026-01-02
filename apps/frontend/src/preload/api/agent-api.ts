/**
 * Agent API - Aggregates all agent-related API modules
 *
 * This file serves as the main entry point for agent APIs, combining:
 * - Roadmap operations
 * - Ideation operations
 * - Insights operations
 * - Changelog operations
 * - Linear integration
 * - GitHub integration
 * - Auto-build source updates
 * - Shell operations
 */

import { createRoadmapAPI, RoadmapAPI } from './modules/roadmap-api';
import { createIdeationAPI, IdeationAPI } from './modules/ideation-api';
import { createInsightsAPI, InsightsAPI } from './modules/insights-api';
import { createChangelogAPI, ChangelogAPI } from './modules/changelog-api';
import { createLinearAPI, LinearAPI } from './modules/linear-api';
import { createGitHubAPI, GitHubAPI } from './modules/github-api';
import { createGitLabAPI, GitLabAPI } from './modules/gitlab-api';
import { createAutoBuildAPI, AutoBuildAPI } from './modules/autobuild-api';
import { createShellAPI, ShellAPI } from './modules/shell-api';
import { createBackendAPI, BackendAPI } from './modules/backend-api';

/**
 * Combined Agent API interface
 * Includes all operations from individual API modules
 */
export interface AgentAPI extends
  RoadmapAPI,
  IdeationAPI,
  InsightsAPI,
  ChangelogAPI,
  LinearAPI,
  GitHubAPI,
  GitLabAPI,
  AutoBuildAPI,
  ShellAPI,
  BackendAPI {}

/**
 * Creates the complete Agent API by combining all module APIs
 *
 * @returns Complete AgentAPI with all operations available
 */
export const createAgentAPI = (): AgentAPI => {
  const roadmapAPI = createRoadmapAPI();
  const ideationAPI = createIdeationAPI();
  const insightsAPI = createInsightsAPI();
  const changelogAPI = createChangelogAPI();
  const linearAPI = createLinearAPI();
  const githubAPI = createGitHubAPI();
  const gitlabAPI = createGitLabAPI();
  const autobuildAPI = createAutoBuildAPI();
  const shellAPI = createShellAPI();
  const backendAPI = createBackendAPI();

  return {
    ...roadmapAPI,
    ...ideationAPI,
    ...insightsAPI,
    ...changelogAPI,
    ...linearAPI,
    ...githubAPI,
    ...gitlabAPI,
    ...autobuildAPI,
    ...shellAPI,
    ...backendAPI
  };
};

export type {
  RoadmapAPI,
  IdeationAPI,
  InsightsAPI,
  ChangelogAPI,
  LinearAPI,
  GitHubAPI,
  GitLabAPI,
  AutoBuildAPI,
  ShellAPI,
  BackendAPI
};
