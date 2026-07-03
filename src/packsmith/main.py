# Copyright (c) 2026 Frank1o3
# SPDX-License-Identifier: MIT

import typer

from packsmith.cli.add import add
from packsmith.cli.downloader import download
from packsmith.cli.export import export
from packsmith.cli.injector import inject
from packsmith.cli.resolve import resolve
from packsmith.cli.setup import setup
from packsmith.cli.ui import print_banner

app = typer.Typer()


app.command(name="init", help="Initialize a new modpack.")(setup)
app.command(name="add", help="Adds a mod, resourcepack or shader to you'r modpack")(add)
app.command(
    name="inject",
    help="Inject an external file into the modpack from a direct download URL.",
)(inject)
app.command(name="resolve", help="Resolve all dependencies for the current modpack.")(
    resolve
)
app.command(
    name="download", help="Download all resolved dependencies for the current modpack."
)(download)
app.command(name="export", help="Export a modpack for distribution.")(export)


@app.callback(invoke_without_command=True)
def callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        print_banner()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
