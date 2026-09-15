# 《最后的晚餐》2026-10-06 高频余票监控（Bark 免费推送版）

每约 2 分钟检查一次 Vivaticket 官方页面。发现 2026 年 10 月 6 日从“无票”变为可选后，立即向 iPhone 发送 Bark 锁屏推送；持续有票时每 10 分钟再次提醒，直到售罄。通知可直接打开官方购票页面。

程序只负责监控和通知，不会自动下单。

## 只有 iPhone：使用免费云端版

不需要电脑常开。使用一个独立的 GitHub 公共仓库运行监控，Bark URL 保存在加密的 Actions Secret 中，不会显示在公开代码里。

1. 在 GitHub 新建一个空的 **Public** 仓库，建议命名 `last-supper-ticket-monitor`。
2. 将本项目文件放入仓库。若由 ChatGPT 协助，在仓库建好后告知仓库名即可。
3. 进入仓库 `Settings → Secrets and variables → Actions → New repository secret`。
4. Name 填写 `BARK_URL`；Secret 粘贴 Bark 首页显示的完整推送 URL。
5. 进入 `Actions → Last Supper ticket monitor → Run workflow` 运行一次测试。

云端版在 2026-09-15 至 2026-10-06 期间每 5 分钟尝试检查一次。GitHub 的定时任务可能偶尔延迟，因此建议保留 ChatGPT 每小时监控作为备用。

## 第一步：在 iPhone 设置 Bark

1. 在 App Store 搜索并安装 `Bark`（开发者 Finb）。
2. 打开 Bark，允许通知。
3. 在 Bark 首页复制推送 URL，格式类似 `https://api.day.app/一串设备密钥`。
4. 在 iPhone“设置 → 通知 → Bark”中开启“允许通知”、锁定屏幕、横幅和声音。
5. 建议在 Bark 设置中允许时效性通知；如系统提供“关键提醒”权限，也一并打开。

推送 URL 相当于通知密码，不要发给别人，也不要上传到公开仓库。

## 第二步：安装并测试

电脑必须保持开机和联网。

### macOS

1. 安装 Python 3（若尚未安装）。
2. 双击 `install_and_setup.command`。
3. 粘贴 Bark 推送 URL；邮件备用可以选择不配置。
4. 收到测试推送后，双击 `start_monitor.command`。

若系统阻止双击，可在终端进入本文件夹后执行：

```bash
chmod +x install_and_setup.command start_monitor.command
./install_and_setup.command
./start_monitor.command
```

### Windows

1. 安装 Python 3，并勾选“Add Python to PATH”。
2. 双击 `install_and_setup.bat`。
3. 粘贴 Bark 推送 URL并确认收到测试推送。
4. 双击 `start_monitor.bat`，命令窗口保持打开。

## 服务器 / NAS 常驻（推荐）

先在本机运行一次配置向导生成 `.env`，然后执行：

```bash
docker compose up -d --build
docker compose logs -f
```

服务器运行后，电脑不需要保持开机。程序包含异常重试、状态持久化和通知去重；设备重启后会自动恢复。

## 当前规则

- 官方页面：`https://cenacolovinciano.vivaticket.it/en/event/cenacolo-vinciano/151991`
- 日期：2026-10-06
- 默认间隔：120 秒，并加入 ±15 秒随机抖动，最低 60 秒
- 首次发现余票：立即响铃推送
- 持续有票：每 10 分钟再次提醒
- 售罄后重新放票：再次立即推送
- 点击通知：打开官方购票页
- 有票时：保存网页截图到 `data/screenshots/`
- 连续三次检查失败：发送一条监控异常通知

## 调整提醒级别

默认使用 iOS 时效性通知。编辑 `.env`：

```text
BARK_LEVEL=timeSensitive
```

如果 Bark 和 iOS 设置均已允许关键提醒，可尝试：

```text
BARK_LEVEL=critical
```

关键提醒可能绕过静音和勿扰模式，请谨慎使用。

## 修改检查频率

编辑 `.env`：

```text
CHECK_INTERVAL_SECONDS=120
```

不建议低于 60 秒，以免给官网造成过多请求或触发限制。

## 停止监控

本机窗口运行时按 `Ctrl+C`。Docker 运行时执行：

```bash
docker compose stop
```

## 重要说明

网页结构、网络故障、验证码或网站限制都可能影响监控；最终余票以官方结算页为准。建议保留原有 ChatGPT 每小时监控，作为独立备用通知。
