import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Check, CircleAlert, LoaderCircle } from 'lucide-react';
import type { WorkNode } from '../types';
import { portName } from '../model.js';
import { PluginIcon } from './PluginIcon';

export function PluginNode({ data, selected }: NodeProps<WorkNode>) {
  const plugin = data.plugin;
  return (
    <div
      className={`flow-card kind-${plugin.kind} ${selected ? 'selected' : ''} ${data.unknown ? 'unknown' : ''} status-${data.status || 'idle'}`}
    >
      <div className="flow-card-head">
        <span className="node-symbol">
          <PluginIcon plugin={plugin} size={18} />
        </span>
        <span className="node-kind">
          {plugin.kind === 'input'
            ? '数据输入'
            : plugin.kind === 'output'
              ? '数据输出'
              : plugin.category || '数据处理'}
        </span>
        {data.status === 'running' ? (
          <LoaderCircle className="spin" size={14} />
        ) : data.status === 'error' ? (
          <CircleAlert size={14} />
        ) : data.status === 'ok' || data.status === 'preview_only' ? (
          <Check size={14} className="success-icon" />
        ) : (
          <span className="idle-dot" />
        )}
      </div>
      <strong>{data.label}</strong>
      <div className="node-caption">
        {data.unknown
          ? '插件未加载'
          : data.portCounts?.data !== undefined
            ? `${data.portCounts.data.toLocaleString()} 行数据`
            : data.portCounts && Object.keys(data.portCounts).length > 1
              ? `${Object.keys(data.portCounts).length} 个输出分支`
              : data.count !== undefined
                ? `${data.count.toLocaleString()} 行${plugin.kind === 'output' ? '输入' : '结果'}`
                : '等待运行'}
      </div>
      <div className="node-ports">
        <div>
          {plugin.inputs.map((port) => (
            <div className="port-row input-port" key={port}>
              <Handle id={port} type="target" position={Position.Left} />
              <span>{portName(port)}</span>
            </div>
          ))}
        </div>
        <div>
          {plugin.outputs.map((port) => (
            <div className={`port-row output-port port-${port}`} key={port}>
              <span>
                {portName(port)}
                {data.portCounts?.[port] !== undefined && (
                  <em>{data.portCounts[port].toLocaleString()}</em>
                )}
              </span>
              <Handle id={port} type="source" position={Position.Right} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
