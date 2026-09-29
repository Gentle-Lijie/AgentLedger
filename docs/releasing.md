# Releasing AgentLedger

Maintainer: Lijie Zhou · Repository: [Gentle-Lijie/AgentLedger](https://github.com/Gentle-Lijie/AgentLedger).

The first planned PyPI release is `agentledger` version `0.1.0`. Creating the public repository and pushing source does **not** publish the package. No release tag should be pushed until the release prerequisites are complete.

This document defines the CI contract. Before tagging, confirm the workflows and packaging configuration implement it; documentation alone does not enable publishing.

## CI contract

| Trigger | Required work | Publication |
| --- | --- | --- |
| Branch push or pull request | Build a wheel and test it installed on macOS, Linux, Windows × Python 3.10, 3.14. | None. |
| Push of a tag matching `v*` | Run `.github/workflows/release.yml`: validate exact version tag, build wheel/sdist, validate artifacts, pass the same installed-wheel matrix. | Publish to PyPI, then create a GitHub Release with wheel and sdist assets. |

Reject tags that are not exactly `v` followed by `__version__` from `src/agentledger/__init__.py`. Initially the valid tag is `v0.1.0`. Package metadata must derive its version from that file; both distribution versions must match. Arbitrary tags matching the broad `v*` trigger must fail before any upload.

Build artifacts once for the tagged revision and pass the same artifacts through checks, tests, publishing, and release attachments. Validate metadata with `twine check --strict`, inspect contents for required metadata/license and accidental private files, and check expected package name/version. A failed check or matrix job blocks publication. Confirm the sdist's packaged source can build a wheel as part of artifact validation.

Wheel tests run from the checkout with the wheel installed in a clean environment, `PYTHONPATH` unset, and `AGENT_SESSION_TEST_INSTALLED=1`. The `src/` layout keeps checkout packages off the default import path; this flag makes the hook test helper remove `PYTHONPATH` from subprocess environments so hooks also use the installed wheel. Confirm that `agentledger.__file__` points into `site-packages`. Keep tests in the checkout so release-metadata tests can access `scripts/check_release.py`. See [CONTRIBUTING.md](../CONTRIBUTING.md) for the local wheel-check commands.

Use `pypa/gh-action-pypi-publish` on a Linux runner with API-token authentication. Prefer `PYPI_API_TOKEN`; fall back to `PYPI_TOKEN` only if the former is absent. Fail clearly if both are missing. The intended action password input is:

~~~yaml
password: ${{ secrets.PYPI_API_TOKEN || secrets.PYPI_TOKEN }}
~~~

Select `environment: pypi` in the publishing job if using that environment's secrets. Create the GitHub Release only after successful PyPI publication, attaching the validated wheel and source archive. Release creation needs `contents: write`; tests need no publishing secrets. Branch pushes and PRs must never publish.

## First-release prerequisites

1. Confirm the checkout remote targets `https://github.com/Gentle-Lijie/AgentLedger.git`. Source pushes are permitted preparation; the tag is the separate publication trigger.
2. Confirm the PyPI name `agentledger` is available or owned by the maintainer.
3. Include the actual license file in source and artifacts, and set package author to Lijie Zhou. The intended license is MIT; a metadata label alone is not a license file.
4. Confirm canonical package, CLI, and module names are `agentledger`, with version derived only from `src/agentledger/__init__.py`. Preserve legacy CLI/module shims and internal names described in [README.md](../README.md).
5. Implement/review the CI contract and confirm branch CI passes all six installed-wheel jobs.
6. Configure the target repository's publishing secret or its `pypi` environment. Enable Actions and review deployment rules for version tags.
7. Private vulnerability reporting is enabled; confirm the [private reporting link](https://github.com/Gentle-Lijie/AgentLedger/security/advisories/new) remains available. Review [SECURITY.md](../SECURITY.md), [README.md](../README.md), and [CHANGELOG.md](../CHANGELOG.md); set the actual release date when ready.
8. Review tracked files and distribution contents for credentials, private transcripts, local bundles, and unrelated build output.

## Configure the PyPI token

In this repository's GitHub Settings, use either:

- **Secrets and variables → Actions**: add `PYPI_API_TOKEN` (or fallback `PYPI_TOKEN`) as a repository secret.
- **Environments → pypi → Environment secrets**: add the same name. The publishing job must select `environment: pypi` to access it.

Repository secrets configured elsewhere cannot be automatically reused or retrieved in plaintext. A token configured “somewhere on GitHub” is insufficient. Organization secrets require an access policy permitting this target. See [GitHub's secret documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).

The token must authorize `agentledger`. A token scoped to another package cannot create or publish this project; the first upload requires a token permitted to create it. After creation, prefer a project-scoped token. Never put token values in commits. See the [PyPA publishing action](https://github.com/pypa/gh-action-pypi-publish) and [Python packaging guide](https://packaging.python.org/en/latest/tutorials/packaging-projects/).

In an authenticated GitHub CLI checkout with the correct remote, inspect secret names:

~~~sh
gh secret list
gh secret list --env pypi
~~~

Presence of a name does not establish the token's validity or PyPI scope.

## Prepare a release locally

These are maintainer instructions, not commands already executed:

~~~sh
python -m pip install -e .
python -m pip install --upgrade build twine
python -c "from agentledger import __version__; print(__version__)"
python -m unittest discover -s tests -v
python -m build --outdir dist/0.1.0
python -m twine check --strict dist/0.1.0/*
python scripts/check_release.py --tag v0.1.0 --dist-dir dist/0.1.0
git diff --check
git status --short
~~~

Start with an empty per-version output directory. Inspect both distributions and check the installed wheel using [CONTRIBUTING.md](../CONTRIBUTING.md). Source tests do not replace the release wheel matrix.

Commit reviewed release preparation, including version/changelog, and push to the default branch. Wait for branch CI to pass. When you intend to publish:

~~~sh
git remote -v
git tag -a v0.1.0 -m "Release 0.1.0"
git push origin v0.1.0
~~~

**Pushing the tag triggers publishing.** Do not run those tag commands until artifacts, metadata, secrets, and workflows are ready. Later releases update the single version source and changelog, then use the new exact version.

## Confirm publication and recover failures

Follow the tag run in Actions. After success, verify PyPI and the GitHub Release, including attached distributions. In a fresh virtual environment:

~~~sh
python -m pip install --index-url https://pypi.org/simple agentledger==0.1.0
python -c "from agentledger import __version__; print(__version__)"
agentledger --help
~~~

The PyPI installation works only after successful first publication.

For a failure before upload, resolve its cause. Configuration-only fixes may allow rerunning the tagged revision; code fixes require a newly reviewed revision and version. Avoid moving public tags.

If PyPI publication succeeds but release creation fails, recover the GitHub Release using the already-published artifacts; do not blindly retry upload. For partial uploads, inspect PyPI and recover only missing original artifacts. PyPI does not allow replacing an uploaded distribution with changed content for the same version. Publish corrections under a new version.
