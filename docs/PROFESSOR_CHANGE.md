# Professor-requested executed-path pipeline

Professor guidance:

1. Execute one fixed generic Behavior Tree many times.
2. Represent the path actually executed as a Behavior Tree itself.
3. Convert that special executed-path BT to the input expected by the existing Prolog transformation.
4. Use the existing `btsg.pl` rule to generate the executed Service Graph.

## Implementation

For every run we keep two representations:

- `executed_bt`: a pruned copy of the original BT used for audit/explanation; it keeps Conditions and original structure.
- `executed_path_bt`: a special Sequence BT containing the Action services in the exact runtime order. This is the transformation input.

The separation is deliberate. A merely-pruned Fallback tree still carries static selector exit-set semantics and can create a false edge from a failed branch to a downstream service. The resolved executed-path BT removes that ambiguity without changing `btsg.pl`.

Retry multiplicity remains in the runtime trace and is not duplicated structurally in the SG.
