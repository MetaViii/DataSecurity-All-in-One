import test from 'node:test';
import assert from 'node:assert/strict';
import { graphOf, definitionOf, canConnect, executionKey, defaultsFor } from '../src/model.js';

const plugins = [
  { id: 'source', name: '输入', inputs: [], outputs: ['data'], parameters: [] },
  {
    id: 'transform',
    name: '处理',
    inputs: ['data'],
    outputs: ['valid', 'invalid'],
    parameters: [{ name: 'rules', type: 'list', default: [{ field: 'x' }] }],
  },
];
const definition = {
  version: 1,
  name: 'test',
  nodes: [
    { id: 'a', plugin: 'source', config: {}, inputs: {} },
    { id: 'b', plugin: 'transform', config: { rules: [] }, inputs: { data: 'a:data' } },
  ],
  ui: { positions: { b: { x: 650, y: 22 } }, labels: { b: '自定义名称' } },
};

test('named ports, position and label survive JSON roundtrip', () => {
  const graph = graphOf(definition, plugins);
  const roundtrip = definitionOf(graph.nodes, graph.edges, 'test');
  assert.deepEqual(roundtrip.nodes, definition.nodes);
  assert.deepEqual(roundtrip.ui.positions.b, { x: 650, y: 22 });
  assert.equal(roundtrip.ui.labels.b, '自定义名称');
});
test('reject cycles, self links and invalid ports', () => {
  const { nodes, edges } = graphOf(definition, plugins);
  assert.equal(
    canConnect({ source: 'a', target: 'b', sourceHandle: 'data', targetHandle: 'data' }, nodes, []),
    true,
  );
  assert.equal(
    canConnect(
      { source: 'b', target: 'b', sourceHandle: 'valid', targetHandle: 'data' },
      nodes,
      edges,
    ),
    false,
  );
  const more = [...nodes, { ...nodes[1], id: 'c' }];
  assert.equal(
    canConnect({ source: 'c', target: 'b', sourceHandle: 'valid', targetHandle: 'data' }, more, [
      ...edges,
      { source: 'b', target: 'c' },
    ]),
    false,
  );
  assert.equal(
    canConnect(
      { source: 'a', target: 'b', sourceHandle: 'missing', targetHandle: 'data' },
      nodes,
      [],
    ),
    false,
  );
});
test('unknown plugin remains inspectable and keeps its config', () => {
  const graph = graphOf(definition, [plugins[0]]);
  assert.equal(graph.nodes[1].data.unknown, true);
  assert.deepEqual(definitionOf(graph.nodes, graph.edges, 'test').nodes, definition.nodes);
});
test('canvas movement does not invalidate execution data; config does', () => {
  assert.equal(executionKey(definition), executionKey({ ...definition, ui: {}, name: 'renamed' }));
  assert.notEqual(
    executionKey(definition),
    executionKey({ ...definition, nodes: definition.nodes.slice(0, 1) }),
  );
});
test('default configs are independent and malformed connections are rejected', () => {
  const first = defaultsFor(plugins[1]),
    second = defaultsFor(plugins[1]);
  first.rules[0].field = 'changed';
  assert.equal(second.rules[0].field, 'x');
  assert.throws(() =>
    graphOf({ ...definition, nodes: [...definition.nodes, definition.nodes[0]] }, plugins),
  );
  assert.throws(() =>
    graphOf(
      { ...definition, nodes: [{ ...definition.nodes[1], inputs: { data: 'nope:data' } }] },
      plugins,
    ),
  );
});
