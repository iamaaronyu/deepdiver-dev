export type Health = {status:string; stage:string; model_configured:boolean; search_configured:boolean; worker_running:boolean};
export type Settings = {depth?:'standard'|'deep'; max_rounds:number; max_search_requests:number; max_sources_per_query:number; timeout_seconds:number; max_budget_usd?:number|null};
export type Task = {id:string; question:string; status:string; created_at:string; updated_at:string; cancel_requested:boolean; error_message:string|null; config:Settings; usage:Record<string,unknown>};
export type Source = {id:string; url:string; canonical_url:string; title:string; fetch_status:string; retrieved_at:string; published_at:string|null; excerpt:string; error_code:string|null; redirect_chain_verified:boolean};
export type Claim = {id:string; claim_text:string; verification_status:string; limitation_note:string; importance:number};
export type Evidence = {id:string; claim_id:string; source_id:string; quote_or_excerpt:string; location_hint:string|null; relation:string; verification_status:string};
export type Material = {claims:Claim[]; evidence:Evidence[]; sources:Source[]; subtasks:{id:string;question:string;status:string}[]};
export type ResearchEvent = {id:number; type:string; created_at:string; data:Record<string,unknown>};
export type Summary = {total:number; running:number; completed:number; stopped:number};
export const terminal = new Set(['COMPLETED','FAILED','CANCELLED','BUDGET_EXCEEDED','TIMED_OUT']);
export const statusNames:Record<string,string> = {CREATED:'排队中',PLANNING:'规划问题',RESEARCHING:'收集资料',VERIFYING:'核验证据',NEEDS_MORE_RESEARCH:'补充研究',WRITING:'整理报告',COMPLETED:'已完成',FAILED:'执行失败',CANCELLED:'已取消',BUDGET_EXCEEDED:'达到预算上限',TIMED_OUT:'已超时',SUPPORTED:'支持',PARTIALLY_SUPPORTED:'部分支持',CONTRADICTED:'存在反证',UNVERIFIED:'未核实',OUTDATED_RISK:'时效风险',FETCHED:'已获取正文',DUPLICATE_URL:'重复链接',DUPLICATE_CONTENT:'重复正文'};
export const eventNames:Record<string,string> = {'plan.created':'研究计划已生成','plan.updated':'已调整补充研究计划','search.started':'开始搜索资料','source.discovered':'已收集来源','verification.updated':'证据核验已更新','research.iteration':'开始研究轮次','report.progress':'正在综合分析与成文','report.analysis_fallback':'分析校验未通过，保留证据报告','report.analysis_reviewed':'已审查分析与证据的一致性','task.completed':'研究已完成','task.failed':'研究执行失败','task.stopped':'研究已停止','task.cancel_requested':'已提交取消请求','evidence.rejected':'已排除无法定位的引用','model.output_rejected':'模型输出未通过校验'};
export function formatTime(value:string) {return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value));}
export function safeHref(value:string) {try { const url=new URL(value); return ['http:','https:'].includes(url.protocol)?url.href:undefined; } catch { return undefined; }}
export function count(value:unknown) {return typeof value==='number'&&Number.isFinite(value)?value:0;}
export async function api<T>(path:string,options?:RequestInit):Promise<T> {
  const response=await fetch(path,{cache:'no-store',...options});
  if(!response.ok) {let message='请求未完成，请稍后重试。';try {const data=await response.json();message=data.error?.message||message;}catch{}throw new Error(message);}
  return response.json();
}
export function taskLink(id:string) {return '/task/?id='+encodeURIComponent(id);}
