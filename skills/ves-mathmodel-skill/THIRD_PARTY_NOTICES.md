# Third-party notices

The original code, documentation, and LaTeX assembly templates in this repository are available under the root [MIT License](./LICENSE).

## Fork provenance (ves-mathmodel-skill)

This skill is a renamed, VES-integrated fork of
[`handsomeZR-netizen/mathmodel-skill`](https://github.com/handsomeZR-netizen/mathmodel-skill),
pinned at commit `d3941e14d8693fb4a79948e59afff3098734127e` (`d3941e14`),
licensed under MIT. The upstream license and third-party notices below remain
in force for the reused portions.

Changes made in this fork:
- renamed the skill to `ves-mathmodel-skill` (SKILL.md frontmatter, agents/openai.yaml);
- removed plugin shim, AGENTS.md, README.md, `.codex-plugin`, state, and the
  paper-maintenance corpus/scripts;
- added `references/ves_regression.md` and `scripts/run_ves_regression.py` as a
  thin VES host-verification adapter (public `ves_modeling.regression` API only);
- added the VES verification contract to Stage 2/3/5/8/9 references and bumped
  the shared decision-log schema to v3.2;
- kept the LaTeX templates and render pipeline.

There is no `v6.1` tag in this fork; version numbers refer only to this
repository's own decision-log schema.

## CUMCM template provenance

The CUMCM electronic-paper template at `templates/latex/cumcm/main.tex` was independently written for this repository from the public competition-format requirements. It does not copy or redistribute the source code, documentation, examples, or binary assets of `latexstudio/CUMCMThesis`; those files are not included in this release.

The template is an assembly aid, not an official CUMCM template or an endorsement by the contest organizer. The current official rules always take precedence.

## Runtime dependencies

Tools and libraries such as Python, Pandoc, TeX Live, MiKTeX, XeLaTeX, pdfLaTeX, CTeX, Fandol, and the Python packages listed in the requirements files are installed separately by the user. They are not vendored by this repository and remain subject to their own licenses.

## External research material

Competition rules, linked papers, datasets, websites, trademarks, and other external sources are not relicensed by this repository's MIT License. Links, provenance notes, and derived descriptive statistics do not transfer ownership or redistribution rights. Users remain responsible for checking the terms that apply to any material they download or submit.
