# Reuse of the existing Prolog rule

`prolog/btsg.pl` is copied unchanged from the previous BT-SG project.

Expected SHA-256:

`98f88f8cc0a8e81b8f3301cf73542c4579023ae10038ed63e77edff83ea62ab0`

The new code changes only the **input BT representation** supplied to the rule:

```text
runtime trace
  -> resolved executed-path BT
  -> legacy-compatible JSON
  -> existing JSON-to-Prolog term conversion
  -> unchanged btsg.pl
  -> executed SG edges
```

This keeps a single BT-to-SG transformation authority while making the Prolog input correspond to the path that actually happened at runtime.
