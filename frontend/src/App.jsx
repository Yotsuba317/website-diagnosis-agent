import { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, ArrowUpRight, CheckCircle2, ChevronRight, CircleHelp, FileClock, FlaskConical, GitCompareArrows, Home, LoaderCircle, Menu, Radar, Settings2, ShieldCheck, X } from 'lucide-react';
import { activeJob, api, date, LABELS, loadSettings, post } from './api';
import Workspace from './workspace';
import Lab from './lab';
import Evaluations from './evaluations';
import Archive from './archive';
import Settings from './config';

const navigation = [
  { id: 'workspace', name: '网站诊断', icon: Radar }, { id: 'lab', name: '故障实验室', icon: FlaskConical },
  { id: 'evaluations', name: '对照评测', icon: GitCompareArrows }, { id: 'archive', name: '报告档案', icon: FileClock },
];
const names = { ...Object.fromEntries(navigation.map(item => [item.id, item.name])), settings: '运行设置' };

export default function App() {
  const [page, setPage] = useState(() => names[location.hash.slice(1)] ? location.hash.slice(1) : 'workspace');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isMobile, setMobile] = useState(() => matchMedia('(max-width: 760px)').matches);
  const [settings, setSettings] = useState(loadSettings);
  const [bootstrap, setBootstrap] = useState(null);
  const [health, setHealth] = useState(null);
  const [checking, setChecking] = useState(false);
  const [reports, setReports] = useState([]);
  const [evaluations, setEvaluations] = useState([]);
  const [evaluation, setEvaluation] = useState(null);
  const [job, setJob] = useState(null);
  const [result, setResult] = useState(null);
  const [archivePath, setArchivePath] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState('');
  const [fatalError, setFatalError] = useState('');
  const toastTimer = useRef();
  const help = useRef();
  const handledJob = useRef(null);
  useEffect(() => {
    const query = matchMedia('(max-width: 760px)');
    const update = () => setMobile(query.matches);
    const escape = event => { if (event.key === 'Escape') setSidebarOpen(false); };
    query.addEventListener('change', update); window.addEventListener('keydown', escape);
    return () => { query.removeEventListener('change', update); window.removeEventListener('keydown', escape); };
  }, []);
  const [formVersion, setFormVersion] = useState(0);
  const toast = useCallback(text => { setMessage(text); clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => setMessage(''), 4500); }, []);
  const navigate = useCallback(next => { setPage(next); location.hash = next; setSidebarOpen(false); window.scrollTo({ top: 0, behavior: 'instant' }); }, []);
  const openReport = useCallback(path => { setArchivePath(path); navigate('archive'); }, [navigate]);
  const refresh = useCallback(async () => {
    setRefreshing(true);
    try { const [reportData, evaluationData] = await Promise.all([api('/reports'), api('/evaluations')]); setReports(reportData.reports); setEvaluations(evaluationData.evaluations); }
    catch (error) { toast(error.message); }
    finally { setRefreshing(false); }
  }, [toast]);
  const checkHealth = useCallback(async host => {
    setChecking(true);
    try { setHealth(await api(`/health?host=${encodeURIComponent(host)}`)); }
    catch (error) { toast(error.message); }
    finally { setChecking(false); }
  }, [toast]);
  useEffect(() => {
    let alive = true;
    Promise.all([api('/bootstrap'), api('/jobs')]).then(([data, jobs]) => {
      if (!alive) return;
      setBootstrap(data);
      const running = jobs.jobs.find(activeJob); if (running) setJob(running);
    }).catch(error => { if (alive) setFatalError(error.message); });
    refresh(); checkHealth(settings.host);
    const onHash = () => { if (names[location.hash.slice(1)]) setPage(location.hash.slice(1)); };
    window.addEventListener('hashchange', onHash);
    return () => { alive = false; window.removeEventListener('hashchange', onHash); clearTimeout(toastTimer.current); };
  }, [refresh, checkHealth]);
  const jobId = job?.id, isRunning = activeJob(job);
  useEffect(() => {
    if (!jobId || !isRunning) return;
    const controller = new AbortController(); let timer;
    async function poll() {
      try {
        const next = await api(`/jobs/${jobId}`, { signal: controller.signal }); setJob(next);
        if (activeJob(next)) timer = setTimeout(poll, 700);
      } catch (error) { if (error.name !== 'AbortError') { toast('连接暂时中断，正在重试…'); timer = setTimeout(poll, 2500); } }
    }
    poll(); return () => { clearTimeout(timer); controller.abort(); };
  }, [jobId, isRunning, toast]);
  useEffect(() => {
    if (!job || activeJob(job) || handledJob.current === job.id) return;
    handledJob.current = job.id;
    refresh();
    if (job.options.kind === 'evaluate' && job.evaluation_path) {
      api(`/evaluation?path=${encodeURIComponent(job.evaluation_path)}`).then(report => setEvaluation({ path: job.evaluation_path, report })).catch(error => toast(error.message));
    } else if (job.report_paths?.[0]) {
      const path = job.report_paths[0];
      api(`/report?path=${encodeURIComponent(path)}`).then(report => setResult({ path, report })).catch(error => toast(error.message));
    }
    toast(job.status === 'completed' ? '调查完成，报告已保存' : job.status === 'cancelled' ? '后续步骤已停止' : '任务结束，观测与错误记录已保留');
  }, [job, refresh, toast]);

  async function run(options) {
    if (activeJob(job)) throw new Error('当前已有任务正在运行，请完成或停止后再开始。');
    const next = await post('/jobs', options);
    handledJob.current = null; setResult(null); setJob(next);
    toast('任务已开始，正在取得真实观测');
  }
  async function cancel(id) { try { setJob(await post(`/jobs/${id}/cancel`, {})); } catch (error) { toast(error.message); } }
  function saveSettings(value) {
    let persisted = true;
    try { localStorage.setItem('netlens:settings:v1', JSON.stringify(value)); }
    catch { persisted = false; }
    setSettings(value); setFormVersion(version => version + 1); checkHealth(value.host); toast(persisted ? '默认配置已保存' : '已应用本次配置；浏览器无法保存偏好');
  }
  async function selectEvaluation(path) {
    if (!path) { setEvaluation(null); return; }
    try { const report = await api(`/evaluation?path=${encodeURIComponent(path)}`); setEvaluation({ path, report }); }
    catch (error) { toast(error.message); }
  }
  const shared = { settings, health, job, onRun: run, onCancel: cancel, report: result?.report, reportPath: result?.path };
  return <div className="app-shell">
    {sidebarOpen ? <button className="sidebar-overlay" aria-label="关闭导航" onClick={() => setSidebarOpen(false)} /> : null}
    <aside id="main-navigation" inert={isMobile && !sidebarOpen ? true : undefined} className={`sidebar ${sidebarOpen ? 'open' : ''}`}><a href="#workspace" className="brand" onClick={() => navigate('workspace')}><span className="brand-symbol"><Radar size={25} strokeWidth={1.65} /></span><span>NetLens<small>网站诊断工作台</small></span></a><span className="nav-caption">工作空间</span><nav aria-label="主导航">{navigation.map(({ id, name, icon: Icon }) => <button key={id} className={`nav-item ${page === id ? 'active' : ''}`} onClick={() => { if (id === 'archive') setArchivePath(null); navigate(id); }}><Icon size={18} /><span>{name}</span>{id === 'archive' && reports.length ? <span className="nav-count">{reports.length}</span> : null}</button>)}</nav>
      <div className="sidebar-recent"><div className="nav-caption">最近访问的报告</div>{reports.slice(0, 3).map(row => <button key={row.path} onClick={() => openReport(row.path)}><span className={`small-dot ${row.diagnosis === 'normal' ? 'success' : 'warning'}`} /><span>{row.url.replace(/^https?:\/\//, '')}<small>{date(row.started_at)}</small></span><ChevronRight size={13} /></button>)}{!reports.length ? <p>尚未生成调查报告</p> : null}</div>
      <div className="sidebar-bottom"><button className={`nav-item ${page === 'settings' ? 'active' : ''}`} onClick={() => navigate('settings')}><Settings2 size={18} />运行设置</button><button className="nav-item" onClick={() => help.current?.showModal()}><CircleHelp size={18} />使用说明 <ArrowUpRight size={13} /></button><div className="local-workspace"><ShieldCheck size={18} /><div>本机工作区<span>数据与报告保存在本地</span></div></div></div>
    </aside>
    <div className="main-shell"><header className="topbar"><button className="icon-button mobile-menu" aria-label="展开导航" onClick={() => setSidebarOpen(true)}><Menu size={20} /></button><div className="breadcrumb"><Home size={14} /><ChevronRight size={12} /><span>工作空间</span><ChevronRight size={12} /><strong>{names[page]}</strong></div><div className="topbar-actions">{isRunning ? <button className="running-task" onClick={() => navigate(job.options.kind === 'evaluate' ? 'evaluations' : job.options.kind === 'demo' ? 'lab' : 'workspace')}><LoaderCircle size={13} className="spin" />返回进行中的任务</button> : null}<span className="today">{new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'long', day: 'numeric', weekday: 'long' }).format(new Date())}</span><button className="service-status" onClick={() => navigate('settings')}><span className={`small-dot ${checking ? 'checking' : health?.connected ? 'success' : 'warning'}`} />{checking ? '检查模型服务' : health?.connected ? 'Ollama 已连接' : '模型未连接'}<ChevronRight size={13} /></button></div></header>
      <main className="main-content" id="main-content">{fatalError ? <div className="fatal-error"><h1>工作台暂时无法连接</h1><p>{fatalError}</p><button className="button primary" onClick={() => location.reload()}>重新连接</button></div> : !bootstrap ? <div className="app-loading"><LoaderCircle size={25} className="spin" /><p>正在准备你的调查工作台…</p></div> : page === 'workspace' ? <Workspace key={`workspace-${formVersion}`} {...shared} reports={reports} onOpen={openReport} navigate={navigate} /> : page === 'lab' ? <Lab key={`lab-${formVersion}`} {...shared} cases={bootstrap.cases} /> : page === 'evaluations' ? <Evaluations key={`evaluations-${formVersion}`} {...shared} cases={bootstrap.cases} evaluations={evaluations} selected={evaluation} onSelect={selectEvaluation} /> : page === 'archive' ? <Archive reports={reports} selectedPath={archivePath} onOpen={openReport} onBack={() => setArchivePath(null)} onRefresh={refresh} refreshing={refreshing} /> : <Settings settings={settings} onSave={saveSettings} health={health} onCheck={checkHealth} checking={checking} output={bootstrap.output} onLab={() => navigate('lab')} toast={toast} />}
      <footer className="page-footer"><span>NetLens · 网站访问异常调查</span><span>用实测说明现象，用证据保留边界。</span></footer></main>
    </div>
    {message ? <div className="toast" role="status"><CheckCircle2 size={18} />{message}<button aria-label="关闭提示" onClick={() => setMessage('')}><X size={15} /></button></div> : null}
    <dialog className="help-dialog" ref={help}><button className="icon-button dialog-close" aria-label="关闭使用说明" onClick={() => help.current?.close()}><X size={19} /></button><span className="help-mark"><Radar size={30} /></span><h2>从一个网址开始。</h2><p>在“网站诊断”输入 HTTP/HTTPS 网址，选择本地模型并开始调查。没有模型时，可进入“故障实验室”选择规则工具测试。</p><ol><li>在“运行设置”检查 Ollama 连接，选择已下载的模型。</li><li>使用“故障实验室”复现七种场景，核对实测与模拟来源。</li><li>在报告中查看证据、建议、模型草稿和校验记录。</li><li>需要课程实验时，在“对照评测”比较 A/B/C 三种方式。</li></ol><p className="muted">本机直连探测不验证网页正文、渲染、登录和完整业务。不会修改你的网络配置。</p><button className="button primary" onClick={() => help.current?.close()}>开始使用 <ChevronRight size={16} /></button></dialog>
  </div>;
}
