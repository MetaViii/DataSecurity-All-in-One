import { CheckCircle2, CircleAlert } from 'lucide-react';
import { scoreCard } from '../scoring.js';
import type { DataRow } from '../types';

export function ScoreSummary({ row }: { row: DataRow }) {
  const score = scoreCard(row.values);
  if (!score) return null;
  return (
    <div className={`score-summary ${score.passed ? 'passed' : 'failed'}`}>
      <div className="score-headline">
        {score.passed ? <CheckCircle2 size={20} /> : <CircleAlert size={20} />}
        <div>
          <span>{score.unit}</span>
          <strong title={`完整数值：${score.exact}`}>{score.score}</strong>
        </div>
        <span className="score-verdict">
          {score.passed ? '达到本地阈值' : '未达到本地阈值'} · {score.threshold}
        </span>
      </div>
      <div className="score-counts">
        {score.counts.map((item) => (
          <div key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>
      <p>{score.profile}。本结果依赖所连接的标准答案与当前评分配置。</p>
    </div>
  );
}
