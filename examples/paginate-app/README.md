# Paginate (bug case)

Issue: `paginate()` returns the wrong slice (page 2 of `[1..7]` with `per_page=3` should be
`[4, 5, 6]`). The visible tests only cover the slice arithmetic; the documented contract also
requires `ValueError` for `page < 1` / `per_page < 1`. A fix that only corrects the slice
passes the visible tests but violates the contract: this is the case adversarial tests
should catch.
