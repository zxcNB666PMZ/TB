# -*- coding: utf-8 -*-
"""把 users 表里的明文密码一次性转成 bcrypt 哈希（幂等，可重复执行）"""

import sys

import db


def main():
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT username, password, role FROM users ORDER BY username")
        rows = cur.fetchall()

    if not rows:
        print("users 表里没有用户")
        return 1

    changed = 0
    for username, password, role in rows:
        if db._is_hash(password):
            print(f"  [跳过] {username}  已是哈希")
            continue
        db.set_password(username, password)
        changed += 1
        print(f"  [转换] {username}  明文 → bcrypt 哈希   (角色: {role})")

    print(f"\n完成：转换 {changed} 个用户，跳过 {len(rows) - changed} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())