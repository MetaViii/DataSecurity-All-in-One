import test from 'node:test';
import assert from 'node:assert/strict';
import { scoreCard } from '../src/scoring.js';

test('score card follows exact backend verdict even when displayed percentages round up', () => {
  const card = scoreCard({
    正确率: '0.9499999999999999999',
    阈值: '0.95',
    达标: '否',
    评分单位: 'cell',
    正确行: '19',
    标准行: '20',
    缺失行: '0',
    多余行: '1',
  });
  assert.equal(card.score, '95%');
  assert.equal(card.passed, false);
  assert.equal(card.unit, '单元格正确率');
  assert.equal(card.counts[3].value, '1');
});
test('reject invalid scores and leave ordinary summaries alone', () => {
  assert.equal(scoreCard({ 得分: '0.9' }), null);
  assert.equal(scoreCard({ 正确率: 'NaN', 阈值: '0.95', 达标: '是' }), null);
  assert.equal(scoreCard({ 正确率: '1.1', 阈值: '0.95', 达标: '是' }), null);
});
