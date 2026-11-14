"""Deterministic Russian explanations of reconciliation, never a new decision.

Inputs are runtime records only. No reference answers, prompts, model calls or
external services are used. Native quotations and report cells require a fresh
local file hash check and native reread; scans have document references only.
"""
from __future__ import annotations

from decimal import Decimal
from copy import deepcopy
import hashlib
from pathlib import Path
import re

from .decision_rules import parse_amount, money_string

VERSION = 'reconciliation-explanations-v1'
ROOT = Path(__file__).resolve().parents[2]
LABELS = {'payroll':'Оплата труда', 'insurance':'Страховые взносы',
          'production_overhead':'Общепроизводственные расходы', 'general_admin':'Общехозяйственные расходы',
          'other':'Прочие расходы', 'total':'Общий итог'}
REASONS = {
    'different_contract':'Документ относится к другому договору.',
    'outside_period':'Период документа находится вне проверяемого периода.',
    'extraction_error':'Данные документа не удалось извлечь.',
    'contract_missing':'Договор документа не установлен.',
    'invalid_or_incomplete_period':'Период документа указан неполно или некорректно.',
    'date_and_period_missing':'Не установлены дата и период документа.',
    'period_partially_overlaps_unallocatable_amount':'Период пересекает проверяемый лишь частично; относящаяся к нему сумма не выделена.',
    'category_evidence_invalid':'Доказательство назначения расходов не прошло проверку целостности.',
    'category_not_source_resolved':'Назначение расходов не подтверждено правилами чтения источника.',
    'category_source_abstention':'Правила источника требуют проверки назначения расходов.',
    'category_missing_or_invalid':'Статья затрат не определена.',
    'amount_missing_or_invalid':'Сумма документа отсутствует или не прочитана однозначно.',
    'explicit_identity_context_conflict':'У документов с совпадающим номером расходятся данные вида документа или исполнителя.',
    'conflicting_duplicate':'У сопоставленных документов расходятся суммы или статьи затрат.',
    'unresolved_document_identity_collision':'Возможное совпадение документов не разрешено.',
    'suspected_bare_tail_identity':'Совпадает цифровая часть номера; этого недостаточно для объединения документов.',
    'completeness_unknown':'Полнота представленных источников не подтверждена.',
    'completeness_basis_missing':'Не указано основание заявления о полноте источников.',
    'completeness_declaration_invalid':'Заявление о полноте источников некорректно.',
    'completeness_declaration_conflicting':'Заявление о полноте противоречит перечню недостающих источников.',
    'declared_incomplete_sources':'Для этой области заявлен неполный комплект источников.',
    'report_category_missing_or_invalid':'Статья строки КФЗ не распознана.',
    'reported_amount_missing_or_invalid':'Сумма строки КФЗ не прочитана однозначно.',
    'no_supporting_documents':'В расчёт строки не включены подтверждающие документы.',
    'total_or_constituent_unverified':'Общий итог или хотя бы одна составляющая строка не подтверждены.',
    'report_extraction_error':'КФЗ не удалось прочитать.',
    'report_contract_not_verified':'Договор КФЗ не подтверждён для проверяемого комплекта.',
    'report_stage_not_verified':'Этап КФЗ не подтверждён для проверяемого комплекта.',
    'report_year_not_verified':'Год КФЗ не подтверждён для проверяемого комплекта.',
    'report_period_start_not_verified':'Начало периода КФЗ не подтверждено.',
    'report_period_end_not_verified':'Конец периода КФЗ не подтверждён.',
    'duplicate_hash':'Повтор файла с тем же содержимым не учитывается повторно.',
    'duplicate_business_identity':'Документ сопоставлен с уже учтённым по подтверждённым реквизитам и не учитывается повторно.',
    'duplicate_id':'Повтор записи с тем же идентификатором не учитывается повторно.',
    'not_selected_without_reason':'Документ не включён в расчёт; причина не передана результатом сверки.',
}
RECOMMENDATIONS = {
    'different_contract':'Хранить документ вне расчёта этого договора; проверить его принадлежность отдельно.',
    'outside_period':'Проверить документ в сверке соответствующего периода.',
    'extraction_error':'Предоставить читаемую копию или проверить извлечение документа.',
    'contract_missing':'Уточнить договор по первичному документу.',
    'invalid_or_incomplete_period':'Уточнить даты начала и окончания периода документа.',
    'date_and_period_missing':'Уточнить дату либо полный период документа.',
    'period_partially_overlaps_unallocatable_amount':'Получить документальное распределение суммы по периодам.',
    'category_evidence_invalid':'Повторно проверить исходный файл и привязку доказательства к нему.',
    'category_not_source_resolved':'Проверить назначение выполненных работ по исходному тексту и при необходимости уточнить распределение по статьям.',
    'category_source_abstention':'Проверить отрицания, отмены и смешанное назначение в источнике; получить уточнение до подтверждения суммы.',
    'category_missing_or_invalid':'Уточнить статью затрат по назначению документа.',
    'amount_missing_or_invalid':'Уточнить сумму по читаемому первичному документу.',
    'explicit_identity_context_conflict':'Проверить вид документа, исполнителя и полные реквизиты обеих записей.',
    'conflicting_duplicate':'Сопоставить версии и установить действующий документ до окончательного расчёта.',
    'unresolved_document_identity_collision':'Сопоставить полные реквизиты возможных повторов вручную.',
    'suspected_bare_tail_identity':'Проверить полный номер с префиксом; не объединять только по цифрам.',
    'completeness_unknown':'Подтвердить полноту комплекта либо перечислить недостающие статьи.',
    'completeness_basis_missing':'Указать основание подтверждения полноты источников.',
    'completeness_declaration_invalid':'Исправить заявление о полноте и перечень затронутых статей.',
    'completeness_declaration_conflicting':'Устранить противоречие в заявлении о полноте источников.',
    'declared_incomplete_sources':'Предоставить недостающие источники по указанным статьям.',
    'report_category_missing_or_invalid':'Сверить обозначение статьи в исходной КФЗ.',
    'reported_amount_missing_or_invalid':'Проверить сумму и формулу соответствующей строки КФЗ.',
    'no_supporting_documents':'Проверить наличие относящихся к строке первичных документов.',
    'total_or_constituent_unverified':'Разрешить причины непроверенности строк и проверить общий итог КФЗ.',
}

REVIEW_ACTIONS = {
    'mixed_purpose': 'Запросить разбивку стоимости по статьям затрат и сверить суммы по каждой статье.',
    'explicit_service_denial': 'Уточнить у исполнителя, какие работы фактически выполнены, и запросить исправленный акт при расхождении.',
    'unresolved_request_cancellation': 'Сверить реквизиты отменённой заявки или поручения с реквизитами фактически выполненных работ.',
}


def _amount(value):
    return money_string(parse_amount(value))


def _rubles(value):
    number = parse_amount(value)
    if number is None:
        return 'не установлена'
    precision = max(2, -number.as_tuple().exponent)
    return format(number, f',.{precision}f').replace(',', '\u00a0').replace('.', ',') + ' ₽'


def _reference(document, identifier=None):
    identifier = str(identifier if identifier is not None else document.get('id', ''))
    path = document.get('path') if isinstance(document.get('path'), str) else None
    return {'document_id':identifier, 'name':Path(path).name if path else identifier, 'path':path}


def _local_path(document):
    path = document.get('path')
    digest = document.get('source_hash')
    if not isinstance(path, str) or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        return None
    value = Path(path)
    value = value if value.is_absolute() else ROOT / value
    try:
        return value if value.is_file() and hashlib.sha256(value.read_bytes()).hexdigest() == digest else None
    except OSError:
        return None


def _native(document):
    """An invalid/missing file or a scan yields no invented text locator."""
    path = _local_path(document)
    text = document.get('source_native_text')
    if path is None or path.suffix.lower() not in {'.xlsx','.docx','.pdf'} or not isinstance(text, str):
        return None
    try:
        from .runtime import native_text
        actual = native_text(path)
        return text if isinstance(actual, str) and actual == text and _local_path(document) is not None else None
    except Exception:
        return None


def _span(document, text, start, end, kind, field=None, **extra):
    if not (isinstance(start, int) and not isinstance(start, bool) and isinstance(end, int)
            and not isinstance(end, bool) and 0 <= start < end <= len(text)):
        return None
    quote = text[start:end]
    locator = {'kind':'native_text','source_char_start':start,'source_char_end':end,
               'line_start':text.count('\n',0,start)+1,'line_end':text.count('\n',0,end-1)+1,'line_basis':'native_text'}
    extension = Path(document.get('path','')).suffix.lower()
    if extension == '.pdf':
        pages = list(re.finditer(r'(?m)^Страница (\d+)\s*$', text[:start]))
        if pages and not re.search(r'(?m)^Страница \d+\s*$', quote):
            locator['page'] = int(pages[-1].group(1))
    elif extension == '.xlsx':
        sheets = list(re.finditer(r'(?m)^Лист: (.+)$', text[:start]))
        if sheets and not re.search(r'(?m)^Лист: ', quote):
            locator['sheet'] = sheets[-1].group(1)
            line_start = text.rfind('\n',0,start)+1
            line_end = text.find('\n',end)
            block = text[line_start:line_end if line_end >= 0 else len(text)]
            locator['cells'] = list(dict.fromkeys(re.findall(r'(?:^|\|\s*)([A-Z]+\d+):', block, re.M)))
            locator['cells_basis'] = 'native_line_context'
    return {'kind':kind, 'field':field, 'text':quote, 'locator':locator,
            'source_hash':document['source_hash'],'native_text_sha256':hashlib.sha256(text.encode()).hexdigest(),**extra}


def _document_evidence(document):
    text = _native(document)
    if text is None:
        return [], 'unavailable'
    found = []
    evidence = document.get('category_evidence') or {}
    digest = hashlib.sha256(text.encode()).hexdigest()
    if (evidence.get('source_verified') is True and evidence.get('source_hash') == document.get('source_hash')
            and evidence.get('native_text_sha256') == digest):
        for statement in evidence.get('statements', []):
            if statement.get('state') not in {'asserted','denied_service','unknown','purchase','nonexclusive'}:
                continue
            start,end = statement.get('source_char_start'),statement.get('source_char_end')
            item = _span(document,text,start,end,'category_statement','category',
                         assertion_state=statement.get('state'),decision_effect=statement.get('decision_effect'))
            if item and item['text'] == statement.get('text'):
                found.append(item)
    number = document.get('number_evidence') or {}
    if (number.get('source_hash') == document.get('source_hash') and number.get('native_text_sha256') == digest):
        for candidate in [*number.get('candidates', []),*number.get('absence_evidence', [])]:
            item = _span(document,text,candidate.get('start'),candidate.get('end'),'own_number','doc_number')
            if item and item['text'] == candidate.get('value',candidate.get('text')):
                found.append(item)
    amount = parse_amount((document.get('prediction') or {}).get('amount'))
    amount_spans = []
    if amount is not None:
        offset = 0
        for line in text.splitlines(keepends=True):
            if re.search(r'\b(?:итого|всего|сумма|стоимость)\b', line, re.I):
                # Coordinates and dates are not amount tokens. A line is cited
                # only when its labelled amount matches the selected value.
                clean = re.sub(r'\b[A-Z]+\d+:', '', line)
                tokens = re.findall(r'(?<![\w./])[-+]?\d+(?:[ \u00a0]\d{3})*(?:[.,]\d{1,2})?(?![\w./])', clean)
                if sum(parse_amount(token)==amount for token in tokens) == 1:
                    item = _span(document,text,offset,offset+len(line.rstrip('\r\n')),'amount_line','amount')
                    if item:
                        amount_spans.append(item)
            offset += len(line)
        if len(amount_spans) == 1:
            found.insert(0,amount_spans[0])
    unique = {}
    for item in found:
        key = (item['kind'],item['locator']['source_char_start'],item['locator']['source_char_end'])
        unique.setdefault(key,item)
    return list(unique.values()), 'verified_native' if unique else 'no_verified_field_locator'


def _report_evidence(report):
    base = _reference(report)
    result = {}
    path = _local_path(report)
    if path is None or path.suffix.lower() != '.xlsx' or report.get('input_kind') != 'bounded_native_report':
        return result
    try:
        from .native_report import read_native_report
        actual = read_native_report(path)
        supplied = report.get('prediction') or {}
        if actual.get('source',{}).get('sha256') != report.get('source_hash') or _local_path(report) is None:
            return result
        for row in [*actual.get('rows', []), {'category':'total','reported_amount':actual['total']['amount'],'source_cells':{'reported_amount':actual['total']['cell']}}]:
            category = row['category']
            original = (supplied.get('total') or {}).get('amount') if category=='total' else next((r.get('reported_amount') for r in supplied.get('rows',[]) if r.get('category')==category),None)
            if parse_amount(original) is None or parse_amount(original) != parse_amount(row['reported_amount']):
                continue
            address = row['source_cells']['reported_amount']
            sheet,cell = address.rsplit('!',1)
            result[category] = {**base,'locator_status':'verified_native','locators':[{'kind':'xlsx_cell',
                'sheet':sheet,'cell':cell,'address':address,'value':_amount(row['reported_amount']),
                'verification':'reread_bounded_native_report','source_hash':report['source_hash']} ]}
    except Exception:
        pass
    return result


def _reason(reason):
    code = str(reason.get('reason','unknown_reason'))
    message = REASONS.get(code)
    if message is None and code.startswith('report_') and code.endswith('_not_verified'):
        message = 'Реквизит КФЗ не подтверждён для проверяемого комплекта.'
    if message is None and code.startswith('business_identity_'):
        message = 'Идентичность документа не подтверждена для автоматического объединения.'
    return {'code':code,'message':message or 'Причина требует отдельной проверки; её код сохранён в результате.',
            **({'document_id':str(reason['id'])} if reason.get('id') is not None else {}),
            **({'basis':reason['basis']} if reason.get('basis') is not None else {})}


def explain(report, documents, reconciliation):
    """Explain existing decisions without changing status, amounts or source IDs."""
    docs = {str(document.get('id')):document for document in documents}
    evidence = {identifier:_document_evidence(document) for identifier,document in docs.items()}
    report_locations = _report_evidence(report)
    all_rows = [*reconciliation.get('rows', []), *([reconciliation['total']] if reconciliation.get('total') else [])]
    used = {}
    for row in reconciliation.get('rows', []):
        for identifier in row.get('source_ids', []):
            used.setdefault(str(identifier),[]).append(row.get('category'))
    document_reasons = {}
    for row in all_rows:
        for reason in row.get('reasons', []):
            if reason.get('id') is not None:
                document_reasons.setdefault(str(reason['id']),[]).append(reason)
    exclusions = {str(item['id']):[item] for item in reconciliation.get('excluded_documents', [])}
    duplicates = {str(item['id']):item for item in reconciliation.get('duplicates', [])}
    for identifier,duplicate in duplicates.items():
        exclusions.setdefault(identifier,[]).append({'id':identifier,'reason':'duplicate_'+str(duplicate.get('basis','unknown'))})
    warnings = []

    def describe_document(identifier):
        document = docs.get(identifier, {})
        items,availability = evidence.get(identifier,([], 'unavailable'))
        return {**_reference(document,identifier),'amount':_amount((document.get('prediction') or {}).get('amount')),
                'evidence':items,'locator_status':availability}

    def describe_row(row):
        category,status = row.get('category'),row.get('status')
        label = LABELS.get(category,str(category) if category is not None else 'Неопределённая статья')
        source_ids = list(dict.fromkeys(str(identifier) for identifier in row.get('source_ids', [])))
        local_warnings = []
        if len(source_ids) != len(row.get('source_ids', [])):
            local_warnings.append('repeated_selected_source_id')
        included = [describe_document(identifier) for identifier in source_ids]
        terms = [{'document_id':item['document_id'],'amount':item['amount']} for item in included]
        values = [parse_amount(term['amount']) for term in terms]
        term_sum = sum(values,Decimal('0')) if all(value is not None for value in values) else None
        if any(identifier not in docs for identifier in source_ids):
            local_warnings.append('selected_source_record_missing')
        partial = row.get('partial_amount')
        expected,delta = row.get('expected_amount'),row.get('delta')
        if status=='unverified' and (expected is not None or delta is not None):
            local_warnings.append('unverified_has_final_amount')
            expected,delta = None,None
        target = parse_amount(partial) if 'partial_amount' in row else parse_amount(expected)
        match = term_sum==target if term_sum is not None and target is not None else None
        if match is False:
            local_warnings.append('selected_terms_do_not_match_reconciliation_amount')
        reported_number,expected_number,delta_number = map(parse_amount,(row.get('reported_amount'),expected,delta))
        location = report_locations.get(category,{**_reference(report),'locator_status':'unavailable','locators':[]})
        if location['locators'] and parse_amount(location['locators'][0]['value']) != reported_number:
            local_warnings.append('reported_amount_differs_from_verified_cell')
            location = {**_reference(report),'locator_status':'unavailable','locators':[]}
        consistent = (reported_number is not None and expected_number is not None and delta_number is not None
                      and reported_number-expected_number==delta_number
                      and bool(terms) and term_sum==expected_number
                      and ((status=='correct' and delta_number==0) or (status=='incorrect' and delta_number!=0)))
        if status in {'correct','incorrect'} and not consistent:
            local_warnings.append('verified_arithmetic_inconsistent')
        formula = (' + '.join(_rubles(term['amount']) for term in terms)+' = '+_rubles(term_sum)) if terms and term_sum is not None else ('Нет учтённых документов.' if not terms else 'Сумма слагаемых не установлена.')
        comparison_formula = f"{_rubles(row.get('reported_amount'))} − {_rubles(expected)} = {_rubles(delta)}" if consistent else None
        if status=='unverified':
            summary = f'{label}: окончательная сумма не подтверждена. В КФЗ: {_rubles(row.get("reported_amount"))}.'
            if 'partial_amount' in row:
                summary += f' Частичная сумма учтённых документов: {_rubles(partial)}; она не является окончательным итогом.'
            else:
                summary += f' Сумма выбранных источников, рассчитанная отдельно: {_rubles(term_sum)}; итог КФЗ пока не проверен.'
            summary += ' Денежное расхождение не установлено.'
        elif status=='correct' and consistent:
            summary = f'{label}: сумма КФЗ {_rubles(row.get("reported_amount"))} совпадает с суммой по учтённым документам {_rubles(expected)}.'
        elif status=='incorrect' and consistent:
            direction = 'больше' if delta_number>0 else 'меньше'
            summary = f'{label}: сумма КФЗ на {_rubles(abs(delta_number))} {direction} суммы по учтённым документам. Причина разницы из одной арифметики не следует.'
        else:
            summary = f'{label}: статус сверки «{status}»; расчётные поля требуют проверки.'
        reasons = [_reason(reason) for reason in row.get('reasons', [])]
        not_included = []
        candidates = list(dict.fromkeys([str(reason['id']) for reason in row.get('reasons',[]) if reason.get('id') is not None] + list(exclusions)))
        for identifier in candidates:
            if identifier in source_ids or identifier not in docs:
                continue
            document = docs[identifier]
            relevant = category=='total' or any(str(reason.get('id'))==identifier for reason in row.get('reasons',[])) or (document.get('prediction') or {}).get('category')==category
            if not relevant:
                continue
            relevant_reasons = [reason for reason in row.get('reasons',[]) if str(reason.get('id'))==identifier] + exclusions.get(identifier,[])
            codes = list(dict.fromkeys(item['code'] for item in map(_reason,relevant_reasons)))
            not_included.append({**describe_document(identifier),'reason_codes':codes,
                'reasons':[REASONS.get(code,'Причина требует проверки: '+code) for code in codes],
                **({'duplicate_of':str(duplicates[identifier]['duplicate_of'])} if identifier in duplicates else {})})
        actions = []
        for reason in reasons:
            code = reason['code']
            action = RECOMMENDATIONS.get(code)
            if action is None and code.startswith('report_'):
                action = 'Проверить реквизиты и читаемость исходной КФЗ.'
            if action is None:
                action = 'Проверить причину по исходным документам до окончательного подтверждения.'
            if not any(item['code']==code for item in actions):
                actions.append({'code':code,'action':action})
            identifier = reason.get('document_id')
            if code in {'category_not_source_resolved', 'category_source_abstention'} and identifier in docs:
                source_check = docs[identifier].get('category_evidence', {})
                if any(item['kind'] == 'category_statement' for item in evidence[identifier][0]):
                    markers = [source_check.get('status'), *source_check.get('hard_reasons', []),
                               *source_check.get('unchecked_reasons', [])]
                    for marker in markers:
                        if marker in REVIEW_ACTIONS and not any(
                                item['code'] == marker and item.get('document_id') == identifier for item in actions):
                            actions.append({'code':marker,'action':REVIEW_ACTIONS[marker],'document_id':identifier})
        if status=='incorrect':
            actions.append({'code':'reconcile_difference','action':'Сверить сумму КФЗ с перечисленными источниками; после проверки основания исправить отчёт либо комплект документов.'})
        if local_warnings:
            actions.append({'code':'verify_explanation_inputs','action':'Проверить согласованность расчётных полей и выбранных источников; объяснение не заменяет эту проверку.'})
        warnings.extend({'category':category,'code':code} for code in local_warnings)
        return {'category':category,'label':label,'status':status,'summary':summary,
            'calculation':{'reported_amount':row.get('reported_amount'),'expected_amount':expected,'partial_amount':partial,
                'delta':delta,'terms':terms,'sum_of_terms':money_string(term_sum),'sum_basis':'selected_document_predictions',
                'terms_match_amount':match,'formula':formula,'comparison_formula':comparison_formula,
                'delta_definition':'КФЗ минус подтверждённая сумма; при unverified не вычисляется.'},
            'report_evidence':location,'included_documents':included,'not_included_documents':not_included,
            'reasons':reasons,'recommendations':actions,'warnings':local_warnings}

    rows = [describe_row(row) for row in reconciliation.get('rows', [])]
    total = describe_row(reconciliation['total']) if reconciliation.get('total') else None
    decisions = []
    for identifier,document in docs.items():
        reasons = exclusions.get(identifier,[]) + document_reasons.get(identifier,[])
        codes = list(dict.fromkeys(_reason(reason)['code'] for reason in reasons))
        included_categories = list(dict.fromkeys(used.get(identifier,[])))
        if included_categories:
            disposition = 'included_with_review' if document_reasons.get(identifier) else 'included'
        elif identifier in duplicates:
            disposition = 'duplicate_not_counted'
        elif identifier in exclusions:
            disposition = 'excluded'
        elif reasons:
            disposition = 'requires_review'
        else:
            disposition = 'not_selected'
            codes = ['not_selected_without_reason']
        decisions.append({**describe_document(identifier),'disposition':disposition,'included_categories':included_categories,
            'reason_codes':codes,'reasons':[REASONS.get(code,'Причина требует проверки: '+code) for code in codes],
            **({'duplicate_of':str(duplicates[identifier]['duplicate_of'])} if identifier in duplicates else {})})
    return {'version':VERSION,'language':'ru','rows':rows,'total':total,'document_decisions':decisions,'warnings':warnings,
            'completeness':deepcopy(reconciliation.get('completeness')),
            'evidence_policy':'Цитаты и локаторы только из повторно прочитанного локального файла с совпавшим хешем. Строки означают строки нативного текста; модельные цитаты и координаты OCR не подтверждаются.',
            'decision_policy':'Объяснение воспроизводит результат сверки; оно не устанавливает причину денежной разницы и не подтверждает полноту источников самостоятельно.'}


def render_text(explanation):
    """Small optional readable view; the structured JSON remains authoritative."""
    blocks = []
    for row in [*explanation.get('rows',[]), *([explanation['total']] if explanation.get('total') else [])]:
        lines = [row['summary'],row['calculation']['formula']]
        if row['calculation']['comparison_formula']:
            lines.append(row['calculation']['comparison_formula'])
        lines += [f"Учтён {item['document_id']} · {item['name']}: {_rubles(item['amount'])}" for item in row['included_documents']]
        lines += [f"Причина: {item['message']}" for item in row['reasons']]
        lines += [f"Действие: {item['action']}" for item in row['recommendations']]
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)
