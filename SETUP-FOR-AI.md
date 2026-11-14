# 给 AI 的施工文档：把「空间小助手」配到能自己发空间、自己换签名

> 读者是**接手配置的 AI**。使用者会把这份文档（和 `README.md`）一起给你，然后说一句：
>
> 「请帮我配置好 AstrBot 里的【空间小助手】插件，并验证是否可用。」
>
> 照做完，应该达到：**她自己判断要不要发 QQ 空间、要不要换签名；能带表情包（GIF 原样发动图）；
> 能删说说、能改资料；发说说会避开每天那条「今天的总结」，不会撞车。**
>
> 文档里的数值都是实测跑通的，不是猜的。**第 4 节是必做项**——漏了会「说说永远发不出去图」。

---

## 0. 开工前必须问使用者（别自己决定）

按顺序问，问完再动配置：

1. **每天自动发说说**（QQ空间插件那条「今天的总结」）要不要开？——**默认开**。
   要主动说清楚三件事：
   - 默认 **23:00** 自动发；
   - 时间**可以改**（`daily_post_time`），改完 QQ空间那边的排期会一起改；
   - **那个点电脑没开、机器人不在线，当天就不发了，也不会补发**（补发的总结里说「今天」其实在说昨天，更怪）。
2. **自动改签名**要不要开？——**默认开**（平时十几天一次，遇到大事一天左右）。
3. **自动发说说**（她自己有情绪/有事的即时说说）要不要开？——**默认开**。
4. **发说说要不要配表情包**？——**默认关，必须他明确同意才开**。要主动说明来源：

   > 配图来自「表情包管理器」(`meme_manager`) 的图包，它会读那个插件里**所有**表情包的图片，
   > 按 **75%（高概率）** 给说说配一张；**每天那条总结也会一起配图**；
   > 两边共用同一个概率，想调就改 `post_sticker_prob`。
   > **GIF 动图会原样发**（QQ 空间保动画），其它格式转静态 JPEG。
   > 插件地址：https://github.com/anka-afk/astrbot_plugin_meme_manager
   > 不同意就保持 `post_sticker_enabled: false`，其它功能不受影响。

5. 顺带确认：每天那条总结要不要跟本插件的「即时说说」并存（两者各算冷却）？
   并存就行——本插件会**自动避开**那个时间点（攒着的说说避开前后 1.5 小时，撞了就重新抽时间）。
   不想要两条，就把 QQ空间 的 `trigger.publish_cron` 关掉。

**配之前还要主动告知使用者两件事（评审要求「用户知情」）：**

- 本插件会**只读**其它插件（陪伴/自我学习/记忆）`plugin_data` 里的状态文件（白名单，不写不改）；
  `state_read_all_files` 默认关，别打开。
- `daily_post_sync_qzone`（默认开）会把每天总结的时间写回 QQ空间 的 `publish_cron`；
  不同意就把它设成 `false`，本插件就只读对方时间、不写配置。

**配完必须回报**：三个开关的状态、配图开没开/概率多少、判断间隔、每天总结的时间。
模板见第 8 节。

---

## 1. 前置（就这些，不用装别的）

| 插件 | 仓库 | 本机实测版本 |
| --- | --- | --- |
| QQ空间 `astrbot_plugin_qzone`（必需） | https://github.com/Zhalslar/astrbot_plugin_qzone | v3.2.0 |
| QQ资料管理 `astrbot_plugin_qqprofile`（必需） | https://github.com/Zhalslar/astrbot_plugin_qqprofile | v1.1.6 |
| 表情包管理器 `meme_manager`（可选，配图才要） | https://github.com/anka-afk/astrbot_plugin_meme_manager | — |
| 我会永远陪着你 `astrbot_plugin_private_companion`（**强烈推荐**） | https://github.com/menglimi/astrbot_plugin_private_companion | 6.5.x / 7.x 都能读 |

要求：

1. 平台是 **aiocqhttp（OneBot v11）**——发空间、改资料都靠它。
2. **QQ空间必须先能用**：能取到 Cookie、能看能发（它自带的「看说说 / 发说说」命令能跑通）。
3. 两个必需插件都**启用**。看日志（搜插件名）确认：
   - `Loading plugin astrbot_plugin_qzone ...` 且后面有 `[AutoPublish]` 的排期日志；
   - `Loading plugin astrbot_plugin_qqprofile ...`；
   - 如果出现 `Plugin xxx is disabled.`，说明它在停用名单里（`data/data_v4.db` → `preferences` 表 →
     `inactivated_plugins`）：要么在 WebUI 里启用，要么把它从那个 JSON 数组里删掉再重启。
4. 不装 `private_companion` 也能跑，但判断「要不要发」只能靠聊天记录猜，会笨一些。

---

## 2. 装本插件

```
<AstrBot>/data/plugins/astrbot_plugin_qzone_kit/
├── main.py
├── metadata.yaml
├── _conf_schema.json
├── README.md
├── SETUP-FOR-AI.md   ← 本文档
└── logo.png
```

放好后**完整重启 AstrBot**（不是面板里的「重载插件」——重载不会重新读配置和代码）。日志里应该有：

```
Loading plugin astrbot_plugin_qzone_kit ...
Added llm tool: qzone_delete_feeds
Added llm tool: qq_profile_update
Added llm tool: qzone_post_summary
Added llm tool: qq_signature_maybe_change
Added llm tool: qzone_post_on_demand
Added llm tool: qzone_mood_post
[QzoneKit] 已启动：自动签名=True（平时 13~32 天 / 重要 22~29.2 小时）、自动说说=True（平时 2~3.6 天 / 重要 22~29.2 小时）、判断间隔≈45 分钟（间隔 ±35% 浮动）
[QzoneKit] 每天 23:00 那条总结：攒着的那批避开前后 1.5 小时（撞了就重抽）；现在就发的只避 15 分钟（撞上挪 30 分钟）
[QzoneKit] 真发模式；表情包=True；一次性强制发=False
```

**六个工具缺一个**，就是插件没加载成功：看 traceback，多半是 `main.py` 语法错或 `_conf_schema.json` 不是合法 JSON。
（`qzone_delete_feeds` / `qq_profile_update` 是删说说、改资料；`qzone_post_summary` 立刻发今天的总结；
`qzone_post_on_demand` 按类型发（周记/聊天/视频/日记/心情）；`qq_signature_maybe_change` / `qzone_mood_post`
是她自己想换签名、想发说说时调的。）

---

## 3. 配置

文件：`<AstrBot>/data/config/astrbot_plugin_qzone_kit_config.json`
（第一次启动 AstrBot 会按 `_conf_schema.json` 自动生成，然后把下面这套覆盖进去）

### 3.1 直接可用的推荐配置

```json
{
  "owner_uids": "",
  "daily_post_enabled": true,
  "daily_post_time": "23:00",
  "daily_post_sync_qzone": true,
  "auto_signature_enabled": true,
  "signature_normal_min_days": 13,
  "signature_normal_max_days": 32,
  "signature_critical_min_hours": 22,
  "signature_critical_max_hours": 29.2,
  "auto_post_enabled": true,
  "post_normal_min_days": 2,
  "post_normal_max_days": 3.6,
  "post_critical_min_hours": 22,
  "post_critical_max_hours": 29.2,
  "post_max_fragments": 5,
  "post_select_threshold": 4,
  "post_publish_min": 3,
  "post_publish_max": 5,
  "post_publish_hard_max": 6,
  "post_fallback_days": 3,
  "post_avoid_window_hours": 1.5,
  "post_instant_guard_minutes": 15,
  "post_instant_push_minutes": 30,
  "post_max_age_days": 5,
  "post_boot_wait_minutes": 3,
  "post_boot_extra_min_minutes": 2,
  "post_boot_extra_max_minutes": 60,
  "judge_interval_minutes": 45,
  "judge_interval_jitter": 0.35,
  "recent_message_limit": 40,
  "judge_only_on_new": false,
  "judge_provider_id": "",
  "post_sticker_enabled": false,
  "post_sticker_prob": 0.75,
  "post_sticker_keep_gif": true,
  "read_plugin_state": true,
  "state_source": "auto",
  "state_source_plugins": "",
  "state_read_all_files": false,
  "dry_run": false,
  "test_force_post_once": false
}
```

### 3.2 每个键干什么

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `owner_uids` | 空 | 谁能用这几个工具。多个用英文逗号分隔；留空 = 不限制（管理员始终可用） |
| `daily_post_enabled` | true | 每天自动发说说（QQ空间插件那条总结）；关掉会 `terminate()` 掉它的 AutoPublish |
| `daily_post_time` | `23:00` | 总结几点发。改它会同步改 QQ空间 的 `publish_cron`；清空 = 每次现读 `publish_cron` |
| `daily_post_sync_qzone` | true | 允不允许本插件改 QQ空间 的配置/排期。关掉 = 只读，不写别人配置 |
| `auto_signature_enabled` | true | 自动改签名 |
| `signature_normal_min_days` / `_max_days` | 13 / 32 | 平时改签名的区间（天），每次随机 |
| `signature_critical_min_hours` / `_max_hours` | 22 / 29.2 | 非常重要时的区间（小时） |
| `auto_post_enabled` | true | 自动发说说总开关 |
| `post_normal_min_days` / `_max_days` | 2 / 3.6 | 平时说说冷却区间（天） |
| `post_critical_min_hours` / `_max_hours` | 22 / 29.2 | 非常重要时的区间（小时） |
| `post_max_fragments` | 5 | 冷却里最多攒几段 |
| `post_select_threshold` | 4 | 攒到几条以上才筛选（4 = 大于三条才挑） |
| `post_publish_min` / `post_publish_max` / `post_publish_hard_max` | 3 / 5 / 6 | 筛选后发几条：常规 3~5，同分放宽到 6 |
| `post_fallback_days` | 3 | 多少天没发就要求她这轮必须发一条（0 = 每轮都要求） |
| `post_avoid_window_hours` | 1.5 | 每天总结前后各多少小时内不落点（攒着的那批） |
| `post_instant_guard_minutes` | 15 | 「现在就发」只避开总结前后这么多分钟 |
| `post_instant_push_minutes` | 30 | 立刻想发却贴着总结时，往后挪多少分钟 |
| `post_max_age_days` | 5 | 碎片最多留几天；超了不发，全过期就当已发过、进下一轮冷却 |
| `post_boot_wait_minutes` / `post_boot_extra_min_minutes` / `_max_minutes` | 3 / 2 / 60 | 开机后先等 3 分钟，再随机 2~60 分钟才补发 |
| `judge_interval_minutes` | 45 | 多久判断一次（试的时候可以填 2~3） |
| `judge_interval_jitter` | 0.35 | 间隔浮动比例（45 分钟约 29~61 分钟随机） |
| `recent_message_limit` | 40 | 判断时回看多少条消息 |
| `judge_provider_id` | 空 | 判断用哪个模型（空 = 当前会话模型） |
| `post_sticker_enabled` | false | 配图开关。**要使用者同意才开** |
| `post_sticker_prob` | 0.75 | 多少比例的说说带图（0~1） |
| `post_sticker_keep_gif` | true | GIF 动图原样发（保动画）；关掉就一律转静态 JPEG |
| `post_ai_image_enabled` | true | 现画配图：说说可以把画面描述交给「豆包画画」插件现画一张，画好再带图发。没装豆包画画就自动跳过 |
| `post_ai_image_prob` | 0.7 | **自动**发说说时，她说了想配画也只有这个概率真画；她当场点名的不受限 |
| `post_ai_image_timeout_seconds` | 200 | 等豆包出图的上限，超时就不配图、发纯文字 |
| `read_plugin_state` | true | 判断时读人格和其它插件的状态（只读） |
| `state_source` | auto | 陪伴插件读哪个版本：auto / v1(6.x) / v2(7.x) |
| `state_source_plugins` | 空 | 去哪些插件的 plugin_data 找状态（默认三个） |
| `state_read_all_files` | false | 默认只读白名单文件；**别开**，开了会扫对方所有 json/db |
| `dry_run` | false | 试运行：只判断、只写日志，不动真格 |
| `test_force_post_once` | false | 一次性测试开关：下一轮强制改签名 + 带图发一条。**平时必须 false** |

> ⚠️ **AstrBot 会把 schema 里没有的配置键直接删掉**（日志 `Config key removed`）。
> 要给插件加新配置，**必须同时写进 `_conf_schema.json`**，否则代码永远读到默认值。

---

## 4. 必做补丁：让「带图说说」真的能发（不改就会 0 张图）

> ⚠️ **这一节改的是别人的插件**（`astrbot_plugin_qzone`），不是本插件的文件。
> 动手之前务必：① 先确认对方版本——下面的改法只对特定版本的 `utils.py` 有效；
> ② 把原文件复制一份 `utils.py.bak` 再改；③ 改完发一条带图说说验证。
> 对方插件一升级就会覆盖这个补丁，升级后要重打。
> **拿不准就别改**：没有图只是难看，改坏了是整条说说发不出去。

**症状**：说说发出去了但没图；日志里

```
[QzoneKit] 带图发布失败（发布说说失败：{}），退回纯文字再发一次
[诊断] 规范化后 0 张图，大小=[] 字节
[诊断] 带图发布：ok=False code=-10061 data='{}'
```

**根因**：QQ空间插件的 `core/qzone/utils.py` 里 `download_file()` 用 `urlparse` 判断「本地路径还是 URL」。
Windows 盘符路径 `D:\xxx.jpg` 会被解析成 **scheme="d"**，于是走到「不支持的协议」分支 → 返回 None →
0 张图 → 发布时 `pic_bo` 为空 → QQ 返回 `code=-10061`。

**先看有没有打过补丁**：打开 `<AstrBot>/data/plugins/astrbot_plugin_qzone/core/qzone/utils.py`，
搜 `PATCH-BY-POPAO` 或「先当本地文件试」。有就不用动；没有就改：

```python
async def download_file(source: str) -> bytes | None:
    source = source.strip()
    if not source:
        return None

    # 先当本地文件试：Windows 盘符路径会被 urlparse 误判成协议，导致永远 0 张图
    try:
        _local = Path(source)
        if _local.is_file():
            return await asyncio.to_thread(_local.read_bytes)
    except OSError:
        pass

    parsed = urlparse(source)
    ...
```

（`Path` / `asyncio` 那个文件里本来就 import 过了。）改完**完整重启 AstrBot**。

> 不要试图给 `publish_post(images=[bytes])` 传 bytes：`Post` 模型只收 `list[str]`，
> 会报 `1 validation error for Post`。只能传路径，所以这个补丁绕不过去。

---

## 5. 验证（照顺序做，每步有判定）

### 5.1 工具在不在（30 秒）

日志里数 `Added llm tool:`，应当是这六个：
`qzone_delete_feeds`、`qq_profile_update`、`qzone_post_summary`、`qzone_post_on_demand`、
`qq_signature_maybe_change`、`qzone_mood_post`。

### 5.2 判断循环真的在跑（3 分钟）

```json
{
  "dry_run": true,
  "judge_interval_minutes": 2
}
```

重启，等 3 分钟，日志应出现：

```
[QzoneKit] 本轮判断：签名=不动｜说说=不发｜配图=''
[QzoneKit][试运行] 本来要发说说（…）→ …
```

- 有「本轮判断」这行 ⇒ 抓消息 → 喂模型 → 解析 JSON 全通。
- `判断没给出可用的 JSON` ⇒ 模型没按格式回；把原文前 200 字看一眼再调提示词。
- `判断这一轮出错` ⇒ 可能是状态读取或模型调用异常，看 traceback。

### 5.3 端到端真发（10 分钟内，会真的发一条）

生产环境不敢乱发，用这个开关：

```json
{
  "dry_run": false,
  "test_force_post_once": true,
  "judge_interval_minutes": 2,
  "post_sticker_enabled": true,
  "post_sticker_prob": 1.0
}
```

重启，等 3~4 分钟。成功日志（一条都不能少）：

```
[QzoneKit][测试] 忽略判断结果：强制改签名 + 强制发一条带图的说说
[QzoneKit] 签名已改：…（critical，测试强制改）
[QzoneKit][测试] 强制发说说，配图分类=happy
[QzoneKit] 说说已发（1xx 字）：…
```

判定：
1. QQ 资料页的签名变了；
2. QQ 空间多了一条**带图**的说说（有 GIF 的话应该是动图）；
3. `data/plugin_data/astrbot_plugin_qzone/posts_*.db` 最新一行 `images` 不是 `[]`。

**测完必须恢复**：`test_force_post_once: false`、`judge_interval_minutes: 45`、`dry_run: false`、
`post_sticker_prob` 改回使用者要的值，然后让使用者**把那条测试说说删掉**（或你自己调 `qzone_delete_feeds` 删第 1 条）。

### 5.4 删说说 / 改资料（各 1 分钟）

让使用者对机器人说（需是管理员或 `owner_uids` 里的人）：

- 「删第 1 条说说」→ 调 `qzone_delete_feeds`，删掉最新那条；
- 「昵称改成 XXX」→ 调 `qq_profile_update`，QQ 资料页确认变了；
- 「状态换成摸鱼中」→ 同理。

### 5.5 每天总结的时间对没对上（看日志，不用真发）

重启后搜 `[AutoPublish] 基准时间`：应当是 `HH:MM` 对应 `daily_post_time`。
再搜 `[QzoneKit] 每天总结的时间：` 确认本插件读到的也是同一个点。

### 5.6 时间窗行为（可选）

本插件的规则（看日志就能确认，不用改系统时间）：

- 攒着的那批：抽到点时间如果落在总结前后 1.5 小时里，会**重新抽**（日志 `抽到的到点时间 … 重新抽`）；
- 「现在就发」：只避开总结前后 15 分钟，撞上就把这次挪 30 分钟（日志 `现在贴着每天 … 那条总结，先不发：挪到 …`）。

---

## 6. 排查表

| 症状 | 原因 | 修法 |
| --- | --- | --- |
| 日志 `Plugin astrbot_plugin_qzone_kit is disabled.` | 在停用名单里 | 从 `inactivated_plugins` 删掉再重启 |
| 六个工具没注册全 | 插件加载报错 | 看 traceback；多半是 `main.py` 语法或 `_conf_schema.json` 不是合法 JSON |
| 永远不会发说说 | 判断循环每轮异常 | 搜 `判断这一轮出错`；旧版是 `KeyError('"signature"')` |
| 改了配置不生效 | AstrBot 删了 schema 外的键 | 把键写进 `_conf_schema.json` |
| 说说发了但没图 | 见第 4 节 | 打 `download_file` 补丁 |
| `1 validation error for Post` | 给 `images` 传了 bytes | 传字符串路径 |
| 说说不发、日志只有「攒着」 | 冷却没过（正常） | 看 `state.json` 的 `pending_due`；想立刻验证走 5.3 |
| 签名一直不动 | 平时区间是 13~32 天 | 正常；想验证用 5.3 |
| 改头像没反应 | 没给图 | 先发一张图或给图片链接，工具会从消息里取 |
| 每天总结没发 | 那个点没开机/不在线 | **正常**：当天不补发 |
| 报 `get_cookies 未返回可用 Cookie` | QQ空间 没登录/掉线 | 先把 QQ空间 插件调通 |

---

## 7.4 动图表情包为什么一闪一闪（已修）

原因不是压缩坏了，是**帧率太高 + 文件太大**：图包里那种表情包是 **20ms/帧（≈50fps）、99 帧、3.9MB**，
手机上 QQ 空间会自己降帧、重编码，看起来就一卡一卡地闪。

现在发之前会先规整：

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `post_sticker_max_frames` | 40 | 最多留几帧（99 → 33） |
| `post_sticker_frame_ms` | 100 | 每帧 100ms = 10fps |
| `post_sticker_max_px` | 360 | 最长边像素 |
| `post_sticker_colors` | 128 | 调色板颜色数 |
| `post_sticker_flatten` | true | 透明背景铺白，防闪白 |

实测：3.9MB/99 帧 → **1.07MB / 33 帧 / 360px / 10fps**。想更小就把 `post_sticker_max_px` 调到 300。

## 7.5 说说排版（2~3 段）

她的说说默认会**自动分成 2~3 段**，不会再是一大块：

- 生成时提示词就要求「分 2~3 段，每段 30~150 字，段与段空一行，别堆比喻和生僻词」；
- 生成后还有一道后处理：如果还是一整块，就按句子平均分成 2~3 段；如果模型已经分好段，就保留她的分段。

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `post_format` | true | 关掉就原样发，不排版 |
| `post_paragraphs` | 3 | 分几段（最多 5），段与段之间空一行 |
| `post_paragraph_chars` | 100 | 每段大致多少字（30~150），用来决定分几段 |
| `post_max_chars` | 180 | 说说总长上限 |
| `post_style_extra` | 空 | 末尾固定加一行（比如小尾巴） |

配完可以让她发一条试试：「发条日记」→ 看是不是分行了。

## 7.6 自带客户端 & QQ 状态（0.12.0 起）

- **不再依赖** `astrbot_plugin_qzone` / `astrbot_plugin_qqprofile`：发/删/查说说、改昵称/签名都走自带客户端，
  **默认就是自带**；那两个插件可以直接卸载。只有自带客户端初始化失败时才临时兜底用它们。
- Cookie：默认问协议端 `get_cookies`；协议端不支持时，让使用者从浏览器复制 Cookie 填进 `qzone_cookie`。
- 每天总结：由自带客户端按 `daily_post_time` 自己写自己发（日志里能看到「自带客户端：下次每天总结 23:00」）；
  如果 QQ空间插件还开着 AutoPublish，启动时会先把它停掉，避免一天两条。
- QQ 状态：`auto_status_enabled`（默认开）+ `auto_status_minutes`（默认 90）；
  按心情映射（困→睡觉中、疲惫→被掏空、emo→emo中、开心→元气满满…），状态没变不改。
- 验收：
  1. 让她调 `qzone_selfcheck` → 应回「客户端=自带客户端｜uin=…｜昵称=…」；
  2. 说「发条说说」→ 能发出去；
  3. 说「把状态改成摸鱼中」→ QQ 上能看到状态变了；
  4. 等一轮 `auto_status_minutes` → 日志里出现「QQ 状态改成：…」。

## 7.7 隐私护栏：说说里不许出现群成员的信息（0.13.2 起）

**0.13.2 之前完全没有防护。** 判断素材是最近几十条消息，九成是群聊，原话（截 200 字）
直接进提示词，格式是 `[时间] 1234: 原话`。模型完全可能把「谁说了什么」写进说说——
而 QQ 空间是好友可见的。这一节是补上的三层。

### 7.7.1 提示词红线（`JUDGE_PROMPT`）

明确写了：最近聊天里大部分是群里别人说的，只是判断心情的参考素材，**一句都不许写进说说**；
不许出现 QQ 号/尾号/昵称/群名/@；不许复述也不许改写原话；只能写她自己的所见所想。
还加了一条兜底：如果这条说说的素材主要是别人的事，干脆不发（`post.want=false`）。

### 7.7.2 发之前硬检查（`privacy_violation()`）

模型再怎么写，发出去之前还要过一道：

| 检查 | 命中就 |
|---|---|
| 正文里出现群成员的 QQ 尾号（前后不挨着数字） | 不发 |
| 正文里连续 8 个字和某条群聊消息重合 | 不发（判定为复述原话） |

命中时日志：`[QzoneKit] 拦下这条说说（原因），没有发布。正文：…`

**阈值为什么这么定**：
- 尾号只在「前后不是数字」时才判，否则 `18:19` 这种时间会被误伤
- 8 个字的重叠，套话撞不上（「今天天气不错」只有 6 个字），复述一整句一定撞上

实测四种情况都符合预期：干净自述放行、带尾号拦下、复述原话拦下、泛指不点名放行、
`18:19` 不误伤。

### 7.7.3 系统消息不进判断素材

以前 `state.recent` 里会混进 `<system_reminder>`、`# CRON JOB CONTEXT` 这类系统内容
（实测 120 条里 2 条）。它们不是人说的话，留着只会让她写出莫名其妙的东西。

现在 `_capture()` 直接丢，而且**启动时会把历史上混进去的清一遍**（`_load_state` 之后）。
清的时候日志是 `[QzoneKit] 清掉 N 条混进聊天记录的系统消息`。

### 7.7.4 关掉的办法

配置项 `qzone_privacy_guard`，默认 `true`。

**不建议关。** 关了只剩提示词那一层，模型想写就能写出去，而空间是公开场合，
一条泄露收不回来。

### 7.7.5 这套护栏管不到的地方（老实说）

- 她可能用「有人说」+ 高度概括的方式提到群里的事——这拦不住，也不该拦
- 如果群成员的名字本身就是常见词（比如有人 nick 叫「晚饭」），8 字重叠不会命中
- 护栏只看**最近窗口里的群消息**；更早的群聊如果被记忆中枢注入了，不在检查范围

真要彻底安全，就把「群聊记忆注入私聊」也关掉（那是记忆中枢的
`visibility.allow_group_public_in_private`），两件事一起做才没有缝。

---

## 7.8 现画配图：说说配一张现画的图（0.14.0 起）

**要解决的问题**：她想配的图不是表情包图库里那种，是「今天的海边」「我现在这个样子」——
得现画一张。豆包出一张 20~60 秒，而 AstrBot 的工具调用有 **120 秒**硬上限，
直接 await 会把工具掐掉（和豆包插件当初的 `async_paint` 同一个坑）。

**链路**：

```
工具 qzone_mood_post / qzone_post_on_demand(illustration="画面描述", self_portrait=?)
  → _apply_post(illustration=…)              解析冷却/攒批，决定现在发还是攒着
  → _spawn_ai_post()                         后台任务，工具立刻返回「配图在画了」
  → _ai_paint(desc, self_portrait)           画她自己 ⇒ 先从 refs 挑角色参考图 + 锁形象说明；
                                             再调 astrbot_plugin_doubao_paint 的 _generate，
                                             共用它的 _lock（同一时刻只画一张）
  → _prepare_generated()                     1728×2304 PNG → 长边 1600 的 JPEG
  → _publish(body, [jpg])                    带图发；失败退回表情包 → 再不行纯文字
  → context.send_message(umo, "说说发好了")   画完回一句
```

**几个关键决定**：

| 决定 | 为什么 |
|---|---|
| 画图放后台任务 | 工具 120 秒上限；等画完再返回，模型那轮就被掐了 |
| 跟豆包画画插件共用 `_lock` | 同一时刻只画一张，别两条说说同时抢豆包的输入框 |
| 画她自己时带角色参考图 | 不然豆包每次画出来都是不同的人，一看就出戏 |
| 画不出来退回表情包 | 图是锦上添花，说说本身不能丢；有表情包就先补一张 |
| 原图压成长边 1600 JPEG | 原图 4MB 左右，QQ空间上传接口容易失败；压完约 300KB |
| 给了画面描述就不配表情包 | 一张图够了，两张图反而怪 |
| 攒着的那条到点才画 | 冷却里可能攒好几天，提前画出来图会「过期」，也白占豆包 |

### 7.8.1 画她自己：取角色参考图（0.14.1）

`_ai_paint()` 判断「这张画里是不是她」，三个来源按优先级：

1. 工具参数 `self_portrait=true`（她主动要画自己时的显式信号）；
2. 委托给「豆包画画」的 `_looks_like_self()`（`你自己`、`泡泡`、`本鲸鱼娘`、`你的样子`…）；
3. 本插件自己的关键词表 `SELF_HINTS_QZ`：`鲸鱼娘`、`我自己`、`画我`、`我的样子`、`我的尾巴`。
   —— 第三条是必须的：自动判断时模型写的是「一只蓝色鲸鱼娘…」这种第三人称，前两条都认不出来。

命中后：

- `_pick_ref_for()` 按描述挑一张「合适」的：
  说「成熟/长大/御姐」⇒ `成熟（长大）.jpg`；说「Q版/女仆装/可爱/默认」或提到图名 ⇒ 默认那张；
  什么都没说 ⇒ 回落到默认（`默认（Q版可爱 女仆装）.png`）。
- 把挑到的图作为 `ref_images` 传给 `_generate()`，豆包会把它当参考图画；
- 提示词再追加 `star._self_appearance_text(有无参考图)`（蓝渐变长发、鲸鳍耳、鲸尾、白饭碗那套）。
- 画风景/物品时**不塞**人物参考图（否则豆包可能硬塞一个角色进去）。

实测（本机）：描述「一只鲸鱼娘端着白饭碗坐在傍晚的窗边」→ 31.6 秒出图，
出来就是蓝发渐变 + 呆毛 + 鲸鳍耳 + 深蓝女仆裙 + 鲸尾 + 白饭碗，没跑偏。

### 7.8.2 和表情包的分工（0.14.1 理顺）

| 情况 | 行为 |
|---|---|
| 有 `illustration` + 表情包开着 | 只现画，**不**配表情包（日志：`这条要现画配图，跳过表情包`） |
| 有 `illustration` 但画失败/超时 | `_pick_sticker("")` 补一张表情包；没有就纯文字（回话会说明原因） |
| 只有 `sticker` 分类 | 按 `post_sticker_prob` 概率配表情包，老规矩 |
| 冷却里攒着的那批到点发 | 碎片里记了 `illustration`/`illustration_self`/`sticker`，到点按记录来：先试画，画不出来再表情包（0.14.1 之前这条路完全没配图，是漏的） |
| 自动判断（`JUDGE_PROMPT`） | 多两个字段 `illustration` / `illustration_self`，和 `sticker` **二选一**；她给了画面描述时 sticker 会被丢掉 |

注意：`_publish` 走自带客户端时，QQ空间插件那层 `publish_post` 包装（会补表情包）不参与；
只有回落到 QQ空间插件的 service 时才会经过它，而那时 `images` 已经不为 None，不会再补第二张。

**怎么验证（本机实测过的）**：

1. 让她在 QQ 上发：「发条说说，配一张你在海边端着饭碗的画」
   → 工具秒回「配图在画了」，约 30 秒后收到「说说发好了（配图画了 xx 秒）」，空间里那条带图。
2. 日志关键字：`[QzoneKit] 配图画好了`、`配图压缩`、`说说先画配图再发`、
   `配图画她自己：参考图=…`。
3. 故意把豆包关掉再试一次 → 日志 `配图没画出来（…），改配表情包/纯文字`，说说照样发出去。

**踩过的坑**：

- 豆包出的图是 **PNG 1728×2304**，直接传 QQ 空间经常失败或很慢，必须压。
- 豆包没在前台/没预热时第一次要 60~90 秒，所以 `post_ai_image_timeout_seconds` 默认给到 200；
  豆包画画插件开着 `prewarm_doubao` 的话，平时 20~30 秒就出图。
- 豆包图右下角有水印（非会员去不掉），发出去就是这样，提前跟使用者说清楚。
- 配图文件存在 `plugin_data/astrbot_plugin_qzone_kit/ai_*.jpg`，**只留 3 天**（超期自动清）。

### 7.8.3 「老大叫我发，她却说冷却还有 57 小时」（0.14.3 修）

**症状**：老大在 QQ 上说「发条说说」，她回「先攒着了，冷却还有 57 小时左右」。

**根因**：不是冷却算错，是**工具走错了**。插件有两个发说说的工具：

| 工具 | 谁该用 | 看不看冷却 |
|---|---|---|
| `qzone_post_on_demand` | **老大点名要发** | 不看（`force=True`） |
| `qzone_mood_post` | 她自己想发 | 看（2~3.6 天） |

模型看到「发说说」就顺手选了 `qzone_mood_post`（名字里没有 on_demand 那么直白），于是老老实实按冷却攒着。

**修法（两道保险）**：

1. 工具说明改硬：`qzone_mood_post` 开头直接写「老大叫她发**不要用这个**，用 `qzone_post_on_demand`」；
   `qzone_post_on_demand` 写「老大叫她发**一律用这个**，完全无视冷却，攒着的一起发掉」。
2. **插件级保险丝** `_owner_asked_to_post()`：就算模型还走错，只要老大这条消息里出现了
   `发说说 / 发条说说 / 发个说说 / 发动态 / 发空间 / 发周记 / 发日记 / 发心情 / 现在就发 / 立刻发 /
   赶紧发 / 帮我发 / 给我发 / 发出去 / 发一下`，`qzone_mood_post` 自己改成 `force=True`；
   出现 `别发 / 不要发 / 不用发 / 先别发 / 不发了` 则**不**强制（这句是否定）。
   命中时日志：`老大在消息里明说要发（…）→ 无视冷却，立即发，不再攒`。
3. 攒着的回话里追加一句给模型看的提示：`【提示】如果是老大点名让你发的，改用 qzone_post_on_demand 重发一次。`
   —— 这样即使保险丝没命中（比如老大发的是语音、`message_str` 是空的），模型也有机会在同一条回复里改正。

**怎么验证**：

| 说 | 应该 |
|---|---|
| 「发条说说」 | 立刻发（日志有「无视冷却」），不会再报冷却 |
| 「现在就发一条」 | 立刻发 |
| 「别发说说」 | 照旧按冷却攒着（否定词生效） |
| 什么也不说、她自己想发 | 按冷却攒着（正常行为） |

### 7.8.4 她不调工具、光靠记忆答「不能发」（0.14.4）

0.14.3 修完还有个缺口：老大问「**现在可以发动态吗？**」时，她可能**一个工具都不调**，
直接把几十分钟前那条「冷却还有 57 小时」的旧结果复述一遍。工具改得再好也没用——
她压根没去问插件。

**修法**：`@filter.on_llm_request()` 每一轮往 `req.extra_user_content_parts` 里塞一段
**临时**说明（`TextPart` + `mark_as_temp()`，不进聊天历史，不会越滚越长）：

```
【QQ 空间：这一刻的真实情况（以这里为准，别凭记忆或旧工具结果答）】
· 上次发说说：2026-11-14 20:01（5.0 小时前）｜现在攒着 5 段（到点会自动合成一条发）
· 她自己想发的节奏：平时 2~3.6 天一条，最短冷却还差 43 小时——这**只**决定「她自己想发」时攒不攒
· 老大让她发：什么时候都能发，不看上面那个节奏 → 调 qzone_post_on_demand（无视冷却、立刻发…）
· 老大问「现在能不能发」：能。直接发，别答「不能发」「等冷却」。
```

老大这句本身命中 `_owner_asked_to_post()` 时，末尾再追加一句：
`（老大这一句就是在让你发说说：别回「现在不能发」、也别再问一遍，直接调 qzone_post_on_demand 把它发出去。）`

**关键点**：把「她自己的节奏」和「老大叫发」拆成两条写，冷却那个数字**只**挂在前者上——
否则模型看到「还差 43 小时」又会答「不能发」。

**验证**：重载插件后随便跟她聊一句，日志里会出现一次（只打一次）
`[QzoneKit] 每轮都会把「空间现状」带给模型`。之后问「现在可以发动态吗」，
她应该答「可以」并直接调工具。

### 7.8.5 要了配图，说说发出去了却没有图（0.14.5）

**症状**：老大说「先发空间吧，配一张想画的图」，说说发出去了，**没有图**。

**根因**（日志实拍）：

```
工具参数 = {'kind': 'mood', 'extra': '配上一张"想画的图片"：一个暖色灯光……'}
```

模型把整段画面描述写进了 `extra`（这个字段只会加进**正文**的写作要求），
`illustration` 留空 → 插件当然不会画。第二次它换成 `illustration=...` 就出图了。

**修法两刀**：

1. `extra` 的说明写死：「**只写正文的补充要求**；老大要配图别写在这里，写在这里不会画，
   用 `illustration`」，并给了个例子。
2. **兜底**：`_maybe_picture()` —— 只要老大这句话（或 `extra`）里在要图、而模型没给画面描述，
   插件就自己调一次小模型按说说正文写 40~120 字的画面描述，再交给豆包画。
   日志：`老大要配图、但没给画面描述 → 插件自己写一段再画：…`

**「在要图」怎么判**（`_asks_for_image`）：不能写死词组——`配上一张想画的图片` 里是「配上」
不是「配一张」。所以规则是：**有「配」又有「图/画」**，或者出现 `插图 / 画一张 / 画一幅 /
画只 / 画个 / 配图`。先用否定表过滤（`不要配图 / 别配图 / 不用配图 / 不配图 / 别画 / 不要画`）。

自动写的描述提示词里还有一条：如果这条说说写的是她自己，就用「鲸鱼娘」称呼她 ——
这样 `_ai_paint()` 的自身识别能命中，会带上角色参考图（否则可能画成陌生人）。

**验证**（本机单测）：

| 输入 | `_asks_for_image` |
|---|---|
| `配上一张想画的图片：暖光灯下…` | true |
| `再发一条说说，配一只小猫的图片` | true |
| `不要配图` | false |
| `今天好累` | false |

`_maybe_picture`：没描述 → 调一次 LLM 生成描述；已给描述 → 原样用、**不额外调模型**；没要图 → 空。

---

## 7. 边界（给使用者的实话）

- **删说说不可撤销**：`qzone_delete_feeds` 按日期是**整批删**；调用前确认使用者说的是「删」。
- **配图**：`post_sticker_enabled` 默认关，必须使用者明确同意才开（会读 `meme_manager` 的图包）；
  现画配图 `post_ai_image_enabled` 默认开（要装豆包画画插件），两者二选一，现画失败才退回表情包。
- **每天总结错过不补**：那个点没开机、机器人不在线，当天就没有总结——补发的总结会时间错位。
- **和 QQ空间插件并存**：总结由 QQ空间 的 AutoPublish 发，本插件只管「她自己的即时说说」，两边各算冷却。
  本插件会避开总结时间；`daily_post_sync_qzone: false` 时完全不写对方配置。
- **只读白名单**：读别的插件状态走白名单（`*state*.json`、`*diary*.json`、`*.sqlite3` 等），
  `state_read_all_files` 默认 false，别随便开。
- **成本**：每轮判断是一次小型 LLM 调用（45 分钟一轮 ≈ 一天 32 次），提示词很短，花费可忽略。

---

## 8. 配完要告诉使用者什么（照抄改数字）

> 配好了。现在的状态：
> - 每天自动发说说：**开**，默认 **23:00** 自动发那条「今天的总结」。
>   **时间可以改**（`daily_post_time`，改完 QQ空间那边会一起改）；
>   **那个时间点电脑没开 / 机器人不在线，当天的总结就不发了，也不补发**。
> - 自动改签名：**开**（平时 13~32 天一次，遇到大事 22~29.2 小时）
> - 自动发说说：**开**（平时 2~3.6 天一条，3 天没发会保底一条）
>   - 跟每天总结挨太近会自动躲开：攒着的那批避开前后 1.5 小时（撞了就重新抽时间）；
>     现在就发的只避 15 分钟，撞上往后挪 30 分钟
>   - 关机错过的：开机后 3 分钟 + 随机 2~60 分钟补发；攒超过 5 天的碎片丢掉，全过期就不发、当已发过
> - 配图：**开/关**（按你同意的来），概率 **75%**；每天那条总结也一起配图；
>   GIF 动图原样发（保动画）。来源：「表情包管理器」的全部图包
> - 判断间隔：45 分钟一轮
>
> 想改哪个随时说：三个开关、配图概率、冷却区间、判断间隔、每天总结的时间都能单独调。

---

## 9. 常见问题（使用者会问的）

**Q：为什么有时候说说隔了三四天才发？**
A：冷却平时是 2~3.6 天，而且撞上总结时间会被重新抽时间，所以是「两三天到四天」这个范围。

**Q：为什么凌晨/早上发的？**
A：它不预设活跃时段，什么时候想发就发；只有贴着每天总结那 15 分钟才会往后挪半小时。

**Q：总结能改到别的时间吗？**
A：能，改 `daily_post_time`（`HH:MM`），QQ空间 的排期会自动跟着改；改完记得看重启后的日志。
