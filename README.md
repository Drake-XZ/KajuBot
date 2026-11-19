# KajuBot

KajuBot 是一个基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的 QQ 聊天机器人，以《败犬女主太多了！》中的角色温水佳树为原型。她会记住和每个人的相处，有自己的心情，会从聊天和看过的内容里学东西，并以角色的口吻说话。

> 本项目是个人兴趣项目，与原作及其版权方无关。仓库只包含代码，不包含原作文本。

## 功能

| 模块 | 说明 |
|---|---|
| 感官 | 看图片、动图和视频（按画面变化选帧），听语音（本地 SenseVoice）和音乐，读文件；支持 B站和抖音链接 |
| 心情与好感 | 心情随对话变化，关系分多个维度，好感会累积；喜好在相处中形成 |
| 记忆 | 长期记忆和工作记忆；记忆有轻重、会褪色、会被触发想起；会记下心里的想法、未完成的约定和对每个人的印象 |
| 学习 | 从聊天、视频、书、音乐和网页搜索里积累知识，越常用越熟；每晚复盘、核对旧知识、总结教训、学习群里的叫法 |
| 生活 | 每日日程，日记、周记、月记；每晚写一条 QQ 空间说说，经主人批准后发出 |
| 说话 | 由大模型规划回复内容，再由回复器按角色口吻写出，发送前核对；群聊中自行判断是否插话 |
| 平台 | QQ 私聊和群聊；B站、抖音私信；自己浏览 B站并分享感受 |
| 管理工具 | Windows 控制台（启停、群聊插话程度、人格编辑、表情包管理）、记忆可视化、`botctl` 部署和测试工具 |

## 架构

```
QQ ── SnowLuma (OneBot v11) ── AstrBot ── plugins/（AstrBot 插件外壳）
                                            │
                                  kaju_astr/（AstrBot 适配层）
                                            │
                    kaju_core/（角色本体，不依赖 AstrBot 和具体聊天平台）
                    kaju_platforms/（B站、抖音、私信、QQ 的接入）
```

- **kaju_core**：`senses`（感官）、`heart`（心情）、`memory`（记忆）、`learn`（学习）、`life`（生活）、`voice`（说话），以及 `people.py`（跨平台身份表）和 `body.py`（对宿主框架的接口）
- **kaju_astr**：`body.py` 接口在 AstrBot 上的实现
- **plugins**：各功能的 AstrBot 插件，只负责事件钩子，逻辑在 kaju_core
- **kaju_platforms**：各平台的登录、链接解析、私信收发

各插件的详细设计、配置项和测试说明见 [bot_setup/docs/插件说明.md](bot_setup/docs/插件说明.md)。

## 目录结构

| 路径 | 内容 |
|---|---|
| `bot_setup/` | 全部机器人代码：kaju_core、kaju_platforms、kaju_astr、plugins、控制台脚本、tools、tests |
| `bot_setup/patches/` | 对第三方插件 memorix、meme_manager 的本地补丁 |
| `local_vision/` | 本地 Ollama 服务（向量模型 bge-m3）的启停脚本 |

## 运行环境

- Windows 10/11
- [AstrBot](https://github.com/AstrBotDevs/AstrBot)（aiocqhttp 适配器）和 SnowLuma（OneBot v11 实现）
- [Ollama](https://ollama.com/)：运行本地向量模型 bge-m3，供长期记忆检索使用
- 第三方 AstrBot 插件：memorix（长期记忆）、meme_manager（表情包）
- 大模型 API：对话规划和回复使用兼容 OpenAI 接口的模型服务，图片、视频理解使用 Gemini

## 部署

1. 安装 AstrBot、SnowLuma 和 Ollama，在 AstrBot 中配置 QQ 账号和模型服务。
2. 准备数据目录 `kaju_data/`（结构见 `kaju_data/README.txt`）：
   - `accounts/`：模型 API key、B站和抖音登录信息
   - `self/`：角色数据（人格、记忆、知识等）
3. 在 `kaju_data/self/people/people.json` 中登记主人的 QQ 号，也可以设置环境变量 `KAJU_OWNER_QQ`。
4. 部署插件和核心代码：

   ```powershell
   python bot_setup/tools/botctl.py deploy kaju_core --reload
   ```

5. 通过控制台 `bot_setup/佳树控制台.vbs` 或 `bot_setup/bot-panel.ps1` 启动。

代码中部分路径按作者本机的 `D:\JiashuBot` 编写，在其他位置部署时需要相应修改。

## 测试

测试不需要机器人运行，AstrBot 由 `bot_setup/tests/stubs` 代替。用 AstrBot 的 venv Python 逐个运行 `bot_setup/tests/test_*.py`：

```powershell
python -I bot_setup/tests/test_plugins.py
```

## 不包含的内容

以下内容出于安全、隐私或版权原因不在仓库中：

- API key、账号登录信息和 Cookie
- 角色的记忆、知识和聊天记录
- 原作文本
- 第三方程序和模型文件

## 许可

暂未指定开源许可证。在指定之前，代码的所有权利由作者保留。
