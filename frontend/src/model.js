// This module has no React or DOM dependency, so the flow contract can be tested
// without starting a browser. Execution data and canvas coordinates stay apart.
export function definitionOf(nodes, edges, name) {
  const definition = {
    version: 1,
    name,
    nodes: nodes.map((node) => ({
      id: node.id,
      plugin: node.data.plugin.id,
      config: node.data.config,
      inputs: Object.fromEntries(
        edges
          .filter((edge) => edge.target === node.id)
          .map((edge) => [edge.targetHandle, `${edge.source}:${edge.sourceHandle}`]),
      ),
    })),
    ui: {
      positions: Object.fromEntries(nodes.map((node) => [node.id, node.position])),
      labels: Object.fromEntries(nodes.map((node) => [node.id, node.data.label])),
    },
  };
  return definition;
}

export function executionKey(definition) {
  return JSON.stringify({ version: definition.version, nodes: definition.nodes });
}

export function autoPositions(nodes, edges) {
  const levels = new Map(),
    pending = new Set(nodes.map((node) => node.id));
  for (let pass = 0; pass <= nodes.length && pending.size; pass++) {
    for (const id of [...pending]) {
      const parents = edges.filter((edge) => edge.target === id).map((edge) => edge.source);
      if (parents.every((parent) => levels.has(parent))) {
        levels.set(
          id,
          parents.length ? 1 + Math.max(...parents.map((parent) => levels.get(parent))) : 0,
        );
        pending.delete(id);
      }
    }
  }
  const slots = new Map();
  return nodes.map((node) => {
    const level = levels.get(node.id) ?? 0,
      slot = slots.get(level) ?? 0;
    slots.set(level, slot + 1);
    return { ...node, position: { x: 40 + level * 290, y: 60 + slot * 190 } };
  });
}

export function graphOf(definition, plugins) {
  if (!definition || definition.version !== 1 || !Array.isArray(definition.nodes))
    throw new Error('需要 version=1 的流程 JSON');
  const ids = definition.nodes.map((node) => node.id);
  if (
    ids.some((id) => typeof id !== 'string' || !/^[A-Za-z][A-Za-z0-9_-]*$/.test(id)) ||
    new Set(ids).size !== ids.length
  )
    throw new Error('节点 ID 无效或重复');
  const edges = [];
  for (const node of definition.nodes) {
    if (!node.inputs || typeof node.inputs !== 'object' || Array.isArray(node.inputs)) {
      if (node.inputs !== undefined) throw new Error('inputs 必须是对象');
    }
    for (const [port, endpoint] of Object.entries(node.inputs || {})) {
      if (typeof endpoint !== 'string' || endpoint.split(':').length !== 2)
        throw new Error('输入连接应为 节点ID:输出端口');
      const [source, sourceHandle] = endpoint.split(':');
      if (!ids.includes(source)) throw new Error(`找不到上游节点：${source}`);
      edges.push({
        id: `${source}:${sourceHandle}->${node.id}:${port}`,
        source,
        sourceHandle,
        target: node.id,
        targetHandle: port,
        type: 'smoothstep',
      });
    }
  }
  let nodes = definition.nodes.map((node) => {
    if (
      typeof node.plugin !== 'string' ||
      (node.config !== undefined &&
        (!node.config || typeof node.config !== 'object' || Array.isArray(node.config)))
    )
      throw new Error('plugin 或 config 格式无效');
    const plugin = plugins.find((item) => item.id === node.plugin);
    const fallback = {
      id: node.plugin,
      name: node.plugin,
      kind: 'transform',
      description: '当前未加载此插件',
      category: '未加载',
      version: '?',
      inputs: Object.keys(node.inputs || {}),
      outputs: [
        ...new Set(
          edges.filter((edge) => edge.source === node.id).map((edge) => edge.sourceHandle),
        ),
      ],
      parameters: [],
    };
    return {
      id: node.id,
      type: 'plugin',
      position: { x: 0, y: 0 },
      data: {
        plugin: plugin || fallback,
        unknown: !plugin,
        config: node.config || {},
        label:
          (typeof definition.ui?.labels?.[node.id] === 'string' && definition.ui.labels[node.id]) ||
          plugin?.name ||
          node.plugin,
      },
    };
  });
  nodes = autoPositions(nodes, edges).map((node) => {
    const saved = definition.ui?.positions?.[node.id];
    return saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)
      ? { ...node, position: saved }
      : node;
  });
  return { nodes, edges };
}

export function canConnect(connection, nodes, edges) {
  const { source, target, sourceHandle, targetHandle } = connection;
  if (!source || !target || source === target) return false;
  if (!nodes.find((node) => node.id === source)?.data.plugin.outputs.includes(sourceHandle))
    return false;
  if (!nodes.find((node) => node.id === target)?.data.plugin.inputs.includes(targetHandle))
    return false;
  const stack = [target],
    seen = new Set();
  while (stack.length) {
    const id = stack.pop();
    if (id === source) return false;
    if (seen.has(id)) continue;
    seen.add(id);
    stack.push(...edges.filter((edge) => edge.source === id).map((edge) => edge.target));
  }
  return true;
}

export function defaultsFor(plugin) {
  return Object.fromEntries(
    plugin.parameters.map((parameter) => [
      parameter.name,
      parameter.default !== undefined
        ? structuredClone(parameter.default)
        : parameter.type === 'bool'
          ? false
          : parameter.type === 'int'
            ? 0
            : parameter.type === 'list'
              ? []
              : parameter.type === 'dict'
                ? {}
                : '',
    ]),
  );
}

export const portName = (name) =>
  ({
    data: '数据',
    valid: '通过',
    invalid: '异常',
    matched: '满足',
    unmatched: '不满足',
    unique: '保留',
    duplicates: '重复',
    summary: '摘要',
    normal: '正常',
    outliers: '异常值',
    reference: '参考表',
    missing: '缺失',
    extra: '多余',
    left: '左表',
    right: '右表',
    answer: '标准答案',
    candidate: '待比较',
    differences: '逐格差异',
    fields: '逐列统计',
    review: '待复核',
    suggestions: '纠错候选',
    patches: '人工修订',
    rejected: '拒绝的修订',
  })[name] || name;
export const bytes = (value) =>
  value < 1024
    ? `${value} B`
    : value < 1024 ** 2
      ? `${(value / 1024).toFixed(1)} KB`
      : `${(value / 1024 ** 2).toFixed(1)} MB`;
