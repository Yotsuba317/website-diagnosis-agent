import { useState } from 'react';
import { Activity, ArrowRight, CheckCircle2, CircleHelp, FlaskConical, Globe2, Network, ShieldAlert, Timer, TriangleAlert } from 'lucide-react';
import { activeJob } from './api';
import { RunConfig } from './config';
import { Button, FormError, Notice, PageHead, Progress, SectionHead, Tag } from './ui';
import { ReportView } from './results';

const caseInfo = {
  normal: { icon: CheckCircle2, name: '正常访问', desc: '本地 HTTP 服务返回 200，建立一次正常访问基线。', stage: '基础访问正常' },
  dns_failure: { icon: Globe2, name: 'DNS 解析失败', desc: '明确标记的 NXDOMAIN 模拟观测，验证前置失败停止。', stage: 'DNS 阶段' },
  tcp_failure: { icon: Network, name: 'TCP 连接失败', desc: '保留本机端口但不监听，复现连接阶段失败。', stage: 'TCP 阶段' },
  tls_failure: { icon: ShieldAlert, name: 'TLS 握手失败', desc: '用 HTTPS 连接只支持 HTTP 的本地服务。', stage: 'TLS 阶段' },
  http_error: { icon: TriangleAlert, name: 'HTTP 错误响应', desc: '本地服务返回 HTTP 503，验证服务错误响应判断。', stage: 'HTTP 阶段' },
  slow_response: { icon: Timer, name: '响应等待偏长', desc: '在发送响应头前等待约 1.2 秒，复现慢响应。', stage: '响应等待' },
  insufficient_evidence: { icon: CircleHelp, name: '关键证据缺失', desc: '保留 DNS/TCP 模拟观测，明确缺少 HTTP 检查。', stage: '证据完整性' },
};

export default function Lab({ cases, settings, health, job, onRun, onCancel, report, reportPath }) {
  const [selected, setSelected] = useState('http_error');
  const [config, setConfig] = useState(settings);
  const [error, setError] = useState('');
  const busy = activeJob(job);
  async function submit(event) { event.preventDefault(); setError(''); try { await onRun({ ...config, kind: 'demo', case_id: selected }); } catch (error) { setError(error.message); } }
  return <><PageHead title="故障实验室" description="不必等待真实故障，用可重复的场景验证调查流程。" /><Notice>实验服务只在本机临时启动并自动关闭。DNS 失败和关键证据缺失使用明确标记的模拟夹具，其余案例使用真实本机探测。</Notice>
    <div className="lab-layout"><form onSubmit={submit} className="lab-main"><section className="panel case-section"><SectionHead icon={FlaskConical} title="选择一个调查场景" description="七种情形，覆盖从域名解析到证据不足的完整链路。" /><div className="case-grid">{cases.map(item => { const info = caseInfo[item.id], Icon = info.icon; return <button className={`case-card ${selected === item.id ? 'selected' : ''}`} type="button" key={item.id} onClick={() => setSelected(item.id)} aria-pressed={selected === item.id} disabled={busy}><div className="case-top"><span className="case-icon"><Icon size={20} /></span><span className="radio-circle">{selected === item.id ? <span /> : null}</span></div><h3>{info.name}</h3><p>{info.desc}</p><span className={`source-label ${item.source === 'synthetic_fixture' ? 'synthetic' : ''}`}><span className="status-dot" />{item.source === 'synthetic_fixture' ? '模拟夹具' : '本机实测'}</span></button>; })}</div></section>
      <section className="panel lab-config"><SectionHead title="配置本次实验" description="可用真实模型调查，也可先验证确定性工具链。" /><RunConfig value={config} onChange={setConfig} health={health} disabled={busy} advanced={false} /><FormError>{error}</FormError><div className="form-footer"><span>已选：{caseInfo[selected].name}</span><Button type="submit" disabled={busy} loading={busy}>运行实验 <ArrowRight size={16} /></Button></div></section>
    </form><aside className="lab-explanation"><div className="experiment-symbol"><FlaskConical size={36} strokeWidth={1.2} /></div><h2>让异常可以复现，<br />让判断可以核对。</h2><p>每个案例都有已知的故障构造方式。查看模型如何取得证据，再检查它的结论和建议是否可靠。</p><dl><div><dt>当前观察重点</dt><dd>{caseInfo[selected].stage}</dd></div><div><dt>结果留存</dt><dd>Markdown 报告 + JSON Trace</dd></div><div><dt>环境变更</dt><dd>不修改 DNS、代理或防火墙</dd></div></dl><Notice tone="warning">规则测试能验证工具，不能证明大模型或 Skill 的效果。</Notice></aside></div>
    {job?.options.kind === 'demo' ? <Progress job={job} onCancel={onCancel} /> : null}
    {report && job?.options.kind === 'demo' ? <ReportView key={reportPath} report={report} path={reportPath} /> : null}
  </>;
}
