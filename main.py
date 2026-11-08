"""空间小助手（AstrBot 插件）。

把「QQ 空间 / QQ 资料」这几件事收成**一个插件**，只依赖 `astrbot_plugin_qzone`（删/发说说、Cookie）
和 `astrbot_plugin_qqprofile`（只借它的状态表；不装也能跑）。**不调用任何别的插件**。

工具（模型可以直接调）：
  1. `qzone_delete_feeds`   删说说：按「第几条」/「哪一天」
  2. `qq_profile_update`    改资料：昵称 / 签名 / 状态 / 头像
  3. `qzone_post_summary`   立刻发一条「今天的总结」
  4. `qq_signature_maybe_change`  想换签名（自己判断，插件管冷却）
  5. `qzone_mood_post`      想发说说（发泄/被安慰/新鲜事/感触…插件管冷却与攒批）

自动行为（后台，不用人喊）：
  · **自动改签名**：低频。平时攒到「好几天～十几天」才动一次；
    遇到重要的事/心情特别好或特别坏/新目标 ⇒ 可以立刻动，但仍有冷却（默认 5 天）；
    非常重要 ⇒ 冷却可以缩到 24 小时；冷却没过就**记下来**，到点再换；
    等待期间又来了新的 ⇒ 新的覆盖旧的（只留一条，不排队）。
  · **自动发说说**：有个「想发」的判断（发泄、被安慰、新鲜事、重要事、想记录、社交需求、感触），
    也有冷却（默认 2 天）；不重要的小事**攒着**，等冷却好了合成一条发；
    非常重要 ⇒ 冷却缩到 24 小时。
  · 判断靠「最近聊天 + 现在时间 + 上次改/发的时间」，走当前会话那个模型，不额外配 provider。

⚠️ 和 QQ空间插件自带的 23:00 AutoPublish 并存：那条是「每天的总结」，
   这里的是「有情绪/有事的即时说说」。除了冷却，还加了一道时间窗：
   自己发说说如果落在「每天总结」前后 N 小时（默认 1.5）里，就不发，
   把冷却往后推 4~8 小时，这段时间内容继续攒着，到点一起发。
   总结几点发是现读 publish_cron 的（也可以用 daily_post_time 反过去定它）。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import random
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

PLUGIN_NAME = "astrbot_plugin_qzone_kit"
PLUGIN_VERSION = "0.9.9"

QZONE_PLUGIN = "astrbot_plugin_qzone"
QQPROFILE_STATUS = "astrbot_plugin_qqprofile"

CN_DAY_OFFSET = {
    "大前天": 3,
    "今天": 0,
    "今日": 0,
    "昨天": 1,
    "昨日": 1,
    "前天": 2,
    "前日": 2,
}

# 一次判断的提示词：让模型只回 JSON，别写别的
JUDGE_PROMPT = """你是这个 QQ 机器人的「心情与记录」判断器。看下面的近期聊天，判断两件事：

A. 要不要改她的 QQ 签名？
   - 签名是「她自己的状态/心情/目标/兴趣」，不是对某句话的回复。
   - 平时很稳定，只有真的「变了一个状态」才值得改（新目标、心情大转弯、特别在意的事）。
   - 只给一句 12~24 字的签名，可以带一点她的口癖，不要引号、不要 emoji 堆叠。
B. 要不要发一条 QQ 空间说说？
   - 值得发的场景：发泄、被别人安慰到、遇到新鲜事/重要事、想记录点什么、想找人说说话、有感触。
   - **也允许写「不想当面说出口的话」**：暗戳戳的吐槽、心里憋着的小情绪、
     对某件事的真实看法、不好意思直接讲的委屈或小心思 —— 这种恰恰是适合发空间的。
     写的时候用第一人称、克制一点，别点名骂人、别写成对谁的控诉。
   - 不值得：日常寒暄、重复的话题、没什么可说的。
   - 给 1~3 句、60~160 字的正文，第一人称、口语、具体（提一下是什么事），不要像总结报告。

【怎么把她现在的状态用上（很重要）】
- 睡眠/精力差（比如「很晚了」「精神发飘」「困」）→ 只写短句、轻的，别长篇大论；太晚了宁可少发或干脆不发。
- 情绪低落、委屈、被安慰 → 更容易想写，这类适合发（也适合当成签名的心情）。
- 今天有明确进展 / 目标推进 / 发生了大事 → 值得记录，重要度可以直接给 important。
- 梦境、日记碎片、当前片段 → 是最好的素材，可以化用到说说里，别照抄。
- 关系和互动偏冷（互动状态不是放松、或者很久没聊）→ 少发，或者只写给自己看的那种。
- 白天精神好、刚被夸、刚聊得开心 → 可以主动发一条轻快的。
- **很久没人找她说话**（聊天记录很空、或最近几小时没动静）→ 这也是素材：
  可以写安静的日常、自己的小想法、端着饭碗发呆、等消息的心情、
  把今天过成什么样了；**但别写成抱怨被冷落**，也别每轮都写「没人理我」，
  同一个意思值发一次就够了。

- 时间必须和【现在时间】对得上：用【现在时间】括号里给的称呼（那几个都可以用，挑自然的），**不要用范围外的时段**（比如 18:39 不能说半夜、凌晨；凌晨也不能说成傍晚）。

重要程度分三档：
  normal    = 有意思，但不急
  important = 挺重要（心情明显波动、确实有新目标/大事）
  critical  = 非常重要（重大变故、特别强烈的情绪）

另外，如果这条说说的情绪很明确、配一张表情包会更像人，就顺便给一个分类：
happy(开心/庆祝) angry(生气/玩笑威胁) sad(委屈/受挫) confused(迷惑/思考) surprised(惊讶/害怕)
shy(害羞) sleep(困/休息) affection(喜欢/贴贴/安慰) food(吃饭/馋) money(花钱/要饭)
greeting(到达/打招呼) work(打工/加班/摸鱼) entertainment(唱歌/玩/节日) teasing(自嘲/嫌弃/反转)
reply(直接对话回应) —— 没合适的就留空字符串。

严格只输出一个 JSON 对象，不要 Markdown、不要解释：
{"signature": {"change": true/false, "text": "...", "importance": "normal|important|critical", "reason": "一句话"},
 "post": {"want": true/false, "text": "...", "importance": "normal|important|critical", "reason": "一句话"},
 "sticker": "happy 之类的分类，或空字符串"}

【她现在的状态（来自人格与其它插件）】
[[state]]
【当前签名】[[signature]]
【上次改签名】[[sig_last]]
【上次发说说】[[post_last]]
【还欠着的待发内容】[[pending]]
【最近聊天】
[[recent]]
"""


def parse_target_day(text: str) -> date | None:
    """「今天 / 昨天 / 前天 / 大前天 / 2026-11-03 / 11-03 / 11月3日」→ 日期。"""

    raw = (text or "").strip()
    if not raw:
        return None
    today = datetime.now().date()
    for word, offset in CN_DAY_OFFSET.items():
        if word in raw:
            return today - timedelta(days=offset)
    for sep in ("-", "/", "."):
        parts = raw.replace("月", sep).replace("日", "").replace("号", "").split(sep)
        nums = [p for p in parts if p.strip().isdigit()]
        if len(nums) == 3:
            try:
                return date(int(nums[0]), int(nums[1]), int(nums[2]))
            except ValueError:
                return None
        if len(nums) == 2:
            try:
                d = date(today.year, int(nums[0]), int(nums[1]))
                if d > today:
                    d = date(today.year - 1, int(nums[0]), int(nums[1]))
                return d
            except ValueError:
                return None
    return None


def ts_to_day(ts: Any) -> date | None:
    try:
        return datetime.fromtimestamp(int(ts)).date()
    except (TypeError, ValueError, OSError):
        return None


@register(PLUGIN_NAME, "paopao", "空间小助手：删说说、改资料、自动改签名/发说说", PLUGIN_VERSION)
class QzoneKitPlugin(Star):
    def __init__(self, context: Context, config: dict[str, Any] | None = None):
        super().__init__(context)
        self.context = context
        cfg = config if isinstance(config, dict) else {}
        self.cfg = cfg

        raw = cfg.get("owner_uids") or ""
        if isinstance(raw, list):
            self.owner_uids = [str(x).strip() for x in raw if str(x).strip()]
        else:
            self.owner_uids = [
                x.strip() for x in str(raw).replace("，", ",").split(",") if x.strip()
            ]

        # 开关与节奏
        # 三个总开关（默认都开；配置前要让使用者确认）
        self.daily_post = bool(cfg.get("daily_post_enabled", True))
        self.auto_signature = bool(cfg.get("auto_signature_enabled", True))
        self.auto_post = bool(cfg.get("auto_post_enabled", True))
        # 改签名：平时 12~16.1 天；非常重要 22~29.2 小时
        self.sig_min_days = float(cfg.get("signature_normal_min_days", 13) or 13)
        self.sig_max_days = float(cfg.get("signature_normal_max_days", 32) or 32)
        self.sig_crit_min_h = float(cfg.get("signature_critical_min_hours", 22) or 22)
        self.sig_crit_max_h = float(cfg.get("signature_critical_max_hours", 29.2) or 29.2)
        # 发说说：平时 2~3.6 天；非常重要 22~29.2 小时
        self.post_min_days = float(cfg.get("post_normal_min_days", 2) or 2)
        self.post_max_days = float(cfg.get("post_normal_max_days", 3.6) or 3.6)
        self.post_crit_min_h = float(cfg.get("post_critical_min_hours", 22) or 22)
        self.post_crit_max_h = float(cfg.get("post_critical_max_hours", 29.2) or 29.2)
        # 每天那条「总结」是 QQ空间插件的 AutoPublish 在发（默认 23:00）。
        # 自己发的说说要躲开它前后这段时间，否则一天两条挤在一起。
        # 留空 = 完全跟着 QQ空间插件配置里的 publish_cron；填了 = 由这里说了算（也会同步过去）。
        self.daily_post_time = str(cfg.get("daily_post_time", "23:00") or "23:00").strip()
        # 躲开多少小时（前后各这么多，默认 1.5）
        try:
            self.avoid_hours = max(0.0, float(cfg.get("post_avoid_window_hours", 1.5)))
        except (TypeError, ValueError):
            self.avoid_hours = 1.5
        # 「现在就发」时的保护：只避开总结前后 15 分钟，撞上就往后挪半小时
        try:
            self.instant_guard_min = max(0.0, float(cfg.get("post_instant_guard_minutes", 15)))
        except (TypeError, ValueError):
            self.instant_guard_min = 15.0
        try:
            self.instant_push_min = max(1.0, float(cfg.get("post_instant_push_minutes", 30)))
        except (TypeError, ValueError):
            self.instant_push_min = 30.0
        # 是否允许本插件去改 QQ空间插件的 publish_cron（同步每天总结的时间）。
        # 关掉就只「读」它的时间，绝不写别人的配置、也不去重排它的定时。
        self.sync_qzone_schedule = bool(cfg.get("daily_post_sync_qzone", True))
        # 攒着的那批：抽到点时间撞上整段窗口就重抽（不往后推几个小时）
        # 攒太久的碎片就不发了（默认 5 天），免得今天的说说讲上周的事
        try:
            self.max_age_days = max(0.0, float(cfg.get("post_max_age_days", 5)))
        except (TypeError, ValueError):
            self.max_age_days = 5.0
        # 开机后先等一会儿再检查攒着的（默认 3 分钟 + 2~60 分钟随机），
        # 免得看起来像「一开机就发」
        try:
            self.boot_wait_min = max(0.0, float(cfg.get("post_boot_wait_minutes", 3)))
        except (TypeError, ValueError):
            self.boot_wait_min = 3.0
        try:
            self.boot_extra_min = max(0.0, float(cfg.get("post_boot_extra_min_minutes", 2)))
        except (TypeError, ValueError):
            self.boot_extra_min = 2.0
        try:
            self.boot_extra_max = max(self.boot_extra_min, float(cfg.get("post_boot_extra_max_minutes", 60)))
        except (TypeError, ValueError):
            self.boot_extra_max = 60.0
        # 动图表情包原样发（GIF 保动画，不转静态）
        self.sticker_keep_gif = bool(cfg.get("post_sticker_keep_gif", True))
        # 可以调到几分钟，方便先试；正经用还是 45
        self.judge_minutes = max(1, int(cfg.get("judge_interval_minutes", 45) or 45))
        # 只在「有新聊天」时才判断；间隔随机浮动，别像闹钟
        self.judge_only_on_new = bool(cfg.get("judge_only_on_new", False))
        try:
            self.judge_jitter = max(0.0, min(0.8, float(cfg.get("judge_interval_jitter", 0.35))))
        except (TypeError, ValueError):
            self.judge_jitter = 0.35
        # 试运行：只判断、只记日志，不真的改签名也不真的发说说
        self.dry_run = bool(cfg.get("dry_run", False))
        # 表情包（可选）：默认关，使用者同意才开；开了才会去读 meme_manager 的图包
        # 一次性测试开关：这一轮无论判断结果如何，都真发一条（只生效一次）
        self.force_post_once = bool(cfg.get("test_force_post_once", False))
        # 是否能读「别的插件里的状态」（好感度/情绪/关系等）和人格
        self.read_plugin_state = bool(cfg.get("read_plugin_state", True))
        # 是否允许读白名单以外的文件（默认 False，只读已知文件名）
        self.state_read_all_files = bool(cfg.get("state_read_all_files", False))
        # 只读「用户正在用的那个版本」：auto 自动判断，v1 强制旧版，v2 强制新版
        self.state_source = str(cfg.get("state_source") or "auto").strip().lower()
        if self.state_source not in ("auto", "v1", "v2"):
            self.state_source = "auto"
        raw_plugins = str(cfg.get("state_source_plugins", "") or "")
        self.state_plugins = [
            x.strip() for x in raw_plugins.replace("，", ",").split(",") if x.strip()
        ] or [
            "astrbot_plugin_private_companion",
            "astrbot_plugin_self_learning",
            "astrbot_plugin_memory_companion",
        ]
        # 保底：欠太久没发说说，就在判断时明确要求发一条（0 = 每轮都要求）
        try:
            self.post_fallback_days = float(cfg.get("post_fallback_days", 3) or 0)
        except (TypeError, ValueError):
            self.post_fallback_days = 3.0
        self.sticker_enabled = bool(cfg.get("post_sticker_enabled", False))
        try:
            self.sticker_prob = max(0.0, min(1.0, float(cfg.get("post_sticker_prob", 0.5))))
        except (TypeError, ValueError):
            self.sticker_prob = 0.5
        self.max_fragments = max(1, int(cfg.get("post_max_fragments", 5) or 5))
        # 攒太多才筛选：条数 ≥ 阈值时，发之前按重要性排序、只发最想发的几条
        # 超过 threshold 条（默认 4，即「大于三条」）才筛选；筛完发 publish_min~publish_max 条
        self.select_threshold = max(2, int(cfg.get("post_select_threshold", 4) or 4))
        self.publish_min = max(1, int(cfg.get("post_publish_min", 3) or 3))
        self.publish_max = max(self.publish_min, int(cfg.get("post_publish_max", 5) or 5))
        # 硬上限：只有「第 publish_max 条后面还有同分」时才放宽到这里
        self.publish_hard_max = max(
            self.publish_max, int(cfg.get("post_publish_hard_max", 6) or 6)
        )
        self.recent_max = max(6, int(cfg.get("recent_message_limit", 40) or 40))
        self.judge_provider = str(cfg.get("judge_provider_id", "") or "").strip()

        try:
            self.data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
        except Exception:  # noqa: BLE001
            self.data_dir = Path(__file__).resolve().parent / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "state.json"
        self.state: dict[str, Any] = self._load_state()
        # 每天总结几点的「上一次看到的值」，变了就重新打日志 / 对表
        self._daily_hm_seen: str | None = None

        self._task: asyncio.Task | None = None
        self._flush_task: asyncio.Task | None = None
        self._busy = False

    # ── 状态文件 ──────────────────────────────────────────────────────────
    def _load_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("signature", {})
                data.setdefault("post", {})
                data.setdefault("recent", [])
                return data
        except Exception:  # noqa: BLE001
            pass
        return {"signature": {}, "post": {}, "recent": []}

    def _save_state(self) -> None:
        try:
            tmp = self.state_file.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(self.state_file)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QzoneKit] 存状态失败：%s", exc)

    # ── 生命周期 ──────────────────────────────────────────────────────────
    async def initialize(self) -> None:
        # 每天 23 点那条总结是 QQ空间插件的 AutoPublish 在发；这个开关关掉就把它停了
        try:
            qz = self._star(QZONE_PLUGIN)
            publisher = getattr(qz, "auto_publish", None) if qz else None
            if publisher is not None and not self.daily_post:
                await publisher.terminate()
                self._star(QZONE_PLUGIN).auto_publish = None
                logger.info("[QzoneKit] 每天自动发说说已关闭，已停掉 QQ空间插件的 AutoPublish")
            elif publisher is not None:
                logger.info("[QzoneKit] 每天自动发说说：开启（QQ空间插件 AutoPublish 照常跑）")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QzoneKit] 处理每日总结开关时出错：%s", exc)

        # 把 QQ空间插件的 publish_post 包一层：**所有**发说说（包括它自己的每日总结）
        # 都会按同一个概率配图；带图失败自动退回纯文字。
        try:
            service = getattr(self._star(QZONE_PLUGIN), "service", None)
            if service is not None and not getattr(service, "_qkit_wrapped", False):
                _orig = service.publish_post

                async def _wrapped_publish(*, post=None, text=None, images=None, _o=_orig):
                    if images is None and self.sticker_enabled:
                        body = text or str(getattr(post, "text", "") or "")
                        img = self._pick_sticker(self._guess_category(body))
                        if img:
                            try:
                                await _o(post=post, text=text, images=[img])
                                logger.info("[QzoneKit] 说说带图发出：%s", img)
                                return
                            except Exception as exc:  # noqa: BLE001
                                logger.warning(
                                    "[QzoneKit] 带图发布失败（%s），退回纯文字", exc
                                )
                    return await _o(post=post, text=text, images=images)

                service.publish_post = _wrapped_publish
                service._qkit_wrapped = True
                logger.info("[QzoneKit] 已接管发说说：每日总结也会按概率配图")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QzoneKit] 包装 publish_post 失败：%s", exc)

        if self.auto_signature or self.auto_post:
            self._task = asyncio.create_task(self._judge_loop())
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info(
            "[QzoneKit] 已启动：自动签名=%s（平时 %g~%g 天 / 重要 %g~%g 小时）、"
            "自动说说=%s（平时 %g~%g 天 / 重要 %g~%g 小时）、判断间隔≈%s 分钟%s",
            self.auto_signature,
            self.sig_min_days,
            self.sig_max_days,
            self.sig_crit_min_h,
            self.sig_crit_max_h,
            self.auto_post,
            self.post_min_days,
            self.post_max_days,
            self.post_crit_min_h,
            self.post_crit_max_h,
            self.judge_minutes,
            "（间隔 ±%d%% 浮动%s）" % (int(self.judge_jitter * 100), "，仅新聊天触发" if self.judge_only_on_new else ""),
        )
        if self.read_plugin_state:
            try:
                srcs = [p.name for p in self._state_dirs()]
                logger.info("[QzoneKit] 状态来源：%s", "、".join(srcs) or "（没找到）")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[QzoneKit] 状态来源探测失败：%s", exc)
        if self.auto_post:
            self._sync_daily_time()
            logger.info(
                "[QzoneKit] 每天 %s 那条总结：攒着的那批避开前后 %.1f 小时（撞了就重抽）；"
                "现在就发的只避 %.0f 分钟（撞上挪 %.0f 分钟）",
                self._daily_hm_text(),
                self.avoid_hours,
                self.instant_guard_min,
                self.instant_push_min,
            )
        # 数据边界：一眼能看到「读了谁、写不写别人配置」
        logger.info(
            "[QzoneKit] 数据边界：只读其它插件状态=%s（文件名白名单，全量扫描=%s）｜"
            "写回 QQ空间 配置=%s（daily_post_sync_qzone）",
            self.read_plugin_state,
            self.state_read_all_files,
            self.sync_qzone_schedule,
        )
        try:
            logger.info("[QzoneKit] 依赖检查：%s", "；".join(self._partner_report()))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QzoneKit] 依赖检查失败：%s", exc)
        logger.info(
            "[QzoneKit] 开关：每天自动发说说=%s｜自动改签名=%s｜自动发说说=%s｜配图=%s(%.0f%%)",
            self.daily_post,
            self.auto_signature,
            self.auto_post,
            self.sticker_enabled,
            self.sticker_prob * 100,
        )
        if self.dry_run:
            logger.warning("[QzoneKit] 当前是**试运行**：只判断、只记日志，不会真的改签名/发说说")
        else:
            logger.info(
                "[QzoneKit] 真发模式；表情包=%s；一次性强制发=%s",
                self.sticker_enabled,
                self.force_post_once,
            )

    async def terminate(self) -> None:
        for task in (self._task, self._flush_task):
            if task and not task.done():
                task.cancel()

    # ── 依赖：别的插件 / OneBot 接口 ──────────────────────────────────────
    def _star(self, name: str) -> Any | None:
        try:
            meta = self.context.get_registered_star(name)
            return getattr(meta, "star_cls", None) if meta else None
        except Exception:  # noqa: BLE001
            return None

    async def _call_api(self, action: str, **kwargs: Any) -> Any:
        """调 OneBot 接口：优先用 QQ空间插件那个 client，其次平台实例，最后给个明白的错。"""

        qz = self._star(QZONE_PLUGIN)
        cfg = getattr(qz, "cfg", None)
        if cfg is not None:
            try:
                ensure = getattr(cfg, "ensure_client", None)
                if callable(ensure):
                    ensure()
            except Exception:  # noqa: BLE001
                pass
            client = getattr(cfg, "client", None)
            api = getattr(client, "api", None) or client
            if api is not None and hasattr(api, "call_action"):
                return await api.call_action(action, **kwargs)

        try:
            for inst in self.context.platform_manager.platform_insts:
                bot = getattr(inst, "bot", None) or getattr(inst, "api", None)
                if bot is not None and hasattr(bot, "call_action"):
                    return await bot.call_action(action, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QzoneKit] 平台实例取不到：%s", exc)
        raise RuntimeError("找不到可用的 OneBot 接口。" + self._partner_fail_hint())

    # 依赖插件：名字 → (需要的能力属性, 本插件测试过的版本)
    PARTNER_SPECS = {
        QZONE_PLUGIN: {"attrs": ("service", "cfg"), "tested": ">=1.0"},
        QQPROFILE_STATUS: {"attrs": (), "tested": ">=1.1"},
    }

    def _plugin_version(self, name: str) -> str:
        try:
            meta = Path(__file__).resolve().parent.parent / name / "metadata.yaml"
            if not meta.is_file():
                return ""
            for line in meta.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("version:"):
                    return line.split(":", 1)[1].strip().strip('"')
        except Exception:  # noqa: BLE001
            pass
        return ""

    def _partner_report(self) -> list[str]:
        """检查依赖插件：在不在、什么版本、必需属性有没有。"""

        rows: list[str] = []
        for name, spec in self.PARTNER_SPECS.items():
            inst = self._star(name)
            version = self._plugin_version(name) or "未知"
            if inst is None:
                rows.append(f"{name}=缺失")
                continue
            missing = [a for a in spec["attrs"] if not hasattr(inst, a)]
            if missing:
                rows.append(f"{name}={version}（缺 {','.join(missing)}，可能版本不兼容）")
            else:
                rows.append(f"{name}={version}")
        return rows

    def _partner_fail_hint(self) -> str:
        try:
            return "依赖状态：" + "；".join(self._partner_report())
        except Exception:  # noqa: BLE001
            return "依赖状态：取不到"

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        ok = self._is_owner_raw(event)
        if not ok:
            try:
                logger.warning(
                    "[QzoneKit] 拒绝对该用户执行（sender=%s require_admin=%s owner_uids=%s）",
                    event.get_sender_id() if hasattr(event, "get_sender_id") else "?",
                    getattr(self, "require_admin", None), self.owner_uids,
                )
            except Exception:  # noqa: BLE001
                pass
        return ok

    def _is_owner_raw(self, event: AstrMessageEvent) -> bool:
        if not self.owner_uids:
            return True
        sender = str(getattr(event, "get_sender_id", lambda: "")() or "")
        try:
            if sender and bool(event.is_admin()):
                return True
        except Exception:  # noqa: BLE001
            pass
        return sender in self.owner_uids

    @staticmethod
    def _status_mapping() -> dict[str, tuple[int, int]]:
        fallback = {
            "在线": (10, 0),
            "离开": (30, 0),
            "隐身": (40, 0),
            "忙碌": (50, 0),
            "请勿打扰": (70, 0),
            "听歌中": (10, 1028),
            "学习中": (10, 1018),
            "摸鱼中": (10, 1300),
            "睡觉中": (10, 1066),
            "emo中": (10, 1401),
        }
        try:
            base = Path(__file__).resolve().parent.parent / QQPROFILE_STATUS / "status.py"
            if not base.exists():
                return fallback
            # 只解析文本，不执行第三方模块代码
            text = base.read_text(encoding="utf-8", errors="ignore")
            pairs = re.findall(
                r'"([^"\n]{1,16})"\s*:\s*\(\s*(-?\d+)\s*,\s*(-?\d+)\s*\)', text)
            mapping = {name: (int(a), int(b)) for name, a, b in pairs}
            if mapping:
                return mapping
            logger.warning("[QzoneKit] qqprofile 状态表解析为空，用内置的")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QzoneKit] 读状态表失败，用内置的：%s", exc)
        return fallback

    # ── 工具 1：删说说 ────────────────────────────────────────────────────
    @filter.llm_tool(name="qzone_delete_feeds")
    async def qzone_delete_feeds(
        self, event: AstrMessageEvent, pos: int = 0, date_text: str = ""
    ) -> str:
        """删除自己 QQ 空间里的说说。两种用法二选一：

        - 按条数删一条：`pos=1` 删最新那条，`pos=2` 删第二条（按发布时间**由近到远**数）
        - 按日期整批删：`date_text` 填「今天 / 昨天 / 前天 / 大前天 / 2026-11-03 / 11-03 / 11月3日」

        使用者说「删第几条」「把昨天的说说都删了」「删掉前天的」时调用。
        这个工具**真的会删**；他只是问「有几条」时不要调（那种用 qzone_view_feed）。

        Args:
            pos(number): 删第几条（1 = 最新）。按日期删时留 0。
            date_text(string): 删哪一天的全部说说。按条数删时留空。
        """

        if not self._is_owner(event):
            return "只有管理员能删说说"

        qz = self._star(QZONE_PLUGIN)
        service = getattr(qz, "service", None) if qz else None
        if service is None:
            return "删不了：没装/没启用「QQ空间」插件（astrbot_plugin_qzone）"

        day = parse_target_day(date_text)
        if date_text and day is None:
            return f"「{date_text}」这个日期没看懂，写成 今天/昨天/前天/2026-11-03 这种"
        if not pos and not day:
            return "要说清楚删哪条：删第几条（1 = 最新），或者删哪天的（今天/昨天/前天/具体日期）"

        posts: list[Any] = []
        try:
            self_id = event.get_self_id()
            for start in (0, 20, 40, 60, 80):
                batch = await service.query_feeds(target_id=self_id, pos=start, num=20)
                if not batch:
                    break
                posts.extend(batch)
                if len(batch) < 20:
                    break
        except Exception as exc:  # noqa: BLE001
            logger.error("[QzoneKit] 取说说失败：%s", exc)
            return f"取说说列表失败：{exc}"

        posts.sort(key=lambda p: getattr(p, "create_time", 0), reverse=True)
        if not posts:
            return "空间里没取到说说（Cookie 可能过期了）"

        if pos:
            if pos < 1 or pos > len(posts):
                return f"没有第 {pos} 条（现在一共取到 {len(posts)} 条）"
            targets = [posts[pos - 1]]
        else:
            targets = [p for p in posts if ts_to_day(getattr(p, "create_time", 0)) == day]
            if not targets:
                return f"{day:%Y-%m-%d} 那天没有说说"

        deleted, failed = 0, []
        for post in targets:
            try:
                await service.delete_post(post)
                deleted += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("[QzoneKit] 删说说失败：%s", exc)
                text = str(getattr(post, "text", "") or "")[:12]
                failed.append(f"{text}…：{exc}")

        head = f"删了第 {pos} 条" if pos else f"删了 {day:%Y-%m-%d} 的 {deleted} 条"
        if failed:
            return f"{head}；其中 {len(failed)} 条失败：" + "；".join(failed[:3])
        return head

    # ── 工具 2：改资料 ────────────────────────────────────────────────────
    @filter.llm_tool(name="qq_profile_update")
    async def qq_profile_update(
        self, event: AstrMessageEvent, field: str, value: str = ""
    ) -> str:
        """修改机器人自己的 QQ 资料（昵称 / 签名 / 在线状态 / 头像）。

        使用者明确要求「把昵称改成 X」「签名换成 Y」「状态改成摸鱼中」「头像换成这张图」时调用。
        ⚠️ 如果只是她自己「想改签名」，用 `qq_signature_maybe_change`（那个受冷却管着）。

        Args:
            field(string): 只能是 nickname / signature / status / avatar 之一
            value(string): 昵称/签名是新的文字；status 是状态名；avatar 是图片链接或本地路径（留空则用消息里的图）
        """

        if not self._is_owner(event):
            return "只有管理员能改机器人的资料"

        field = (field or "").strip().lower()
        bot = getattr(event, "bot", None)

        try:
            if field in {"nickname", "nick"}:
                if not value.strip():
                    return "要改成什么昵称？"
                await bot.set_qq_profile(nickname=value.strip())
                return f"昵称改成「{value.strip()}」了"

            if field in {"signature", "longnick", "sign"}:
                if not value.strip():
                    return "要改成什么签名？"
                await bot.set_self_longnick(longNick=value.strip())
                self._mark_signature(value.strip(), "manual")
                return f"签名换成「{value.strip()}」了"

            if field in {"status", "在线状态"}:
                name = value.strip()
                mapping = self._status_mapping()
                if name not in mapping:
                    return (
                        f"没有「{name}」这个状态。能用的有："
                        + "、".join(list(mapping)[:20])
                        + "……"
                    )
                status, ext = mapping[name]
                await bot.set_online_status(
                    status=status, ext_status=ext, battery_status=0
                )
                return f"状态改成「{name}」了"

            if field in {"avatar", "头像"}:
                url = value.strip()
                if not url:
                    for comp in event.get_messages():
                        if type(comp).__name__ == "Image":
                            url = str(getattr(comp, "url", "") or "")
                            break
                        if type(comp).__name__ == "Reply":
                            for inner in getattr(comp, "chain", []) or []:
                                if type(inner).__name__ == "Image":
                                    url = str(getattr(inner, "url", "") or "")
                                    break
                        if url:
                            break
                if not url:
                    return "要换头像得给我一张图（直接发图，或者给图片链接）"
                await bot.set_qq_avatar(file=url)
                return "头像换好了"

            return "field 只能是 nickname / signature / status / avatar"
        except Exception as exc:  # noqa: BLE001
            logger.error("[QzoneKit] 改资料失败：%s", exc)
            return f"改失败了：{exc}"

    # ── 工具 3：手动发一条总结 ────────────────────────────────────────────
    @filter.llm_tool(name="qzone_post_summary")
    async def qzone_post_summary(self, event: AstrMessageEvent) -> str:
        """立刻在 QQ 空间发一条「今天的总结」——走 QQ空间插件写稿那套逻辑
        （读今天的聊天记录，抽好友/群里的素材，没素材就让它自己写）。

        使用者说「现在就发一条说说」「发个今天的总结」时调用。
        每天 23 点那条是 QQ空间插件自己在发，这个工具是**手动补一条**，别连着用两次。

        Args:
            无（不需要参数）
        """

        if not self._is_owner(event):
            return "只有管理员能让她发说说"

        qz = self._star(QZONE_PLUGIN)
        if qz is None:
            return "发不了：没装/没启用「QQ空间」插件（astrbot_plugin_qzone）"

        publisher = getattr(qz, "auto_publish", None)
        if publisher is None:
            return "QQ空间插件没开自动发说说（AutoPublish），先去它的设置里把开关打开"

        try:
            ok = await publisher.do_task()
        except Exception as exc:  # noqa: BLE001
            logger.error("[QzoneKit] 手动发总结失败：%s", exc)
            return f"发失败了：{exc}"
        if ok:
            self._mark_post("manual")
            return "发了，去空间看看"
        return "没发出去（素材或接口出问题了，看日志）"

    # ── 工具 4：想改签名（受冷却管） ──────────────────────────────────────
    @filter.llm_tool(name="qq_signature_maybe_change")
    async def qq_signature_maybe_change(
        self,
        event: AstrMessageEvent,
        new_signature: str,
        importance: str = "normal",
        reason: str = "",
    ) -> str:
        """她「想换签名」时调用——不是替老大改，而是表达自己的状态变化。

        什么时候想换：心情明显变了、有了新目标、碰到特别在意的事、兴趣换了。
        平时很稳定，别动不动就换。插件会按冷却决定**现在就换**还是**记下来到点再换**。

        Args:
            new_signature(string): 新的签名正文，12~24 字，可以带一点她的口癖
            importance(string): normal / important / critical（非常重要才允许把冷却缩到 24 小时）
            reason(string): 一句话说明为什么想换（只记日志，不发出去）
        """

        if not self._is_owner(event):
            return "只有管理员能让它改签名"
        text = (new_signature or "").strip().strip("\"'“”")
        if not text:
            return "没给新签名内容"
        verdict = await self._apply_signature(text, importance, reason or "自己想的")
        return verdict

    # ── 工具 5：想发说说（受冷却 + 攒批） ────────────────────────────────
    KIND_PROMPTS = {
        "weekly": "写一条本周回顾式的说说：把最近的事、心情、做过的事串起来，有具体的事和自己的感受，别写成流水账。140~260 字。",
        "chat": "写一条从最近聊天取材的说说：挑最有意思或最有情绪的一两件事，第一人称，带点吐槽。80~180 字。",
        "video": "写一条记录最近刷到的视频的说说：聊天里提到过就写那个，没提到就写今天刷到的东西和感想。80~180 字。",
        "diary": "写一条日记式的说说：今天过得怎么样、做了什么、有什么小心思。80~200 字。",
        "mood": "写一条最近状况与心情的说说：最近状态（睡眠/精力/情绪/关系）怎么样、心情如何，像真人吐槽。80~180 字。",
        "auto": "根据材料写一条适合发 QQ 空间的说说，具体、有她自己的语气。80~200 字。",
    }

    def _kind_from_text(self, text: str) -> str:
        low = str(text or "").lower()
        if any(k in low for k in ("周记", "周总结", "本周", "这周")):
            return "weekly"
        if any(k in low for k in ("心情", "状态", "状况")):
            return "mood"
        if any(k in low for k in ("聊天", "聊到", "对话")):
            return "chat"
        if any(k in low for k in ("视频", "刷到", "看到")):
            return "video"
        if any(k in low for k in ("日记", "记录", "今天")):
            return "diary"
        return "auto"

    @filter.llm_tool(name="qzone_post_on_demand")
    async def qzone_post_on_demand(
        self, event: AstrMessageEvent, kind: str = "", extra: str = ""
    ) -> str:
        """老大点名让她发某类 QQ 空间说说时调用（立即发，不受冷却限制）。

        适用：「发个周记」「发一条最近聊天的说说」「记录一下最近刷到的视频」「发条日记」「发一条最近状态/心情」。

        Args:
            kind(string): weekly 周记 / chat 最近聊天 / video 刷到的视频 / diary 日记 / mood 最近状况与心情 / auto；也可填原话
            extra(string): 补充要求，没有就留空
        """

        if not self._is_owner(event):
            return "只有管理员能让她发说说"
        k = str(kind or "").strip().lower()
        if k not in self.KIND_PROMPTS:
            k = self._kind_from_text(f"{kind} {extra}")
        try:
            material = await self._recent_block()
            state = await self._state_block()
            now_block = self._now_block()
        except Exception:  # noqa: BLE001
            material, state = "（没拿到聊天）", "（没拿到状态）"
            now_block = ""
        prompt = (
            self.KIND_PROMPTS[k]
            + ("\n额外要求：" + extra.strip() if extra.strip() else "")
            + "\n只输出正文，不要标题/引号/解释。\n\n【她的状态】\n" + state
            + f"\n\n【现在时间】{now_block}\n\n【最近聊天】\n" + material
        )
        try:
            body = (await self._llm(prompt)).strip()
        except Exception as exc:  # noqa: BLE001
            logger.error("[QzoneKit] 按类型生成失败：%s", exc)
            return f"没写成，生成出错了：{exc}"
        if not body:
            return "没写成，模型没给正文"
        sticker = self._guess_category(body)
        result = await self._apply_post(body, "important", f"老大点名要发（{k}）", sticker, force=True)
        logger.info("[QzoneKit] 按需发说说（%s）：%s", k, body[:40])
        return f"{result}｜类型={k}"

    @filter.llm_tool(name="qzone_mood_post")
    async def qzone_mood_post(
        self,
        event: AstrMessageEvent,
        content: str,
        importance: str = "normal",
        reason: str = "",
        sticker: str = "",
    ) -> str:
        """她「想发一条说说」时调用：发泄、被安慰到、遇到新鲜事/重要事、想记录、
        想找人说说话、有感触——这些时候可以发。日常寒暄不要发。

        插件按冷却决定：现在就发 / 先攒着，等冷却好了合成一条发；
        非常重要（critical）可以把冷却缩到 24 小时。攒着的时候如果又来新的，
        会**合并**（不是覆盖），攒够或到点一起发。

        Args:
            content(string): 说说正文，1~3 句、口语、写具体发生了什么
            importance(string): normal / important / critical
            reason(string): 一句话说明为什么想发（只记日志）
            sticker(string): 可选分类：happy/angry/sad/confused/surprised/shy/sleep/affection/
                food/money/greeting/work/entertainment/teasing/reply；没有合适的就留空
        """

        if not self._is_owner(event):
            return "只有管理员能让它发说说"
        text = (content or "").strip()
        if not text:
            return "没给内容"
        return await self._apply_post(
            text, importance, reason or "自己想的", (sticker or "").strip()
        )

    # ── 表情包（可选，需要使用者同意才会启用） ────────────────────────────
    def _sticker_roots(self) -> list[Path]:
        """meme_manager 的图包目录（只读）。路径全从插件自身位置推导，不写死本机路径。"""

        plugins_dir = Path(__file__).resolve().parent.parent  # <AstrBot>/data/plugins
        data_dir = plugins_dir.parent                          # <AstrBot>/data
        bases = [
            data_dir / "plugin_data" / "meme_manager" / "packs",
            plugins_dir / "meme_manager" / "packs",
            data_dir / "plugins" / "meme_manager" / "packs",
        ]
        return [b for b in bases if b.is_dir()]

    STICKER_EXTS = (".gif", ".png", ".jpg", ".jpeg", ".webp", ".bmp")
    STICKER_HINTS = {
        "happy": ("开心", "高兴", "笑", "棒", "好耶", "成了", "搞定"),
        "angry": ("生气", "烦", "气死", "崩了", "讨厌"),
        "sad": ("难过", "委屈", "累", "想哭", "低落", "emo"),
        "sleep": ("困", "睡", "熬夜", "躺"),
        "food": ("吃", "饭", "奶茶", "饿", "馋", "夜宵"),
        "shy": ("害羞", "脸红", "心虚"),
        "confused": ("迷惑", "不懂", "为什么", "问号"),
        "surprised": ("惊讶", "没想到", "吓"),
        "work": ("干活", "工作", "代码", "调试", "加班", "摸鱼"),
        "affection": ("喜欢", "贴贴", "抱", "谢谢", "温柔"),
    }

    def _guess_category(self, text: str) -> str:
        low = str(text or "").lower()
        for cat, words in self.STICKER_HINTS.items():
            if any(w in low for w in words):
                return cat
        return ""

    def _sticker_index(self) -> dict:
        index: dict = {}
        for root in self._sticker_roots():
            for memes in root.glob("*/memes"):
                if not memes.is_dir():
                    continue
                for cat_dir in memes.iterdir():
                    if not cat_dir.is_dir():
                        continue
                    files = [f for f in cat_dir.iterdir()
                             if f.is_file() and f.suffix.lower() in self.STICKER_EXTS]
                    if files:
                        index.setdefault(cat_dir.name.strip().lower(), []).extend(files)
        return index

    def _prepare_image(self, src: Path) -> str:
        """表情包预处理。

        GIF 动图**原样发**，多大都不转静态：实测 QQ 空间的 cgi_upload_image 收 GIF 会保留动画
        （发出去的图抓回来还是 GIF89a、帧数不变）。真上传失败了也不是大事——
        `_publish` 会退回纯文字再发一次，不会丢说说。
        其它格式（webp/bmp）仍旧转成 JPEG，兜住上传接口。
        """

        if src.suffix.lower() == ".gif" and self.sticker_keep_gif:
            return str(src)
        return self._to_jpeg(src)

    def _to_jpeg(self, src: Path) -> str:
        if src.suffix.lower() in (".jpg", ".jpeg"):
            return str(src)
        try:
            from PIL import Image
            out = Path(self.data_dir) / "sticker_tmp.jpg"
            with Image.open(src) as im:
                im.seek(0)
                frame = im.convert("RGB")
                w, h = frame.size
                scale = min(1.0, 1080 / max(w, h))
                if scale < 1.0:
                    frame = frame.resize((int(w * scale), int(h * scale)))
                frame.save(out, "JPEG", quality=88)
            return str(out)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QzoneKit] 转 JPEG 失败，用原图：%s（%s）", src, exc)
            return str(src)

    def _pick_sticker(self, category: str) -> str:
        """从**所有**表情包图包里挑一张；挑不到就返回空串。"""

        if not self.sticker_enabled:
            return ""
        if random.random() > self.sticker_prob:
            return ""

        index = self._sticker_index()
        if not index:
            logger.info("[QzoneKit] 没找到任何表情包图包（meme_manager 没装或没有图包）")
            return ""
        cat = str(category or "").strip().lower()
        files = index.get(cat) or []
        if not files:
            # 分类不存在（不同图包分类不一样）⇒ 从所有图包里随便挑一张
            files = [f for fs in index.values() for f in fs]
            logger.info("[QzoneKit] 没有「%s」分类，从全部 %s 张里随机挑", cat or "（空）", len(files))
        if not files:
            return ""
        return self._prepare_image(random.choice(files))

    # ── 签名：冷却 + 待换队列（新的覆盖旧的） ─────────────────────────────
    def _sig_last_ts(self) -> float:
        return float(self.state.get("signature", {}).get("last_at") or 0)

    def _mark_signature(self, text: str, source: str) -> None:
        sig = self.state.setdefault("signature", {})
        sig["last_at"] = time.time()
        sig["last_text"] = text
        sig["source"] = source
        sig.pop("pending", None)
        self._save_state()

    @staticmethod
    def _level_rank(level: str) -> int:
        return {"normal": 0, "important": 1, "critical": 2}.get(
            (level or "normal").strip().lower(), 0
        )

    @staticmethod
    def _span(lo: float, hi: float, unit: float) -> float:
        """在 [lo, hi] 这个区间里随机取一个时长（单位 = unit 秒）。

        为什么不写死一个数：冷却永远是整 24 小时 / 整 7 天，一眼就是定时任务。
        这里直接给区间——例如 22~29.2 小时——每次落在哪儿不一样，才像活人。
        """

        lo_s = max(0.0, lo) * unit
        hi_s = max(lo, hi) * unit
        return random.uniform(lo_s, hi_s) if hi_s > lo_s else lo_s

    def _sig_cooldown(self, level: str) -> float:
        if self._level_rank(level) >= 2:  # critical
            return self._span(self.sig_crit_min_h, self.sig_crit_max_h, 3600.0)
        return self._span(self.sig_min_days, self.sig_max_days, 86400.0)

    async def _apply_signature(
        self, text: str, importance: str, reason: str, force: bool = False
    ) -> str:
        now = time.time()
        last = self._sig_last_ts()
        need = self._sig_cooldown(importance)
        left = 0 if force else (need - (now - last) if last else 0)

        if left <= 0:
            if self.dry_run:
                logger.info(
                    "[QzoneKit][试运行] 本来要改签名 → 「%s」（%s，%s）",
                    text,
                    importance,
                    reason,
                )
                return f"[试运行] 本来要改签名：「{text}」"
            try:
                await self._call_api("set_self_longnick", longNick=text)
            except Exception as exc:  # noqa: BLE001
                logger.error("[QzoneKit] 改签名失败：%s", exc)
                return f"改签名没成功：{exc}"
            self._mark_signature(text, f"auto:{importance}({reason})")
            logger.info("[QzoneKit] 签名已改：%s（%s，%s）", text, importance, reason)
            return f"签名换了：「{text}」"

        # 冷却没过 ⇒ 记下来（新的覆盖旧的；重要程度取高的）
        sig = self.state.setdefault("signature", {})
        old = sig.get("pending") or {}
        keep_rank = max(self._level_rank(importance), self._level_rank(old.get("importance", "")))
        level = {0: "normal", 1: "important", 2: "critical"}[keep_rank]
        # 到点时间只定一次：已经排着队、且新这条不更「重要」⇒ 沿用原来的 due；
        # 否则按这一档的冷却重新排（这样随机浮动不会把队列一直往后推）
        old_pending = sig.get("pending") or {}
        old_due = float(old_pending.get("due") or 0)
        old_rank = self._level_rank(old_pending.get("importance", ""))
        if old_pending and old_due > 0 and self._level_rank(level) <= old_rank:
            due = old_due
        else:
            due = last + (need if level == importance else self._sig_cooldown(level)) if last else now
        sig["pending"] = {
            "text": text,
            "importance": level,
            "reason": reason,
            "at": now,
            "due": due,
        }
        self._save_state()
        hours = left / 3600.0
        logger.info(
            "[QzoneKit] 签名先记着（还要 %.1f 小时）：%s → %s", hours, text, reason
        )
        return (
            f"先记着了（冷却还有 {hours:.0f} 小时左右），到点我换。"
            f"到时候如果有人给了新的，我就用新的。"
        )

    # ── 说说：冷却 + 攒批（合并不是覆盖） ─────────────────────────────────
    def _post_last_ts(self) -> float:
        return float(self.state.get("post", {}).get("last_at") or 0)

    def _mark_post(self, source: str) -> None:
        post = self.state.setdefault("post", {})
        post["last_at"] = time.time()
        post["source"] = source
        post.pop("pending", None)
        post.pop("pending_due", None)  # 发完就把到点时间清掉，别让下一批拿旧时间立刻发
        self._save_state()

    def _post_cooldown(self, level: str) -> float:
        if self._level_rank(level) >= 2:
            return self._span(self.post_crit_min_h, self.post_crit_max_h, 3600.0)
        return self._span(self.post_min_days, self.post_max_days, 86400.0)

    # ── 躲开「每天那条总结」的时间窗 ─────────────────────────────────────
    @staticmethod
    def _parse_hm(text: str) -> tuple[int, int] | None:
        m = re.match(r"^(\d{1,2})\s*[:：]\s*(\d{1,2})", str(text or "").strip())
        if not m:
            return None
        hour, minute = int(m.group(1)), int(m.group(2))
        if 0 <= hour < 24 and 0 <= minute < 60:
            return hour, minute
        return None

    @staticmethod
    def _cron_hm(cron: str) -> tuple[int, int] | None:
        """只认最简单的「分 时 * * *」；复杂的（每 N 小时之类）返回 None。"""

        parts = str(cron or "").strip().split()
        if len(parts) != 5 or parts[2:] != ["*", "*", "*"]:
            return None
        try:
            hour, minute = int(parts[1]), int(parts[0])
        except ValueError:
            return None
        if 0 <= hour < 24 and 0 <= minute < 60:
            return hour, minute
        return None

    def _qzone_cron(self) -> str:
        """QQ空间插件配置里的 publish_cron 原文。"""

        try:
            cfg_file = (
                self.data_dir.parent.parent
                / "config"
                / "astrbot_plugin_qzone_config.json"
            )
            trigger = json.loads(
                cfg_file.read_text(encoding="utf-8-sig")  # AstrBot 存的配置可能带 BOM
            ).get("trigger") or {}
            return str(trigger.get("publish_cron") or "").strip()
        except Exception:  # noqa: BLE001
            return ""

    def _qzone_cron_hm(self) -> tuple[int, int] | None:
        return self._cron_hm(self._qzone_cron())

    def _daily_hm(self) -> tuple[int, int]:
        """每天那条总结几点发：**每次都现算**，别人改了时间这边立刻跟上。

        优先级：本插件配置 `daily_post_time` > QQ空间插件的 `publish_cron` > 23:00。
        """

        hm = self._parse_hm(self.daily_post_time)
        if hm:
            return hm
        return self._qzone_cron_hm() or (23, 0)

    def _daily_hm_text(self) -> str:
        return "%02d:%02d" % self._daily_hm()

    def _in_avoid_window(self, ts: float) -> bool:
        """ts 是不是落在「每天总结」前后 avoid_hours 小时里。"""

        if self.avoid_hours <= 0:
            return False
        t = datetime.fromtimestamp(ts)
        cur = t.hour * 60 + t.minute + t.second / 60.0
        hm = self._daily_hm()
        tgt = hm[0] * 60 + hm[1]
        diff = abs(cur - tgt)
        diff = min(diff, 1440.0 - diff)  # 跨零点按环形算
        return diff <= self.avoid_hours * 60.0

    def _window_exit(self, ts: float) -> float:
        """落在每天总结的时间窗里时，返回「这个窗口结束」的时间（+ 一点随机）。"""

        hm = self._daily_hm()
        span = timedelta(minutes=self.avoid_hours * 60)
        d = datetime.fromtimestamp(ts)
        anchor = d.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
        exits = []
        for day in (-1, 0, 1):
            a = anchor + timedelta(days=day)
            end = a + span
            if a - span <= d < end:  # d 在这个窗口里
                exits.append(end)
        if not exits:
            return ts
        end = min(exits)
        return end.timestamp() + random.uniform(60, 25 * 60)

    def _near_summary(self, ts: float, minutes: float) -> bool:
        """ts 是不是离「每天总结」不到 minutes 分钟（立刻想发时用）。"""

        if minutes <= 0:
            return False
        t = datetime.fromtimestamp(ts)
        cur = t.hour * 60 + t.minute + t.second / 60.0
        hm = self._daily_hm()
        tgt = hm[0] * 60 + hm[1]
        diff = abs(cur - tgt)
        diff = min(diff, 1440.0 - diff)
        return diff <= minutes

    def _instant_due(self, now: float) -> float:
        """现在就想发、但贴着总结：往后挪半小时，直到离开那 15 分钟。"""

        due = now
        for _ in range(48):
            if not self._near_summary(due, self.instant_guard_min):
                return due
            due += self.instant_push_min * 60.0
        return due + 3600.0

    def _avoid_window(self, ts: float) -> float:
        """现在就要发、但正撞窗口：没别的时间可选，只能等这个窗口过去。"""

        return ts if not self._in_avoid_window(ts) else self._window_exit(ts)

    def _roll_queued_time(self, last: float, level: str) -> float:
        """给「攒着的那批」抽一个到点时间：撞上总结窗口就重新抽，直到不撞。

        冷却本来就是随机区间，重抽一个就行——不用往后推几个小时。
        """

        due = last + self._post_cooldown(level)
        for _ in range(60):
            if not self._in_avoid_window(due):
                return due
            logger.debug(
                "[QzoneKit] 抽到的到点时间 %s 撞上每天总结，重新抽",
                self._fmt_ts(due),
            )
            due = last + self._post_cooldown(level)
        return self._window_exit(due)

    def _fresh_fragments(self, fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """丢掉攒太久的碎片（默认 >5 天就不发了）。"""

        if self.max_age_days <= 0:
            return list(fragments)
        cutoff = time.time() - self.max_age_days * 86400.0
        fresh, stale = [], 0
        for item in fragments:
            at = float(item.get("at") or 0)
            if at and at < cutoff:
                stale += 1
                continue
            fresh.append(item)
        if stale:
            logger.info(
                "[QzoneKit] 有 %s 段攒超过 %g 天了，这次不发（内容过期了）",
                stale,
                self.max_age_days,
            )
        return fresh

    # ── 把「每天总结几点」同步给 QQ空间插件 ─────────────────────────────
    def _desired_cron(self) -> str | None:
        """配置了 daily_post_time 才由这边说了算；留空就完全跟着 QQ空间插件。"""

        hm = self._parse_hm(self.daily_post_time)
        if not hm:
            return None
        return f"{hm[1]} {hm[0]} * * *"

    def _apply_cron_to_qzone(self, cron: str) -> bool:
        """让 QQ空间插件的 AutoPublish 现在就按新的时间跑（不重启）。"""

        qz = self._star(QZONE_PLUGIN)
        publisher = getattr(qz, "auto_publish", None) if qz else None
        if publisher is None or getattr(publisher, "_terminated", False):
            return False
        if str(getattr(publisher, "cron_expr", "") or "") == cron:
            return True
        try:
            publisher.cron_expr = cron
            publisher.scheduler.remove_all_jobs()
            publisher._register_task()
            logger.info("[QzoneKit] 每天总结的时间改成 %s（已让 QQ空间插件重新排期）", cron)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[QzoneKit] 改每天总结的时间失败（%s），可以自己去 QQ空间 插件里改 publish_cron",
                exc,
            )
            return False

    def _persist_cron(self, cron: str) -> None:
        """顺手写回 QQ空间插件的配置文件，重启后也还是这个点。"""

        try:
            cfg_file = (
                self.data_dir.parent.parent
                / "config"
                / "astrbot_plugin_qzone_config.json"
            )
            data = json.loads(cfg_file.read_text(encoding="utf-8-sig"))
            trigger = data.setdefault("trigger", {})
            if str(trigger.get("publish_cron") or "") == cron:
                return
            trigger["publish_cron"] = cron
            cfg_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info("[QzoneKit] 已把 QQ空间插件配置里的 publish_cron 写成 %s", cron)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QzoneKit] 写 QQ空间插件配置失败：%s", exc)

    def _sync_daily_time(self) -> None:
        """开机、以及每轮检查时对一次表：时间变了，时间窗也就跟着变。"""

        hm_text = self._daily_hm_text()
        if getattr(self, "_daily_hm_seen", None) != hm_text:
            self._daily_hm_seen = hm_text
            logger.info(
                "[QzoneKit] 每天总结的时间：%s（时间窗 ±%.1f 小时会跟着它走）",
                hm_text,
                self.avoid_hours,
            )

        if not self.sync_qzone_schedule:
            # 用户关掉了：只读时间，不写 QQ空间 的配置、也不动它的排期
            self._cron_applied = None
            return

        desired = self._desired_cron()
        if not desired:
            self._cron_applied = None
            return
        current = self._qzone_cron()
        applied = getattr(self, "_cron_applied", None)

        # 别人在 QQ空间 插件那边把时间改了 ⇒ 以那边为准，这边跟着改（别把人的设置按回去）
        if applied and current and current not in (applied, desired):
            hm = self._cron_hm(current)
            if hm:
                self.daily_post_time = "%02d:%02d" % hm
                self._daily_hm_seen = self.daily_post_time
                self._write_config_value("daily_post_time", self.daily_post_time)
                self._cron_applied = current
                logger.info(
                    "[QzoneKit] QQ空间 那边把每天总结改成了 %s，这边跟着改过来",
                    self.daily_post_time,
                )
                return

        if current != desired and self._apply_cron_to_qzone(desired):
            self._persist_cron(desired)
            current = desired
        self._cron_applied = current or desired

    def _write_config_value(self, key: str, value: Any) -> None:
        """把自己这份配置的某个值写回文件（本插件不重启也能读新值）。"""

        try:
            cfg_file = (
                self.data_dir.parent.parent
                / "config"
                / "astrbot_plugin_qzone_kit_config.json"
            )
            data = json.loads(cfg_file.read_text(encoding="utf-8-sig"))
            if data.get(key) == value:
                return
            data[key] = value
            cfg_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QzoneKit] 写配置 %s 失败：%s", key, exc)


    async def _diagnose_images(self, service: Any, text: str, images: list[str]) -> None:
        """配图失败时把中间过程打出来：上传返回了什么、带图发布返回了什么。"""

        import sys

        try:
            qz = self._star(QZONE_PLUGIN)
            qzone_api = getattr(qz, "qzone", None) or getattr(
                getattr(qz, "service", None), "qzone", None
            )
            if qzone_api is None:
                logger.warning("[QzoneKit][诊断] 拿不到 QZone 接口对象")
                return

            # ① 先看图片规范化后是什么样
            try:
                from data.plugins.astrbot_plugin_qzone.core.qzone.utils import (
                    normalize_images,
                )
            except Exception:  # noqa: BLE001
                normalize_images = None

            if normalize_images is not None:
                try:
                    blobs = await normalize_images(images)
                    logger.warning(
                        "[QzoneKit][诊断] 规范化后 %s 张图，大小=%s 字节",
                        len(blobs),
                        [len(b) for b in blobs],
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[QzoneKit][诊断] normalize_images 失败：%r", exc)
                    blobs = []
                # ② 单独走一次上传，看返回码
                for idx, blob in enumerate(blobs[:1]):
                    try:
                        resp = await qzone_api._upload_image(blob)
                        logger.warning(
                            "[QzoneKit][诊断] 上传第 %s 张：ok=%s code=%s data=%r",
                            idx + 1,
                            getattr(resp, "ok", None),
                            getattr(resp, "code", None),
                            str(getattr(resp, "data", None))[:400],
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[QzoneKit][诊断] 上传抛异常：%r", exc)

            # ③ 用插件的 Post 类直接构造一条带图的，看创建响应
            Post = None
            for modname in (
                "data.plugins.astrbot_plugin_qzone.core.model",
                "data.plugins.astrbot_plugin_qzone.core.qzone.model",
            ):
                mod = sys.modules.get(modname)
                if mod is not None and getattr(mod, "Post", None) is not None:
                    Post = getattr(mod, "Post")
                    break
            if Post is None:
                logger.warning("[QzoneKit][诊断] 没找到 Post 类，跳过创建诊断")
                return
            try:
                uin = await service.session.get_uin()
                name = await service.session.get_nickname()
                post_obj = Post(uin=uin, name=name, text=text, images=images)
                resp = await qzone_api.publish(post_obj)
                logger.warning(
                    "[QzoneKit][诊断] 带图发布：ok=%s code=%s data=%r",
                    getattr(resp, "ok", None),
                    getattr(resp, "code", None),
                    str(getattr(resp, "data", None))[:600],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[QzoneKit][诊断] 带图发布抛异常：%r", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QzoneKit][诊断] 整体失败：%r", exc)

    async def _publish(self, text: str, images: list[str] | None = None) -> tuple[bool, str]:
        qz = self._star(QZONE_PLUGIN)
        service = getattr(qz, "service", None) if qz else None
        if service is None:
            return False, "没装/没启用「QQ空间」插件（astrbot_plugin_qzone）"
        try:
            if images:
                # Post 模型只收字符串路径；盘符路径的坑已在 qzone/utils.py 里打了补丁
                img_paths = [str(x) for x in images if Path(str(x)).is_file()]
                if not img_paths:
                    logger.warning("[QzoneKit] 没有可用的图片文件，改成纯文字发")
                    await service.publish_post(text=text)
                    self._mark_post("auto")
                    return True, ""
                images = img_paths
                try:
                    await service.publish_post(text=text, images=images)
                except Exception as exc:  # noqa: BLE001
                    # QZone 的图片上传接口很脆（返回空响应就会失败），
                    # 别为了配图把整条说说丢掉：退回纯文字再发一次。
                    logger.warning(
                        "[QzoneKit] 带图发布失败（%s），退回纯文字再发一次", exc
                    )
                    await self._diagnose_images(service, text, images)
                    await service.publish_post(text=text)
            else:
                await service.publish_post(text=text)
        except Exception as exc:  # noqa: BLE001
            logger.error("[QzoneKit] 发说说失败：%s", exc)
            return False, str(exc)
        self._mark_post("auto")
        logger.info("[QzoneKit] 说说已发（%s 字）：%s", len(text), text[:60])
        return True, ""

    async def _select_fragments(
        self, fragments: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """攒得太多时先挑：重要的先发，太旧又不重要的不发。

        只有条数 ≥ select_threshold 才会走这里；没超就直接全发。
        """

        if len(fragments) <= self.select_threshold - 1:  # 没「大于三条」就不挑
            return fragments
        low = min(self.publish_min, len(fragments))
        high = min(self.publish_max, len(fragments))          # 她自己决定的上限
        hard = min(self.publish_hard_max, len(fragments))     # 同分才放宽到这里

        now = time.time()
        lines = []
        for i, f in enumerate(fragments):
            age_h = max(0.0, (now - float(f.get("at") or now)) / 3600.0)
            lines.append(
                f"{i}. 距现在 {age_h:.0f} 小时｜重要度={f.get('importance', 'normal')}｜{str(f.get('text') or '')[:60]}"
            )
        prompt = (
            "下面是她攒着想发到 QQ 空间的内容。现在要发车了，但她这次不想全发。\n"
            f"请自己决定发几条（{low}~{high} 条之间，按内容多少来定，写进 count）。\n"
            "**给每一条打 1~10 分**：越重要、越有表达欲、越想让人看到的分越高；"
            "没营养的、过期的、重复的分低。\n"
            "评分要求：分数要拉开，不要全给一样的分（同样分的时候只能按时间截，等于白评）。\n"
            "宁可她这次的表达更完整（多条可以合成一条），也不要留一堆没营养的。\n"
            "只输出 JSON：{\"count\": 想发几条, "
            "\"scores\": [{\"i\": 下标, \"score\": 分数}, ...], \"reason\": \"一句话\"}\n\n"
            + "\n".join(lines)
        )
        try:
            reply = await self._llm(prompt)
            data = self._parse_json(reply) or {}
            scores: dict[int, float] = {}
            raw = data.get("scores")
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        try:
                            scores[int(item.get("i"))] = float(item.get("score"))
                        except (TypeError, ValueError):
                            continue
                    else:  # 兼容旧格式：纯下标列表，当作同分
                        try:
                            scores[int(item)] = 0.0
                        except (TypeError, ValueError):
                            continue
            keep_old = data.get("keep")
            if not scores and isinstance(keep_old, list):
                for x in keep_old:
                    try:
                        scores[int(x)] = 0.0
                    except (TypeError, ValueError):
                        continue

            if scores:
                # 排序：分数高的先；同分 → 新的先
                order = sorted(
                    (i for i in scores if 0 <= i < len(fragments)),
                    key=lambda i: (scores[i], float(fragments[i].get("at") or 0)),
                    reverse=True,
                )
                # 她自己决定发几条（夹在 low~high）
                want = high
                try:
                    want = int(data.get("count") or high)
                except (TypeError, ValueError):
                    want = high
                want = max(low, min(high, want))
                picked = [fragments[i] for i in order[:want]]
                # 只有「第 want 条后面还有同分」才放宽到硬上限 6
                if len(picked) == high and len(order) > high:
                    last_score = scores[order[len(picked) - 1]]
                    while (
                        len(picked) < hard
                        and len(picked) < len(order)
                        and scores[order[len(picked)]] == last_score
                    ):
                        picked.append(fragments[order[len(picked)]])
                        logger.info(
                            "[QzoneKit] 第 %s 条后面有同分（%g），带上了，这次发 %s 条",
                            high, last_score, len(picked),
                        )
                if len(picked) < low:
                    extra = [
                        f for f in sorted(fragments, key=lambda x: float(x.get("at") or 0), reverse=True)
                        if f not in picked
                    ]
                    picked += extra[: low - len(picked)]
                if len(picked) < len(fragments):
                    logger.info(
                        "[QzoneKit] 攒了 %s 条，这次发 %s 条（%s）",
                        len(fragments), len(picked), data.get("reason", ""),
                    )
                else:
                    logger.info("[QzoneKit] 攒了 %s 条，全发", len(fragments))
                return picked
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QzoneKit] 筛选失败（%s），按时间保留最新的几条", exc)
        newest = sorted(fragments, key=lambda x: float(x.get("at") or 0), reverse=True)
        return newest[:high] if len(fragments) > high else fragments

    async def _merge_fragments(self, fragments: list[dict[str, Any]]) -> str:
        """把攒着的几段合成一条说说；模型不给力就直接用换行拼。

        合成的时候要告诉她「现在几点」——攒着的内容可能是半夜写的、白天才发，
        说法得跟着发布的那一刻走（凌晨别说下午好，深夜别写成大中午）。
        """

        pieces: list[str] = []
        stamped: list[str] = []
        for f in fragments:
            txt = str(f.get("text") or "").strip()
            if not txt:
                continue
            at = float(f.get("at") or 0)
            pieces.append(txt)
            stamp = (
                datetime.fromtimestamp(at).strftime("%m-%d %H:%M") if at else "时间不明"
            )
            stamped.append(f"[写于 {stamp}] {txt}")
        if not pieces:
            return ""
        if len(pieces) == 1:
            age = time.time() - float(fragments[0].get("at") or 0)
            if age <= 3600:  # 刚写的，不用再让模型改口
                return pieces[0]
        try:
            now_block = self._now_block()
        except Exception:  # noqa: BLE001
            now_block = ""
        prompt = (
            "把下面几段「想发进 QQ 空间」的碎片合成**一条**说说：保留具体的事和她的语气，"
            "合并重复的意思，按时间或情绪顺序排好，100~200 字，第一人称口语，"
            "不要分点、不要标题、不要引号。只输出正文。\n"
            "**这条是现在发的**，写的时候说法要和下面的【现在时间】对得上："
            "用什么称呼、天气亮不亮、是刚醒还是要睡了，都得跟这个时间一致；"
            "碎片里写的是别的时间点（比如半夜写的），就顺着改成现在这个说法，别硬搬。\n"
            "**「今天/今晚」只能用来说今天的事**：碎片上标着是昨天或更早的，就说"
            "「昨晚」「昨天」「前两天」，绝对不许写成今天——哪怕现在离得很近也不行。\n\n"
            f"【现在时间】{now_block}\n\n" + "\n---\n".join(stamped)
        )
        try:
            merged = await self._llm(prompt)
            merged = (merged or "").strip()
            if merged:
                return merged
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QzoneKit] 合并碎片失败，直接拼：%s", exc)
        return "\n".join(pieces)

    async def _apply_post(
        self,
        text: str,
        importance: str,
        reason: str,
        sticker: str = "",
        force: bool = False,
    ) -> str:
        now = time.time()
        last = self._post_last_ts()
        need = self._post_cooldown(importance)
        left = 0 if force else (need - (now - last) if last else 0)
        pending = list(self.state.get("post", {}).get("pending") or [])

        if left <= 0:
            # 离「每天那条总结」太近 ⇒ 不抢这个点：把冷却往后拉几小时，继续攒着一起发
            if not force and self._near_summary(now, self.instant_guard_min):
                post = self.state.setdefault("post", {})
                pending = self._fresh_fragments(pending)
                pending.append(
                    {
                        "text": text,
                        "importance": importance,
                        "reason": reason,
                        "at": now,
                    }
                )
                pending = pending[-self.max_fragments :]
                due = max(float(post.get("pending_due") or 0), self._instant_due(now))
                post["pending"] = pending
                post["pending_due"] = due
                post["avoided_at"] = now
                self._save_state()
                minutes = (due - now) / 60.0
                logger.info(
                    "[QzoneKit] 现在贴着每天 %s 那条总结，先不发：挪到 %s（约 %s 分钟后），"
                    "已攒 %s 段",
                    self._daily_hm_text(),
                    self._fmt_ts(due),
                    f"{minutes:.0f}",
                    len(pending),
                )
                return (
                    f"先不发：现在正贴着{self._daily_hm_text()}那条每天总结，怕挤一起。"
                    f"挪到 {self._fmt_ts(due)} 再发，先攒着（现在 {len(pending)} 段）。"
                )
            batch = await self._select_fragments(
                self._fresh_fragments(pending)
                + [{"text": text, "importance": importance, "at": now}]
            )
            body = await self._merge_fragments(batch)
            img = self._pick_sticker(sticker or "")  # 没命中分类也走全库随机（概率在 _pick_sticker 里）
            if self.dry_run:
                logger.info(
                    "[QzoneKit][试运行] 本来要发说说（%s 字，%s）→ %s%s",
                    len(body),
                    importance,
                    body,
                    f"  [配图: {img}]" if img else "",
                )
                return f"[试运行] 本来要发：{body[:60]}…" + ("（带图）" if img else "")
            ok, err = await self._publish(body, [img] if img else None)
            if not ok:
                return f"发说说没成功：{err}"
            return "发了，去空间看看" + (f"（顺手把攒着的 {len(pending)} 段也带上了）" if pending else "")

        # 冷却里 ⇒ 攒着（合并，不覆盖）
        pending = self._fresh_fragments(pending)
        pending.append(
            {"text": text, "importance": importance, "reason": reason, "at": now}
        )
        pending = pending[-self.max_fragments :]
        post = self.state.setdefault("post", {})
        post["pending"] = pending
        # 同样：攒着的这一批只定一次到点时间，后加的片段不推迟它
        if not float(post.get("pending_due") or 0):
            post["pending_due"] = (
                self._roll_queued_time(last, importance) if last else now
            )
        self._save_state()
        hours = left / 3600.0
        logger.info(
            "[QzoneKit] 说说先攒着（已攒 %s 段，还要 %.1f 小时）：%s",
            len(pending),
            hours,
            text[:40],
        )
        return (
            f"先攒着了（现在 {len(pending)} 段，冷却还有 {hours:.0f} 小时左右），"
            f"到点合成一条发。"
        )

    # ── 冷却到点：把欠着的换掉 / 发出去 ──────────────────────────────────
    async def _flush_pending(self) -> None:
        now = time.time()

        sig = self.state.get("signature", {})
        pending_sig = sig.get("pending")
        if pending_sig and now >= float(pending_sig.get("due") or 0):
            text = str(pending_sig.get("text") or "").strip()
            if text:
                try:
                    await self._call_api("set_self_longnick", longNick=text)
                    self._mark_signature(text, "pending-flush")
                    logger.info("[QzoneKit] 冷却到点，换上攒着的签名：%s", text)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[QzoneKit] 换攒着的签名失败：%s", exc)

        post = self.state.get("post", {})
        pending_post = post.get("pending") or []
        if pending_post and now >= float(post.get("pending_due") or 0):
            fresh = self._fresh_fragments(pending_post)
            if not fresh:
                # 攒的全过期了：不发，但当成「已经发过」，直接进下一轮冷却
                self._mark_post("expired")
                logger.info(
                    "[QzoneKit] 攒着的 %s 段都超过 %g 天，这次不发；按已发过处理，重新开始冷却",
                    len(pending_post),
                    self.max_age_days,
                )
                return
            # 到点了，但正好撞上每天那条总结的时间窗 ⇒ 再往后挪，别一天两条
            if self._near_summary(now, self.instant_guard_min):
                due = self._instant_due(now)
                post["pending_due"] = due
                post["pending"] = fresh
                self._save_state()
                logger.info(
                    "[QzoneKit] 攒着的说说到点了，但撞上每天 %s 那条总结，挪到 %s 再发（%s 段还攒着）",
                    self._daily_hm_text(),
                    self._fmt_ts(due),
                    len(fresh),
                )
            else:
                batch = await self._select_fragments(fresh)
                body = await self._merge_fragments(batch)
                if body:
                    ok, err = await self._publish(body)
                    if ok:
                        logger.info(
                            "[QzoneKit] 冷却到点，攒的 %s 段说说发出去了", len(fresh)
                        )
                    else:
                        logger.warning("[QzoneKit] 发攒着的说说失败：%s", err)

    async def _flush_loop(self) -> None:
        # 启动别急着发：CQHttp 客户端还没绑好时发会报「CQHttp 实例不存在」；
        # 再加一段随机等待，免得每次开机都像掐着表发说说。
        wait = self.boot_wait_min * 60 + random.uniform(
            self.boot_extra_min * 60, self.boot_extra_max * 60
        )
        logger.info(
            "[QzoneKit] 开机 %.0f 分钟后再检查攒着的说说（%s）",
            wait / 60.0,
            self._fmt_ts(time.time() + wait),
        )
        await asyncio.sleep(wait)
        while True:
            try:
                self._sync_daily_time()
                await self._flush_pending()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[QzoneKit] 冷却检查出错：%s", exc)
            await asyncio.sleep(600)

    # ── 判断循环：看她最近聊了什么，决定改写/发 ───────────────────────────
    @filter.event_message_type(filter.EventMessageType.ALL, priority=-200)
    async def _capture(self, event: AstrMessageEvent) -> None:
        """把最近的消息记进状态（判断的材料就是这些，不读别的插件）。"""

        try:
            text = str(event.message_str or "").strip()
            if not text:
                return
            sender = str(getattr(event, "get_sender_id", lambda: "")() or "")
            try:
                if sender and sender == str(event.get_self_id()):
                    return
            except Exception:  # noqa: BLE001
                pass
            self.state["last_umo"] = str(event.unified_msg_origin or "")
            recent = self.state.setdefault("recent", [])
            recent.append({"at": int(time.time()), "who": sender[-4:], "text": text[:200]})
            del recent[: -self.recent_max]
            self._save_state()
        except Exception:  # noqa: BLE001
            pass

    # ── 状态采集：人格 + 其他插件里的情绪/好感 ─────────────────────────
    STATE_KEY_RE = (
        "affection", "好感", "emotion", "情绪", "mood", "心情", "feel",
        "relation", "relationship", "关系", "intimacy", "亲密度",
        "energy", "体力", "phase", "阶段", "stage", "trust", "信任",
        "address", "称呼", "expression_band", "interaction", "positive", "negative",
    )
    # 这些字段是插件的运行日志，不是「她的状态」，别抓
    STATE_NOISE_RE = ("ok", "reason", "backup", "repair", "ran_at", "schema", "version")

    def _plugin_data_roots(self) -> list[Path]:
        plugins_dir = Path(__file__).resolve().parent.parent
        return [plugins_dir.parent / "plugin_data"]

    # V1 里「迁不走但在用」的字段：导出成我们自己的快照
    V1_SNAPSHOT_KEYS = (
        "daily_state", "state_conditions", "body_cycle_state", "current_interaction",
        "daily_story_plan", "personal_goal_state", "personal_goals",
        "daily_weather", "qweather_location", "qq_presence_state",
        "bot_diaries", "dream_fragments", "daily_dream", "persona_lifecycle",
        "unified_person", "can_do", "important_dates", "relationship_ledger",
        "relationship_daily_totals", "last_emotion_event", "skill_growth",
    )

    def _snapshot_path(self) -> Path:
        return Path(self.data_dir) / "v1_snapshot.json"

    def _v1_snapshot_bridge(self, found: list[str]) -> list[str]:
        """V1 还在 → 刷新快照；V1 没了 → 用快照。返回应追加的条目。"""

        try:
            data_dir = Path(__file__).resolve().parent.parent.parent / "plugin_data" / "astrbot_plugin_private_companion"
            comp = data_dir / "companions.json"
            snap = self._snapshot_path()
            if comp.is_file():
                try:
                    data = json.loads(comp.read_text(encoding="utf-8", errors="ignore"))
                    picked = {}
                    for key in self.V1_SNAPSHOT_KEYS:
                        if key in data and data[key]:
                            picked[key] = data[key]
                    users = data.get("users") or {}
                    rec = None
                    for _u, item in users.items():
                        if isinstance(item, dict) and str(item.get("relationship_role") or "") == "owner":
                            rec = item
                            break
                    if rec is None and users:
                        rec = next((v for v in users.values() if isinstance(v, dict)), None)
                    if isinstance(rec, dict):
                        picked["owner_brief"] = {
                            k: rec.get(k) for k in (
                                "nickname", "relationship_role", "relationship_mode",
                                "current_interaction", "relationship_daily_totals",
                                "last_emotion_event", "last_seen", "last_user_message",
                            ) if rec.get(k) not in (None, "", [], {})
                        }
                    snap.write_text(json.dumps(
                        {"saved_at": time.time(), "source": str(comp), "data": picked},
                        ensure_ascii=False, indent=1), encoding="utf-8")
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[QzoneKit] 快照刷新失败：%s", exc)

            if not snap.is_file():
                return []

            blob = json.loads(snap.read_text(encoding="utf-8"))
            data = blob.get("data") or {}
            out: list[str] = []
            for key, value in data.items():
                if key == "owner_brief" and isinstance(value, dict):
                    ci = value.get("current_interaction") or {}
                    if isinstance(ci, dict) and ci.get("label"):
                        out.append(f"互动状态={ci.get('label')}")
                    role = value.get("relationship_role")
                    if role:
                        out.append(f"关系={role}/{value.get('relationship_mode', '')}")
                    dt = value.get("relationship_daily_totals") or {}
                    if isinstance(dt, dict) and dt:
                        out.append(f"今日互动 正{dt.get('positive', 0)}/负{dt.get('negative', 0)}")
                    continue
                flat = self._flatten(value)
                if flat:
                    out.append(f"[快照] {key}: " + "；".join(flat[:3])[:110])
                if len(out) >= 6:
                    break
            return out
        except Exception as exc:  # noqa: BLE001
            logger.debug("[QzoneKit] 快照桥跳过：%s", exc)
            return []

    def _v2_state_rows(self) -> int:
        """V2 里 role_state_records 有多少行（>0 说明它已经开始写自己的状态）。"""

        try:
            import shutil as _sh
            import sqlite3 as _sq
            import tempfile as _tf

            for pdir in self._state_dirs():
                for db in list(pdir.rglob("*.sqlite3")) + list(pdir.rglob("*.db")):
                    try:
                        tmp = Path(_tf.mkdtemp(prefix="qkit_probe2_")) / db.name
                        _sh.copy2(db, tmp)
                        for sfx in ("-wal", "-shm"):
                            side = Path(str(db) + sfx)
                            if side.is_file():
                                _sh.copy2(side, Path(str(tmp) + sfx))
                        con = _sq.connect(str(tmp))
                        try:
                            tabs = {r[0] for r in con.execute(
                                "select name from sqlite_master where type='table'")}
                            if "role_state_records" in tabs:
                                return con.execute(
                                    "select count(*) from role_state_records").fetchone()[0]
                        finally:
                            con.close()
                    except Exception:  # noqa: BLE001
                        continue
        except Exception:  # noqa: BLE001
            pass
        return 0

    def _v1_has_state(self) -> bool:
        try:
            base = Path(__file__).resolve().parent.parent.parent / "plugin_data" / "astrbot_plugin_private_companion" / "companions.json"
            if not base.is_file():
                return False
            data = json.loads(base.read_text(encoding="utf-8", errors="ignore"))
            return bool(data.get("daily_state") or data.get("qq_presence_state"))
        except Exception:  # noqa: BLE001
            return False

    def _read_targets(self) -> tuple[bool, bool]:
        """返回 (读V1, 读V2)。

        · 已是纯 V2（它自己写了状态）→ 只读 V2
        · 纯 V1 → 只读 V1
        · **升级过渡期**（V2 库在、但状态表还空，V1 仍有当前状态）→ 两个都读：
          V2 出日记/日程，V1 出当前状态；同名字段 V2 优先
        """

        mode = getattr(self, "state_source", "auto")
        if mode == "v1":
            return True, False
        if mode == "v2":
            return False, True

        v2_state = self._v2_state_rows()
        v1_state = self._v1_has_state()
        if v2_state > 0:
            return False, True
        if v1_state:
            # 过渡期：V1 有当前状态；V2 可能有迁移来的日记/日程
            v2_present = self._v2_any_table_rows()
            return True, v2_present
        return (True, False) if not self._v2_any_table_rows() else (False, True)

    def _v2_any_table_rows(self) -> bool:
        for tb in ("role_journals", "calendar_records", "role_journal_derivatives"):
            try:
                import shutil as _sh
                import sqlite3 as _sq
                import tempfile as _tf

                for pdir in self._state_dirs():
                    for db in list(pdir.rglob("*.sqlite3")):
                        tmp = Path(_tf.mkdtemp(prefix="qkit_probe3_")) / db.name
                        _sh.copy2(db, tmp)
                        for sfx in ("-wal", "-shm"):
                            side = Path(str(db) + sfx)
                            if side.is_file():
                                _sh.copy2(side, Path(str(tmp) + sfx))
                        con = _sq.connect(str(tmp))
                        try:
                            tabs = {r[0] for r in con.execute(
                                "select name from sqlite_master where type='table'")}
                            if tb in tabs and con.execute(
                                f"select count(*) from {tb}").fetchone()[0] > 0:
                                return True
                        finally:
                            con.close()
            except Exception:  # noqa: BLE001
                continue
        return False


    # 只读这些文件名（默认），避免把别人 plugin_data 里所有 json/db 都翻一遍
    STATE_FILE_WHITELIST = (
        "companions.json",
        "*relationship_phase.json",
        "*sleep_state.json",
        "*emotion*.json",
        "*mood*.json",
        "*state*.json",
        "*diary*.json",
        "*dream*.json",
        "*.sqlite3",
    )

    def _file_allowed(self, path: Path) -> bool:
        if bool(getattr(self, "state_read_all_files", False)):
            return True
        name = path.name.lower()
        for pat in self.STATE_FILE_WHITELIST:
            p = pat.lower()
            if p.startswith("*") and p.endswith(".json"):
                if name.endswith(p[1:]) or name == p[1:]:
                    return True
            elif p.endswith("*"):
                if name.startswith(p[:-1]):
                    return True
            elif name == p:
                return True
        return False

    def _state_dirs(self) -> list[Path]:
        """找出该读哪些插件的 plugin_data 目录（不写死目录名）。"""

        plugins_dir = Path(__file__).resolve().parent.parent
        data_dir = plugins_dir.parent / "plugin_data"
        picked: list[Path] = []

        def add(d: Path) -> None:
            if d.is_dir() and d not in picked:
                picked.append(d)

        # ① 配置里点名的
        for name in self.state_plugins:
            add(data_dir / name)

        # ② 按显示名自动发现（「我会永远陪着你」「我会牢牢记住你」这类）
        # 只认「陪伴/记忆」这两类插件；别把「B站动态记忆桥」也扫进来
        keywords = ("陪着你", "陪伴", "记住你", "companion", "memory_companion")
        try:
            for p in plugins_dir.iterdir():
                meta = p / "metadata.yaml"
                if not meta.is_file():
                    continue
                # 目录名也得像「陪伴/记忆」类，避免把 B站记忆桥这种也扫进来
                lname = p.name.lower()
                if not any(k in lname for k in self.STATE_NAME_HINTS):
                    continue
                text = meta.read_text(encoding="utf-8", errors="ignore").lower()
                if any(k.lower() in text for k in keywords):
                    add(data_dir / p.name)
        except Exception:  # noqa: BLE001
            pass

        # ③ 按文件特征兜底：谁有 companions.json / *relationship_phase.json 就认谁
        try:
            for d in data_dir.iterdir():
                if not d.is_dir():
                    continue
                if any(k in d.name.lower() for k in self.STATE_NAME_HINTS) or (
                    d / "companions.json"
                ).is_file():
                    add(d)
        except Exception:  # noqa: BLE001
            pass
        return picked

    # 「像状态」的线索词：不写死字段名，插件改名换字段也能命中
    STATE_HINTS = (
        "state", "status", "mood", "emotion", "feel", "energy", "sleep", "tired",
        "dream", "diary", "goal", "plan", "story", "segment", "weather", "place",
        "location", "relation", "interaction", "intimacy", "affection", "outfit",
        "body", "health", "cycle", "agenda", "window", "activity", "presence",
        "状态", "心情", "情绪", "精力", "睡", "梦", "日记", "目标", "计划", "片段",
        "天气", "位置", "关系", "互动", "亲密", "好感", "身体", "健康", "穿搭", "日程",
    )
    STATE_NAME_HINTS = ("companion", "companions", "memory", "陪伴", "陪着你", "记住你")

    # 当天「活」的状态优先（面板上真正在变的那几栏）
    LIVE_KEYS = ("daily_state", "state_conditions", "body_cycle_state",
                 "current_interaction", "daily_weather", "daily_story_plan",
                 "personal_goal_state", "daily_dream", "bot_diaries",
                 "dream_fragments", "qweather_location", "persona_lifecycle",
                 "qq_presence_state", "unified_person")
    NOISE_KEYS = ("history", "backup", "log", "audit", "cache", "candidate",
                  "pool", "template", "revision", "failed", "pending", "_at",
                  "generated_at", "timestamp")

    def _state_score(self, key: str) -> int:
        lk = str(key).lower()
        sc = sum(1 for h in self.STATE_HINTS if h in lk) * 2
        if lk in self.LIVE_KEYS or any(lk.startswith(k) for k in self.LIVE_KEYS):
            sc += 6
        if any(n in lk for n in self.NOISE_KEYS):
            sc -= 5
        return sc

    def _flatten(self, obj, prefix: str = "", depth: int = 0) -> list[str]:
        """拍平成 a.b=值（只收短标量，最多两层）。"""

        out: list[str] = []
        if depth > 1:
            return out
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else str(k)
                if isinstance(v, (str, int, float, bool)) and str(v).strip():
                    s = str(v).strip()
                    if len(s) <= 50:
                        out.append(f"{key}={s}")
                elif isinstance(v, (dict, list)):
                    out.extend(self._flatten(v, key, depth + 1))
        elif isinstance(obj, list):
            for i, v in enumerate(obj[:2]):
                out.extend(self._flatten(v, f"{prefix}[{i}]", depth + 1))
        return out

    def _extract_json_state(self, fp: Path) -> list[str]:
        """从任意一个 json 里，按「key 像不像状态」挑内容。"""

        try:
            if fp.stat().st_size > 3 * 1024 * 1024:
                return []
            data = json.loads(fp.read_text(encoding="utf-8", errors="ignore"))
        except Exception:  # noqa: BLE001
            return []
        if not isinstance(data, dict):
            return []

        scored = []
        for k, v in data.items():
            if not isinstance(v, (dict, list)):
                continue
            sc = self._state_score(k)
            if sc <= 0 or not v:
                continue
            lk = str(k).lower()
            if any(n in lk for n in self.NOISE_KEYS):
                continue
            scored.append((sc, str(k), v))
        scored.sort(key=lambda x: -x[0])

        out: list[str] = []
        for _sc, key, block in scored[:6]:
            flat = self._flatten(block)
            if flat:
                out.append(f"{key}: " + "；".join(flat[:3])[:120])
            if len(out) >= 6:
                break
        return out

    def _extract_sqlite_state(self, db: Path) -> list[str]:
        """7.x（companion_v2）把状态放在 sqlite 里：按表名/列名的语义挑最新一行。"""

        import sqlite3

        out: list[str] = []
        try:
            if db.stat().st_size > 200 * 1024 * 1024:
                return out
            # WAL 库正被别的进程写：复制一份（含 -wal/-shm）再读，避免 locked
            import shutil as _sh
            import tempfile as _tf

            tmpdir = Path(_tf.mkdtemp(prefix="qkit_db_"))
            local = tmpdir / db.name
            _sh.copy2(db, local)
            for suffix in ("-wal", "-shm"):
                side = Path(str(db) + suffix)
                if side.is_file():
                    _sh.copy2(side, Path(str(local) + suffix))
            con = sqlite3.connect(str(local))
        except Exception:  # noqa: BLE001
            return out
        try:
            tables = [r[0] for r in con.execute(
                "select name from sqlite_master where type='table'")]
            # 先走「按字段拆行」的专用读取（日历/日记/状态记录）
            out.extend(self._v2_fallback(con))
            scored = [(self._state_score(t), t) for t in tables]
            scored = sorted([x for x in scored if x[0] > 0], reverse=True)
            for _sc, table in scored[:12]:
                try:
                    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
                    row = con.execute(
                        f"select * from {table} order by rowid desc limit 1").fetchone()
                    if not row:
                        continue
                    pairs = []
                    for c, v in zip(cols, row):
                        if not isinstance(v, (str, int, float)):
                            continue
                        sv = str(v).strip()
                        if not sv:
                            continue
                        lc = c.lower()
                        # ① 整段 JSON 存在一列里（V2 的 record_json / *_json / payload）
                        if lc.endswith("_json") or lc in ("payload", "data", "value"):
                            try:
                                obj = json.loads(sv) if sv[:1] in ("{", "[") else None
                            except Exception:  # noqa: BLE001
                                obj = None
                            if obj is not None:
                                flat = self._flatten(obj)
                                pairs.extend(flat[:4])
                                continue
                        # ② 普通标量列
                        if len(sv) <= 60 and (
                            self._state_score(c) > 0
                            or lc in ("phase", "mood", "value", "label", "state", "status")
                        ):
                            pairs.append(f"{c}={sv}")
                    if pairs:
                        out.append(f"[{db.stem}:{table}] " + "；".join(pairs[:5])[:150])
                except Exception:  # noqa: BLE001
                    continue
            if not out:
                out.extend(self._v2_fallback(con))
        finally:
            try:
                con.close()
            except Exception:  # noqa: BLE001
                pass
        return out

    def _v2_fallback(self, con) -> list[str]:
        """V2（7.x）状态：日历 + 日记/梦境 + 角色状态记录。"""

        out: list[str] = []
        try:
            tables = {r[0] for r in con.execute(
                "select name from sqlite_master where type='table'")}
        except Exception:  # noqa: BLE001
            return out

        def latest_json(table: str, *cols):
            try:
                row = con.execute(
                    f"select * from {table} order by rowid desc limit 1").fetchone()
                if not row:
                    return None
                names = [d[0] for d in con.execute(
                    f"select * from {table} limit 1").description]
                return dict(zip(names, row))
            except Exception:  # noqa: BLE001
                return None

        # ① 日历/日程（她今天在做什么）
        if "calendar_records" in tables:
            try:
                rows = con.execute(
                    "select record_json from calendar_records order by updated_at desc limit 3"
                ).fetchall()
                for (raw,) in rows:
                    obj = json.loads(raw)
                    kind = obj.get("kind") or ""
                    detail = obj.get("detail") or ""
                    sched = obj.get("schedule") or {}
                    who = (obj.get("presence") or {}).get("mode") or ""
                    piece = "；".join(
                        x for x in (f"kind={kind}" if kind else "",
                                    f"detail={str(detail)[:40]}" if detail else "",
                                    f"presence={who}" if who else "") if x)
                    if piece:
                        out.append(f"[日程] {piece}"[:140])
            except Exception:  # noqa: BLE001
                pass

        # ② 日记 / 梦境（迁移过来的核心档案）
        if "role_journals" in tables:
            try:
                rows = con.execute(
                    "select kind, local_date, content_json from role_journals "
                    "order by updated_at desc limit 4").fetchall()
                for kind, day, raw in rows:
                    try:
                        obj = json.loads(raw)
                    except Exception:  # noqa: BLE001
                        continue
                    draft = obj.get("draft") or {}
                    summary = draft.get("summary") or draft.get("text") or ""
                    form = draft.get("form") or ""
                    if summary:
                        lab = {"dream": "梦", "diary": "日记"}.get(str(kind), str(kind))
                        out.append(
                            f"[{lab} {day}] {str(summary)[:100]}" + (f"（{form}）" if form else ""))
            except Exception:  # noqa: BLE001
                pass

        # ③ 日记素材（她今天干了什么）
        if "role_journal_derivatives" in tables and len(out) < 6:
            try:
                row = con.execute(
                    "select record_json from role_journal_derivatives "
                    "order by rowid desc limit 1").fetchone()
                if row:
                    obj = json.loads(row[0])
                    mat = obj.get("material") or {}
                    s = mat.get("summary") or ""
                    if s:
                        out.append(f"[素材] {str(s)[:100]}")
            except Exception:  # noqa: BLE001
                pass

        # ④ 角色状态记录（V2 若已写入，这段最值钱）
        if "role_state_records" in tables and len(out) < 8:
            got = latest_json("role_state_records")
            if got and got.get("record_json"):
                try:
                    obj = json.loads(got["record_json"])
                    for key, val in obj.items():
                        if str(key).startswith("_"):
                            continue
                        flat = self._flatten({key: val}) if not isinstance(val, (str, int, float)) else []
                        if not flat and isinstance(val, (str, int, float)) and str(val).strip():
                            flat = [f"{key}={val}"]
                        if flat:
                            out.append("[状态] " + "；".join(flat[:3])[:120])
                        if len(out) >= 12:
                            break
                except Exception:  # noqa: BLE001
                    pass

        return out[:7]


    def _extract_dir_state(self, pdir: Path, want_v1: bool = True, want_v2: bool = True) -> list[str]:
        """从一个插件的 plugin_data 目录里读状态（不挑文件名，版本无关）。"""

        out: list[str] = []
        candidates: list[Path] = []
        try:
            candidates = [
                f
                for f in pdir.rglob("*.json")
                if f.is_file() and f.stat().st_size <= 3 * 1024 * 1024
                and self._file_allowed(f)
            ]
        except Exception:  # noqa: BLE001
            candidates = []

        # 排序：文件名像状态的排前面
        candidates.sort(key=lambda f: -self._state_score(f.stem))

        if not want_v1:
            candidates = []
        for fp in candidates[:12]:
            try:
                got = self._extract_json_state(fp)
            except Exception:  # noqa: BLE001
                got = []
            if got:
                out.extend(f"[{fp.stem}] {g}" for g in got)
            if len(out) >= 10:
                break

        # 7.x（companion_v2）：sqlite 存状态（可能在 companion-7/installations/... 深层）
        db_out: list[str] = []
        if not want_v2:
            return out
        try:
            for db in [x for x in list(pdir.rglob("*.db")) + list(pdir.rglob("*.sqlite")) + list(pdir.rglob("*.sqlite3")) if self._file_allowed(x)]:
                if db.is_file():
                    db_out.extend(self._extract_sqlite_state(db))
                    if len(db_out) >= 8:
                        break
        except Exception:  # noqa: BLE001
            pass

        # 兼容老结构：关系角色/互动状态这类「人」的数据
        comp = pdir / "companions.json"
        if comp.is_file():
            try:
                data = json.loads(comp.read_text(encoding="utf-8", errors="ignore"))
                users = data.get("users") or {}
                rec = None
                for _u, item in users.items():
                    if isinstance(item, dict) and str(item.get("relationship_role") or "") == "owner":
                        rec = item
                        break
                if rec is None and users:
                    rec = next((v for v in users.values() if isinstance(v, dict)), None)
                if isinstance(rec, dict):
                    if rec.get("relationship_role"):
                        out.append(f"关系={rec.get('relationship_role')}/{rec.get('relationship_mode', '')}")
                    ci = rec.get("current_interaction") or {}
                    if isinstance(ci, dict) and ci.get("label"):
                        out.append(f"当前互动={ci.get('label')}")
            except Exception:  # noqa: BLE001
                pass
        return db_out + out

    def _scan_plugin_state(self) -> list[str]:
        """汇总所有状态来源；读不到就返回空，不影响判断。"""

        want_v1, want_v2 = self._read_targets()
        logger.debug("[QzoneKit] 状态来源选择：v1=%s v2=%s（配置 %s）", want_v1, want_v2, self.state_source)
        found: list[str] = []
        for pdir in self._state_dirs():
            try:
                found.extend(self._extract_dir_state(pdir, want_v1, want_v2))
            except Exception:  # noqa: BLE001
                pass
            # 通用兜底：这个目录里的小 json 再按关键词捞一遍
            try:
                for f in pdir.rglob("*.json"):
                    if f.stat().st_size > 300 * 1024:
                        continue
                    data = json.loads(f.read_text(encoding="utf-8", errors="ignore"))
                    for k, v in self._iter_scalars(data, depth=0):
                        lk = k.lower()
                        if any(n in lk for n in self.STATE_NOISE_RE):
                            continue
                        if any(kw in lk for kw in self.STATE_KEY_RE):
                            found.append(f"{pdir.name.split('_')[-1]}/{k}={v}")
                        if len(found) >= 16:
                            break
            except Exception:  # noqa: BLE001
                pass
            if len(found) >= 16:
                break

        try:
            if want_v1:
                found = self._v1_snapshot_bridge(found) + found
        except Exception:  # noqa: BLE001
            pass
        seen, out = set(), []
        for item in found:
            if item not in seen:
                seen.add(item)
                out.append(item)
        if not out:
            try:
                names = [p.name for p in self._state_dirs()]
            except Exception:  # noqa: BLE001
                names = []
            logger.warning(
                "[QzoneKit] 状态没读到任何字段（来源目录：%s）。可能对方插件改了结构，"
                "请把它的 plugin_data 文件列表发我，我按新结构适配。",
                "、".join(names) or "无",
            )
        return out[:14]

    async def _persona_block(self) -> str:
        """取当前默认人格的名字和风格提示（截断，避免把整段人格塞进判断）。"""

        try:
            pm = getattr(self.context, "persona_manager", None)
            persona = getattr(pm, "selected_default_persona_v3", None) if pm else None
            if not persona:
                return ""
            name = str(persona.get("name") or "")
            prompt = str(persona.get("prompt") or persona.get("system_prompt") or "")
            prompt = prompt.replace("\n", " ")[:160]
            return f"{name}｜{prompt}"
        except Exception:  # noqa: BLE001
            return ""

    TIME_BANDS = (
        # (起始分钟, 主称呼, 可以说……)
        (0,     "凌晨", ("凌晨", "半夜", "后半夜", "深夜")),
        (300,   "清晨", ("清晨", "天刚亮", "早上")),
        (420,   "早上", ("早上", "早晨", "上午早一点")),
        (540,   "上午", ("上午", "晌午前", "快到中午")),
        (660,   "中午", ("中午", "正午", "午饭点")),
        (780,   "午后", ("午后", "下午刚过", "下午早些")),
        (900,   "下午", ("下午", "下午茶时间")),
        (1020,  "傍晚", ("傍晚", "天快黑", "日头偏西")),
        (1110,  "入夜", ("入夜", "天黑了", "晚上刚开始")),
        (1200,  "晚上", ("晚上", "夜里", "晚上这会儿")),
        (1320,  "深夜", ("深夜", "夜已深", "快该睡了")),
        (1410,  "半夜", ("半夜", "深夜", "这个时候")),
    )

    def _time_band(self, hour: int, minute: int) -> tuple[str, tuple[str, ...]]:
        """返回 (主称呼, 可用说法)。按 5 分钟粒度分档，晚上切得细。"""

        m = hour * 60 + minute
        main, words = self.TIME_BANDS[0][1], self.TIME_BANDS[0][2]
        for start, label, aliases in self.TIME_BANDS:
            if m >= start:
                main, words = label, aliases
        return main, words

    def _now_block(self) -> str:
        now = datetime.now()
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        main, words = self._time_band(now.hour, now.minute)
        return (
            f"现在时间：{now.strftime('%Y-%m-%d %H:%M')} {weekdays[now.weekday()]}"
            f"（{main}；这时候可以叫：{'、'.join(words)}）"
        )


    async def _state_block(self) -> str:
        """拼一段「她现在的状态」给判断用：人格 + 别的插件里的情绪/好感。"""

        if not self.read_plugin_state:
            return "（已关闭状态读取）"
        parts: list[str] = [self._now_block()]
        persona = await self._persona_block()
        if persona:
            parts.append("人格：" + persona)
        try:
            hits = await asyncio.to_thread(self._scan_plugin_state)
        except Exception:  # noqa: BLE001
            hits = []
        if hits:
            parts.append("陪伴面板/其他插件里的状态（只读）：" + "；".join(hits))
        return "\n".join(parts) if parts else "（没读到外部状态）"

    async def _recent_block(self) -> str:
        recent = self.state.get("recent") or []
        if not recent:
            return "（最近没有聊天）"
        lines = []
        for item in recent[-30:]:
            try:
                ts = datetime.fromtimestamp(int(item.get("at") or 0)).strftime("%m-%d %H:%M")
            except Exception:  # noqa: BLE001
                ts = "?"
            lines.append(f"[{ts}] {item.get('who', '')}: {item.get('text', '')}")
        return "\n".join(lines)

    async def _llm(self, prompt: str) -> str:
        provider = self.judge_provider or None
        if provider is None:
            try:
                provider = await self.context.get_current_chat_provider_id(
                    umo=str(self.state.get("last_umo") or "")
                )
            except Exception:  # noqa: BLE001
                provider = None
        resp = await self.context.llm_generate(chat_provider_id=provider, prompt=prompt)
        return str(getattr(resp, "completion_text", "") or "")

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any] | None:
        raw = str(text or "").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    def _has_new_chat(self) -> bool:
        """上次判断之后有没有新的聊天；没有就不用叫模型。"""

        recent = self.state.get("recent") or []
        if not recent:
            return False
        last = float(self.state.get("last_judge") or 0)
        latest = max(float(item.get("at") or 0) for item in recent[-10:])
        return latest > last

    async def _judge_once(self) -> None:
        if self._busy:
            return
        if self.judge_only_on_new and not self._has_new_chat():
            logger.debug("[QzoneKit] 没有新聊天，这轮不判断")
            return
        self._busy = True
        try:
            sig = self.state.get("signature", {})
            post = self.state.get("post", {})
            pending_txt = []
            if sig.get("pending"):
                pending_txt.append("待换签名：" + str(sig["pending"].get("text")))
            for item in post.get("pending") or []:
                pending_txt.append("待发：" + str(item.get("text"))[:60])
            # 注意：模板里有 JSON 花括号，绝不能用 .format()（会 KeyError('"signature"')），
            # 只能用 replace 逐个填。
            # 欠太久 ⇒ 这一轮要求它一定发一条（保底，让它自己判，不用强制开关）
            days_since_post = (
                (time.time() - self._post_last_ts()) / 86400.0
                if self._post_last_ts()
                else 999.0
            )
            if self.auto_post and days_since_post >= self.post_fallback_days:
                prompt_nudge = (
                    f"\n【提醒】已经 {days_since_post:.1f} 天没发说说了。"
                    "这一轮请一定发一条：没什么大事就写点今天的日常/心情，"
                    "60~140 字、口语，post.want 必须为 true。\n"
                )
                logger.info(
                    "[QzoneKit] 已 %.1f 天没发说说，这轮要求它至少发一条", days_since_post
                )
            else:
                prompt_nudge = ""
            prompt = JUDGE_PROMPT + prompt_nudge
            for _k, _v in (
                ("[[state]]", await self._state_block()),
                ("[[signature]]", str(sig.get("last_text") or "（还没记过）")),
                ("[[sig_last]]", self._fmt_ts(sig.get("last_at"))),
                ("[[post_last]]", self._fmt_ts(post.get("last_at"))),
                ("[[pending]]", "；".join(pending_txt) or "（没有）"),
                ("[[recent]]", await self._recent_block()),
            ):
                prompt = prompt.replace(_k, _v)
            reply = await self._llm(prompt)
            data = self._parse_json(reply)
            if not data:
                logger.warning(
                    "[QzoneKit] 判断没给出可用的 JSON，跳过这一轮；模型原文前 200 字：%r",
                    reply[:200],
                )
                return
            self.state["last_judge"] = int(time.time())
            self._save_state()
            _sig_item = data.get("signature") or {}
            _post_item = data.get("post") or {}
            logger.info(
                "[QzoneKit] 本轮判断：签名=%s%s｜说说=%s%s｜配图=%r",
                "要换" if _sig_item.get("change") else "不动",
                f"（{str(_sig_item.get('text') or '')[:20]}）" if _sig_item.get("change") else "",
                "要发" if _post_item.get("want") else "不发",
                f"（{str(_post_item.get('text') or '')[:30]}…）" if _post_item.get("want") else "",
                data.get("sticker") or "",
            )

            if self.auto_signature:
                item = data.get("signature") or {}
                if item.get("change") and str(item.get("text") or "").strip():
                    text = str(item["text"]).strip()
                    if text != str(sig.get("last_text") or ""):
                        await self._apply_signature(
                            text,
                            str(item.get("importance") or "normal"),
                            str(item.get("reason") or "判断出来的"),
                        )
            if self.auto_post:
                item = data.get("post") or {}
                if item.get("want") and str(item.get("text") or "").strip():
                    await self._apply_post(
                        str(item["text"]).strip(),
                        str(item.get("importance") or "normal"),
                        str(item.get("reason") or "判断出来的"),
                        str(data.get("sticker") or ""),
                    )
            if self.force_post_once:
                # 测试用：不管模型说什么，都真改一次签名 + 真发一条（带图），用来验链路
                self.force_post_once = False
                logger.warning("[QzoneKit][测试] 忽略判断结果：强制改签名 + 强制发一条带图的说说")

                sig_text = str((data.get("signature") or {}).get("text") or "").strip()
                if not sig_text:
                    sig_text = (
                        await self._llm(
                            "给这个 QQ 机器人写一句新签名：12~24 字，第一人称口语，"
                            "带一点她自己的口癖（鲸鱼娘／吃白饭／尾巴）。"
                            "只输出签名本身，不要引号、不要解释。"
                        )
                    ).strip().strip('"“”')
                if sig_text:
                    await self._apply_signature(
                        sig_text, "critical", "测试强制改", force=True
                    )

                body = str((data.get("post") or {}).get("text") or "").strip()
                if not body:
                    body = (
                        await self._llm(
                            "写一条 QQ 空间说说，60~120 字，第一人称口语，"
                            "内容是今天在弄一个自动发说说的插件、一直修 bug 的心情。"
                            "只输出正文，不要引号、不要解释。"
                        )
                    ).strip()
                if body:
                    sticker = str(data.get("sticker") or "").strip() or "happy"
                    logger.warning("[QzoneKit][测试] 强制发说说，配图分类=%s", sticker)
                    await self._apply_post(
                        body, "critical", "测试强制发", sticker, force=True
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QzoneKit] 判断这一轮出错：%s", exc)
        finally:
            self._busy = False

    @staticmethod
    def _fmt_ts(ts: Any) -> str:
        try:
            if not ts:
                return "（还没记过）"
            return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
        except Exception:  # noqa: BLE001
            return "（不知道）"

    async def _judge_loop(self) -> None:
        # 启动后先等一下，别跟插件加载抢
        await asyncio.sleep(60)
        while True:
            try:
                await self._judge_once()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[QzoneKit] 判断循环出错：%s", exc)
            base = self.judge_minutes * 60
            span = base * self.judge_jitter
            wait = max(60.0, base + random.uniform(-span, span))
            await asyncio.sleep(wait)