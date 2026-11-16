import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, ChevronDown, LoaderCircle, Download, TriangleAlert, Globe2, Network, ShieldCheck, FileCheck2, CircleHelp } from 'lucide-react';
import { activeJob, date, eventLabel, reportUrl } from './api';

export function Button({ children, variant = 'primary', className = '', loading, ...props }) {
  return <button className={`button ${variant} ${className}`} {...props}>{loading ? <LoaderCircle size={16} className="spin" /> : null}{children}</button>;
}
export function Empty({ title, children, action, icon: Icon = FileCheck2 }) {
  return <div className="empty"><div className="empty-icon"><Icon size={27} strokeWidth={1.5} /></div><h3>{title}</h3><p>{children}</p>{action}</div>;
}
export function SectionHead({ icon: Icon, title, description, children }) {
  return <div className="section-head"><div className="section-name">{Icon ? <Icon size={19} /> : null}<div><h2>{title}</h2>{description ? <p>{description}</p> : null}</div></div>{children}</div>;
}
export function PageHead({ title, description, children }) {
  return <header className="page-head"><div><h1>{title}</h1><p>{description}</p></div>{children}</header>;
}
export function Tag({ children, tone = 'neutral' }) { return <span className={`tag ${tone}`}>{children}</span>; }
export function Notice({ children, tone = 'info' }) { return <div className={`notice ${tone}`}><CircleHelp size={16} /><div>{children}</div></div>; }
export function Downloads({ path, compact = false }) {
  if (!path) return null;
  return <div className="downloads"><a className={`button ${compact ? 'text-button' : 'secondary'}`} href={reportUrl(path, 'md')} download><Download size={15} />{compact ? '报告' : '下载报告'}</a><a className="button text-button" href={reportUrl(path, 'json')} download>JSON</a></div>;
}
export function JsonBlock({ value }) { return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>; }
export function FormError({ children }) { return children ? <div className="form-error" role="alert"><TriangleAlert size={17} />{children}</div> : null; }

export function StageRail({ evidence = [], running = false, modelActive = false }) {
  const records = Object.fromEntries(evidence.map(item => [item.tool, item]));
  const dns = records.check_dns, tcp = records.check_tcp, http = records.check_http;
  const stages = [
    { name: 'DNS', desc: dns?.ip_literal ? 'IP 地址输入' : '域名解析', icon: Globe2, result: dns },
    { name: 'TCP', desc: '端口连接', icon: Network, result: tcp },
    { name: 'TLS', desc: http?.tls_checked === false ? 'HTTP 不适用' : '安全握手', icon: ShieldCheck,
      result: http ? { status: http.tls_checked === false || http.scheme === 'http' ? 'skipped' : http.error_type === 'tls_error' ? 'error' : http.tls_checked === true && http.status === 'ok' ? 'ok' : 'unavailable' } : null },
    { name: 'HTTP', desc: http?.slow ? '响应等待偏长' : '响应检查', icon: FileCheck2, result: http ? { ...http, status: http.http_error ? 'error' : http.status } : null },
  ];
  const next = !dns ? 0 : dns.status !== 'ok' ? -1 : !tcp ? 1 : tcp.status !== 'ok' ? -1 : !http ? 2 : -1;
  return <div className="stage-rail">{stages.map(({ name, desc, icon: Icon, result }, index) => {
    const status = result?.status;
    const state = status === 'ok' ? 'done' : status === 'error' ? 'fault' : status ? 'skipped' : running && index === next && !modelActive ? 'current' : 'waiting';
    return <div className={`stage ${state}`} key={name}><div className="stage-icon">{state === 'done' ? <Check size={17} /> : state === 'current' ? <LoaderCircle size={17} className="spin" /> : <Icon size={17} />}</div><div><strong>{name}</strong><span>{status === 'error' ? '检测到异常' : desc}</span></div>{index < 3 ? <div className="stage-line" /> : null}</div>;
  })}</div>;
}

export function Progress({ job, onCancel }) {
  const [expanded, setExpanded] = useState(false);
  const container = useRef(null);
  useEffect(() => {
    if (job?.id) container.current?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'center' });
  }, [job?.id]);
  if (!job) return null;
  const running = activeJob(job), events = job.events || [];
  const tools = Object.values(Object.fromEntries(events.filter(event => event.type === 'tool' && event.accepted).map(event => [event.tool, { tool: event.tool, ...event.result }])));
  const last = events.at(-1);
  const status = { queued: '等待运行', running: '正在调查', cancelling: '正在停止', completed: '调查已完成', failed: '执行未成功', cancelled: '已停止', interrupted: '服务已重启' }[job.status];
  const finalMessage = job.status === 'completed' ? (job.options.kind === 'evaluate' ? '评测已完成，结果与完整 Trace 已保存。' : '报告已保存，可以查看证据或下载报告。') : job.status === 'failed' && job.report_paths?.length ? '模型执行未成功，已有观测和错误详情已保存在报告中。' : job.error || eventLabel(last);
  return <section ref={container} className={`panel progress-panel ${job.status}`} aria-live="polite"><div className="progress-title"><div className={`progress-dot ${running ? 'pulse' : ''}`} /><strong>{status}</strong><span>{job.started_at ? date(job.started_at) : '任务已加入队列'}</span>{running && job.status !== 'cancelling' ? <Button variant="text-button" onClick={() => onCancel(job.id)}>停止后续步骤</Button> : null}</div>
    {job.options.kind !== 'evaluate' ? <StageRail evidence={tools} running={running} modelActive={last?.type === 'model_started'} /> : null}
    <div className="progress-message">{running ? <LoaderCircle size={15} className="spin" /> : job.status === 'failed' ? <TriangleAlert size={15} /> : <Check size={15} />}{job.status === 'cancelling' ? '等待当前网络或模型调用结束后停止，不会继续下一步。' : running ? eventLabel(last) : finalMessage}</div>
    <button className="log-toggle" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>查看运行记录 <ChevronDown size={14} className={expanded ? 'rotate' : ''} /></button>
    {expanded ? <ol className="event-log">{events.map((event, index) => <li key={index}><time>{new Date(event.at).toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}</time><span>{eventLabel(event)}</span></li>)}</ol> : null}
  </section>;
}

export function Guide({ onLab }) {
  return <aside className="guide"><div className="guide-heading"><span className="tiny-line" /> 一次有据可依的调查</div><ol className="guide-steps"><li><span>01</span><div><strong>输入遇到问题的网址</strong><p>从当前电脑直连目标，检查实际访问链路。</p></div></li><li><span>02</span><div><strong>让工具取得真实证据</strong><p>依次检查解析、连接与响应，前置失败即停止后续检查。</p></div></li><li><span>03</span><div><strong>带着证据，继续排查</strong><p>查看异常阶段、未验证项与下一步建议，导出完整报告。</p></div></li></ol>
    <div className="lab-invite"><div className="orbit-mark"><span /><Globe2 size={31} strokeWidth={1.1} /><span /></div><h3>不必等故障发生。</h3><p>用七种可重复的本地场景，熟悉完整调查流程。</p><button onClick={onLab}>进入故障实验室 <ArrowRight size={16} /></button></div>
    <div className="scope-note"><ShieldCheck size={17} /><p>不会修改 DNS、代理或防火墙配置。检测结果只代表本机、本次直连访问。</p></div>
  </aside>;
}
