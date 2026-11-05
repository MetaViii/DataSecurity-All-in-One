import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  ArrowDownToLine,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  FileCheck2,
  History,
  LoaderCircle,
  Search,
  Table2,
} from 'lucide-react';
import { api } from '../api';
import { bytes, portName } from '../model.js';
import type { DataRow, Job, Preview, WorkNode } from '../types';
import { ScoreSummary } from './ScoreSummary';

type Props = {
  job: Job | null;
  nodes: WorkNode[];
  selected: string | null;
  history: Job[];
  stale: boolean;
  onSelectJob: (job: Job) => void;
  onRecord: (row: DataRow) => void;
  onPreview: () => void;
  busy?: boolean;
};
const statusName: Record<string, string> = {
  queued: '排队中',
  running: '处理中',
  success: '完成',
  error: '失败',
  cancelled: '已取消',
};

export function Results({
  job,
  nodes,
  selected,
  history,
  stale,
  onSelectJob,
  onRecord,
  onPreview,
  busy = false,
}: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [height, setHeight] = useState(() => {
    try {
      return Math.min(
        window.innerHeight * 0.58,
        Math.max(
          200,
          Number(localStorage.getItem('datasecurity:preview-height')) ||
            Math.min(310, window.innerHeight * 0.36),
        ),
      );
    } catch {
      return 310;
    }
  });
  const drag = useRef<{ y: number; height: number } | null>(null);
  useEffect(() => {
    setCollapsed(false);
  }, [job?.id]);
  const [tab, setTab] = useState('data'),
    [view, setView] = useState('output'),
    [port, setPort] = useState('data');
  const [page, setPage] = useState(1),
    [pageSize, setPageSize] = useState(50),
    [search, setSearch] = useState(''),
    [query, setQuery] = useState('');
  const [data, setData] = useState<Preview | null>(null),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(false);
  const [fallback, setFallback] = useState('');
  const selectedNode = nodes.find((node) => node.id === selected);
  const node =
    selectedNode ||
    nodes.find((item) => item.id === fallback) ||
    nodes.find((item) => item.data.plugin.kind === 'output') ||
    nodes.at(-1);
  const ports = node ? (view === 'input' ? node.data.plugin.inputs : node.data.plugin.outputs) : [];
  const activePort = ports.includes(port) ? port : ports[0] || '';
  const canShow = useMemo(() => {
    if (!job || !node || !activePort) return false;
    if (view === 'output')
      return Boolean(job.nodes.find((item) => item.id === node.id)?.ports[activePort]);
    return job.status !== 'running' && job.status !== 'queued';
  }, [job, node, activePort, view]);
  useEffect(() => {
    if (node) {
      setView(node.data.plugin.outputs.length ? 'output' : 'input');
      setPage(1);
      setSearch('');
    }
  }, [node?.id, job?.id]);
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search);
      setPage(1);
    }, 250);
    return () => clearTimeout(timer);
  }, [search]);
  useEffect(() => {
    let active = true;
    setError('');
    setData(null);
    if (!canShow || !job || !node) {
      setLoading(false);
      return;
    }
    const parameters = new URLSearchParams({
      node: node.id,
      port: activePort,
      view,
      page: String(page),
      page_size: String(pageSize),
      q: query,
    });
    setLoading(true);
    api<Preview>(`/api/runs/${job.id}/table?${parameters}`)
      .then((result) => {
        if (active) setData(result);
      })
      .catch((exc) => {
        if (active) setError(exc.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [job?.id, job?.status, node?.id, activePort, view, page, pageSize, query, canShow]);
  return (
    <section
      className={`results-panel ${collapsed ? 'is-collapsed' : ''}`}
      style={{ height: collapsed ? 46 : `clamp(180px, ${height}px, 58vh)` }}
    >
      {!collapsed && (
        <div
          className="preview-resizer"
          role="separator"
          aria-label="调整预览区高度"
          aria-orientation="horizontal"
          aria-valuenow={Math.round(height)}
          aria-valuemin={180}
          aria-valuemax={Math.round(window.innerHeight * 0.58)}
          tabIndex={0}
          onPointerDown={(event) => {
            drag.current = { y: event.clientY, height };
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={(event) => {
            if (drag.current)
              setHeight(
                Math.min(
                  window.innerHeight * 0.58,
                  Math.max(180, drag.current.height + drag.current.y - event.clientY),
                ),
              );
          }}
          onPointerUp={() => {
            drag.current = null;
            try {
              localStorage.setItem('datasecurity:preview-height', String(height));
            } catch {}
          }}
          onPointerCancel={() => {
            drag.current = null;
          }}
          onKeyDown={(event) => {
            if (['ArrowUp', 'ArrowDown'].includes(event.key)) {
              event.preventDefault();
              setHeight((value) =>
                Math.min(
                  window.innerHeight * 0.58,
                  Math.max(180, value + (event.key === 'ArrowUp' ? 24 : -24)),
                ),
              );
            }
          }}
        >
          <span />
        </div>
      )}
      <div className="results-heading">
        <div className="result-tabs">
          <button
            className={tab === 'data' ? 'active' : ''}
            onClick={() => {
              setTab('data');
              setCollapsed(false);
            }}
          >
            <Table2 size={14} />
            数据预览
          </button>
          <button
            className={tab === 'history' ? 'active' : ''}
            onClick={() => {
              setTab('history');
              setCollapsed(false);
            }}
          >
            <History size={14} />
            运行记录<span>{history.length}</span>
          </button>
          <button
            className={tab === 'exports' ? 'active' : ''}
            onClick={() => {
              setTab('exports');
              setCollapsed(false);
            }}
          >
            <ArrowDownToLine size={14} />
            导出结果{Boolean(job?.artifacts.length) && <span>{job?.artifacts.length}</span>}
          </button>
        </div>
        <div className="result-context">
          {stale && job && <span className="stale-badge">配置已修改 · 结果来自上次运行</span>}
          {node && <span className="selected-name">{node.data.label}</span>}
        </div>
        <button
          className="icon-button preview-collapse"
          title={collapsed ? '展开预览区' : '收起预览区'}
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((value) => !value)}
        >
          {collapsed ? <ChevronUp size={17} /> : <ChevronDown size={17} />}
        </button>
      </div>
      {!collapsed &&
        (tab === 'data' ? (
          <>
            <div className="table-toolbar">
              <div className="segmented">
                <button
                  className={view === 'input' ? 'active' : ''}
                  disabled={!node?.data.plugin.inputs.length}
                  onClick={() => {
                    setView('input');
                    setPage(1);
                  }}
                >
                  输入
                </button>
                <button
                  className={view === 'output' ? 'active' : ''}
                  disabled={!node?.data.plugin.outputs.length}
                  onClick={() => {
                    setView('output');
                    setPage(1);
                  }}
                >
                  输出
                </button>
              </div>
              {!selectedNode && (
                <select
                  aria-label="预览节点"
                  className="node-select"
                  value={node?.id || ''}
                  onChange={(event) => setFallback(event.target.value)}
                >
                  {nodes.map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.data.label}
                    </option>
                  ))}
                </select>
              )}
              <select
                aria-label="预览端口"
                className="port-select"
                value={activePort}
                onChange={(event) => {
                  setPort(event.target.value);
                  setPage(1);
                }}
              >
                {ports.map((item) => (
                  <option key={item} value={item}>
                    {portName(item)} · {item}
                  </option>
                ))}
              </select>
              {data && (
                <span className="table-count">
                  {data.row_count.toLocaleString()} 条记录{' '}
                  <span>· {data.columns.length} 个字段</span>
                </span>
              )}
              <label className="table-search">
                <Search size={13} />
                <input
                  aria-label="搜索结果"
                  placeholder="搜索全部结果…"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </label>
              {canShow && job && node && (
                <a
                  className="branch-export"
                  href={`/api/runs/${job.id}/table.csv?${new URLSearchParams({ node: node.id, port: activePort, view })}`}
                  title="下载当前完整分支的 UTF-8 CSV，包含全部行，不受分页或搜索影响"
                >
                  <ArrowDownToLine size={13} />
                  导出此分支
                </a>
              )}
            </div>
            {!loading &&
              !error &&
              data?.rows[0] &&
              view === 'output' &&
              activePort === 'summary' &&
              node?.data.plugin.id === 'tables.score' && <ScoreSummary row={data.rows[0]} />}
            <div className="table-scroll">
              {loading ? (
                <div className="result-empty">
                  <LoaderCircle className="spin" size={25} />
                  <span>正在读取结果…</span>
                </div>
              ) : error ? (
                <div className="result-empty error">
                  <AlertCircle size={25} />
                  <strong>此结果暂不可用</strong>
                  <p>{error}</p>
                  <button className="button secondary" onClick={onPreview} disabled={busy}>
                    重新预览
                  </button>
                </div>
              ) : data ? (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th className="row-number">#</th>
                      {data.columns.map((column) => (
                        <th key={column}>
                          <span className="column-type">T</span>
                          {column}
                        </th>
                      ))}
                      <th className="trace-column">记录追踪</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((row, index) => (
                      <tr
                        key={index}
                        onClick={() => onRecord(row)}
                        tabIndex={0}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') onRecord(row);
                        }}
                      >
                        <td className="row-number">
                          {(data.page - 1) * data.page_size + index + 1}
                        </td>
                        {data.columns.map((column) => (
                          <td
                            key={column}
                            className={
                              row.issues.some((issue) => issue.field === column) ? 'cell-issue' : ''
                            }
                            title={row.values[column]}
                          >
                            {row.values[column] === '' ? (
                              <span className="empty-cell">空</span>
                            ) : (
                              row.values[column]
                            )}
                          </td>
                        ))}
                        <td className="trace-column">
                          {row.issues.length > 0 ? (
                            <span className="issue-pill">{row.issues.length} 个问题</span>
                          ) : row.changes.length > 0 ? (
                            <span className="change-pill">{row.changes.length} 处修改</span>
                          ) : (
                            <span className="source-pill">查看来源 ↗</span>
                          )}
                        </td>
                      </tr>
                    ))}
                    {!data.rows.length && (
                      <tr>
                        <td colSpan={data.columns.length + 2} className="no-data">
                          {query ? '没有匹配搜索条件的记录' : '这个分支没有记录'}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              ) : (
                <div className="result-empty">
                  <div className="empty-table-icon">
                    <Table2 size={25} strokeWidth={1.4} />
                  </div>
                  <strong>
                    {job?.status === 'running' ? '流程正在处理' : '在这里检查每一步的数据'}
                  </strong>
                  <p>
                    {job?.status === 'running'
                      ? '完成后可查看各节点的完整结果'
                      : '选择节点后点击预览，查看字段、问题与修改明细'}
                  </p>
                  <button
                    className="text-button"
                    onClick={onPreview}
                    disabled={busy || !nodes.length}
                  >
                    预览所选节点 →
                  </button>
                </div>
              )}
            </div>
            <div className="table-footer">
              <span>
                {data
                  ? query
                    ? `搜索命中 ${data.filtered_count.toLocaleString()} / ${data.row_count.toLocaleString()} 条`
                    : '点击记录查看来源、问题与修改历史'
                  : '预览只展示分页样本，处理范围为完整数据'}
              </span>
              <div>
                <select
                  aria-label="每页条数"
                  value={pageSize}
                  onChange={(event) => {
                    setPageSize(Number(event.target.value));
                    setPage(1);
                  }}
                >
                  {[25, 50, 100, 200, 500].map((size) => (
                    <option value={size} key={size}>
                      {size} 条 / 页
                    </option>
                  ))}
                </select>
                <button
                  className="icon-button"
                  disabled={!data || data.page <= 1 || loading}
                  title="上一页"
                  onClick={() => setPage((value) => value - 1)}
                >
                  <ChevronLeft size={14} />
                </button>
                <span>{data ? `${data.page} / ${data.pages}` : '— / —'}</span>
                <button
                  className="icon-button"
                  disabled={!data || data.page >= data.pages || loading}
                  title="下一页"
                  onClick={() => setPage((value) => value + 1)}
                >
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          </>
        ) : tab === 'history' ? (
          <div className="history-list">
            {history.length ? (
              history.map((item) => (
                <button
                  className={`history-item ${item.id === job?.id ? 'active' : ''}`}
                  onClick={() => onSelectJob(item)}
                  key={item.id}
                >
                  <span className={`job-dot ${item.status}`} />
                  <div>
                    <strong>
                      {item.preview ? '数据预览' : '正式运行'}{' '}
                      <small>{item.target || '完整流程'}</small>
                    </strong>
                    <span>
                      {new Date(item.created_at).toLocaleTimeString('zh-CN', { hour12: false })} ·{' '}
                      {item.completed}/{item.total} 个节点{item.error && ` · ${item.error}`}
                    </span>
                  </div>
                  <span className={`status-label ${item.status}`}>{statusName[item.status]}</span>
                </button>
              ))
            ) : (
              <div className="result-empty">
                <History size={25} />
                <p>运行或预览后，处理记录会出现在这里</p>
              </div>
            )}
          </div>
        ) : (
          <div className="artifact-list">
            {job?.artifacts.length ? (
              job.artifacts.map((file) => (
                <a key={file.url} href={file.url} download className="artifact-card">
                  <FileCheck2 size={24} />
                  <div>
                    <strong>{file.name}</strong>
                    <span>{bytes(file.size)} · 完整运行结果</span>
                  </div>
                  <ArrowDownToLine size={17} />
                </a>
              ))
            ) : (
              <div className="result-empty">
                <ArrowDownToLine size={25} />
                <strong>还没有导出文件</strong>
                <p>添加输出节点并执行“运行全部”，然后在这里下载</p>
              </div>
            )}
          </div>
        ))}
    </section>
  );
}
