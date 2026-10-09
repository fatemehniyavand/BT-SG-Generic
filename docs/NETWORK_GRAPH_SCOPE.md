# Network Graph scope

The Network Graph and placement/routing solver are intentionally **not used in this phase**.

Current phase:

`Fixed BT -> Execution -> Executed BT -> Existing Prolog -> Executed SG -> activation statistics -> operation-based workload`

Later phase:

`Executed SG + operation workload -> resource mapping -> Network Graph + Solver -> placement/routing/cost`

A mapping from generic operation counts to solver resource units must be defined before the Network Graph/solver integration is scientifically meaningful.
