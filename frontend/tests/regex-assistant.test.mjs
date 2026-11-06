import test from 'node:test';
import assert from 'node:assert/strict';
import {
  regexBinding,
  regexPatch,
  escapeLiteral,
  testCases,
  canApplyRegex,
} from '../src/regex-assistant.js';

test('binding follows the target node operation', () => {
  assert.equal(regexBinding('validate.regex', 'pattern', {}).mode, 'fullmatch');
  assert.equal(regexBinding('validate.regex', 'pattern', { full_match: false }).mode, 'search');
  assert.deepEqual(regexBinding('text.extract', 'pattern', { group: 2, occurrence: 'last' }), {
    mode: 'extract',
    group: 2,
    occurrence: 'last',
  });
  assert.equal(regexBinding('text.records', 'start_pattern', {}).mode, 'search');
  assert.equal(regexBinding('columns.calculate', 'expression', {}), null);
});

test('literal replacement becomes escaped Python regex and related settings patch together', () => {
  const binding = regexBinding('text.replace', 'search', {
    search: 'a.b[1]',
    regex: false,
    replacement: 'new',
    count: 1,
  });
  assert.equal(binding.pattern, 'a\\.b\\[1\\]');
  assert.equal(escapeLiteral('a+b(c)\\'), 'a\\+b\\(c\\)\\\\');
  const original = { fields: ['备注'], search: 'a.b', regex: false, count: 0 };
  const patch = regexPatch('text.replace', 'search', {
    pattern: 'a\\.b',
    replacement: 'x',
    count: 1,
  });
  assert.deepEqual(
    { ...original, ...patch },
    { fields: ['备注'], search: 'a\\.b', regex: true, replacement: 'x', count: 1 },
  );
});

test('fullmatch and extraction settings stay consistent on apply', () => {
  assert.deepEqual(
    regexPatch('validate.regex', 'pattern', { pattern: '1[0-9]{10}', mode: 'search' }),
    { pattern: '1[0-9]{10}', full_match: false },
  );
  assert.deepEqual(
    regexPatch('text.extract', 'pattern', { pattern: 'id=([0-9]+)', group: 1, occurrence: 'last' }),
    { pattern: 'id=([0-9]+)', group: 1, occurrence: 'last' },
  );
});

test('sample parsing preserves spaces and makes empty-string expectation explicit', () => {
  assert.deepEqual(testCases(' 123\r\nabc\n', '123 \n\n', 'negative'), {
    positive: [' 123', 'abc'],
    negative: ['123 ', ''],
  });
  assert.deepEqual(testCases('', '', 'positive'), { positive: [''], negative: [] });
  assert.deepEqual(testCases('', '', 'skip'), { positive: [], negative: [] });
});

test('apply requires passed tests for the current exact configuration', () => {
  const result = { key: 'current', data: { total: 4, passed: 4 } };
  assert.equal(canApplyRegex(result, 'current'), true);
  assert.equal(canApplyRegex(result, 'edited'), false);
  assert.equal(canApplyRegex({ key: 'current', data: { total: 4, passed: 3 } }, 'current'), false);
  assert.equal(canApplyRegex({ key: 'current', data: { total: 0, passed: 0 } }, 'current'), false);
  assert.equal(canApplyRegex(null, 'current'), false);
});
