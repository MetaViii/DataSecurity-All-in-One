import test from 'node:test';
import assert from 'node:assert/strict';
import { filterPlugins, pluginDraftError, refreshNodePlugins } from '../src/plugin-manager.js';

test('plugin draft check enforces actual UTF-8 bytes and prevents path-shaped filenames', () => {
  assert.equal(pluginDraftError('cleaner.py', '# 中文\nPLUGINS = []'), '');
  assert.match(pluginDraftError('../cleaner.py', 'x'), /目录/);
  assert.match(pluginDraftError('cleaner.py', '中'.repeat(90000)), /256 KiB/);
  assert.match(pluginDraftError('cleaner.py', ' \n '), /源码/);
});

test('refresh preserves graph/config while marking disabled plugins and restoring them', () => {
  const old = { id: 'custom.clean', name: 'Old', inputs: ['rows'] };
  const nodes = [
    {
      id: 'n1',
      position: { x: 1, y: 2 },
      data: { plugin: old, config: { field: '姓名' }, label: '我的节点' },
    },
  ];
  const disabled = refreshNodePlugins(nodes, []);
  assert.equal(disabled[0].data.unknown, true);
  assert.equal(disabled[0].data.plugin, old);
  const enabled = refreshNodePlugins(disabled, [{ ...old, name: 'New' }]);
  assert.equal(enabled[0].data.unknown, false);
  assert.equal(enabled[0].data.plugin.name, 'New');
  assert.deepEqual(enabled[0].data.config, { field: '姓名' });
  assert.equal(enabled[0].data.label, '我的节点');
  assert.equal(nodes[0].data.unknown, undefined);
});

test('search includes all plugins regardless of common scope and matches categories', () => {
  const plugins = [
    { id: 'csv.read', name: 'CSV读取', description: '', category: '输入' },
    { id: 'custom.clean', name: '扩展清洗', description: '我的功能', category: '拓展' },
  ];
  assert.deepEqual(
    filterPlugins(plugins, '', 'common').map((p) => p.id),
    ['csv.read'],
  );
  assert.deepEqual(
    filterPlugins(plugins, ' 拓展 ', 'common').map((p) => p.id),
    ['custom.clean'],
  );
  assert.equal(filterPlugins(plugins, '', 'all').length, 2);
});
