"""Deterministic evidence-only writer: source links cannot be invented by a model."""
import html
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote

from deepdive.evidence.sources import timestamp


def safe(text):
    value=html.escape(str(text),quote=False)
    for character in ('\\','[',']','*','_','`','|'):
        value=value.replace(character,'\\'+character)
    return value.replace('\r',' ').replace('\n',' ')


def link(source):
    url=source['canonical_url'] or source['url']
    return '['+safe(source['title'] or '来源')+']('+quote(url,safe=':/?&=%#+-._~')+')'


def write(repository,task_id,partial_reason=None,analysis=None):
    task=repository.get(task_id)
    material=repository.materials(task_id)
    sources={s['id']:s for s in material['sources'] if s['fetch_status']=='FETCHED'}
    claims=material['claims']
    supported=[c for c in claims if c['verification_status']=='SUPPORTED']
    lines=['# DeepDive 研究报告','', '**研究问题**：'+safe(task['question']),'', '**生成时间**：'+datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='minutes').replace('T',' ')+'（Asia/Shanghai）','',
           '## 执行摘要','',f'取得 {len(sources)} 个不重复有效正文来源，形成 {len(claims)} 条候选主张，其中 {len(supported)} 条通过当前自动证据关联检查。']
    if partial_reason:
        lines+=['','**部分报告**：'+safe(partial_reason)]
    if analysis:
        by_id={c['id']:c for c in claims}
        numbers={c['id']:index for index,c in enumerate(claims,1)}
        def point(item):
            references=[]
            for claim_id in dict.fromkeys(item.claim_ids):
                claim=by_id[claim_id]
                status='部分支持' if claim['verification_status']!='SUPPORTED' else '支持'
                references.append('[证据 '+str(numbers[claim_id])+'](#evidence-'+str(numbers[claim_id])+')（'+status+'）')
            return safe(item.text)+' '+' '.join(references)
        lines+=['','## 核心判断','']+[point(item)+'\n' for item in analysis.overview]
        for section in analysis.sections:
            lines+=['','## '+safe(section.title),'']+[point(item)+'\n' for item in section.points]
        if analysis.implications:
            lines+=['','## 决策启示','']+['- '+point(item) for item in analysis.implications]
        if analysis.open_questions:
            lines+=['','## 仍待回答的问题','']+['- '+safe(item) for item in analysis.open_questions]
        lines+=['','## 证据附录','', '以下保留逐字摘录和自动核验状态，供复核分析。分析文字由模型基于材料综合，引用关联校验不等同于逐句事实认证。','']
    else:
        lines+=['','## 关键结论','']
        lines += ['- '+safe(c['claim_text'])+'（详见下方证据）。' for c in supported] or ['证据尚不足以给出通过核验的确定结论。']
    lines+=['','## 分主题分析与证据引用','']
    for index,claim in enumerate(claims,1):
        lines += [f'### 证据 {index}：'+safe(claim['claim_text']),'','状态：`'+claim['verification_status']+'`；'+safe(claim['limitation_note']),'']
        items=[e for e in material['evidence'] if e['claim_id']==claim['id'] and e['source_id'] in sources]
        if not items:
            lines+=['未取得可定位的实际来源摘录。','']
        for item in items:
            source=sources[item['source_id']]
            lines+=['- '+link(source)+'；关系：`'+item['relation']+'`；位置：'+safe(item['location_hint'] or '未知'),'> '+safe(item['quote_or_excerpt']),'']
    if not claims:
        lines+=['尚未形成有证据关联的主张。以下仅为已取得的原始材料摘录，未经主张核验：','']
        for source in list(sources.values())[:10]:
            lines += ['- '+link(source),'> '+safe(source['extracted_text'][:400]),'']
    lines+=['## 来源冲突与不确定性','']
    uncertain=[c for c in claims if c['verification_status']!='SUPPORTED']
    lines += ['- `'+c['verification_status']+'`：'+safe(c['claim_text'])+'；'+safe(c['limitation_note']) for c in uncertain] or ['未发现已记录的来源冲突；这不证明不存在冲突。']
    lines+=['','## 局限性','', '- 自动核验检查实际正文、逐字摘录、词面关联和来源域名；不是人工事实认证，可能漏检冲突或误判语义。',
            '- 跨语言转述可能因词面关联不足而保持未核实；同一域名按非独立来源处理，域名不同也不保证内容独立。',
            '- DeepSeek Fetch 不返回最终 URL 或跳转链；来源日期可能来自搜索服务，未经独立确认。',
            '- 抓取失败、截断正文、预算及时间上限会影响覆盖；缺失作者或日期不猜测。','', '## 来源清单','']
    for source in sources.values():
        lines += ['- '+link(source)+'；抓取时间：'+safe(source['retrieved_at'])+'；报告的发布日期：'+safe(source.get('published_at') or '未知')]
    failures=sum(s['fetch_status']=='FAILED' for s in material['sources'])
    usage=task['usage']
    lines+=['',f'失败来源记录：{failures} 条；完整证据关联保存在本地数据库。','','## 用量与停止条件','',
            '- 实际研究：'+str(usage.get('rounds',0))+' 轮；搜索 '+str(usage.get('search_requests',0))+' 次；正文获取尝试 '+str(usage.get('fetch_requests',0))+' 次。',
            '- 模型调用：'+str(usage.get('model_call_attempts',0))+' 次；输入 '+str(usage.get('input_tokens',0))+' tokens，输出 '+str(usage.get('output_tokens',0))+' tokens。',
            '- 已记录耗时：'+str(usage.get('duration_seconds',0))+' 秒。',
            '- 费用估算：'+(str(usage['cost_estimate_usd'])+' USD' if usage.get('cost_estimate_usd') is not None else '不可可靠估算')+'；'+safe(usage.get('cost_note','用量尚不完整。')),'']
    return '\n'.join(lines)
