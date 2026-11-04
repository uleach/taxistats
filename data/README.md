# data/

| Folder                     | Committed? | Contents                                                   |
|----------------------------|------------|------------------------------------------------------------|
| `sample/2024-06-30/`       | yes        | Synthetic export #1: the nine files of a Yandex Go export  |
| `sample/2025-10-31/`       | yes        | Synthetic export #2: full history again, plus later rides  |
| `raw/` (yours)             | **never**  | Your real export folder(s)                                 |

Only `ridehistory.json` is analysed. The other eight files (`cardstorage`,
`coupons`, `routehistory`, `shared-payments`, `support_chats`, `user_phones`,
`userplaces`, `users`) are generated so the sample looks like a real export,
and the loader never opens them.

## Protection

- **`.gitignore`:** all nine export file names are ignored *anywhere* in the
  repository except `data/sample/`, and everything in `data/` other than
  `sample/` is ignored too.
- **Pre-commit hook:** with `git config core.hooksPath .githooks`, the hook
  also rejects force-added data files, unexpected files in `data/sample/`,
  and sample files containing URLs outside `.example.invalid`.

## Running on real data

```bash
taxistats run data/raw --out output
```

`output/` is git-ignored as well, because the dashboard contains driver
names and plates. Add `--anonymise` for a version you can share.

To compare a real export's structure with the sample without revealing any
values:

```bash
taxistats profile data/raw/<export-folder>
```
