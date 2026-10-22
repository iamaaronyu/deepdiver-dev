import type {Metadata} from 'next';
import Shell from '@/components/shell';
import './globals.css';
export const metadata:Metadata={title:'DeepDive · 研究工作空间',description:'创建研究、追踪证据、阅读可追溯报告'};
export default function RootLayout({children}:{children:React.ReactNode}) {return <html lang="zh-CN"><body><Shell>{children}</Shell></body></html>;}
