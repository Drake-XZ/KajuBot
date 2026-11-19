# bot_setup · 机器人代码

AstrBot（aiocqhttp 适配器）+ SnowLuma（OneBot v11）+ 一个小号 QQ。主人的 QQ 登记在身份表 `kaju_data/self/people/people.json`。

各插件的做法和配置项见 [docs/插件说明.md](docs/插件说明.md)。

## 目录

| 路径 | 内容 |
|---|---|
| `bot-panel.ps1` / `佳树控制台.vbs` / `icons/` | 控制台：启停机器人、群聊插话滑块、群聊暂停、拖图加表情包 |
| `persona-editor.ps1` + `tools/persona.py` | 人格微调：人设、关于自己、工具权限、出错回复、历史版本；`persona.py export` / `sync` 在 AstrBot 和人格正本之间同步 |
| `meme-manager.ps1` + `tools/memes.py` | 表情包管理：所有包共用一套分类，增删改、回收站 |
| `tools/memsea.py` + `memsea/` | 记忆星海：把她记得的东西画成 3D 星图 |
| `tools/botctl.py` + `tools/kajudata.py` | 部署插件和核心代码、热重载、看和改插件配置、身份表、清缓存、备份 |
| `kaju_core/` | 角色本体，不依赖 AstrBot：`senses`（感官）、`heart`（心情）、`memory`（记忆）、`learn`（学习）、`life`（生活）、`voice`（说话），`people.py`（身份表）、`body.py`（宿主接口）、`parts.py`（各部分登记表）、`paths.py`（数据位置） |
| `kaju_platforms/` | 各平台的接入：`bili/`、`douyin/`（链接、登录、私信、下载）、`shared/`（自己刷视频、私信规则、找主人）、`dm/`（私信逻辑）、`qq/`（QQ 上的动作） |
| `kaju_astr/` | `body.py` 在 AstrBot 上的实现 |
| `plugins/<名字>/` | AstrBot 插件外壳，部署后名为 `astrbot_plugin_<名字>`，逻辑在 `kaju_core/<块>/mind.py` |
| `tests/` | 离线测试（AstrBot 由 `tests/stubs` 代替；部分带 `--live` 调用真实模型） |
| `patches/*.patch` | 第三方插件 memorix、meme_manager 的本地补丁 |
| `scheduled-tasks/*.xml` | 计划任务导出（AstrBot、SnowLuma、掉线重连） |
| `qq-watchdog.ps1` / `.vbs` | 掉线自动重连 |

数据在 `kaju_data/`：`self/` 是角色本身（需要备份），`accounts/` 是 API key 和登录信息（不能外传），`cache/` 随时可清。

## 插件

| 插件 | 作用 |
|---|---|
| kaju_basics 佳树基础 | 唤醒、消息管道（连发合并、引用、稳定前缀、请求时限）、看图看视频读文件听语音听音乐、B站和抖音链接、小号登录、自己刷视频、挑主模型、Ollama 看门狗 |
| kaju_style 说话习惯 | 大脑出指导 → 回复器用她的口吻写 → 核对 → 分条发出 |
| kaju_heart 心情与好感 | 心情、好感、关系、心事、余韵、喜好、看视频读书时的感受、找主人帮忙 |
| memory_weight 记忆轻重 | 铭记、褪色、用上更牢、触景生情、珍藏的文件、工作记忆、没结果的事、人物印象 |
| kaju_learn 学到的东西 | 从聊天和看过的内容里学知识、睡前消化、自己去查、每晚复盘和教训、边读边想、群里的叫法 |
| kaju_life 佳树的生活 | 日程、日记、关于自己 |
| address_book 称呼簿 | 谁叫什么（"兄长大人"只叫主人） |
| smart_chime_in 聪明插话 | 群聊中什么时候主动接话 |
| kaju_dm 佳树私信 | B站、抖音私信，互关才回，回关和超额视频要主人批准 |
| follow_through 说到做到 | 能力清单，答应的事没做就后台补做；**新加的 LLM 工具必须加进它的 `CAPABILITY_LABELS`** |
| qzone_post 发说说 | 每晚写说说草稿，主人批准后发出 |
| group_peek 看群 | `peek_group_chat` / `send_group_message` |
| meme_saver 存表情 | `save_meme`（依赖 meme_manager） |
| memorix、meme_manager | 第三方插件（长期记忆、表情包），本地改动见 `patches/` |

本地运行的只有两个模型：记忆向量 bge-m3（便携 Ollama，`local_vision/runtime.ps1`）和语音转文字 SenseVoice（`models/`）。其余都用 API：大脑和看图看视频用 Gemini，回复器用 Claude。

时间：机器人按 AstrBot 配置的时区（Asia/Shanghai）计算日程和日期，与服务器本机时区无关。

## 常用操作

```bat
:: 启动 / 状态（也可以直接用控制台）
powershell -File bot_setup\bot-panel.ps1 -Action start -Quiet
powershell -File bot_setup\bot-panel.ps1 -Action status -Quiet

:: 改完源码：先跑测试，再部署 + 热重载
<venv>\Scripts\python.exe -I bot_setup\tests\test_plugins.py
python bot_setup\tools\botctl.py deploy kaju_core --reload

:: 生成记忆星海并用浏览器打开
<venv>\Scripts\python.exe -I bot_setup\tools\memsea.py build --open

:: 清缓存（先 --dry 看会删什么）/ 备份角色数据（--accounts 连登录一起）
python bot_setup\tools\botctl.py clean-cache --dry
python bot_setup\tools\botctl.py backup-self

:: 看 / 改插件配置（嵌套项用点号）
python bot_setup\tools\botctl.py config kaju_style
python bot_setup\tools\botctl.py config kaju_style bedtime.nag_chance=0.2
```

`<venv>` 是 AstrBot 实例的 Python 虚拟环境。只重启 AstrBot：结束占用 6185 / 6199 端口的进程，再运行 `bot-panel.ps1 -Action start -Quiet`（只拉起缺的部分）。跑全部离线测试：`tests/` 下每个 `test_*.py` 各运行一遍，结尾打印 ALL OK。
