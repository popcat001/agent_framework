/**
 * Merged project configuration.
 * Combines framework defaults with project-specific overrides.
 * Overrides come from @project/config — resolved by Vite to either
 * the stub (standalone) or the parent project's web/project-config.ts.
 */
import { projectDefaults } from "./projectDefaults";
// @ts-ignore — resolved by Vite alias
import { projectOverrides } from "@project/config";
import type { ProjectConfig } from "./projectTypes";

const overrides = projectOverrides as Partial<ProjectConfig>;

export const project: ProjectConfig = {
  ...projectDefaults,
  ...overrides,
  theme: { ...projectDefaults.theme, ...(overrides.theme ?? {}) },
  sampleQuestions: overrides.sampleQuestions ?? projectDefaults.sampleQuestions,
};
