export const MAX_PLUGIN_BYTES = 256 * 1024;

// These checks are feedback only. Python validates the file and its contract on install.
export function pluginDraftError(filename, source) {
  if (!filename.trim()) return '填写插件文件名，例如 my_cleaner.py';
  if (!/\.py$/i.test(filename) || /[\\/]/.test(filename))
    return '请使用单个 .py 文件名，不要填写目录';
  if (!source.trim()) return '先导入 Python 文件、选择模板，或粘贴源码';
  if (new TextEncoder().encode(source).byteLength > MAX_PLUGIN_BYTES) return '插件源码最多 256 KiB';
  return '';
}

export function refreshNodePlugins(nodes, plugins) {
  const lookup = new Map(plugins.map((plugin) => [plugin.id, plugin]));
  return nodes.map((node) => {
    const plugin = lookup.get(node.data.plugin.id);
    return {
      ...node,
      data: { ...node.data, plugin: plugin || node.data.plugin, unknown: !plugin },
    };
  });
}

const common = new Set([
  'csv.read',
  'xlsx.read',
  'json.read',
  'text.clean',
  'values.map',
  'values.fill',
  'rows.filter',
  'rows.deduplicate',
  'validate.rules',
  'validate.identity',
  'tables.join',
  'tables.score',
  'tables.fuzzy_lookup',
  'group.aggregate',
  'profile.summary',
  'csv.write',
  'xlsx.write',
]);

export function filterPlugins(plugins, search, scope) {
  const query = search.trim().toLocaleLowerCase();
  return plugins.filter((plugin) => {
    if (query)
      return `${plugin.name} ${plugin.id} ${plugin.description} ${plugin.category || ''}`
        .toLocaleLowerCase()
        .includes(query);
    return scope === 'all' || common.has(plugin.id) || plugin.id.startsWith('local.');
  });
}
