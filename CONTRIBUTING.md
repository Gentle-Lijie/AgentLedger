# Contributing to Agent Session Commit

Agent Session Commit is maintained by Lijie Zhou (GitHub: Gentle-Lijie). Use [Issues](https://github.com/Gentle-Lijie/AgentLedger/issues) and [Pull requests](https://github.com/Gentle-Lijie/AgentLedger/pulls) for bugs, proposals, and contributions. For security concerns, follow [SECURITY.md](SECURITY.md).

## Development setup

Use Python 3.10 or newer and Git. On Windows, use Git for Windows so integration tests can execute shell hooks.

~~~sh
git clone https://github.com/Gentle-Lijie/AgentLedger.git
cd AgentLedger
python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows PowerShell instead:
# .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e '.[pre-commit]'
python -m unittest discover -s tests -v
~~~

This editable source install is for development. Release users should install `agent-session-commit[pre-commit]==0.1.4` from PyPI in a persistent virtual environment and run `agent-session-commit install --pre-commit` in their target repository; native `install` remains supported. See [README.md](README.md#install).

Tests create temporary repositories with synthetic transcripts. Keep actual prompts, tokens, and private archives out of fixtures, issues, and pull requests.

## Change guidelines

- Preserve user staging, working files, author information, commit messages, and parents when adding archives.
- Keep internal amend operations from triggering recursion or duplicate external hooks.
- Handle paths using platform-aware APIs. Document environment overrides and CLI versus IDE differences for new adapters.
- Treat session formats as version-dependent. Document discovery assumptions and incomplete capture.
- Add focused regression coverage for changed archive or Git behavior, using disposable repositories.
- Update the [changelog](CHANGELOG.md) and relevant usage documentation.
- Preserve the legacy CLI/module shims and internal configuration/state names described in [README.md](README.md) unless a deliberate migration is documented.

In a pull request, explain the change, source format, commands used to check it, and known limitations. Include sanitized reproduction steps for bugs.

## Check distribution artifacts

~~~sh
python -m pip install --upgrade build twine
python -m build
python -m twine check --strict dist/*
~~~

Start with a clean output directory so stale distributions cannot be uploaded. Check contents for required metadata/license, unexpected files, credentials, and private sessions. Both the wheel and sdist must report the intended version.

The CI contract tests an **installed wheel**, not an editable source install, on macOS, Linux, and Windows with Python 3.10 and 3.14. The release must pass the same six combinations before publishing; [releasing.md](docs/releasing.md) defines that contract.

For a local wheel check, use a fresh virtual environment with only the built wheel and its dependencies installed. Run tests from the checkout root so release-metadata tests can access `scripts/check_release.py`. The `src/` layout keeps source packages off the default import path. Unset `PYTHONPATH` and set `AGENT_SESSION_TEST_INSTALLED=1`: the hook test helper then removes `PYTHONPATH` from subprocess environments instead of pointing them at checkout source. CI uses this same gate so the installed wheel is authoritative.

For example, from the checkout root in Bash, create a new environment that has never had an editable install:

~~~sh
python -m venv .venv-wheel
# macOS / Linux:
source .venv-wheel/bin/activate
# Windows Git Bash instead:
# source .venv-wheel/Scripts/activate
unset PYTHONPATH
python -m pip install dist/*.whl
export AGENT_SESSION_TEST_INSTALLED=1
python -c "import agent_session_commit; print(agent_session_commit.__file__)"
python -m unittest discover -s tests -v
~~~

The printed `agent_session_commit.__file__` must be inside the fresh environment's `site-packages`, not the checkout's `src/`. Keep the checkout's tests and scripts in place. Test fixtures should never require a live agent account. When returning to editable source development, unset `AGENT_SESSION_TEST_INSTALLED` and activate your development environment again.

## Versions and publishing

`__version__` in `src/agent_session_commit/__init__.py` is the single version source for builds. It currently reports `0.1.4` in the checkout, matching the current stable PyPI release. Package metadata must derive its version from the source file. The canonical distribution and CLI are `agent-session-commit`; the Python module is `agent_session_commit`. Preserve the `agentledger` CLI/module shims and pre-commit hook alias. Do not maintain a second manual version in metadata or compatibility shims.

The `v0.1.0` upload attempt used `agentledger` and failed PyPI's project-name check before any distribution files were uploaded. Keep that public tag unchanged; `0.1.1` restored the selected name and was published on PyPI.

Maintainers follow [docs/releasing.md](docs/releasing.md). Do not create or push a release tag as part of an ordinary contribution: pushing `v<version>` triggers publication.
