# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT


import typer

from packsmith.cli.add import add
from packsmith.cli.setup import setup
from packsmith.cli.ui import console, print_banner

app = typer.Typer()


app.command(name="init", help="Initialize a new modpack.")(setup)
app.command(help="Adds a mod, resourcepack or shader to you'r modpack")(add)


@app.callback(invoke_without_command=True)
def callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        print_banner()
        console.print("[dim]Use --help to see available commands[/dim]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
