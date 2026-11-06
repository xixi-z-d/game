# 部署到 Render

项目已经包含 Dockerfile 和 Render Blueprint。推荐使用 Render：

- 免费 HTTPS 域名：`https://<service-name>.onrender.com`
- 自动支持安全 WebSocket：`wss://`
- 云平台会通过 `PORT` 环境变量指定监听端口，`game.py` 已适配

## 准备代码仓库

先创建 GitHub 仓库，然后在本目录执行：

```powershell
git init
git add .
git commit -m "Prepare draw game for deployment"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

`users.json` 已被 `.dockerignore` 排除，不会把本机账号和密码哈希上传到镜像。

## 一键创建 Render 服务

1. 登录 [Render](https://render.com/)。
2. 选择 **New → Blueprint**。
3. 连接上面的 GitHub 仓库。
4. Render 会自动读取 `render.yaml` 并创建 Web Service。
5. 部署完成后，控制台会显示 `https://<service-name>.onrender.com`。

## 本地验证镜像

```powershell
docker build -t draw-together .
docker run --rm -p 8765:8765 draw-together
```

访问 `http://localhost:8765`。

## 账号持久化

免费 Web Service 的容器文件系统是临时的，重新部署或实例重建后
`/app/data/users.json` 可能丢失。

如果需要长期保存用户：

1. 在 Render 中创建持久磁盘。
2. 将磁盘挂载到 `/app/data`。
3. 保持环境变量 `DRAW_ACCOUNTS_FILE=/app/data/users.json`。

## 自定义域名

服务部署成功后，可以在 Render 的 **Settings → Custom Domains** 中添加
自己的域名，并按页面提示配置 DNS 的 `CNAME` 记录。

## 免费实例说明

Render 免费实例长时间无人访问时会休眠。再次打开页面可能需要等待几十秒冷启动。
