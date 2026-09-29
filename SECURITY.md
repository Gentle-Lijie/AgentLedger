# AgentLedger security policy

## Reporting a vulnerability

Private vulnerability reporting is enabled. [Report a vulnerability privately](https://github.com/Gentle-Lijie/AgentLedger/security/advisories/new) to the maintainer, Lijie Zhou (GitHub: Gentle-Lijie). Do not disclose exploit details, credentials, raw transcripts, or private code in public issues. No private email address is designated by this policy.

Include the affected version, OS, Python/Git versions, relevant configuration, impact, and a reproduction using synthetic data. Only the latest released version is maintained for fixes during the initial 0.x series. Until the first release, identify the checkout revision. There is no guaranteed response time.

## Session archives and disclosure

AgentLedger reads local records and writes unencrypted bundles into Git commits. Prompts, replies, code, tool output, local paths, and credentials may be present. The manifest includes the absolute repository path. Checksums do not encrypt or redact content.

Repository matching is heuristic. A matching text file can contain material from multiple projects. SQLite exports are best-effort and can omit related records or include rows that mention the repository. Use a controlled export directory when you need to review exactly what is eligible for capture.

Review the source and permissions for sharing its contents before enabling archiving in a public or shared repository. Do not use real transcripts in this project's tests, examples, release assets, or reports. Keep agent credentials in their credential store and publishing tokens in GitHub Actions secrets.

Uninstalling does not remove bundles from Git history. If credentials are committed, revoke or rotate them first, then coordinate removal from history and published copies. Deleting a file in a later commit does not erase earlier copies.

## Hook behavior

The post-commit hook amends the just-created commit and changes its SHA. A temporary index keeps unrelated staged changes out; internal hooks are suppressed. Existing hooks are executable code with their normal privileges. Signed commits need a working signing key for the amend; an archive failure leaves the original commit intact.

The legacy command/module shims and internal storage/configuration names remain available for earlier installations. See [README.md](README.md) for their names.

## Release credentials

The publisher uses `PYPI_API_TOKEN`, with `PYPI_TOKEN` as fallback, from the target repository or its `pypi` environment. Never place token values in files, command examples, logs, issue text, or release assets. A secret configured on another repository is not automatically available here; the token must permit the new `agentledger` PyPI project.

See [release setup](docs/releasing.md) for configuration and the tag-triggered publication gate.
