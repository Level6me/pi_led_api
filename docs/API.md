# 🍓 Raspberry Pi LED Control API 详细开发与对接文档 (v2.4)

> **服务地址**: `https://piled.abab.pw` / `http://127.0.0.1:8080`  
> **交互式调试文档 (Swagger UI)**: `https://piled.abab.pw/docs`  
> **OpenAPI 规范 (ReDoc)**: `https://piled.abab.pw/redoc`

---

## 目录
1. [认证与安全体系 (Authentication)](#一认证与安全体系)
2. [系统预设状态接口 (State Presets)](#二系统预设状态接口)
3. [单通道高级调控接口 (Single Channel)](#三单通道高级调控接口)
4. [智能倒计时与渐暗关灯 (Smart Timer)](#四智能倒计时与渐暗关灯)
5. [动效剧场与自定义帧序列 (Pattern Studio)](#五动效剧场与自定义帧序列)
6. [硬件引脚热重映射 (Hardware Config)](#六硬件引脚热重映射)
7. [调用审计与数据导出 (Audit Logs)](#七调用审计与数据导出)
8. [访问令牌管理 (Tokens)](#八访问令牌管理)
9. [WebSocket 实时数据流](#九websocket-实时数据流)

---

## 一、认证与安全体系

本 API 支持以下 3 种认证方式：

| 认证方式 | Header / 请求参数 | 适用场景 |
| :--- | :--- | :--- |
| **设备 API-Key（推荐）** | `X-API-Key: <token>` | iOS 快捷指令、群机器人、自动化脚本 |
| **OAuth2 JWT Token** | `Authorization: Bearer <jwt>` | Web 控制台、管理员会话 |
| **URL Query Token** | `?token=<token>` | 简易 GET 请求、不支持自定义 Header 的客户端 |

---

## 二、系统预设状态接口

### 1. 切换系统预设状态
* **端点**: `POST /api/state`
* **鉴权**: 需提供 Token / JWT
* **请求体**:
  ```json
  {
    "state": "thinking",
    "duration": 300
  }
  ```
* **可选预设状态 (`state`)**:
  * `thinking`：🟡 黄灯常亮（思考中）
  * `breathing`：✨ 黄灯正弦平滑呼吸（任务执行中）
  * `restarting`：⚡ 黄灯闪烁（服务重启中）
  * `success`：🟢 绿灯常亮指定秒数后熄灭（任务成功）
  * `error`：🔴 红灯常亮（系统异常 / 报错 / 强制停止）
  * `startup`：🔄 绿灯连闪 5 次后熄灭（开机自检完成）
  * `off`：⏹️ 熄灭所有通道
* **cURL 示例**:
  ```bash
  curl -X POST https://piled.abab.pw/api/state \
    -H "X-API-Key: ipad_pro_secret_888" \
    -H "Content-Type: application/json" \
    -d '{"state": "thinking", "duration": 300}'
  ```

### 2. 一键熄灭所有指示灯
* **端点**: `POST /api/off`
* **cURL 示例**:
  ```bash
  curl -X POST https://piled.abab.pw/api/off \
    -H "X-API-Key: ipad_pro_secret_888"
  ```

---

## 三、单通道高级调控接口

### 独立/独占控制单灯
* **端点**: `POST /api/led`
* **请求体**:
  ```json
  {
    "color": "green",
    "action": "breath",
    "value": 1.0,
    "frequency": 1.5,
    "exclusive": false
  }
  ```
* **参数说明**:
  * `color` (*string*): `red` | `yellow` | `green`
  * `action` (*string*): `on` (常亮) | `off` (关闭) | `pwm` (调光) | `blink` (闪烁) | `breath` (呼吸)
  * `value` (*float*): `0.0` ~ `1.0`（PWM 亮度值，内置 CIE 1931 / Gamma 2.2 校正）
  * `frequency` (*float*): 闪烁或呼吸频率（Hz）
  * `exclusive` (*bool*): 若为 `true`，则自动熄灭其它通道

---

## 四、智能倒计时与渐暗关灯

### 1. 启动倒计时任务
* **端点**: `POST /api/timer`
* **请求体**:
  ```json
  {
    "color": "green",
    "duration_sec": 60,
    "fade_out_sec": 5
  }
  ```
* **说明**: 指示灯点亮运行 60 秒，在最后 5 秒内以微积分阶梯自动平滑变暗直至熄灭。

### 2. 取消倒计时
* **端点**: `DELETE /api/timer`

---

## 五、动效剧场与自定义帧序列

### 1. 运行动效
* **端点**: `POST /api/pattern`
* **方式 A (按名称运行内置/已保存动效)**:
  ```json
  {
    "name": "police_alert",
    "repeat": 5
  }
  ```
* **方式 B (运行即时自定义帧序列)**:
  ```json
  {
    "name": "my_flow",
    "repeat": 3,
    "frames": [
      {"red": 1.0, "yellow": 0.0, "green": 0.0, "duration": 0.15},
      {"red": 0.0, "yellow": 1.0, "green": 0.0, "duration": 0.15},
      {"red": 0.0, "yellow": 0.0, "green": 1.0, "duration": 0.15}
    ]
  }
  ```

### 2. 保存自定义动效至系统库
* **端点**: `POST /api/patterns`
* **端点 (获取动效库)**: `GET /api/patterns`
* **端点 (删除动效)**: `DELETE /api/patterns/{name}`

---

## 六、硬件引脚热重映射

### 1. 获取硬件配置
* **端点**: `GET /api/hardware/config`

### 2. 在线修改引脚编号与极性
* **端点**: `POST /api/hardware/config`
* **请求体**:
  ```json
  {
    "pins": {
      "red": 22,
      "yellow": 27,
      "green": 17
    },
    "active_high": true,
    "gamma_correction": true,
    "gamma_value": 2.2
  }
  ```

---

## 七、调用审计与数据导出

### 1. 查询调用审计记录
* **端点**: `GET /api/logs?limit=80&device=iPad&status=success`

### 2. 一键导出审计日志文件
* **端点**: `GET /api/logs/export?format=csv` 或 `?format=json`

### 3. 获取图表与硬件统计数据
* **端点**: `GET /api/stats/summary`

---

## 八、访问令牌管理

### 1. 查询令牌列表
* **端点**: `GET /api/tokens`

### 2. 在线生成新设备专属 Token
* **端点**: `POST /api/tokens/create`
* **请求体**:
  ```json
  {
    "device_name": "客厅 iPad Pro",
    "custom_token": null,
    "expires_days": 90
  }
  ```

### 3. 撤销/删除 Token
* **端点**: `DELETE /api/tokens/{token_id}`

---

## 九、WebSocket 实时数据流

* **端点**: `wss://piled.abab.pw/ws/status`
* **连接即推送**: 连接成功后自动推送最新的整机快照与物理引脚状态；每当有新调用或状态变更时实时流式广播。
