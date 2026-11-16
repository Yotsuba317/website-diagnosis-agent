import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, ArrowRight, FileSearch, RefreshCw, Search } from 'lucide-react';
import { api } from './api';
import { Button, Empty, FormError, PageHead } from './ui';
import { RecentReports, ReportView } from './results';

export default function Archive({ reports, selectedPath, onOpen, onBack, onRefresh, refreshing }) {
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const [engine, setEngine] = useState('all');
  const [page, setPage] = useState(0);
  const [report, setReport] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!selectedPath) { setReport(null); setError(''); return; }
    const controller = new AbortController(); setReport(null); setError('');
    api(`/report?path=${encodeURIComponent(selectedPath)}`, { signal: controller.signal }).then(setReport).catch(error => { if (error.name !== 'AbortError') setError(error.message); });
    return () => controller.abort();
  }, [selectedPath]);
  const filtered = useMemo(() => reports.filter(row => {
    const matches = `${row.url} ${row.case_id || ''} ${row.path} ${row.model || ''}`.toLowerCase().includes(search.toLowerCase());
    return matches && (engine === 'all' || row.engine === engine) && (filter === 'all' || (filter === 'normal' ? row.diagnosis === 'normal' : filter === 'failed' ? row.diagnosis === 'execution_error' : filter === 'uncertain' ? row.diagnosis === 'insufficient_evidence' : !['normal', 'execution_error', 'insufficient_evidence'].includes(row.diagnosis)));
  }), [reports, search, filter, engine]);
  const pages = Math.max(1, Math.ceil(filtered.length / 10));
  const currentPage = Math.min(page, pages - 1);
  if (selectedPath) return <><PageHead title="调查报告" description="保留原始观测，核对每一项判断。"><Button variant="secondary" onClick={onBack}><ArrowLeft size={15} />返回报告档案</Button></PageHead><FormError>{error}</FormError>{report ? <ReportView key={selectedPath} report={report} path={selectedPath} /> : !error ? <div className="panel loading-panel">正在读取报告…</div> : null}</>;
  return <><PageHead title="报告档案" description="把每一次调查，变成下一次排查的依据。"><Button variant="secondary" onClick={onRefresh} loading={refreshing}><RefreshCw size={15} />刷新档案</Button></PageHead><section className="panel archive-tools"><div className="search-field"><Search size={18} /><input aria-label="搜索报告" placeholder="搜索网址、案例、模型或文件路径" value={search} onChange={e => { setSearch(e.target.value); setPage(0); }} /></div><select aria-label="按诊断结果筛选" value={filter} onChange={e => { setFilter(e.target.value); setPage(0); }}><option value="all">全部结果</option><option value="normal">基础访问正常</option><option value="abnormal">检测到异常</option><option value="uncertain">证据不足</option><option value="failed">模型执行未成功</option></select><select aria-label="按运行引擎筛选" value={engine} onChange={e => { setEngine(e.target.value); setPage(0); }}><option value="all">全部引擎</option><option value="ollama">Ollama 模型</option><option value="rules">规则工具测试</option></select></section>
    {filtered.length ? <RecentReports reports={filtered.slice(currentPage * 10, (currentPage + 1) * 10)} limit={10} onOpen={onOpen} /> : <section className="panel"><Empty title="没有符合条件的报告" icon={FileSearch}>换一个关键词或筛选条件，或先完成一次诊断。</Empty></section>}
    <div className="pagination"><span>共 {filtered.length} 份报告 · 当前第 {currentPage + 1} / {pages} 页</span><div><Button variant="secondary" aria-label="上一页" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}><ArrowLeft size={15} /></Button><Button variant="secondary" aria-label="下一页" disabled={currentPage >= pages - 1} onClick={() => setPage(currentPage + 1)}><ArrowRight size={15} /></Button></div></div>
  </>;
}
