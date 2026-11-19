# 本地视觉运行时

Ollama 便携版位于 `D:\JiashuBot\local_vision\runtime`，模型为 `qwen3-vl:4b-instruct`。服务地址是 `http://127.0.0.1:11435`，OpenAI 兼容地址是 `http://127.0.0.1:11435/v1`。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\JiashuBot\local_vision\runtime.ps1 -Action Start
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\JiashuBot\local_vision\runtime.ps1 -Action Status
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\JiashuBot\local_vision\runtime.ps1 -Action Stop
```

启停脚本返回一行 JSON。Start 可以重复执行；Stop 检查可执行文件路径、进程启动时间和端口归属，仅关闭本项目的服务和它的本地推理子进程。11435 被其他进程占用时会报错，不会抢占端口。11434 不受影响。后台窗口隐藏，日志保存在 `logs`，每次启动覆盖上一次服务日志。

运行时使用以下进程环境变量，不修改用户或系统环境：

| 设置 | 值 |
| --- | --- |
| `OLLAMA_HOST` | `127.0.0.1:11435` |
| `OLLAMA_MODELS` | 本目录 `models` |
| `OLLAMA_TMPDIR`、`TEMP`、`TMP` | 本目录 `tmp` |
| `CUDA_CACHE_PATH` | 本目录 `cache\cuda` |
| `OLLAMA_CONTEXT_LENGTH` | `4096`（2026-11-04 从 8192 降下来：请求最长约 2k token——一张拼图 + 短提示；重说模型自己的 Modelfile 是 2048） |
| `OLLAMA_FLASH_ATTENTION` | `1` |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0`（KV 缓存减半，质量几乎不变） |
| `OLLAMA_KEEP_ALIVE` | `10m`（兄长选的：一段聊天里不冷启动，安静 10 分钟后还显存） |
| `OLLAMA_NUM_PARALLEL` | `1` |
| `OLLAMA_MAX_LOADED_MODELS` | `3`（看图 qwen3-vl 3.06 GB + 重说 kaju-rewriter 2.55 GB + 记忆 bge-m3 0.64 GB ≈ 6.25 GB 一起常驻，不再互相挤出去） |
| `OLLAMA_NO_CLOUD` | `1` |
| `OLLAMA_DEBUG` | `0` |
| `OLLAMA_DEBUG_LOG_REQUESTS` | `0` |

模型空闲约 10 分钟后卸载，服务继续运行。2026-11-04 实测（RTX 4060 8 GB）：以前上下文 8192 + f16 KV 时看图模型要 4.03 GB，最多只留 2 个模型，发图时看图模型把重说模型挤掉（看图冷加载 8.3 秒，回复时重说模型再加载 2.1 秒）；现在三个一起常驻，显卡总占用约 7.8 GB（含系统和别的程序约 1.2 GB），热调用都在 0.1 秒内，看图自检照常通过（OpenAI 兼容接口 10.6 秒）。机器人收到私聊或被叫到时会先让 bge-m3 和重说模型加载（kaju_basics / kaju_style 的预热），冷启动藏在等 DeepSeek 的那几秒里。本地 provider 应设较长的请求超时；首次冷图像请求实测约 93 秒，紧接着的 OpenAI 兼容图像请求约 9.7 秒；重启并改用项目 CUDA 缓存后的 OpenAI 冷请求实测 93.485 秒。较大的图像或输出会延长耗时，推荐本地请求至少允许 180 秒。不要通过每个请求覆盖 `num_ctx`、`num_parallel` 或 `keep_alive` 来增加资源占用。

模型、CUDA 缓存、临时文件和服务日志都在本目录。Ollama 仍会读取用户目录中原有的 `.ollama` 身份密钥或元数据；该版本没有已确认的独立目录设置，因此保留原来的 `HOME`、`USERPROFILE`。本次没有改动原有密钥。

## 自检

生命周期测试会启动和关闭服务，应在机器人不使用本地模型时执行，并先 Stop：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\JiashuBot\local_vision\test_runtime.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\JiashuBot\local_vision\runtime.ps1 Start
& 'D:\JiashuBot\AstrBot-Data\instances\c3dc9f47-5318-45ea-9792-d00fb8f0f15b\venv\Scripts\python.exe' D:\JiashuBot\local_vision\check_vision.py
```

图像自检只使用 Python 标准库，在内存中生成红色正方形与蓝色圆形。它检查 `/api/version`、`/api/tags`、原生图像请求、OpenAI 兼容 data URL 图像请求和 `/api/ps` 的 GPU 占用，按图像事实判断通过，不依赖回复措辞。`logs\vision-check.json` 记录耗时、模型摘要与显存数据，不保存图像或凭据。

## 版本来源

- [Ollama v0.40.13 官方 release](https://github.com/ollama/ollama/releases/tag/v0.40.13)，发布于 2026-10-28。
- [Windows 便携包](https://github.com/ollama/ollama/releases/download/v0.40.13/ollama-windows-amd64.zip)，SHA256 为 `7afa38624fa62ee5d8293422d0ab084c1bb4603134c7f4dafce11a033b57cc19`，已与官方 release digest 核对。已解压到 `runtime`；原始包（1.5 GB）2026-11-03 整理时删掉了，要重装就从这个链接重新下载、核对 SHA256。
- [Qwen3-VL 4B Instruct 官方模型页](https://ollama.com/library/qwen3-vl:4b-instruct)：Q4_K_M，下载大小 3,337,225,651 字节。本地模型摘要为 `84f7ed8042fa7cdbd902f7dcb7d0370e032095047cc3244179f263b77b5bc318`。
- [Windows 独立 CLI 说明](https://docs.ollama.com/windows)、[本地模式及资源设置](https://docs.ollama.com/faq)、[CUDA 缓存目录设置](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/environment-variables.html)。

下载运行时和模型需要网络；运行本地模型不使用付费 API。云模型及 Ollama 云搜索已禁用。
