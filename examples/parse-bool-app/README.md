# parse_bool (bug case)

Issue: parse_bool('false') returns True. Config values like 'false' must parse to False.

The docstring documents more than the visible tests check; a minimal fix can pass the visible tests and still violate the contract.
