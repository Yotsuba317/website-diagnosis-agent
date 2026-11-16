---
name: website-investigation
description: Evidence-based DNS, TCP, TLS and HTTP investigation for network engineers.
---

# 网站访问异常调查 Skill

适用：网络工程师调查一个明确网址的访问失败或响应等待偏长。

## 调查步骤

1. 将报障者的推测当作待验证线索。先检查目标适用的候选假设，再用实测证据更新判断。IP 输入不验证域名解析，HTTP 输入不做 TLS 检查。
2. 先调用 check_dns。失败时记录 DNS 阶段证据；不继续调用依赖 DNS 的工具。
3. DNS 成功后调用 check_tcp。失败时定位到 TCP 连接阶段；无需继续 HTTP。
4. TCP 成功后调用 check_http，检查 TLS、HTTP 状态和 response_wait_ms。
5. 将结果与候选假设核对。把有证据反驳的原因写入 rejected_hypotheses；尚不能排除的原因写入 uncertainties，两者不能混用。没有可排除项时允许 rejected_hypotheses 为空。
6. 每项关键结论引用真实 evidence_ids，不创建工具没有返回的测量值。
7. 建议应指出下一项检查或恢复后复测方式；不执行网络配置变更。

## 判断与专业边界

- DNS 失败支持解析阶段异常；不等于 DNS 服务器全面宕机。
- TCP 拒绝或超时支持连接阶段失败；仅凭此不能确定是防火墙、服务监听还是路径问题。
- TCP 成功反驳“该端口完全不可达”；随后发生 TLS 失败应归入 tls_failure。
- HTTP 400–599 为 http_error，说明已获得 HTTP 响应。现场若推测链路拥塞，检查 slow 是否为 false，以及 TCP 是否成功；仅据本次观测修正对当前请求的判断。
- 2xx 且 response_wait_ms 达到工具返回的 slow_threshold_ms，为 slow_response。
- response_wait_ms 包含网络与服务响应等待，不是纯服务端处理时间；不能单凭它认定拥塞或带宽不足。
- 2xx 且无慢响应，只能说明本次基础请求正常；未验证页面渲染、登录和业务逻辑。
- 3xx 且未追踪目标、工具不可用、关键数据缺失或矛盾，归为 insufficient_evidence。
- 缺少 HTTP 观测时，不排除 HTTP 错误、慢响应或尚未检查的 TLS 故障。缺少观测是调查缺口，不是目标服务故障的证据。
- ip_literal=true 表示输入为 IP，未验证域名解析服务正常。
- 诊断仅代表运行机器、探测时刻和直连路径。未使用代理，不能代表全部校园网用户。
- scheme=http 且 tls_checked=false 表示没有进行 TLS，不把 tls_ms=0 解释为 TLS 成功，也不将 HTTP 问题归因于证书。
- 没有执行的 DNS/TLS 检查属于未验证或不适用，不能写成已经排除了 DNS/TLS 故障。
- source=synthetic_fixture 表示模拟证据；source=live_probe 表示实际探测。不得混称。

## 输出

diagnosis 只能是 normal、dns_failure、tcp_failure、tls_failure、http_error、slow_response、insufficient_evidence。
输出 summary、evidence_ids、supported_hypotheses、rejected_hypotheses、uncertainties、recommendations。
summary 必须逐字采用程序在最终阶段提供的 diagnosis 对应摘要短句，不追加解释。耗时数值及大小关系全部由程序展示；其他文字字段也不重复耗时数值或进行数值比较。
supported_hypotheses 只写已被观测支持的事实。slow=false 时不能声称响应偏慢、耗时超过阈值；TLS 只有耗时读数而没有配置阈值，不能据此声称 TLS 握手偏慢。
建议优先核查与已发现异常阶段直接相关的配置或日志，最多给出三项，不提出无证据的具体设备故障。
证据不足时先补采缺失检查、确认观测采集是否成功并复测；不得仅因观测缺失建议重启、重新部署或更改网络配置。
当前工具没有服务端日志或进程状态证据，不建议重启、重新部署或关闭安全检查。HTTP 已获得响应时，优先围绕已观测阶段排查，不建议修复证书或增大超时时间。
证据不足时明确承认不确定；概率数值没有校准，禁止自行生成“置信度百分比”。
