import { useState } from 'react';
import { ChevronDown, Plus, Puzzle, Search, Upload, X } from 'lucide-react';
import type { FileInfo, Plugin } from '../types';
import { bytes } from '../model.js';
import { PluginIcon } from './PluginIcon';
import { filterPlugins } from '../plugin-manager.js';

type Props = {
  plugins: Plugin[];
  files: FileInfo[];
  onAdd: (plugin: Plugin) => void;
  onUseFile: (file: FileInfo) => void;
  onUpload: () => void;
  uploading: boolean;
  onPlugins: () => void;
};
export function Library({
  plugins,
  files,
  onAdd,
  onUseFile,
  onUpload,
  uploading,
  onPlugins,
}: Props) {
  const [scope, setScope] = useState('common');
  const [tab, setTab] = useState('modules'),
    [search, setSearch] = useState(''),
    [collapsed, setCollapsed] = useState<string[]>([]);
  const groups = [
    '数据输入',
    '字段处理',
    '文本处理',
    '行处理',
    '计算与分类',
    '数据校验',
    '统计分析',
    '多表处理',
    '编码与脱敏',
    '扩展插件',
    '数据输出',
  ];
  const category = (plugin: Plugin) =>
    plugin.category ||
    (plugin.kind === 'input' ? '数据输入' : plugin.kind === 'output' ? '数据输出' : '扩展插件');
  const filtered: Plugin[] = filterPlugins(plugins, search, scope);
  const visibleGroups = [...new Set([...groups, ...filtered.map(category)])];
  return (
    <aside className="library-panel">
      <div className="panel-tabs">
        <button className={tab === 'modules' ? 'active' : ''} onClick={() => setTab('modules')}>
          处理模块 <span>{plugins.length}</span>
        </button>
        <button className={tab === 'files' ? 'active' : ''} onClick={() => setTab('files')}>
          数据文件 <span>{files.length}</span>
        </button>
      </div>
      {tab === 'modules' ? (
        <>
          <label className="search-box">
            <Search size={15} />
            <input
              aria-label="搜索处理模块"
              placeholder="搜索节点名称或功能…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            {search ? (
              <button aria-label="清空模块搜索" onClick={() => setSearch('')}>
                <X size={14} />
              </button>
            ) : (
              <kbd>/</kbd>
            )}
          </label>
          <div className="library-scope">
            <button
              className={scope === 'common' ? 'active' : ''}
              onClick={() => setScope('common')}
            >
              常用
            </button>
            <button className={scope === 'all' ? 'active' : ''} onClick={() => setScope('all')}>
              全部 {plugins.length}
            </button>
            <button title="添加插件" onClick={onPlugins}>
              <Puzzle size={14} />
              添加插件
            </button>
          </div>
          <div className="module-groups">
            {visibleGroups.map((group) => {
              const items = filtered.filter((plugin) => category(plugin) === group);
              if (!items.length) return null;
              return (
                <section className="module-group" key={group}>
                  <button
                    className="group-title"
                    aria-expanded={Boolean(search) || !collapsed.includes(group)}
                    onClick={() =>
                      setCollapsed((value) =>
                        value.includes(group)
                          ? value.filter((item) => item !== group)
                          : [...value, group],
                      )
                    }
                  >
                    <ChevronDown
                      size={13}
                      className={collapsed.includes(group) ? 'collapsed' : ''}
                    />
                    {group}
                    <span>{items.length}</span>
                  </button>
                  {(search || !collapsed.includes(group)) &&
                    items.map((plugin) => (
                      <button
                        className={`module-item module-${plugin.kind}`}
                        key={plugin.id}
                        title={plugin.description}
                        draggable
                        onDragStart={(event) => {
                          event.dataTransfer.setData('application/datasecurity-plugin', plugin.id);
                          event.dataTransfer.effectAllowed = 'copy';
                        }}
                        onClick={() => onAdd(plugin)}
                      >
                        <span className="module-icon">
                          <PluginIcon plugin={plugin} size={17} />
                        </span>
                        <span>{plugin.name}</span>
                        <Plus size={13} className="module-add" />
                      </button>
                    ))}
                </section>
              );
            })}
            {!filtered.length && <div className="empty-small">没有匹配的模块</div>}
          </div>
        </>
      ) : (
        <>
          <button className="upload-button" onClick={onUpload} disabled={uploading}>
            <Upload size={16} />
            {uploading ? '正在导入…' : '导入数据文件'}
          </button>
          <p className="file-hint">
            CSV / XLSX / JSON / JSONL / TXT
            <br />
            文件保存在本机工作区
          </p>
          <div className="file-list">
            {files.map((file) => (
              <button
                key={file.path}
                className="file-card"
                onClick={() => onUseFile(file)}
                title={file.path}
              >
                <span className="file-format">{file.extension.slice(1).toUpperCase()}</span>
                <strong>{file.name.replace(/^[0-9a-f]{12}_/, '')}</strong>
                <span>
                  {bytes(file.size)} ·{' '}
                  {file.columns.length ? `${file.columns.length} 个字段` : '点击添加输入节点'}
                </span>
              </button>
            ))}
            {!files.length && <div className="empty-small">导入第一份数据，开始构建流程</div>}
          </div>
        </>
      )}
      <div className="library-footer">
        <span className="local-dot" />
        本地运行 · 数据不上传到云端
      </div>
    </aside>
  );
}
