# 佳树 QQ 机器人 · 自建部分

AstrBot（aiocqhttp 适配器）+ SnowLuma（OneBot v11）+ 小号 QQ（`D:\JiashuBot\QQ-Bot`）。机器人 QQ 555555555，兄长大人本人 111111111（只在称呼簿 `owner_qq` 里配）。

每个工具、每个插件的完整说明（做法、配置项、踩过的坑、测试）在 [docs\插件说明.md](docs/插件说明.md)。

## 目录

| 路径 | 内容 |
|---|---|
| `bot-panel.ps1` / `佳树控制台.vbs` / `icons\` | 佳树控制台：启停机器人、群聊插话滑块、拖图加表情包（桌面快捷方式指向 vbs，路径别改） |
| `persona-editor.ps1` + `tools\persona.py` | 控制台「人格微调」：人设、关于自己（kaju_life 的 self_facts.json）、示例对话、工具权限、出错回复、历史版本（存在 `_backup\persona\`）。人格正本在 `kaju_data\self\persona\`，AstrBot 数据库里那份是副本：`persona.py export`（AstrBot → 正本）/ `sync`（正本 → AstrBot） |
| `meme-manager.ps1` + `tools\memes.py` | 控制台「表情包管理」：所有包共用一套分类，增删改、回收站（`_backup\meme-trash\`） |
| `tools\memsea.py` + `memsea\` | 控制台「记忆星海」：把她记得的东西（含关于自己、知识本）画成 3D 星图，输出 `memsea\out\memory-sea.html` |
| `tools\botctl.py` + `tools\kajudata.py` | 部署插件和 kaju_core / 热重载 / 看和改插件配置 / 清缓存 / 备份她本人 |
| `kaju_core\` | 佳树本人那部分（不依赖 AstrBot、不认识任何聊天软件）：`paths.py`（她的东西放在哪）、`senses\`（感官：看视频、补看、动图、听音乐、听语音、读文件）、`heart\` `memory\` `learn\` `life\` `voice\`（心情、记忆轻重、学到的东西、关于自己、说话方式的纯逻辑）、`people.py`（谁是谁：一个人的 QQ / B站 / 抖音号认成同一个人，兄长是谁也以它为准；QQ 里 `/佳树认人` 或 `botctl people` 改）。以后人格、记忆、心情、知识、说话方式一块块搬进来。部署到 `core\data\kaju_lib\`，venv 里 `kaju_core.pth` 指过去；改了 kaju_core `botctl deploy kaju_core --reload`（只重载用到改动那块的插件），改了 `__init__` / `paths` 要重启 AstrBot |
| `kaju_platforms\` | 各平台怎么接（不碰 AstrBot）：`bili\` `douyin\`（链接、登录、私信、下载）、`shared\`（自己刷视频、私信规矩）、`dm\`（kaju_dm 的逻辑）、`qq\`（找兄长帮忙）。和 kaju_core 一起部署 |
| `kaju_astr\` | kaju_core 在 AstrBot 上的那一层（`AstrBody`：AstrBot 的模型、设置、QQ 接口），和 kaju_core 一起部署；改了要重启 AstrBot |
| `plugins\<名字>\` | 自写插件源码，部署后叫 `astrbot_plugin_<名字>`。kaju_heart / memory_weight / kaju_learn / kaju_life / kaju_style 只剩 AstrBot 外壳（钩子），逻辑在 `kaju_core\<块>\mind.py` |
| `tests\` | 离线测试（astrbot 用 `tests\stubs` 代替，不需要机器人在跑；部分带 `--live` 用真模型） |
| `patches\*.patch` | 第三方插件（meme_manager、memorix）的本地改动，插件更新后要重新打 |
| `scheduled-tasks\*.xml` | 计划任务 AstrBot-QQBot、SnowLuma-QQBot 的导出 |
| `docs\插件说明.md` | 详细说明 |

项目里其它目录：`D:\JiashuBot\local_vision\`（便携 Ollama：看图的 qwen3-vl + 记忆用的 bge-m3，说明见里面的 README）、`D:\JiashuBot\models\`（本地语音转文字 SenseVoice + silero VAD）、`D:\JiashuBot\_backup\`（人格历史版本、表情包回收站、11-17 / 11-18 改动的回滚点，以及几次整理时打包的旧备份 `cleanup-20261030.zip` / `archive-20261103.zip` / `archive-20261104.zip` / `archive-20261107.zip` / `archive-20261113.zip` / `archive-20261118.zip`——文档里提到的旧备份路径原样在这些 zip 里，`archive-20261107.zip`、`archive-20261118.zip` 里的 `_说明.txt` 列了装了什么）。

AstrBot 实例：`D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\core`（`C:\Users\18525\.astrbot_launcher` 是指向 AstrBot-Data 的链接），日志 `core\logs\stdout.log`。

**她的数据在 `D:\JiashuBot\kaju_data\`**（2026-11-08 起，按能不能删分开，说明见里面的 README.txt）：
`self\<插件名>\` = 她本人（心情、记忆、知识本、日记、称呼簿、memorix 长期记忆、表情包），要备份；
`accounts\` = B站/抖音小号的登录（丢了要重新扫码，有 Cookie 别外传）；`cache\` = 下载的视频、截帧、抖音网页缓存，随时能清。
AstrBot 的 `plugin_data\<插件全名>` 现在是指到 `self\` 的目录联接，老脚本按老路径读照样行。人格的正本在 `self\persona\`（2026-11-13 起；`persona.txt` 是人设正文），AstrBot 的 `data_v4.db` 里是给它用的副本；聊天记录还在 `data_v4.db`。

## 插件

| 插件 | 一句话 |
|---|---|
| kaju_basics 佳树基础 | 账号白名单、昵称/戳一戳唤醒、看图看视频读文件听语音听音乐、B 站链接、抖音链接（开本机 Chrome 看）、B站小号扫码登录（自动续期）、有许可时自己刷B站（/佳树B站登录 /佳树刷B站）、稳定前缀、请求时限、发送前检查、私聊连发合并、群聊记录按到达顺序、离得远就引用、本地语音转文字、Ollama 看门狗 |
| kaju_style 说话习惯 | 主模型当大脑出指导（或写草稿）→ Gemini 整理成第四版要点卡 + 心情行 → 回复器（API 大模型）照指导写、本地写手 kaju-writer-p6-8b-r7k 当后备 → 核对（回滚写手：`rewrite.card_model=kaju-writer-p5-8b-r6` 或 `p4-8b-k`；11-18 删了第一版卡和“规划器出卡”）；被纠正提醒、先回应别当解说员、问之前先听懂、聊作品说具体、消息分行、深夜催睡限频。1.18.0（2026-11-13）删掉了早就关着的首句称呼、句尾语气词、说短、大白话、说话有变化、开头少用"诶"、开头别老"好的"和旧的看草稿重说（kaju-rewriter） |
| kaju_life 佳树的生活 | 每日小日程 + 日记/周记/月记（read_diary / search_diary，/佳树日程 /佳树日记） |
| kaju_heart 心情与好感 | 心情、好感、心事、余韵、心里记下的、关系的几个侧面、喜好自己长出来、自己刷到的视频、最依赖兄长大人（ask_brother_for_help）；/好感度 /佳树心情 |
| memory_weight 记忆轻重 | 铭记、记忆打分量、用上更牢、遗忘曲线、珍藏的文件（recall_shared_file）、褪色、触景生情、工作记忆；/记忆轻重 /佳树备忘 |
| kaju_learn 学到的东西 | 聊天（私聊、群聊）、看过的视频和书、听过的歌、上网查过的都能学，攒成她自己懂的东西（越碰越熟、不碰慢慢记不清）；睡前消化、想弄明白的事拿去刷B站搜；聊到时自然想起来（recall_knowledge）；边读边想：长篇后台按人的速度一段段读（reading_pace）、长视频一段段看；/佳树学到的 |
| address_book 称呼簿 | 谁叫什么（兄长大人只叫主人，别人"名字+学长/学姐"）；set_address / clear_address |
| smart_chime_in 聪明插话 | 群聊什么时候主动接话；控制台滑块改它 |
| follow_through 说到做到 | 答应的事没做就后台补做；**新加的 LLM 工具必须加进它的 CAPABILITY_LABELS** |
| group_peek 看群 | peek_group_chat / send_group_message |
| kaju_dm 佳树私信 | 和她互关的人能在B站、抖音私信她聊天、发视频（像 QQ 私聊一样回，兄长的B站号就是他的 QQ 私聊）；她回关别人、别人每天超过 3 条的视频要兄长在 QQ 同意（/佳树私信，或直接跟她说）；抖音私信在常驻浏览器里开着私信页收发（表情包改发抖音表情库里的：按意思打字、点弹出来的建议表情） |
| qzone_post 发说说 | post_qzone；说说的点赞加好感、评论按私聊流程回复 |
| meme_saver 存表情 | save_meme（依赖 meme_manager） |
| memorix、meme_manager | 第三方插件（长期记忆、表情包），源码不在这里维护，本地改动见 `patches\` |

不用任何收费的云端语音/向量服务：语音转文字是本地 SenseVoice，记忆向量是本地 bge-m3，看图看视频是本地 qwen3-vl，说话的写手是本地训练的分层写手 kaju-writer-l1a（回退用 kaju-rewriter）；聊天本身用 DeepSeek。

资源：三个本地模型一起常驻显存约 6.25 GB（闲置 10 分钟释放），AstrBot 进程约 0.5 GB 内存（`core\start-bot.cmd` 限了 OpenBLAS 线程数）；细节见 [docs\插件说明.md](docs/插件说明.md)「速度、显存、内存」。训练用的东西在 `D:\JiashuBot\voice_train\`（基础模型、训练环境、数据、适配器；训练好的模型只存在 Ollama 里，对照表和重建方法见 `voice_train\models\README.md`）和 `kaju_train_kit\`（给别人电脑训练用的包）。

时间：服务器本机是当地时间（不是北京时间），机器人按 AstrBot 配置的时区（Asia/Shanghai）过日子，插件里算时间都用配置时区。

## 常用操作

```bat
:: 启动 / 停止 / 状态（也可以直接用控制台）
powershell -File D:\JiashuBot\bot_setup\bot-panel.ps1 -Action start -Quiet
powershell -File D:\JiashuBot\bot_setup\bot-panel.ps1 -Action status -Quiet

:: 改完插件源码：先跑测试，再部署 + 热重载
<venv>\Scripts\python.exe -I D:\JiashuBot\bot_setup\tests\test_plugins.py
python D:\JiashuBot\bot_setup\tools\botctl.py deploy kaju_style --reload

:: 生成记忆星海并用浏览器打开（控制台「记忆星海」按钮做的就是这个）
<venv>\Scripts\python.exe -I D:\JiashuBot\bot_setup\tools\memsea.py build --open

:: 清缓存（先 --dry 看会删什么；她本人和登录不碰）/ 备份她本人到 _backup\self-时间.zip（--accounts 连登录一起）
python D:\JiashuBot\bot_setup\tools\botctl.py clean-cache --dry
python D:\JiashuBot\bot_setup\tools\botctl.py backup-self

:: 看 / 改插件配置（嵌套项用点号）
python D:\JiashuBot\bot_setup\tools\botctl.py config kaju_style
python D:\JiashuBot\bot_setup\tools\botctl.py config kaju_style bedtime.nag_chance=0.2
```

`<venv>` = `D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\venv`。
只重启 AstrBot：结束占用 6185 / 6199 端口的 python，再 `bot-panel.ps1 -Action start -Quiet`（只会拉起缺的部分）。
跑全部离线测试：`tests\` 下每个 `test_*.py` 用上面的 venv python 加 `-I` 跑一遍，结尾打印 ALL OK / 全部通过。
