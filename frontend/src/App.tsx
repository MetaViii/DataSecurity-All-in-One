import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Background,
  BackgroundVariant,
  MiniMap,
  ReactFlow,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
} from '@xyflow/react';
import {
  ArrowDownToLine,
  BookOpen,
  Check,
  CheckCheck,
  ChevronDown,
  CircleAlert,
  Code2,
  Copy,
  FolderOpen,
  Home,
  Map,
  Minus,
  LayoutDashboard,
  LoaderCircle,
  Maximize2,
  PanelLeftClose,
  PanelRightClose,
  Play,
  Plus,
  Puzzle,
  Redo2,
  RefreshCw,
  Save,
  Settings2,
  Square,
  Undo2,
  Upload,
  Workflow,
  X,
} from 'lucide-react';
import { api, setToken, upload } from './api';
import {
  autoPositions,
  canConnect,
  defaultsFor,
  definitionOf,
  executionKey,
  graphOf,
} from './model.js';
import type {
  Bootstrap,
  DataRow,
  Definition,
  FileInfo,
  Job,
  Plugin,
  PluginManagement,
  Project,
  Template,
  WorkNode,
} from './types';
import { PluginNode } from './components/PluginNode';
import { Library } from './components/Library';
import { Inspector } from './components/Inspector';
import { Results } from './components/Results';
import { DocsDialog, FlowDialog, Modal, ProjectsDialog, RecordDialog } from './components/Dialogs';
import { WorkspaceHome } from './components/WorkspaceHome';
import { PluginManager } from './components/PluginManager';
import { PythonExport } from './components/PythonExport';
import { useConfirmation } from './hooks/useConfirmation';
import { useServiceStatus } from './hooks/useServiceStatus';
import { draftProblems } from './presentation.js';
import { refreshNodePlugins } from './plugin-manager.js';

const nodeTypes = { plugin: PluginNode };
const activeStatus = (job: Job | null) =>
  Boolean(job && ['queued', 'running'].includes(job.status));

export default function App() {
  const [home, setHome] = useState(true);
  const [mapOpen, setMapOpen] = useState(false);
  const { confirm, confirmation } = useConfirmation();
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null),
    [bootError, setBootError] = useState('');
  const { connected, check: checkConnection } = useServiceStatus(Boolean(bootstrap));
  const [plugins, setPlugins] = useState<Plugin[]>([]),
    [files, setFiles] = useState<FileInfo[]>([]),
    [projects, setProjects] = useState<Project[]>([]);
  const [nodes, setNodes] = useState<WorkNode[]>([]),
    [edges, setEdges] = useState<Edge[]>([]),
    [selected, setSelected] = useState<string | null>(null);
  const [name, setName] = useState('未命名流程'),
    [project, setProject] = useState<Project | null>(null),
    [dirty, setDirty] = useState(false),
    [saving, setSaving] = useState(false);
  const [job, setJob] = useState<Job | null>(null),
    [history, setHistory] = useState<Job[]>([]),
    [runningId, setRunningId] = useState<string | null>(null),
    [starting, setStarting] = useState(false);
  const [dialog, setDialog] = useState<string | null>(null),
    [record, setRecord] = useState<DataRow | null>(null);
  const [toast, setToast] = useState<{ message: string; error: boolean } | null>(null),
    [uploading, setUploading] = useState(false);
  const [leftOpen, setLeftOpen] = useState(() => window.innerWidth >= 640),
    [rightOpen, setRightOpen] = useState(() => window.innerWidth > 1100),
    [historyVersion, setHistoryVersion] = useState(0);
  const fileInput = useRef<HTMLInputElement>(null),
    flowInput = useRef<HTMLInputElement>(null),
    graph = useRef({ nodes, edges });
  const undoStack = useRef<{ nodes: WorkNode[]; edges: Edge[] }[]>([]),
    redoStack = useRef<{ nodes: WorkNode[]; edges: Edge[] }[]>([]);
  const signatures = useRef<Record<string, string>>({}),
    canvas = useReactFlow<WorkNode>();
  const saveLock = useRef(false);
  graph.current = { nodes, edges };
  const definition = useMemo(
    () => definitionOf(nodes, edges, name) as Definition,
    [nodes, edges, name],
  );
  const latestDefinition = useRef(definition);
  latestDefinition.current = definition;
  const signature = executionKey(definition),
    stale = Boolean(job && signatures.current[job.id] !== signature);
  const selectedNode = nodes.find((node) => node.id === selected);
  const problems = useMemo(() => draftProblems(nodes, edges), [nodes, edges]);
  const runningJob = history.find((item) => item.id === runningId) || null;
  const busy = Boolean(runningId) || starting;
  const notify = useCallback((message: string, error = false) => setToast({ message, error }), []);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), toast.error ? 9000 : 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  const fit = useCallback(
    (overview = false) => {
      setTimeout(() => {
        const beginning = [...graph.current.nodes]
          .sort(
            (left, right) =>
              left.position.x - right.position.x || left.position.y - right.position.y,
          )
          .slice(0, window.innerWidth <= 640 ? 1 : 3)
          .map((node) => ({ id: node.id }));
        return canvas.fitView({
          nodes: overview ? undefined : beginning,
          padding: 0.12,
          duration: 250,
          minZoom: overview ? 0.2 : 0.85,
          maxZoom: 1,
        });
      }, 60);
    },
    [canvas],
  );
  useEffect(() => {
    if (!home) fit();
  }, [home, fit]);
  const remember = useCallback(() => {
    undoStack.current.push(structuredClone(graph.current));
    if (undoStack.current.length > 50) undoStack.current.shift();
    redoStack.current = [];
    setHistoryVersion((value) => value + 1);
  }, []);
  const loadDefinition = useCallback(
    (value: Definition, pluginList: Plugin[], fileList: FileInfo[], reset = true) => {
      const normalized = structuredClone(value);
      delete normalized.plugin_dirs;
      normalized.nodes.forEach((node) => {
        if (!node.config) node.config = {};
        const plugin = pluginList.find((item) => item.id === node.plugin);
        if (plugin?.kind === 'output' && typeof node.config.path === 'string')
          node.config.path = node.config.path.split(/[\\/]/).at(-1) || 'result.csv';
        if (
          plugin?.kind === 'input' &&
          typeof node.config.path === 'string' &&
          !fileList.some((file) => file.path === node.config.path)
        ) {
          const matches = fileList.filter((file) => file.path.endsWith(`/${node.config.path}`));
          if (matches.length === 1) node.config.path = matches[0].path;
        }
      });
      const next = graphOf(normalized, pluginList) as { nodes: WorkNode[]; edges: Edge[] };
      setNodes(next.nodes);
      setEdges(next.edges);
      setName(normalized.name || '未命名流程');
      setSelected(next.nodes[0]?.id || null);
      setRightOpen(window.innerWidth > 1100);
      if (reset) {
        undoStack.current = [];
        redoStack.current = [];
        setHistoryVersion((value) => value + 1);
        setJob(null);
      }
      fit();
    },
    [fit],
  );

  const initialize = useCallback(async () => {
    setBootError('');
    try {
      const data = await api<Bootstrap>('/api/bootstrap');
      setToken(data.token);
      setBootstrap(data);
      setPlugins(data.plugins);
      setFiles(data.files);
      setProjects(data.projects);
      let restored = false;
      try {
        const saved = localStorage.getItem(`datasecurity:draft:${data.workspace}`);
        if (saved) {
          const draft = JSON.parse(saved);
          loadDefinition(draft.definition, data.plugins, data.files);
          setProject(draft.project || null);
          setDirty(Boolean(draft.dirty));
          restored = true;
        }
      } catch {
        /* A stale browser draft must not prevent opening the workspace. */
      }
      if (!restored)
        loadDefinition(
          data.templates[0]?.definition || { version: 1, name: '未命名流程', nodes: [] },
          data.plugins,
          data.files,
        );
      if (data.plugin_errors.length)
        notify(`有 ${data.plugin_errors.length} 个插件加载提示，可在工作区设置中查看`, true);
    } catch (error) {
      setBootError((error as Error).message || '无法连接本地服务');
    }
  }, [loadDefinition, notify]);
  useEffect(() => {
    void initialize();
  }, []);
  useEffect(() => {
    if (!bootstrap) return;
    const timer = setTimeout(() => {
      try {
        localStorage.setItem(
          `datasecurity:draft:${bootstrap.workspace}`,
          JSON.stringify({ definition, project, dirty }),
        );
      } catch {
        /* Saving projects to disk remains available. */
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [definition, project, dirty, bootstrap]);
  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (dirty) event.preventDefault();
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  const patchConfig = useCallback(
    (patch: Record<string, unknown>) => {
      if (!selected) return;
      remember();
      setDirty(true);
      setNodes((current) =>
        current.map((node) =>
          node.id === selected
            ? { ...node, data: { ...node.data, config: { ...node.data.config, ...patch } } }
            : node,
        ),
      );
    },
    [selected, remember],
  );
  const setConfig = useCallback(
    (key: string, value: unknown) => patchConfig({ [key]: value }),
    [patchConfig],
  );
  const connect = useCallback(
    (connection: Connection) => {
      if (!canConnect(connection, graph.current.nodes, graph.current.edges)) {
        notify('无法连接：请检查端口，且流程不能形成循环', true);
        return;
      }
      remember();
      setDirty(true);
      setEdges((current) => [
        ...current.filter(
          (edge) =>
            !(edge.target === connection.target && edge.targetHandle === connection.targetHandle),
        ),
        {
          ...connection,
          id: `${connection.source}:${connection.sourceHandle}->${connection.target}:${connection.targetHandle}`,
          type: 'smoothstep',
        },
      ]);
    },
    [remember, notify],
  );
  const addPlugin = useCallback(
    (plugin: Plugin, file?: FileInfo, position?: { x: number; y: number }) => {
      remember();
      const config = defaultsFor(plugin) as Record<string, unknown>;
      if (plugin.kind === 'output')
        config.path =
          plugin.id === 'xlsx.write'
            ? 'result.xlsx'
            : plugin.id === 'json.write'
              ? 'result.json'
              : 'result.csv';
      if (file) {
        config.path = file.path;
        if (file.encoding) config.encoding = file.encoding;
        if (file.extension === '.tsv') config.delimiter = '\t';
      }
      const parent = graph.current.nodes.find((node) => node.id === selected),
        id = `n_${crypto.randomUUID().replaceAll('-', '').slice(0, 10)}`;
      const node: WorkNode = {
        id,
        type: 'plugin',
        position:
          position ||
          (parent
            ? { x: parent.position.x + 290, y: parent.position.y }
            : {
                x: 80 + graph.current.nodes.length * 24,
                y: 100 + graph.current.nodes.length * 24,
              }),
        data: { plugin, config, label: plugin.name },
      };
      setNodes((current) => [...current, node]);
      if (parent?.data.plugin.outputs.length && plugin.inputs.length === 1) {
        const sourceHandle = parent.data.plugin.outputs[0],
          targetHandle = plugin.inputs[0];
        setEdges((current) => [
          ...current,
          {
            id: `${parent.id}:${sourceHandle}->${id}:${targetHandle}`,
            source: parent.id,
            sourceHandle,
            target: id,
            targetHandle,
            type: 'smoothstep',
          },
        ]);
      }
      setSelected(id);
      setRightOpen(true);
      setDirty(true);
    },
    [selected, remember],
  );
  const useFile = useCallback(
    (file: FileInfo) => {
      if (selectedNode?.data.plugin.id === file.reader) {
        remember();
        setNodes((current) =>
          current.map((node) =>
            node.id === selected
              ? {
                  ...node,
                  data: {
                    ...node.data,
                    config: {
                      ...node.data.config,
                      path: file.path,
                      ...(file.encoding ? { encoding: file.encoding } : {}),
                      ...(file.extension === '.tsv' ? { delimiter: '\t' } : {}),
                    },
                  },
                }
              : node,
          ),
        );
        setDirty(true);
      } else {
        const plugin = plugins.find((item) => item.id === file.reader);
        if (plugin) addPlugin(plugin, file);
      }
    },
    [selectedNode, selected, plugins, addPlugin, remember],
  );
  const handleUpload = async (file?: File) => {
    if (!file) return;
    setUploading(true);
    try {
      const info: FileInfo = await upload(file);
      setFiles((current) => [...current, info]);
      if (home) void beginWithFile(info);
      else useFile(info);
      notify(`已导入 ${file.name}`);
    } catch (error) {
      notify((error as Error).message, true);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  };
  const deleteNode = useCallback(() => {
    if (!selected) return;
    remember();
    setNodes((current) => current.filter((node) => node.id !== selected));
    setEdges((current) =>
      current.filter((edge) => edge.source !== selected && edge.target !== selected),
    );
    setSelected(null);
    setDirty(true);
  }, [selected, remember]);
  const undo = useCallback((redo = false) => {
    const source = redo ? redoStack : undoStack,
      destination = redo ? undoStack : redoStack;
    const snapshot = source.current.pop();
    if (!snapshot) return;
    destination.current.push(structuredClone(graph.current));
    setNodes(snapshot.nodes);
    setEdges(snapshot.edges);
    setDirty(true);
    setHistoryVersion((value) => value + 1);
  }, []);

  const saveProject = useCallback(
    async (asNew = false) => {
      if (saveLock.current || !connected) return;
      saveLock.current = true;
      setSaving(true);
      try {
        const saved = await api<Project>('/api/projects', 'POST', {
          ...(!asNew && project ? { id: project.id, revision: project.revision } : {}),
          name,
          definition,
        });
        setProject(saved);
        setDirty(JSON.stringify(latestDefinition.current) !== JSON.stringify(definition));
        setProjects(await api<Project[]>('/api/projects'));
        notify('流程已保存到本机');
      } catch (error) {
        notify((error as Error).message, true);
      } finally {
        saveLock.current = false;
        setSaving(false);
      }
    },
    [name, definition, project, notify, connected],
  );
  const replaceFlow = async (value: Definition, loadedProject: Project | null = null) => {
    if (saveLock.current) {
      notify('正在保存当前流程，请稍候再切换。');
      return false;
    }
    if (busy) {
      notify('任务正在运行，请等待完成，或返回编辑器取消任务后再切换流程。', true);
      return false;
    }
    graphOf(value, plugins);
    if (
      dirty &&
      !(await confirm({
        title: '切换当前流程？',
        message: `“${name}”有未保存的修改。返回画布保存后再切换，或放弃这些修改。`,
        action: '放弃修改并切换',
      }))
    )
      return false;
    loadDefinition(value, plugins, files);
    setProject(loadedProject);
    setDirty(!loadedProject);
    setDialog(null);
    setHome(false);
    return true;
  };
  const beginWithFile = async (file: FileInfo) => {
    const plugin = plugins.find((item) => item.id === file.reader);
    if (!plugin) return;
    const config = {
      ...defaultsFor(plugin),
      path: file.path,
      ...(file.encoding ? { encoding: file.encoding } : {}),
      ...(file.extension === '.tsv' ? { delimiter: '\t' } : {}),
    };
    await replaceFlow({
      version: 1,
      name: file.name.replace(/^[0-9a-f]{12}_/, '').replace(/\.[^.]+$/, '') + ' · 数据处理',
      nodes: [{ id: 'read', plugin: plugin.id, config, inputs: {} }],
    });
  };
  const loadProject = async (item: Project) => {
    try {
      const loaded = await api<Project>(`/api/projects/${item.id}`);
      await replaceFlow(loaded.definition!, loaded);
    } catch (error) {
      notify((error as Error).message, true);
    }
  };
  const deleteProject = async (item: Project) => {
    if (
      !(await confirm({
        title: '删除已保存的流程？',
        message: `将删除“${item.name}”的流程文件，输入附件和已导出的文件会保留。此操作无法撤销。`,
        action: '删除流程',
        danger: true,
      }))
    )
      return;
    try {
      await api(`/api/projects/${item.id}`, 'DELETE');
      setProjects((current) => current.filter((project) => project.id !== item.id));
      if (project?.id === item.id) {
        setProject(null);
        setDirty(true);
      }
      notify('已删除保存的流程');
    } catch (error) {
      notify((error as Error).message, true);
    }
  };
  const importFlow = async (file?: File) => {
    if (!file) return;
    try {
      if (await replaceFlow(JSON.parse(await file.text())))
        notify('已导入流程，请检查数据文件与参数');
    } catch (error) {
      notify((error as Error).message, true);
    } finally {
      if (flowInput.current) flowInput.current.value = '';
    }
  };

  const beginRun = useCallback(
    async (preview: boolean, target?: string) => {
      if (busy) return;
      if (!nodes.length) {
        notify('先添加一个数据输入节点', true);
        return;
      }
      setStarting(true);
      try {
        const result = await api<Job>('/api/runs', 'POST', {
          definition,
          preview,
          ...(preview && target ? { target } : {}),
        });
        signatures.current[result.id] = signature;
        setJob(result);
        setHistory((current) => [result, ...current].slice(0, 6));
        setRunningId(result.id);
      } catch (error) {
        notify((error as Error).message, true);
      } finally {
        setStarting(false);
      }
    },
    [busy, nodes.length, definition, signature, notify],
  );
  useEffect(() => {
    if (!runningId) return;
    let active = true,
      timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const current = await api<Job>(`/api/runs/${runningId}`);
        if (!active) return;
        setHistory((values) => values.map((item) => (item.id === current.id ? current : item)));
        setJob((value) => (value?.id === current.id ? current : value));
        if (activeStatus(current)) timer = setTimeout(poll, 400);
        else {
          setRunningId(null);
          notify(
            current.status === 'success'
              ? current.preview
                ? '预览完成，输出文件未写入'
                : `处理完成，已生成 ${current.artifacts.length} 个文件`
              : current.status === 'cancelled'
                ? '任务已取消'
                : current.error || '运行失败',
            current.status === 'error',
          );
          if (current.error_node) {
            setSelected(current.error_node);
            setRightOpen(true);
          }
        }
      } catch (error) {
        if (active) {
          notify(`暂时无法读取任务状态：${(error as Error).message}`, true);
          timer = setTimeout(poll, 2000);
        }
      }
    };
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [runningId, notify]);
  const validate = async () => {
    try {
      const result = await api<{ order: string[] }>('/api/validate', 'POST', { definition });
      notify(`配置检查通过，共 ${result.order.length} 个节点`);
    } catch (error) {
      notify((error as Error).message, true);
    }
  };
  const cancelRun = async () => {
    if (runningId) {
      try {
        await api(`/api/runs/${runningId}/cancel`, 'POST');
        notify('已请求取消，等待当前节点安全退出');
      } catch (error) {
        notify((error as Error).message, true);
      }
    }
  };
  const updatePlugins = (result: PluginManagement) => {
    signatures.current = {};
    setPlugins(result.plugins);
    setBootstrap((current) =>
      current ? { ...current, plugin_errors: result.plugin_errors } : current,
    );
    setNodes((current) => refreshNodePlugins(current, result.plugins));
  };
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (dialog || record) return;
      const typing = (event.target as HTMLElement)?.matches(
        'input,textarea,select,[contenteditable]',
      );
      if (!home && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        void saveProject();
      }
      if (!home && !typing && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        undo(event.shiftKey);
      }
      if (!home && !typing && event.key === '/') {
        event.preventDefault();
        setLeftOpen(true);
        setTimeout(
          () => document.querySelector<HTMLInputElement>('[aria-label="搜索处理模块"]')?.focus(),
          30,
        );
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [saveProject, undo, home, dialog, record]);

  const availableFields = useMemo(() => {
    const find = (id: string, seen = new Set<string>()): string[] => {
      if (seen.has(id)) return [];
      seen.add(id);
      const entry = job?.nodes.find((item) => item.id === id);
      if (!stale && entry && Object.keys(entry.ports).length)
        return [...new Set(Object.values(entry.ports).flatMap((port) => port.columns))];
      const current = nodes.find((item) => item.id === id);
      if (!current) return [];
      if (current.data.plugin.kind === 'input')
        return files.find((file) => file.path === current.data.config.path)?.columns || [];
      const upstream = [
        ...new Set(
          edges.filter((edge) => edge.target === id).flatMap((edge) => find(edge.source, seen)),
        ),
      ];
      const config = current.data.config;
      if (
        current.data.plugin.id === 'columns.select' &&
        config.mode !== 'drop' &&
        Array.isArray(config.fields)
      )
        return config.fields as string[];
      if (
        current.data.plugin.id === 'columns.rename' &&
        config.mapping &&
        typeof config.mapping === 'object'
      )
        return upstream.map((field) =>
          String((config.mapping as Record<string, unknown>)[field] ?? field),
        );
      return [
        ...new Set([
          ...upstream,
          ...(typeof config.output === 'string' && config.output ? [config.output] : []),
        ]),
      ];
    };
    if (!selectedNode) return [];
    return selectedNode.data.plugin.kind === 'input'
      ? find(selectedNode.id)
      : [
          ...new Set(
            edges
              .filter((edge) => edge.target === selectedNode.id)
              .flatMap((edge) => find(edge.source)),
          ),
        ];
  }, [selectedNode, nodes, edges, files, job, stale]);
  const visibleNodes = useMemo(
    () =>
      nodes.map((node) => {
        const step = job?.steps.find((item) => item.id === node.id),
          metadata = job?.nodes.find((item) => item.id === node.id);
        const count =
          metadata && Object.values(metadata.ports).length
            ? Object.values(metadata.ports).reduce((total, port) => total + port.rows, 0)
            : step
              ? Object.values(step.inputs).reduce((total, value) => total + value, 0)
              : undefined;
        const status =
          job?.error_node === node.id
            ? 'error'
            : job?.status === 'running' && job.current_node === node.id
              ? 'running'
              : step?.status;
        const portCounts = metadata
          ? Object.fromEntries(
              Object.entries(metadata.ports).map(([port, value]) => [port, value.rows]),
            )
          : step?.outputs;
        return { ...node, data: { ...node.data, status, count, portCounts } };
      }),
    [nodes, job],
  );
  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      notify('已复制');
    } catch {
      notify('浏览器未允许复制，请手动选择文本', true);
    }
  };

  if (!bootstrap)
    return (
      <div className="boot-screen">
        <div className="brand-mark">
          D<span />
        </div>
        <h1>DataSecurity</h1>
        {bootError ? (
          <>
            <p>{bootError}</p>
            <button className="button primary" onClick={() => void initialize()}>
              <RefreshCw size={15} />
              重新连接
            </button>
            <small>请先启动本地服务：python -m datasecurity serve</small>
          </>
        ) : (
          <>
            <LoaderCircle className="spin" size={22} />
            <p>正在连接本地工作区…</p>
          </>
        )}
      </div>
    );

  return (
    <div
      className={`app-shell ${leftOpen ? '' : 'left-hidden'} ${rightOpen ? '' : 'right-hidden'}`}
    >
      <header className="app-header">
        <a
          className="brand"
          href="#"
          onClick={(event) => {
            event.preventDefault();
            setHome(true);
          }}
        >
          <span className="brand-mark">
            D<span />
          </span>
          <strong>DataSecurity</strong>
          <span className="brand-tag">本地数据工作台</span>
        </a>
        <div className="header-divider" />
        <button
          className="project-trigger"
          title="打开已保存的流程"
          onClick={() => setDialog('projects')}
        >
          <FolderOpen size={15} />
          <span>{project ? '我的流程' : '本地工作区'}</span>
          <ChevronDown size={12} />
        </button>
        <span className="header-spacer" />
        <button className={`header-nav ${home ? 'active' : ''}`} onClick={() => setHome(true)}>
          <Home size={16} />
          工作区
        </button>
        <button
          className={`header-nav ${home ? '' : 'active'}`}
          onClick={() => {
            setHome(false);
            fit();
          }}
        >
          <Workflow size={16} />
          流程编辑器
        </button>
        <span className={`connection-status ${connected ? '' : 'offline'}`}>
          <span className="local-dot" />
          {connected ? '服务已连接' : '连接已断开'}
        </span>
        <button className="icon-button" title="代码与使用文档" onClick={() => setDialog('docs')}>
          <BookOpen size={17} />
        </button>
        <button
          className="header-nav plugin-entry"
          aria-label="插件"
          title="添加与管理本地插件"
          onClick={() => setDialog('plugins')}
        >
          <Puzzle size={17} />
          <span>插件</span>
        </button>
        <button className="icon-button" title="工作区设置" onClick={() => setDialog('settings')}>
          <Settings2 size={17} />
        </button>
      </header>
      {!connected && (
        <div className="connection-banner" role="status">
          <CircleAlert size={16} />
          <span>暂时无法连接本地服务，编辑内容已保留。服务恢复后会自动重连。</span>
          <button onClick={() => void checkConnection()}>
            <RefreshCw size={14} />
            重新连接
          </button>
        </div>
      )}
      {home ? (
        <WorkspaceHome
          projects={projects}
          templates={bootstrap.templates}
          files={files}
          pluginCount={plugins.length}
          currentName={name}
          hasCurrent={Boolean(nodes.length || project || dirty)}
          dirty={dirty}
          uploading={uploading}
          onContinue={() => setHome(false)}
          onNew={() => void replaceFlow({ version: 1, name: '未命名流程', nodes: [] })}
          onImport={() => flowInput.current?.click()}
          onUpload={() => fileInput.current?.click()}
          onTemplate={(template) => void replaceFlow(template.definition)}
          onLoad={(item) => void loadProject(item)}
          onDelete={(item) => void deleteProject(item)}
          onFile={(file) => void beginWithFile(file)}
          onDocs={() => setDialog('docs')}
        />
      ) : (
        <>
          <div className="workspace-toolbar">
            <button
              className="icon-button"
              title="展开或折叠模块库"
              onClick={() => setLeftOpen((value) => !value)}
            >
              <PanelLeftClose size={17} />
            </button>
            <div className="flow-name">
              <input
                aria-label="流程名称"
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                  setDirty(true);
                }}
              />
              <span
                className={dirty ? 'unsaved' : 'saved'}
                title={dirty ? '未保存的修改' : '已保存或未修改'}
              >
                {dirty ? '未保存' : project ? '已保存' : '示例流程'}
              </span>
            </div>
            <div className="toolbar-divider" />
            <button
              className="icon-button"
              title="撤销 Ctrl+Z"
              disabled={!undoStack.current.length}
              onClick={() => undo()}
            >
              <Undo2 size={16} />
            </button>
            <button
              className="icon-button"
              title="重做 Ctrl+Shift+Z"
              disabled={!redoStack.current.length}
              onClick={() => undo(true)}
            >
              <Redo2 size={16} />
            </button>
            <button className="toolbar-link" onClick={() => setDialog('flow')}>
              <Code2 size={15} />
              <span>流程 JSON</span>
            </button>
            <button
              className="toolbar-link"
              disabled={!connected || !nodes.length}
              onClick={() => setDialog('python-export')}
              title="导出含处理源码的独立复现脚本"
            >
              <ArrowDownToLine size={15} />
              <span>导出 Python</span>
            </button>
            <span className="header-spacer" />
            <button
              className="button subtle"
              aria-label="保存"
              title="保存流程（Ctrl+S）"
              disabled={saving || !connected}
              onClick={() => void saveProject()}
            >
              {saving ? <LoaderCircle className="spin" size={14} /> : <Save size={14} />}
              <span className="button-label">保存</span>
            </button>
            <button className="button subtle check-button" onClick={() => void validate()}>
              <CheckCheck size={15} />
              检查
            </button>
            <button
              className="button secondary preview-button"
              aria-label={selected ? '预览所选' : '预览流程'}
              title={selected ? '预览所选节点' : '预览完整流程'}
              disabled={busy || !connected || !nodes.length}
              onClick={() => void beginRun(true, selected || undefined)}
            >
              <LayoutDashboard size={14} />
              <span className="button-label">{selected ? '预览所选' : '预览流程'}</span>
            </button>
            <button
              className="button primary run-button"
              aria-label="运行全部"
              title="运行完整流程并导出文件"
              disabled={busy || !connected || !nodes.length}
              onClick={() => void beginRun(false)}
            >
              {busy ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                <Play size={14} fill="currentColor" />
              )}
              <span className="button-label">运行全部</span>
            </button>
            <button
              className="icon-button"
              title="展开或折叠节点配置"
              onClick={() => setRightOpen((value) => !value)}
            >
              <PanelRightClose size={17} />
            </button>
          </div>
          <div className="workspace-body">
            {leftOpen && (
              <Library
                onPlugins={() => setDialog('plugins')}
                plugins={plugins}
                files={files}
                onAdd={(plugin) => addPlugin(plugin)}
                onUseFile={useFile}
                onUpload={() => fileInput.current?.click()}
                uploading={uploading}
              />
            )}
            <main className="workbench-main">
              <div className="canvas-heading">
                <span>
                  <Workflow size={14} />
                  流程画布{' '}
                  <small>
                    {nodes.length} 个节点 · {edges.length} 条连接
                  </small>
                </span>
                <div>
                  {problems.length > 0 && (
                    <button
                      className="draft-warning"
                      title={problems.map((problem) => problem.message).join('\n')}
                      onClick={() => {
                        setSelected(problems[0].node);
                        setRightOpen(true);
                      }}
                    >
                      <CircleAlert size={14} />
                      {problems.length} 项待配置
                    </button>
                  )}
                  <button
                    className="canvas-action"
                    title="自动排列节点"
                    onClick={() => {
                      remember();
                      setNodes((current) => autoPositions(current, edges) as WorkNode[]);
                      setDirty(true);
                      fit();
                    }}
                  >
                    自动布局
                  </button>
                  <button className="icon-button" title="查看完整流程" onClick={() => fit(true)}>
                    <Maximize2 size={14} />
                  </button>
                  <button
                    className="icon-button"
                    title="放大画布"
                    onClick={() => void canvas.zoomIn({ duration: 150 })}
                  >
                    <Plus size={15} />
                  </button>
                  <button
                    className="icon-button"
                    title="缩小画布"
                    onClick={() => void canvas.zoomOut({ duration: 150 })}
                  >
                    <Minus size={15} />
                  </button>
                  <button
                    className={`icon-button ${mapOpen ? 'active' : ''}`}
                    title={mapOpen ? '隐藏流程导航' : '显示流程导航'}
                    aria-pressed={mapOpen}
                    onClick={() => setMapOpen((value) => !value)}
                  >
                    <Map size={15} />
                  </button>
                </div>
              </div>
              <div
                className="canvas"
                onDragOver={(event) => {
                  event.preventDefault();
                  event.dataTransfer.dropEffect = 'copy';
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  const plugin = plugins.find(
                    (item) =>
                      item.id === event.dataTransfer.getData('application/datasecurity-plugin'),
                  );
                  if (plugin)
                    addPlugin(
                      plugin,
                      undefined,
                      canvas.screenToFlowPosition({ x: event.clientX, y: event.clientY }),
                    );
                }}
              >
                <ReactFlow<WorkNode>
                  nodes={visibleNodes}
                  edges={edges}
                  nodeTypes={nodeTypes}
                  onNodesChange={(changes: NodeChange<WorkNode>[]) => {
                    if (changes.some((change) => change.type === 'remove')) {
                      remember();
                      setDirty(true);
                    }
                    setNodes((current) => applyNodeChanges(changes, current));
                  }}
                  onEdgesChange={(changes: EdgeChange[]) => {
                    if (changes.some((change) => change.type === 'remove')) {
                      remember();
                      setDirty(true);
                    }
                    setEdges((current) => applyEdgeChanges(changes, current));
                  }}
                  onConnect={connect}
                  onNodeClick={(_, node) => {
                    setSelected(node.id);
                    setRightOpen(true);
                  }}
                  onPaneClick={() => setSelected(null)}
                  onNodeDragStart={remember}
                  onNodeDragStop={() => setDirty(true)}
                  fitView
                  minZoom={0.2}
                  maxZoom={1.8}
                  proOptions={{ hideAttribution: false }}
                  defaultEdgeOptions={{
                    type: 'smoothstep',
                    style: { stroke: '#94a8c1', strokeWidth: 1.6 },
                  }}
                  deleteKeyCode={['Backspace', 'Delete']}
                >
                  <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#ccd5df" />
                  {mapOpen && nodes.length > 3 && (
                    <MiniMap<WorkNode>
                      pannable
                      zoomable
                      ariaLabel="流程导航缩略图"
                      nodeColor={(node) =>
                        node.data.plugin.kind === 'input'
                          ? '#bce4d5'
                          : node.data.plugin.kind === 'output'
                            ? '#d6c8ef'
                            : '#c7d9f6'
                      }
                      maskColor="rgba(234,239,247,.7)"
                      position="bottom-right"
                    />
                  )}
                </ReactFlow>
                {!nodes.length && (
                  <div className="canvas-empty">
                    <div>
                      <Workflow size={36} strokeWidth={1.2} />
                    </div>
                    <h2>把数据处理，连成一条流程</h2>
                    <p>从左侧添加输入节点，或导入一份数据文件</p>
                    <button className="button primary" onClick={() => fileInput.current?.click()}>
                      <Upload size={15} />
                      导入数据
                    </button>
                    <button
                      className="text-button"
                      onClick={() =>
                        bootstrap.templates[0] && replaceFlow(bootstrap.templates[0].definition)
                      }
                    >
                      打开清洗示例 →
                    </button>
                  </div>
                )}
                <div className="canvas-caption">
                  {selectedNode ? (
                    <>
                      <span className="small-blue-dot" />
                      {selectedNode.data.label}
                      <code>{selectedNode.id}</code>
                    </>
                  ) : (
                    <span>拖动节点调整位置 · 连接端口编排流程</span>
                  )}
                </div>
              </div>
              {busy && (
                <div className="run-progress">
                  <LoaderCircle className="spin" size={14} />
                  <span>
                    {runningJob?.current_node
                      ? `正在处理 ${nodes.find((node) => node.id === runningJob.current_node)?.data.label || runningJob.current_node}`
                      : '正在准备任务…'}
                  </span>
                  <div className="progress-track">
                    <div
                      style={{
                        width: `${runningJob?.total ? (runningJob.completed / runningJob.total) * 100 : 0}%`,
                      }}
                    />
                  </div>
                  <small>
                    {runningJob?.completed || 0}/{runningJob?.total || '—'}
                  </small>
                  <button onClick={() => void cancelRun()}>
                    <Square size={11} />
                    取消
                  </button>
                </div>
              )}
              {!busy && job && (
                <div role="status" className={`run-summary ${job.status} ${stale ? 'stale' : ''}`}>
                  {job.status === 'error' ? <CircleAlert size={17} /> : <Check size={17} />}
                  <div>
                    <strong>
                      {stale
                        ? '配置已更新，请重新预览'
                        : job.status === 'success'
                          ? job.preview
                            ? '预览完成'
                            : '处理完成'
                          : job.status === 'cancelled'
                            ? '任务已取消'
                            : '运行失败'}
                    </strong>
                    <span>
                      {job.error ||
                        (job.status === 'cancelled'
                          ? '可以调整配置后重新运行。'
                          : `${job.completed}/${job.total} 个节点 · ${job.steps.reduce((total, step) => total + step.seconds, 0).toFixed(2)} 秒${job.preview ? ' · 未写入文件' : ` · 已生成 ${job.artifacts.length} 个文件`}`)}
                    </span>
                  </div>
                </div>
              )}
              <Results
                job={job}
                nodes={nodes}
                selected={selected}
                history={history}
                stale={stale}
                onSelectJob={setJob}
                onRecord={setRecord}
                onPreview={() => void beginRun(true, selected || undefined)}
                busy={busy || !connected}
              />
            </main>
            {rightOpen && (
              <Inspector
                node={selectedNode}
                nodes={nodes}
                edges={edges}
                fields={availableFields}
                files={files}
                onLabel={(label) => {
                  remember();
                  setNodes((current) =>
                    current.map((node) =>
                      node.id === selected ? { ...node, data: { ...node.data, label } } : node,
                    ),
                  );
                  setDirty(true);
                }}
                onConfig={setConfig}
                onPatch={patchConfig}
                onConnect={(port, endpoint) => {
                  if (!endpoint) {
                    remember();
                    setEdges((current) =>
                      current.filter(
                        (edge) => !(edge.target === selected && edge.targetHandle === port),
                      ),
                    );
                    setDirty(true);
                  } else {
                    const [source, sourceHandle] = endpoint.split(':');
                    connect({ source, sourceHandle, target: selected!, targetHandle: port });
                  }
                }}
                onDelete={deleteNode}
                onClose={() => setRightOpen(false)}
                onPreview={() => void beginRun(true, selected || undefined)}
                busy={busy || !connected}
              />
            )}
          </div>
          <footer className="app-footer">
            <span>
              <span className="local-dot" />
              本地工作区{' '}
              <code title={bootstrap.workspace}>{bootstrap.workspace.split(/[\\/]/).at(-1)}</code>
            </span>
            <span>完整数据计算 · 预览不写文件</span>
            <span>
              v{bootstrap.version}
              <button onClick={() => setDialog('docs')}>代码导读 ↗</button>
            </span>
          </footer>
        </>
      )}
      <input
        ref={fileInput}
        type="file"
        hidden
        accept=".csv,.tsv,.json,.jsonl,.ndjson,.txt,.log,.xlsx,.pcap,.pcapng"
        onChange={(event) => void handleUpload(event.target.files?.[0])}
      />
      <input
        ref={flowInput}
        type="file"
        hidden
        accept=".json"
        onChange={(event) => void importFlow(event.target.files?.[0])}
      />
      {toast && (
        <div role="status" className={`toast ${toast.error ? 'error' : ''}`}>
          {toast.error ? <CircleAlert size={17} /> : <Check size={17} />}
          <span>{toast.message}</span>
          <button className="icon-button" aria-label="关闭提示" onClick={() => setToast(null)}>
            <X size={14} />
          </button>
        </div>
      )}
      {dialog === 'projects' && (
        <ProjectsDialog
          projects={projects}
          templates={bootstrap.templates}
          onClose={() => setDialog(null)}
          onNew={() => replaceFlow({ version: 1, name: '未命名流程', nodes: [] })}
          onLoad={(item) => void loadProject(item)}
          onTemplate={(template) => replaceFlow(template.definition)}
          onImport={() => flowInput.current?.click()}
          onDelete={(item) => void deleteProject(item)}
        />
      )}
      {dialog === 'flow' && (
        <FlowDialog
          definition={definition}
          onClose={() => setDialog(null)}
          onApply={(value) => {
            remember();
            loadDefinition(value, plugins, files, false);
            setDirty(true);
            setDialog(null);
            notify('流程配置已应用');
          }}
        />
      )}
      {dialog === 'docs' && <DocsDialog onClose={() => setDialog(null)} />}
      {dialog === 'python-export' && (
        <PythonExport definition={definition} onClose={() => setDialog(null)} />
      )}
      {dialog === 'plugins' && (
        <PluginManager
          busy={busy}
          connected={connected}
          onClose={() => setDialog(null)}
          onUpdate={updatePlugins}
          onDocs={() => setDialog('docs')}
        />
      )}
      {record && (
        <RecordDialog
          record={record}
          onClose={() => setRecord(null)}
          onCopy={(value) => void copy(value)}
        />
      )}
      {dialog === 'settings' && (
        <Modal title="工作区设置" onClose={() => setDialog(null)}>
          <div className="settings-body">
            <span className="section-label">工作区目录</span>
            <code>{bootstrap.workspace}</code>
            <button className="button secondary" onClick={() => void copy(bootstrap.workspace)}>
              <Copy size={14} />
              复制路径
            </button>
            <p>网页读取的数据文件位于这个目录内。上传、保存的流程和导出结果位于 work 子目录。</p>
            <div className="settings-divider" />
            <span className="section-label">本地插件</span>
            <p>导入源码或从模板创建，安装后即可在节点库使用。</p>
            <button className="button secondary" onClick={() => setDialog('plugins')}>
              <Puzzle size={14} />
              管理插件（{plugins.length}）
            </button>
            {bootstrap.plugin_errors.map((error, index) => (
              <pre className="plugin-error" key={index}>
                {error}
              </pre>
            ))}
            <div className="settings-divider" />
            <button className="button secondary" onClick={() => void saveProject(true)}>
              <Plus size={14} />
              将当前流程另存为新项目
            </button>
          </div>
        </Modal>
      )}
      {confirmation}
    </div>
  );
}
