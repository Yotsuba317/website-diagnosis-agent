import { useState } from 'react';
import { ChevronDown, Settings2, RefreshCw, Server, Check, Copy, ShieldCheck, FlaskConical } from 'lucide-react';
import { Button, Notice, PageHead, SectionHead, FormError } from './ui';

export function RunConfig({ value, onChange, health, disabled, advanced = true }) {
  const [showAdvanced, setAdvanced] = useState(false);
  const change = (key, next) => onChange({ ...value, [key]: next, ...(key === 'engine' && next === 'rules' && value.mode === 'baseline' ? { mode: 'skill' } : {}) });
  const modelOptions = [...new Set([value.model, ...(health?.models || [])])].filter(Boolean);
  return <div className="run-config"><div className="config-grid">
    <label>运行引擎<select value={value.engine} onChange={e => change('engine', e.target.value)} disabled={disabled}><option value="ollama">Ollama 大模型</option><option value="rules">规则工具测试 · 无需模型</option></select></label>
    <label>调查模型<select value={value.model} onChange={e => change('model', e.target.value)} disabled={disabled || value.engine === 'rules'}>{modelOptions.map(model => <option key={model}>{model}</option>)}</select></label>
    <label>调查方式<select value={value.mode} onChange={e => change('mode', e.target.value)} disabled={disabled || value.engine === 'rules'}><option value="skill">工具 + 专业 Skill</option><option value="tools">仅工具调查</option><option value="baseline">直接分析相同观测</option></select></label>
  </div>
    {advanced ? <><button type="button" className="advanced-toggle" onClick={() => setAdvanced(!showAdvanced)} aria-expanded={showAdvanced}><Settings2 size={14} />高级选项<ChevronDown size={14} className={showAdvanced ? 'rotate' : ''} /><span>超时 {value.timeout} s · 慢响应阈值 {value.slow_ms} ms</span></button>{showAdvanced ? <div className="advanced-fields"><label>单次探测超时（秒）<input type="number" min="0.1" max="30" step="0.1" required value={value.timeout} onChange={e => change('timeout', e.target.value === '' ? '' : Number(e.target.value))} disabled={disabled} /></label><label>慢响应阈值（毫秒）<input type="number" min="1" max="60000" required value={value.slow_ms} onChange={e => change('slow_ms', e.target.value === '' ? '' : Number(e.target.value))} disabled={disabled} /></label></div> : null}</> : null}
    {value.engine === 'rules' ? <Notice tone="warning">当前为确定性规则工具测试，不调用大模型，结果不代表 Agent 或 Skill 的实验成绩。</Notice> : health && !health.connected ? <Notice tone="warning">Ollama 尚未连接。请在运行设置中检查服务，也可切换到“规则工具测试”先体验。</Notice> : null}
  </div>;
}

export default function Settings({ settings, onSave, health, onCheck, checking, output, onLab, toast }) {
  const [draft, setDraft] = useState(settings);
  const [error, setError] = useState('');
  const update = (key, value) => setDraft(current => ({ ...current, [key]: value }));
  function save(event) {
    event.preventDefault();
    if (!(Number(draft.timeout) > 0 && Number(draft.timeout) <= 30 && Number(draft.slow_ms) >= 1 && Number(draft.slow_ms) <= 60000)) { setError('请检查超时和慢响应阈值的范围。'); return; }
    if (!draft.model.trim()) { setError('请输入有效的模型名称。'); return; }
    try { const host = new URL(draft.host); if (host.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(host.hostname) || host.port === '0' || host.username || host.password || host.search || host.hash || !['', '/'].includes(host.pathname)) throw new Error(); }
    catch { setError('请输入本机 Ollama 地址，例如 http://127.0.0.1:11434'); return; }
    setError(''); onSave({ ...draft, model: draft.model.trim(), host: draft.host.trim(), timeout: Number(draft.timeout), slow_ms: Number(draft.slow_ms) });
  }
  async function copy(text) { try { await navigator.clipboard.writeText(text); toast('命令已复制'); } catch { toast('请手动复制下方命令'); } }
  return <><PageHead title="运行设置" description="让本机工具、模型和你的排查习惯保持一致。" />
    <div className="settings-layout"><form className="panel settings-form" onSubmit={save}><SectionHead icon={Settings2} title="默认调查配置" description="保存后用于下一次新建的任务；正在运行的任务保持原配置。" />
      <label>Ollama 服务地址<div className="input-action"><input value={draft.host} onChange={e => update('host', e.target.value)} required placeholder="http://127.0.0.1:11434" /><Button type="button" variant="secondary" onClick={() => onCheck(draft.host)} loading={checking}>检查连接</Button></div><small>只允许本机 HTTP 服务地址，默认端口为 11434。</small></label>
      <label>默认模型<input list="models" value={draft.model} onChange={e => update('model', e.target.value)} required maxLength={160} /><datalist id="models">{(health?.models || []).map(model => <option key={model}>{model}</option>)}</datalist></label>
      <RunConfig value={draft} onChange={setDraft} health={health} />
      <FormError>{error}</FormError><div className="form-footer"><span>偏好仅保存在此浏览器中</span><Button type="submit"><Check size={16} />保存设置</Button></div>
    </form>
    <div className="settings-aside"><section className="panel environment"><SectionHead icon={Server} title="本机环境" /><dl><div><dt>Ollama</dt><dd className={health?.connected ? 'text-success' : 'text-warning'}>{health?.connected ? '已连接' : '未连接'}</dd></div><div><dt>Python</dt><dd>{health?.python || '检查中'}</dd></div><div><dt>可用模型</dt><dd>{health?.models?.length ?? '—'} 个</dd></div></dl>{health?.connected ? <div className="model-list">{health.models.map(model => <span key={model}>{model}</span>)}</div> : <p className="muted">启动本地 Ollama 后，点击“检查连接”刷新模型列表。</p>}</section>
      <section className="panel connection-help"><h3>首次连接模型？</h3><p>在 PowerShell 中启动 Ollama，并准备默认模型。</p>{['ollama serve', 'ollama pull qwen3.5:0.8b'].map(command => <div className="command" key={command}><code>{command}</code><button type="button" aria-label={`复制 ${command}`} onClick={() => copy(command)}><Copy size={14} /></button></div>)}<button className="inline-link" type="button" onClick={onLab}><FlaskConical size={15} />没有模型？先体验规则工具测试</button></section>
    </div></div>
    <section className="panel storage"><ShieldCheck size={22} /><div><h3>报告保存在你自己的电脑上</h3><p>检测不会修改网络配置。原始观测、模型草稿与校验记录均可在报告中复查。</p><code>{output}</code></div></section>
  </>;
}
