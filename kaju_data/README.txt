佳树的数据（2026-11-08 起；排法见 bot_setup\kaju_core\paths.py）

self\       她本人：心情、记忆、知识本、日记、称呼簿、表情包……  要备份，不能乱删
            一个插件一个目录。AstrBot 的 plugin_data\<插件全名> 是指到这里的目录联接。
accounts\   各平台登录：B站小号（bili_login.json）、抖音小号（douyin_login.json + douyin_profile 浏览器资料夹）
            丢了要重新扫码；里面有 Cookie，别发给别人
cache\      下载的视频、截帧、临时音频、抖音网页缓存……  随时可以清

清缓存：  python bot_setup\tools\botctl.py clean-cache      （先 --dry 看看会删什么）
备份她：  python bot_setup\tools\botctl.py backup-self      （加 --accounts 连登录一起）
人格和聊天记录还在 AstrBot 的 data_v4.db 里，backup-self 会一起备份。
