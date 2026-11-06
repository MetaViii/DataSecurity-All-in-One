// Match the actual operation used by each node; this file does not run regexes.
export const escapeLiteral = (value) => String(value ?? '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

export function regexBinding(plugin, parameter, config) {
  if (plugin === 'validate.regex' && parameter === 'pattern')
    return {
      mode: config.full_match === false ? 'search' : 'fullmatch',
      modes: ['fullmatch', 'search'],
    };
  if (plugin === 'text.extract' && parameter === 'pattern')
    return {
      mode: 'extract',
      group: Number(config.group ?? 1),
      occurrence: config.occurrence || 'first',
    };
  if (plugin === 'text.replace' && parameter === 'search')
    return {
      mode: 'replace',
      replacement: String(config.replacement ?? ''),
      count: Number(config.count ?? 0),
      pattern: config.regex ? String(config.search ?? '') : escapeLiteral(config.search),
    };
  if (plugin === 'text.records' && parameter === 'start_pattern') return { mode: 'search' };
  return null;
}

export function regexPatch(plugin, parameter, selection) {
  const patch = { [parameter]: selection.pattern };
  if (plugin === 'validate.regex') patch.full_match = selection.mode === 'fullmatch';
  if (plugin === 'text.extract') {
    patch.group = selection.group;
    patch.occurrence = selection.occurrence;
  }
  if (plugin === 'text.replace') {
    patch.regex = true;
    patch.replacement = selection.replacement;
    patch.count = selection.count;
  }
  return patch;
}

export function testCases(positive, negative, empty) {
  const lines = (value) => value.split(/\r?\n/).filter((line) => line !== '');
  const result = { positive: lines(positive), negative: lines(negative) };
  if (empty === 'positive') result.positive.push('');
  if (empty === 'negative') result.negative.push('');
  return result;
}

export function canApplyRegex(result, currentKey) {
  return Boolean(
    result &&
      result.key === currentKey &&
      result.data.total > 0 &&
      result.data.passed === result.data.total,
  );
}
