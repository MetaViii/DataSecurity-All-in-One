import test from 'node:test';
import assert from 'node:assert/strict';
import { documentTarget } from '../src/documentation.js';

test('documentation navigation only resolves bundled guide names', () => {
  assert.equal(documentTarget('./correction.md#本地评分'), 'correction');
  assert.equal(documentTarget('contest-round2.md'), 'contest-round2');
  assert.equal(documentTarget('../secrets.md'), null);
  assert.equal(documentTarget('constructor'), null);
  assert.equal(documentTarget('javascript:alert(1)'), null);
  assert.equal(documentTarget('https://example.test/correction.md'), null);
});
