# dedupe (bug case)

Issue: dedupe() loses the original order: dedupe([3, 1, 3, 2]) returns [1, 2, 3] instead of [3, 1, 2].

The docstring documents more than the visible tests check; a minimal fix can pass the visible tests and still violate the contract.
