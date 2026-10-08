# Contributing

Thanks for helping improve Portfolio. Bug reports, fixes and new features are
all welcome.

## Never share real financial data

Issues, pull requests, screenshots and test fixtures must not contain real
account numbers, balances or transactions. Reproduce problems with the demo
data (`python src/app.py --demo`) or a small synthetic CSV in a test. Your
own exports live in `data/`, which is git-ignored; keep it that way.

## Development setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python src/app.py --demo
```

## Tests

Every change that touches numbers needs a test. Write it first, watch it fail,
then make it pass. Tests are plain Python files in `tests/`:

```bash
for t in tests/test_*.py; do python "$t" || break; done
```

CI runs the same command on every push and pull request.

## Code layout

| Layer | Files | Owns |
|---|---|---|
| Data | `src/data_loader.py` | Parsing Fidelity CSVs, categorizing transactions, prices |
| Calculations | `src/metrics.py`, `src/insights.py` | Cost basis, returns, derived facts |
| UI | `src/layout.py`, `src/views.py`, `src/components.py`, `src/charts.py`, `src/formatting.py` | Pages, building blocks, charts, number formatting |
| App | `src/app.py` | Loading data and wiring callbacks |

Keep calculations out of the UI layer, and send every displayed number through
`formatting.py`.

## Pull requests

- Keep each pull request focused on one change.
- Use conventional commit messages: `feat:`, `fix:`, `docs:`, `test:`,
  `refactor:`, `chore:`.
- If the UI changes, include a screenshot taken with `--demo`.
- Confirm that values on unaffected views stay the same.
