# Release OffLook to PyPI

`pyproject.toml` is the source of truth for the version. Release a commit merged
into `main`, tagged `v<version>`. Never move an existing release tag or reuse a
version to publish different files.

## First release: account and repository setup

- Check the [PyPI project](https://pypi.org/project/offlook/) and the [TestPyPI
  project](https://test.pypi.org/project/offlook/) independently. A missing page
  does not reserve the name. If either project already exists, confirm that you
  control it before using the name.
- Check the project and documentation links in `pyproject.toml` and
  `README.pypi.md` in a signed-out browser. If the repository is private, decide
  whether to make the public release documentation available separately or to
  make the repository public before publishing. Do not change visibility without
  first reviewing what the repository and its history will expose.
- In GitHub **Settings > Environments**, create `testpypi` and `pypi`. Restrict
  deployment to release tags (`v*`, as a **tag** rule). Set required reviewers on
  `pypi` and verify that the repository plan supports that protection. Without
  required reviewers, `publish=true` can continue to PyPI automatically as soon
  as TestPyPI verification passes; only enable it when ready for both uploads.
- On each index, sign in and configure a Trusted Publisher. For a new project,
  use the account's **Publishing** page to add a [pending publisher]; for a
  project you already own, use the project's **Publishing** page. TestPyPI uses
  its own account and publisher configuration. No API token or GitHub secret is
  needed for this workflow.

| Publisher field | TestPyPI | PyPI |
| --- | --- | --- |
| Project name | `offlook` | `offlook` |
| Repository owner | `EvanLuo0103` | `EvanLuo0103` |
| Repository name | `OffLook` | `OffLook` |
| Workflow name | `release.yml` | `release.yml` |
| Environment name | `testpypi` | `pypi` |

[pending publisher]: https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/

## Rehearse without uploading

Use Windows x64 with Python 3.11-3.15 and Tcl/Tk. From the repository root,
build into a new directory so stale artifacts are never picked up:

```powershell
py -m venv .venv
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install build twine
$dist = Join-Path $PWD "dist/rehearsal-$(Get-Date -Format yyyyMMdd-HHmmss)"
& $python -m build --outdir $dist
& $python -m twine check --strict "$dist/*"
& $python -m qa.release_artifacts $dist
```

Once the candidate is on GitHub `main`, run **Release OffLook** with `publish`
left unchecked. The dry run builds and inspects the wheel and sdist, installs
the wheel on Windows x64 with every supported Python version, installs the
sdist with the `office` extra, and builds the Windows installer. Review the
`python-dist` and `windows-installer` artifacts. Smoke-test the unsigned
installer and the GUI (launch, Explorer preview shortcut, and uninstall) on a
clean Windows machine before publication. This check is separate from the
automated CLI and renderer smoke tests.

## Publish when approved

1. After the dry run passes, tag the reviewed `main` commit and push only that
   tag. For `0.4.3`, from an up-to-date `main`:

   ```powershell
   git tag -a v0.4.3 -m "OffLook 0.4.3"
   git push origin refs/tags/v0.4.3
   gh workflow run release.yml --repo EvanLuo0103/OffLook --ref v0.4.3 -f publish=true
   ```

2. Wait for the TestPyPI upload and verification. Open that version's page
   and check the description, links, version and files. The workflow compares
   both files' SHA-256 hashes and installs the TestPyPI wheel using only PyPI
   for its dependencies.
3. Approve the `pypi` environment in the **same run**. The workflow promotes
   the same artifacts, verifies the files on PyPI, then publishes the Windows
   installer and its checksum to GitHub Releases.
4. Confirm the public PyPI page and GitHub release. In a new Windows venv, run
   `python -m pip install offlook==0.4.3`, `python -m pip check`,
   `ol --version`, and `python -m offlook --help`.

If an upload fails after artifacts have reached either index, rerun the failed
jobs in the same workflow run if its artifacts still exist. Do not start a new
build for that version: zip/tar timestamps and dependency changes can change
the bytes even at the same commit. If the verified artifacts cannot be reused,
bump the version and create a new tag.
