import { useEffect, useState } from 'react';
import { Copy, Download, LoaderCircle } from 'lucide-react';
import { api, downloadText } from '../api';
import type { Definition } from '../types';
import { Modal } from './Dialogs';

type Exported = {
  filename: string;
  script: string;
  nodes: number;
  modules: number;
  requirements: string[];
  commands: string[];
  inputs: Record<string, { path: string; template: boolean }>;
  outputs: Record<string, string>;
  warnings: string[];
  bytes: number;
};

export function PythonExport({
  definition,
  onClose,
}: {
  definition: Definition;
  onClose: () => void;
}) {
  const [result, setResult] = useState<Exported | null>(null);
  const [error, setError] = useState('');
  const [fullSource, setFullSource] = useState(false);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let current = true;
    setResult(null);
    setError('');
    api<Exported>('/api/export/python', 'POST', { definition })
      .then((value) => {
        if (current) setResult(value);
      })
      .catch((exc) => {
        if (current) setError((exc as Error).message);
      });
    return () => {
      current = false;
    };
  }, [definition]);
  const command = 'python exp.py --base-dir "附件根目录" --output-dir output';
  return (
    <Modal title="导出独立 Python 脚本" onClose={onClose} wide>
      <div className="python-export">
        <p className="dialog-description">
          把当前完整流程保存为
          exp.py，包含所需处理源码，无需安装本工具。导出只检查配置，不运行节点；附件单独提供。
        </p>
        {!result && !error && (
          <p role="status">
            <LoaderCircle size={16} className="spin" /> 正在生成脚本…
          </p>
        )}
        {error && (
          <p className="dialog-error" role="alert">
            {error}
          </p>
        )}
        {result && (
          <>
            <div className="export-facts">
              <span>{result.nodes} 个步骤</span>
              <span>Python 3.11+</span>
              <span>{Math.ceil(result.bytes / 1024)} KB · 单文件</span>
            </div>
            <div className="export-command">
              <code>{command}</code>
              <button
                className="icon-button"
                title="复制运行命令"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(command);
                    setCopied(true);
                  } catch {
                    setError('复制失败，请手动选择运行命令');
                  }
                }}
              >
                <Copy size={15} />
              </button>
              {copied && <small role="status">已复制</small>}
            </div>
            <p className="export-hint">
              相对输入路径默认以脚本目录为准；也可用 --input 节点.参数=路径
              单独指定。结果统一放到输出目录，默认不覆盖。
            </p>
            <details className="export-files" open>
              <summary>附件与依赖</summary>
              {Object.entries(result.inputs).length ? (
                <ul>
                  {Object.entries(result.inputs).map(([key, input]) => (
                    <li key={key}>
                      <code>{key}</code>
                      <span>
                        {input.path}
                        {input.template ? '（路径模板）' : ''}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p>未声明文件输入；自定义节点的额外资源请按插件要求提供。</p>
              )}
              <p>
                Python 依赖：
                {result.requirements.length ? result.requirements.join('、') : '内置流程仅需标准库'}
              </p>
              {result.commands.length > 0 && <p>外部程序（PATH）：{result.commands.join('、')}</p>}
              {result.warnings.map((warning) => (
                <p className="export-hint" key={warning}>
                  {warning}
                </p>
              ))}
            </details>
            <div className="export-source-heading">
              <strong>{fullSource ? '完整源码' : '步骤与参数预览'}</strong>
              <label>
                <input
                  type="checkbox"
                  checked={fullSource}
                  onChange={(event) => setFullSource(event.target.checked)}
                />
                显示内嵌处理源码
              </label>
            </div>
            <textarea
              className="flow-json"
              aria-label="Python 脚本预览"
              readOnly
              spellCheck={false}
              value={fullSource ? result.script : result.script.split('# ---- 内嵌处理源码')[0]}
            />
          </>
        )}
      </div>
      {result && (
        <div className="modal-footer python-export-footer">
          <button className="button secondary" onClick={onClose}>
            关闭
          </button>
          <button
            className="button primary"
            onClick={() =>
              downloadText(result.script, result.filename, 'text/x-python;charset=utf-8')
            }
          >
            <Download size={15} />
            下载 exp.py
          </button>
        </div>
      )}
    </Modal>
  );
}
