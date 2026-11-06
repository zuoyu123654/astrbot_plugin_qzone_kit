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
   这里的是「有情绪/有事的即时说说」，靠冷却各自管着，不会一天刷两条。
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
PLUGIN_VERSION = "0.2.0"

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
        self.sig_min_days = float(cfg.get("signature_normal_min_days", 12) or 12)
        self.sig_max_days = float(cfg.get("signature_normal_max_days", 16.1) or 16.1)
        self.sig_crit_min_h = float(cfg.get("signature_critical_min_hours", 22) or 22)
        self.sig_crit_max_h = float(cfg.get("signature_critical_max_hours", 29.2) or 29.2)
        # 发说说：平时 2~2.6 天；非常重要 22~29.2 小时
        self.post_min_days = float(cfg.get("post_normal_min_days", 2) or 2)
        self.post_max_days = float(cfg.get("post_normal_max_days", 2.6) or 2.6)
        self.post_crit_min_h = float(cfg.get("post_critical_min_hours", 22) or 22)
        self.post_crit_max_h = float(cfg.get("post_critical_max_hours", 29.2) or 29.2)
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
        # 安全：owner_uids 留空时，默认只允许管理员触发删说说/改资料
        self.require_admin = bool(cfg.get("require_admin", True))
        self.read_plugin_state = bool(cfg.get("read_plugin_state", True))
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
                logger.warning(
                    "[QzoneKit] 已包装前置插件(astrbot_plugin_qzone)的 service.publish_post："
                    "只为让它自己的定时说说也走同一个配图概率。若该插件升级改了方法签名，"
                    "把 post_sticker_enabled 关掉即可完全复原，不影响其它功能。"
                )
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
        raise RuntimeError("找不到可用的 OneBot 接口（QQ空间插件没启用？）")

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        if getattr(self, "require_admin", True):
            try:
                if event.is_admin():
                    return True
            except Exception:  # noqa: BLE001
                pass
            if not self.owner_uids:
                return False
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
        """读 qqprofile 的状态对照表：**解析文本**，不执行第三方模块代码。"""

        fallback = {
            "在线": (10, 0), "离开": (30, 0), "隐身": (40, 0), "忙碌": (50, 0),
            "请勿打扰": (70, 0), "听歌中": (10, 1028), "学习中": (10, 1018),
            "摸鱼中": (10, 1300), "睡觉中": (10, 1066), "emo中": (10, 1401),
        }
        try:
            base = Path(__file__).resolve().parent.parent / QQPROFILE_STATUS / "status.py"
            if not base.is_file():
                return fallback
            text = base.read_text(encoding="utf-8", errors="ignore")
            pairs = re.findall(
                r'"([^"\n]{1,16})"\s*:\s*\(\s*(-?\d+)\s*,\s*(-?\d+)\s*\)', text)
            mapping = {name: (int(a), int(b)) for name, a, b in pairs}
            return mapping or fallback
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QzoneKit] 读状态表失败，用内置的：%s", exc)
            return fallback

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
            scored = [(self._state_score(t), t) for t in tables]
            scored = sorted([x for x in scored if x[0] > 0], reverse=True)
            for _sc, table in scored[:3]:
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
        finally:
            try:
                con.close()
            except Exception:  # noqa: BLE001
                pass
        return out

    # ── 表情包（配图）────────────────────────────────────────────────
    STICKER_EXTS = (".gif", ".png", ".jpg", ".jpeg", ".webp", ".bmp")

    STICKER_HINTS = {
        "happy": ("开心", "高兴", "笑", "爽", "棒", "夸", "顺利", "搞定", "成了", "好耶"),
        "angry": ("生气", "烦", "气死", "崩", "讨厌", "吵", "骂"),
        "sad": ("难过", "委屈", "累", "想哭", "不开心", "低落", "emo"),
        "sleep": ("困", "睡", "熬夜", "躺"),
        "food": ("吃", "饭", "奶茶", "饿", "馋", "夜宵"),
        "shy": ("害羞", "脸红", "不好意思", "心虚"),
        "confused": ("迷惑", "不懂", "为什么", "问号", "晕"),
        "surprised": ("惊讶", "惊", "吓", "没想到"),
        "work": ("干活", "工作", "写代码", "调试", "加班", "摸鱼", "bug"),
        "teasing": ("自嘲", "嫌弃", "反讽", "笑死"),
        "greeting": ("你好", "早上好", "晚安", "来了"),
        "affection": ("喜欢", "贴贴", "抱", "谢谢", "温柔"),
    }

    def _guess_category(self, text: str) -> str:
        """按文字关键词猜一个表情包分类；猜不到给空串（= 全图包随机）。"""

        low = str(text or "").lower()
        for cat, words in self.STICKER_HINTS.items():
            if any(w in low for w in words):
                return cat
        return ""

    def _sticker_index(self) -> dict[str, list[Path]]:
        """所有图包的 memes/<分类>/* → 索引。"""

        index: dict[str, list[Path]] = {}
        for root in self._sticker_roots():
            for memes in root.glob("*/memes"):
                if not memes.is_dir():
                    continue
                for cat_dir in memes.iterdir():
                    if not cat_dir.is_dir():
                        continue
                    files = [
                        f
                        for f in cat_dir.iterdir()
                        if f.is_file() and f.suffix.lower() in self.STICKER_EXTS
                    ]
                    if files:
                        index.setdefault(cat_dir.name.strip().lower(), []).extend(files)
        return index

    def _to_jpeg(self, src: Path) -> str:
        """任意格式转 JPEG（QZone 上传最稳；动图取第一帧）。"""

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
        """按概率挑一张表情包；挑不到返回空串。"""

        if not getattr(self, "sticker_enabled", False):
            return ""
        try:
            if random.random() > float(getattr(self, "sticker_prob", 0.5)):
                return ""
        except (TypeError, ValueError):
            pass
        index = self._sticker_index()
        if not index:
            logger.info("[QzoneKit] 没有表情包图包，跳过得配图")
            return ""
        cat = str(category or "").strip().lower()
        files = index.get(cat) or [f for fs in index.values() for f in fs]
        if not files:
            return ""
        return self._to_jpeg(random.choice(files))

    def _extract_dir_state(self, pdir: Path) -> list[str]:
        """从一个插件的 plugin_data 目录里读状态（不挑文件名，版本无关）。"""

        out: list[str] = []
        candidates: list[Path] = []
        try:
            candidates = [
                f
                for f in pdir.rglob("*.json")
                if f.is_file() and f.stat().st_size <= 3 * 1024 * 1024
            ]
        except Exception:  # noqa: BLE001
            candidates = []

        # 排序：文件名像状态的排前面
        candidates.sort(key=lambda f: -self._state_score(f.stem))

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
        try:
            for db in list(pdir.rglob("*.db")) + list(pdir.rglob("*.sqlite")) + list(pdir.rglob("*.sqlite3")):
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

        found: list[str] = []
        for pdir in self._state_dirs():
            try:
                found.extend(self._extract_dir_state(pdir))
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
        return out[:12]

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

    async def _state_block(self) -> str:
        """拼一段「她现在的状态」给判断用：人格 + 别的插件里的情绪/好感。"""

        if not self.read_plugin_state:
            return "（已关闭状态读取）"
        parts: list[str] = []
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
