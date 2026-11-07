# 给 AI 的施工文档：把「空间小助手」配到能自己发说说、自己换签名

> 读者是**接手配置的 AI**。使用者会把这份文档 + `README.md` 给你，并说一句：
> 「请帮我配置好 AstrBot 里的【空间小助手】插件，并检测功能是否可用。」
>
> 照做完，应该达到：**她自己判断要不要发 QQ 空间、要不要换签名，能带表情包，能删说说，能改资料。**
> 文档里所有数值都是本机实测跑通的，不是猜的。**第 4 节是必做项**，漏了会「说说永远发不出去图」。

---

## 0. 开工前必须问使用者（别自己决定）

按顺序问，问完再动配置：

1. **每天自动发说说**（QQ空间插件 23 点那条「今天的总结」）要不要开？——**默认开**
2. **自动改签名**要不要开？——**默认开**
3. **自动发说说**（她自己有情绪/有事的即时说说）要不要开？——**默认开**
4. **发说说要不要配表情包**？——**默认关，必须他明确同意才开**。
   要主动说明来源：

   > 配图来自「表情包管理器」(`meme_manager`) 的图包，它会读那个插件里**所有**表情包的图片，
   > 按 **75%（高概率）** 给说说配一张；**每天那条总结也一起配图**，
> 两边共用同一个概率，想调就改 `post_sticker_prob`。
   > GIF 动图会**原样发**（空间保动画），其它格式转静态 JPEG。
   > 插件地址：https://github.com/anka-afk/astrbot_plugin_meme_manager
   > 不同意就保持 `post_sticker_enabled: false`，其它功能不受影响。

5. 顺带确认：每天总结要不要跟本插件的「即时说说」并存（两者各算冷却）；
   不想要两条的话把 QQ空间 的 `trigger.publish_cron` 关掉。
   并存的话本插件会自动躲开那个点（前后各 1.5 小时不自己发，撞上就推后 4~12 小时），
   每天总结是几点不用手填——`daily_post_time` 默认 23:00，改它 QQ空间那边跟着变；
不想管就清空，会每次现读 `publish_cron`。

**配完必须回报**：哪三个开关是开的/关的、配图开没开、配图概率多少、判断间隔多少。
模板见第 7 节。

## 1. 前置（只这两个，别的一个都不用）

| 插件 | 仓库 | 本机实测版本 |
| --- | --- | --- |
| QQ空间 `astrbot_plugin_qzone` | https://github.com/Zhalslar/astrbot_plugin_qzone | v3.2.0 |
| QQ资料管理 `astrbot_plugin_qqprofile` | https://github.com/Zhalslar/astrbot_plugin_qqprofile | v1.1.6 |

要求：

1. 平台是 **aiocqhttp（OneBot v11）**，因为要发 QQ 空间、改 QQ 资料。
2. **QQ空间必须先能用**：能取到 Cookie、能正常看/发说说（它的命令 `看说说`、`发说说` 能跑）。
3. 两个插件都**启用**。检查日志（搜插件名）：
   - `Loading plugin astrbot_plugin_qzone ...` 并且有 `[AutoPublish] 下次任务时间…`
   - `Loading plugin astrbot_plugin_qqprofile ...`
   - 如果出现 `Plugin xxx is disabled.`，说明它在 AstrBot 的停用名单里
     （`data/data_v4.db` → `preferences` 表 → key `inactivated_plugins`），
     要么在 WebUI 里点启用，要么把对应 module_path 从那个 JSON 数组里删掉再重启。
4. 表情包是**可选**的：想带图就先装「表情包管理器」`meme_manager` 并至少有一个图包；
   没装也能用，只是不带图。

---

## 2. 装本插件

```
<AstrBot>/data/plugins/astrbot_plugin_qzone_kit/
├── main.py
├── metadata.yaml
├── _conf_schema.json
├── README.md
└── SETUP-FOR-AI.md
```

放好后**完整重启 AstrBot**（不是面板里的「重载插件」——重载不会重新读配置和代码）。验证日志：

```
Loading plugin astrbot_plugin_qzone_kit ...
Added llm tool: qzone_delete_feeds
Added llm tool: qzone_delete_feeds / qq_profile_update / qzone_post_summary
                / qq_signature_maybe_change / qzone_mood_post
[QzoneKit] 已启动：自动签名=True（平时 13~32 天 / 重要 22~29.2 小时）、
           自动说说=True（平时 2~2.6 天 / 重要 22~29.2 小时）、判断间隔=45 分钟
[QzoneKit] 真发模式；表情包=True；一次性强制发=False
```

五个工具缺一个，就是插件没加载成功（看 traceback，多半是 schema 写错或语法错）。

---

## 3. 配置

文件：`<AstrBot>/data/config/astrbot_plugin_qzone_kit_config.json`
（第一次启动 AstrBot 会按 schema 自动生成，然后把下面这套覆盖进去）

```json
{
  "owner_uids": "",
  "auto_signature_enabled": true,
  "signature_normal_min_days": 13,
  "signature_normal_max_days": 32,
  "signature_critical_min_hours": 22,
  "signature_critical_max_hours": 29.2,
  "auto_post_enabled": true,
  "post_normal_min_days": 2,
  "post_normal_max_days": 2.6,
  "post_critical_min_hours": 22,
  "post_critical_max_hours": 29.2,
  "post_max_fragments": 5,
  "judge_interval_minutes": 45,
  "recent_message_limit": 40,
  "judge_provider_id": "",
  "daily_post_enabled": true,
  "post_sticker_enabled": true,
  "post_sticker_prob": 0.75,
  "post_fallback_days": 3,
  "dry_run": false,
  "test_force_post_once": false
}
```

含义 + 为什么这么配：

| 键 | 值 | 为什么 |
| --- | --- | --- |
| `signature_normal_min_days` / `_max_days` | 13 / 32 | 签名平时要「十几天到一个月」才动一次，太快就假 |
| `signature_critical_min_hours` / `_max_hours` | 22 / 29.2 | 遇到大事允许缩短到「一天左右」，但别正好 24 小时（像定时任务） |
| `post_normal_*` | 2 / 2.6 天 | 说说比签名勤，但也不能天天刷 |
| `post_critical_*` | 22 / 29.2 小时 | 强烈情绪/大事才允许一天一条 |
| `post_fallback_days` | 3 | **保底**：3 天没发就要求她这轮必须发一条日常，避免长期沉默 |
| `judge_interval_minutes` | 45 | 判断频率。调试时可以临时改 2~3（见 5.3），正式改回来 |
| `daily_post_enabled` | true | 每天 23 点那条总结（QQ空间插件 AutoPublish）；关掉会 `terminate()` 掉它 |
| `post_sticker_enabled` | true | 带表情包。**启用前必须问使用者同意**；来源是「表情包管理器」`meme_manager`（https://github.com/anka-afk/astrbot_plugin_meme_manager），用它**全部图包**（本机实测 2 个包共 331 张），GIF 原样发（保动画），其它格式转 JPEG |
| `post_sticker_prob` | 0.75 | 3/4 的说说带图；**每日总结与即时说说共用这个概率**（插件会包一层 `publish_post`） |
| `daily_post_time` | `23:00` | 每天总结几点（`HH:MM`）。改这里会同步改 QQ空间的排期与配置；在 QQ空间 那边改了这边也会跟过来。清空 = 每次现读 `publish_cron` |
| `post_avoid_window_hours` | 1.5 | 每天总结前后**各**这么多小时不自己另发；撞上就往后推 |
| `post_shift_min_hours` / `_max_hours` | 4 / 12 | 推后的小时数区间（这个区间里随机） |
| `dry_run` | false | 试运行开关：true = 只判断、只写日志 |
| `test_force_post_once` | false | 一次性测试开关（见 5.3），平时必须 false |

> ⚠️ **AstrBot 会把 schema 里没有的配置键直接删掉**（日志 `Config key removed`）。
> 如果你要给插件加新配置，**必须同时写进 `_conf_schema.json`**，否则代码永远读到默认值。

---

## 4. 带图说说为什么会 0 张图（上游 bug + 本地绕过方案）

**症状**：说说发出去了但没图；日志里

```
[QzoneKit] 带图发布失败（发布说说失败：{}），退回纯文字再发一次
[诊断] 规范化后 0 张图，大小=[] 字节
[诊断] 带图发布：ok=False code=-10061 data='{}'
```

**根因**：QQ空间插件 `core/qzone/utils.py` 的 `download_file()` 用 `urlparse` 判断"本地路径还是 URL"。
Windows 盘符路径 `D:\xxx.jpg` 会被解析成 **scheme="d"**，于是走到"不支持的协议"分支 → 返回 None →
0 张图 → 发布时 `pic_bo` 为空 → QQ 返回 `code=-10061`。

### 推荐做法：先向上游反馈 / 提 PR

这个问题在 **QQ空间插件**（`astrbot_plugin_qzone`）里，不是本插件的 bug。优先级从高到低：

1. **给上游提 issue/PR**（最推荐）：把上面的根因和复现步骤贴过去，建议它在 `download_file()` 里
   **先判断本地文件是否存在**（`os.path.isfile`），存在就直接读文件，再回退到 URL 解析
2. **等上游修**：修好后本插件不需要任何改动，配图自然恢复
3. **本地临时绕过（有风险，见下）**：自己改第三方插件源码

### 本地临时绕过（仅在 1、2 都等不了时）

> ⚠️ **风险提示（请先读）**
> - 这会修改**别人的插件**：上游升级时会被覆盖，升级后要重新打
> - 改坏了会影响 QQ空间插件**所有**功能（不只是本插件的配图）
> - 不是本插件维护范围：出问题请先还原备份、再向上游反馈
> - **动手前必须备份**：`utils.py` → `utils.py.bak`

改法：在 `download_file()` 最前面加"本地文件优先"判断——**已存在文件就直接读，不做 url 解析**：

```python
# 改前备份：core/qzone/utils.py → utils.py.bak
def download_file(url: str):
    # PATCH-BY-USER: 本地绝对路径优先（Windows 盘符会被 urlparse 误判成 scheme）
    try:
        if isinstance(url, str) and os.path.isfile(url):
            return Path(url).read_bytes()
    except Exception:
        pass
    # ...原有 urlparse 逻辑保持不变...
```

改完**必须整进程重启 AstrBot**，再发一条带图说说验证；不行就还原备份。

> 如果你不想动别人代码：把 `post_sticker_enabled` 关掉，只用纯文字说说——功能不受影响，只是没有配图。

## 5. 验证（照顺序做，每步有判定）

### 5.1 工具在不在（30 秒）

日志里数一遍 `Added llm tool:`，应当有：
`qzone_delete_feeds`、`qq_profile_update`、`qzone_post_summary`、`qq_signature_maybe_change`、`qzone_mood_post`。

### 5.2 判断循环真的在跑（3 分钟）

把 `judge_interval_minutes` 临时改成 `2`，重启，等 3 分钟，日志应当出现：

```
[QzoneKit] 本轮判断：签名=不动｜说说=不发｜配图=''
```

- 有这行 ⇒ 抓消息 → 喂模型 → 解析 JSON 全通。
- 出现 `判断这一轮出错：'"signature"'` ⇒ 你用的还是旧代码（提示词里的 JSON 花括号被 `str.format()` 吃了），换新版 `main.py`。
- 出现 `判断没给出可用的 JSON，…模型原文前 200 字：...` ⇒ 模型没按格式回，把原文看一眼再调提示词。

### 5.3 端到端真发（10 分钟内）

生产环境不敢乱发，用这个开关：

```json
"dry_run": false,
"test_force_post_once": true,
"judge_interval_minutes": 2,
"post_sticker_enabled": true,
"post_sticker_prob": 1.0
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
2. QQ 空间多了一条带图的说说；
3. `posts_*.db` 最新一行 `images` 不是 `[]`。

**测完必须恢复**：`test_force_post_once: false`、`judge_interval_minutes: 45`、`post_sticker_prob: 0.5`、冷却改回第 3 节的正式值，再重启一次。

### 5.4 纯自动（可选，验证「不需要人喊」）

临时把冷却压到分钟级 + 让 `post_fallback_days: 0`（每轮都要求发），`test_force_post_once: false`：

```json
"judge_interval_minutes": 2,
"post_fallback_days": 0,
"post_normal_min_days": 0.001, "post_normal_max_days": 0.002,
"post_critical_min_hours": 0.02, "post_critical_max_hours": 0.04
```

2 分钟内应当看到：

```
[QzoneKit] 已 0.0 天没发说说，这轮要求它至少发一条
[QzoneKit] 本轮判断：签名=不动｜说说=要发（…）｜配图='confused'
[QzoneKit] 说说已发（88 字）：…
```

这条路径**没有任何强制开关**，是它自己判的。测完同样恢复。

---

## 6. 排查表

| 症状 | 原因 | 修法 |
| --- | --- | --- |
| 日志 `Plugin astrbot_plugin_qzone_kit is disabled.` | 在停用名单里 | 从 `inactivated_plugins` 删掉再重启 |
| 五个工具没有全注册 | 插件加载报错 | 看 traceback；多半是 `main.py` 语法或 `_conf_schema.json` 不是合法 JSON |
| 永远不会发说说 | 判断循环每轮异常 | 搜日志 `判断这一轮出错`；旧版是 `KeyError('"signature"')` |
| 改了配置不生效 | AstrBot 删了 schema 外的键 | 把键写进 `_conf_schema.json` |
| 说说发了但没图 | 见第 4 节 | 打 `download_file` 补丁 |
| `1 validation error for Post` | 给 `images` 传了 bytes | 传字符串路径 |
| 说说不发、日志只有「攒着」 | 冷却没过 | 正常行为；看 `state.json` 的 `pending_due` |
| 签名一直不动 | 平时区间是 13~32 天 | 正常；想验证用 5.3 的强制开关 |
| 改头像没反应 | 没给图 | 让它发图或给图片链接，工具会从消息里取 |

---

## 7. 配完要告诉使用者什么（照抄改数字）

> 配好了。现在的状态：
> - 每天自动发说说（23 点那条总结）：**开**
> - 自动改签名：**开**（平时 13~32 天一次，遇到大事 22~29.2 小时）
> - 自动发说说：**开**（平时 2~2.6 天一条，3 天没发会保底一条）
> - 配图：**开**，现在是**高概率配图（75%）**，而且**每天那条总结也会配图**（同一个概率）；
>   图来自「表情包管理器」（https://github.com/anka-afk/astrbot_plugin_meme_manager）里所有图包
> - 配图频率**可调**：`post_sticker_prob`（0 = 不配，1 = 每条都配）
> - 判断间隔：45 分钟一轮；QQ空间插件的图片补丁也打好了（不然带图说说发不出去）
>
> 想改哪个随时说：三个开关、配图概率、冷却区间、判断间隔都能单独调。

## 8. 边界

- **删说说不可撤销**：`qzone_delete_feeds` 按日期是**整批删**；调用前确认使用者说的是「删」。
- **表情包**：`post_sticker_enabled` 默认 false，启用前必须获得使用者同意（会读取 `meme_manager` 图包）。
- **和 QQ空间插件自带的 23:00 AutoPublish 并存**：那条是「每日总结」，本插件是「有情绪/有事的即时说说」，
  两边各自算冷却；本插件会自动躲开那个时间点前后各 1.5 小时（撞上就推后 4~8 小时）。
  时间从 QQ空间 的 `publish_cron` 现读，对方改了会跟着变；也可以用本插件的 `daily_post_time` 反过来定它。
  如果不想要两条，把 QQ空间 的 `trigger.publish_cron` 关掉（或反过来）。
- **成本**：每轮判断就是一次小型 LLM 调用（45 分钟一轮 ≈ 一天 32 次），判断提示词很短，花费可忽略。
