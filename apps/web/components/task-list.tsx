'use client';
import {Task,formatTime,taskLink} from '@/lib/api';
import {Badge,Empty} from './shell';
export function TaskList({tasks}:{tasks:Task[]}) {if(!tasks.length)return <Empty title="还没有研究记录">从一个具体的问题开始，研究完成后会保存在这里。</Empty>;return <div className="task-list">{tasks.map(task=><a className="task-row" key={task.id} href={taskLink(task.id)}><div className="task-symbol" aria-hidden="true">≋</div><div className="task-text"><h3>{task.question}</h3><div><time>{formatTime(task.created_at)}</time><span>·</span><span>{task.cancel_requested&&!['COMPLETED','CANCELLED','FAILED','TIMED_OUT','BUDGET_EXCEEDED'].includes(task.status)?'取消请求已提交':'研究任务'}</span></div></div><Badge status={task.status}/><span className="row-arrow" aria-hidden="true">→</span></a>)}</div>;}
