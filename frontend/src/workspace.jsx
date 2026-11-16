import { useState } from 'react';
import { ArrowRight, ArrowUpRight, Globe2, Radar, Search, Sparkles } from 'lucide-react';
import { activeJob } from './api';
import { RunConfig } from './config';
import { Button, Empty, FormError, Guide, PageHead, Progress, SectionHead, StageRail } from './ui';
import { RecentReports, ReportView } from './results';

export default function Workspace({ settings, health, job, onRun, onCancel, report, reportPath, reports, onOpen, navigate }) {
  const [url, setUrl] = useState('');
  const [config, setConfig] = useState(settings);
  const [error, setError] = useState('');
  const busy = activeJob(job);
  async function submit(event) {
    event.preventDefault(); setError('');
    let target = url.trim();
    if (!target) { setError('请输入要调查的网址。'); return; }
    if (!target.includes('://')) target = `https://${target}`;
    try { const parsed = new URL(target); if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) throw new Error(); }
    catch { setError('请输入有效的 HTTP 或 HTTPS 网址，不要包含用户名和密码。'); return; }
    try { await onRun({ ...config, kind: 'diagnose', url: target }); }
    catch (error) { setError(error.message); }
  }
  return <><PageHead title="网站访问诊断" description="从解析到响应，循着证据找到问题。"><Button variant="secondary" onClick={() => navigate('lab')}>故障实验室 <ArrowUpRight size={15} /></Button></PageHead>
    <div className="workspace-layout"><div className="workspace-primary"><form className="panel diagnostic-form" onSubmit={submit}><SectionHead icon={Radar} title="新建诊断" description="一个网址，一次完整的基础访问调查。"><span className="subtle-mark"><ShieldLabel /></span></SectionHead>
      <label htmlFor="target-url" className="url-label">目标网址</label><div className="url-input"><Globe2 size={21} /><input id="target-url" type="text" inputMode="url" autoComplete="url" placeholder="输入网址，例如 https://www.bilibili.com" value={url} onChange={e => setUrl(e.target.value)} disabled={busy} /><Button type="submit" disabled={busy} loading={busy}>开始诊断 {!busy ? <ArrowRight size={16} /> : null}</Button></div>
      <FormError>{error}</FormError><RunConfig value={config} onChange={setConfig} health={health} disabled={busy} />
      <div className="form-bottom"><Sparkles size={14} /><span>工具负责测量，模型协助调查，结论保留证据。</span></div>
    </form>
      {job?.options.kind === 'diagnose' ? <Progress job={job} onCancel={onCancel} /> : null}
      {report && job?.options.kind === 'diagnose' ? <ReportView report={report} path={reportPath} key={reportPath} /> : !busy ? <section className="panel ready-panel"><StageRail /><Empty title="准备好开始一次调查" icon={Search}>输入目标网址，依次查看 DNS、TCP、TLS 和 HTTP 的实测证据。</Empty></section> : null}
    </div><Guide onLab={() => navigate('lab')} /></div>
    <RecentReports reports={reports} onOpen={onOpen} onAll={() => navigate('archive')} />
  </>;
}
function ShieldLabel() { return <><span className="local-dot" />本机直连</>; }
