# Contributing

Original contributions are provided under GPL-3.0-or-later. Preserve upstream
notices and record modifications of OFFBEAT-derived examples. Read the relevant
Skill instructions before changing runtime behavior. Keep source templates
read-only and execute studies in independent workspaces.

Validate this distributed source with Python 3.12 and Bash:

```bash
python3 examples/run.py --check
python3 rag/build_index.py --check
bash -n scripts/prepare-agent.sh scripts/resolve-node.sh scripts/start-dsh.sh
python3 scripts/build-plugin.py --snapshot --output-dir /outside/source/releases
```

With dependencies configured, use `bash scripts/start-dsh.sh --check headless`, then run
the relevant example in a fresh workspace. Example file changes require
updating examples/manifest.json before building. Preserve failure records;
host exits and file-existence checks are not proof of physical validity.
Never commit local configuration, API keys, solver outputs or host histories.
The source packager uses an explicit allowlist; it does not include unit tests.
