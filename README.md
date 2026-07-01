# Packsmith

Packsmith is a CLI tool for creating and managing Minecraft modpacks. It is designed to help you initialize a pack, add mods or other content, resolve dependencies from Modrinth, download the resolved files, and export a distributable modpack archive.

This project is a remake of [ModForge-CLI](https://github.com/Frank1o3/ModForge-CLI), with a focus on a cleaner codebase and a more direct workflow for modern modpack creation.

## What Packsmith does

Packsmith helps you:

- create a new modpack structure with the expected folders
- add mods, resourcepacks, and shaders to a pack manifest
- resolve Modrinth dependencies into a lockfile
- download the resolved files into the correct directories
- export a modpack as an `.mrpack`-style archive for distribution

## Installation

You can install the project locally with:

```bash
pip install -e .
```

Or with `uv`:

```bash
uv sync
```

## Basic workflow

1. Create a new pack:

```bash
packsmith init <pack-name> <game-version> <loader> <loader-version>
```

2. Add content to the pack:

```bash
packsmith add <name> mod
```

You can also use other project types such as `resourcepack` or `shader`.

3. Resolve dependencies:

```bash
packsmith resolve
```

4. Download the resolved files:

```bash
packsmith download
```

5. Export the pack:

```bash
packsmith export --client
```

or

```bash
packsmith export --server
```

by default it will export the pack with both server and client stuff

## Project structure

When you initialize a pack, Packsmith creates a basic folder layout similar to this:

```text
<pack-name>/
  meta.json
  lock.toml
  mods/
  overrides/
    config/
    resourcepacks/
    shaderpacks/
```

## Notes

Packsmith is still being developed, and some features are still evolving. The current focus is on building a reliable workflow for modpack creation, dependency resolution, and export.
