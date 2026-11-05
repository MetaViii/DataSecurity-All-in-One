import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  BookOpen,
  Braces,
  Copy,
  Download,
  FilePlus2,
  FolderOpen,
  Plus,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { api, downloadJSON } from '../api';
import type { DataRow, Definition, Project, Template } from '../types';
import { Markdown } from './Markdown';

export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const panel = useRef<HTMLElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const selectors =
      'button:not(:disabled),input:not([type="hidden"]):not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex="0"]';
    const focusable = () =>
      Array.from(panel.current?.querySelectorAll<HTMLElement>(selectors) || []).filter(
        (element) => element.getClientRects().length > 0,
      );
    const initial = panel.current?.querySelector<HTMLElement>('[data-autofocus]') || focusable()[0];
    initial?.focus();
    const handler = (event: KeyboardEvent) => {
      if (Array.from(document.querySelectorAll('[role="dialog"]')).at(-1) !== panel.current) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        close.current();
      }
      if (event.key === 'Tab') {
        const elements = focusable(),
          first = elements[0],
          last = elements.at(-1);
        if (
          event.shiftKey &&
          (document.activeElement === first || !panel.current?.contains(document.activeElement))
        ) {
          event.preventDefault();
          last?.focus();
        } else if (
          !event.shiftKey &&
          (document.activeElement === last || !panel.current?.contains(document.activeElement))
        ) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => {
      window.removeEventListener('keydown', handler);
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`modal ${wide ? 'wide' : ''}`}
      >
        <div className="modal-heading">
          <h2>{title}</h2>
          <button className="icon-button" title="关闭" aria-label="关闭对话框" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

export function ProjectsDialog({
  projects,
  templates,
  onClose,
  onNew,
  onLoad,
  onTemplate,
  onImport,
  onDelete,
}: {
  projects: Project[];
  templates: Template[];
  onClose: () => void;
  onNew: () => void;
  onLoad: (project: Project) => void;
  onTemplate: (template: Template) => void;
  onImport: () => void;
  onDelete: (project: Project) => void;
}) {
  return (
    <Modal title="我的流程" onClose={onClose} wide>
      <div className="project-dialog-body">
        <div className="project-actions">
          <button className="new-project-card" onClick={onNew}>
            <Plus size={25} />
            <strong>空白流程</strong>
            <span>从一个输入节点开始</span>
          </button>
          {templates.map((template) => (
            <button
              className="new-project-card template"
              key={template.id}
              onClick={() => onTemplate(template)}
            >
              <Braces size={23} />
              <strong>{template.name}</strong>
              <span>{template.description}</span>
            </button>
          ))}
        </div>
        <div className="dialog-subheading">
          <h3>
            已保存的流程 <span>{projects.length}</span>
          </h3>
          <button className="text-button" onClick={onImport}>
            <Upload size={14} />
            导入 JSON
          </button>
        </div>
        {projects.length ? (
          <div className="saved-projects">
            {projects.map((project) => (
              <div className="saved-project" key={project.id}>
                <button className="project-open" onClick={() => onLoad(project)}>
                  <FolderOpen size={20} />
                  <div>
                    <strong>{project.name}</strong>
                    <span>
                      更新于{' '}
                      {new Date(project.updated_at).toLocaleString('zh-CN', { hour12: false })} ·
                      版本 {project.revision}
                    </span>
                  </div>
                </button>
                <button
                  className="icon-button danger"
                  title={`删除 ${project.name}`}
                  onClick={() => onDelete(project)}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="projects-empty">
            <FilePlus2 size={28} />
            <p>还没有保存的流程。编辑完成后点击顶部“保存”。</p>
          </div>
        )}
      </div>
    </Modal>
  );
}

export function FlowDialog({
  definition,
  onClose,
  onApply,
}: {
  definition: Definition;
  onClose: () => void;
  onApply: (definition: Definition) => void;
}) {
  const [draft, setDraft] = useState(JSON.stringify(definition, null, 2)),
    [error, setError] = useState('');
  return (
    <Modal title="流程 JSON" onClose={onClose} wide>
      <p className="dialog-description">
        节点配置和画布布局都保存在这份文件中，也可以通过命令行执行。
      </p>
      <textarea
        className="flow-json"
        aria-label="流程 JSON 内容"
        spellCheck={false}
        value={draft}
        onChange={(event) => {
          setDraft(event.target.value);
          setError('');
        }}
      />
      {error && <p className="dialog-error">{error}</p>}
      <div className="modal-footer">
        <button
          className="button secondary"
          onClick={() => downloadJSON(JSON.parse(draft), `${definition.name || 'flow'}.json`)}
          disabled={(() => {
            try {
              JSON.parse(draft);
              return false;
            } catch {
              return true;
            }
          })()}
        >
          <Download size={14} />
          导出 JSON
        </button>
        <button
          className="button primary"
          onClick={() => {
            try {
              onApply(JSON.parse(draft));
            } catch (exc) {
              setError((exc as Error).message);
            }
          }}
        >
          应用配置
        </button>
      </div>
    </Modal>
  );
}

export function RecordDialog({
  record,
  onClose,
  onCopy,
}: {
  record: DataRow;
  onClose: () => void;
  onCopy: (value: string) => void;
}) {
  const [tab, setTab] = useState('values');
  return (
    <Modal title="记录详情" onClose={onClose} wide>
      <div className="record-tabs">
        {[
          ['values', '字段值'],
          ['origins', `数据来源 ${record.origins.length}`],
          ['issues', `问题 ${record.issues.length}`],
          ['changes', `修改 ${record.changes.length}`],
        ].map(([key, label]) => (
          <button className={tab === key ? 'active' : ''} key={key} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>
      <div className="record-body">
        {tab === 'values' ? (
          <dl className="record-values">
            {Object.entries(record.values).map(([field, value]) => (
              <div key={field}>
                <dt>{field}</dt>
                <dd>
                  <pre>{value || '（空字符串）'}</pre>
                  <button className="icon-button" title="复制单元格" onClick={() => onCopy(value)}>
                    <Copy size={13} />
                  </button>
                </dd>
              </div>
            ))}
          </dl>
        ) : tab === 'origins' ? (
          record.origins.map((origin, index) => (
            <div className="trace-card" key={index}>
              <strong>
                源记录 {origin.record}
                {origin.line !== null && ` · 起始行 ${origin.line}`}
              </strong>
              <code>{origin.source}</code>
            </div>
          ))
        ) : tab === 'issues' ? (
          record.issues.length ? (
            record.issues.map((issue, index) => (
              <div className="trace-card issue" key={index}>
                <strong>
                  {issue.field} · {issue.node}
                </strong>
                <p>{issue.message}</p>
              </div>
            ))
          ) : (
            <div className="empty-small">这条记录没有附加问题</div>
          )
        ) : record.changes.length ? (
          record.changes.map((change, index) => (
            <div className="trace-card" key={index}>
              <strong>
                {change.field} <span className="change-pill">{change.operation || 'update'}</span>
                <small>{change.node}</small>
              </strong>
              <div className="change-values">
                <pre>{change.before || '（空）'}</pre>
                <span>→</span>
                <pre>{change.after || '（空）'}</pre>
              </div>
              <p>{change.reason}</p>
            </div>
          ))
        ) : (
          <div className="empty-small">这条记录没有字段修改历史</div>
        )}
      </div>
      <div className="modal-footer">
        <button className="button secondary" onClick={() => downloadJSON(record, 'record.json')}>
          <Download size={14} />
          导出这条记录
        </button>
      </div>
    </Modal>
  );
}

export function DocsDialog({ onClose }: { onClose: () => void }) {
  const [document, setDocument] = useState('code-tour'),
    [content, setContent] = useState('正在读取…');
  useEffect(() => {
    let current = true;
    setContent('正在读取…');
    fetch(`/api/docs/${document}`)
      .then((response) => {
        if (!response.ok) throw new Error('文档暂不可用');
        return response.text();
      })
      .then((text) => {
        if (current) setContent(text);
      })
      .catch((error) => {
        if (current) setContent(error.message);
      });
    return () => {
      current = false;
    };
  }, [document]);
  return (
    <Modal title="使用与代码阅读指南" onClose={onClose} wide>
      <div className="docs-layout">
        <nav>
          {[
            ['code-tour', '代码导读'],
            ['workbench', '解题工作流'],
            ['recipes', '赛题演练'],
            ['real-ctf', '完整原题实测'],
            ['contest-round2', '浙江与羊城杯原附件'],
            ['correction', '纠错与正确率'],
            ['nodes', '节点手册'],
            ['advanced-nodes', '新增节点'],
            ['plugins', '开发插件'],
            ['plugin-manager', '插件管理'],
            ['architecture', '架构与边界'],
          ].map(([key, name]) => (
            <button
              className={document === key ? 'active' : ''}
              key={key}
              onClick={() => setDocument(key)}
            >
              <BookOpen size={14} />
              {name}
            </button>
          ))}
        </nav>
        <article className="markdown">
          <Markdown content={content} onNavigate={setDocument} />
        </article>
      </div>
    </Modal>
  );
}
