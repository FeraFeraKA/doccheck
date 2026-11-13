// Render input facts only. Monetary calculations belong to the Python model.
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const moduleDir = process.env.ARTIFACT_TOOL_MODULE_DIR;
const api = moduleDir
  ? await import(pathToFileURL(createRequire(path.join(moduleDir, '_resolver.cjs')).resolve('@oai/artifact-tool')).href)
  : await import('@oai/artifact-tool');
const { Workbook, SpreadsheetFile } = api;
const [source, output, previewDir] = process.argv.slice(2);
const documents = JSON.parse(await fs.readFile(source, 'utf8'));
const moneyFormat = '#,##0.00;[Red](#,##0.00);-';

function writePayroll(sheet, doc) {
  sheet.getRange('A5:D5').values = [['Код статьи', 'Вид начисления', 'Сумма, руб.', 'Основание']];
  sheet.getRange('A6:D7').values = doc.items.map(
    (item) => [item.article_code, item.label, Number(item.amount), item.basis],
  );
  sheet.getRange('B8').values = [['ИТОГО']];
  sheet.getRange('C8').formulas = [['=SUM(C6:C7)']];
  sheet.getRange('C6:C8').setNumberFormat(moneyFormat);
  sheet.getRange('B8:C8').format.font.bold = true;
  return 'C8';
}

function writeInsurance(sheet, doc) {
  sheet.getRange('A5:D5').values = [
    ['База начислений, руб.', 'Начислено взносов, руб.', 'Код статьи', 'Комментарий'],
  ];
  sheet.getRange('A6:D6').values = [
    [Number(doc.accrual_base), Number(doc.amount), doc.article_code, doc.comment],
  ];
  sheet.getRange('A6:B6').setNumberFormat(moneyFormat);
  return 'B6';
}

if (previewDir) await fs.mkdir(previewDir, { recursive: true });
for (const doc of documents) {
  const payroll = doc.category === 'payroll';
  if (!payroll && doc.category !== 'insurance') throw new Error(`Unknown XLSX layout: ${doc.category}`);
  const wb = Workbook.create();
  const sheet = wb.worksheets.add(payroll ? 'Ведомость' : 'Расчет взносов');
  const range = payroll ? 'A1:D8' : 'A1:D6';
  sheet.showGridLines = false;
  sheet.getRange(range).format.font = { name: 'Arial', size: 10 };
  sheet.getRange(range).format.rowHeight = 22;
  const widths = payroll ? [23, 33, 19, 32] : [26, 28, 17, 36];
  for (const [index, column] of Array.from('ABCD').entries()) {
    sheet.getRange(`${column}:${column}`).format.columnWidth = widths[index];
  }
  sheet.getRange('A1:D1').merge();
  const title = payroll ? 'РАСЧЕТНАЯ ВЕДОМОСТЬ ПО ОПЛАТЕ ТРУДА' : 'РАСЧЕТ СТРАХОВЫХ ВЗНОСОВ';
  sheet.getRange('A1:A3').values = [
    [`${title} — СИНТЕТИЧЕСКИЙ ДОКУМЕНТ`],
    [`Документ: ${doc.number}`],
    [`Проект: ${doc.contract} | Период: ${doc.period_label}`],
  ];
  sheet.getRange('A1:D1').format.font = { name: 'Arial', size: 12, bold: true };
  sheet.getRange('A5:D5').format = { fill: '#E8E8E8', font: { bold: true } };
  const amountCell = payroll ? writePayroll(sheet, doc) : writeInsurance(sheet, doc);
  wb.recalculate();
  const total = sheet.getRange(amountCell).values[0][0];
  if (Number(total).toFixed(2) !== doc.amount) throw new Error(`Wrong total ${doc.id}`);
  const errors = await wb.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!', options: { useRegex: true, maxResults: 5 } });
  if (/"match"/.test(errors.ndjson)) throw new Error(errors.ndjson);
  if (previewDir) {
    const png = await wb.render({ sheetName: sheet.name, range, scale: 1.5, format: 'png' });
    await fs.writeFile(path.join(previewDir, `${doc.id}.png`), new Uint8Array(await png.arrayBuffer()));
  }
  const destination = path.join(output, doc.file);
  await (await SpreadsheetFile.exportXlsx(wb)).save(destination);
  // Export may create a diagnostic sidecar. Keep runtime inputs document-only.
  await fs.rm(`${destination}.inspect.ndjson`, { force: true });
}
