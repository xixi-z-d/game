# MySQL 配置

后端支持两种账号存储方式：

- 未配置 MySQL 环境变量时，使用本地 `users.json`
- 配置完整的 MySQL 环境变量后，自动使用 MySQL

应用启动时会自动创建 `users` 表，也可以手动执行 `schema.mysql.sql`。

## 本地 MySQL

复制配置模板：

```powershell
Copy-Item .env.example .env
```

修改 `.env` 中的两个密码，然后启动：

```powershell
docker compose up --build
```

访问 `http://localhost:8765`。

## 从 users.json 迁移

先设置与目标数据库一致的环境变量，然后执行：

```powershell
python migrate_accounts.py
```

迁移只会插入或更新账号，不会删除 MySQL 中已有的其他账号。

## 云数据库

生产环境至少需要：

- 固定 MySQL 8.x 主机和数据库
- 独立应用账号，不使用 root
- 强制 TLS 时设置 `MYSQL_SSL=true`
- 如提供 CA 文件，设置 `MYSQL_SSL_CA`
- 每日自动备份

不要把密码提交到 GitHub。部署平台通过 Secret 或环境变量注入。
