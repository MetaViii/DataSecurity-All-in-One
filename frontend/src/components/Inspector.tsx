import { ArrowLeftRight, SlidersHorizontal, Trash2, X } from 'lucide-react';
import type { Edge } from '@xyflow/react';
import type { FileInfo, WorkNode } from '../types';
import { canConnect, portName } from '../model.js';
import { ParameterField } from './Fields';

type Props = {
  node?: WorkNode;
  nodes: WorkNode[];
  edges: Edge[];
  fields: string[];
  files: FileInfo[];
  onLabel: (value: string) => void;
  onConfig: (key: string, value: unknown) => void;
  onConnect: (port: string, endpoint: string) => void;
  onDelete: () => void;
  onPreview: () => void;
  busy?: boolean;
  onClose: () => void;
};
export function Inspector({
  node,
  nodes,
  edges,
  fields,
  files,
  onLabel,
  onConfig,
  onConnect,
  onDelete,
  onPreview,
  busy = false,
  onClose,
}: Props) {
  if (!node)
    return (
      <aside className="inspector-panel">
        <div className="inspector-title">
          <SlidersHorizontal size={16} />
          <strong>节点配置</strong>
        </div>
        <div className="inspector-empty">
          <SlidersHorizontal size={30} strokeWidth={1.3} />
          <strong>选择一个节点</strong>
          <p>
            点击画布中的节点，配置处理参数
            <br />
            或从左侧添加一个新模块
          </p>
        </div>
      </aside>
    );
  const { plugin, config } = node.data;
  const advanced = new Set([
    'encoding',
    'delimiter',
    'skip_blank_lines',
    'line_ending',
    'diagnostics',
    'male_values',
    'female_values',
    'allow_lower_x',
    'region_codes',
    'reference_date',
    'max_rows',
    'check_sequence',
    'check_date',
    'check_region_format',
  ]);
  const extra = plugin.parameters.filter((parameter) => advanced.has(parameter.name));
  return (
    <aside className="inspector-panel">
      <div className="inspector-title">
        <SlidersHorizontal size={16} />
        <strong>节点配置</strong>
        <button className="icon-button danger" title="删除所选节点" onClick={onDelete}>
          <Trash2 size={15} />
        </button>
        <button className="icon-button inspector-close" title="收起节点配置" onClick={onClose}>
          <X size={16} />
        </button>
      </div>
      <div className="inspector-scroll">
        <div className="selected-plugin">
          <span className={`kind-label kind-${plugin.kind}`}>
            {plugin.kind === 'input'
              ? '输入节点'
              : plugin.kind === 'output'
                ? '输出节点'
                : '处理节点'}
          </span>
          <h2>{plugin.name}</h2>
          <p>{plugin.description}</p>
          <code>{plugin.id}</code>
        </div>
        <div className="config-section">
          <label className="section-label" htmlFor="node-label">
            节点名称
          </label>
          <input
            id="node-label"
            value={node.data.label}
            onChange={(event) => onLabel(event.target.value)}
          />
        </div>
        {plugin.inputs.length > 0 && (
          <div className="config-section connections">
            <div className="section-label">
              <ArrowLeftRight size={13} />
              输入连接
            </div>
            {plugin.inputs.map((port) => {
              const current = edges.find(
                (edge) => edge.target === node.id && edge.targetHandle === port,
              );
              return (
                <label key={port}>
                  <span>
                    {portName(port)} <code>{port}</code>
                  </span>
                  <select
                    aria-label={`连接 ${port}`}
                    value={current ? `${current.source}:${current.sourceHandle}` : ''}
                    onChange={(event) => onConnect(port, event.target.value)}
                  >
                    <option value="">选择上游输出…</option>
                    {nodes
                      .filter((item) => item.id !== node.id)
                      .flatMap((item) =>
                        item.data.plugin.outputs
                          .filter((output) =>
                            canConnect(
                              {
                                source: item.id,
                                sourceHandle: output,
                                target: node.id,
                                targetHandle: port,
                              },
                              nodes,
                              edges,
                            ),
                          )
                          .map((output) => (
                            <option value={`${item.id}:${output}`} key={`${item.id}:${output}`}>
                              {item.data.label} · {portName(output)}
                            </option>
                          )),
                      )}
                  </select>
                </label>
              );
            })}
          </div>
        )}
        <div className="config-section">
          <div className="section-label">
            处理参数
            {fields.length > 0 && <span className="field-count">{fields.length} 个可用字段</span>}
          </div>
          {plugin.parameters
            .filter(
              (parameter) =>
                !(plugin.kind === 'output' && parameter.name === 'overwrite') &&
                !advanced.has(parameter.name),
            )
            .map((parameter) => {
              const id = `param-${node.id}-${parameter.name}`;
              if (
                parameter.widget === 'input_file' ||
                (plugin.kind === 'input' && parameter.name === 'path')
              )
                return (
                  <div className="parameter-field" key={id}>
                    <label className="parameter-label" htmlFor={id}>
                      数据文件<span className="required-dot">*</span>
                    </label>
                    <select
                      id={id}
                      value={String(config[parameter.name] || '')}
                      onChange={(event) => {
                        onConfig(parameter.name, event.target.value);
                        const file = files.find((item) => item.path === event.target.value);
                        if (
                          file?.encoding &&
                          plugin.parameters.some((item) => item.name === 'encoding')
                        )
                          onConfig('encoding', file.encoding);
                        if (
                          file?.extension === '.tsv' &&
                          plugin.parameters.some((item) => item.name === 'delimiter')
                        )
                          onConfig('delimiter', '\t');
                      }}
                    >
                      <option value="">选择已导入的文件…</option>
                      {files
                        .filter((file) => file.reader === plugin.id)
                        .map((file) => (
                          <option value={file.path} key={file.path}>
                            {file.name.replace(/^[0-9a-f]{12}_/, '')}
                          </option>
                        ))}
                    </select>
                    <input
                      aria-label="工作区内文件路径"
                      className="quiet-input"
                      placeholder="也可填写工作区内相对路径"
                      value={String(config[parameter.name] || '')}
                      onChange={(event) => onConfig(parameter.name, event.target.value)}
                    />
                  </div>
                );
              return (
                <ParameterField
                  key={id}
                  parameter={parameter}
                  value={config[parameter.name]}
                  onChange={(value) => onConfig(parameter.name, value)}
                  fields={fields}
                  id={id}
                />
              );
            })}
          {extra.length > 0 && (
            <details className="advanced-settings" key={node.id}>
              <summary>更多选项 · {extra.length}</summary>
              {extra.map((parameter) => (
                <ParameterField
                  key={parameter.name}
                  parameter={parameter}
                  value={config[parameter.name]}
                  onChange={(value) => onConfig(parameter.name, value)}
                  fields={fields}
                  id={`param-${node.id}-${parameter.name}`}
                />
              ))}
            </details>
          )}
          {plugin.kind === 'output' && (
            <p className="config-note">填写导出文件名即可。每次运行会创建独立的结果目录。</p>
          )}
        </div>
      </div>
      <div className="inspector-footer">
        <button className="button secondary full" onClick={onPreview} disabled={busy}>
          预览这个节点
        </button>
      </div>
    </aside>
  );
}
