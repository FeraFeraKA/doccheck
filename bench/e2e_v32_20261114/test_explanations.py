"""Critical explanation safety: partial money, source membership and locators."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

from bench.e2e_v32_20261114.explanations import explain, render_text


def document(identifier='a', amount='100.00'):
    return {'id':identifier,'path':f'missing-{identifier}.pdf','source_hash':'0'*64,
            'prediction':{'amount':amount,'category':'general_admin','evidence_quote':'Invented quote','page':77}}


def row(status='correct', reported='100.00', expected='100.00', partial='100.00', delta='0.00', sources=None, reasons=None):
    return {'category':'general_admin','status':status,'reported_amount':reported,'expected_amount':expected,
            'partial_amount':partial,'delta':delta,'source_ids':['a'] if sources is None else sources,'reasons':reasons or []}


def reconciliation(item, total=None, **extra):
    result={'rows':[item],'excluded_documents':[],'duplicates':[],**extra}
    if total is not None:result['total']=total
    return result


class ExplanationTests(unittest.TestCase):
    def test_unverified_partial_is_neither_complete_total_nor_discrepancy(self):
        item=row('unverified','150.00',None,'100.00',None,reasons=[{'reason':'declared_incomplete_sources','basis':'user_manifest'}])
        result=explain({'id':'report'},[document()],reconciliation(item))['rows'][0]
        self.assertEqual(result['status'],'unverified')
        self.assertIsNone(result['calculation']['expected_amount'])
        self.assertIsNone(result['calculation']['delta'])
        self.assertIsNone(result['calculation']['comparison_formula'])
        self.assertEqual(result['calculation']['partial_amount'],'100.00')
        self.assertIn('не является окончательным',result['summary'])
        self.assertIn('расхождение не установлено',result['summary'])
        self.assertEqual(result['reasons'][0]['code'],'declared_incomplete_sources')
        self.assertEqual(result['recommendations'][0]['code'],'declared_incomplete_sources')

    def test_terms_count_only_selected_documents_and_exclusions_are_explicit(self):
        documents=[document('a','100.10'),document('b','20.20'),document('copy','100.10'),document('foreign','900.00')]
        item=row('incorrect','130.30','120.30','120.30','10.00',sources=['a','b'])
        result=explain({'id':'report'},documents,reconciliation(item,
            duplicates=[{'id':'copy','duplicate_of':'a','basis':'hash'}],excluded_documents=[{'id':'foreign','reason':'different_contract'}]))
        explanation=result['rows'][0]
        self.assertEqual([d['document_id'] for d in explanation['included_documents']],['a','b'])
        self.assertEqual(explanation['calculation']['sum_of_terms'],'120.30')
        self.assertTrue(explanation['calculation']['terms_match_amount'])
        self.assertIn('10,00 ₽ больше',explanation['summary'])
        self.assertIn('Причина разницы из одной арифметики не следует',explanation['summary'])
        excluded={d['document_id']:d for d in explanation['not_included_documents']}
        self.assertEqual(excluded['copy']['reason_codes'],['duplicate_hash'])
        self.assertEqual(excluded['foreign']['reason_codes'],['different_contract'])
        self.assertEqual(excluded['copy']['duplicate_of'],'a')

    def test_total_without_partial_field_labels_derived_sum_and_keeps_null(self):
        item=row('unverified','100.00',None,'100.00',None,reasons=[{'reason':'completeness_unknown'}])
        total={'category':'total','status':'unverified','reported_amount':'100.00','expected_amount':None,
               'delta':None,'source_ids':['a'],'reasons':[{'reason':'total_or_constituent_unverified'}]}
        result=explain({'id':'report'},[document()],reconciliation(item,total))['total']
        self.assertIsNone(result['calculation']['partial_amount'])
        self.assertIsNone(result['calculation']['terms_match_amount'])
        self.assertEqual(result['calculation']['sum_of_terms'],'100.00')
        self.assertIn('рассчитанная отдельно',result['summary'])
        self.assertIsNone(result['calculation']['delta'])

    def test_model_quote_page_and_missing_source_are_not_evidence(self):
        source=document()
        source['source_native_text']='Invented quote'
        result=explain({'id':'report','prediction':{'page':42,'evidence_quote':'Invented report'}},[source],reconciliation(row()))
        self.assertEqual(result['rows'][0]['included_documents'][0]['evidence'],[])
        self.assertEqual(result['rows'][0]['report_evidence']['locators'],[])
        self.assertNotIn('Invented',render_text(result))
        missing=explain({'id':'report'},[],reconciliation(row()))['rows'][0]
        self.assertIn('selected_source_record_missing',missing['warnings'])
        self.assertIsNone(missing['calculation']['sum_of_terms'])

    def test_inconsistent_terms_do_not_get_a_confident_equality_explanation(self):
        result=explain({'id':'report'},[document('a','200.00')],reconciliation(row()))['rows'][0]
        self.assertEqual(result['status'],'correct')
        self.assertIn('selected_terms_do_not_match_reconciliation_amount',result['warnings'])
        self.assertIn('verified_arithmetic_inconsistent',result['warnings'])
        self.assertNotIn('совпадает',result['summary'])
        self.assertIsNone(result['calculation']['comparison_formula'])

    def test_native_docx_quotes_have_literal_spans_and_no_invented_page(self):
        from docx import Document
        from bench.e2e_v32_20261114.runtime import native_text
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.docx'
            doc=Document();doc.add_paragraph('Обслуживание административного аппарата.');doc.add_paragraph('ИТОГО: 100,00');doc.save(path)
            text=native_text(path)
            source=document();source.update(path=str(path),source_hash=hashlib.sha256(path.read_bytes()).hexdigest(),source_native_text=text)
            phrase='Обслуживание административного аппарата.'
            source['category_evidence']={'source_verified':True,'source_hash':source['source_hash'],
                'native_text_sha256':hashlib.sha256(text.encode()).hexdigest(),'statements':[
                {'text':phrase,'source_char_start':0,'source_char_end':len(phrase),'state':'asserted','decision_effect':'evidence'}]}
            evidence=explain({'id':'report'},[source],reconciliation(row()))['rows'][0]['included_documents'][0]['evidence']
            self.assertEqual({e['kind'] for e in evidence},{'amount_line','category_statement'})
            for item in evidence:
                loc=item['locator'];self.assertEqual(text[loc['source_char_start']:loc['source_char_end']],item['text'])
                self.assertNotIn('page',loc)
            source['source_native_text']='Changed text'
            self.assertEqual(explain({'id':'report'},[source],reconciliation(row()))['rows'][0]['included_documents'][0]['evidence'],[])
            source['source_native_text']=text;source['source_hash']='f'*64
            self.assertEqual(explain({'id':'report'},[source],reconciliation(row()))['rows'][0]['included_documents'][0]['evidence'],[])

    def test_report_cell_requires_native_file_hash_and_matching_row_amount(self):
        from openpyxl import Workbook
        from bench.e2e_v32_20261114.native_report import read_native_report
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.xlsx';book=Workbook();sheet=book.active;sheet.title='КФЗ'
            for cell,value in {'A3':'Договор № EX-72','A4':'Период: 2026-03-01 — 2026-03-31. Этап 3.',
                               'B6':'Статья затрат','C6':'Отчетная сумма, руб.','B7':'Общехозяйственные расходы','C7':100,
                               'A8':'Всего по отчету','C8':'=SUM(C7:C7)'}.items():sheet[cell]=value
            book.save(path)
            report={'id':'report','path':str(path),'source_hash':hashlib.sha256(path.read_bytes()).hexdigest(),
                    'input_kind':'bounded_native_report','prediction':read_native_report(path)}
            location=explain(report,[document()],reconciliation(row()))['rows'][0]['report_evidence']
            self.assertEqual(location['locators'][0]['address'],'КФЗ!C7')
            self.assertEqual(location['locators'][0]['value'],'100.00')
            changed=row(reported='999.00')
            result=explain(report,[document()],reconciliation(changed))['rows'][0]
            self.assertEqual(result['report_evidence']['locators'],[])
            self.assertIn('reported_amount_differs_from_verified_cell',result['warnings'])
            report['source_hash']='f'*64
            self.assertEqual(explain(report,[document()],reconciliation(row()))['rows'][0]['report_evidence']['locators'],[])

    def test_deterministic_and_does_not_mutate_inputs_or_share_completeness(self):
        report={'id':'report'};documents=[document()];rec=reconciliation(row(),completeness={'status':'complete','basis':'user'})
        before=deepcopy((report,documents,rec));first=explain(report,documents,rec)
        self.assertEqual(first,explain(report,documents,rec));self.assertEqual((report,documents,rec),before)
        first['completeness']['status']='changed'
        self.assertEqual(rec['completeness']['status'],'complete')


if __name__=='__main__':unittest.main()
