import { escapeHtml, money, statusLabels } from '../presentation';
import type { DemoRun, Finding } from '../presentation';
import { scope } from './fixture';

export function demoJson(run: DemoRun, findings: Finding[]) {
  return JSON.stringify({
    kind: 'doccheck-ui-demo-export', synthetic: true, presentation_only: true,
    note: 'Синтетический пример интерфейса. Не результат обработки документов и не канонический CheckResult.',
    run, scope,
    findings: findings.map(({ sources, ...finding }) => ({ ...finding, sources: sources.map(({ id, filename, amount, page, bbox }) => ({ id, filename, amount, page, bbox })) })),
  }, null, 2);
}

export function demoHtml(run: DemoRun, findings: Finding[]) {
  const e = escapeHtml;
  return `<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DocCheck — ${e(run.id)}</title>
<style>body{font:15px/1.6 system-ui,sans-serif;color:#172b2a;max-width:1000px;margin:40px auto;padding:0 24px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}td,th{padding:12px;border-bottom:1px solid #d8e3df;text-align:left}td:nth-child(n+2):nth-child(-n+4){text-align:right;white-space:nowrap}.note{padding:16px;background:#f4f7f6;border:1px solid #d8e3df}section{break-inside:avoid;margin-top:28px}@media print{body{margin:0;max-width:none}button{display:none}}</style>
<h1>DocCheck · Сверка затрат</h1><p class="note"><strong>Демо · синтетические данные.</strong> Отчёт создан из примера интерфейса. Реальные документы не обрабатывались.</p>
<p>Запуск ${e(run.id)} · Договор ${e(scope.contract)} · 01.11.2026–30.11.2026 · ${e(scope.row)}</p>
<table><thead><tr><th>Статья</th><th>В отчёте, ₽</th><th>По документам, ₽</th><th>Разница, ₽</th><th>Статус</th></tr></thead><tbody>${findings.map(f => `<tr><td>${e(f.article)}</td><td>${money(f.reported)}</td><td>${money(f.expected)}</td><td>${money(f.delta, true)}</td><td>${e(statusLabels[f.status])}</td></tr>`).join('')}</tbody></table>
<p>— нет данных, а не ноль. Разница = в отчёте − по документам.</p>
${findings.map(f => `<section><h2>${e(f.article)} · ${e(statusLabels[f.status])}</h2><p>${e(f.explanation)}</p>${f.formula ? `<p>Расчёт: ${e(f.formula)}</p>` : ''}<ul>${f.sources.map(s => `<li>${e(s.filename)} · стр. ${s.page} · ${money(s.amount)} ₽ · область ${e(s.bbox.join(', '))}</li>`).join('') || '<li>Подтверждающий источник отсутствует.</li>'}</ul></section>`).join('')}
<p>Исключён: Демо-акт № 01 (копия).pdf — дубликат; сумма повторно не учтена.</p>
<p>Основание полноты — демо-манифест. Непроверенные показатели не считаются подтверждёнными.</p></html>`;
}

export function downloadFile(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
