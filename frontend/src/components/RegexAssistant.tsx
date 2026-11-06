import { useEffect, useRef, useState } from 'react';
import { Check, LoaderCircle, Play } from 'lucide-react';
import { api } from '../api';
import { canApplyRegex, testCases } from '../regex-assistant.js';
import { Modal } from './Dialogs';
import type { RegexSelection } from './RegexInput';
import './RegexAssistant.css';

type Template = {
  id: string;
  name: string;
  pattern: string;
  search_pattern: string;
  positive: string[];
  negative: string[];
  note: string;
};
type TestRow = {
  sample: string;
  expected: boolean;
  matched: boolean;
  passed: boolean;
  matches: { value: string; start: number; end: number }[];
  output: string | null;
  truncated: boolean;
};
type TestResult = {
  total: number;
  passed: number;
  false_positive: number;
  false_negative: number;
  groups: number;
  seconds: number;
  rows: TestRow[];
};
const modeNames: Record<string, string> = {
  fullmatch: '完整字段校验',
  search: '搜索匹配',
  extract: '提取一项',
  find_all: '提取全部',
  replace: '查找替换',
};

export default function RegexAssistant({
  initial,
  modes,
  target,
  onApply,
  onClose,
}: {
  initial: RegexSelection;
  modes?: string[];
  target: string;
  onApply: (value: RegexSelection) => void;
  onClose: () => void;
}) {
  const [selection, setSelection] = useState(initial);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [tab, setTab] = useState('templates');
  const [selectedTemplate, setSelectedTemplate] = useState('');
  const [positive, setPositive] = useState('');
  const [negative, setNegative] = useState('');
  const [empty, setEmpty] = useState('negative');
  const [builder, setBuilder] = useState({
    prefix: '1',
    suffix: '',
    characters: 'digits',
    custom: '',
    min_length: 10,
    max_length: 10,
    allow_empty: false,
    ignore_case: false,
  });
  const [explanation, setExplanation] = useState<{ pattern: string; lines: string[] } | null>(null);
  const [result, setResult] = useState<{ key: string; data: TestResult } | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [building, setBuilding] = useState(false);
  const mounted = useRef(true);
  const payload = { ...selection, ...testCases(positive, negative, empty) };
  const key = JSON.stringify(payload);
  const fresh = result?.key === key;
  const canApply = canApplyRegex(result, key);
  const update = (patch: Partial<RegexSelection>) => {
    setSelection((value) => ({ ...value, ...patch }));
    setError('');
  };
  useEffect(() => {
    mounted.current = true;
    api<{ templates: Template[] }>('/api/regex/templates')
      .then((value) => {
        if (mounted.current) setTemplates(value.templates);
      })
      .catch((exc) => {
        if (mounted.current) setError((exc as Error).message);
      });
    return () => {
      mounted.current = false;
    };
  }, []);
  const useTemplate = (id: string) => {
    setSelectedTemplate(id);
    const item = templates.find((value) => value.id === id);
    if (!item) return;
    const pattern = selection.mode === 'fullmatch' ? item.pattern : item.search_pattern;
    update({ pattern, group: 0 });
    setPositive(item.positive.join('\n'));
    setNegative(item.negative.join('\n'));
    setEmpty('negative');
    setExplanation({ pattern, lines: [item.note] });
  };
  const build = async () => {
    setBuilding(true);
    setError('');
    try {
      const value = await api<{ pattern: string; explanation: string[] }>(
        '/api/regex/build',
        'POST',
        builder,
      );
      if (mounted.current) {
        update({ pattern: value.pattern, group: 0 });
        setSelectedTemplate('');
        setExplanation({ pattern: value.pattern, lines: value.explanation });
      }
    } catch (exc) {
      if (mounted.current) setError((exc as Error).message);
    } finally {
      if (mounted.current) setBuilding(false);
    }
  };
  const changeMode = (mode: string) => {
    const item = templates.find((value) => value.id === selectedTemplate);
    if (
      item &&
      selection.pattern === (selection.mode === 'fullmatch' ? item.pattern : item.search_pattern)
    ) {
      const pattern = mode === 'fullmatch' ? item.pattern : item.search_pattern;
      update({ mode, pattern });
      setExplanation({ pattern, lines: [item.note] });
    } else update({ mode });
  };
  const test = async () => {
    setBusy(true);
    setError('');
    try {
      const data = await api<TestResult>('/api/regex/test', 'POST', payload);
      if (mounted.current) setResult({ key, data });
    } catch (exc) {
      if (mounted.current) {
        setResult(null);
        setError((exc as Error).message);
      }
    } finally {
      if (mounted.current) setBusy(false);
    }
  };
  return (
    <Modal title="正则助手" onClose={onClose} wide>
      <div className="regex-assistant">
        <div className="regex-assistant-intro">
          <p>
            选择模板或组合规则，用正反例确认后回填。测试在本机使用 Python re，不会运行整个流程。
          </p>
          <span>回填到：{target}</span>
        </div>
        <div className="regex-assistant-layout">
          <section className="regex-builder">
            <div className="regex-tabs" role="tablist" aria-label="生成方式">
              <button
                role="tab"
                aria-selected={tab === 'templates'}
                onClick={() => setTab('templates')}
              >
                常用模板
              </button>
              <button
                role="tab"
                aria-selected={tab === 'builder'}
                onClick={() => setTab('builder')}
              >
                规则组合
              </button>
            </div>
            {tab === 'templates' ? (
              <>
                <label className="regex-label">
                  选择格式
                  <select
                    aria-label="常用模板"
                    value={selectedTemplate}
                    onChange={(event) => useTemplate(event.target.value)}
                  >
                    <option value="">保留当前表达式</option>
                    {templates.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="regex-note">
                  选择模板会填入表达式和一组示例，可继续修改。模板的限制会显示在表达式下方。
                </p>
              </>
            ) : (
              <div className="regex-builder-fields">
                <label className="regex-label">
                  固定前缀
                  <input
                    aria-label="固定前缀"
                    value={builder.prefix}
                    placeholder="可留空，按原文匹配"
                    onChange={(e) => setBuilder({ ...builder, prefix: e.target.value })}
                  />
                </label>
                <label className="regex-label">
                  中间字符
                  <select
                    aria-label="中间字符"
                    value={builder.characters}
                    onChange={(e) => setBuilder({ ...builder, characters: e.target.value })}
                  >
                    {[
                      ['digits', '数字 0～9'],
                      ['letters', '英文字母'],
                      ['lower', '小写字母'],
                      ['upper', '大写字母'],
                      ['alnum', '字母或数字'],
                      ['han', '汉字（常用区）'],
                      ['custom', '自定义字符'],
                    ].map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                {builder.characters === 'custom' && (
                  <label className="regex-label">
                    允许的字符
                    <input
                      aria-label="允许的字符"
                      placeholder="逐字列出，如 abc_-；不写范围"
                      value={builder.custom}
                      onChange={(e) => setBuilder({ ...builder, custom: e.target.value })}
                    />
                  </label>
                )}
                <div className="regex-lengths">
                  <label className="regex-label">
                    最小中间长度
                    <input
                      aria-label="最小中间长度"
                      type="number"
                      min={0}
                      max={1000}
                      value={builder.min_length}
                      onChange={(e) =>
                        setBuilder({ ...builder, min_length: Number(e.target.value) })
                      }
                    />
                  </label>
                  <label className="regex-label">
                    最大中间长度
                    <input
                      aria-label="最大中间长度"
                      type="number"
                      min={0}
                      max={1000}
                      value={builder.max_length}
                      onChange={(e) =>
                        setBuilder({ ...builder, max_length: Number(e.target.value) })
                      }
                    />
                  </label>
                </div>
                <label className="regex-label">
                  固定后缀
                  <input
                    aria-label="固定后缀"
                    value={builder.suffix}
                    placeholder="可留空，按原文匹配"
                    onChange={(e) => setBuilder({ ...builder, suffix: e.target.value })}
                  />
                </label>
                <label className="regex-check">
                  <input
                    type="checkbox"
                    checked={builder.allow_empty}
                    onChange={(e) => setBuilder({ ...builder, allow_empty: e.target.checked })}
                  />
                  允许整个值为空
                </label>
                <label className="regex-check">
                  <input
                    type="checkbox"
                    checked={builder.ignore_case}
                    onChange={(e) => setBuilder({ ...builder, ignore_case: e.target.checked })}
                  />
                  忽略英文大小写
                </label>
                <button
                  className="button secondary"
                  disabled={building}
                  onClick={() => void build()}
                >
                  {building && <LoaderCircle size={13} className="spin" />}生成表达式
                </button>
              </div>
            )}
          </section>
          <section className="regex-workarea">
            <div className="regex-pattern-heading">
              <strong>表达式</strong>
              {modes && modes.length > 1 ? (
                <select
                  aria-label="匹配方式"
                  value={selection.mode}
                  onChange={(e) => changeMode(e.target.value)}
                >
                  {modes.map((mode) => (
                    <option key={mode} value={mode}>
                      {modeNames[mode]}
                    </option>
                  ))}
                </select>
              ) : (
                <span>{modeNames[selection.mode]}</span>
              )}
            </div>
            <textarea
              aria-label="助手正则表达式"
              className="regex-code"
              rows={2}
              value={selection.pattern}
              onChange={(e) => update({ pattern: e.target.value })}
              spellCheck={false}
              placeholder="只填表达式，不加引号或 /…/"
            />
            {explanation?.pattern === selection.pattern && (
              <div className="regex-explanation">
                {explanation.lines.map((line) => (
                  <p key={line}>{line}</p>
                ))}
              </div>
            )}
            {['extract', 'find_all'].includes(selection.mode) && (
              <div className="regex-operation-options">
                <label className="regex-label">
                  捕获组（0为完整匹配）
                  <input
                    aria-label="助手捕获组"
                    type="number"
                    min={0}
                    max={1000}
                    value={selection.group}
                    onChange={(e) => update({ group: Number(e.target.value) })}
                  />
                </label>
                {selection.mode === 'extract' && (
                  <label className="regex-label">
                    提取顺序
                    <select
                      aria-label="提取顺序"
                      value={selection.occurrence}
                      onChange={(e) => update({ occurrence: e.target.value })}
                    >
                      <option value="first">第一项</option>
                      <option value="last">最后一项</option>
                    </select>
                  </label>
                )}
              </div>
            )}
            {selection.mode === 'find_all' && (
              <p className="regex-note">只测试当前规则；多规则的重叠取舍请在节点预览中检查。</p>
            )}
            {selection.mode === 'replace' && (
              <div className="regex-operation-options">
                <label className="regex-label">
                  替换为
                  <input
                    aria-label="助手替换内容"
                    value={selection.replacement}
                    placeholder={'支持 Python 分组引用，如 \\g<1>'}
                    onChange={(e) => update({ replacement: e.target.value })}
                  />
                </label>
                <label className="regex-label">
                  最多替换（0为全部）
                  <input
                    aria-label="助手替换次数"
                    type="number"
                    min={0}
                    value={selection.count}
                    onChange={(e) => update({ count: Number(e.target.value) })}
                  />
                </label>
              </div>
            )}
            <div className="regex-samples">
              <label className="regex-label">
                正例 · 应命中
                <textarea
                  aria-label="正例"
                  rows={4}
                  placeholder="每行一个样例"
                  value={positive}
                  onChange={(e) => setPositive(e.target.value)}
                  spellCheck={false}
                />
              </label>
              <label className="regex-label">
                反例 · 不应命中
                <textarea
                  aria-label="反例"
                  rows={4}
                  placeholder="每行一个样例"
                  value={negative}
                  onChange={(e) => setNegative(e.target.value)}
                  spellCheck={false}
                />
              </label>
            </div>
            <div className="regex-test-actions">
              <label>
                空字符串
                <select
                  aria-label="空字符串预期"
                  value={empty}
                  onChange={(e) => setEmpty(e.target.value)}
                >
                  <option value="negative">不应命中</option>
                  <option value="positive">应命中</option>
                  <option value="skip">不测试</option>
                </select>
              </label>
              <button
                className="button secondary"
                disabled={busy || building}
                onClick={() => void test()}
              >
                {busy ? <LoaderCircle size={14} className="spin" /> : <Play size={14} />}测试正反例
              </button>
            </div>
            <p className="regex-note">
              每行一例，保留空格、忽略空行。最多100例；多行单元格可在节点预览中检查。全部通过仅表示这些样例符合预期。
            </p>
            {error && (
              <p className="regex-error" role="alert">
                {error}
              </p>
            )}
            {result && (
              <div className="regex-results">
                <div className={`regex-verdict ${fresh && canApply ? 'passed' : ''}`} role="status">
                  {!fresh
                    ? '配置或样例已修改，请重新测试'
                    : `${result.data.passed}/${result.data.total} 个样例通过 · 误匹配 ${result.data.false_positive} · 漏匹配 ${result.data.false_negative}`}
                </div>
                {fresh && (
                  <div className="regex-result-table">
                    <table>
                      <thead>
                        <tr>
                          <th>样例</th>
                          <th>预期 / 实际</th>
                          <th>{selection.mode === 'replace' ? '替换结果' : '命中内容'}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.data.rows.map((row, index) => (
                          <tr key={index} className={row.passed ? '' : 'failed'}>
                            <td>
                              <code>{JSON.stringify(row.sample)}</code>
                            </td>
                            <td>
                              {row.expected ? '命中' : '不命中'} / {row.matched ? '命中' : '不命中'}{' '}
                              {row.passed ? '✓' : '✕'}
                            </td>
                            <td>
                              <code>
                                {selection.mode === 'replace'
                                  ? JSON.stringify(row.output)
                                  : row.matches
                                      .map(
                                        (hit) =>
                                          `${JSON.stringify(hit.value)} [${hit.start},${hit.end})`,
                                      )
                                      .join('；') || '—'}
                                {row.truncated && '（仅展示前20项）'}
                              </code>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      </div>
      <div className="modal-footer regex-assistant-footer">
        <span>{canApply ? '已用当前配置测试，可回填' : '请先测试，全部样例通过后回填'}</span>
        <button className="button secondary" onClick={onClose}>
          取消
        </button>
        <button
          className="button primary"
          disabled={!canApply || busy || building}
          onClick={() => onApply(selection)}
        >
          <Check size={14} />
          回填到节点
        </button>
      </div>
    </Modal>
  );
}
