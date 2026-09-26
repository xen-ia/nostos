# Router eval fixtures

15 labeled Nostos briefs (`router-cases.json`) + the 6 Jev questions (`nostos-*.task.json`)
in the exact wire format sent to `POST /v1/systemone`.

Measured 2026-09-20 with `jev-1.13.0` via [4esv/jev-eval](https://github.com/4esv/jev-eval):
accuracy 0.89 (80/90), per-question budget 1.00, crowds 0.93, flights 0.93,
pace 0.87, stay 0.73, travel-mode 0.87. n=15: wide CIs, do not overclaim.
Known-ambiguous: `sicilia-auto` crowds (borghi = anti-mass or not?).

Re-run (costs cents, needs `TYPESAFE_API_KEY`):

```bash
git clone https://github.com/4esv/jev-eval /tmp/jev-eval
# copy tests/eval/nostos-*.task.json + generated per-question jsonl into /tmp/jev-eval/data/
uv run --project /tmp/jev-eval --directory /tmp/jev-eval python -m evaljev.run --task nostos-pace --model jev
```
