import { useEffect, useRef, useState } from 'react';
import { Code2, Plus, X } from 'lucide-react';
import type { Parameter } from '../types';
import { choiceLabel, parameterLabel } from '../presentation.js';

type Rule = Record<string, unknown>;
type EditorProps = { value: unknown; onChange: (value: unknown) => void; fields: string[] };
const string = (value: unknown) => String(value ?? '');
const list = (value: unknown): Rule[] => (Array.isArray(value) ? value : []);

export function FieldInput({
  value,
  onChange,
  fields,
  label = '字段',
  id,
}: {
  value: unknown;
  onChange: (value: string) => void;
  fields: string[];
  label?: string;
  id?: string;
}) {
  const optionsId = `fields-${id || label.replace(/\s/g, '-')}`;
  return (
    <>
      <input
        id={id}
        aria-label={label}
        list={optionsId}
        placeholder="输入或选择字段"
        value={string(value)}
        onChange={(event) => onChange(event.target.value)}
      />
      <datalist id={optionsId}>
        {fields.map((field) => (
          <option key={field} value={field} />
        ))}
      </datalist>
    </>
  );
}

function JsonEditor({ value, onChange }: { value: unknown; onChange: (value: unknown) => void }) {
  const format = (item: unknown) =>
    typeof item === 'string' ? item : JSON.stringify(item, null, 2);
  const [draft, setDraft] = useState(format(value)),
    focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setDraft(format(value));
  }, [value]);
  let error = '';
  try {
    JSON.parse(draft);
  } catch {
    error = 'JSON 尚不完整，运行前请修正';
  }
  return (
    <>
      <textarea
        className={`json-editor ${error ? 'invalid-input' : ''}`}
        aria-label="JSON 参数"
        value={draft}
        spellCheck={false}
        onFocus={() => {
          focused.current = true;
        }}
        onBlur={() => {
          focused.current = false;
          if (!error) setDraft(JSON.stringify(JSON.parse(draft), null, 2));
        }}
        onChange={(event) => {
          setDraft(event.target.value);
          try {
            onChange(JSON.parse(event.target.value));
          } catch {
            onChange(event.target.value);
          }
        }}
      />
      {error && <small className="field-error">{error}</small>}
    </>
  );
}

function NamesEditor({ value, onChange, fields }: EditorProps) {
  const items: string[] = Array.isArray(value) ? value : [];
  const [draft, setDraft] = useState('');
  const add = (name: string) => {
    if (name && !items.includes(name)) onChange([...items, name]);
    setDraft('');
  };
  return (
    <div className="names-editor">
      <div className="field-chips">
        {items.map((name, index) => (
          <span className="field-chip" key={`${name}-${index}`}>
            {name}
            <button
              aria-label={`移除字段 ${name}`}
              onClick={() => onChange(items.filter((_, position) => position !== index))}
            >
              <X size={11} />
            </button>
          </span>
        ))}
      </div>
      <div className="inline-form">
        <input
          aria-label="添加字段名称"
          placeholder="字段名，回车添加"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              add(draft);
            }
          }}
        />
        <button className="icon-button" title="添加字段" onClick={() => add(draft)}>
          <Plus size={14} />
        </button>
      </div>
      {fields.length > 0 && (
        <select aria-label="从上游添加字段" value="" onChange={(event) => add(event.target.value)}>
          <option value="">从上游字段中选择…</option>
          {fields
            .filter((field) => !items.includes(field))
            .map((field) => (
              <option value={field} key={field}>
                {field}
              </option>
            ))}
        </select>
      )}
    </div>
  );
}

function ExtractionEditor({ value, onChange }: EditorProps) {
  const rules = list(value);
  const update = (index: number, patch: Rule) =>
    onChange(rules.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)));
  return (
    <div className="extraction-rules">
      {rules.map((rule, index) => (
        <div className="extraction-rule" key={index}>
          <div>
            <input
              aria-label={`规则${index + 1}分类标签`}
              placeholder="分类标签，如 idcard"
              value={string(rule.label)}
              onChange={(event) => update(index, { label: event.target.value })}
            />
            <button
              className="icon-button"
              title="删除提取规则"
              onClick={() => onChange(rules.filter((_, i) => i !== index))}
            >
              <X size={13} />
            </button>
          </div>
          <textarea
            aria-label={`规则${index + 1}正则表达式`}
            rows={2}
            placeholder="正则表达式，注意数字边界"
            value={string(rule.pattern)}
            spellCheck={false}
            onChange={(event) => update(index, { pattern: event.target.value })}
          />
          <label>
            捕获组{' '}
            <input
              aria-label={`规则${index + 1}捕获组`}
              type="number"
              min={0}
              value={Number(rule.group ?? 0)}
              onChange={(event) => update(index, { group: Number(event.target.value) })}
            />
          </label>
        </div>
      ))}
      <button
        className="text-button"
        onClick={() => onChange([...rules, { label: '', pattern: '', group: 0 }])}
      >
        <Plus size={12} /> 添加提取规则
      </button>
    </div>
  );
}

const operations = [
  ['eq', '等于'],
  ['ne', '不等于'],
  ['contains', '包含'],
  ['not_contains', '不包含'],
  ['regex', '匹配正则'],
  ['length', '长度范围'],
  ['gt', '数值 >'],
  ['gte', '数值 ≥'],
  ['lt', '数值 <'],
  ['lte', '数值 ≤'],
  ['empty', '为空'],
  ['not_empty', '不为空'],
];
function ConditionsEditor({ value, onChange, fields }: EditorProps) {
  const rules = list(value);
  const update = (index: number, patch: Rule) =>
    onChange(rules.map((rule, position) => (position === index ? { ...rule, ...patch } : rule)));
  return (
    <div className="rule-editor">
      {rules.map((rule, index) => (
        <div className="rule-card" key={index}>
          <div className="rule-title">
            <span>条件 {index + 1}</span>
            <button
              className="icon-button"
              aria-label={`删除条件 ${index + 1}`}
              onClick={() => onChange(rules.filter((_, position) => position !== index))}
            >
              <X size={13} />
            </button>
          </div>
          <div className="rule-pair">
            <FieldInput
              value={rule.field}
              onChange={(field) => update(index, { field })}
              fields={fields}
              label={`条件 ${index + 1} 字段`}
            />
            <select
              aria-label={`条件 ${index + 1} 运算符`}
              value={string(rule.op || 'eq')}
              onChange={(event) => {
                const op = event.target.value;
                const next: Rule = {
                  field: rule.field,
                  op,
                  ...(op === 'length'
                    ? { min: 0, max: 20 }
                    : ['empty', 'not_empty'].includes(op)
                      ? {}
                      : { value: '' }),
                };
                onChange(rules.map((item, position) => (position === index ? next : item)));
              }}
            >
              {operations.map(([key, name]) => (
                <option value={key} key={key}>
                  {name}
                </option>
              ))}
            </select>
          </div>
          {rule.op === 'length' ? (
            <div className="inline-form">
              <input
                aria-label={`条件 ${index + 1} 最小长度`}
                type="number"
                value={Number(rule.min ?? 0)}
                onChange={(event) => update(index, { min: Number(event.target.value) })}
              />
              <span>至</span>
              <input
                aria-label={`条件 ${index + 1} 最大长度`}
                type="number"
                value={Number(rule.max ?? 20)}
                onChange={(event) => update(index, { max: Number(event.target.value) })}
              />
            </div>
          ) : (
            !['empty', 'not_empty'].includes(string(rule.op)) && (
              <input
                aria-label={`条件 ${index + 1} 比较值`}
                placeholder={rule.op === 'regex' ? 'Python 正则表达式' : '比较值（字符串）'}
                value={string(rule.value)}
                onChange={(event) => update(index, { value: event.target.value })}
              />
            )
          )}
        </div>
      ))}
      <button
        className="add-rule"
        onClick={() => onChange([...rules, { field: '', op: 'eq', value: '' }])}
      >
        <Plus size={13} />
        添加条件
      </button>
    </div>
  );
}

function ValidationEditor({ value, onChange, fields }: EditorProps) {
  const rules = list(value),
    types = [
      ['required', '必填'],
      ['regex', '正则格式'],
      ['length', '字符长度'],
      ['number', '有效数值'],
      ['range', '数值范围'],
      ['enum', '允许值'],
      ['unique', '唯一值'],
      ['date', '有效日期'],
      ['equals_field', '等于另一字段'],
    ];
  const update = (index: number, patch: Rule) =>
    onChange(rules.map((rule, position) => (position === index ? { ...rule, ...patch } : rule)));
  return (
    <div className="rule-editor">
      {rules.map((rule, index) => (
        <div className="rule-card" key={index}>
          <div className="rule-title">
            <span>规则 {index + 1}</span>
            <button
              className="icon-button"
              aria-label="删除校验规则"
              onClick={() => onChange(rules.filter((_, position) => position !== index))}
            >
              <X size={13} />
            </button>
          </div>
          <div className="rule-pair">
            <FieldInput
              value={rule.field}
              onChange={(field) => update(index, { field })}
              fields={fields}
              label={`规则 ${index + 1} 字段`}
            />
            <select
              aria-label={`规则 ${index + 1} 类型`}
              value={string(rule.check)}
              onChange={(event) => {
                const check = event.target.value;
                const extra =
                  check === 'regex'
                    ? { pattern: '' }
                    : ['length', 'range'].includes(check)
                      ? { min: check === 'length' ? 0 : '0', max: check === 'length' ? 20 : '100' }
                      : check === 'enum'
                        ? { values: [] }
                        : check === 'equals_field'
                          ? { other: '' }
                          : check === 'date'
                            ? { format: '' }
                            : {};
                onChange(
                  rules.map((item, position) =>
                    position === index ? { field: rule.field, check, ...extra } : item,
                  ),
                );
              }}
            >
              {types.map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          {rule.check === 'regex' && (
            <input
              aria-label="校验正则"
              placeholder="完整匹配的正则表达式"
              value={string(rule.pattern)}
              onChange={(event) => update(index, { pattern: event.target.value })}
            />
          )}
          {['length', 'range'].includes(string(rule.check)) && (
            <div className="inline-form">
              <input
                aria-label="最小值"
                placeholder="最小值"
                value={string(rule.min)}
                onChange={(event) =>
                  update(index, {
                    min: rule.check === 'length' ? Number(event.target.value) : event.target.value,
                  })
                }
              />
              <span>至</span>
              <input
                aria-label="最大值"
                placeholder="最大值"
                value={string(rule.max)}
                onChange={(event) =>
                  update(index, {
                    max: rule.check === 'length' ? Number(event.target.value) : event.target.value,
                  })
                }
              />
            </div>
          )}
          {rule.check === 'enum' && (
            <input
              aria-label="允许的值"
              placeholder="允许值，用英文逗号分隔"
              value={Array.isArray(rule.values) ? rule.values.join(',') : ''}
              onChange={(event) => update(index, { values: event.target.value.split(',') })}
            />
          )}
          {rule.check === 'equals_field' && (
            <FieldInput
              label="比较字段"
              value={rule.other}
              onChange={(other) => update(index, { other })}
              fields={fields}
            />
          )}
          {rule.check === 'date' && (
            <input
              aria-label="日期格式"
              placeholder="留空按 ISO 解析，或 %Y-%m-%d"
              value={string(rule.format)}
              onChange={(event) => update(index, { format: event.target.value })}
            />
          )}
          <input
            aria-label="失败提示"
            className="quiet-input"
            placeholder="自定义失败原因（可选）"
            value={string(rule.message)}
            onChange={(event) => update(index, { message: event.target.value })}
          />
        </div>
      ))}
      <button
        className="add-rule"
        onClick={() => onChange([...rules, { field: '', check: 'required' }])}
      >
        <Plus size={13} />
        添加校验规则
      </button>
    </div>
  );
}

function SortEditor({ value, onChange, fields }: EditorProps) {
  const rules = list(value),
    update = (index: number, patch: Rule) =>
      onChange(rules.map((rule, position) => (position === index ? { ...rule, ...patch } : rule)));
  return (
    <div className="rule-editor">
      {rules.map((rule, index) => (
        <div className="rule-card" key={index}>
          <div className="rule-title">
            <span>优先级 {index + 1}</span>
            <button
              className="icon-button"
              aria-label="删除排序项"
              onClick={() => onChange(rules.filter((_, position) => position !== index))}
            >
              <X size={13} />
            </button>
          </div>
          <FieldInput
            value={rule.field}
            onChange={(field) => update(index, { field })}
            fields={fields}
            label={`排序字段 ${index + 1}`}
          />
          <div className="rule-pair">
            <select
              value={string(rule.type || 'text')}
              onChange={(event) => update(index, { type: event.target.value })}
            >
              <option value="text">文本</option>
              <option value="number">数值</option>
              <option value="date">日期</option>
            </select>
            <select
              value={string(rule.direction || 'asc')}
              onChange={(event) => update(index, { direction: event.target.value })}
            >
              <option value="asc">升序</option>
              <option value="desc">降序</option>
            </select>
          </div>
          {rule.type === 'date' && (
            <input
              placeholder="日期格式（可选）"
              value={string(rule.format)}
              onChange={(event) => update(index, { format: event.target.value })}
            />
          )}
        </div>
      ))}
      <button
        className="add-rule"
        onClick={() => onChange([...rules, { field: '', type: 'text', direction: 'asc' }])}
      >
        <Plus size={13} />
        添加排序字段
      </button>
    </div>
  );
}

function AggregateEditor({ value, onChange, fields }: EditorProps) {
  const rules = list(value),
    update = (index: number, patch: Rule) =>
      onChange(rules.map((rule, position) => (position === index ? { ...rule, ...patch } : rule)));
  return (
    <div className="rule-editor">
      {rules.map((rule, index) => (
        <div className="rule-card" key={index}>
          <div className="rule-title">
            <span>统计项 {index + 1}</span>
            <button
              className="icon-button"
              aria-label="删除统计项"
              onClick={() => onChange(rules.filter((_, position) => position !== index))}
            >
              <X size={13} />
            </button>
          </div>
          <div className="rule-pair">
            <select
              value={string(rule.op || 'count')}
              onChange={(event) => update(index, { op: event.target.value })}
            >
              {[
                ['count', '记录数'],
                ['sum', '求和'],
                ['mean', '平均值'],
                ['min', '最小值'],
                ['max', '最大值'],
                ['distinct_count', '不同值数量'],
              ].map(([key, name]) => (
                <option value={key} key={key}>
                  {name}
                </option>
              ))}
            </select>
            <input
              aria-label="统计结果名称"
              placeholder="结果名称"
              value={string(rule.output)}
              onChange={(event) => update(index, { output: event.target.value })}
            />
          </div>
          {rule.op !== 'count' && (
            <FieldInput
              value={rule.field}
              onChange={(field) => update(index, { field })}
              fields={fields}
              label="统计字段"
            />
          )}
        </div>
      ))}
      <button
        className="add-rule"
        onClick={() =>
          onChange([...rules, { op: 'count', field: '', output: `统计${rules.length + 1}` }])
        }
      >
        <Plus size={13} />
        添加统计项
      </button>
    </div>
  );
}

function MappingEditor({ value, onChange, fields }: EditorProps) {
  const entries =
    value && typeof value === 'object' && !Array.isArray(value) ? Object.entries(value) : [];
  const update = (index: number, key: string, target: unknown) =>
    onChange(
      Object.fromEntries(
        entries.map((entry, position) => (position === index ? [key, target] : entry)),
      ),
    );
  return (
    <div className="rule-editor">
      {entries.map(([key, target], index) => (
        <div className="mapping-row" key={index}>
          <FieldInput
            value={key}
            onChange={(field) => update(index, field, target)}
            fields={fields}
            label={`原字段 ${index + 1}`}
          />
          <span>→</span>
          <input
            aria-label={`新字段 ${index + 1}`}
            placeholder="新名称"
            value={string(target)}
            onChange={(event) => update(index, key, event.target.value)}
          />
          <button
            className="icon-button"
            aria-label="删除映射"
            onClick={() =>
              onChange(Object.fromEntries(entries.filter((_, position) => position !== index)))
            }
          >
            <X size={12} />
          </button>
        </div>
      ))}
      <button className="add-rule" onClick={() => onChange({ ...(value as object), '': '' })}>
        <Plus size={13} />
        添加映射
      </button>
    </div>
  );
}

function CasesEditor({ value, onChange, fields }: EditorProps) {
  const rules = list(value),
    update = (index: number, patch: Rule) =>
      onChange(rules.map((rule, position) => (position === index ? { ...rule, ...patch } : rule)));
  return (
    <div className="rule-editor">
      {rules.map((rule, index) => (
        <div className="case-card" key={index}>
          <div className="rule-title">
            <input
              aria-label="分类标签"
              placeholder="分类标签"
              value={string(rule.label)}
              onChange={(event) => update(index, { label: event.target.value })}
            />
            <button
              className="icon-button"
              aria-label="删除分类"
              onClick={() => onChange(rules.filter((_, position) => position !== index))}
            >
              <X size={13} />
            </button>
          </div>
          <select
            value={string(rule.match || 'all')}
            onChange={(event) => update(index, { match: event.target.value })}
          >
            <option value="all">全部条件满足</option>
            <option value="any">任意条件满足</option>
          </select>
          <ConditionsEditor
            value={rule.conditions}
            fields={fields}
            onChange={(conditions) => update(index, { conditions })}
          />
        </div>
      ))}
      <button
        className="add-rule"
        onClick={() =>
          onChange([
            ...rules,
            {
              label: `分类${rules.length + 1}`,
              match: 'all',
              conditions: [{ field: '', op: 'eq', value: '' }],
            },
          ])
        }
      >
        <Plus size={13} />
        添加分类
      </button>
    </div>
  );
}

export function ParameterField({
  parameter,
  value,
  onChange,
  fields,
  id,
}: {
  parameter: Parameter;
  value: unknown;
  onChange: (value: unknown) => void;
  fields: string[];
  id: string;
}) {
  if (value === undefined) value = parameter.default;
  const [jsonMode, setJsonMode] = useState(false);
  const compound = ['list', 'dict'].includes(parameter.type);
  const editors: Record<string, React.ComponentType<EditorProps>> = {
    fields: NamesEditor,
    names: NamesEditor,
    conditions: ConditionsEditor,
    validation_rules: ValidationEditor,
    sort_rules: SortEditor,
    aggregate_rules: AggregateEditor,
    mapping: MappingEditor,
    case_rules: CasesEditor,
    extraction_rules: ExtractionEditor,
  };
  const Editor = editors[parameter.widget || ''];
  let control;
  if (compound)
    control =
      !jsonMode && Editor && typeof value !== 'string' ? (
        <Editor value={value} onChange={onChange} fields={fields} />
      ) : (
        <JsonEditor value={value ?? (parameter.type === 'list' ? [] : {})} onChange={onChange} />
      );
  else if (parameter.type === 'bool')
    control = (
      <label className="switch-line">
        <span>{value ? '已开启' : '已关闭'}</span>
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span className="switch-track" />
      </label>
    );
  else if (parameter.choices?.length)
    control = (
      <select
        id={id}
        value={string(value)}
        onChange={(event) =>
          onChange(parameter.type === 'int' ? Number(event.target.value) : event.target.value)
        }
      >
        {parameter.choices.map((choice) => (
          <option value={string(choice)} key={string(choice)}>
            {choiceLabel(parameter.name, choice)}
          </option>
        ))}
      </select>
    );
  else if (parameter.widget === 'field' || parameter.name === 'field' || parameter.name === 'other')
    control = (
      <FieldInput
        id={id}
        label={parameterLabel(parameter.name)}
        value={value}
        onChange={onChange}
        fields={fields}
      />
    );
  else if (parameter.widget === 'textarea')
    control = (
      <textarea
        id={id}
        rows={4}
        value={string(value)}
        placeholder="例如：[单价] * [数量]"
        onChange={(event) => onChange(event.target.value)}
        spellCheck={false}
      />
    );
  else
    control = (
      <input
        id={id}
        type={parameter.type === 'int' ? 'number' : 'text'}
        value={string(value)}
        onChange={(event) =>
          onChange(
            parameter.type === 'int' && event.target.value !== ''
              ? Number(event.target.value)
              : event.target.value,
          )
        }
      />
    );
  return (
    <div className="parameter-field">
      <div className="parameter-label">
        <label htmlFor={id}>
          {parameterLabel(parameter.name)}
          {parameter.required && <span className="required-dot">*</span>}
        </label>
        {compound && Editor && (
          <button
            className={jsonMode ? 'json-toggle active' : 'json-toggle'}
            title="切换 JSON 编辑"
            onClick={() => setJsonMode((value) => !value)}
          >
            <Code2 size={12} />
            JSON
          </button>
        )}
      </div>
      <p className="field-description">{parameter.description}</p>
      {control}
    </div>
  );
}
