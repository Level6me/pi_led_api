# 🍓 Raspberry Pi LED Control API (v2.4 - Clean Edition)

> 基于 **FastAPI + AsyncIO** 构建的高性能、多通道、集成 **Apple Abit 悬浮 Dock 栏**、**拟真水晶透镜面板**、**CIE 1931 / Gamma 2.2 视觉平滑呼吸**、**智能倒计时渐暗关灯**、**自定义动效剧场 (Pattern Studio)**、**硬件引脚热重映射**、**审计日志 CSV/JSON 导出** 与 **动态 Token 管理** 的树莓派指示灯中央控制网关服务。

---

## 🌟 核心功能特性

1. **🌈 CIE 1931 / Gamma 2.2 视觉亮度校正 & 自然正弦呼吸曲线**：
   - 彻底告别生硬线性的 PWM 调节，引入幂律人眼感知校正，使暗部渐变更细腻、亮部层次更分明。
   - 任务执行状态采用连续平滑正弦波呼吸，柔和如苹果呼吸灯。
2. **🖱️ 拟真面板直接触控交互 (Direct Bulb Touch/Click)**：
   * 在 Web 面板上直接轻触红/黄/绿灯珠，即可 **0ms 零延迟乐观切换** 开关状态。
3. **⏱️ 智能倒计时 & 渐暗关灯引擎 (Smart Timers & Fade-Out)**：
   * 支持指定通道运行倒计时（1分钟、5分钟、25分钟番茄钟等），在倒计时结束前自动平滑减小亮度渐暗至熄灭。
   * Web 端实时显示倒计时进度条与剩余时间。
4. **🎭 自定义动效剧场 (Custom Patterns Studio & Store)**：
   * 支持在线添加多帧动画（配置每帧红黄绿亮度与持续时间），持久化存储至 `data/patterns.json`，一键运行。
5. **🎛️ 硬件引脚热重映射与电平极性配置 (Hardware Pin Mapping)**：
   * 支持在 Web 界面随时修改各通道 BCM GPIO 编号、极性（高电平有效/低电平有效）与 Gamma 开关，配置保存在 `data/hardware.json`，免改代码热生效。
6. **📥 审计调用日志一键导出 (CSV / JSON Export)**：
   * 支持从 Web 控制台或 API 一键将历史调用记录导出下载为 `.csv` 或 `.json` 文件。
7. **🛡️ 纯内存本地极速 OAuth2 JWT 鉴权 (<0.05ms)**：
   * 极速本地优先验签，支持密码登录与多设备专属动态 Token。

---

## 🛠️ API 接口清单

| 接口 | 方法 | 鉴权要求 | 说明 |
| :--- | :--- | :--- | :--- |
| `/` | `GET` | 无 | Apple Abit 风格现代 Web 控制台 (带悬浮 Dock 与拟真透镜) |
| `/docs` | `GET` | 无 | Swagger UI 交互式在线调试文档 |
| `/api/status` | `GET` | 无 | 获取当前整机、各通道、硬件引脚及倒计时状态快照 |
| `/api/state` | `POST` | 需 Token | 切换系统统一预设状态 (thinking, breathing, success, error, off) |
| `/api/led` | `POST` | 需 Token | 独立/独占控制单灯通道 (支持 on/off/pwm/blink/breath) |
| `/api/off` | `POST` | 需 Token | 一键熄灭所有通道 |
| `/api/timer` | `POST` | 需 Token | 启动智能倒计时 (支持设置结束前平滑渐暗秒数) |
| `/api/timer` | `DELETE` | 需 Token | 提前取消正在运行的倒计时 |
| `/api/patterns` | `GET` | 无 | 获取所有内置与自定义动效列表 |
| `/api/patterns` | `POST` | 需 Token | 保存新的自定义动效帧序列 |
| `/api/patterns/{name}` | `DELETE` | 需 Token | 删除指定的自定义动效 |
| `/api/pattern` | `POST` | 需 Token | 运行指定名称或自定义帧的动效 |
| `/api/hardware/config` | `GET` | 无 | 获取当前硬件引脚及极性配置 |
| `/api/hardware/config` | `POST` | 需 Token | 动态修改引脚编号与极性并热重载 |
| `/api/logs` | `GET` | 无 | 查询调用审计记录 (支持 device / status 过滤) |
| `/api/logs/export` | `GET` | 无 | 导出下载审计日志 (`?format=csv` 或 `?format=json`) |
| `/api/tokens` | `GET` | 无 | 查询所有已颁发与配置的 Token 列表 |
| `/api/tokens/create` | `POST` | 需 Token | 在线生成设备专属 API 访问令牌 |
| `/api/tokens/{id}` | `DELETE` | 需 Token | 撤销并删除指定的动态 Token |
| `/api/oauth/token` | `POST` | 无 | 密码或设备 Token 换取 JWT 访问令牌 |
| `/ws/status` | `WebSocket` | 无 | 实时状态与审计日志广播长连接 |
