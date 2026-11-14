"""Pre-gold independent absence/operation-purpose contract fixtures. No models."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path

from bench.e2e_v32_20261114.document_identity import apply_document_number_checks, validate_number_evidence
from bench.e2e_v32_20261114.classification import apply_source_checks
from bench.e2e_v32_20261114.decision_rules import reconcile


def record(identifier, text, raw_number='07.02.2026', category='general_admin'):
    return {'id':identifier,'source_hash':hashlib.sha256((identifier+'|'+str(text)).encode()).hexdigest(),
            'prediction':{'doc_number':raw_number,'contract_number':'ТЕСТ-42','date':'2026-02-07','period_start':'2026-02-01','period_end':'2026-02-28','amount':'100.00','category':category,'description':'test','evidence_quote':'test'}}


def identity(identifier,text,raw='07.02.2026'):
    return apply_document_number_checks(record(identifier,text,raw),text)


def purpose(text,raw='production_overhead'):
    return apply_source_checks(record('purpose',text,category=raw),text)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--section',choices=['all','number'],default='all');args=parser.parse_args()
    checks=[]
    def check(name,fn):
        if args.section=='number' and not name.startswith(('explicit_absence','no_absence_authority','filled_own_id','scan_has_no_absence','absence_suppresses')):return
        try:fn();checks.append({'name':name,'passed':True})
        except Exception as error:checks.append({'name':name,'passed':False,'error':repr(error)})
    def require(value):assert value

    absent=['Акт № __________ от 07.02.2026','Номер документа: без номера','Номер документа: б/н','Акт\n№ — от 07.02.2026']
    for index,text in enumerate(absent):
        for raw in ('07.02.2026','К-913',None):
            def clear(text=text,raw=raw):
                before=record('a',text,raw);old=deepcopy(before);after=apply_document_number_checks(before,text);proof=validate_number_evidence(after)
                assert before==old and after['prediction']['doc_number'] is None and after['raw_prediction']['doc_number']==raw
                assert proof['valid'] and not proof['identity_usable'] and proof['number'] is None
                assert {k:v for k,v in before['prediction'].items()if k!='doc_number'}=={k:v for k,v in after['prediction'].items()if k!='doc_number'}
                assert apply_document_number_checks(after,text)==after
            check('explicit_absence_'+str(index)+'_'+str(raw),clear)

    not_absent=['Дата составления: 07.02.2026\nДоговор № К-913','Основание: акт № б/н',
                'Цитата из предыдущего акта: «Номер документа: без номера».','Неизвестный вид\n№ ___',
                'Документ: Инвентаризация-2026','Номер документа: АБ-___','Номер документа: ___123',
                'Номер документа: б/н\nДокумент № К-913','Номер документа: б/н\nНомер документа: АБ-___',
                'Номер документа: б/н\n'+('\n'.join('техническая строка' for _ in range(20)))+'\nНомер документа: К-913']
    for index,text in enumerate(not_absent):
        check('no_absence_authority_'+str(index),lambda text=text:require(identity('n',text,'К-913')['prediction']['doc_number']=='К-913'))
    for text,raw in [('Номер документа:\nК-913','К-913'),('Номер документа: 0','0'),
                     ('Документ № 07.02.2026\nДата составления: 12.02.2026','07.02.2026'),
                     ('Акт № Б/Н-42','Б/Н-42'),('Документ № ПР-913','ПР-913')]:
        check('filled_own_id_preserved_'+raw,lambda text=text,raw=raw:require(identity('f',text,raw)['prediction']['doc_number']==raw))
    check('scan_has_no_absence_authority',lambda:require(identity('scan',None)['prediction']['doc_number']=='07.02.2026' and identity('scan',None)['number_evidence']['source_verified'] is False))

    def absent_alias_requires_valid_proof():
        a=identity('a','Номер документа: б/н','К-913');b=identity('b','Документ № К-913','К-913')
        def compare(x):return reconcile([x,b],[{'category':'general_admin','reported_amount':'200.00'}],'ТЕСТ-42','2026-02-01','2026-02-28',{'status':'complete','basis':'test'})
        good=compare(a);assert good['rows'][0]['status']=='correct' and not good['duplicates']
        for key,value in [('source_hash','bad'),('native_text_sha256','bad')]:
            damaged=deepcopy(a);damaged['number_evidence'][key]=value
            assert not validate_number_evidence(damaged)['valid']
            bad=compare(damaged);assert bad['rows'][0]['status']=='unverified' and not bad['duplicates']
    check('absence_suppresses_raw_alias_only_with_valid_proof',absent_alias_requires_valid_proof)

    positive=['Сканирование папок административной дирекции. Общехозяйственные расходы.',
              'Оцифровка карточек административного отдела. Общехозяйственные расходы.',
              'Переплёт документов аппарата управления. Общехозяйственные расходы.',
              'Ламинирование карточек производственного участка. Общепроизводственные расходы.',
              'Обслуживание административной системы «Контур».',
              "Обслуживание административной системы O'Reilly."]
    for index,text in enumerate(positive):
        expected='production_overhead'if'Общепроизводственные' in text else'general_admin'
        for raw in ('general_admin','production_overhead',None):
            def confirmed(text=text,raw=raw,expected=expected):
                after=purpose(text,raw);assert after['prediction']['category']==expected and after['category_evidence']['financial_usable'] is True
                assert after['raw_prediction']['category']==raw
            check('independent_positive_'+str(index)+'_'+str(raw),confirmed)

    risky=['Сканирование не проводилось.','Оцифровка лишь планировалась.','Переплёт не выполнялся.',
           'Сканирование административных папок приведено в образце.',
           'Для примера: оцифровка административных карточек.','Эти услуги не оказывались.',
           'Сканирование административных папок выполнено?',
           'Если оцифровка административных карточек будет принята, расходы будут учтены.',
           'Приобретение оборудования административной дирекции.']
    for index,risk in enumerate(risky):
        for separator in (' ','\n'):
            check('risk_kept_'+str(index)+'_'+repr(separator),lambda risk=risk,separator=separator:require(purpose('Общехозяйственные расходы.'+separator+risk)['category_evidence']['financial_usable'] is False))

    no_own_positive=['Административная дирекция.','Цитата из чужого акта: «Обслуживание административной дирекции».',
                     'В прежнем документе: «Общехозяйственные расходы».',
                     'Услуги не относятся к административным расходам.',
                     'Исполнитель: ООО «Административное обслуживание».']
    for index,text in enumerate(no_own_positive):
        check('no_own_positive_'+str(index),lambda text=text:require(purpose(text)['category_evidence']['financial_usable'] is not True))

    def mixed_scope():
        a=purpose('Оцифровка материалов административного и производственного подразделений. Общехозяйственные и общепроизводственные расходы. Распределение суммы не указано.')
        assert a['prediction']['category'] is None and a['category_evidence']['financial_usable'] is False
        assert set(a['category_evidence']['candidates'])=={'general_admin','production_overhead'}
        a['id']='mixed';b=record('payroll',None,'ЗП-1','payroll')
        r=reconcile([a,b],[{'category':k,'reported_amount':'100.00'}for k in ['general_admin','production_overhead','payroll']],'ТЕСТ-42','2026-02-01','2026-02-28',{'status':'complete','basis':'test'})
        assert {x['category']:x['status']for x in r['rows']}=={'general_admin':'unverified','production_overhead':'unverified','payroll':'correct'}
    check('mixed_scope_preserves_independent_payroll',mixed_scope)

    out={'at_utc':datetime.now(timezone.utc).isoformat(),'passed':all(c['passed']for c in checks),'section':args.section,'checks':checks,'future_gold_read':False,'model_calls':0,
         'source_hashes':{str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in [Path(__file__).with_name(n)for n in ['document_identity.py','classification.py','decision_rules.py']]+[Path(__file__)]}}
    target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x')as f:json.dump(out,f,ensure_ascii=False,indent=2)
    print(json.dumps({'passed':out['passed'],'total':len(checks),'failures':[c for c in checks if not c['passed']]},ensure_ascii=False))
    if not out['passed']:raise SystemExit(1)


if __name__=='__main__':main()
