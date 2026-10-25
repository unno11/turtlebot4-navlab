#!/usr/bin/env python3
"""Manage the one-line Ogre2 sensor renderer fix for TurtleBot4/Create3.

Usage:
    python3 scripts/manage_ogre2.py status
    sudo python3 scripts/manage_ogre2.py apply
    sudo python3 scripts/manage_ogre2.py revert

Runs only against the known ROS 2 package xacro. Does not alter other settings.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile

TARGET = Path('/opt/ros/jazzy/share/irobot_create_description/urdf/create3.urdf.xacro')
BACKUP = TARGET.with_name(TARGET.name + '.navlab-ogre1.bak')
OLD = '<render_engine>ogre</render_engine>'
NEW = '<render_engine>ogre2</render_engine>'


def load():
    if not TARGET.is_file():
        raise RuntimeError(f'文件不存在: {TARGET}。先确认 ros-jazzy-irobot-create-description 已安装。')
    s = TARGET.read_text(encoding='utf-8')
    old_n, new_n = s.count(OLD), s.count(NEW)
    if (old_n, new_n) not in ((1, 0), (0, 1)):
        raise RuntimeError(f'目标文件状态不符合预期：ogre={old_n}, ogre2={new_n}；拒绝自动修改。')
    return s, old_n == 1


def write_atomic(content: str):
    info = TARGET.stat()
    tmp = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=TARGET.parent,
                                         prefix='.navlab-tmp-', delete=False) as f:
            f.write(content)
            tmp = Path(f.name)
        os.chmod(tmp, info.st_mode)
        os.chown(tmp, info.st_uid, info.st_gid)
        os.replace(tmp, TARGET)
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()


def main():
    parser = argparse.ArgumentParser(description='TurtleBot 4 Ogre2 渲染配置管理')
    parser.add_argument('action', choices=['status', 'apply', 'revert'])
    args = parser.parse_args()
    try:
        s, is_old = load()
        print(f'目标文件: {TARGET}')
        if args.action == 'status':
            print('当前渲染器: ' + ('ogre（未应用补丁）' if is_old else 'ogre2（已应用补丁）'))
            print('原始文件备份: ' + (str(BACKUP) if BACKUP.is_file() else '未找到（可能是此前手动修改）'))
            return 0
        if os.geteuid() != 0:
            raise RuntimeError('修改系统文件需要管理员权限，请用 sudo python3 scripts/manage_ogre2.py ' + args.action)
        if args.action == 'apply':
            if not is_old:
                print('已是 ogre2：无需重复修改。')
                return 0
            if not BACKUP.exists():
                shutil.copy2(TARGET, BACKUP)
                print(f'已保存原始备份: {BACKUP}')
            write_atomic(s.replace(OLD, NEW, 1))
            print('成功：已将唯一的 <render_engine>ogre</render_engine> 改成 ogre2。请重启 Gazebo。')
            return 0
        if is_old:
            print('已经是 ogre：无需回滚。')
            return 0
        if BACKUP.is_file():
            backup = BACKUP.read_text(encoding='utf-8')
            if backup.replace(OLD, NEW, 1) != s or backup.count(OLD) != 1:
                raise RuntimeError('备份与当前文件不只相差 Ogre 行，拒绝覆盖；请手动检查。')
            write_atomic(backup)
            print('成功：已从受检备份恢复 ogre。请重启 Gazebo。')
        else:
            # Older manual patches may not have created the managed backup.
            write_atomic(s.replace(NEW, OLD, 1))
            print('成功：已将唯一的 ogre2 行改回 ogre；由于是历史手动修改，未找到本工具的备份。')
        return 0
    except (RuntimeError, PermissionError, OSError, UnicodeError) as exc:
        print(f'错误：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
