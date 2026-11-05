import type { Node } from '@xyflow/react';

export type Parameter = {
  name: string;
  type: string;
  description: string;
  required: boolean;
  default?: unknown;
  choices?: unknown[];
  widget?: string;
};
export type Plugin = {
  id: string;
  name: string;
  kind: 'input' | 'transform' | 'output';
  description: string;
  version: string;
  category: string;
  inputs: string[];
  outputs: string[];
  parameters: Parameter[];
};
export type PluginFile = {
  filename: string;
  enabled: boolean;
  plugin_ids: string[];
  error?: string;
  size: number;
  source?: string;
};
export type PluginTemplate = {
  id: string;
  name: string;
  description: string;
  filename: string;
  source: string;
};
export type PluginManagement = {
  files: PluginFile[];
  templates: PluginTemplate[];
  plugins: Plugin[];
  plugin_errors: string[];
};
export type NodeData = {
  plugin: Plugin;
  config: Record<string, unknown>;
  label: string;
  unknown?: boolean;
  status?: string;
  count?: number;
  portCounts?: Record<string, number>;
};
export type WorkNode = Node<NodeData, 'plugin'>;
export type FlowNode = {
  id: string;
  plugin: string;
  config: Record<string, unknown>;
  inputs: Record<string, string>;
};
export type Definition = {
  version: 1;
  name?: string;
  description?: string;
  plugin_dirs?: string[];
  nodes: FlowNode[];
  ui?: { positions?: Record<string, { x: number; y: number }>; labels?: Record<string, string> };
};
export type FileInfo = {
  name: string;
  path: string;
  size: number;
  extension: string;
  reader: string;
  columns: string[];
  encoding?: string;
  sheets?: string[];
  note?: string;
};
export type Project = {
  id: string;
  name: string;
  revision: number;
  updated_at: string;
  definition?: Definition;
};
export type Template = { id: string; name: string; description: string; definition: Definition };
export type Bootstrap = {
  token: string;
  version: string;
  workspace: string;
  plugins: Plugin[];
  plugin_errors: string[];
  files: FileInfo[];
  projects: Project[];
  templates: Template[];
};
export type Step = {
  id: string;
  plugin: string;
  status: string;
  inputs: Record<string, number>;
  outputs: Record<string, number>;
  seconds: number;
};
export type Job = {
  id: string;
  status: 'queued' | 'running' | 'success' | 'error' | 'cancelled';
  preview: boolean;
  target: string | null;
  created_at: string;
  current_node: string | null;
  completed: number;
  total: number;
  steps: Step[];
  error: string | null;
  error_node: string | null;
  nodes: { id: string; ports: Record<string, { rows: number; columns: string[] }> }[];
  artifacts: { name: string; size: number; url: string }[];
};
export type DataRow = {
  values: Record<string, string>;
  origins: { source: string; record: number; line: number | null }[];
  issues: { node: string; field: string; message: string }[];
  changes: {
    node: string;
    field: string;
    before: string;
    after: string;
    reason: string;
    operation: string;
  }[];
};
export type Preview = {
  columns: string[];
  row_count: number;
  filtered_count: number;
  page: number;
  page_size: number;
  pages: number;
  rows: DataRow[];
};
