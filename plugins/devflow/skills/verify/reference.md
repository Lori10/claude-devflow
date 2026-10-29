# What counts as a weakened test

Never weaken an existing test unless its spec changed. In a diff of the test paths, each of
these is a weakening unless the change's delta spec (`openspec/changes/<name>/specs/`)
changed the behaviour the test pins:

- An assertion removed, or relaxed: `==` → `in`, exact count → `>=`, a specific error type
  → `Exception`, `toEqual` → `toBeTruthy`.
- A skip added to an existing test: `pytest.mark.skip/skipif/xfail`, `pytest.skip(...)`,
  `@unittest.skip`, `it.skip`, `test.skip`, `describe.skip`, `xit`, `.todo`.
- `.only` added: it silently stops every other test in the file from running.
- An existing test deleted or renamed away without a replacement covering its scenario.
- An expected value edited to match new output (the "update the snapshot" move).
- A mock widened or a fixture changed so a guard or error path never fires.

Not weakening: moving or splitting a test with the same assertions (the scan already ignores
lines that reappear unchanged), adding tests, tightening assertions, or fixing a test that
asserted a bug the spec says is wrong (cite the spec line).
