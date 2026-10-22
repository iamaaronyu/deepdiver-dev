"""Read-only aggregation; writes a fresh report edition without changing measured outcomes."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import html
import json
from pathlib import Path
from uuid import uuid4

from deepdive.evaluation.metrics import audit_metrics,ratio


def summarize(rows):
    n=len(rows)
    links=sum(r['evidence_links'] for r in rows)
    known_costs=[r['usage'].get('cost_estimate_usd') for r in rows if r['usage'].get('cost_estimate_usd') is not None]
    reviewed=[r for r in rows if r.get('review_status')=='reference_audited']
    determinate=sum(r.get('determinate_reviewed_facts',0) for r in reviewed)
    errors=sum(round(r['reference_audited_fact_error_rate']*r['determinate_reviewed_facts']) for r in reviewed if r['reference_audited_fact_error_rate'] is not None)
    return {'attempts':n,'completed':sum(r['completed'] for r in rows),'completion_rate':ratio(sum(r['completed'] for r in rows),n),
        'analysis_reports':sum(r['has_analysis'] for r in rows),'failures':dict(Counter(r['task_status'] for r in rows if not r['completed'])),
        'literal_citation_validity':ratio(sum(r['literal_citation_valid_count'] for r in rows),links),'evidence_links':links,
        'mean_keyword_coverage_hint':ratio(sum(r['coverage_keyword_hint'] or 0 for r in rows),n),
        'reviewed_attempts':len(reviewed),'reference_audited_fact_error_rate':ratio(errors,determinate),
        'determinate_reviewed_facts':determinate,'reference_audited_coverage':ratio(sum(r['reference_audited_coverage'] for r in reviewed),len(reviewed)),
        'cost_estimate_known_subtotal_usd':round(sum(known_costs),8),'unknown_cost_attempts':n-len(known_costs),
        'reserved_upper_usd':round(sum(r['usage'].get('cost_reserved_upper_usd',0) for r in rows),8),
        'recorded_input_tokens':sum(r['usage'].get('input_tokens',0) for r in rows),'recorded_output_tokens':sum(r['usage'].get('output_tokens',0) for r in rows),
        'recorded_search_requests':sum(r['usage'].get('search_requests',0) for r in rows),'recorded_model_attempts':sum(r['usage'].get('model_call_attempts',0) for r in rows),
        'mean_recorded_duration_seconds':ratio(sum(r['usage'].get('duration_seconds',0) for r in rows),n),
        'incomplete_usage_attempts':sum(not(r['usage'].get('model_usage_complete') and r['usage'].get('tool_usage_complete')) for r in rows)}


def render(folder):
    suite=json.loads((folder/'suite.json').read_text());cases={c['id']:c for c in suite['cases']}
    rows=[]
    for path in sorted(folder.glob('*.metrics.json')):
        row=json.loads(path.read_text())
        audit=folder/'audits'/(row['case_id']+'--'+row['profile']+'.json')
        if audit.exists():row.update(audit_metrics(json.loads(audit.read_text()),cases[row['case_id']],row['task_id']))
        rows.append(row)
    profiles={p:summarize([r for r in rows if r['profile']==p]) for p in sorted({r['profile'] for r in rows})}
    pairs=[]
    for case in cases:
        pair={r['profile']:r for r in rows if r['case_id']==case}
        if {'standard','deep'}<=set(pair):
            a,b=pair['standard'],pair['deep']
            pairs.append({'case_id':case,'standard_status':a['task_status'],'deep_status':b['task_status'],
                          'both_completed':a['completed'] and b['completed'],
                          'keyword_hint_delta_deep_minus_standard':b['coverage_keyword_hint']-a['coverage_keyword_hint'],
                          'reference_audited_coverage_delta':b['reference_audited_coverage']-a['reference_audited_coverage'] if a['reference_audited_coverage'] is not None and b['reference_audited_coverage'] is not None else None})
    result={'run_dir':str(folder),'complete':(folder/'complete.json').exists(),'profiles':profiles,'paired_cases':pairs,'rows':rows,
        'limits':['Keyword matches are coverage hints, not semantic correctness.','Literal quotations are not proof that a claim is correct.','Reference audits are separate judgments with explicit bases; not human certification.','Unknown usage/cost is not zero; prices are dated conservative estimates, not invoices.','Interrupted and failed attempts remain in completion denominators.']}
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:4]
    base=folder/('comparison-'+stamp)
    base.with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    def pct(v):return '未评定' if v is None else f'{v:.1%}'
    lines=['# 研究质量与成本对比','',f'运行：{folder.name}；状态：'+('全部尝试已结束' if result['complete'] else '仍在执行 / 部分结果'),'','## 策略汇总','',
           '| 策略 | 完成/尝试 | 分析报告 | 引用逐字有效率 | 复核覆盖率 | 已复核确定事实错误率 | 已知费用小计 USD | 用量不完整 |',
           '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for p,s in profiles.items():lines.append(f"| {p} | {s['completed']}/{s['attempts']} | {s['analysis_reports']} | {pct(s['literal_citation_validity'])} | {pct(s['reference_audited_coverage'])} | {pct(s['reference_audited_fact_error_rate'])} | {s['cost_estimate_known_subtotal_usd']:.6f} | {s['incomplete_usage_attempts']} |")
    lines+=['','事实错误率只覆盖已复核且可确定的事实，不代表全报告或一般准确率。费用是已知用量小计，未知部分没有记为零。','','## 逐题结果','',
            '| 问题 | 策略 | 状态 | 主张 / 证据 | 分析 | 关键词覆盖提示 | 已复核覆盖 | 失败原因 |',
            '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in rows:lines.append(f"| {r['case_id']} | {r['profile']} | {r['task_status']} | {r['claims']} / {r['evidence_links']} | {'有' if r['has_analysis'] else '无'} | {pct(r['coverage_keyword_hint'])} | {pct(r['reference_audited_coverage'])} | {r['error_code'] or '—'} |")
    lines+=['','## 指标边界','']+['- '+s for s in result['limits']]
    base.with_suffix('.md').write_text('\n'.join(lines)+'\n')
    table=''.join('<tr><td>'+html.escape(r['case_id'])+'</td><td>'+html.escape(r['profile'])+'</td><td>'+html.escape(r['task_status'])+'</td><td>'+str(r['claims'])+' / '+str(r['evidence_links'])+'</td><td>'+pct(r['reference_audited_coverage'])+'</td><td><a href="'+html.escape(r['case_id']+'--'+r['profile']+'.md',quote=True)+'">原始报告</a></td></tr>' for r in rows)
    cards=''.join('<section><h2>'+html.escape(p)+'</h2><strong>'+str(s['completed'])+' / '+str(s['attempts'])+'</strong><p>流程完成 / 全部尝试</p><p>逐字引用有效率 '+pct(s['literal_citation_validity'])+'</p><p>复核覆盖率 '+pct(s['reference_audited_coverage'])+'</p><p>已知费用小计 $'+str(s['cost_estimate_known_subtotal_usd'])+'</p></section>' for p,s in profiles.items())
    doc='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>DeepDive 质量评测</title><style>body{margin:0;background:#f3f2ee;color:#19314a;font:15px/1.8 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{max-width:1200px;margin:50px auto;padding:24px}h1{font-size:34px}small{color:#7d6a46;letter-spacing:2px}.cards{display:flex;gap:24px;margin:32px 0}section{background:white;border-top:3px solid #244565;padding:24px;flex:1}strong{font-size:36px}table{background:white;width:100%;border-collapse:collapse}td,th{padding:14px;text-align:left;border-bottom:1px solid #e5e8ea}a{color:#315a7b}.scroll{overflow:auto}aside{padding:18px;background:#faf7ed;margin:24px 0}@media(max-width:600px){main{margin:15px auto;padding:18px}.cards{display:block}section{margin-bottom:16px}}</style><main><small>RESEARCH QUALITY / COST REVIEW</small><h1>研究质量与成本评测</h1><p>'+html.escape(folder.name)+'</p><aside>引用能定位不代表结论正确。未复核指标显示“未评定”；费用仅为已知用量估算。失败与中断均保留。</aside><div class="cards">'+cards+'</div><div class="scroll"><table><tr><th>问题</th><th>策略</th><th>状态</th><th>主张/证据</th><th>复核覆盖</th><th>报告</th></tr>'+table+'</table></div></main></html>'
    base.with_suffix('.html').write_text(doc)
    print(json.dumps({'report_json':str(base.with_suffix('.json')),'report_md':str(base.with_suffix('.md')),'report_html':str(base.with_suffix('.html')),'profiles':profiles},ensure_ascii=False))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run_dir');args=parser.parse_args();render(Path(args.run_dir).resolve())
