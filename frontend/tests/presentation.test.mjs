import test from 'node:test';
import assert from 'node:assert/strict';
import { choiceLabel, draftProblems, parameterLabel } from '../src/presentation.js';

test('Chinese labels preserve unknown plugin keys and choice values', () => {
  assert.equal(parameterLabel('encoding'), '字符编码');
  assert.equal(choiceLabel('keep', 'last'), '保留最后一条');
  assert.equal(parameterLabel('my_custom_parameter'), 'my_custom_parameter');
  assert.equal(choiceLabel('mode', 'custom_mode'), 'custom_mode');
});

test('draft hints find missing connections, required fields and unknown plugins', () => {
  const source = {
    id: 'read',
    data: {
      plugin: { inputs: [], parameters: [{ name: 'path', required: true }] },
      config: { path: '' },
    },
  };
  const transform = {
    id: 'clean',
    data: {
      unknown: true,
      plugin: { inputs: ['data'], parameters: [{ name: 'fields', required: true }] },
      config: { fields: [] },
    },
  };
  const problems = draftProblems([source, transform], []);
  assert.equal(problems.length, 4);
  assert.ok(problems.some((item) => item.node === 'read' && item.message.includes('文件路径')));
  assert.ok(problems.some((item) => item.node === 'clean' && item.message.includes('连接')));
});

test('false, zero and metadata defaults are valid required values', () => {
  const node = {
    id: 'a',
    data: {
      plugin: {
        inputs: ['data'],
        parameters: [
          { name: 'enabled', required: true },
          { name: 'count', required: true },
          { name: 'mode', required: true, default: 'head' },
        ],
      },
      config: { enabled: false, count: 0 },
    },
  };
  assert.deepEqual(draftProblems([node], [{ target: 'a', targetHandle: 'data' }]), []);
});
