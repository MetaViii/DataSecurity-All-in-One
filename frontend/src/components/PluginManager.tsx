import { useEffect, useRef, useState } from 'react';
import {
  Check,
  ChevronLeft,
  Code2,
  Download,
  FileCode2,
  LoaderCircle,
  Plus,
  Puzzle,
  RefreshCw,
  Upload,
} from 'lucide-react';
import { api } from '../api';
import { bytes } from '../model.js';
import { MAX_PLUGIN_BYTES, pluginDraftError } from '../plugin-manager.js';
import type { PluginFile, PluginManagement, PluginTemplate } from '../types';
import { Modal } from './Dialogs';

type Props = {
  busy: boolean;
  connected: boolean;
  onClose: () => void;
  onUpdate: (result: PluginManagement) => void;
  onDocs: () => void;
};

export function PluginManager({ busy, connected, onClose, onUpdate, onDocs }: Props) {
  const [data, setData] = useState<PluginManagement | null>(null);
  const [page, setPage] = useState<'installed' | 'add'>('installed');
  const [filename, setFilename] = useState('my_plugin.py');
  const [source, setSource] = useState('');
  const [trusted, setTrusted] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [pending, setPending] = useState(false);
  const [viewing, setViewing] = useState<PluginFile | null>(null);
  const [enableFile, setEnableFile] = useState<PluginFile | null>(null);
  const [enableTrusted, setEnableTrusted] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const alive = useRef(true);
  const requestLock = useRef(false);
  const disabled = busy || !connected || pending;
  const draftError = pluginDraftError(filename, source);

  useEffect(() => {
    alive.current = true;
    api<PluginManagement>('/api/plugins/manage')
      .then((result) => {
        if (alive.current) setData(result);
      })
      .catch((exc) => {
        if (alive.current) setError(exc.message);
      });
    return () => {
      alive.current = false;
    };
  }, []);

  const mutate = async (url: string, body: unknown, success: string) => {
    if (requestLock.current || disabled) return false;
    requestLock.current = true;
    setPending(true);
    setError('');
    setMessage('');
    try {
      const result = await api<PluginManagement>(url, 'POST', body);
      // A reload response may contain only registry metadata on older servers.
      const complete = result.files ? result : await api<PluginManagement>('/api/plugins/manage');
      onUpdate(complete);
      if (alive.current) {
        setData(complete);
        setMessage(success);
      }
      return true;
    } catch (exc) {
      if (alive.current) setError((exc as Error).message);
      return false;
    } finally {
      requestLock.current = false;
      if (alive.current) setPending(false);
    }
  };

  const chooseTemplate = (template: PluginTemplate) => {
    setFilename(template.filename);
    setSource(template.source);
    setTrusted(false);
    setMessage('');
    setError('');
    setPage('add');
  };

  const readFile = async (file?: File) => {
    if (!file) return;
    setError('');
    setMessage('');
    try {
      if (!file.name.toLowerCase().endsWith('.py')) throw new Error('请选择 Python .py 源码文件');
      if (file.size > MAX_PLUGIN_BYTES) throw new Error('插件源码最多 256 KiB');
      const content = await file.text();
      if (alive.current) {
        setFilename(file.name);
        setSource(content);
        setTrusted(false);
        setPage('add');
      }
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      if (input.current) input.current.value = '';
    }
  };

  const downloadSource = () => {
    const url = URL.createObjectURL(new Blob([source], { type: 'text/x-python;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = filename || 'my_plugin.py';
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Modal
      title="插件管理"
      onClose={() => {
        if (!pending) onClose();
      }}
      wide
    >
      <div className="plugin-manager">
        <div className="plugin-manager-top">
          <div className="segmented-control" aria-label="插件管理视图">
            <button
              className={page === 'installed' ? 'active' : ''}
              onClick={() => {
                setPage('installed');
                setError('');
              }}
              disabled={pending}
            >
              已安装 <span>{data?.files.length ?? '…'}</span>
            </button>
            <button
              className={page === 'add' ? 'active' : ''}
              onClick={() => {
                setPage('add');
                setViewing(null);
                setEnableFile(null);
                setError('');
              }}
              disabled={pending}
            >
              <Plus size={14} /> 添加插件
            </button>
          </div>
          <button className="text-button" onClick={onDocs} disabled={pending}>
            开发指南 ↗
          </button>
        </div>
        {(busy || !connected) && (
          <p className="manager-notice">
            {busy
              ? '流程运行中，可以查看源码；任务结束后可添加、停用或重新加载插件。'
              : '本地服务未连接，连接恢复后可管理插件。'}
          </p>
        )}
        {error && (
          <div className="manager-feedback error" role="alert">
            {error}
          </div>
        )}
        {message && (
          <div className="manager-feedback success" role="status">
            <Check size={16} />
            {message}
          </div>
        )}
        {page === 'installed' ? (
          <>
            <div className="manager-section-heading">
              <div>
                <strong>本地扩展</strong>
                <p>文件保存在工作区的 plugins 目录。内置节点随程序提供。</p>
              </div>
              <button
                className="button secondary"
                disabled={disabled}
                title="重新执行可信 plugins 目录内的代码并刷新节点库"
                onClick={() => void mutate('/api/plugins/reload', undefined, '已重新加载本地插件')}
              >
                <RefreshCw size={14} className={pending ? 'spin' : ''} />
                重新加载
              </button>
            </div>
            {!data && !error && (
              <div className="manager-empty">
                <LoaderCircle size={20} className="spin" />
                正在读取插件…
              </div>
            )}
            {data && !data.files.length && (
              <div className="manager-empty">
                <Puzzle size={28} />
                <strong>还没有本地插件</strong>
                <p>导入一个 .py 文件，或从模板开始编写。</p>
                <button className="button primary" onClick={() => setPage('add')}>
                  <Plus size={15} />
                  添加第一个插件
                </button>
              </div>
            )}
            <div className="installed-plugins">
              {data?.files.map((file) => (
                <div
                  className={`installed-plugin ${file.error ? 'has-error' : ''}`}
                  key={file.filename}
                >
                  <div className="installed-plugin-main">
                    <span className="plugin-file-icon">
                      <FileCode2 size={22} />
                    </span>
                    <div>
                      <strong>{file.filename}</strong>
                      <span>
                        {file.plugin_ids.length ? file.plugin_ids.join(' · ') : '尚无已加载节点'} ·{' '}
                        {bytes(file.size)}
                      </span>
                    </div>
                    <span
                      className={`plugin-state ${file.error ? 'error' : file.enabled ? 'enabled' : ''}`}
                    >
                      {file.error ? '加载失败' : file.enabled ? '已启用' : '已停用'}
                    </span>
                  </div>
                  {file.error && <pre className="plugin-file-error">{file.error}</pre>}
                  <div className="installed-plugin-actions">
                    <button
                      className="text-button"
                      disabled={file.source === undefined}
                      onClick={() => {
                        setViewing(viewing?.filename === file.filename ? null : file);
                        setEnableFile(null);
                      }}
                    >
                      <Code2 size={14} />
                      {viewing?.filename === file.filename ? '收起源码' : '查看源码'}
                    </button>
                    <button
                      className="text-button"
                      disabled={disabled}
                      onClick={() => {
                        if (file.enabled)
                          void mutate(
                            '/api/plugins/toggle',
                            { filename: file.filename, enabled: false },
                            `已停用 ${file.filename}，文件仍保留`,
                          );
                        else {
                          setEnableFile(file);
                          setEnableTrusted(false);
                          setViewing(file);
                        }
                      }}
                    >
                      {file.enabled ? '停用' : '启用'}
                    </button>
                  </div>
                  {viewing?.filename === file.filename && (
                    <pre className="plugin-source-preview">
                      <code>{file.source}</code>
                    </pre>
                  )}
                  {enableFile?.filename === file.filename && (
                    <div className="enable-plugin-confirm">
                      <p>启用会立即执行此 Python 文件，插件具有当前 Python 进程的完整权限。</p>
                      <label className="trust-checkbox">
                        <input
                          type="checkbox"
                          checked={enableTrusted}
                          onChange={(event) => setEnableTrusted(event.target.checked)}
                        />
                        我已查看源码，并信任此插件
                      </label>
                      <div>
                        <button
                          className="button secondary"
                          disabled={pending}
                          onClick={() => setEnableFile(null)}
                        >
                          取消
                        </button>
                        <button
                          className="button primary"
                          disabled={disabled || !enableTrusted}
                          onClick={async () => {
                            if (
                              await mutate(
                                '/api/plugins/toggle',
                                { filename: file.filename, enabled: true, trusted: true },
                                `已启用 ${file.filename}`,
                              )
                            )
                              setEnableFile(null);
                          }}
                        >
                          确认启用
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
            {Boolean(data?.plugin_errors.length) && (
              <details className="manager-errors">
                <summary>加载诊断 · {data?.plugin_errors.length}</summary>
                {data?.plugin_errors.map((item, index) => (
                  <pre key={index}>{item}</pre>
                ))}
              </details>
            )}
          </>
        ) : (
          <>
            <div className="plugin-add-choices">
              <button
                className="plugin-choice import"
                disabled={pending}
                onClick={() => input.current?.click()}
              >
                <Upload size={21} />
                <strong>导入 Python 文件</strong>
                <span>选择 .py 源码，先查看再安装</span>
              </button>
              {data?.templates.map((template) => (
                <button
                  className="plugin-choice"
                  key={template.id}
                  disabled={pending}
                  onClick={() => chooseTemplate(template)}
                >
                  <FileCode2 size={21} />
                  <strong>{template.name}</strong>
                  <span>{template.description}</span>
                </button>
              ))}
            </div>
            <div className="plugin-editor-heading">
              <label htmlFor="plugin-filename">插件文件名</label>
              <span>新增文件，不覆盖已安装插件</span>
            </div>
            <input
              id="plugin-filename"
              value={filename}
              disabled={pending}
              onChange={(event) => {
                setFilename(event.target.value);
                setTrusted(false);
              }}
              placeholder="my_plugin.py"
              autoComplete="off"
              spellCheck={false}
            />
            <div className="plugin-editor-heading">
              <label htmlFor="plugin-source">Python 源码</label>
              <span>{bytes(new TextEncoder().encode(source).byteLength)} / 256 KiB</span>
            </div>
            <textarea
              id="plugin-source"
              className="plugin-source-editor"
              value={source}
              disabled={pending}
              onChange={(event) => {
                setSource(event.target.value);
                setTrusted(false);
              }}
              placeholder="从上方选择模板，或在这里粘贴插件源码…"
              spellCheck={false}
            />
            <div className="plugin-trust">
              <p>
                安装时会执行 Python 代码，插件可以读写本机文件，具有当前 Python
                进程的完整权限。请只添加自己编写或已审阅的代码。
              </p>
              <label className="trust-checkbox">
                <input
                  type="checkbox"
                  checked={trusted}
                  disabled={pending}
                  onChange={(event) => setTrusted(event.target.checked)}
                />
                我已查看源码，并信任此插件
              </label>
            </div>
            {draftError && <p className="plugin-draft-hint">{draftError}</p>}
            <div className="plugin-install-footer">
              <button
                className="button subtle"
                disabled={pending}
                onClick={() => setPage('installed')}
              >
                <ChevronLeft size={15} />
                返回列表
              </button>
              <span />
              <button
                className="button secondary"
                disabled={!source.trim() || pending}
                onClick={downloadSource}
              >
                <Download size={14} />
                下载源码
              </button>
              <button
                className="button primary"
                disabled={disabled || !trusted || Boolean(draftError)}
                onClick={async () => {
                  if (
                    await mutate(
                      '/api/plugins/install',
                      { filename: filename.trim(), source, trusted: true },
                      `已安装 ${filename.trim()}，节点库已更新`,
                    )
                  ) {
                    setPage('installed');
                    setTrusted(false);
                    setSource('');
                  }
                }}
              >
                {pending ? <LoaderCircle size={15} className="spin" /> : <Plus size={15} />}
                安装并加载
              </button>
            </div>
          </>
        )}
      </div>
      <input
        type="file"
        accept=".py"
        ref={input}
        hidden
        onChange={(event) => void readFile(event.target.files?.[0])}
      />
    </Modal>
  );
}
