import { useState } from 'react';
import {
  ArrowRight,
  BookOpen,
  Braces,
  Database,
  FilePlus2,
  FolderOpen,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
  Upload,
  Workflow,
} from 'lucide-react';
import type { FileInfo, Project, Template } from '../types';
import { bytes } from '../model.js';

type Props = {
  projects: Project[];
  templates: Template[];
  files: FileInfo[];
  pluginCount: number;
  currentName: string;
  hasCurrent: boolean;
  dirty: boolean;
  uploading: boolean;
  onContinue: () => void;
  onNew: () => void;
  onImport: () => void;
  onUpload: () => void;
  onTemplate: (template: Template) => void;
  onLoad: (project: Project) => void;
  onDelete: (project: Project) => void;
  onFile: (file: FileInfo) => void;
  onDocs: () => void;
};

export function WorkspaceHome(props: Props) {
  const [search, setSearch] = useState('');
  const [templateSearch, setTemplateSearch] = useState('');
  const matches = props.projects.filter((project) =>
    project.name.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
  );
  return (
    <main className="workspace-home">
      <div className="home-content">
        <div className="home-heading">
          <div>
            <span className="eyebrow">
              <span className="local-dot" />
              本地工作区
            </span>
            <h1>开始一条数据处理流程</h1>
            <p>导入附件，组合处理节点，检查每一步的结果。</p>
          </div>
          <div className="home-actions">
            <button className="button secondary" onClick={props.onImport}>
              <Upload size={16} />
              导入流程
            </button>
            <button className="button primary" onClick={props.onNew}>
              <Plus size={17} />
              新建流程
            </button>
          </div>
        </div>
        {props.hasCurrent && (
          <button className="continue-card" onClick={props.onContinue}>
            <span className="home-icon">
              <Workflow size={22} />
            </span>
            <div>
              <span>继续编辑{props.dirty ? ' · 有未保存的修改' : ''}</span>
              <strong>{props.currentName}</strong>
            </div>
            <span className="continue-action">
              打开画布
              <ArrowRight size={17} />
            </span>
          </button>
        )}
        <section className="home-section">
          <div className="home-section-title">
            <div>
              <h2>从示例开始</h2>
              <p>从小样本演练入门，或打开公开原附件流程。</p>
            </div>
            <label className="home-search">
              <Search size={15} />
              <input
                aria-label="搜索示例"
                placeholder="搜索场景或能力…"
                value={templateSearch}
                onChange={(event) => setTemplateSearch(event.target.value)}
              />
            </label>
          </div>
          <div className="template-grid">
            <button className="home-template blank" onClick={props.onNew}>
              <span className="template-icon">
                <FilePlus2 size={23} />
              </span>
              <strong>空白流程</strong>
              <p>从自己的数据和规则开始。</p>
              <span className="template-footer">
                自由组合节点
                <Plus size={16} />
              </span>
            </button>
            {props.templates
              .filter((template) =>
                `${template.name} ${template.description}`
                  .toLowerCase()
                  .includes(templateSearch.toLowerCase()),
              )
              .map((template, index) => (
                <button
                  className={`home-template template-${index}`}
                  key={template.id}
                  onClick={() => props.onTemplate(template)}
                >
                  <span className="template-icon">
                    {index ? <Braces size={23} /> : <ShieldCheck size={23} />}
                  </span>
                  <strong>{template.name}</strong>
                  <p>{template.description}</p>
                  <span className="template-footer">
                    {template.definition.nodes.length} 个节点 ·{' '}
                    {template.id.startsWith('ctf_real_') ? '公开原附件' : '含演示数据'}
                    <ArrowRight size={16} />
                  </span>
                </button>
              ))}
          </div>
        </section>
        <div className="home-columns">
          <section className="home-section home-projects">
            <div className="home-section-title">
              <div>
                <h2>
                  我的流程 <span>{props.projects.length}</span>
                </h2>
                <p>已保存的流程保留在当前工作区。</p>
              </div>
              <label className="home-search">
                <Search size={15} />
                <input
                  aria-label="搜索已保存流程"
                  placeholder="搜索流程…"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </label>
            </div>
            {matches.length ? (
              <div className="home-project-list">
                {matches.map((project) => (
                  <div className="home-project-row" key={project.id}>
                    <button onClick={() => props.onLoad(project)}>
                      <span className="project-folder">
                        <FolderOpen size={20} />
                      </span>
                      <div>
                        <strong>{project.name}</strong>
                        <span>
                          更新于{' '}
                          {new Date(project.updated_at).toLocaleString('zh-CN', {
                            month: '2-digit',
                            day: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit',
                            hour12: false,
                          })}{' '}
                          · 修订 {project.revision}
                        </span>
                      </div>
                      <ArrowRight size={16} />
                    </button>
                    <button
                      className="icon-button danger"
                      title={`删除 ${project.name}`}
                      onClick={() => props.onDelete(project)}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="home-empty">
                <FolderOpen size={28} />
                <strong>{search ? '没有找到匹配的流程' : '还没有保存的流程'}</strong>
                <p>{search ? '试试其他名称。' : '从示例或空白流程开始，编辑后保存到这里。'}</p>
              </div>
            )}
          </section>
          <section className="home-section home-files">
            <div className="home-section-title">
              <div>
                <h2>
                  数据文件 <span>{props.files.length}</span>
                </h2>
                <p>选择文件，创建一条输入流程。</p>
              </div>
              <button
                className="icon-button"
                title="导入数据文件"
                onClick={props.onUpload}
                disabled={props.uploading}
              >
                <Upload size={17} />
              </button>
            </div>
            <div className="home-file-list">
              {props.files.slice(-5).map((file) => (
                <button key={file.path} title={file.path} onClick={() => props.onFile(file)}>
                  <span className={`file-type type-${file.extension.slice(1)}`}>
                    {file.extension.slice(1).toUpperCase()}
                  </span>
                  <div>
                    <strong>{file.name.replace(/^[0-9a-f]{12}_/, '')}</strong>
                    <span>
                      {bytes(file.size)}
                      {file.columns.length ? ` · ${file.columns.length} 个字段` : ''}
                      {file.path.startsWith('examples/') ? ' · 示例' : ''}
                    </span>
                  </div>
                  <ArrowRight size={15} />
                </button>
              ))}
            </div>
            <button
              className="file-import-link"
              onClick={props.onUpload}
              disabled={props.uploading}
            >
              <Plus size={15} />
              {props.uploading ? '正在导入…' : '导入新的数据文件'}
            </button>
          </section>
        </div>
        <div className="home-guide">
          <span>
            <Database size={16} />
            文件在本机处理，流程可以重复执行。
          </span>
          <button onClick={props.onDocs}>
            <BookOpen size={16} />
            查看使用指南
            <ArrowRight size={14} />
          </button>
        </div>
      </div>
    </main>
  );
}
