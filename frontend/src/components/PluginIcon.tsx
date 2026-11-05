import {
  Binary,
  Braces,
  Calculator,
  ChartNoAxesCombined,
  Columns3,
  Database,
  FileOutput,
  GitMerge,
  ListFilter,
  Puzzle,
  ShieldCheck,
  Type,
} from 'lucide-react';
import type { Plugin } from '../types';

export function PluginIcon({ plugin, size = 17 }: { plugin: Plugin; size?: number }) {
  const icons: Record<string, typeof Braces> = {
    字段处理: Columns3,
    文本处理: Type,
    行处理: ListFilter,
    计算与分类: Calculator,
    数据校验: ShieldCheck,
    统计分析: ChartNoAxesCombined,
    多表处理: GitMerge,
    编码与脱敏: Binary,
  };
  const Icon =
    plugin.kind === 'input'
      ? Database
      : plugin.kind === 'output'
        ? FileOutput
        : icons[plugin.category] || Puzzle;
  return <Icon size={size} strokeWidth={1.7} />;
}
