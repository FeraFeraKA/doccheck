import { useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { classes } from '../../shared/lib/classes';
import { formatDecimal, statusLabels } from './reviewResult';
import type { ReviewResult } from './reviewResult';
import './source-context.css';

const tabs = [['source', 'Источник'], ['rule', 'Правило проверки']] as const;
type Panel = (typeof tabs)[number][0];

export function SourceContext({ row, picker, children }: {
  row: ReviewResult['rows'][number];
  picker: ReactNode;
  children: (active: boolean) => ReactNode;
}) {
  const [panel, setPanel] = useState<Panel>('source');
  const id = useId();
  const tablist = useRef<HTMLDivElement>(null);

  return <section className={classes('source-context', panel === 'rule' && 'source-context-show-rule')}>
    <header className="source-context-header">
      <div><h3>{row.label}</h3><span className="checks-status" data-status={row.status}>{statusLabels[row.status]}</span></div>
      <dl>{([
        ['В КФЗ', row.reported_value], ['По документам', row.expected_value], ['Разница', row.delta],
      ] as const).map(([label, amount]) => <div key={label}>
        <dt>{label} · {row.unit}</dt><dd>{formatDecimal(amount)}</dd>
      </div>)}</dl>
      {row.expected_value === null && row.observed_evidence_sum != null &&
        <p>Частичная сумма: {formatDecimal(row.observed_evidence_sum)} {row.unit}</p>}
    </header>
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
      {picker}
      {children(panel === 'source')}
    </div>
    <div className="source-context-rule" role="tabpanel" id={id + '-rule'} tabIndex={0}
      aria-labelledby={id + '-rule-tab'} hidden={panel !== 'rule'}>
      <h3>Основание результата</h3>
      <dl>
        <dt>Правило</dt><dd>{row.calculation.policy_id}</dd>
        <dt>Формула</dt><dd>{row.calculation.formula}</dd>
        <dt>Основание полноты</dt><dd>{row.completeness.reason}</dd>
      </dl>
      {row.reasons.length > 0 && <ul>
        {row.reasons.map((reason) => <li key={reason.code}>{reason.message}</li>)}
      </ul>}
    </div>
  </section>;
}
