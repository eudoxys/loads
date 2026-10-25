# Contributing to loads

Thank you for your interest in contributing to `loads`, part of the
[Eudoxys](https://www.eudoxys.com/) family of packages. This guide explains
how to report problems, propose changes, and submit pull requests.

Read the [README](README.md) for what the package does, and the
[documentation](https://www.eudoxys.com/loads) for how to use it.
Maintainers and AI assistants should also read [CLAUDE.md](CLAUDE.md)
and [MANIFEST.md](MANIFEST.md).

## Code of conduct

Be respectful and constructive. Maintainers may remove comments, issues,
or pull requests that are abusive or off topic.

## New contributor guide

To get an overview of the project, read the README and the package
documentation. These GitHub guides may help:

- [Finding ways to contribute to open source on GitHub](https://docs.github.com/en/get-started/exploring-projects-on-github/finding-ways-to-contribute-to-open-source-on-github)
- [Set up Git](https://docs.github.com/en/get-started/git-basics/set-up-git)
- [GitHub flow](https://docs.github.com/en/get-started/using-github/github-flow)
- [Collaborating with pull requests](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests)

## Issues

### Create a new issue

If you find a problem or want a change, first
[search the existing issues](https://github.com/eudoxys/loads/issues).
If no issue covers it, open a new one. Include:

- what you did (command or code, with the package version from
  `pip show loads`);
- what you expected and what happened instead (full error output);
- for install problems, your Python and `pip` versions.

### Approved issues

An issue is **approved** when a human owner or maintainer of this repository
adds the `approved` label to it. Approval means the maintainers agree the
change is wanted and how it should be done. Discuss the approach in the
issue before writing code; ask there if anything is unclear.

Browse [approved open issues](https://github.com/eudoxys/loads/issues?q=is%3Aissue+is%3Aopen+label%3Aapproved)
to find something to work on, and comment on the issue to say you are
taking it.

## Pull requests

> [!IMPORTANT]
> **Pull requests from new contributors must address an open issue that a
> human owner has approved.** A pull request from a contributor with no
> previously merged pull request in this repository is automatically closed
> with the comment "PR does not address an approved open issue." unless its
> description links an open issue carrying the `approved` label added by an
> owner or maintainer. Link the issue in the description with a closing
> keyword, e.g. `Fixes #123`.
>
> If your pull request was closed this way, open (or find) an issue, wait
> for it to be approved, then open a new pull request that links it.

### Make changes

1. Fork the repository and create a branch from `main`.
2. Set up a development environment:

       python3 -m venv .venv
       . .venv/bin/activate
       pip install --upgrade pip
       pip install -e . pytest

3. Make your changes. Follow the conventions in [CLAUDE.md](CLAUDE.md);
   match the existing code style and don't reformat code you aren't changing.
4. Add or update tests in `loads/_test/` and run them:

       pytest

5. If you change a public class, function, argument, or output, update its
   docstring and example output, the package docstring, and the README.
   Check the documentation builds with `make docs`.
6. If you add, move, or delete files, update [MANIFEST.md](MANIFEST.md) and
   run `python .github/check_manifest.py`.
7. Don't commit caches, downloaded data, or generated output. Changes to
   curated data must include the script that produces them and an updated
   data README.

### Open a pull request

- Keep each pull request to one concern.
- Give it a descriptive title, and link the approved issue in the
  description (`Fixes #123`).
- Describe what changed, why, and how you tested it, including any slow
  or networked tests you ran.
- Enable [Allow edits from maintainers](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/allowing-changes-to-a-pull-request-branch-created-from-a-fork)
  so maintainers can make small fixes.
- Make sure the Validation check passes.

### Review

A maintainer will review your pull request and may ask questions or request
changes. Use suggested changes or push new commits to your branch, and mark
conversations resolved as you address them. If the branch falls behind
`main`, rebase or merge `main` into it and resolve any conflicts.

### Your PR is merged

Congratulations, and thank you. Once merged, your change is installable
from `main` with `epm upgrade loads` or
`pip install git+https://github.com/eudoxys/loads`, and appears in the next
tagged release.

## License

By contributing, you agree that your contributions are licensed under the
repository's [LICENSE](LICENSE).
