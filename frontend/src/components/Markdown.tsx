import type { ReactNode } from 'react';
import { documentTarget } from '../documentation.js';

// A small renderer for our bundled guides. HTML is always treated as text.
function inline(text: string, onNavigate?: (name: string) => void): ReactNode[] {
  const parts: ReactNode[] = [];
  const tokens = /\[([^\]]+)\]\(([^)]+)\)|`([^`]+)`|\*\*([^*]+)\*\*/g;
  let previous = 0;
  for (const match of text.matchAll(tokens)) {
    const index = match.index!;
    parts.push(text.slice(previous, index));
    const key = `${index}-${parts.length}`;
    if (match[1]) {
      parts.push(
        /^https?:\/\//i.test(match[2]) ? (
          <a key={key} href={match[2]} target="_blank" rel="noreferrer">
            {match[1]} ↗
          </a>
        ) : onNavigate && documentTarget(match[2]) ? (
          <button
            key={key}
            className="doc-link"
            onClick={() => onNavigate(documentTarget(match[2])!)}
          >
            {match[1]}
          </button>
        ) : (
          <span key={key}>{match[1]}</span>
        ),
      );
    } else if (match[3]) parts.push(<code key={key}>{match[3]}</code>);
    else parts.push(<strong key={key}>{match[4]}</strong>);
    previous = index + match[0].length;
  }
  parts.push(text.slice(previous));
  return parts;
}

export function Markdown({
  content,
  onNavigate,
}: {
  content: string;
  onNavigate?: (name: string) => void;
}) {
  const renderInline = (text: string) => inline(text, onNavigate);
  const lines = content.replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  const cells = (line: string) =>
    line
      .trim()
      .replace(/^\||\|$/g, '')
      .split('|')
      .map((cell) => cell.trim());
  let i = 0;
  while (i < lines.length) {
    const line = lines[i],
      key = i;
    if (!line.trim()) {
      i++;
      continue;
    }
    if (line.startsWith('```')) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) code.push(lines[i++]);
      i++;
      blocks.push(
        <pre key={key}>
          <code>{code.join('\n')}</code>
        </pre>,
      );
      continue;
    }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      blocks.push(
        heading[1].length === 1 ? (
          <h1 key={key}>{renderInline(heading[2])}</h1>
        ) : (
          <h2 key={key}>{renderInline(heading[2])}</h2>
        ),
      );
      i++;
      continue;
    }
    if (line.includes('|') && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] || '')) {
      const header = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim())
        rows.push(cells(lines[i++]));
      blocks.push(
        <div className="docs-table" key={key}>
          <table>
            <thead>
              <tr>
                {header.map((cell, n) => (
                  <th key={n}>{renderInline(cell)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, n) => (
                <tr key={n}>
                  {row.map((cell, m) => (
                    <td key={m}>{renderInline(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    const list = /^\s*(?:[-*]|\d+\.)\s+/.test(line);
    if (list) {
      const ordered = /^\s*\d+\./.test(line),
        items: ReactNode[] = [];
      while (i < lines.length && /^\s*(?:[-*]|\d+\.)\s+/.test(lines[i])) {
        items.push(
          <li key={i}>{renderInline(lines[i++].replace(/^\s*(?:[-*]|\d+\.)\s+/, ''))}</li>,
        );
      }
      blocks.push(ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>);
      continue;
    }
    const paragraph = [line];
    i++;
    while (i < lines.length && lines[i].trim() && !/^(?:#|```|[-*] |\d+\. |\|)/.test(lines[i]))
      paragraph.push(lines[i++]);
    blocks.push(<p key={key}>{renderInline(paragraph.join('\n'))}</p>);
  }
  return <>{blocks}</>;
}
