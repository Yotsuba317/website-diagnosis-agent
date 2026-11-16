import { useState } from 'react';
import { ArrowRight, BarChart3, Check, Download, GitCompareArrows } from 'lucide-react';
import { activeJob, api, date, MODES, percent, reportUrl } from './api';
import { Button, Empty, FormError, Notice, PageHead, Progress, SectionHead, Tag } from './ui';

function Summary({ report, path }) {
  const prefix = path.slice(0, path.lastIndexOf('/') + 1);
  return <section className="panel evaluation-results"><SectionHead icon={BarChart3} title="对照实验结果" description={`${report.engine === 'rules' ? '规则工具测试' : report.model || '模型未记录'} · 每案例重复 ${report.repeats} 次`}><div className="downloads"><a className="button secondary" href={reportUrl(`${prefix}evaluation.md`, 'md')} download><Download size={15} />实验报告</a><a className="button text-button" href={reportUrl(`${prefix}evaluation.csv`, 'csv')} download>CSV</a></div></SectionHead>
    <Notice tone={report.engine === 'rules' ? 'warning' : 'info'}>{report.engine === 'rules' ? '本次为规则工具测试，不计作 LLM 或 Skill 效果。' : '三组分析相同观测。最终结果可能经过程序校验或候选辅助，请同时审阅首次草稿与原始 Trace。'}</Notice>
    <div className="table-scroll"><table className="comparison-table"><thead><tr><th>实验组</th><th>运行数</th><th>首次正确率</th><th>最终正确率</th><th>任务成功率</th><th>证据覆盖率</th><th>平均用时</th><th>文字辅助</th></tr></thead><tbody>{report.summary.map(row => <tr key={row.mode}><td><strong>{report.engine === 'rules' ? '规则测试' : MODES[row.mode]}</strong></td><td>{row.runs}</td><td>{percent(row.first_draft_accuracy)}</td><td><div className="score-cell"><strong>{percent(row.conclusion_accuracy)}</strong><span><i style={{ width: `${row.conclusion_accuracy * 100}%` }} /></span></div></td><td>{percent(row.task_success_rate)}</td><td>{percent(row.mean_evidence_coverage)}</td><td>{row.mean_elapsed_seconds.toFixed(2)} s</td><td>{row.narrative_repair_runs == null ? '未记录' : `${row.narrative_repair_runs} 次`}</td></tr>)}</tbody></table></div>
    <details className="metric-definitions"><summary>这些指标如何计算？</summary><p>首次正确率：首次可解析草稿类别正确的运行数 / 全部运行数。最终正确率：最终类别正确数 / 全部运行数。任务成功还要求引用决定性证据并提出建议。证据覆盖率只核对必要阶段的证据引用，不全面评价解释质量。</p><p>小型受控案例上的高分不代表真实校园网泛化；程序辅助后的成绩不能代替模型未经帮助的能力。</p></details>
    <details className="evaluation-details"><summary>查看逐次运行结果 · {report.rows.length} 次</summary><div className="table-scroll"><table className="comparison-table"><thead><tr><th>案例</th><th>实验组</th><th>预期 / 最终</th><th>是否正确</th><th>耗时</th><th>执行错误</th></tr></thead><tbody>{report.rows.map((row, index) => <tr key={index}><td>{row.case_id}</td><td>{MODES[row.mode]}</td><td>{row.expected}<br /><span className="muted">{row.predicted}</span></td><td><Tag tone={row.correct ? 'success' : 'danger'}>{row.correct ? '正确' : '不正确'}</Tag></td><td>{row.elapsed_seconds} s</td><td className="error-cell">{row.error || '无'}</td></tr>)}</tbody></table></div></details>
  </section>;
}

export default function Evaluations({ cases, settings, health, job, onRun, onCancel, evaluations, selected, onSelect }) {
  const [chosenCases, setCases] = useState(cases.map(item => item.id));
  const [modes, setModes] = useState(['baseline', 'tools', 'skill']);
  const [model, setModel] = useState(settings.model);
  const [engine, setEngine] = useState('ollama');
  const [repeats, setRepeats] = useState(1);
  const [error, setError] = useState('');
  const busy = activeJob(job);
  const toggle = (list, value) => list.includes(value) ? list.filter(item => item !== value) : [...list, value];
  async function submit(event) { event.preventDefault(); setError(''); try { await onRun({ ...settings, kind: 'evaluate', engine, mode: 'skill', model, cases: chosenCases, modes, repeats: Number(repeats) }); } catch (error) { setError(error.message); } }
  const modelOptions = [...new Set([model, ...(health?.models || [])])];
  return <><PageHead title="对照评测" description="同一模型、同一份观测，比较不同调查方式。" />
    <div className="evaluation-layout"><form className="panel evaluation-form" onSubmit={submit}><SectionHead icon={GitCompareArrows} title="新建 A / B / C 实验" description="真实观测先采集一次，再回放给各组，避免故障状态变化。" />
      <fieldset><legend>选择案例 <button type="button" onClick={() => setCases(chosenCases.length === cases.length ? [] : cases.map(item => item.id))}>{chosenCases.length === cases.length ? '取消全选' : '全选'}</button></legend><div className="checkbox-grid">{cases.map(item => <label key={item.id}><input type="checkbox" checked={chosenCases.includes(item.id)} onChange={() => setCases(toggle(chosenCases, item.id))} disabled={busy} /><span>{item.title}</span></label>)}</div></fieldset>
      <fieldset><legend>实验组</legend><div className="mode-options">{Object.entries(MODES).map(([value, label]) => <label key={value} className={modes.includes(value) ? 'chosen' : ''}><input type="checkbox" checked={modes.includes(value)} onChange={() => setModes(toggle(modes, value))} disabled={busy || engine === 'rules'} /><div><strong>{label}</strong><small>{value === 'baseline' ? '直接读取相同原始观测' : value === 'tools' ? '模型调用工具获取观测' : '工具调查 + 专业排障 Skill'}</small></div></label>)}</div></fieldset>
      <div className="config-grid"><label>运行引擎<select value={engine} onChange={e => setEngine(e.target.value)} disabled={busy}><option value="ollama">Ollama 大模型</option><option value="rules">仅规则工具测试</option></select></label><label>实验模型<select value={model} onChange={e => setModel(e.target.value)} disabled={busy || engine === 'rules'}>{modelOptions.map(value => <option key={value}>{value}</option>)}</select></label><label>重复次数<input type="number" min="1" max="5" required value={repeats} onChange={e => setRepeats(e.target.value)} disabled={busy} /></label></div>
      {engine === 'rules' ? <Notice tone="warning">规则测试只运行一组工具链，不执行 A/B/C 模型对照，也不证明 Skill 效果。</Notice> : health && !health.connected ? <Notice tone="warning">Ollama 尚未连接，请先在运行设置中检查服务，或切换到规则工具测试。</Notice> : null}<FormError>{error}</FormError><div className="form-footer"><span>共 {chosenCases.length * (engine === 'rules' ? 1 : modes.length) * (Number(repeats) || 0)} 次调查 · 串行执行</span><Button type="submit" disabled={busy || !chosenCases.length || (engine === 'ollama' && !modes.length)} loading={busy}>开始评测 <ArrowRight size={16} /></Button></div>
    </form><aside className="evaluation-guide"><h3>看清提升，也看清边界。</h3><p>最终分类正确，不等于解释和建议完全可靠。首次草稿、证据引用与程序辅助记录同样值得检查。</p><ol><li><span>A</span><div><strong>直接分析</strong><p>不提供工具，直接给出同一份完整观测。</p></div></li><li><span>B</span><div><strong>工具调查</strong><p>由模型选择工具，按需取得观测。</p></div></li><li><span>C</span><div><strong>工具 + Skill</strong><p>额外加载专业调查步骤与判断边界。</p></div></li></ol></aside></div>
    {job?.options.kind === 'evaluate' ? <Progress job={job} onCancel={onCancel} /> : null}
    <section className="evaluation-history"><div className="history-picker"><h2>已保存的实验</h2><select aria-label="选择已保存的实验" value={selected?.path || ''} onChange={e => onSelect(e.target.value)}><option value="">选择一份实验结果</option>{evaluations.map(item => <option value={item.path} key={item.path}>{item.path.replace('/summary.json', '')} · {item.engine === 'rules' ? '规则测试' : item.model || '模型未记录'}</option>)}</select></div>{selected?.report ? <Summary report={selected.report} path={selected.path} /> : <section className="panel"><Empty title="用数据比较调查方式" icon={BarChart3}>运行新的实验，或选择项目中已有的实验结果进行查看。</Empty></section>}</section>
  </>;
}
