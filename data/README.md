# data/

| Folder         | Committed? | Contents                                                        |
|----------------|------------|-----------------------------------------------------------------|
| `sample/`      | yes        | Synthetic exports from `taxistats sample` — no real data        |
| `raw/` (yours) | **never**  | Put your real Yandex Go export files here                       |

Everything in `data/` except `sample/` and this README is git-ignored, and so
are folders named like `exports/`, `private/` or `*Yandex*/` anywhere in the
repo. The opt-in pre-commit hook (`git config core.hooksPath .githooks`)
also rejects data files outside `data/sample/`, even when force-added.

Run on real data:

```bash
taxistats run data/raw --out output
```

`output/` is git-ignored too: the dashboard contains driver names and plates.
Add `--anonymise` if you want a version you can share.
