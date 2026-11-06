"""Minimal multiplayer drawing board.

Run:
    python game.py

Then open http://localhost:8765 in two or more browser windows.
Requires websockets 13.x.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import random
import re
import secrets
import socket
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol, serve


HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8765"))
MAX_NAME_LENGTH = 20
MAX_NICKNAME_LENGTH = 20
MAX_BIO_LENGTH = 160
MAX_CHAT_LENGTH = 200
MAX_REPORT_REASON_LENGTH = 500
MAX_PASSWORD_LENGTH = 20
MAX_STROKES = 50_000
ROUND_SECONDS = 60
MAX_ROUNDS = 5
PASSWORD_ITERATIONS = 260_000
ACCOUNT_FILE = Path(
    os.environ.get("DRAW_ACCOUNTS_FILE")
    or Path(__file__).with_name("users.json")
)
REPORT_FILE = Path(
    os.environ.get("DRAW_REPORTS_FILE")
    or ACCOUNT_FILE.with_name("reports.json")
)
MYSQL_HOST = os.environ.get("MYSQL_HOST", "").strip()
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "").strip()
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "").strip()
MYSQL_SSL = os.environ.get("MYSQL_SSL", "").strip().lower() in {"1", "true", "yes"}
MYSQL_SSL_CA = os.environ.get("MYSQL_SSL_CA", "").strip()
MYSQL_ENABLED = bool(MYSQL_HOST and MYSQL_USER and MYSQL_DATABASE)
WECHAT_APPID = os.environ.get("WECHAT_APPID", "").strip()
WECHAT_APPSECRET = os.environ.get("WECHAT_APPSECRET", "").strip()
WECHAT_TOKEN_SECRET = os.environ.get("WECHAT_TOKEN_SECRET", "").strip()
WECHAT_TOKEN_TTL = 15 * 60
WECHAT_TOKENS: dict[str, tuple[str, float]] = {}
PRIVACY_VERSION = os.environ.get("PRIVACY_VERSION", "1").strip() or "1"
ADMIN_USERNAME = (
    os.environ.get("ADMIN_USERNAME") or os.environ.get("ADMIN_USER") or ""
).strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_NICKNAME = os.environ.get("ADMIN_NICKNAME", "管理员").strip()[:MAX_NICKNAME_LENGTH]
USERNAME_PATTERN = re.compile(r"^[0-9A-Za-z_\u4e00-\u9fff]{2,20}$")
COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")


def configured_sensitive_words() -> tuple[str, ...]:
    values: list[str] = []
    values.extend(re.split(r"[,\n\r]+", os.environ.get("SENSITIVE_WORDS", "")))
    word_file = os.environ.get("SENSITIVE_WORDS_FILE", "").strip()
    if word_file:
        try:
            values.extend(Path(word_file).read_text(encoding="utf-8").splitlines())
        except OSError as error:
            print(f"[敏感词] 无法读取 {word_file}: {error}", flush=True)
    return tuple(
        sorted(
            {word.strip().casefold() for word in values if word.strip()},
            key=len,
            reverse=True,
        )
    )


SENSITIVE_WORDS = configured_sensitive_words()
WORD_BANK = (
    "太阳",
    "月亮",
    "雨伞",
    "小猫",
    "狗",
    "长颈鹿",
    "冰淇淋",
    "生日蛋糕",
    "自行车",
    "热气球",
    "机器人",
    "仙人掌",
    "电视机",
    "汉堡包",
    "草莓",
    "火箭",
    "章鱼",
    "雪人",
    "海盗船",
    "彩虹",
    "吉他",
    "恐龙",
    "宇航员",
    "火锅",
    "蘑菇",
    "摩天轮",
    "电风扇",
    "笔记本电脑",
    "兔子",
    "鲨鱼",
    "钢琴",
    "牙刷",
    "风车",
    "潜水艇",
    "披萨",
    "眼镜",
    "小丑",
    "灯塔",
    "西瓜",
    "蝴蝶",
    "帐篷",
)
WORD_PINYIN = {
    "太阳": "taiyang",
    "月亮": "yueliang",
    "雨伞": "yusan",
    "小猫": "xiaomao",
    "狗": "gou",
    "长颈鹿": "changjinglu",
    "冰淇淋": "bingqilin",
    "生日蛋糕": "shengridangao",
    "自行车": "zixingche",
    "热气球": "reqiqiu",
    "机器人": "jiqiren",
    "仙人掌": "xianrenzhang",
    "电视机": "dianshiji",
    "汉堡包": "hanbaobao",
    "草莓": "caomei",
    "火箭": "huojian",
    "章鱼": "zhangyu",
    "雪人": "xueren",
    "海盗船": "haidaochuan",
    "彩虹": "caihong",
    "吉他": "jita",
    "恐龙": "konglong",
    "宇航员": "yuhangyuan",
    "火锅": "huoguo",
    "蘑菇": "mogu",
    "摩天轮": "motianlun",
    "电风扇": "dianfengshan",
    "笔记本电脑": "bijibendiannao",
    "兔子": "tuzi",
    "鲨鱼": "shayu",
    "钢琴": "gangqin",
    "牙刷": "yashua",
    "风车": "fengche",
    "潜水艇": "qianshuiting",
    "披萨": "pisa",
    "眼镜": "yanjing",
    "小丑": "xiaochou",
    "灯塔": "dengta",
    "西瓜": "xigua",
    "蝴蝶": "hudie",
    "帐篷": "zhangpeng",
}
if set(WORD_BANK) != set(WORD_PINYIN):
    missing_pinyin = sorted(set(WORD_BANK) - set(WORD_PINYIN))
    extra_pinyin = sorted(set(WORD_PINYIN) - set(WORD_BANK))
    raise RuntimeError(
        f"Pinyin mapping mismatch: missing={missing_pinyin}, extra={extra_pinyin}"
    )
PLAYER_COLORS = (
    "#ff6b57",
    "#3d9be9",
    "#35a777",
    "#f0a91b",
    "#9b6bd6",
    "#e05b93",
    "#4a9e9b",
    "#7d8b36",
)


@dataclass
class Client:
    websocket: WebSocketServerProtocol
    client_id: str
    name: str
    role: str
    color: str
    score: int = 0


@dataclass
class Session:
    websocket: WebSocketServerProtocol
    username: str
    client: Client | None = None
    room: "Room | None" = None


@dataclass
class Room:
    room_code: str | None = None
    clients: dict[WebSocketServerProtocol, Client] = field(default_factory=dict)
    player_order: list[WebSocketServerProtocol] = field(default_factory=list)
    strokes: list[dict[str, Any]] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    turn_index: int = 0
    round_number: int = 0
    round_id: int = 0
    current_word: str | None = None
    round_deadline: float | None = None
    timer_task: asyncio.Task[None] | None = None
    drawn_client_ids: set[str] = field(default_factory=set)
    game_over: bool = False
    owner_username: str | None = None
    invited_usernames: set[str] = field(default_factory=set)

    def unique_name(self, requested_name: str) -> str:
        base = requested_name.strip()[:MAX_NAME_LENGTH] or "游客"
        existing = {client.name for client in self.clients.values()}
        if base not in existing:
            return base
        index = 2
        while f"{base} ({index})" in existing:
            index += 1
        return f"{base} ({index})"

    def next_color(self) -> str:
        used = {client.color for client in self.clients.values()}
        for color in PLAYER_COLORS:
            if color not in used:
                return color
        return PLAYER_COLORS[len(self.clients) % len(PLAYER_COLORS)]

    def player_payload(self) -> list[dict[str, Any]]:
        return [
            {
                "id": client.client_id,
                "name": client.name,
                "role": client.role,
                "color": client.color,
                "score": client.score,
            }
            for client in self.clients.values()
        ]

    async def broadcast(self, payload: dict[str, Any]) -> None:
        if not self.clients:
            return
        message = encode(payload)
        await asyncio.gather(
            *(
                client.send(message)
                for client in list(self.clients)
            ),
            return_exceptions=True,
        )

    async def broadcast_presence(self) -> None:
        await self.broadcast(
            {
                "type": "presence",
                "players": self.player_payload(),
                "count": len(self.clients),
            }
        )

    def clients_in_order(self) -> list[Client]:
        return [
            self.clients[websocket]
            for websocket in self.player_order
            if websocket in self.clients
        ]

    def current_player(self) -> Client | None:
        players = self.clients_in_order()
        if not players:
            return None
        self.turn_index %= len(players)
        return players[self.turn_index]

    def sync_roles(self) -> Client | None:
        players = self.clients_in_order()
        if not players:
            return None
        self.turn_index %= len(players)
        drawer = players[self.turn_index]
        for player in players:
            player.role = "drawer" if player is drawer else "guesser"
        return drawer

    def round_payload(self) -> dict[str, Any] | None:
        drawer = self.current_player()
        if drawer is None:
            return None
        remaining = ROUND_SECONDS
        if self.round_deadline is not None:
            remaining = max(0, math.ceil(self.round_deadline - asyncio.get_running_loop().time()))
        return {
            "roundNumber": self.round_number,
            "drawerId": drawer.client_id,
            "drawerName": drawer.name,
            "duration": ROUND_SECONDS,
            "remaining": max(0, remaining),
            "maxRounds": MAX_ROUNDS,
        }

    def ranking_payload(self) -> list[dict[str, Any]]:
        players = sorted(
            self.clients_in_order(),
            key=lambda player: player.score,
            reverse=True,
        )
        ranking = []
        previous_score: int | None = None
        rank = 0
        for index, player in enumerate(players, start=1):
            if previous_score is None or player.score != previous_score:
                rank = index
                previous_score = player.score
            ranking.append(
                {
                    "rank": rank,
                    "playerId": player.client_id,
                    "name": player.name,
                    "score": player.score,
                    "color": player.color,
                }
            )
        return ranking

    def should_end_game(self) -> bool:
        player_ids = {player.client_id for player in self.clients_in_order()}
        return (
            self.round_number >= MAX_ROUNDS
            and bool(player_ids)
            and player_ids.issubset(self.drawn_client_ids)
        )

    def cancel_timer(self) -> None:
        task = self.timer_task
        self.timer_task = None
        self.round_deadline = None
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()

    async def send_private_word(self, drawer: Client) -> bool:
        try:
            await drawer.websocket.send(
                encode(
                    {
                        "type": "word",
                        "word": self.current_word,
                        "roundNumber": self.round_number,
                    }
                )
            )
            return True
        except ConnectionClosed:
            return False

    async def begin_round(self) -> None:
        if self.game_over:
            return
        drawer = self.sync_roles()
        if drawer is None:
            return
        self.cancel_timer()
        self.round_number += 1
        self.round_id += 1
        self.current_word = random.choice(WORD_BANK)
        self.drawn_client_ids.add(drawer.client_id)
        self.round_deadline = asyncio.get_running_loop().time() + ROUND_SECONDS
        round_payload = self.round_payload()
        if round_payload is None:
            return
        await self.broadcast(
            {
                "type": "round_started",
                **round_payload,
            }
        )
        word_sent = await self.send_private_word(drawer)
        await self.broadcast_presence()
        if not word_sent:
            return
        self.timer_task = asyncio.create_task(
            self.round_timer(self.round_id),
            name=f"drawing-round-{self.round_id}",
        )

    async def round_timer(self, round_id: int) -> None:
        try:
            await asyncio.sleep(ROUND_SECONDS)
            async with self.lock:
                if round_id != self.round_id or not self.clients:
                    return
                await self.finish_round("timeout")
        except asyncio.CancelledError:
            pass

    async def finish_round(self, reason: str, *, rotate: bool = True) -> None:
        self.cancel_timer()
        self.strokes.clear()
        await self.broadcast({"type": "clear", "reason": reason})
        if rotate:
            self.turn_index += 1
        if self.should_end_game():
            await self.end_game()
            return
        self.sync_roles()
        await self.begin_round()

    async def drawer_disconnected(self) -> None:
        await self.finish_round("drawer-left", rotate=False)

    async def end_game(self) -> None:
        self.game_over = True
        self.cancel_timer()
        self.strokes.clear()
        self.current_word = None
        self.round_deadline = None
        ranking = self.ranking_payload()
        await self.broadcast_presence()
        await self.broadcast(
            {
                "type": "game_over",
                "roundsPlayed": self.round_number,
                "ranking": ranking,
                "message": "游戏结束！",
            }
        )

    async def restart_game(self) -> bool:
        if not self.game_over:
            return False
        self.cancel_timer()
        self.game_over = False
        self.strokes.clear()
        self.drawn_client_ids.clear()
        self.turn_index = 0
        self.round_number = 0
        self.round_id += 1
        self.current_word = None
        self.round_deadline = None
        for player in self.clients_in_order():
            player.score = 0
        await self.broadcast({"type": "game_reset"})
        self.sync_roles()
        await self.begin_round()
        return True

    async def remove_client(self, websocket: WebSocketServerProtocol) -> None:
        players = self.clients_in_order()
        removed_index = next(
            (index for index, player in enumerate(players) if player.websocket is websocket),
            None,
        )
        if removed_index is None:
            return

        removed = players[removed_index]
        was_drawer = removed.role == "drawer"
        was_owner = username_key(removed.name) == self.owner_username
        self.clients.pop(websocket, None)
        self.player_order.pop(removed_index)
        self.invited_usernames.discard(removed.name)

        if not self.clients:
            self.cancel_timer()
            self.strokes.clear()
            self.turn_index = 0
            self.round_number = 0
            self.round_id += 1
            self.current_word = None
            self.round_deadline = None
            self.drawn_client_ids.clear()
            self.game_over = False
            self.owner_username = None
            self.invited_usernames.clear()
            return

        if was_owner:
            self.owner_username = username_key(self.clients_in_order()[0].name)

        if self.game_over:
            await self.broadcast_presence()
            return

        if was_drawer:
            if self.turn_index >= len(self.clients):
                self.turn_index = 0
            await self.drawer_disconnected()
            return

        if removed_index < self.turn_index:
            self.turn_index -= 1
        self.sync_roles()
        await self.broadcast_presence()


ROOM = Room()
ROOMS: dict[str, Room] = {}
SESSIONS: dict[WebSocketServerProtocol, Session] = {}


def session_room(session: Session) -> Room | None:
    return session.room


def new_room_code() -> str:
    while True:
        code = f"{secrets.randbelow(1_000_000):06d}"
        if code not in ROOMS:
            return code


def room_for_code(code: Any) -> Room | None:
    if not isinstance(code, str):
        return None
    return ROOMS.get(code.strip())


def mysql_connection():
    try:
        import pymysql
    except ImportError as error:
        raise RuntimeError(
            "缺少 PyMySQL，请先安装：python -m pip install PyMySQL==1.1.1"
        ) from error

    options: dict[str, Any] = {
        "host": MYSQL_HOST,
        "port": MYSQL_PORT,
        "user": MYSQL_USER,
        "password": MYSQL_PASSWORD,
        "database": MYSQL_DATABASE,
        "charset": "utf8mb4",
        "autocommit": False,
        "connect_timeout": 10,
        "read_timeout": 20,
        "write_timeout": 20,
    }
    if MYSQL_SSL_CA:
        options["ssl"] = {"ca": MYSQL_SSL_CA}
    elif MYSQL_SSL:
        options["ssl"] = {"check_hostname": True}
    try:
        return pymysql.connect(**options)
    except Exception as error:
        raise RuntimeError(
            f"无法连接 MySQL {MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}: {error}"
        ) from error


def ensure_mysql_schema() -> None:
    connection = mysql_connection()
    user_columns = {
        "nickname": "VARCHAR(20) NOT NULL DEFAULT ''",
        "bio": "VARCHAR(160) NOT NULL DEFAULT ''",
        "privacy_version": "VARCHAR(32) NULL",
        "privacy_accepted_at": "BIGINT NULL",
        "role": "VARCHAR(16) NOT NULL DEFAULT 'user'",
        "muted_until": "BIGINT NULL",
        "banned_until": "BIGINT NULL",
        "ban_reason": "VARCHAR(255) NOT NULL DEFAULT ''",
        "blocked_users_json": "LONGTEXT NOT NULL DEFAULT '[]'",
    }
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_key VARCHAR(64) PRIMARY KEY,
                    username VARCHAR(20) NOT NULL UNIQUE,
                    salt CHAR(32) NOT NULL,
                    password_hash CHAR(64) NOT NULL,
                    password_iterations INT NOT NULL,
                    created_at BIGINT NOT NULL,
                    nickname VARCHAR(20) NOT NULL DEFAULT '',
                    bio VARCHAR(160) NOT NULL DEFAULT '',
                    privacy_version VARCHAR(32) NULL,
                    privacy_accepted_at BIGINT NULL,
                    role VARCHAR(16) NOT NULL DEFAULT 'user',
                    muted_until BIGINT NULL,
                    banned_until BIGINT NULL,
                    ban_reason VARCHAR(255) NOT NULL DEFAULT '',
                    friends_json LONGTEXT NOT NULL,
                    friend_requests_json LONGTEXT NOT NULL,
                    blocked_users_json LONGTEXT NOT NULL DEFAULT '[]'
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS reports (
                    report_id CHAR(32) PRIMARY KEY,
                    report_type VARCHAR(20) NOT NULL,
                    reporter_key VARCHAR(64) NOT NULL,
                    target_key VARCHAR(64) NULL,
                    target_username VARCHAR(20) NOT NULL DEFAULT '',
                    reason VARCHAR(500) NOT NULL,
                    message_text VARCHAR(200) NOT NULL DEFAULT '',
                    message_id VARCHAR(80) NOT NULL DEFAULT '',
                    status VARCHAR(20) NOT NULL DEFAULT 'open',
                    action VARCHAR(32) NOT NULL DEFAULT '',
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL,
                    metadata_json LONGTEXT NOT NULL
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                """
            )
            cursor.execute(
                """
                SELECT COLUMN_NAME FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'users'
                """,
                (MYSQL_DATABASE,),
            )
            existing = {str(row[0]) for row in cursor.fetchall()}
            for name, definition in user_columns.items():
                if name not in existing:
                    cursor.execute(
                        f"ALTER TABLE users ADD COLUMN {name} {definition}"
                    )
            cursor.execute(
                "UPDATE users SET nickname = username WHERE nickname = '' OR nickname IS NULL"
            )
        connection.commit()
    finally:
        connection.close()


def normalize_account(account: dict[str, Any]) -> dict[str, Any]:
    account.setdefault("friends", [])
    account.setdefault("friendRequests", [])
    account.setdefault("blockedUsers", [])
    account.setdefault("nickname", account.get("username", ""))
    account.setdefault("bio", "")
    account.setdefault("privacyVersion", None)
    account.setdefault("privacyAcceptedAt", None)
    account.setdefault("role", "user")
    account.setdefault("mutedUntil", 0)
    account.setdefault("bannedUntil", 0)
    account.setdefault("banReason", "")
    return account


def load_accounts_mysql() -> dict[str, dict[str, Any]]:
    ensure_mysql_schema()
    connection = mysql_connection()
    accounts: dict[str, dict[str, Any]] = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT user_key, username, salt, password_hash,
                       password_iterations, created_at, friends_json,
                       friend_requests_json, nickname, bio, privacy_version,
                       privacy_accepted_at, role, muted_until, banned_until,
                       ban_reason, blocked_users_json
                FROM users
                """
            )
            for row in cursor.fetchall():
                accounts[str(row[0])] = normalize_account({
                    "username": str(row[1]),
                    "salt": str(row[2]),
                    "passwordHash": str(row[3]),
                    "iterations": int(row[4]),
                    "createdAt": int(row[5]),
                    "friends": json.loads(row[6] or "[]"),
                    "friendRequests": json.loads(row[7] or "[]"),
                    "nickname": str(row[8] or row[1]),
                    "bio": str(row[9] or ""),
                    "privacyVersion": row[10],
                    "privacyAcceptedAt": row[11],
                    "role": str(row[12] or "user"),
                    "mutedUntil": int(row[13] or 0),
                    "bannedUntil": int(row[14] or 0),
                    "banReason": str(row[15] or ""),
                    "blockedUsers": json.loads(row[16] or "[]"),
                })
    finally:
        connection.close()
    return accounts


def save_accounts_mysql() -> None:
    ensure_mysql_schema()
    connection = mysql_connection()
    try:
        rows = []
        for key, raw_account in ACCOUNTS.items():
            account = normalize_account(raw_account)
            rows.append(
                (
                    key,
                    account["username"],
                    account["salt"],
                    account["passwordHash"],
                    int(account["iterations"]),
                    int(account["createdAt"]),
                    str(account.get("nickname") or account["username"]),
                    str(account.get("bio", "")),
                    account.get("privacyVersion"),
                    account.get("privacyAcceptedAt"),
                    str(account.get("role", "user")),
                    int(account.get("mutedUntil") or 0),
                    int(account.get("bannedUntil") or 0),
                    str(account.get("banReason", "")),
                    json.dumps(account.get("friends", []), ensure_ascii=False),
                    json.dumps(account.get("friendRequests", []), ensure_ascii=False),
                    json.dumps(account.get("blockedUsers", []), ensure_ascii=False),
                )
            )
        with connection.cursor() as cursor:
            if rows:
                cursor.executemany(
                    """
                    INSERT INTO users (
                        user_key, username, salt, password_hash,
                        password_iterations, created_at, nickname, bio,
                        privacy_version, privacy_accepted_at, role, muted_until,
                        banned_until, ban_reason, friends_json,
                        friend_requests_json, blocked_users_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        username = VALUES(username), salt = VALUES(salt),
                        password_hash = VALUES(password_hash),
                        password_iterations = VALUES(password_iterations),
                        created_at = VALUES(created_at), nickname = VALUES(nickname),
                        bio = VALUES(bio), privacy_version = VALUES(privacy_version),
                        privacy_accepted_at = VALUES(privacy_accepted_at),
                        role = VALUES(role), muted_until = VALUES(muted_until),
                        banned_until = VALUES(banned_until), ban_reason = VALUES(ban_reason),
                        friends_json = VALUES(friends_json),
                        friend_requests_json = VALUES(friend_requests_json),
                        blocked_users_json = VALUES(blocked_users_json)
                    """,
                    rows,
                )
        connection.commit()
    except Exception as error:
        connection.rollback()
        print(
            f"\n[MySQL 保存失败] {MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}\n"
            f"系统错误：{error}\n",
            flush=True,
        )
        raise OSError(f"MySQL 保存失败: {error}") from error
    finally:
        connection.close()


def load_accounts() -> dict[str, dict[str, Any]]:
    if MYSQL_ENABLED:
        return load_accounts_mysql()
    if not ACCOUNT_FILE.exists():
        return {}
    try:
        data = json.loads(ACCOUNT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"无法读取账号文件 {ACCOUNT_FILE}: {error}") from error
    users = data.get("users") if isinstance(data, dict) else None
    if not isinstance(users, dict):
        raise RuntimeError(f"账号文件格式无效: {ACCOUNT_FILE}")
    for key, account in list(users.items()):
        if isinstance(account, dict):
            users[key] = normalize_account(account)
    return users


def save_accounts() -> None:
    if MYSQL_ENABLED:
        save_accounts_mysql()
        return
    for account in ACCOUNTS.values():
        normalize_account(account)
    payload = json.dumps(
        {"version": 2, "users": ACCOUNTS},
        ensure_ascii=False,
        indent=2,
    )
    try:
        # parents=True 会自动创建账号文件所需的父目录。
        ACCOUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
        ACCOUNT_FILE.write_text(payload, encoding="utf-8")
    except PermissionError as error:
        print(
            f"\n[账号保存失败] 无法写入 {ACCOUNT_FILE}\n"
            "请关闭可能占用该文件的程序，并确认项目目录具有写入权限。\n"
            f"系统错误：{error}\n",
            flush=True,
        )
        raise
    except OSError as error:
        print(
            f"\n[账号保存失败] 写入 {ACCOUNT_FILE} 时发生错误。\n"
            "请检查磁盘空间、目录权限和账号文件状态。\n"
            f"系统错误：{error}\n",
            flush=True,
        )
        raise


def load_reports_mysql() -> list[dict[str, Any]]:
    ensure_mysql_schema()
    connection = mysql_connection()
    reports: list[dict[str, Any]] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT report_id, report_type, reporter_key, target_key,
                       target_username, reason, message_text, message_id,
                       status, action, created_at, updated_at, metadata_json
                FROM reports ORDER BY created_at DESC
                """
            )
            for row in cursor.fetchall():
                try:
                    metadata = json.loads(row[12] or "{}")
                except (TypeError, json.JSONDecodeError):
                    metadata = {}
                reports.append(
                    {
                        "reportId": str(row[0]),
                        "type": str(row[1]),
                        "reporter": str(row[2]),
                        "target": str(row[3]) if row[3] else "",
                        "targetUsername": str(row[4] or ""),
                        "reason": str(row[5] or ""),
                        "text": str(row[6] or ""),
                        "messageId": str(row[7] or ""),
                        "status": str(row[8] or "open"),
                        "action": str(row[9] or ""),
                        "createdAt": int(row[10]),
                        "updatedAt": int(row[11]),
                        "metadata": metadata,
                    }
                )
    finally:
        connection.close()
    return reports


def save_reports_mysql() -> None:
    ensure_mysql_schema()
    connection = mysql_connection()
    try:
        rows = [
            (
                str(report.get("reportId") or uuid.uuid4().hex),
                str(report.get("type") or "user"),
                str(report.get("reporter") or ""),
                str(report.get("target") or "") or None,
                str(report.get("targetUsername") or ""),
                str(report.get("reason") or ""),
                str(report.get("text") or ""),
                str(report.get("messageId") or ""),
                str(report.get("status") or "open"),
                str(report.get("action") or ""),
                int(report.get("createdAt") or time.time()),
                int(report.get("updatedAt") or time.time()),
                json.dumps(report.get("metadata") or {}, ensure_ascii=False),
            )
            for report in REPORTS
        ]
        with connection.cursor() as cursor:
            if rows:
                cursor.executemany(
                    """
                    INSERT INTO reports (
                        report_id, report_type, reporter_key, target_key,
                        target_username, reason, message_text, message_id,
                        status, action, created_at, updated_at, metadata_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        target_key = VALUES(target_key), target_username = VALUES(target_username),
                        reason = VALUES(reason), message_text = VALUES(message_text),
                        message_id = VALUES(message_id), status = VALUES(status),
                        action = VALUES(action), updated_at = VALUES(updated_at),
                        metadata_json = VALUES(metadata_json)
                    """,
                    rows,
                )
        connection.commit()
    except Exception as error:
        connection.rollback()
        raise OSError(f"MySQL 举报保存失败: {error}") from error
    finally:
        connection.close()


def load_reports() -> list[dict[str, Any]]:
    if MYSQL_ENABLED:
        return load_reports_mysql()
    if not REPORT_FILE.exists():
        return []
    try:
        data = json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"无法读取举报文件 {REPORT_FILE}: {error}") from error
    if isinstance(data, dict):
        data = data.get("reports", [])
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def save_reports() -> None:
    if MYSQL_ENABLED:
        save_reports_mysql()
        return
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(
        json.dumps({"version": 1, "reports": REPORTS}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def username_key(value: str) -> str:
    return value.strip().casefold()


def password_digest(password: str, salt_hex: str, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        iterations,
    ).hex()


def wechat_username(openid: str) -> str:
    digest = hashlib.sha256(
        f"{WECHAT_TOKEN_SECRET}:{openid}".encode("utf-8")
    ).hexdigest()[:17]
    return f"wx_{digest}"


def issue_wechat_token(username: str) -> str:
    token = secrets.token_urlsafe(32)
    WECHAT_TOKENS[token] = (username, time.time() + WECHAT_TOKEN_TTL)
    return token


def verify_wechat_token(token: Any) -> str | None:
    if not isinstance(token, str):
        return None
    value = WECHAT_TOKENS.get(token)
    if value is None:
        return None
    username, expires_at = value
    if expires_at <= time.time():
        WECHAT_TOKENS.pop(token, None)
        return None
    return username


def wechat_account(code: str) -> tuple[bool, str]:
    if not WECHAT_APPID or not WECHAT_APPSECRET or not WECHAT_TOKEN_SECRET:
        return False, "微信登录未配置，请设置 WECHAT_APPID、WECHAT_APPSECRET、WECHAT_TOKEN_SECRET"
    query = urlencode({"appid": WECHAT_APPID, "secret": WECHAT_APPSECRET, "js_code": code, "grant_type": "authorization_code"})
    try:
        with urlopen(f"https://api.weixin.qq.com/sns/jscode2session?{query}", timeout=8) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False, "微信服务暂时不可用"
    openid = result.get("openid") if isinstance(result, dict) else None
    if not isinstance(openid, str) or not openid:
        return False, "微信登录失败，请检查 code"
    username = wechat_username(openid)
    if username_key(username) not in ACCOUNTS:
        ACCOUNTS[username_key(username)] = normalize_account({
            "username": username,
            "nickname": "微信用户",
            "createdAt": int(time.time()),
            "salt": secrets.token_hex(16),
            "passwordHash": "",
            "iterations": PASSWORD_ITERATIONS,
        })
        try:
            save_accounts()
        except OSError:
            ACCOUNTS.pop(username_key(username), None)
            return False, "微信账号创建失败，请稍后重试"
    return True, username


def register_account(username: str, password: str) -> tuple[bool, str]:
    username = username.strip()
    if not USERNAME_PATTERN.fullmatch(username):
        return False, "用户名需为 2-20 个中英文字符、数字或下划线"
    if not 6 <= len(password) <= MAX_PASSWORD_LENGTH:
        return False, f"密码长度需为 6-{MAX_PASSWORD_LENGTH} 个字符"
    key = username_key(username)
    if key in ACCOUNTS:
        return False, "该用户名已注册"

    salt = secrets.token_hex(16)
    ACCOUNTS[key] = normalize_account({
        "username": username,
        "salt": salt,
        "passwordHash": password_digest(password, salt, PASSWORD_ITERATIONS),
        "iterations": PASSWORD_ITERATIONS,
        "createdAt": int(time.time()),
        "nickname": username,
        "friends": [],
        "friendRequests": [],
    })
    try:
        save_accounts()
    except OSError:
        ACCOUNTS.pop(key, None)
        return False, "账号保存失败，请查看运行服务的终端提示"
    return True, username


def verify_account(username: str, password: str) -> tuple[bool, str]:
    account = ACCOUNTS.get(username_key(username))
    if account is None or not 1 <= len(password) <= MAX_PASSWORD_LENGTH:
        return False, "用户名或密码错误"
    try:
        iterations = int(account["iterations"])
        expected = password_digest(password, account["salt"], iterations)
    except (KeyError, TypeError, ValueError):
        return False, "账号数据异常，请联系管理员"
    if not secrets.compare_digest(expected, account.get("passwordHash", "")):
        return False, "用户名或密码错误"
    if account_is_banned(account):
        reason = str(account.get("banReason") or "")
        return False, f"账号已封禁{(': ' + reason) if reason else ''}"
    return True, str(account.get("username") or username.strip())


def relation_keys(account: dict[str, Any], field: str) -> list[str]:
    raw_values = account.get(field, [])
    if not isinstance(raw_values, list):
        raw_values = []
    return [str(value) for value in raw_values]


def send_friend_request(sender: str, target: str) -> tuple[bool, str]:
    sender_key = username_key(sender)
    target_key = username_key(target)
    if sender_key == target_key:
        return False, "不能添加自己为好友"
    target_account = ACCOUNTS.get(target_key)
    sender_account = ACCOUNTS.get(sender_key)
    if sender_account is None or target_account is None:
        return False, "该用户名不存在"
    if target_key in relation_keys(sender_account, "friends"):
        return False, "你们已经是好友"
    if sender_key in relation_keys(target_account, "friendRequests"):
        return False, "好友申请已发送，请等待对方同意"
    if target_key in relation_keys(sender_account, "friendRequests"):
        return False, "对方已向你发送好友申请，请直接接受"
    requests = relation_keys(target_account, "friendRequests")
    target_account["friendRequests"] = [*requests, sender_key]
    try:
        save_accounts()
    except OSError:
        target_account["friendRequests"] = requests
        return False, "好友申请保存失败，请稍后重试"
    return True, "好友申请已发送"


def accept_friend_request(user: str, requester: str) -> tuple[bool, str]:
    user_key = username_key(user)
    requester_key = username_key(requester)
    user_account = ACCOUNTS.get(user_key)
    requester_account = ACCOUNTS.get(requester_key)
    if user_account is None or requester_account is None:
        return False, "账号不存在"
    requests = relation_keys(user_account, "friendRequests")
    if requester_key not in requests:
        return False, "该好友申请已失效"
    old_friends_user = relation_keys(user_account, "friends")
    old_friends_requester = relation_keys(requester_account, "friends")
    user_account["friendRequests"] = [key for key in requests if key != requester_key]
    user_account["friends"] = list(dict.fromkeys([*old_friends_user, requester_key]))
    requester_account["friends"] = list(dict.fromkeys([*old_friends_requester, user_key]))
    try:
        save_accounts()
    except OSError:
        user_account["friendRequests"] = requests
        user_account["friends"] = old_friends_user
        requester_account["friends"] = old_friends_requester
        return False, "好友关系保存失败，请稍后重试"
    return True, "已添加好友"


def reject_friend_request(user: str, requester: str) -> bool:
    user_key = username_key(user)
    requester_key = username_key(requester)
    user_account = ACCOUNTS.get(user_key)
    if user_account is None:
        return False
    requests = relation_keys(user_account, "friendRequests")
    if requester_key not in requests:
        return False
    user_account["friendRequests"] = [key for key in requests if key != requester_key]
    try:
        save_accounts()
    except OSError:
        user_account["friendRequests"] = requests
        return False
    return True


def remove_friend(user: str, friend: str) -> bool:
    user_key = username_key(user)
    friend_key = username_key(friend)
    user_account = ACCOUNTS.get(user_key)
    friend_account = ACCOUNTS.get(friend_key)
    if user_account is None or friend_account is None:
        return False
    old_user = relation_keys(user_account, "friends")
    old_friend = relation_keys(friend_account, "friends")
    user_account["friends"] = [key for key in old_user if key != friend_key]
    friend_account["friends"] = [key for key in old_friend if key != user_key]
    try:
        save_accounts()
    except OSError:
        user_account["friends"] = old_user
        friend_account["friends"] = old_friend
        return False
    return True


def are_friends(user: str, friend: str) -> bool:
    user_account = ACCOUNTS.get(username_key(user))
    friend_account = ACCOUNTS.get(username_key(friend))
    if user_account is None or friend_account is None:
        return False
    other_key = username_key(friend)
    own_key = username_key(user)
    return (
        other_key in relation_keys(user_account, "friends")
        and own_key in relation_keys(friend_account, "friends")
    )


def contains_sensitive_word(value: str) -> bool:
    normalized = value.casefold()
    return any(word in normalized for word in SENSITIVE_WORDS)


def validate_profile_text(value: Any, limit: int) -> tuple[bool, str]:
    if not isinstance(value, str):
        return False, "内容格式无效"
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", value).strip()
    if len(cleaned) > limit:
        return False, f"内容不能超过 {limit} 个字符"
    if contains_sensitive_word(cleaned):
        return False, "内容包含不适宜词语"
    return True, cleaned


def account_is_banned(account: dict[str, Any]) -> bool:
    until = int(account.get("bannedUntil") or 0)
    return until > int(time.time())


def account_is_muted(account: dict[str, Any]) -> bool:
    until = int(account.get("mutedUntil") or 0)
    return until > int(time.time())


def profile_payload(username: str) -> dict[str, Any]:
    key = username_key(username)
    account = normalize_account(ACCOUNTS.get(key, {}))
    return {
        "type": "profile_get",
        "username": str(account.get("username") or username),
        "nickname": str(account.get("nickname") or account.get("username") or username),
        "bio": str(account.get("bio") or ""),
        "privacyVersion": account.get("privacyVersion"),
        "privacyAccepted": account.get("privacyVersion") == PRIVACY_VERSION,
        "privacyAcceptedAt": account.get("privacyAcceptedAt"),
        "role": str(account.get("role") or "user"),
    }


def update_profile(username: str, message: dict[str, Any]) -> tuple[bool, str, dict[str, Any] | None]:
    key = username_key(username)
    account = ACCOUNTS.get(key)
    if account is None:
        return False, "账号不存在", None
    nickname_value = message.get("nickname", account.get("nickname") or account.get("username"))
    bio_value = message.get("bio", account.get("bio", ""))
    valid, nickname = validate_profile_text(nickname_value, MAX_NICKNAME_LENGTH)
    if not valid or not nickname or len(nickname) < 1:
        return False, "昵称不能为空且不能包含不适宜词语", None
    if not USERNAME_PATTERN.fullmatch(nickname):
        return False, "昵称需为 2-20 个中英文字符、数字或下划线", None
    valid, bio = validate_profile_text(bio_value, MAX_BIO_LENGTH)
    if not valid:
        return False, bio, None
    old_values = (account.get("nickname"), account.get("bio"))
    account["nickname"] = nickname
    account["bio"] = bio
    try:
        save_accounts()
    except OSError:
        account["nickname"], account["bio"] = old_values
        return False, "资料保存失败，请稍后重试", None
    payload = profile_payload(username)
    payload["type"] = "profile_update"
    return True, "资料已更新", payload


def accept_privacy(username: str, version: Any) -> tuple[bool, str]:
    if version is None:
        version = PRIVACY_VERSION
    if not isinstance(version, str) or not version.strip() or len(version.strip()) > 32:
        return False, "隐私协议版本无效"
    account = ACCOUNTS.get(username_key(username))
    if account is None:
        return False, "账号不存在"
    old_values = (account.get("privacyVersion"), account.get("privacyAcceptedAt"))
    account["privacyVersion"] = version.strip()
    account["privacyAcceptedAt"] = int(time.time())
    try:
        save_accounts()
    except OSError:
        account["privacyVersion"], account["privacyAcceptedAt"] = old_values
        return False, "隐私协议状态保存失败，请稍后重试"
    return True, "隐私协议已确认"


def delete_account(username: str) -> tuple[bool, str]:
    key = username_key(username)
    if key not in ACCOUNTS:
        return False, "账号不存在"
    removed = ACCOUNTS.pop(key)
    changed: list[tuple[dict[str, Any], str, list[str]]] = []
    for account in ACCOUNTS.values():
        for field in ("friends", "friendRequests", "blockedUsers"):
            values = relation_keys(account, field)
            filtered = [value for value in values if username_key(value) != key]
            if filtered != values:
                changed.append((account, field, values))
                account[field] = filtered
    try:
        save_accounts()
    except OSError:
        ACCOUNTS[key] = removed
        for account, field, values in changed:
            account[field] = values
        return False, "账号删除失败，请稍后重试"
    return True, "账号已删除"


def set_blocked(username: str, target: str, blocked: bool) -> tuple[bool, str]:
    own_key = username_key(username)
    target_key = username_key(target)
    if own_key == target_key:
        return False, "不能屏蔽自己"
    account = ACCOUNTS.get(own_key)
    if account is None or target_key not in ACCOUNTS:
        return False, "目标账号不存在"
    values = relation_keys(account, "blockedUsers")
    if blocked:
        if target_key in values:
            return False, "该账号已被屏蔽"
        account["blockedUsers"] = [*values, target_key]
        message = "已屏蔽该账号"
    else:
        if target_key not in values:
            return False, "该账号未被屏蔽"
        account["blockedUsers"] = [value for value in values if value != target_key]
        message = "已解除屏蔽"
    try:
        save_accounts()
    except OSError:
        account["blockedUsers"] = values
        return False, "屏蔽状态保存失败，请稍后重试"
    return True, message


def is_blocked_for_chat(sender: str, recipient: str) -> bool:
    sender_key = username_key(sender)
    recipient_key = username_key(recipient)
    sender_account = ACCOUNTS.get(sender_key, {})
    recipient_account = ACCOUNTS.get(recipient_key, {})
    return recipient_key in relation_keys(sender_account, "blockedUsers") or sender_key in relation_keys(recipient_account, "blockedUsers")


def create_report(
    reporter: str,
    report_type: str,
    target: str,
    reason: str,
    *,
    text: str = "",
    message_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    reporter_key = username_key(reporter)
    target_key = username_key(target)
    if reporter_key not in ACCOUNTS:
        return False, "账号不存在", None
    if report_type not in {"user", "chat"}:
        return False, "举报类型无效", None
    if target_key not in ACCOUNTS:
        return False, "目标账号不存在", None
    valid, clean_reason = validate_profile_text(reason, MAX_REPORT_REASON_LENGTH)
    if not valid or not clean_reason:
        return False, "请填写有效的举报原因", None
    clean_text = clean_chat_text(text)
    if contains_sensitive_word(clean_text):
        return False, "举报内容包含不适宜词语", None
    now = int(time.time())
    report = {
        "reportId": uuid.uuid4().hex,
        "type": report_type,
        "reporter": reporter_key,
        "target": target_key,
        "targetUsername": account_name(target_key),
        "reason": clean_reason,
        "text": clean_text,
        "messageId": message_id[:80] if isinstance(message_id, str) else "",
        "status": "open",
        "action": "",
        "createdAt": now,
        "updatedAt": now,
        "metadata": metadata if isinstance(metadata, dict) else {},
    }
    REPORTS.insert(0, report)
    try:
        save_reports()
    except OSError:
        REPORTS.remove(report)
        return False, "举报保存失败，请稍后重试", None
    return True, "举报已提交", report


def admin_account(account: dict[str, Any] | None) -> bool:
    return bool(account and str(account.get("role") or "user") == "admin")


def admin_reports_payload(status: Any = None) -> dict[str, Any]:
    requested = str(status).strip() if isinstance(status, str) else ""
    items = [
        report for report in REPORTS
        if not requested or report.get("status") == requested
    ]
    return {"type": "admin_report_list", "reports": items[:200], "count": len(items)}


def admin_report_status(report_id: str, status: str, action: str = "") -> tuple[bool, str, dict[str, Any] | None]:
    if status not in {"open", "reviewing", "resolved", "rejected"}:
        return False, "举报状态无效", None
    report = next((item for item in REPORTS if item.get("reportId") == report_id), None)
    if report is None:
        return False, "举报不存在", None
    old_values = (report.get("status"), report.get("action"), report.get("updatedAt"))
    report["status"] = status
    report["action"] = action[:32] if isinstance(action, str) else ""
    report["updatedAt"] = int(time.time())
    try:
        save_reports()
    except OSError:
        report["status"], report["action"], report["updatedAt"] = old_values
        return False, "举报状态保存失败，请稍后重试", None
    return True, "举报状态已更新", report


def admin_set_restriction(target: str, kind: str, duration: Any, reason: Any) -> tuple[bool, str, dict[str, Any] | None]:
    account = ACCOUNTS.get(username_key(target))
    if account is None:
        return False, "目标账号不存在", None
    try:
        seconds = max(0, min(int(duration), 365 * 24 * 60 * 60))
    except (TypeError, ValueError):
        return False, "时长无效", None
    if kind not in {"mute", "ban"}:
        return False, "管理操作无效", None
    field = "mutedUntil" if kind == "mute" else "bannedUntil"
    old_value = account.get(field)
    old_reason = account.get("banReason", "")
    account[field] = int(time.time()) + seconds if seconds else 0
    if kind == "ban":
        account["banReason"] = clean_chat_text(reason)
    try:
        save_accounts()
    except OSError:
        account[field] = old_value
        account["banReason"] = old_reason
        return False, "账号状态保存失败，请稍后重试", None
    return True, ("已禁言" if kind == "mute" else "已封禁"), {
        "username": account.get("username"),
        "action": kind,
        "until": account.get(field),
        "reason": account.get("banReason", ""),
    }


def initialize_admin_account() -> None:
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        return
    if not USERNAME_PATTERN.fullmatch(ADMIN_USERNAME) or not 6 <= len(ADMIN_PASSWORD) <= MAX_PASSWORD_LENGTH:
        print("[管理员] ADMIN_USERNAME/ADMIN_PASSWORD 格式无效，跳过初始化", flush=True)
        return
    key = username_key(ADMIN_USERNAME)
    account = ACCOUNTS.get(key)
    changed = False
    if account is None:
        salt = secrets.token_hex(16)
        account = normalize_account({
            "username": ADMIN_USERNAME,
            "nickname": ADMIN_NICKNAME or ADMIN_USERNAME,
            "salt": salt,
            "passwordHash": password_digest(ADMIN_PASSWORD, salt, PASSWORD_ITERATIONS),
            "iterations": PASSWORD_ITERATIONS,
            "createdAt": int(time.time()),
            "role": "admin",
        })
        ACCOUNTS[key] = account
        changed = True
    elif account.get("role") != "admin":
        account["role"] = "admin"
        changed = True
    if changed:
        try:
            save_accounts()
        except OSError as error:
            print(f"[管理员] 初始化保存失败: {error}", flush=True)


ACCOUNTS = load_accounts()
REPORTS = load_reports()
initialize_admin_account()


def session_for_username(username: str) -> Session | None:
    key = username_key(username)
    return next(
        (
            session
            for session in SESSIONS.values()
            if username_key(session.username) == key
        ),
        None,
    )


def account_name(key: str) -> str:
    account = ACCOUNTS.get(key)
    return str(account.get("username") or key) if account else key


def social_state_payload(username: str) -> dict[str, Any]:
    key = username_key(username)
    account = ACCOUNTS.get(key, {})
    friend_keys = {
        str(friend_key)
        for friend_key in account.get("friends", [])
        if str(friend_key) in ACCOUNTS
    }
    friend_items = []
    for friend_key in friend_keys:
        friend_session = session_for_username(friend_key)
        friend_items.append(
            {
                "name": account_name(friend_key),
                "online": friend_session is not None,
                "inGame": bool(friend_session and friend_session.client),
                "invited": friend_key in ROOM.invited_usernames,
            }
        )

    incoming = [
        {"name": account_name(str(requester_key))}
        for requester_key in relation_keys(account, "friendRequests")
        if str(requester_key) in ACCOUNTS
    ]
    outgoing = [
        {"name": account_name(requester_key)}
        for requester_key, requester in ACCOUNTS.items()
        if key in relation_keys(requester, "friendRequests")
    ]
    room_active = bool(ROOM.clients)
    return {
        "onlineCount": sum(1 for friend in friend_items if friend["online"]),
        "friends": sorted(friend_items, key=lambda friend: friend["name"].casefold()),
        "incomingRequests": incoming,
        "outgoingRequests": outgoing,
        "roomActive": room_active,
        "roomPlayers": len(ROOM.clients),
        "roomOwnerName": (
            account_name(ROOM.owner_username)
            if room_active and ROOM.owner_username
            else None
        ),
        "roomInvited": room_active and key in ROOM.invited_usernames,
    }


def lobby_payload(username: str) -> dict[str, Any]:
    account = normalize_account(ACCOUNTS.get(username_key(username), {}))
    return {
        "type": "lobby",
        "username": username,
        "nickname": str(account.get("nickname") or username),
        "bio": str(account.get("bio") or ""),
        "privacyAccepted": account.get("privacyVersion") == PRIVACY_VERSION,
        "role": str(account.get("role") or "user"),
        **social_state_payload(username),
    }


async def broadcast_social_states() -> None:
    if not SESSIONS:
        return
    await asyncio.gather(
        *(
            session.websocket.send(
                encode(
                    {
                        "type": "social_state",
                        "username": session.username,
                        **social_state_payload(session.username),
                    }
                )
            )
            for session in list(SESSIONS.values())
        ),
        return_exceptions=True,
    )


def encode(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def clean_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\x00-\x1f\x7f]", "", value).strip()[:MAX_NAME_LENGTH]


def clean_chat_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\x00-\x1f\x7f]", "", value)[:MAX_CHAT_LENGTH]


def is_correct_guess(guess: str, word: str | None) -> bool:
    if not word:
        return False
    normalized = guess.strip().casefold()
    if normalized == word.strip().casefold():
        return True
    expected_pinyin = WORD_PINYIN.get(word)
    if expected_pinyin is None:
        return False
    compact_pinyin = re.sub(r"[\s'-]", "", normalized)
    return compact_pinyin == expected_pinyin


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def make_segment(message: dict[str, Any]) -> dict[str, Any] | None:
    x0 = number(message.get("x0"))
    y0 = number(message.get("y0"))
    x1 = number(message.get("x1"))
    y1 = number(message.get("y1"))
    width = number(message.get("width"))
    color = message.get("color")
    segment_id = message.get("id")

    if None in (x0, y0, x1, y1, width):
        return None
    if not isinstance(color, str) or not COLOR_PATTERN.fullmatch(color):
        return None
    if not isinstance(segment_id, str) or not (0 < len(segment_id) <= 80):
        return None

    return {
        "id": segment_id,
        "x0": min(1.0, max(0.0, x0)),
        "y0": min(1.0, max(0.0, y0)),
        "x1": min(1.0, max(0.0, x1)),
        "y1": min(1.0, max(0.0, y1)),
        "color": color.lower(),
        "width": min(24.0, max(1.0, width)),
    }


async def send_error(websocket: WebSocketServerProtocol, message: str) -> None:
    try:
        await websocket.send(encode({"type": "error", "message": message}))
    except ConnectionClosed:
        pass


async def send_auth_error(websocket: WebSocketServerProtocol, message: str) -> None:
    try:
        await websocket.send(encode({"type": "auth_error", "message": message}))
    except ConnectionClosed:
        pass


async def send_notice(websocket: WebSocketServerProtocol, message: str) -> None:
    try:
        await websocket.send(encode({"type": "notice", "message": message}))
    except ConnectionClosed:
        pass


async def broadcast_chat_message(payload: dict[str, Any], sender: str) -> None:
    """Send chat only to users who have not blocked either side."""
    recipients = []
    for recipient_session in list(SESSIONS.values()):
        if is_blocked_for_chat(sender, recipient_session.username):
            continue
        recipients.append(recipient_session.websocket.send(encode(payload)))
    if recipients:
        await asyncio.gather(*recipients, return_exceptions=True)


async def broadcast_room_chat_message(payload: dict[str, Any], sender: str, room: Room) -> None:
    recipients = []
    for room_websocket in list(room.clients):
        recipient_session = SESSIONS.get(room_websocket)
        recipient_name = recipient_session.username if recipient_session else room.clients[room_websocket].name
        if is_blocked_for_chat(sender, recipient_name):
            continue
        recipients.append(room_websocket.send(encode(payload)))
    if recipients:
        await asyncio.gather(*recipients, return_exceptions=True)


async def disconnect_session(session: Session, reason: str) -> None:
    room = session_room(session)
    if session.client is not None and room is not None:
        async with room.lock:
            await room.remove_client(session.websocket)
            await room.broadcast_presence()
        if room.room_code and not room.clients:
            ROOMS.pop(room.room_code, None)
        session.client = None
        session.room = None
    try:
        await session.websocket.close(code=1008, reason=reason)
    except ConnectionClosed:
        pass


async def send_admin_result(
    websocket: WebSocketServerProtocol,
    success: bool,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    if success:
        result = {"type": "admin_result", "message": message, **(payload or {})}
        try:
            await websocket.send(encode(result))
        except ConnectionClosed:
            pass
    else:
        await send_error(websocket, message)


async def authenticate_client(
    websocket: WebSocketServerProtocol,
) -> str | None:
    while True:
        try:
            raw_message = await asyncio.wait_for(websocket.recv(), timeout=60)
            message = json.loads(raw_message)
        except asyncio.TimeoutError:
            await websocket.close(code=1008, reason="Authentication timeout")
            return None
        except (json.JSONDecodeError, TypeError):
            await send_auth_error(websocket, "消息格式无效")
            continue

        if not isinstance(message, dict):
            await send_auth_error(websocket, "消息格式无效")
            continue

        message_type = message.get("type")
        if message_type == "session_token":
            authenticated_name = verify_wechat_token(message.get("token"))
            if authenticated_name is not None:
                return authenticated_name
            await send_auth_error(websocket, "登录令牌无效或已过期")
            continue
        username = message.get("username", message.get("name", ""))
        password = message.get("password", "")
        if not isinstance(username, str) or not isinstance(password, str):
            await send_auth_error(websocket, "用户名和密码格式无效")
            continue

        if message_type == "register":
            success, result = register_account(username, password)
            if success:
                return result
            await send_auth_error(websocket, result)
        elif message_type == "join":
            success, result = verify_account(username, password)
            if success:
                return result
            await send_auth_error(websocket, result)
        else:
            await send_auth_error(websocket, "请先登录或注册账号")


async def enter_room(
    websocket: WebSocketServerProtocol,
    session: Session,
    room: Room,
) -> Client:
    async with room.lock:
        is_first_player = not room.clients
        if is_first_player:
            room.owner_username = username_key(session.username)
            room.invited_usernames.clear()
        else:
            room.invited_usernames.discard(username_key(session.username))
        client = Client(
            websocket=websocket,
            client_id=uuid.uuid4().hex,
            name=session.username,
            role="guesser",
            color=room.next_color(),
        )
        room.clients[websocket] = client
        room.player_order.append(websocket)
        session.client = client
        session.room = room
        room.sync_roles()
        await websocket.send(
            encode(
                {
                    "type": "joined",
                    "clientId": client.client_id,
                    "role": client.role,
                    "name": client.name,
                    "color": client.color,
                    "roomCode": room.room_code,
                    "strokes": room.strokes,
                    "round": room.round_payload() if room.round_number else None,
                    "gameOver": room.game_over,
                    "ranking": room.ranking_payload() if room.game_over else [],
                    "maxRounds": MAX_ROUNDS,
                }
            )
        )
        await room.broadcast_presence()
        if is_first_player:
            await room.begin_round()
        return client


async def handle_client(websocket: WebSocketServerProtocol, path: str) -> None:
    if path != "/ws":
        await websocket.close(code=1008, reason="Unknown WebSocket path")
        return

    session: Session | None = None
    try:
        authenticated_name = await authenticate_client(websocket)
        if authenticated_name is None:
            return

        if any(
            existing.username.casefold() == authenticated_name.casefold()
            for existing in SESSIONS.values()
        ):
            await send_auth_error(websocket, "该账号已经在线，请先关闭另一个窗口")
            await websocket.close(code=1008, reason="Account already online")
            return

        session = Session(websocket=websocket, username=authenticated_name)
        SESSIONS[websocket] = session
        await websocket.send(encode(lobby_payload(authenticated_name)))
        await broadcast_social_states()

        async for raw_message in websocket:
            try:
                message = json.loads(raw_message)
            except (json.JSONDecodeError, TypeError):
                await send_error(websocket, "消息格式无效")
                continue

            if not isinstance(message, dict):
                await send_error(websocket, "消息格式无效")
                continue

            message_type = message.get("type")
            current_account = normalize_account(ACCOUNTS.get(username_key(session.username), {}))
            if account_is_banned(current_account):
                await send_error(websocket, "账号已封禁，连接即将关闭")
                await disconnect_session(session, "Account banned")
                break

            if message_type in {"profile_get", "get_profile"}:
                target = clean_name(message.get("username") or session.username)
                if username_key(target) not in ACCOUNTS:
                    await send_error(websocket, "账号不存在")
                else:
                    await websocket.send(encode(profile_payload(target)))
                continue

            if message_type in {"profile_update", "update_profile"}:
                success, result, payload = update_profile(session.username, message)
                if success:
                    await websocket.send(encode(payload or profile_payload(session.username)))
                    await send_notice(websocket, result)
                    await broadcast_social_states()
                else:
                    await send_error(websocket, result)
                continue

            if message_type in {"privacy_accept", "accept_privacy"}:
                success, result = accept_privacy(
                    session.username,
                    message.get("version", message.get("privacyVersion", PRIVACY_VERSION)),
                )
                if success:
                    await websocket.send(encode({
                        "type": "privacy_accept",
                        "version": PRIVACY_VERSION,
                        "accepted": True,
                    }))
                    await send_notice(websocket, result)
                else:
                    await send_error(websocket, result)
                continue

            if message_type in {"delete_account", "account_delete"}:
                if message.get("confirm", True) is not True:
                    await send_error(websocket, "请确认删除账号")
                    continue
                success, result = delete_account(session.username)
                if success:
                    await send_notice(websocket, result)
                    await disconnect_session(session, "Account deleted")
                    break
                await send_error(websocket, result)
                continue

            if message_type in {"block_user", "unblock_user"}:
                target = clean_name(message.get("username") or message.get("target"))
                success, result = set_blocked(
                    session.username,
                    target,
                    message_type == "block_user",
                )
                if success:
                    await send_notice(websocket, result)
                    await broadcast_social_states()
                else:
                    await send_error(websocket, result)
                continue

            if message_type in {"report_user", "report_chat"}:
                target = clean_name(
                    message.get("username")
                    or message.get("target")
                    or message.get("targetUsername")
                    or message.get("playerName")
                )
                success, result, report = create_report(
                    session.username,
                    "chat" if message_type == "report_chat" else "user",
                    target,
                    message.get("reason", ""),
                    text=message.get("text", ""),
                    message_id=message.get("messageId", ""),
                    metadata={
                        "room": bool(session.client),
                        "source": message.get("source", "client"),
                    },
                )
                if success:
                    await websocket.send(encode({
                        "type": message_type,
                        "reportId": report.get("reportId") if report else None,
                        "status": "open",
                    }))
                    await send_notice(websocket, result)
                else:
                    await send_error(websocket, result)
                continue

            if message_type == "admin_report_list":
                if not admin_account(current_account):
                    await send_error(websocket, "需要管理员权限")
                else:
                    await websocket.send(encode(admin_reports_payload(message.get("status"))))
                continue

            if message_type == "admin_report_status":
                if not admin_account(current_account):
                    await send_error(websocket, "需要管理员权限")
                    continue
                success, result, report = admin_report_status(
                    str(message.get("reportId") or ""),
                    str(message.get("status") or ""),
                    str(message.get("action") or ""),
                )
                await send_admin_result(
                    websocket,
                    success,
                    result,
                    {"report": report} if report else None,
                )
                continue

            if message_type in {"admin_mute", "admin_ban"} or message_type == "admin_action":
                if not admin_account(current_account):
                    await send_error(websocket, "需要管理员权限")
                    continue
                action = "mute" if message_type == "admin_mute" else "ban" if message_type == "admin_ban" else str(message.get("action") or "")
                target = clean_name(message.get("username") or message.get("target"))
                success, result, restriction = admin_set_restriction(
                    target,
                    action,
                    message.get("duration", message.get("durationSeconds", 0)),
                    message.get("reason", ""),
                )
                await send_admin_result(
                    websocket,
                    success,
                    result,
                    {"restriction": restriction} if restriction else None,
                )
                if success and action == "ban":
                    target_session = session_for_username(target)
                    if target_session is not None and target_session is not session:
                        await send_notice(target_session.websocket, "账号已被管理员封禁")
                        await disconnect_session(target_session, "Account banned")
                continue

            if message_type == "friend_request":
                target = clean_name(message.get("username"))
                success, result = send_friend_request(session.username, target)
                if success:
                    await send_notice(websocket, result)
                    await broadcast_social_states()
                else:
                    await send_error(websocket, result)
                continue

            if message_type == "friend_accept":
                requester = clean_name(message.get("username"))
                success, result = accept_friend_request(session.username, requester)
                if success:
                    await send_notice(websocket, result)
                    await broadcast_social_states()
                else:
                    await send_error(websocket, result)
                continue

            if message_type == "friend_reject":
                requester = clean_name(message.get("username"))
                if reject_friend_request(session.username, requester):
                    await send_notice(websocket, "已拒绝好友申请")
                    await broadcast_social_states()
                else:
                    await send_error(websocket, "该好友申请已失效")
                continue

            if message_type == "friend_remove":
                friend_name = clean_name(message.get("username"))
                if remove_friend(session.username, friend_name):
                    await send_notice(websocket, "已移除好友")
                    await broadcast_social_states()
                else:
                    await send_error(websocket, "无法移除该好友")
                continue

            if session.client is None:
                if message_type == "create_room":
                    requested_code = message.get("roomCode")
                    if requested_code == "new":
                        room = Room(room_code=new_room_code())
                        ROOMS[room.room_code] = room
                        await enter_room(websocket, session, room)
                    else:
                        if ROOM.clients and username_key(session.username) not in ROOM.invited_usernames:
                            await send_error(websocket, "房间进行中，只有受邀好友可以加入")
                            continue
                        await enter_room(websocket, session, ROOM)
                    await broadcast_social_states()
                elif message_type == "join_room":
                    requested_code = message.get("roomCode")
                    if requested_code is not None:
                        room = room_for_code(requested_code)
                        if room is None:
                            await send_error(websocket, "房间不存在或房间码无效")
                            continue
                        await enter_room(websocket, session, room)
                    else:
                        if not ROOM.clients:
                            await send_error(websocket, "房间不存在，请先创建房间")
                            continue
                        if username_key(session.username) not in ROOM.invited_usernames:
                            await send_error(websocket, "需要房主邀请才能加入房间")
                            continue
                        await enter_room(websocket, session, ROOM)
                    await broadcast_social_states()
                elif message_type == "decline_room_invite":
                    ROOM.invited_usernames.discard(username_key(session.username))
                    await send_notice(websocket, "已拒绝房间邀请")
                    await broadcast_social_states()
                else:
                    await send_error(websocket, "请先创建房间或接受好友邀请")
                continue

            client = session.client
            room = session_room(session)
            if client is None or room is None:
                await send_error(websocket, "请先创建或加入房间")
                continue
            if message_type == "leave_room":
                async with room.lock:
                    await room.remove_client(websocket)
                    await room.broadcast_presence()
                if room.room_code and not room.clients:
                    ROOMS.pop(room.room_code, None)
                session.client = None
                session.room = None
                await websocket.send(encode(lobby_payload(session.username)))
                await broadcast_social_states()
                continue
            if message_type == "invite_friend":
                friend_name = clean_name(message.get("username"))
                friend_key = username_key(friend_name)
                if room.owner_username != username_key(session.username):
                    await send_error(websocket, "只有房主可以邀请好友")
                    continue
                if not are_friends(session.username, friend_name):
                    await send_error(websocket, "只能邀请你的好友")
                    continue
                if any(username_key(player.name) == friend_key for player in room.clients.values()):
                    await send_error(websocket, "该好友已经在房间中")
                    continue
                room.invited_usernames.add(friend_key)
                await send_notice(websocket, f"已邀请 {friend_name} 加入房间")
                await broadcast_social_states()
                continue

            if message_type == "play_again":
                async with room.lock:
                    if not await room.restart_game():
                        await send_error(websocket, "游戏尚未结束")
                continue

            if room.game_over:
                await send_error(websocket, "游戏已结束，请点击再来一局")
                continue

            if message_type == "stroke":
                segment = make_segment(message)
                if segment is None:
                    await send_error(websocket, "笔触数据无效")
                    continue
                async with room.lock:
                    if room.game_over:
                        await send_error(websocket, "游戏已结束，请点击再来一局")
                        continue
                    if client.role != "drawer":
                        await send_error(websocket, "只有画手可以绘画")
                        continue
                    if len(room.strokes) >= MAX_STROKES:
                        await send_error(websocket, "画布笔触数量已达上限，请清空画布")
                        continue
                    room.strokes.append(segment)
                    await room.broadcast({"type": "stroke", **segment})

            elif message_type == "clear":
                async with room.lock:
                    if room.game_over:
                        await send_error(websocket, "游戏已结束，请点击再来一局")
                        continue
                    if client.role != "drawer":
                        await send_error(websocket, "只有画手可以清空画布")
                        continue
                    room.strokes.clear()
                    await room.broadcast({"type": "clear"})

            elif message_type == "guess":
                guess = clean_chat_text(message.get("text"))
                if not guess.strip():
                    await send_error(websocket, "请输入文字")
                    continue
                if contains_sensitive_word(guess):
                    await send_error(websocket, "消息包含不适宜词语")
                    continue
                if account_is_muted(current_account):
                    await send_error(websocket, "你当前处于禁言状态")
                    continue

                async with room.lock:
                    if room.game_over:
                        await send_error(websocket, "游戏已结束，请点击再来一局")
                        continue
                    chat_payload = {
                        "type": "chat",
                        "messageId": uuid.uuid4().hex,
                        "playerId": client.client_id,
                        "playerName": client.name,
                        "color": client.color,
                        "text": guess,
                    }
                    if client.role == "drawer":
                        await broadcast_room_chat_message(chat_payload, session.username, room)
                        continue

                    if is_correct_guess(guess, room.current_word):
                        word = room.current_word or ""
                        client.score += 1
                        await room.broadcast(
                            {
                                "type": "correct_guess",
                                "playerId": client.client_id,
                                "playerName": client.name,
                                "word": word,
                                "message": f"{client.name} 猜对了！答案是：{word}",
                            }
                        )
                        await room.broadcast_presence()
                        await room.finish_round("correct-guess")
                    else:
                        await broadcast_room_chat_message(chat_payload, session.username, room)

            else:
                await send_error(websocket, "未知消息类型")

    except ConnectionClosed:
        pass
    finally:
        if session is not None and session.client is not None:
            room = session_room(session)
            if room is not None:
                async with room.lock:
                    await room.remove_client(websocket)
                    await room.broadcast_presence()
                if room.room_code and not room.clients:
                    ROOMS.pop(room.room_code, None)
            session.client = None
            session.room = None
        if session is not None and SESSIONS.get(websocket) is session:
            SESSIONS.pop(websocket, None)
        if session is not None:
            await broadcast_social_states()


async def process_request(
    path: str, request_headers: Any
) -> tuple[HTTPStatus, list[tuple[str, str]], bytes] | None:
    request_path = urlparse(path).path
    if request_path == "/ws":
        return None
    if request_path == "/_wechat_login":
        if not WECHAT_APPID or not WECHAT_APPSECRET or not WECHAT_TOKEN_SECRET:
            body = json.dumps({"error": "微信登录未配置，请设置 WECHAT_APPID、WECHAT_APPSECRET、WECHAT_TOKEN_SECRET"}, ensure_ascii=False).encode("utf-8")
            return HTTPStatus.SERVICE_UNAVAILABLE, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")], body
        code = parse_qs(urlparse(path).query).get("code", [""])[0]
        if not code:
            body = json.dumps({"error": "缺少 code"}, ensure_ascii=False).encode("utf-8")
            return HTTPStatus.BAD_REQUEST, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))], body
        success, result = wechat_account(code)
        if not success:
            body = json.dumps({"error": result}, ensure_ascii=False).encode("utf-8")
            status = HTTPStatus.SERVICE_UNAVAILABLE if "不可用" in result else HTTPStatus.BAD_REQUEST
            return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")], body
        token = issue_wechat_token(result)
        body = json.dumps({"token": token, "expiresIn": WECHAT_TOKEN_TTL}, ensure_ascii=False).encode("utf-8")
        return HTTPStatus.OK, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")], body

    if request_path in ("/", "/index.html"):
        body = HTML_PAGE.encode("utf-8")
        return (
            HTTPStatus.OK,
            [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
            ],
            body,
        )

    if request_path == "/healthz":
        body = b"ok\n"
        return (
            HTTPStatus.OK,
            [
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ],
            body,
        )

    if request_path == "/privacy":
        body = PRIVACY_PAGE.encode("utf-8")
        return (
            HTTPStatus.OK,
            [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")],
            body,
        )

    if request_path == "/terms":
        body = TERMS_PAGE.encode("utf-8")
        return (
            HTTPStatus.OK,
            [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")],
            body,
        )

    if request_path == "/account-deletion":
        body = ACCOUNT_DELETION_PAGE.encode("utf-8")
        return (
            HTTPStatus.OK,
            [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")],
            body,
        )


    body = b"Not found\n"
    return (
        HTTPStatus.NOT_FOUND,
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
        body,
    )


def local_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = result[4][0]
            if not address.startswith("127."):
                addresses.add(address)
    except socket.gaierror:
        pass
    return sorted(addresses)


async def main() -> None:
    async with serve(
        handle_client,
        HOST,
        PORT,
        process_request=process_request,
        ping_interval=20,
        ping_timeout=20,
        max_size=1_000_000,
    ):
        print(f"多人画板已启动：http://localhost:{PORT}", flush=True)
        for address in local_addresses():
            print(f"局域网访问：http://{address}:{PORT}", flush=True)
        print("按 Ctrl+C 停止服务。", flush=True)
        await asyncio.Future()


HTML_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#f7f2e8">
  <title>一起画 · 多人实时画板</title>
  <style>
    :root {
      --ink: #20242c;
      --muted: #73777f;
      --paper: #fffdf8;
      --bg: #f7f2e8;
      --coral: #ff6b57;
      --sun: #ffd84d;
      --blue: #3d9be9;
      --line: #ded7ca;
      --shadow: 0 12px 30px rgba(52, 43, 29, .10);
    }
    * { box-sizing: border-box; }
    html, body { min-height: 100%; }
    body {
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 8% 10%, rgba(255, 216, 77, .35), transparent 23rem),
        radial-gradient(circle at 93% 90%, rgba(61, 155, 233, .16), transparent 25rem),
        var(--bg);
      font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
    }
    button, input { font: inherit; }
    button { color: inherit; }
    .hidden { display: none !important; }

    .login {
      min-height: 100dvh;
      display: grid;
      place-items: center;
      padding: 24px;
    }
    .login-card {
      position: relative;
      width: min(100%, 440px);
      padding: 38px;
      background: var(--paper);
      border: 2px solid var(--ink);
      border-radius: 28px;
      box-shadow: 9px 9px 0 var(--ink);
      overflow: hidden;
    }
    .login-card::before {
      content: "";
      position: absolute;
      width: 150px;
      height: 150px;
      top: -75px;
      right: -55px;
      border: 22px solid var(--sun);
      border-radius: 50%;
      opacity: .9;
    }
    .logo-mark {
      position: relative;
      display: inline-flex;
      align-items: center;
      gap: 10px;
      font-size: 15px;
      font-weight: 800;
      letter-spacing: .12em;
      text-transform: uppercase;
    }
    .logo-dot {
      width: 16px;
      height: 16px;
      border-radius: 50% 50% 48% 30%;
      background: var(--coral);
      border: 2px solid var(--ink);
      transform: rotate(-18deg);
    }
    h1 {
      position: relative;
      margin: 42px 0 10px;
      font-size: clamp(42px, 11vw, 64px);
      line-height: .98;
      letter-spacing: -.06em;
    }
    .accent {
      position: relative;
      display: inline-block;
      color: var(--coral);
    }
    .accent::after {
      content: "";
      position: absolute;
      left: 2px;
      right: -4px;
      bottom: 1px;
      height: 9px;
      border-radius: 50%;
      border-top: 5px solid var(--sun);
      transform: rotate(-2deg);
    }
    .lead {
      position: relative;
      margin: 0 0 28px;
      color: var(--muted);
      line-height: 1.7;
    }
    label {
      display: block;
      margin: 0 0 9px;
      font-size: 13px;
      font-weight: 800;
    }
    .join-row { display: flex; gap: 10px; }
    .auth-tabs {
      position: relative;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 4px;
      margin-bottom: 20px;
      padding: 4px;
      border-radius: 13px;
      background: #eee9df;
    }
    .auth-tab {
      height: 38px;
      border: 0;
      border-radius: 9px;
      background: transparent;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      cursor: pointer;
    }
    .auth-tab.active {
      background: var(--paper);
      color: var(--ink);
      box-shadow: 0 2px 8px rgba(32, 36, 44, .09);
    }
    .auth-field { margin-bottom: 14px; }
    .auth-field input { width: 100%; }
    .auth-error {
      margin: 2px 0 13px;
      padding: 9px 11px;
      border: 1px solid #f1b5ae;
      border-radius: 9px;
      background: #fff0ee;
      color: #a9372f;
      font-size: 11px;
      font-weight: 700;
      line-height: 1.5;
    }
    .auth-submit { width: 100%; }
    .auth-switch-hint {
      margin: 13px 0 0;
      color: var(--muted);
      font-size: 10px;
      line-height: 1.6;
      text-align: center;
    }
    input {
      flex: 1;
      min-width: 0;
      height: 54px;
      padding: 0 17px;
      border: 2px solid var(--ink);
      border-radius: 15px;
      background: #fff;
      outline: none;
      transition: box-shadow .18s, transform .18s;
    }
    input:focus {
      box-shadow: 0 0 0 4px rgba(61, 155, 233, .2);
      transform: translateY(-1px);
    }
    .primary {
      height: 54px;
      padding: 0 22px;
      border: 2px solid var(--ink);
      border-radius: 15px;
      background: var(--ink);
      color: #fff;
      font-weight: 800;
      cursor: pointer;
      box-shadow: 4px 4px 0 var(--sun);
      transition: transform .16s, box-shadow .16s;
    }
    .primary:hover { transform: translate(-1px, -1px); box-shadow: 6px 6px 0 var(--sun); }
    .primary:active { transform: translate(2px, 2px); box-shadow: 1px 1px 0 var(--sun); }
    .primary:disabled { opacity: .52; cursor: wait; }
    .login-note {
      margin: 18px 0 0;
      font-size: 12px;
      color: var(--muted);
      text-align: center;
    }

    .lobby-view {
      width: min(1180px, 100%);
      min-height: 100dvh;
      margin: auto;
      padding: max(18px, env(safe-area-inset-top)) 22px max(24px, env(safe-area-inset-bottom));
    }
    .lobby-topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 22px;
    }
    .lobby-user {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255, 253, 248, .82);
      font-size: 12px;
      font-weight: 800;
    }
    .lobby-user::before {
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #35a777;
    }
    .lobby-top-actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
      gap: 7px;
    }
    .lobby-action {
      height: 34px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 9px;
      background: var(--paper);
      color: var(--ink);
      font-size: 11px;
      font-weight: 800;
      cursor: pointer;
    }
    .lobby-action:hover { border-color: var(--ink); background: var(--sun); }
    .lobby-action.admin-action { background: #eaf4ff; color: #2569a9; }
    .lobby-action.danger-action { color: #a9372f; }
    .lobby-grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 350px;
      gap: 20px;
      align-items: start;
    }
    .lobby-hero {
      position: relative;
      min-height: 570px;
      padding: clamp(28px, 5vw, 58px);
      overflow: hidden;
      border: 2px solid var(--ink);
      border-radius: 28px;
      background: var(--paper);
      box-shadow: 8px 8px 0 var(--ink);
    }
    .lobby-hero::before {
      content: "";
      position: absolute;
      width: 260px;
      height: 260px;
      right: -90px;
      top: -95px;
      border: 42px solid var(--sun);
      border-radius: 50%;
      transform: rotate(-10deg);
    }
    .lobby-hero::after {
      content: "";
      position: absolute;
      width: 150px;
      height: 90px;
      right: 48px;
      bottom: 42px;
      border-bottom: 10px solid rgba(255, 107, 87, .35);
      border-radius: 50%;
      transform: rotate(-7deg);
    }
    .lobby-kicker {
      position: relative;
      color: var(--coral);
      font-size: 11px;
      font-weight: 900;
      letter-spacing: .18em;
    }
    .lobby-hero h1 {
      position: relative;
      max-width: 620px;
      margin: 42px 0 16px;
      font-size: clamp(46px, 7vw, 82px);
      line-height: .98;
      letter-spacing: -.065em;
    }
    .lobby-copy {
      position: relative;
      max-width: 500px;
      margin: 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.8;
    }
    .room-entry {
      position: relative;
      z-index: 1;
      display: flex;
      max-width: 570px;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      margin-top: 70px;
      padding: 20px;
      border: 1.5px solid var(--ink);
      border-radius: 18px;
      background: #f8f5ee;
    }
    .room-entry-copy strong { display: block; margin-bottom: 4px; font-size: 16px; }
    .room-entry-copy span { color: var(--muted); font-size: 11px; }
    .room-entry button {
      flex: 0 0 auto;
      min-width: 132px;
      height: 48px;
      border: 1.5px solid var(--ink);
      border-radius: 12px;
      background: var(--coral);
      color: #fff;
      font-size: 13px;
      font-weight: 900;
      cursor: pointer;
      box-shadow: 3px 3px 0 var(--ink);
    }
    .room-entry button:hover { transform: translate(-1px, -1px); }
    .room-entry button:disabled { opacity: .58; cursor: wait; }
    .lobby-steps {
      position: relative;
      z-index: 1;
      display: flex;
      flex-wrap: wrap;
      gap: 20px;
      margin-top: 42px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
    }
    .lobby-steps span::before {
      content: "✓";
      margin-right: 6px;
      color: #267552;
    }
    .lobby-social {
      position: sticky;
      top: 18px;
      display: flex;
      flex-direction: column;
      gap: 18px;
      padding: 18px;
      border: 1.5px solid var(--line);
      border-radius: 23px;
      background: rgba(255, 253, 248, .94);
      box-shadow: var(--shadow);
    }
    .lobby-online-list {
      display: flex;
      flex-direction: column;
      gap: 7px;
    }
    .online-player {
      display: grid;
      grid-template-columns: 31px minmax(0, 1fr) auto;
      align-items: center;
      gap: 9px;
      padding: 8px 9px;
      border-radius: 11px;
      background: #f8f5ee;
    }
    .online-player .avatar { width: 31px; height: 31px; }
    .online-player-name {
      display: block;
      overflow: hidden;
      font-size: 12px;
      font-weight: 800;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .online-player-state {
      display: block;
      margin-top: 1px;
      color: var(--muted);
      font-size: 9px;
      font-weight: 700;
    }
    .online-player-state.playing { color: #267552; }
    .lobby-empty {
      padding: 15px 10px;
      border: 1px dashed var(--line);
      border-radius: 11px;
      color: var(--muted);
      font-size: 10px;
      line-height: 1.6;
      text-align: center;
    }
    .lobby-social .side-section { margin: 0; padding: 0; border: 0; }
    .lobby-social .side-section + .side-section {
      padding-top: 17px;
      border-top: 1px solid var(--line);
    }

    .app {
      width: min(1440px, 100%);
      margin: auto;
      padding: max(18px, env(safe-area-inset-top)) 22px max(22px, env(safe-area-inset-bottom));
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 18px;
    }
    .brand { display: flex; align-items: center; gap: 12px; }
    .brand h2 {
      margin: 0;
      font-size: 23px;
      letter-spacing: -.04em;
    }
    .brand small {
      display: block;
      margin-top: 2px;
      color: var(--muted);
      font-size: 11px;
      letter-spacing: .12em;
    }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255, 253, 248, .78);
      font-size: 12px;
      font-weight: 700;
    }
    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #35a777;
      box-shadow: 0 0 0 4px rgba(53, 167, 119, .14);
    }
    .status.offline .status-dot { background: #d44d4d; }
    .header-actions {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .top-timer {
      display: flex;
      align-items: baseline;
      gap: 5px;
      min-width: 128px;
      padding: 7px 13px 8px;
      border: 1.5px solid var(--ink);
      border-radius: 14px;
      background: var(--sun);
      box-shadow: 3px 3px 0 var(--ink);
      transition: background .2s, color .2s, transform .2s;
    }
    .top-timer .timer-label {
      margin-right: auto;
      font-size: 10px;
      font-weight: 800;
      letter-spacing: .08em;
    }
    .top-timer #round-timer {
      font-size: 25px;
      line-height: 1;
      font-variant-numeric: tabular-nums;
      font-weight: 900;
      letter-spacing: -.05em;
    }
    .top-timer small { font-size: 10px; font-weight: 800; }
    .top-timer.urgent {
      background: var(--coral);
      color: #fff;
      transform: scale(1.03);
    }

    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 354px;
      gap: 20px;
      align-items: stretch;
    }
    .board-card, .side-card {
      border: 1.5px solid var(--line);
      background: rgba(255, 253, 248, .92);
      border-radius: 23px;
      box-shadow: var(--shadow);
    }
    .board-card {
      display: flex;
      min-width: 0;
      flex-direction: column;
      padding: 16px;
    }
    .board-head {
      min-height: 52px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 0 5px 12px;
    }
    .role-badge {
      display: inline-flex;
      align-items: center;
      gap: 9px;
      font-weight: 800;
    }
    .role-badge .glyph {
      width: 31px;
      height: 31px;
      display: grid;
      place-items: center;
      border-radius: 10px;
      background: var(--sun);
      border: 1.5px solid var(--ink);
      font-size: 16px;
    }
    .role-badge.guesser .glyph { background: #d9ecff; }
    .role-hint { color: var(--muted); font-size: 12px; }
    .round-strip {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 42px;
      margin-bottom: 10px;
      padding: 8px 12px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #f8f5ee;
    }
    .round-copy { min-width: 0; }
    .round-kicker {
      display: block;
      margin-bottom: 2px;
      color: var(--muted);
      font-size: 9px;
      font-weight: 800;
      letter-spacing: .12em;
    }
    .round-title {
      display: block;
      overflow: hidden;
      font-size: 13px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .word-card {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 10px;
      padding: 10px 14px;
      border: 1.5px solid var(--ink);
      border-radius: 12px;
      background: #fff3b9;
      box-shadow: 3px 3px 0 var(--ink);
    }
    .word-card span { color: #725600; font-size: 11px; font-weight: 700; }
    .word-card strong {
      font-size: clamp(20px, 4vw, 28px);
      letter-spacing: .06em;
    }

    .canvas-wrap {
      position: relative;
      width: 100%;
      aspect-ratio: 4 / 3;
      max-height: calc(100dvh - 430px);
      min-height: 300px;
      overflow: hidden;
      border: 1.5px solid var(--line);
      border-radius: 16px;
      background:
        linear-gradient(90deg, rgba(32, 36, 44, .035) 1px, transparent 1px),
        linear-gradient(rgba(32, 36, 44, .035) 1px, transparent 1px),
        #fff;
      background-size: 22px 22px;
    }
    canvas {
      display: block;
      width: 100%;
      height: 100%;
      touch-action: none;
      cursor: crosshair;
    }
    .canvas-wrap.readonly canvas { cursor: default; }
    .readonly-cover {
      position: absolute;
      top: 12px;
      left: 12px;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 7px 10px;
      border: 1px solid var(--line);
      border-radius: 9px;
      background: rgba(255, 253, 248, .9);
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      pointer-events: none;
    }
    .toolbar {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
      min-height: 58px;
      margin-top: 12px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #f8f5ee;
    }
    .tool-cluster {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .tool-label {
      color: var(--muted);
      font-size: 10px;
      font-weight: 800;
      white-space: nowrap;
    }
    .colors { display: flex; align-items: center; gap: 7px; }
    .swatch {
      width: 30px;
      height: 30px;
      padding: 0;
      border: 2px solid #fff;
      border-radius: 50%;
      background: var(--swatch);
      box-shadow: 0 0 0 1px var(--line);
      cursor: pointer;
      transition: transform .15s, box-shadow .15s;
    }
    .swatch:hover { transform: scale(1.1); }
    .swatch.active {
      box-shadow: 0 0 0 2px var(--ink);
      transform: scale(1.08);
    }
    .toolbar-divider {
      width: 1px;
      height: 28px;
      background: var(--line);
    }
    .tool-group {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    input[type=range] { width: 84px; accent-color: var(--ink); }
    .size-dot {
      width: 22px;
      height: 22px;
      display: grid;
      place-items: center;
    }
    .size-dot::before {
      content: "";
      width: var(--brush-size);
      height: var(--brush-size);
      border-radius: 50%;
      background: var(--brush-color, var(--ink));
      box-shadow: 0 0 0 1px var(--line);
    }
    .size-value {
      min-width: 30px;
      color: var(--ink);
      font-variant-numeric: tabular-nums;
      font-weight: 800;
    }
    .tool-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      height: 36px;
      padding: 0 12px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fff;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      transition: border-color .15s, background .15s, color .15s;
    }
    .tool-button:hover { border-color: var(--ink); }
    .tool-button.active {
      border-color: var(--ink);
      background: var(--ink);
      color: #fff;
    }
    .tool-button.danger { margin-left: auto; color: #b7453d; }
    .tool-button.danger:hover { border-color: #b7453d; background: #fff2ef; }
    .chat-panel {
      display: flex;
      min-height: 0;
      flex: 1;
      flex-direction: column;
      padding: 0;
      border: 0;
      background: transparent;
    }
    .chat-head {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 9px;
    }
    .chat-head { margin: 0 0 10px; }
    .chat-head strong { font-size: 14px; }
    .chat-head span { color: var(--muted); font-size: 10px; }
    .chat-log {
      min-height: 150px;
      max-height: none;
      flex: 1;
      overflow-y: auto;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 13px;
      background: var(--paper);
      scroll-behavior: smooth;
    }
    .chat-line {
      display: flex;
      align-items: flex-start;
      gap: 7px;
      margin-bottom: 7px;
      font-size: 12px;
    }
    .chat-line:last-child { margin-bottom: 0; }
    .chat-author {
      flex: 0 0 auto;
      max-width: 82px;
      overflow: hidden;
      color: var(--chat-color, var(--ink));
      font-weight: 800;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .chat-bubble {
      min-width: 0;
      padding: 4px 7px;
      border-radius: 7px;
      border-left: 3px solid var(--blue);
      background: #eaf4ff;
      line-height: 1.5;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }
    .chat-line.system { display: block; }
    .chat-line.system .chat-bubble {
      padding: 7px 9px;
      border: 1px solid #efce62;
      border-left: 3px solid #e9b622;
      background: #fff4be;
      color: #715700;
      font-weight: 800;
      text-align: center;
    }
    .chat-form {
      display: flex;
      gap: 7px;
      margin-top: 8px;
    }
    .chat-input {
      flex: 1;
      min-width: 0;
      height: 38px;
      padding: 0 11px;
      border: 1px solid var(--line);
      border-radius: 9px;
      background: #fff;
      font-size: 12px;
      outline: none;
    }
    .chat-input:focus { border-color: var(--ink); }
    .chat-send {
      height: 38px;
      padding: 0 14px;
      border: 1px solid var(--ink);
      border-radius: 9px;
      background: var(--ink);
      color: #fff;
      font-size: 12px;
      font-weight: 800;
      cursor: pointer;
    }

    .side-card {
      position: sticky;
      top: 18px;
      display: flex;
      min-height: 0;
      max-height: calc(100dvh - 36px);
      flex-direction: column;
      padding: 18px;
    }
    .side-section { flex: 0 0 auto; }
    .side-section + .side-section {
      margin-top: 16px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
    }
    .side-section.chat-panel {
      min-height: 0;
      flex: 1 1 auto;
    }
    .side-head {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      margin-bottom: 15px;
    }
    .side-head h3 { margin: 0; font-size: 14px; }
    .side-head span { color: var(--muted); font-size: 11px; }
    .players {
      display: flex;
      max-height: 230px;
      overflow-y: auto;
      flex-direction: column;
      gap: 8px;
      margin-bottom: 0;
    }
    .player {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 10px;
      border: 1px solid transparent;
      border-radius: 12px;
      background: #f8f5ee;
      animation: player-in .25s ease-out;
      transition: transform .18s, border-color .18s, background .18s, box-shadow .18s;
    }
    .player.current-drawer {
      border-color: var(--ink);
      background: #fff4be;
      box-shadow: 3px 3px 0 var(--ink);
      transform: translate(-1px, -1px);
    }
    .player.current-drawer .avatar {
      box-shadow: 0 0 0 3px rgba(255, 216, 77, .55);
    }
    @keyframes player-in { from { opacity: 0; transform: translateY(4px); } }
    .avatar {
      width: 31px;
      height: 31px;
      display: grid;
      place-items: center;
      flex: 0 0 auto;
      border: 1.5px solid var(--ink);
      border-radius: 10px;
      background: var(--avatar);
      font-size: 12px;
      font-weight: 900;
    }
    .player-name {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 13px;
      font-weight: 700;
    }
    .player-identity {
      min-width: 0;
      flex: 1;
    }
    .player-name-line {
      display: flex;
      min-width: 0;
      align-items: center;
      gap: 6px;
    }
    .you { margin-left: 3px; color: var(--muted); font-size: 10px; }
    .mini-role {
      margin-left: auto;
      padding: 4px 7px;
      border-radius: 6px;
      background: #e5f5ed;
      color: #267552;
      font-size: 10px;
      font-weight: 800;
    }
    .mini-role.drawer { background: #fff0b7; color: #725600; }
    .player-score {
      flex: 0 0 auto;
      padding: 2px 6px;
      border-radius: 999px;
      background: #fff;
      color: var(--ink);
      font-size: 9px;
      font-variant-numeric: tabular-nums;
      font-weight: 800;
      white-space: nowrap;
    }
    .player.current-drawer .player-score { background: var(--sun); }
    .friend-add {
      width: 27px;
      height: 27px;
      display: grid;
      flex: 0 0 auto;
      place-items: center;
      padding: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--ink);
      font-size: 15px;
      font-weight: 900;
      line-height: 1;
      cursor: pointer;
      transition: border-color .15s, background .15s, color .15s;
    }
    .friend-add:hover { border-color: var(--ink); background: var(--sun); }
    .friend-add.added {
      border-color: #a8dcc2;
      background: #e5f5ed;
      color: #267552;
      cursor: default;
    }
    .friend-list {
      display: flex;
      max-height: 178px;
      overflow-y: auto;
      flex-direction: column;
      gap: 6px;
    }
    .friend-row {
      display: grid;
      grid-template-columns: 30px minmax(0, 1fr) auto;
      align-items: center;
      gap: 9px;
      padding: 7px 8px;
      border-radius: 10px;
      background: #f8f5ee;
    }
    .friend-avatar-wrap {
      position: relative;
      width: 30px;
      height: 30px;
    }
    .friend-avatar {
      width: 30px;
      height: 30px;
      display: grid;
      place-items: center;
      border: 1px solid var(--ink);
      border-radius: 9px;
      background: var(--friend-color, #ffd84d);
      font-size: 10px;
      font-weight: 900;
    }
    .online-dot {
      position: absolute;
      right: -2px;
      bottom: -2px;
      width: 9px;
      height: 9px;
      border: 2px solid var(--paper);
      border-radius: 50%;
      background: #b9bdc3;
    }
    .online-dot.online {
      background: #35a777;
      box-shadow: 0 0 0 2px rgba(53, 167, 119, .14);
    }
    .friend-info { min-width: 0; }
    .friend-name {
      display: block;
      overflow: hidden;
      font-size: 12px;
      font-weight: 800;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .friend-status {
      display: block;
      margin-top: 1px;
      color: var(--muted);
      font-size: 9px;
      font-weight: 700;
    }
    .friend-status.online { color: #267552; }
    .friend-remove {
      width: 24px;
      height: 24px;
      padding: 0;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--muted);
      font-size: 15px;
      cursor: pointer;
    }
    .friend-remove:hover { background: #fde8e5; color: #b7453d; }
    .friend-empty {
      padding: 13px 10px;
      border: 1px dashed var(--line);
      border-radius: 10px;
      color: var(--muted);
      font-size: 10px;
      line-height: 1.6;
      text-align: center;
    }
    .friend-request-form {
      display: flex;
      gap: 7px;
      margin-bottom: 10px;
    }
    .friend-request-form input {
      height: 36px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 9px;
      font-size: 11px;
    }
    .friend-request-form button,
    .request-action,
    .friend-invite {
      border: 1px solid var(--ink);
      border-radius: 8px;
      background: var(--ink);
      color: #fff;
      font-size: 10px;
      font-weight: 800;
      cursor: pointer;
      white-space: nowrap;
    }
    .friend-request-form button { height: 36px; padding: 0 10px; }
    .friend-requests {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .friend-request-row {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px;
      border: 1px solid #efce62;
      border-radius: 10px;
      background: #fff8d8;
    }
    .friend-request-name {
      min-width: 0;
      flex: 1;
      overflow: hidden;
      font-size: 11px;
      font-weight: 800;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .request-action { height: 27px; padding: 0 7px; }
    .request-action.reject {
      border-color: var(--line);
      background: #fff;
      color: var(--muted);
    }
    .friend-actions {
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .friend-invite {
      height: 24px;
      padding: 0 7px;
      background: #eaf4ff;
      color: #2569a9;
      border-color: #b9d9f6;
    }
    .friend-invite.invited {
      background: #f1eee7;
      color: var(--muted);
      border-color: var(--line);
    }
    .scoreboard {
      display: flex;
      max-height: 170px;
      overflow-y: auto;
      flex-direction: column;
      gap: 6px;
    }
    .scoreboard-row {
      display: grid;
      grid-template-columns: 22px minmax(0, 1fr) auto;
      align-items: center;
      gap: 9px;
      min-height: 34px;
      padding: 5px 8px;
      border-radius: 9px;
      background: #f8f5ee;
      font-size: 12px;
    }
    .scoreboard-row.leader { background: #fff2ad; }
    .scoreboard-rank {
      color: var(--muted);
      font-size: 10px;
      font-weight: 900;
      text-align: center;
    }
    .scoreboard-name {
      overflow: hidden;
      font-weight: 700;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .scoreboard-points {
      font-variant-numeric: tabular-nums;
      font-weight: 900;
    }
    .scoreboard-points small {
      color: var(--muted);
      font-size: 9px;
      font-weight: 700;
    }
    .rules {
      padding: 14px;
      border-radius: 14px;
      background: #f3f0e8;
    }
    .rules h4 { margin: 0 0 10px; font-size: 12px; }
    .rules ol {
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.8;
    }
    .toast {
      position: fixed;
      left: 50%;
      bottom: max(22px, env(safe-area-inset-bottom));
      z-index: 20;
      transform: translate(-50%, 20px);
      padding: 10px 15px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--ink);
      color: #fff;
      font-size: 12px;
      opacity: 0;
      pointer-events: none;
      transition: opacity .2s, transform .2s;
    }
    .toast.show { opacity: 1; transform: translate(-50%, 0); }
    .overlay-panel {
      position: fixed;
      inset: 0;
      z-index: 40;
      display: grid;
      place-items: center;
      padding: 20px;
      background: rgba(32, 36, 44, .54);
      backdrop-filter: blur(5px);
    }
    .panel-card {
      width: min(100%, 450px);
      max-height: calc(100dvh - 40px);
      overflow-y: auto;
      padding: 24px;
      border: 2px solid var(--ink);
      border-radius: 20px;
      background: var(--paper);
      box-shadow: 7px 7px 0 var(--ink);
    }
    .privacy-card { text-align: center; }
    .panel-card h2 { margin: 6px 0 16px; font-size: 28px; letter-spacing: -.04em; }
    .panel-card p { color: var(--muted); font-size: 12px; line-height: 1.7; }
    .panel-card label { margin-top: 12px; }
    .panel-card input, .panel-card textarea, .panel-card select {
      width: 100%;
      min-height: 40px;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 9px;
      background: #fff;
      outline: none;
    }
    .panel-card textarea { resize: vertical; }
    .panel-card .primary { width: 100%; height: 44px; margin-top: 16px; }
    .panel-heading, .admin-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
    .panel-heading h2 { margin: 0; }
    .panel-close { width: 32px; height: 32px; border: 1px solid var(--line); border-radius: 8px; background: #fff; font-size: 20px; line-height: 1; cursor: pointer; }
    .admin-toolbar { margin: 16px 0; }
    .admin-toolbar select { width: auto; flex: 1; }
    .admin-report-list { display: flex; flex-direction: column; gap: 8px; }
    .admin-report { padding: 10px; border: 1px solid var(--line); border-radius: 10px; background: #f8f5ee; font-size: 11px; }
    .admin-report strong { display: block; margin-bottom: 4px; }
    .admin-report p { margin: 4px 0; font-size: 11px; }
    .admin-report-actions { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
    .admin-report-actions button { height: 27px; padding: 0 7px; border: 1px solid var(--line); border-radius: 7px; background: #fff; font-size: 10px; cursor: pointer; }
    .moderation-actions { display: inline-flex; gap: 4px; margin-left: auto; }
    .moderation-button { height: 24px; padding: 0 6px; border: 1px solid var(--line); border-radius: 7px; background: #fff; color: var(--muted); font-size: 10px; cursor: pointer; }
    .moderation-button:hover { border-color: var(--ink); background: var(--sun); color: var(--ink); }
    .chat-moderation { display: inline-flex; gap: 4px; margin-left: 2px; }
    .chat-moderation button { padding: 0; border: 0; background: transparent; color: var(--muted); font-size: 10px; cursor: pointer; }
    .chat-moderation button:hover { color: var(--coral); }
    .reconnecting { color: #a36d00; }
    .toast.show { opacity: 1; transform: translate(-50%, 0); }
    .game-over {
      position: fixed;
      inset: 0;
      z-index: 30;
      display: grid;
      place-items: center;
      padding: 20px;
      background: rgba(32, 36, 44, .54);
      backdrop-filter: blur(5px);
    }
    .result-card {
      width: min(100%, 430px);
      max-height: calc(100dvh - 40px);
      overflow-y: auto;
      padding: 28px;
      border: 2px solid var(--ink);
      border-radius: 24px;
      background: var(--paper);
      box-shadow: 9px 9px 0 var(--ink);
    }
    .result-kicker {
      color: var(--coral);
      font-size: 10px;
      font-weight: 900;
      letter-spacing: .18em;
    }
    .result-card h2 {
      margin: 8px 0 4px;
      font-size: 34px;
      letter-spacing: -.05em;
    }
    .result-subtitle {
      margin: 0 0 20px;
      color: var(--muted);
      font-size: 12px;
    }
    .ranking-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-bottom: 20px;
    }
    .ranking-row {
      display: grid;
      grid-template-columns: 30px 34px minmax(0, 1fr) auto;
      align-items: center;
      gap: 9px;
      padding: 10px;
      border-radius: 12px;
      background: #f5f1e9;
    }
    .ranking-row.winner {
      border: 1.5px solid var(--ink);
      background: #fff1ad;
    }
    .ranking-number {
      font-size: 13px;
      font-weight: 900;
      text-align: center;
    }
    .ranking-avatar {
      width: 32px;
      height: 32px;
      display: grid;
      place-items: center;
      border: 1.5px solid var(--ink);
      border-radius: 9px;
      background: var(--rank-color);
      font-size: 11px;
      font-weight: 900;
    }
    .ranking-name {
      overflow: hidden;
      font-size: 13px;
      font-weight: 800;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .ranking-score {
      font-size: 17px;
      font-variant-numeric: tabular-nums;
      font-weight: 900;
    }
    .ranking-score small {
      margin-left: 2px;
      color: var(--muted);
      font-size: 10px;
    }
    .play-again {
      width: 100%;
      height: 52px;
      border: 2px solid var(--ink);
      border-radius: 14px;
      background: var(--coral);
      color: #fff;
      font-weight: 900;
      cursor: pointer;
      box-shadow: 4px 4px 0 var(--ink);
    }
    .play-again:hover { transform: translate(-1px, -1px); }
    .play-again:disabled { opacity: .65; cursor: wait; }

    @media (max-width: 860px) {
      .lobby-grid { grid-template-columns: 1fr; }
      .lobby-social { position: static; }
      .lobby-hero { min-height: 0; }
      .app { padding-left: 12px; padding-right: 12px; }
      .layout { grid-template-columns: 1fr; }
      .canvas-wrap { max-height: none; min-height: 240px; }
      .side-card {
        position: static;
        max-height: none;
        padding: 13px;
      }
      .side-head { margin-bottom: 10px; }
      .players {
        max-height: none;
        overflow-y: visible;
        flex-direction: row;
        overflow-x: auto;
        padding-bottom: 2px;
        margin-bottom: 0;
      }
      .player {
        min-width: max-content;
        flex: 0 0 auto;
        padding: 6px 8px;
        background: transparent;
        border: 1px solid var(--line);
      }
      .avatar { width: 26px; height: 26px; }
      .rules { display: none; }
      .chat-log { min-height: 140px; max-height: 240px; }
    }
    @media (max-width: 520px) {
      .lobby-view { padding-left: 12px; padding-right: 12px; }
      .lobby-topbar { margin-bottom: 12px; }
      .lobby-user { max-width: 145px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .lobby-hero { padding: 26px 22px 30px; border-radius: 20px; box-shadow: 5px 5px 0 var(--ink); }
      .lobby-hero h1 { margin-top: 30px; font-size: 48px; }
      .room-entry { align-items: stretch; flex-direction: column; margin-top: 42px; }
      .room-entry button { width: 100%; }
      .lobby-steps { gap: 10px; margin-top: 26px; }
      header { margin-bottom: 10px; }
      .brand small { display: none; }
      .brand h2 { font-size: 18px; }
      .header-actions { gap: 6px; }
      .top-timer { min-width: 92px; padding: 6px 9px 7px; }
      .top-timer .timer-label { display: none; }
      .top-timer #round-timer { font-size: 21px; }
      .status { padding: 6px 9px; }
      .status #connection-text { display: none; }
      .board-card { padding: 8px; border-radius: 18px; }
      .players {
        flex-direction: column;
        overflow: visible;
      }
      .player { width: 100%; }
      .player .friend-add { width: 29px; height: 29px; }
      .friend-list { max-height: none; }
      .board-head { min-height: 44px; padding-bottom: 7px; }
      .role-hint { display: none; }
      .round-strip { min-height: 37px; margin-bottom: 7px; padding: 6px 9px; }
      .round-kicker { display: none; }
      .round-title { font-size: 12px; }
      .word-card { margin-bottom: 7px; padding: 8px 10px; box-shadow: 2px 2px 0 var(--ink); }
      .word-card span { font-size: 9px; }
      .canvas-wrap { aspect-ratio: 1 / 1; border-radius: 12px; }
      .toolbar { gap: 8px; padding-top: 10px; }
      .swatch { width: 27px; height: 27px; }
      .colors { gap: 6px; }
      .tool-group span { display: none; }
      input[type=range] { width: 62px; }
      .toolbar-divider { display: none; }
      .tool-button { height: 33px; padding: 0 10px; }
      .chat-panel { margin-top: 0; }
      .chat-log { height: 112px; }
      .login-card { padding: 30px 24px; box-shadow: 6px 6px 0 var(--ink); }
      .join-row { flex-direction: column; }
      .primary { width: 100%; }
    }
  </style>
</head>
<body>
  <section id="login" class="login">
    <div class="login-card">
      <div class="logo-mark"><span class="logo-dot"></span>DRAW TOGETHER</div>
      <h1>一起<span class="accent">画</span>。</h1>
      <p class="lead">同一个房间，同一块画布。<br>第一笔，从你开始。</p>
      <form id="join-form">
        <div class="auth-tabs" role="tablist" aria-label="账号操作">
          <button id="login-tab" class="auth-tab active" type="button" role="tab" aria-selected="true">登录</button>
          <button id="register-tab" class="auth-tab" type="button" role="tab" aria-selected="false">注册新用户</button>
        </div>
        <div class="auth-field">
          <label for="username">用户名</label>
          <input id="username" maxlength="20" autocomplete="username" placeholder="2-20 个中英文字符" required>
        </div>
        <div class="auth-field">
          <label for="password">密码</label>
          <input id="password" type="password" minlength="6" maxlength="20" autocomplete="current-password" placeholder="6-20 个字符" required>
        </div>
        <p id="auth-error" class="auth-error hidden" role="alert"></p>
        <button id="join-button" class="primary auth-submit" type="submit">登录并进入大厅</button>
      </form>
      <p id="auth-hint" class="auth-switch-hint">还没有账号？点击上方“注册新用户”创建账号。</p>
      <p class="login-note">账号保存在本机服务中 · 第一位进入房间的玩家自动成为画手</p>
    </div>
  </section>

  <main id="lobby-view" class="lobby-view hidden">
    <div class="lobby-topbar">
      <div class="brand">
        <span class="logo-dot"></span>
        <div>
          <h2>一起画</h2>
          <small>GAME LOBBY</small>
        </div>
      </div>
      <div class="lobby-top-actions">
        <div id="lobby-user" class="lobby-user">已登录</div>
        <button id="profile-button" class="lobby-action" type="button">资料</button>
        <button id="admin-button" class="lobby-action admin-action hidden" type="button">管理</button>
        <button id="delete-account-button" class="lobby-action danger-action" type="button">删除账号</button>
      </div>
    </div>

    <div class="lobby-grid">
      <section class="lobby-hero">
        <span class="lobby-kicker">DRAW · LAUGH · CONNECT</span>
        <h1>画点什么，<br>让朋友猜。</h1>
        <p class="lobby-copy">创建一个房间，邀请在线好友。每个人都会成为画手，用三分钟画出今晚最好笑的答案。</p>
        <div class="room-entry">
          <div class="room-entry-copy">
            <strong>一起画 · 公共房间</strong>
            <span id="lobby-room-summary">等待创建第一轮游戏</span>
          </div>
          <button id="create-room" type="button" disabled>创建房间</button>
        </div>
        <div class="lobby-steps">
          <span>5 轮一局</span>
          <span>猜中得 1 分</span>
          <span>支持中文与拼音</span>
        </div>
      </section>

      <aside class="lobby-social">
        <section class="side-section">
          <div class="side-head">
            <h3>添加好友</h3>
            <span>需对方同意</span>
          </div>
          <form id="friend-request-form" class="friend-request-form">
            <input id="friend-username" maxlength="20" autocomplete="off" placeholder="输入对方用户名">
            <button type="submit">发送申请</button>
          </form>
          <div id="friend-request-list" class="friend-requests">
            <div class="lobby-empty">暂无新的好友申请</div>
          </div>
        </section>
        <section class="side-section">
          <div class="side-head">
            <h3>我的好友</h3>
            <span id="lobby-friend-online-count">在线 0</span>
          </div>
          <div id="lobby-friend-list" class="friend-list">
            <div class="friend-empty">在在线玩家旁点击 <strong>+</strong> 添加好友</div>
          </div>
        </section>
      </aside>
    </div>
  </main>

  <main id="app" class="app hidden">
    <header>
      <div class="brand">
        <span class="logo-dot"></span>
        <div>
          <h2>一起画</h2>
          <small>LIVE DRAWING ROOM</small>
        </div>
      </div>
      <div class="header-actions">
        <div id="top-timer" class="top-timer">
          <span class="timer-label">本轮剩余</span>
          <strong id="round-timer">60</strong>
          <small id="timer-unit">秒</small>
        </div>
        <div id="connection" class="status">
          <span class="status-dot"></span>
          <span id="connection-text">实时连接</span>
        </div>
      </div>
    </header>

    <div class="layout">
      <section class="board-card">
        <div class="board-head">
          <div id="role-badge" class="role-badge">
            <span class="glyph">✎</span>
            <span id="role-text">正在连接…</span>
          </div>
          <span id="role-hint" class="role-hint">你的每一笔都会同步给房间里的所有人</span>
        </div>
        <div class="round-strip">
          <div class="round-copy">
            <span class="round-kicker">CURRENT ROUND</span>
            <strong id="round-title" class="round-title">等待第一轮开始…</strong>
          </div>
        </div>
        <div id="word-card" class="word-card hidden">
          <span>本轮词语 · 只有画手可见</span>
          <strong id="word-text">—</strong>
        </div>
        <div id="canvas-wrap" class="canvas-wrap readonly">
          <canvas id="board" aria-label="多人共享画板"></canvas>
          <span id="readonly-cover" class="readonly-cover">👀 观战模式 · 画布只读</span>
        </div>
        <div id="toolbar" class="toolbar hidden">
          <div class="tool-cluster">
            <span class="tool-label">颜色</span>
            <div id="colors" class="colors" aria-label="画笔颜色">
              <button class="swatch" type="button" data-color="#ff5f57" style="--swatch:#ff5f57" aria-label="红色" title="红色"></button>
              <button class="swatch" type="button" data-color="#2f80ed" style="--swatch:#2f80ed" aria-label="蓝色" title="蓝色"></button>
              <button class="swatch active" type="button" data-color="#20242c" style="--swatch:#20242c" aria-label="黑色" title="黑色"></button>
            </div>
          </div>
          <span class="toolbar-divider"></span>
          <label class="tool-group" for="brush-size">
            <span class="size-dot" id="size-preview" style="--brush-size:5px"></span>
            <span>粗细</span>
            <input id="brush-size" type="range" min="2" max="18" value="5">
            <output id="brush-size-value" class="size-value">5</output>
          </label>
          <span class="toolbar-divider"></span>
          <button id="eraser-button" class="tool-button" type="button" aria-pressed="false">⌫ 橡皮</button>
          <button id="clear-button" class="tool-button danger" type="button">清空画布</button>
        </div>
      </section>

      <aside class="side-card">
        <section class="side-section">
          <div class="side-head">
            <h3>玩家列表</h3>
            <span id="player-count">0 位玩家</span>
          </div>
          <div id="players" class="players"></div>
        </section>
        <section class="side-section">
          <div class="side-head">
            <h3>好友</h3>
            <span id="friend-online-count">在线 0</span>
          </div>
          <div id="friend-list" class="friend-list">
            <div class="friend-empty">在玩家列表点击 <strong>+</strong> 添加好友</div>
          </div>
        </section>
        <section class="side-section">
          <div class="side-head">
            <h3>实时积分</h3>
            <span>按分数排序</span>
          </div>
          <div id="scoreboard" class="scoreboard">
            <div class="scoreboard-row">
              <span class="scoreboard-rank">–</span>
              <span class="scoreboard-name">等待玩家进入</span>
              <span class="scoreboard-points">0 <small>分</small></span>
            </div>
          </div>
        </section>
        <section class="side-section chat-panel">
          <div class="chat-head">
            <strong>聊天猜词</strong>
            <span id="chat-role-hint">输入答案或全拼，猜中进入下一轮</span>
          </div>
          <div id="chat-log" class="chat-log" aria-live="polite">
            <div class="chat-line system">
              <div class="chat-bubble">猜手输入答案或拼音，答案会被实时判定。</div>
            </div>
          </div>
          <form id="guess-form" class="chat-form">
            <input id="guess-input" class="chat-input" maxlength="200" autocomplete="off" placeholder="输入答案或拼音…">
            <button class="chat-send" type="submit">发送</button>
          </form>
        </section>
      </aside>
    </div>
  </main>

  <div id="game-over" class="game-over hidden" role="dialog" aria-modal="true" aria-labelledby="result-title">
    <div class="result-card">
      <span class="result-kicker">FINAL SCORE</span>
      <h2 id="result-title">游戏结束</h2>
      <p id="result-subtitle" class="result-subtitle">本轮派对最终排名</p>
      <div id="ranking-list" class="ranking-list"></div>
      <button id="play-again" class="play-again" type="button">再来一局</button>
    </div>
  </div>

  <div id="toast" class="toast" role="status"></div>

  <div id="privacy-panel" class="overlay-panel hidden" role="dialog" aria-modal="true" aria-labelledby="privacy-title">
    <div class="panel-card privacy-card">
      <span class="result-kicker">PRIVACY</span>
      <h2 id="privacy-title">请先同意隐私协议</h2>
      <p>我们会保存账号资料、好友关系和举报记录，用于提供多人游戏与社区管理功能。</p>
      <button id="privacy-accept-button" class="primary" type="button">同意并继续</button>
    </div>
  </div>

  <div id="profile-panel" class="overlay-panel hidden" role="dialog" aria-modal="true" aria-labelledby="profile-title">
    <div class="panel-card">
      <div class="panel-heading"><h2 id="profile-title">我的资料</h2><button class="panel-close" data-close-panel="profile-panel" type="button" aria-label="关闭">×</button></div>
      <form id="profile-form">
        <label for="profile-nickname">昵称</label>
        <input id="profile-nickname" maxlength="20" required>
        <label for="profile-bio">简介</label>
        <textarea id="profile-bio" maxlength="160" rows="4"></textarea>
        <button class="primary" type="submit">保存资料</button>
      </form>
    </div>
  </div>

  <div id="admin-panel" class="overlay-panel hidden" role="dialog" aria-modal="true" aria-labelledby="admin-title">
    <div class="panel-card admin-card">
      <div class="panel-heading"><h2 id="admin-title">管理员面板</h2><button class="panel-close" data-close-panel="admin-panel" type="button" aria-label="关闭">×</button></div>
      <div class="admin-toolbar"><select id="admin-status-filter"><option value="">全部状态</option><option value="open">待处理</option><option value="reviewing">处理中</option><option value="resolved">已解决</option><option value="rejected">已驳回</option></select><button id="admin-load-button" class="lobby-action" type="button">加载举报</button></div>
      <div id="admin-report-list" class="admin-report-list"><div class="lobby-empty">点击“加载举报”查看记录</div></div>
    </div>
  </div>

  <script>
    (() => {
      const $ = (selector) => document.querySelector(selector);
      const login = $("#login");
      const lobbyView = $("#lobby-view");
      const app = $("#app");
      const joinForm = $("#join-form");
      const usernameInput = $("#username");
      const passwordInput = $("#password");
      const joinButton = $("#join-button");
      const loginTab = $("#login-tab");
      const registerTab = $("#register-tab");
      const authError = $("#auth-error");
      const authHint = $("#auth-hint");
      const lobbyUser = $("#lobby-user");
      const profileButton = $("#profile-button");
      const adminButton = $("#admin-button");
      const deleteAccountButton = $("#delete-account-button");
      const privacyPanel = $("#privacy-panel");
      const privacyAcceptButton = $("#privacy-accept-button");
      const profilePanel = $("#profile-panel");
      const profileForm = $("#profile-form");
      const profileNickname = $("#profile-nickname");
      const profileBio = $("#profile-bio");
      const adminPanel = $("#admin-panel");
      const adminLoadButton = $("#admin-load-button");
      const adminStatusFilter = $("#admin-status-filter");
      const adminReportList = $("#admin-report-list");
      const friendRequestForm = $("#friend-request-form");
      const friendUsername = $("#friend-username");
      const friendRequestList = $("#friend-request-list");
      const lobbyFriendList = $("#lobby-friend-list");
      const lobbyFriendOnlineCount = $("#lobby-friend-online-count");
      const lobbyRoomSummary = $("#lobby-room-summary");
      const createRoomButton = $("#create-room");
      const canvas = $("#board");
      const canvasWrap = $("#canvas-wrap");
      const ctx = canvas.getContext("2d");
      const toolbar = $("#toolbar");
      const readonlyCover = $("#readonly-cover");
      const roleBadge = $("#role-badge");
      const roleText = $("#role-text");
      const roleHint = $("#role-hint");
      const playersBox = $("#players");
      const playerCount = $("#player-count");
      const friendList = $("#friend-list");
      const friendOnlineCount = $("#friend-online-count");
      const scoreboard = $("#scoreboard");
      const roundTitle = $("#round-title");
      const roundTimer = $("#round-timer");
      const timerUnit = $("#timer-unit");
      const topTimer = $("#top-timer");
      const wordCard = $("#word-card");
      const wordText = $("#word-text");
      const chatLog = $("#chat-log");
      const chatRoleHint = $("#chat-role-hint");
      const guessForm = $("#guess-form");
      const guessInput = $("#guess-input");
      const gameOverPanel = $("#game-over");
      const resultSubtitle = $("#result-subtitle");
      const rankingList = $("#ranking-list");
      const playAgainButton = $("#play-again");
      const connection = $("#connection");
      const connectionText = $("#connection-text");
      const brushSize = $("#brush-size");
      const brushSizeValue = $("#brush-size-value");
      const sizePreview = $("#size-preview");
      const eraserButton = $("#eraser-button");
      const toast = $("#toast");

      let socket = null;
      let authMode = "login";
      let myUsername = "";
      let myPassword = "";
      let accountRole = "user";
      let reconnectAttempts = 0;
      let reconnectTimer = 0;
      let reconnecting = false;
      let intentionalClose = false;
      let privacyAccepted = true;
      let myId = "";
      let myRole = "guesser";
      let color = "#20242c";
      let lastColor = "#20242c";
      let eraserActive = false;
      let width = 5;
      let drawing = false;
      let lastPoint = null;
      let segments = [];
      let seenIds = new Set();
      let resizeFrame = 0;
      let toastTimer = 0;
      let countdownTimer = 0;
      let lastRoundNumber = 0;
      let currentPlayers = [];
      let friends = [];
      let incomingFriendRequests = [];
      let outgoingFriendRequests = [];
      let socialRoom = {
        roomActive: false,
        roomPlayers: 0,
        roomOwnerName: null,
        roomInvited: false
      };

      function isFriend(playerName) {
        return friends.some((friend) => friend.name === playerName);
      }

      function addFriend(player) {
        requestFriend(player.name);
      }

      function removeFriend(playerName) {
        if (send({ type: "friend_remove", username: playerName })) {
          showToast(`正在移除好友 ${playerName}`);
        }
      }

      function requestFriend(username) {
        const target = String(username || "").trim();
        if (!target) return;
        if (target === myUsername || isFriend(target)) {
          showToast(target === myUsername ? "不能添加自己" : "你们已经是好友");
          return;
        }
        if (send({ type: "friend_request", username: target })) {
          showToast("好友申请已发送");
        }
      }

      function acceptFriendRequest(requester) {
        send({ type: "friend_accept", username: requester });
      }

      function rejectFriendRequest(requester) {
        send({ type: "friend_reject", username: requester });
      }

      function showToast(message) {
        toast.textContent = message;
        toast.classList.add("show");
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => toast.classList.remove("show"), 2200);
      }

      function setConnection(online) {
        connection.classList.toggle("offline", !online);
        connectionText.textContent = online ? "实时连接" : "连接已断开";
      }

      function send(payload) {
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify(payload));
          return true;
        }
        return false;
      }

      function openPanel(panel) { panel.classList.remove("hidden"); }
      function closePanel(panel) { panel.classList.add("hidden"); }
      function requestBlock(target) {
        const name = String(target || "").trim();
        if (!name || name === myUsername) return showToast("不能操作自己");
        if (confirm(`确认屏蔽 ${name}？屏蔽后将不再收到对方聊天。`)) {
          if (send({ type: "block_user", username: name })) showToast(`已提交屏蔽 ${name}`);
        }
      }
      function requestReport(type, target, extra = {}) {
        const name = String(target || "").trim();
        if (!name || name === myUsername) return showToast("不能举报自己");
        const reason = prompt("请输入举报原因（必填）", "不当内容");
        if (reason === null || !reason.trim()) return;
        const payload = { type: type === "chat" ? "report_chat" : "report_user", target: name, reason: reason.trim(), ...extra };
        if (send(payload)) showToast("举报已提交");
      }
      function addModerationActions(container, target) {
        const actions = document.createElement("span");
        actions.className = "moderation-actions";
        const block = document.createElement("button");
        block.className = "moderation-button";
        block.type = "button";
        block.textContent = "屏蔽";
        block.addEventListener("click", () => requestBlock(target));
        const report = document.createElement("button");
        report.className = "moderation-button";
        report.type = "button";
        report.textContent = "举报";
        report.addEventListener("click", () => requestReport("user", target));
        actions.append(block, report);
        container.append(actions);
      }
      function renderAdminReports(reports) {
        adminReportList.replaceChildren();
        if (!Array.isArray(reports) || !reports.length) {
          const empty = document.createElement("div");
          empty.className = "lobby-empty";
          empty.textContent = "暂无举报记录";
          adminReportList.append(empty);
          return;
        }
        reports.forEach((report) => {
          const row = document.createElement("div");
          row.className = "admin-report";
          const title = document.createElement("strong");
          title.textContent = `${report.type === "chat" ? "聊天" : "用户"} · ${report.targetUsername || report.target || "未知"}`;
          const details = document.createElement("p");
          details.textContent = `${report.reason || "未说明"} · ${report.status || "open"}`;
          if (report.text) details.textContent += ` · ${report.text}`;
          const actions = document.createElement("div");
          actions.className = "admin-report-actions";
          [["处理中", "reviewing"], ["已解决", "resolved"], ["驳回", "rejected"]].forEach(([label, status]) => {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = label;
            button.addEventListener("click", () => send({ type: "admin_report_status", reportId: report.reportId, status, action: label }));
            actions.append(button);
          });
          [["禁言", "mute"], ["封禁", "ban"]].forEach(([label, action]) => {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = label;
            button.addEventListener("click", () => {
              const duration = prompt(`${label}时长（秒）`, action === "ban" ? "3600" : "600");
              if (duration === null) return;
              const reason = prompt("操作原因", report.reason || "违反社区规则") || "";
              send({ type: action === "mute" ? "admin_mute" : "admin_ban", username: report.targetUsername || report.target, duration: Number(duration), reason });
            });
            actions.append(button);
          });
          row.append(title, details, actions);
          adminReportList.append(row);
        });
      }
      function loadAdminReports() {
        if (!send({ type: "admin_report_list", status: adminStatusFilter.value })) showToast("当前未连接");
      }

      function setAuthButtonLabel() {
        joinButton.textContent = authMode === "register" ? "注册并进入大厅" : "登录并进入大厅";
      }

      function showAuthError(message) {
        authError.textContent = message;
        authError.classList.remove("hidden");
      }

      function clearAuthError() {
        authError.textContent = "";
        authError.classList.add("hidden");
      }

      function setAuthMode(mode) {
        authMode = mode;
        const isRegister = mode === "register";
        loginTab.classList.toggle("active", !isRegister);
        registerTab.classList.toggle("active", isRegister);
        loginTab.setAttribute("aria-selected", String(!isRegister));
        registerTab.setAttribute("aria-selected", String(isRegister));
        passwordInput.autocomplete = isRegister ? "new-password" : "current-password";
        authHint.textContent = isRegister
          ? "注册成功后将自动登录并进入房间。"
          : "还没有账号？点击上方“注册新用户”创建账号。";
        clearAuthError();
        setAuthButtonLabel();
      }

      function sendAuth(useMemory = false) {
        const username = useMemory ? myUsername : usernameInput.value.trim();
        const password = useMemory ? myPassword : passwordInput.value;
        if (!username) {
          showAuthError("请输入用户名");
          usernameInput.focus();
          return false;
        }
        if (password.length < 6 || password.length > 20) {
          showAuthError("密码长度需为 6-20 个字符");
          usernameInput.focus();
          return false;
        }
        clearAuthError();
        myUsername = username;
        myPassword = password;
        intentionalClose = false;
        if (!useMemory) reconnectAttempts = 0;
        joinButton.disabled = true;
        joinButton.textContent = authMode === "register" ? "正在注册…" : "正在登录…";
        return send({
          type: useMemory ? "join" : (authMode === "register" ? "register" : "join"),
          username,
          password
        });
      }

      function resizeCanvas() {
        const rect = canvasWrap.getBoundingClientRect();
        const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
        canvas.width = Math.max(1, Math.round(rect.width * dpr));
        canvas.height = Math.max(1, Math.round(rect.height * dpr));
        canvas.style.width = `${rect.width}px`;
        canvas.style.height = `${rect.height}px`;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        redrawAll();
      }

      function drawSegment(segment) {
        const rect = canvas.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        const x0 = segment.x0 * rect.width;
        const y0 = segment.y0 * rect.height;
        const x1 = segment.x1 * rect.width;
        const y1 = segment.y1 * rect.height;
        ctx.strokeStyle = segment.color;
        ctx.fillStyle = segment.color;
        ctx.lineWidth = segment.width;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        if (x0 === x1 && y0 === y1) {
          ctx.beginPath();
          ctx.arc(x0, y0, segment.width / 2, 0, Math.PI * 2);
          ctx.fill();
          return;
        }
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.lineTo(x1, y1);
        ctx.stroke();
      }

      function redrawAll() {
        const rect = canvas.getBoundingClientRect();
        ctx.clearRect(0, 0, rect.width, rect.height);
        for (const segment of segments) drawSegment(segment);
      }

      function addSegment(segment) {
        if (seenIds.has(segment.id)) return;
        seenIds.add(segment.id);
        segments.push(segment);
        drawSegment(segment);
      }

      function pointFromEvent(event) {
        const rect = canvas.getBoundingClientRect();
        return {
          x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
          y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height))
        };
      }

      function newSegment(from, to) {
        return {
          id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`,
          x0: from.x,
          y0: from.y,
          x1: to.x,
          y1: to.y,
          color,
          width
        };
      }

      canvas.addEventListener("pointerdown", (event) => {
        if (myRole !== "drawer" || (event.pointerType === "mouse" && event.button !== 0)) return;
        event.preventDefault();
        canvas.setPointerCapture(event.pointerId);
        drawing = true;
        lastPoint = pointFromEvent(event);
        const segment = newSegment(lastPoint, { x: lastPoint.x + 0.00001, y: lastPoint.y });
        addSegment(segment);
        send({ type: "stroke", ...segment });
      });

      canvas.addEventListener("pointermove", (event) => {
        if (!drawing || myRole !== "drawer") return;
        event.preventDefault();
        const nextPoint = pointFromEvent(event);
        if (!lastPoint) lastPoint = nextPoint;
        const dx = (nextPoint.x - lastPoint.x) * canvas.clientWidth;
        const dy = (nextPoint.y - lastPoint.y) * canvas.clientHeight;
        if (dx * dx + dy * dy < 0.4) return;
        const segment = newSegment(lastPoint, nextPoint);
        addSegment(segment);
        send({ type: "stroke", ...segment });
        lastPoint = nextPoint;
      });

      function stopDrawing(event) {
        if (!drawing) return;
        drawing = false;
        lastPoint = null;
        if (event && canvas.hasPointerCapture(event.pointerId)) {
          canvas.releasePointerCapture(event.pointerId);
        }
      }

      canvas.addEventListener("pointerup", stopDrawing);
      canvas.addEventListener("pointercancel", stopDrawing);
      canvas.addEventListener("lostpointercapture", () => {
        drawing = false;
        lastPoint = null;
      });

      document.querySelectorAll(".swatch").forEach((button) => {
        button.addEventListener("click", () => {
          lastColor = button.dataset.color;
          setEraser(false);
        });
      });

      brushSize.addEventListener("input", () => {
        width = Number(brushSize.value);
        sizePreview.style.setProperty("--brush-size", `${Math.max(3, width)}px`);
        brushSizeValue.textContent = String(width);
      });

      function setEraser(enabled) {
        eraserActive = enabled;
        color = enabled ? "#ffffff" : lastColor;
        eraserButton.classList.toggle("active", enabled);
        eraserButton.setAttribute("aria-pressed", String(enabled));
        document.querySelectorAll(".swatch").forEach((button) => {
          button.classList.toggle("active", !enabled && button.dataset.color === lastColor);
        });
        sizePreview.style.setProperty("--brush-color", color);
      }

      eraserButton.addEventListener("click", () => setEraser(!eraserActive));
      setEraser(false);

      $("#clear-button").addEventListener("click", () => {
        if (myRole !== "drawer") return;
        if (segments.length && !window.confirm("确定清空所有人的画布吗？")) return;
        segments = [];
        seenIds.clear();
        redrawAll();
        send({ type: "clear" });
      });

      function setRole(role) {
        myRole = role;
        const isDrawer = role === "drawer";
        canvasWrap.classList.toggle("readonly", !isDrawer);
        toolbar.classList.toggle("hidden", !isDrawer);
        readonlyCover.classList.toggle("hidden", isDrawer);
        roleBadge.classList.toggle("guesser", !isDrawer);
        roleBadge.querySelector(".glyph").textContent = isDrawer ? "✎" : "👀";
        roleText.textContent = isDrawer ? "你是画手" : "你是猜手";
        roleHint.textContent = isDrawer
          ? "你的每一笔都会实时同步给房间里的所有人"
          : "画布只读，你可以实时观看画手作画";
        if (!isDrawer) wordCard.classList.add("hidden");
        chatRoleHint.textContent = isDrawer
          ? "画手消息只作为普通聊天，不参与猜词"
          : "输入答案或全拼，猜中立即进入下一轮";
        guessInput.placeholder = isDrawer
          ? "画手聊天，不参与猜词…"
          : "输入答案或拼音…";
      }

      function appendChat({ playerName = "", text = "", color = "#20242c", system = false, messageId = "" }) {
        const line = document.createElement("div");
        line.className = `chat-line ${system ? "system" : "guess"}`;
        if (!system) {
          const author = document.createElement("span");
          author.className = "chat-author";
          author.style.setProperty("--chat-color", color);
          author.textContent = playerName;
          line.append(author);
          const moderation = document.createElement("span");
          moderation.className = "chat-moderation";
          const block = document.createElement("button");
          block.type = "button";
          block.textContent = "屏蔽";
          block.addEventListener("click", () => requestBlock(playerName));
          const report = document.createElement("button");
          report.type = "button";
          report.textContent = "举报";
          report.addEventListener("click", () => requestReport("chat", playerName, { text, messageId }));
          moderation.append(block, report);
          line.append(moderation);
        }
        const bubble = document.createElement("div");
        bubble.className = "chat-bubble";
        bubble.textContent = text;
        line.append(bubble);
        chatLog.append(line);
        chatLog.scrollTop = chatLog.scrollHeight;
      }

      function startCountdown(seconds) {
        window.clearInterval(countdownTimer);
        timerUnit.textContent = "秒";
        const startedAt = performance.now();
        const duration = Math.max(0, Number(seconds) || 0);
        const updateClock = () => {
          const elapsed = (performance.now() - startedAt) / 1000;
          const left = Math.max(0, Math.ceil(duration - elapsed));
          roundTimer.textContent = String(left);
          topTimer.classList.toggle("urgent", left <= 10);
          if (left <= 0) window.clearInterval(countdownTimer);
        };
        updateClock();
        countdownTimer = window.setInterval(updateClock, 250);
      }

      function applyRound(round) {
        if (!round) return;
        const isNewRound = round.roundNumber !== lastRoundNumber;
        if (isNewRound) {
          lastRoundNumber = round.roundNumber;
          wordText.textContent = "—";
          wordCard.classList.add("hidden");
        }
        setRole(round.drawerId === myId ? "drawer" : "guesser");
        roundTitle.textContent = `第 ${round.roundNumber} / ${round.maxRounds || 5} 轮 · 轮到 ${round.drawerName} 画了`;
        startCountdown(round.remaining ?? round.duration);
      }

      function showGameOver(message) {
        window.clearInterval(countdownTimer);
        roundTimer.textContent = "结束";
        timerUnit.textContent = "";
        topTimer.classList.remove("urgent");
        wordCard.classList.add("hidden");
        guessInput.disabled = true;
        playAgainButton.disabled = false;
        resultSubtitle.textContent = `共进行 ${message.roundsPlayed || lastRoundNumber} 轮 · 最终排名`;
        rankingList.replaceChildren();
        const ranking = Array.isArray(message.ranking) ? message.ranking : [];
        ranking.forEach((player) => {
          const row = document.createElement("div");
          row.className = `ranking-row${player.rank === 1 ? " winner" : ""}`;
          const rank = document.createElement("span");
          rank.className = "ranking-number";
          rank.textContent = `#${player.rank}`;
          const avatar = document.createElement("span");
          avatar.className = "ranking-avatar";
          avatar.style.setProperty("--rank-color", player.color || "#ffd84d");
          avatar.textContent = Array.from(player.name || "?")[0];
          const name = document.createElement("span");
          name.className = "ranking-name";
          name.textContent = player.name;
          const score = document.createElement("span");
          score.className = "ranking-score";
          score.append(document.createTextNode(String(player.score || 0)));
          const unit = document.createElement("small");
          unit.textContent = "分";
          score.append(unit);
          row.append(rank, avatar, name, score);
          rankingList.append(row);
        });
        gameOverPanel.classList.remove("hidden");
      }

      function hideGameOver() {
        gameOverPanel.classList.add("hidden");
        guessInput.disabled = false;
        playAgainButton.disabled = false;
      }

      function applySocialState(message) {
        const wasInvited = socialRoom.roomInvited;
        friends = Array.isArray(message.friends) ? message.friends : [];
        incomingFriendRequests = Array.isArray(message.incomingRequests)
          ? message.incomingRequests
          : [];
        outgoingFriendRequests = Array.isArray(message.outgoingRequests)
          ? message.outgoingRequests
          : [];
        socialRoom = {
          roomActive: Boolean(message.roomActive),
          roomPlayers: Number(message.roomPlayers) || 0,
          roomOwnerName: message.roomOwnerName || null,
          roomInvited: Boolean(message.roomInvited)
        };

        if (!socialRoom.roomActive) {
          createRoomButton.disabled = false;
          createRoomButton.textContent = "创建房间";
          lobbyRoomSummary.textContent = "房间空闲，点击创建并成为第一位画手";
        } else if (socialRoom.roomInvited) {
          createRoomButton.disabled = false;
          createRoomButton.textContent = "接受邀请并加入";
          lobbyRoomSummary.textContent = `${socialRoom.roomOwnerName || "好友"} 邀请你加入房间 · ${socialRoom.roomPlayers} 人`;
        } else {
          createRoomButton.disabled = true;
          createRoomButton.textContent = "等待邀请";
          lobbyRoomSummary.textContent = `${socialRoom.roomOwnerName || "好友"} 的房间进行中 · 仅受邀好友可加入`;
        }

        if (socialRoom.roomInvited && !wasInvited) {
          showToast(`${socialRoom.roomOwnerName || "好友"} 邀请你加入房间`);
        }
        renderFriendRequests();
        renderFriends(currentPlayers);
      }

      function showLobby(message) {
        myUsername = message.username || myUsername;
        accountRole = message.role || accountRole || "user";
        privacyAccepted = Boolean(message.privacyAccepted);
        lobbyUser.textContent = `已登录 · ${message.nickname || myUsername}`;
        adminButton.classList.toggle("hidden", accountRole !== "admin");
        if (message.nickname) profileNickname.value = message.nickname;
        if (typeof message.bio === "string") profileBio.value = message.bio;
        localStorage.setItem("draw-together-user", myUsername);
        passwordInput.value = "";
        clearAuthError();
        login.classList.add("hidden");
        app.classList.add("hidden");
        lobbyView.classList.remove("hidden");
        if (!privacyAccepted) openPanel(privacyPanel);
        else closePanel(privacyPanel);
        applySocialState(message);
      }

      function resetToLogin(message = "") {
        window.clearTimeout(reconnectTimer);
        reconnectAttempts = 0;
        reconnecting = false;
        intentionalClose = true;
        myPassword = "";
        if (socket) {
          try { socket.close(); } catch {}
          socket = null;
        }
        login.classList.remove("hidden");
        lobbyView.classList.add("hidden");
        app.classList.add("hidden");
        closePanel(privacyPanel);
        closePanel(profilePanel);
        closePanel(adminPanel);
        joinButton.disabled = false;
        setAuthButtonLabel();
        if (message) showAuthError(message);
      }

      function renderScoreboard(players) {
        const ranked = [...players].sort(
          (left, right) => (Number(right.score) || 0) - (Number(left.score) || 0)
        );
        scoreboard.replaceChildren();
        ranked.forEach((player, index) => {
          const row = document.createElement("div");
          const score = Number(player.score) || 0;
          row.className = `scoreboard-row${index === 0 && score > 0 ? " leader" : ""}`;

          const rank = document.createElement("span");
          rank.className = "scoreboard-rank";
          rank.textContent = String(index + 1).padStart(2, "0");

          const name = document.createElement("span");
          name.className = "scoreboard-name";
          name.textContent = player.name;
          if (player.id === myId) name.append("（你）");

          const points = document.createElement("span");
          points.className = "scoreboard-points";
          points.append(document.createTextNode(String(score)));
          const unit = document.createElement("small");
          unit.textContent = " 分";
          points.append(unit);

          row.append(rank, name, points);
          scoreboard.append(row);
        });
      }

      function renderFriends(players) {
        const roomPlayers = new Map(players.map((player) => [player.name, player]));
        const onlineCount = friends.filter((friend) => friend.online).length;
        const palette = ["#ff6b57", "#3d9be9", "#35a777", "#f0a91b", "#9b6bd6"];
        const canInvite = !app.classList.contains("hidden")
          && socialRoom.roomOwnerName === myUsername;
        const renderInto = (container, inLobby) => {
          container.replaceChildren();
          friends.forEach((friend, index) => {
            const player = roomPlayers.get(friend.name);
            const isOnline = Boolean(friend.online);
            const friendColor = player?.color || palette[index % palette.length];

            const row = document.createElement("div");
            row.className = "friend-row";

            const avatarWrap = document.createElement("span");
            avatarWrap.className = "friend-avatar-wrap";
            const avatar = document.createElement("span");
            avatar.className = "friend-avatar";
            avatar.style.setProperty("--friend-color", friendColor);
            avatar.textContent = Array.from(friend.name)[0] || "?";
            const dot = document.createElement("span");
            dot.className = `online-dot${isOnline ? " online" : ""}`;
            avatarWrap.append(avatar, dot);

            const info = document.createElement("span");
            info.className = "friend-info";
            const name = document.createElement("span");
            name.className = "friend-name";
            name.textContent = friend.name;
            const status = document.createElement("span");
            status.className = `friend-status${isOnline ? " online" : ""}`;
            if (!isOnline) {
              status.textContent = "离线";
            } else if (friend.inGame) {
              status.textContent = "在线 · 游戏中";
            } else {
              status.textContent = "在线 · 大厅中";
            }
            info.append(name, status);

            const actions = document.createElement("span");
            actions.className = "friend-actions";
            if (canInvite) {
              const invite = document.createElement("button");
              invite.className = `friend-invite${friend.invited ? " invited" : ""}`;
              invite.type = "button";
              invite.disabled = Boolean(friend.invited);
              invite.textContent = friend.invited ? "已邀请" : "邀请";
              invite.addEventListener("click", () => {
                if (send({ type: "invite_friend", username: friend.name })) {
                  showToast(`已邀请 ${friend.name}`);
                }
              });
              actions.append(invite);
            }
            const remove = document.createElement("button");
            remove.className = "friend-remove";
            remove.type = "button";
            remove.title = "移除好友";
            remove.setAttribute("aria-label", `移除好友 ${friend.name}`);
            remove.textContent = "×";
            remove.addEventListener("click", () => removeFriend(friend.name));
            actions.append(remove);
            addModerationActions(actions, friend.name);

            row.append(avatarWrap, info, actions);
            container.append(row);
          });

          if (!friends.length) {
            const empty = document.createElement("div");
            empty.className = "friend-empty";
            empty.textContent = inLobby
              ? "还没有好友，在左侧输入用户名发送申请"
              : "还没有好友，只有同意申请后才可成为好友";
            container.append(empty);
          }
        };

        renderInto(friendList, false);
        renderInto(lobbyFriendList, true);
        friendOnlineCount.textContent = `在线 ${onlineCount}`;
        lobbyFriendOnlineCount.textContent = `在线 ${onlineCount}`;
      }

      function renderFriendRequests() {
        friendRequestList.replaceChildren();
        incomingFriendRequests.forEach((request) => {
          const row = document.createElement("div");
          row.className = "friend-request-row";
          const name = document.createElement("span");
          name.className = "friend-request-name";
          name.textContent = request.name;
          const accept = document.createElement("button");
          accept.className = "request-action";
          accept.type = "button";
          accept.textContent = "同意";
          accept.addEventListener("click", () => acceptFriendRequest(request.name));
          const reject = document.createElement("button");
          reject.className = "request-action reject";
          reject.type = "button";
          reject.textContent = "拒绝";
          reject.addEventListener("click", () => rejectFriendRequest(request.name));
          row.append(name, accept, reject);
          friendRequestList.append(row);
        });
        outgoingFriendRequests.forEach((request) => {
          const row = document.createElement("div");
          row.className = "friend-request-row";
          const name = document.createElement("span");
          name.className = "friend-request-name";
          name.textContent = `${request.name} · 等待对方同意`;
          row.append(name);
          friendRequestList.append(row);
        });
        if (!incomingFriendRequests.length && !outgoingFriendRequests.length) {
          const empty = document.createElement("div");
          empty.className = "lobby-empty";
          empty.textContent = "暂无新的好友申请";
          friendRequestList.append(empty);
        }
      }

      function renderPlayers(players) {
        currentPlayers = players;
        playersBox.replaceChildren();
        playerCount.textContent = `${players.length} 位玩家`;
        for (const player of players) {
          const row = document.createElement("div");
          row.className = "player";
          row.classList.toggle("current-drawer", player.role === "drawer");

          const avatar = document.createElement("span");
          avatar.className = "avatar";
          avatar.style.setProperty("--avatar", player.color);
          avatar.textContent = Array.from(player.name)[0] || "?";

          const name = document.createElement("span");
          name.className = "player-name";
          name.textContent = player.name;

          const identity = document.createElement("div");
          identity.className = "player-identity";
          const nameLine = document.createElement("div");
          nameLine.className = "player-name-line";
          nameLine.append(name);

          const score = document.createElement("span");
          score.className = "player-score";
          score.textContent = `${Number(player.score) || 0} 分`;
          nameLine.append(score);
          identity.append(nameLine);

          if (player.id === myId) {
            const you = document.createElement("span");
            you.className = "you";
            you.textContent = "（你）";
            name.append(you);
          }

          const role = document.createElement("span");
          role.className = `mini-role ${player.role}`;
          role.textContent = player.role === "drawer" ? "画手" : "猜手";

          row.append(avatar, identity, role);
          if (player.id !== myId) {
            const alreadyFriends = isFriend(player.name);
            const incoming = incomingFriendRequests.some((request) => request.name === player.name);
            const outgoing = outgoingFriendRequests.some((request) => request.name === player.name);
            const addButton = document.createElement("button");
            addButton.className = `friend-add${alreadyFriends || outgoing ? " added" : ""}`;
            addButton.type = "button";
            addButton.disabled = alreadyFriends || outgoing;
            addButton.title = alreadyFriends
              ? "已经是好友"
              : outgoing
                ? "好友申请等待对方同意"
                : incoming
                  ? "同意好友申请"
                  : `添加 ${player.name} 为好友`;
            addButton.setAttribute("aria-label", addButton.title);
            addButton.textContent = alreadyFriends ? "✓" : outgoing ? "…" : incoming ? "✓" : "+";
            if (!alreadyFriends && !outgoing) {
              addButton.addEventListener("click", () => {
                if (incoming) acceptFriendRequest(player.name);
                else requestFriend(player.name);
              });
            }
            row.append(addButton);
            addModerationActions(row, player.name);
          }
          playersBox.append(row);
          if (player.id === myId && player.role !== myRole) setRole(player.role);
        }
        renderScoreboard(players);
        renderFriends(players);
      }

      function scheduleReconnect() {
        if (intentionalClose || reconnecting || !myUsername || !myPassword || reconnectAttempts >= 4) {
          if (reconnectAttempts >= 4) showToast("自动重连次数已用完，请重新登录");
          return;
        }
        reconnecting = true;
        reconnectAttempts += 1;
        const delay = Math.min(1000 * reconnectAttempts, 4000);
        connection.classList.add("reconnecting");
        connectionText.textContent = `正在重连（${reconnectAttempts}/4）`;
        reconnectTimer = window.setTimeout(() => {
          reconnecting = false;
          connect(true);
        }, delay);
      }

      function connect(isReconnect = false) {
        if (socket && socket.readyState === WebSocket.OPEN) {
          if (isReconnect) sendAuth(true);
          else sendAuth(false);
          return;
        }
        if (socket && socket.readyState === WebSocket.CONNECTING) return;
        if (!isReconnect) {
          const username = usernameInput.value.trim();
          const password = passwordInput.value;
          if (username && password) {
            myUsername = username;
            myPassword = password;
          }
          intentionalClose = false;
          reconnectAttempts = 0;
        }
        joinButton.disabled = true;
        joinButton.textContent = isReconnect ? "正在恢复连接…" : "连接中…";
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        socket = new WebSocket(`${protocol}//${location.host}/ws`);

        socket.addEventListener("open", () => {
          connection.classList.remove("reconnecting");
          sendAuth(isReconnect);
        });

        socket.addEventListener("message", (event) => {
          let message;
          try { message = JSON.parse(event.data); }
          catch { return; }

          if (message.type === "lobby") {
            myUsername = message.username || myUsername;
            accountRole = message.role || accountRole || "user";
            showLobby(message);
          } else if (message.type === "profile_get" || message.type === "profile_update") {
            if (message.username) myUsername = message.username;
            profileNickname.value = message.nickname || myUsername;
            profileBio.value = message.bio || "";
            if (message.role) {
              accountRole = message.role;
              adminButton.classList.toggle("hidden", accountRole !== "admin");
            }
            if (message.type === "profile_update") {
              lobbyUser.textContent = `已登录 · ${message.nickname || myUsername}`;
              showToast("资料已更新");
            }
          } else if (message.type === "privacy_accept") {
            privacyAccepted = Boolean(message.accepted);
            if (privacyAccepted) closePanel(privacyPanel);
          } else if (message.type === "admin_report_list") {
            renderAdminReports(message.reports);
          } else if (message.type === "admin_result") {
            showToast(message.message || "管理员操作已完成");
            if (message.report) loadAdminReports();
          } else if (message.type === "social_state") {
            applySocialState(message);
          } else if (message.type === "notice") {
            showToast(message.message || "操作成功");
          } else if (message.type === "joined") {
            myId = message.clientId;
            segments = Array.isArray(message.strokes) ? message.strokes : [];
            seenIds = new Set(segments.map((segment) => segment.id));
            setRole(message.role);
            localStorage.setItem("draw-together-user", message.name);
            myUsername = message.name;
            clearAuthError();
            passwordInput.value = "";
            login.classList.add("hidden");
            lobbyView.classList.add("hidden");
            app.classList.remove("hidden");
            createRoomButton.disabled = false;
            setConnection(true);
            if (message.round) applyRound(message.round);
            if (message.gameOver) {
              showGameOver({
                ranking: message.ranking,
                roundsPlayed: message.round ? message.round.roundNumber : 0,
                message: "游戏结束！"
              });
            }
            requestAnimationFrame(resizeCanvas);
          } else if (message.type === "presence") {
            renderPlayers(Array.isArray(message.players) ? message.players : []);
          } else if (message.type === "round_started") {
            applyRound(message);
          } else if (message.type === "word") {
            if (message.roundNumber === lastRoundNumber && myRole === "drawer") {
              wordText.textContent = message.word;
              wordCard.classList.remove("hidden");
            }
          } else if (message.type === "chat") {
            appendChat(message);
          } else if (message.type === "correct_guess") {
            appendChat({ text: message.message || "有人猜对了！", system: true });
            showToast(message.message || "有人猜对了！");
          } else if (message.type === "game_over") {
            showGameOver(message);
          } else if (message.type === "game_reset") {
            hideGameOver();
            segments = [];
            seenIds.clear();
            redrawAll();
            chatLog.replaceChildren();
            appendChat({ text: "新一局开始，所有玩家分数已重置。", system: true });
          } else if (message.type === "stroke") {
            addSegment(message);
          } else if (message.type === "clear") {
            segments = [];
            seenIds.clear();
            redrawAll();
            if (message.reason === "timeout") {
              showToast("时间到，准备下一位画手");
            } else if (message.reason === "drawer-left") {
              showToast("画手已离开，正在切换下一位");
            } else if (message.reason === "correct-guess") {
              showToast("猜对了，准备下一轮");
            } else {
              showToast("画布已由画手清空");
            }
          } else if (message.type === "error") {
            showToast(message.message || "操作失败");
            if (!lobbyView.classList.contains("hidden")) {
              createRoomButton.disabled = socialRoom.roomActive && !socialRoom.roomInvited;
              createRoomButton.textContent = socialRoom.roomActive
                ? socialRoom.roomInvited ? "接受邀请并加入" : "等待邀请"
                : "创建房间";
            }
          } else if (message.type === "auth_error") {
            intentionalClose = true;
            myPassword = "";
            reconnectAttempts = 4;
            showAuthError(message.message || "登录失败");
            joinButton.disabled = false;
            setAuthButtonLabel();
            passwordInput.focus();
          }
        });

        socket.addEventListener("close", () => {
          socket = null;
          if (intentionalClose) return;
          if (!login.classList.contains("hidden")) {
            joinButton.disabled = false;
            setAuthButtonLabel();
            if (authError.classList.contains("hidden")) {
              showToast("连接失败，请确认服务仍在运行");
            }
          } else {
            setConnection(false);
            createRoomButton.disabled = true;
            showToast("与服务器的连接已断开");
            if (reconnectAttempts < 4) {
              scheduleReconnect();
            } else {
              resetToLogin("自动重连失败，请重新登录");
            }
          }
        });

        socket.addEventListener("error", () => {
          if (!login.classList.contains("hidden")) showToast("无法连接到服务器");
        });
      }

      joinForm.addEventListener("submit", (event) => {
        event.preventDefault();
        connect();
      });

      profileButton.addEventListener("click", () => {
        openPanel(profilePanel);
        send({ type: "profile_get" });
      });
      profileForm.addEventListener("submit", (event) => {
        event.preventDefault();
        if (!profileNickname.value.trim()) return;
        if (send({ type: "profile_update", nickname: profileNickname.value.trim(), bio: profileBio.value })) {
          profileButton.blur();
        }
      });
      privacyAcceptButton.addEventListener("click", () => {
        privacyAcceptButton.disabled = true;
        if (!send({ type: "privacy_accept" })) privacyAcceptButton.disabled = false;
      });
      deleteAccountButton.addEventListener("click", () => {
        if (!confirm("确认删除账号？该操作不可恢复。")) return;
        if (send({ type: "delete_account", confirm: true })) {
          intentionalClose = true;
          showToast("正在删除账号…");
        }
      });
      adminButton.addEventListener("click", () => {
        openPanel(adminPanel);
        loadAdminReports();
      });
      adminLoadButton.addEventListener("click", loadAdminReports);
      document.querySelectorAll("[data-close-panel]").forEach((button) => {
        button.addEventListener("click", () => closePanel($(button.dataset.closePanel)));
      });

      loginTab.addEventListener("click", () => setAuthMode("login"));
      registerTab.addEventListener("click", () => setAuthMode("register"));

      createRoomButton.addEventListener("click", () => {
        createRoomButton.disabled = true;
        createRoomButton.textContent = "正在进入…";
        const action = socialRoom.roomActive ? "join_room" : "create_room";
        if (!send({ type: action })) {
          createRoomButton.disabled = socialRoom.roomActive && !socialRoom.roomInvited;
          createRoomButton.textContent = socialRoom.roomActive
            ? socialRoom.roomInvited ? "接受邀请并加入" : "等待邀请"
            : "创建房间";
        }
      });

      friendRequestForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const username = friendUsername.value.trim();
        if (!username) return;
        requestFriend(username);
        friendUsername.value = "";
      });

      guessForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const text = guessInput.value;
        if (!text.trim()) return;
        if (send({ type: "guess", text })) {
          guessInput.value = "";
          guessInput.focus({ preventScroll: true });
        }
      });

      playAgainButton.addEventListener("click", () => {
        playAgainButton.disabled = true;
        if (!send({ type: "play_again" })) playAgainButton.disabled = false;
      });

      usernameInput.value = localStorage.getItem("draw-together-user") || "";
      setAuthMode("login");
      window.addEventListener("resize", () => {
        cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(resizeCanvas);
      });
      new ResizeObserver(() => {
        if (!app.classList.contains("hidden")) {
          cancelAnimationFrame(resizeFrame);
          resizeFrame = requestAnimationFrame(resizeCanvas);
        }
      }).observe(canvasWrap);
    })();
  </script>
</body>
</html>
"""


PRIVACY_PAGE = """<!doctype html><meta charset='utf-8'><title>隐私政策 · 一起画</title><h1>隐私政策</h1><p>一起画保存账号登录信息、昵称、好友关系和必要的举报处理记录，用于提供多人游戏、好友功能和社区安全。</p><p>聊天内容仅在房间实时传输；举报时会保存用户提交的原因和必要的内容快照，用于处理违规行为。</p><p>你可以在应用内删除账号。删除后会清理账号、好友关系、好友申请和屏蔽关系；已提交的举报会保留去标识化的安全审计信息。</p><p>隐私政策版本：%s</p>""" % PRIVACY_VERSION
TERMS_PAGE = """<!doctype html><meta charset='utf-8'><title>用户协议 · 一起画</title><h1>用户协议</h1><p>请遵守法律法规和友善交流规则，不得发布违法、骚扰、欺诈或侵犯他人权益的内容。</p><p>用户可以举报或屏蔽其他用户。管理员可以根据举报结果采取禁言、封禁等措施。</p><p>继续使用一起画即表示你同意本协议。</p>"""
ACCOUNT_DELETION_PAGE = """<!doctype html><meta charset='utf-8'><title>账号删除 · 一起画</title><h1>删除账号</h1><p>登录后打开“删除账号”，确认后账号会立即删除，好友关系、申请和屏蔽关系会同步清理。</p><p>举报安全审计记录可能以去标识化方式保留。</p>"""


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n服务已停止。")
