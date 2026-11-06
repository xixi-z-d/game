---
title: Draw Together
emoji: 🎨
colorFrom: yellow
colorTo: red
sdk: docker
app_port: 8765
pinned: false
---

# 一起画

一个支持账号注册、好友在线状态、多人聊天猜词和实时同步画板的网页小游戏。

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/xixi-z-d/game)

Docker 镜像默认监听 `8765`。云平台注入 `PORT` 环境变量时会自动使用平台端口。

账号文件默认位于 `/app/data/users.json`，可通过 `DRAW_ACCOUNTS_FILE` 修改。

## Android

原生 Android WebView 工程位于 `android/`，应用包名为
`com.xixizd.drawtogether`。构建和签名说明见 `android/README.md`。

GitHub Actions 可以自动构建 Debug APK：

```text
.github/workflows/android.yml
```

应用内已提供隐私政策、用户协议和账号删除说明：

- `http://localhost:8765/privacy`
- `http://localhost:8765/terms`
- `http://localhost:8765/account-deletion`

生产环境必须替换为正式隐私政策内容和正式管理员密钥。

## 微信原生小游戏

`minigame/` 是可导入微信开发者工具的原生 Canvas 小游戏工程，不依赖 DOM 或外部库。导入后，在“连接配置”中填写 WebSocket 地址（本地服务通常为 `ws://电脑局域网IP:8765/ws`），使用开发测试账号登录或注册。小游戏支持房间码、实时画板、聊天猜词和有限自动重连，具体导入步骤见 `minigame/README.md`。

服务端已提供微信登录接口，需配置 `WECHAT_APPID`、`WECHAT_APPSECRET`、`WECHAT_TOKEN_SECRET`。小游戏“微信快捷登录”会调用 `wx.login()` 并通过短期 token 认证；开发测试账号仍可用于本地调试。`AppSecret` 只能保存在服务端环境变量中，不能写进小游戏客户端。

## MySQL

配置 `MYSQL_HOST`、`MYSQL_USER`、`MYSQL_PASSWORD` 和
`MYSQL_DATABASE` 后，服务端会自动改用 MySQL。详细说明见 `MYSQL_SETUP.md`。
