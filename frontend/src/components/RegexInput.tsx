import { useState } from 'react';
import { Sparkles } from 'lucide-react';

export type RegexSelection = {
  pattern: string;
  mode: string;
  group: number;
  occurrence: string;
  replacement: string;
  count: number;
};
export type RegexScope = {
  mode: string;
  modes?: string[];
  group?: number;
  occurrence?: string;
  replacement?: string;
  count?: number;
  pattern?: string;
};

export function RegexInput({
  value,
  onChange,
  onApply,
  scope,
  label = '正则表达式',
  id,
  placeholder,
  multiline = false,
}: {
  value: string;
  onChange: (value: string) => void;
  onApply?: (selection: RegexSelection) => void;
  scope: RegexScope;
  label?: string;
  id?: string;
  placeholder?: string;
  multiline?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [Assistant, setAssistant] = useState<typeof import('./RegexAssistant').default | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const common = {
    id,
    'aria-label': label,
    value,
    placeholder,
    spellCheck: false,
    onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      onChange(event.target.value),
  };
  return (
    <div className="regex-input">
      {multiline ? <textarea {...common} rows={2} /> : <input {...common} />}
      <div className="regex-input-tools">
        <button
          type="button"
          className="text-button"
          aria-label={`${label}：打开正则助手`}
          disabled={loading}
          onClick={async () => {
            setLoading(true);
            setError('');
            try {
              const module = await import('./RegexAssistant');
              setAssistant(() => module.default);
              setOpen(true);
            } catch {
              setError('助手加载失败，请刷新页面后重试');
            } finally {
              setLoading(false);
            }
          }}
        >
          <Sparkles size={12} />
          正则助手
        </button>
      </div>
      {loading && <small role="status">正在加载助手…</small>}
      {error && (
        <small role="alert" className="field-error">
          {error}
        </small>
      )}
      {open && Assistant && (
        <Assistant
          initial={{
            pattern: scope.pattern ?? value,
            mode: scope.mode,
            group: scope.group ?? 0,
            occurrence: scope.occurrence ?? 'first',
            replacement: scope.replacement ?? '',
            count: scope.count ?? 0,
          }}
          modes={scope.modes}
          target={label}
          onClose={() => setOpen(false)}
          onApply={(selection) => {
            if (onApply) onApply(selection);
            else onChange(selection.pattern);
            setOpen(false);
          }}
        />
      )}
    </div>
  );
}
