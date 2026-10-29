# truncate (bug case)

Issue: truncate('hello world', 8) returns 'hello wo...' (11 characters), which is longer than the requested width of 8.

The docstring documents more than the visible tests check; a minimal fix can pass the visible tests and still violate the contract.
