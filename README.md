# NBA 关注球员实时提醒面板

> **English**: A self-hosted NBA live alert dashboard — get notified only when the players you care about check in, score, assist or turn the ball over. Built with `nba_api` + `FastAPI` + `WebSocket` + `RapidOCR`.

只在**你关心的球员**发生上场 / 得分 / 助攻 / 失误时收到提醒，不必看完全场。

技术栈：`nba_api` + `FastAPI` + `WebSocket` + `RapidOCR`，本地可运行的完整最小实时系统。

![License](https://img.shields.io/badge/license-MIT-blue) ![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![CI](https://github.com/LHL-2006/nba-alert/actions/workflows/ci.yml/badge.svg)

> ⚠️ 本项目为**个人本地工具，非官方产品**，与 NBA、ESPN 及各球队无任何隶属、授权或合作关系；NBA 及相关名称、商标归其各自所有者所有。

---

## 一、架构与关键取舍

```
   直播画面 (m3u8 / 本地视频)              实时比赛数据
          │                                    │
          ▼                                    ▼
   FrameGrabber 抽帧              nba_api (主) ──失败自动降级──> ESPN (兜底)
          │                                    │
          ▼                                    ▼
   RapidOCR 识别球衣号/姓名       play-by-play → 事件分类器
          │                        (score/assist/turnover/sub_in...)
          ▼                                    │
   PresenceTracker 投票去抖                   │
   → ON_COURT / OFF_COURT                    │
          └──────────────┬─────────────────────┘
                         ▼
             AlertEngine（关注球员匹配 / 去重 / 冷却）
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   企业微信/微信    Windows 桌面通知     SMTP 邮件
                         │
                         ▼
        FastAPI  /ws  WebSocket  →  浏览器实时面板
```

**为什么「上场」用画面 OCR，其余用数据？**

| 行为 | 判定方式 | 原因 |
| --- | --- | --- |
| 上场 / 在场 | **画面 OCR**（球衣号 + 姓名 + 转播图文） | 是视觉可见状态；数据层换人事件作为回退与交叉验证 |
| 得分 | 实时逐回合数据 | 需要精确分值与球员归因 |
| 助攻 | 实时逐回合数据 | 规则判定，画面无法知道谁传球 |
| 失误 | 实时逐回合数据 | 规则判定，画面无法知道球权丢失归属 |

转播画面里球员小、遮挡、背身、快速移动，**单帧 OCR 不可靠**，因此实现了滑动窗口投票
（`vote_window` / `vote_threshold`）与离场去抖（`absent_frames`），只在状态**发生翻转**时推送一次。

**为什么有 ESPN 兜底？** `cdn.nba.com` / `stats.nba.com` 在部分网络（含中国大陆）会被
Akamai 返回 403，`nba_api` 的 live 端点依赖该域名。`SourceManager` 启动时会探测，
不通就自动切到 ESPN 公开实时逐回合接口（实测 2026-11-20 比赛日可用，一场 468 条回合）。
换到可访问的网络，`data_source.prefer: nba_api` 即可切回官方源。

---

## 二、快速开始

```bash
cd nba-alert
pip install -r requirements.txt

# 1) 立即验证全链路（不访问网络，回放内置样本，推送只走控制台）
python run.py --demo
# 浏览器打开 http://127.0.0.1:8000

# 2) 真实模式
cp .env.example .env      # 填入密钥（可选）
# 编辑 config.yaml：关注球员、事件类型、推送渠道
python run.py
```

面板会显示：当前比分与节次、关注球员的在场状态灯与 OCR 置信度、实时事件流、
推送记录（含每个通道的成功/失败结果）、视觉模块与数据源状态。

---

## 二·五 桌面应用版（不打开 WorkBuddy 也能用）

> 📦 **不想自己打包？** 到 [Releases](https://github.com/LHL-2006/nba-alert/releases/latest)
> 下载 `NBAAlert-Windows-x64.zip`（约 121 MB，绿色免安装，自包含 Python 运行时）。
> ⚠️ **解压整个文件夹**后双击 `NBAAlert.exe`；`_internal` 必须与 exe 同目录，
> 只单独保存一个 exe 会报 `Failed to load Python DLL ... python313.dll`。

自行从源码打包：

```bash
python build_app.py
```

产物 `dist/NBAAlert/NBAAlert.exe`：**绿色免安装，自包含 Python 运行时与全部依赖**
（含 OCR），把整个 `NBAAlert` 文件夹复制到任意位置，双击 exe 即可：

- 后台内嵌启动 FastAPI / WebSocket 服务，自动打开默认浏览器到实时面板
- 常驻系统托盘：打开面板 / 演示模式 / 重启服务 / 打开应用目录 / 查看日志 / 退出
- 单实例保护，重复双击只会打开已有面板
- `config.yaml`、`.env`、`data/` 位于 exe 同目录，首次运行自动释放，可直接编辑

详见 `应用使用说明.txt`。源码运行方式见上一节。

---

## 三、配置说明（`config.yaml`）

| 配置 | 说明 |
| --- | --- |
| `app.demo_mode` | `true` 时不联网，回放内置样本事件 |
| `app.poll_interval_sec` | 数据轮询间隔，默认 8 秒（公开接口请勿设过低） |
| `app.date` | 指定比赛日 `YYYYMMDD`，留空为今天 |
| `data_source.prefer` | `auto`（推荐）/ `nba_api` / `espn` |
| `watch.players[].name` | 球员英文名（用于数据层匹配） |
| `watch.players[].aliases` | 别名/中文名，供 OCR 文本匹配，如 `["库里","詹姆斯","LBJ"]` |
| `watch.players[].jersey` | 球衣号，供画面 OCR 号码 → 球员映射 |
| `watch.players[].events` | 订阅事件；不填则用 `default_events` |
| `watch.cooldown_sec` | 同球员同类型事件的冷却秒数，`0` 表示每条都推 |
| `vision.stream_url` | 直播流地址（m3u8 / 本地视频 / 摄像头编号） |
| `vision.fps` | 抽帧频率，默认 `0.5`（每 2 秒一帧） |
| `vision.roi` | 裁剪识别区域，如 `[0.0, 0.35, 1.0, 1.0]` 只扫下半屏 |
| `vision.vote_window` / `vote_threshold` | 最近 N 帧内命中 ≥ M 帧判为在场 |
| `vision.absent_frames` | 连续 N 帧未命中才判离场 |
| `notify.channels` | `wecom` / `serverchan` / `desktop` / `email` / `console` |

可用事件类型：`on_court`、`off_court`、`sub_in`、`sub_out`、`score`、`assist`、
`turnover`、`rebound`、`steal`、`block`、`foul`。

### 推送通道

- **企业微信**：建一个群机器人，把 Webhook 填进 `.env` 的 `WECOM_WEBHOOK`。
- **微信（Server酱）**：`SERVERCHAN_KEY` 填了就会自动追加该通道。
- **桌面通知**：Windows 原生气泡，无需额外依赖，开箱即用。
- **邮件**：`SMTP_USER` / `SMTP_PASS` + `notify.email.to` 收件人列表（QQ 邮箱用授权码）。

未配置凭证的通道会自动停用，面板里显示「未配置/停用」，不影响主链路。
可用 `POST /api/test?name=LeBron James` 或面板「测试推送」按钮验证通道。

---

## 四、直播流配置（画面 OCR 上场判定）

聚合类直播站点的首页通常只有导航，直播间流地址由 JS 动态生成、页面中无明文 m3u8。
项目提供两种获取方式：

```bash
# 方式 A：命令行探测页面里明文出现的 m3u8
python tools/probe_stream.py "https://<直播间页面URL>"

# 方式 B：面板「快捷操作」里输入页面 URL 点「探测流地址」
```

若探测不到（混淆或接口动态下发），在浏览器打开直播间 → `F12` → `Network` →
过滤 `.m3u8` → 复制实际请求地址，填入 `config.yaml` 的 `vision.stream_url`，重启服务。

抓帧支持两种后端：`ffmpeg` 管道（优先，若系统装了 ffmpeg）或 `cv2.VideoCapture` 直读。
OCR 用 `RapidOCR`（ONNX，中英文，轻量，无需 GPU / PyTorch / Paddle）。

> ⚠️ **合规提示**：本模块只读取使用者自行配置、且已获授权观看的流地址，
> **不提供、不破解、不绕过任何加密或付费内容**，探测工具仅提取页面里明文可见的地址
> （等价于浏览器 Network 面板）。请确保你对所观看的直播内容拥有合法权限，
> 本系统仅供个人本地分析与提醒使用，不得用于转播、分发或商业用途。
> 项目**不提供、不存储、不转播**任何直播源或比赛音视频内容。
> 数据接口为公开端点，请遵守其服务条款并控制请求频率。

**未配置流地址时**：画面模块自动停用，上场判定回退到数据层换人事件（`sub_in` / `sub_out`），
其余功能照常工作——这是设计好的降级路径，不是故障。

---

## 五、HTTP / WebSocket 接口

| 接口 | 说明 |
| --- | --- |
| `GET /` | 实时面板 |
| `GET /api/status` | 数据源、视觉模块、比赛、在场状态、通道状态 |
| `GET /api/history?limit=100` | 历史事件与推送记录 |
| `POST /api/watch` | 动态增删关注球员，body：`{"name":"...","jersey":"...","action":"add"}` |
| `POST /api/test?name=...` | 手动触发一条测试提醒 |
| `GET /api/probe?url=...` | 探测直播间页面里的 m3u8 |
| `WS /ws` | 推送 `status` / `history` / `event` / `alert` / `presence` 五类消息 |

---

## 六、测试

```bash
python -m unittest discover -s tests -t . -v
```

覆盖：文本分类器（ESPN + NBA CDN 两种格式）、换人/助攻/失误派生事件、
名单解析、规则引擎过滤与别名匹配、去重与冷却、通道结果记录。

---

## 七、常见问题

**Q：启动后没有事件？**
首次轮询会**预热**（把该场已有的全部回合标记为已见但不推送），避免一开服务就刷屏几百条历史。
之后只推新产生的回合。想立刻看效果用 `python run.py --demo`。

**Q：日志里出现 `nba_api 不可用，自动降级 ESPN`？**
正常，表示当前网络访问不了 `cdn.nba.com`。ESPN 源覆盖同样的事件类型，功能不受影响。

**Q：OCR 误判/漏判？**
调 `vision.roi` 缩小到球衣区域、提高 `vision.min_score`、增大 `vote_threshold`，
或降低 `vision.fps` 减少耗时。球衣号码与姓名是**任一命中即算命中**，两者都配可提高召回。

**Q：想接别的推送渠道？**
在 `app/notifiers/` 新增一个继承 `Notifier` 的类，实现 `send()`，
在 `base.py` 的 `build_notifiers()` 注册表加一行即可。

**Q：想扩展事件类型？**
`app/models.py` 的 `EventType` + `app/sources/classifier.py` 加一条规则，
前端 `TYPES` / `COLORS` 补一个映射。

**Q：双击 exe 报 `Failed to load Python DLL ... python313.dll`？**
`_internal` 文件夹没和 exe 放在一起。本应用是 PyInstaller onedir 模式，exe 只是引导程序，
Python 运行时与全部依赖都在 `_internal/` 里。重新下载完整 zip 并**解压整个文件夹**即可，
不要只保存单个 exe；整个 `NBAAlert` 文件夹可以整体移动，但不能拆开。

---

## 八、开源与免责声明

- **许可证**：[MIT](LICENSE)，可自由使用、修改与二次分发。
- **非官方声明**：本项目为个人学习与自用工具，与 NBA、ESPN 及其关联方无任何官方关系；所有队名、球员名与商标归各自所有者所有。
- **数据来源**：仅调用公开实时数据端点，请遵守对应站点的服务条款并控制请求频率（默认 8 秒轮询）。
- **内容合规**：项目不包含、不提供、不破解任何直播源或受版权保护的内容；画面模块仅处理使用者自行配置且已获授权观看的流。
- **免责**：事件判定与 OCR 识别可能存在延迟或误差，本项目仅供观赛提醒，不构成实时数据服务或任何投注依据。

欢迎提交 Issue / PR：新增数据源、推送渠道、事件类型，或改进 OCR 准确率。
