"""Comandos de manutenção local usados pelos scripts Windows."""

from __future__ import annotations

import argparse
from pathlib import Path

from prospector.config import AppPaths
from prospector.database.backup import create_backup, restore_backup
from prospector.database.engine import Database


def main() -> None:
    parser = argparse.ArgumentParser(description="Manutenção do Prospector IA")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup", help="Cria backup local do banco")
    restore = commands.add_parser("restore", help="Restaura backup local com confirmação explícita")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--confirm", action="store_true", help="Confirma a substituição do banco")
    arguments = parser.parse_args()
    database = Database(AppPaths.from_environment())
    database.initialize()
    if arguments.command == "backup":
        print(create_backup(database))
    else:
        print(restore_backup(database, arguments.backup, arguments.confirm))


if __name__ == "__main__":
    main()
