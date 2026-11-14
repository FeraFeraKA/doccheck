import { useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { ReviewResult } from './reviewResult';
import './source-context.css';

const tabs = [['source', 'Источник'], ['rule', 'Правило проверки']] as const;
type Panel = (typeof tabs)[number][0];

export function SourceContext({ row, children }: {
  row: ReviewResult['rows'][number];
  children: (active: boolean) => ReactNode;
}) {
  const [panel, setPanel] = useState<Panel>('source');
  const id = useId();
  const tablist = useRef<HTMLDivElement>(null);
  const formula = row.calculation.formula.trim();
  const notes = [...new Set([
    row.completeness.reason.trim(), ...row.reasons.map(({ message }) => message.trim()),
  ])].filter((message) => message && message !== formula);

  return <section className="source-context">
    <div ref={tablist} role="tablist" aria-label="Сведения об источнике" className="source-context-tabs"
      onKeyDown={(event) => {
        if (event.altKey || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const next = event.key === 'Home' ? 'source' : event.key === 'End' ? 'rule' : panel === 'source' ? 'rule' : 'source';
        setPanel(next);
        tablist.current?.querySelectorAll('button')[next === 'source' ? 0 : 1]?.focus();
      }}>
      {tabs.map(([value, label]) => <button key={value} type="button" role="tab"
        id={id + '-' + value + '-tab'} aria-controls={id + '-' + value}
        tabIndex={panel === value ? 0 : -1} aria-selected={panel === value}
        onClick={() => setPanel(value)}>{label}</button>)}
    </div>
    <div className="source-context-preview" role="tabpanel" id={id + '-source'}
      aria-labelledby={id + '-source-tab'} hidden={panel !== 'source'}>
      {children(panel === 'source')}
    </div>
    <div className="source-context-rule" role="tabpanel" id={id + '-rule'} tabIndex={0}
      aria-labelledby={id + '-rule-tab'} hidden={panel !== 'rule'}>
      <h3>{row.label}</h3>
      {formula && <p className="source-rule-formula">{formula}</p>}
      {notes.length > 0 && <ul>
        {notes.map((message) => <li key={message}>{message}</li>)}
      </ul>}
    </div>
  </section>;
}
