# Android 构建与上架

应用包名：`com.xixizd.drawtogether`

## 构建环境

- JDK 17
- Android SDK Platform 36
- Android SDK Build Tools

可直接用 Android Studio 打开本目录。命令行构建：

```powershell
cd C:\gameproject\android
.\gradlew.bat assembleDebug
```

Debug APK 输出到：

```text
app/build/outputs/apk/debug/app-debug.apk
```

## 配置正式服务器

发布前必须把 `gradle.properties` 中的 `APP_URL` 改成永久 HTTPS 地址：

```properties
APP_URL=https://你的正式域名
```

也可以在构建时覆盖：

```powershell
.\gradlew.bat bundleRelease -PAPP_URL=https://你的正式域名
```

Android 应用只通过 HTTPS/WSS 与后端通信。正式版不会允许明文 HTTP。

## Google Play 发布

1. 注册 Google Play Console 个人开发者账号并完成身份验证。
2. 使用 Android Studio 创建上传密钥：
   **Build → Generate Signed App Bundle or APK**。
3. 妥善备份 keystore 和密码，不要提交到 Git。
4. 构建 Android App Bundle：

```powershell
.\gradlew.bat bundleRelease -PAPP_URL=https://你的正式域名
```

5. AAB 输出位置：

```text
app/build/outputs/bundle/release/app-release.aab
```

6. 在 Play Console 填写 Data Safety、内容分级、隐私政策和账号删除说明。
7. 新个人开发者账号通常需要先完成封闭测试，具体人数和周期以 Google Play 当前政策为准。

## 发布前必须替换

- 临时 Back4app 地址
- 测试用户和测试房间
- 正式隐私政策、用户协议与账号删除入口
- 举报聊天、屏蔽用户和敏感词审核
- 永久 MySQL 数据库及备份
