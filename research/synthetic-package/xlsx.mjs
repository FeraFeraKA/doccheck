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
if (previewDir) await fs.mkdir(previewDir, { recursive: true });
for (const doc of documents) {
  const wb = Workbook.create();
  const s = wb.worksheets.add('Ведомость');
  s.showGridLines = false;
  s.getRange('A1:D18').format.font = { name: 'Arial', size: 10 };
  s.getRange('A1:D18').format.rowHeight = 25;
  s.getRange('A1:A18').format.columnWidth = 4;
  s.getRange('B1:B18').format.columnWidth = 40;
  s.getRange('C1:C18').format.columnWidth = 18;
  s.getRange('D1:D18').format.columnWidth = 19;
  for (const row of [1, 2, 3, 4, 5, 6, 17]) s.getRange(`A${row}:D${row}`).merge();
  s.getRange('A1').values = [['СИНТЕТИЧЕСКИЙ ДОКУМЕНТ - НЕ ДЛЯ БУХГАЛТЕРСКОГО УЧЕТА']];
  s.getRange('A1:D1').format.font.size = 8;
  s.getRange('A2').values = [[doc.kind]];
  s.getRange('A2:D2').format.font = { name: 'Arial', size: 14, bold: true };
  s.getRange('A3').values = [[`№ ${doc.number}. Договор № ${doc.contract}`]];
  s.getRange('A4').values = [[doc.company]];
  s.getRange('A5').values = [[`Расчетный период: ${doc.period_start} - ${doc.period_end}`]];
  s.getRange('A6').values = [['Начисленные суммы по договору. Единица измерения: рубль.']];
  s.getRange('A8:D8').values = [['№', 'Исполнитель', 'Дата начисления', 'Начислено, руб.']];
  s.getRange('A8:D8').format = { fill: '#E8E8E8', font: { bold: true }, horizontalAlignment: 'center' };
  const excelDate = (Date.parse(`${doc.date}T00:00:00Z`) - Date.UTC(1899, 11, 30)) / 86400000;
  s.getRange('A9:D11').values = doc.items.map((item, i) => [i + 1, item.label, excelDate, Number(item.amount)]);
  s.getRange('C9:C11').setNumberFormat('dd.mm.yyyy');
  s.getRange('D9:D13').setNumberFormat('#,##0.00');
  s.getRange('B13').values = [['Итого начислено']];
  s.getRange('D13').formulas = [['=ROUND(SUM(D9:D11),2)']];
  s.getRange('A13:D13').format.font.bold = true;
  s.getRange('A13:D13').format.borders = { preset: 'outside', style: 'thin', color: '#999999' };
  s.getRange('A17').values = [['Все лица и реквизиты вымышлены. Ответственный: Синтез У. У.']];
  wb.recalculate();
  const total = s.getRange('D13').values[0][0];
  if (Number(total).toFixed(2) !== doc.amount) throw new Error(`Wrong total ${doc.id}`);
  const errors = await wb.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!', options: { useRegex: true, maxResults: 5 } });
  if (/"match"/.test(errors.ndjson)) throw new Error(errors.ndjson);
  if (previewDir) {
    const png = await wb.render({ sheetName: s.name, range: 'A1:D18', scale: 1.5, format: 'png' });
    await fs.writeFile(path.join(previewDir, `${doc.id}.png`), new Uint8Array(await png.arrayBuffer()));
  }
  const destination = path.join(output, doc.file);
  await (await SpreadsheetFile.exportXlsx(wb)).save(destination);
  // Export may create a diagnostic sidecar. Keep runtime inputs document-only.
  await fs.rm(`${destination}.inspect.ndjson`, { force: true });
}
