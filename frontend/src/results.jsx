import { useEffect, useRef, useState } from 'react';
import { Activity, ArrowRight, ArrowUpRight, CheckCircle2, CircleAlert, Clock3, Code2, FileCheck2, FileSearch, Globe2, Network, ShieldCheck, Sparkles, Timer, TriangleAlert } from 'lucide-react';
import { date, LABELS, MODES, tone } from './api';
import { Downloads, Empty, JsonBlock, Notice, SectionHead, StageRail, Tag } from './ui';

const statusLabels = { ok: '已取得观测', error: '检测到异常', unavailable: '观测缺失', skipped: '未执行', not_ready: '前置条件未满足' };
function Evidence({ item, replayed }) {
  const icon = { check_dns: Globe2, check_tcp: Network, check_http: ShieldCheck };
  const Icon = icon[item.tool] || FileSearch;
  const title = { check_dns: 'DNS · 目标地址', check_tcp: 'TCP · 端口连通', check_http: 'TLS / HTTP · 安全与响应' }[item.tool];
  const entries = [];
  if (item.addresses) entries.push(['解析地址', item.addresses.join('、')]);
  if (item.ip_literal) entries.push(['检测范围', '输入为 IP 地址，本次没有验证 DNS 服务']);
  if (item.address) entries.push(['连接地址', item.address]);
  if (item.port) entries.push(['目标端口', item.port]);
  if (item.elapsed_ms != null) entries.push(['阶段耗时', `${item.elapsed_ms} ms`]);
  if (item.http_status != null) entries.push(['HTTP 状态', item.http_status]);
  if (item.response_wait_ms != null) entries.push(['响应等待', `${item.response_wait_ms} ms`]);
  if (item.slow_threshold_ms != null) entries.push(['配置阈值', `${item.slow_threshold_ms} ms`]);
  if (item.tls_checked != null) entries.push(['TLS 校验', item.tls_checked ? '已执行，握手及证书校验通过' : 'HTTP 请求，不执行 TLS']);
  if (item.tls_checked && item.tls_ms != null) entries.push(['TLS 耗时', `${item.tls_ms} ms（未设置 TLS 慢阈值）`]);
  if (item.error_type) entries.push(['错误类型', item.error_type]);
  if (item.detail || item.reason) entries.push(['详细信息', item.detail || item.reason]);
  return <article className="evidence-card"><header><span className="evidence-id">{item.evidence_id}</span><Icon size={18} /><h3>{title || item.tool}</h3><Tag tone={item.status === 'error' ? 'danger' : item.status === 'ok' ? 'success' : 'warning'}>{statusLabels[item.status] || item.status}</Tag></header><div className="evidence-source">{item.source === 'synthetic_fixture' || item.source === 'recorded_fixture' ? '明确标记的模拟数据' : replayed ? '实测观测回放' : '真实本机探测'}{item.observed_at ? ` · ${date(item.observed_at, true)}` : ''}</div><dl className="evidence-values">{entries.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><details><summary>查看原始工具返回值</summary><JsonBlock value={item} /></details></article>;
}

function TextList({ title, values, icon: Icon = FileCheck2, emptyText = '没有记录此项内容' }) {
  return <section className="finding-section"><h3><Icon size={17} />{title}</h3>{values?.length ? <ul>{values.map((value, index) => <li key={index}>{value}</li>)}</ul> : <p className="muted">{emptyText}</p>}</section>;
}

export function ReportView({ report, path }) {
  const [tab, setTab] = useState('overview');
  const container = useRef(null);
  useEffect(() => { if (path) container.current?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' }); }, [path]);
  if (!report) return null;
  const final = report.final;
  const program = report.program_findings;
  const diagnosis = final?.diagnosis || 'execution_error';
  const http = report.evidence?.find(item => item.tool === 'check_http');
  const replayed = !!report.evaluation?.observations_replayed;
  const Icon = diagnosis === 'normal' ? CheckCircle2 : diagnosis === 'insufficient_evidence' ? CircleAlert : TriangleAlert;
  const tlsStatus = http?.tls_checked ? '校验通过' : http?.error_type === 'tls_error' ? '校验失败' : http?.scheme === 'http' || http?.tls_checked === false ? 'HTTP 不适用' : '未完成检查';
  const tabs = [['overview', '诊断概览'], ['evidence', `检测证据 · ${report.evidence?.length || 0}`], ['model', '模型与校验'], ['json', '完整 JSON']];
  return <section ref={container} className="panel report-view"><div className={`report-banner ${tone(diagnosis)}`}><div className="report-status-icon"><Icon size={26} strokeWidth={1.6} /></div><div className="report-heading"><div><h2>{LABELS[diagnosis]}</h2>{report.engine === 'rules' ? <Tag tone="warning">规则工具测试</Tag> : <Tag tone="neutral">{report.model}</Tag>}{replayed ? <Tag>观测回放</Tag> : null}</div><p>{final?.summary || '模型未能完成有效调查。请在运行设置中检查服务与模型；已取得的工具观测和错误详情仍可查看。'}</p></div><Downloads path={path} /></div>
    <div className="report-meta"><span><Globe2 size={13} /><span>{report.target?.url}</span></span><span><Clock3 size={13} />{date(report.started_at, true)}</span><span>{report.engine === 'rules' ? '规则工具测试' : MODES[report.mode] || report.mode}</span></div>
    <div className="report-tabs" role="tablist" aria-label="报告内容">{tabs.map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{label}</button>)}</div>
    <div className="report-body">
      {!report.narrative_policy && report.engine === 'ollama' ? <Notice tone="warning">这是一份旧版历史报告，未启用当前文字一致性校验。请以原始工具观测为准，旧模型文字可能包含错误。</Notice> : null}
      {tab === 'overview' ? <>
        <div className="result-metrics"><div><span>HTTP 状态</span><strong className={http?.http_error ? 'text-danger' : ''}>{http?.http_status ?? '—'}</strong><small>{http?.http_status ? http.http_error ? '已收到错误响应' : '已收到 HTTP 响应' : '未取得 HTTP 状态'}</small></div><div><span>响应等待</span><strong>{http?.response_wait_ms ?? '—'}<em>ms</em></strong><small>{http?.slow != null ? `${http.slow ? '达到或超过' : '低于'} ${http.slow_threshold_ms} ms 阈值` : '未取得等待耗时'}</small></div><div><span>TLS 安全检查</span><strong className="text-metric">{tlsStatus}</strong><small>不根据单次耗时判断 TLS 偏慢</small></div><div><span>调查总用时</span><strong>{report.elapsed_seconds ?? '—'}<em>s</em></strong><small>{report.llm_requests ?? 0} 次模型调用</small></div></div>
        <StageRail evidence={report.evidence} />
        {report.narrative_repair_used ? <Notice tone="warning">本次模型文字经过程序候选辅助修正。首次草稿、冲突和修正记录保存在“模型与校验”中，不代表模型未经帮助的判断能力。</Notice> : null}
        {report.engine === 'rules' ? <Notice tone="warning">本次未调用大模型。以下结果由确定性规则生成，仅用于验证工具链。</Notice> : null}
        <div className="finding-columns"><div><TextList title="下一步，先从这里开始" values={program?.recommendations} icon={ArrowRight} emptyText="请结合原始证据继续检查。" /><span className="source-caption">程序依据实际观测给出的阶段建议</span>{final && report.engine === 'ollama' ? <><TextList title="模型补充建议" values={final.recommendations} icon={Sparkles} /><span className="source-caption">模型意见仍需结合现场情况核对</span></> : null}</div><div><TextList title="尚未验证的部分" values={final?.uncertainties || program?.uncertainties} icon={CircleAlert} /><TextList title="观测支持与排除" values={final ? [...final.supported_hypotheses.map(text => `支持：${text}`), ...final.rejected_hypotheses.map(text => `排除：${text}`)] : []} icon={ShieldCheck} emptyText="模型未形成有效判断，请查看检测证据。" /></div></div>
        {program && final && program.diagnosis !== final.diagnosis ? <Notice tone="warning">程序阶段核对：{program.summary} 模型分类与程序阶段判断不同，请结合证据审阅。</Notice> : null}
        <div className="report-footnote"><ShieldCheck size={15} />仅代表本机、本次直连。未读取网页正文、未验证登录或页面渲染，不自动追踪重定向。</div>
      </> : tab === 'evidence' ? <div className="evidence-list">{report.evidence?.length ? report.evidence.map(item => <Evidence item={item} replayed={replayed} key={item.evidence_id} />) : <Empty title="没有取得工具观测">请检查模型连接或重新运行诊断。</Empty>}</div> : tab === 'model' ? <>
        {report.error ? <TextList title="执行错误详情" values={[report.error]} icon={TriangleAlert} /> : null}
        <div className="model-stats"><span>模型请求 <strong>{report.llm_requests ?? 0}</strong></span><span>输入 tokens <strong>{report.input_tokens ?? 0}</strong></span><span>输出 tokens <strong>{report.output_tokens ?? 0}</strong></span><span>校验修正 <strong>{report.validation_errors?.length ?? 0}</strong></span></div>
        <TextList title="输出校验与修正记录" values={report.validation_errors} icon={ShieldCheck} emptyText="本次没有记录校验冲突。" />
        <TextList title="运行说明" values={[...(report.warnings || []), ...(report.narrative_policy ? ['最终摘要使用与类别绑定的程序短句。其他模型文字仅经过有限规则检查，仍需人工核对。'] : [])]} icon={CircleAlert} />
        <details className="detail-block"><summary>模型首次及后续结构化草稿 · {report.drafts?.length || 0} 份</summary><JsonBlock value={report.drafts || []} /></details>
        <details className="detail-block"><summary>实际工具调用 Trace · {report.trace?.length || 0} 次</summary><JsonBlock value={report.trace || []} /></details>
        <details className="detail-block"><summary>本次加载的专业 Skill {report.skill_loaded ? '· 已加载' : '· 未加载'}</summary><pre className="skill-text">{report.skill_text || '该实验组未加载专业 Skill。'}</pre></details>
      </> : <JsonBlock value={report} />}
    </div>
  </section>;
}

export function RecentReports({ reports, onOpen, onAll, limit = 5 }) {
  return <section className="panel recent-reports"><SectionHead title="最近的调查" description="每次运行都留下可复查的记录。">{onAll ? <button className="inline-link" onClick={onAll}>全部报告 <ArrowRight size={14} /></button> : null}</SectionHead>{!reports.length ? <Empty title="第一份调查，从这里开始" icon={FileSearch}>完成一次诊断后，报告会自动出现在这里。</Empty> : <div className="table-scroll"><table className="report-table"><thead><tr><th>调查目标</th><th>结果</th><th>方式</th><th>时间</th><th aria-label="操作" /></tr></thead><tbody>{reports.slice(0, limit).map(row => <tr key={row.path}><td><button className="target-link" onClick={() => onOpen(row.path)}><span className="site-icon"><Globe2 size={16} /></span><span><strong>{row.url.replace(/^https?:\/\//, '').replace(/\/$/, '')}</strong><small>{row.case_id ? `实验 · ${row.case_id}` : row.replayed ? '观测回放' : '网站诊断'}</small></span></button></td><td><Tag tone={tone(row.diagnosis)}><span className="status-dot" />{LABELS[row.diagnosis]}</Tag></td><td><span className="mode-text">{row.engine === 'rules' ? '规则工具测试' : MODES[row.mode]}</span></td><td className="table-date">{date(row.started_at)}</td><td><button className="icon-button" aria-label={`查看 ${row.url} 的报告`} onClick={() => onOpen(row.path)}><ArrowUpRight size={17} /></button></td></tr>)}</tbody></table></div>}</section>;
}
