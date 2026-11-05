// Display the backend verdict. Rounded percentages never decide whether a submission passes.
export function scoreCard(values) {
  if (!values || !['是', '否'].includes(values['达标'])) return null;
  const score = Number(values['正确率']);
  const threshold = Number(values['阈值']);
  if (
    !Number.isFinite(score) ||
    !Number.isFinite(threshold) ||
    score < 0 ||
    score > 1 ||
    threshold < 0 ||
    threshold > 1
  )
    return null;
  const percent = (value) =>
    new Intl.NumberFormat('zh-CN', { style: 'percent', maximumFractionDigits: 4 }).format(value);
  return {
    score: percent(score),
    exact: values['正确率'],
    threshold: percent(threshold),
    passed: values['达标'] === '是',
    unit: values['评分单位'] === 'cell' ? '单元格正确率' : '整行正确率',
    counts: (values['评分单位'] === 'cell'
      ? ['正确单元格', '单元格总数', '缺失行', '多余行']
      : ['正确行', '标准行', '缺失行', '多余行']
    ).map((key) => ({
      label: { 正确单元格: '正确格', 单元格总数: '总格数' }[key] || key,
      value: values[key] ?? '—',
    })),
    profile: values['口径'] ?? '',
  };
}
