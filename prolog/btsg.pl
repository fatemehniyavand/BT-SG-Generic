% ============================================================================
%  BEHAVIOUR TREE  ->  SERVICE DEPENDENCY GRAPH
% ============================================================================
%
%  WHAT THIS PROGRAM DOES
%  -----------------------
%  It takes a Behaviour Tree (BT) definition, together with the Blackboard
%  that the tree's tasks read from / write to, and derives a "service
%  graph": a set of directed edges  edge(A, B, Reason)  meaning
%
%       "task A cannot (successfully) execute until task B has finished"
%
%  Three different mechanisms create these edges, matching how a BT
%  actually behaves at runtime:
%
%   1. SEQUENCE ordering   - a Sequence node runs its children strictly
%                             left-to-right, and every child requires all
%                             earlier children to have SUCCEEDED. This is a
%                             hard dependency  -> Reason = sequence.
%
%   2. SELECTOR ordering   - a Selector node also runs children left to
%                             right, but a child only runs if the earlier
%                             children FAILED. This is not a "success"
%                             dependency in the same sense, but it is still
%                             a real execution-order dependency (you cannot
%                             even ATTEMPT the later child before the
%                             earlier one is resolved), so we record it as
%                             a distinct, weaker/conditional edge
%                             -> Reason = selector.
%
%   3. BLACKBOARD linking   - if task W writes a blackboard key K and task R
%                             reads the same key K, then R depends on W
%                             having run first (otherwise R would read
%                             stale/undefined data) -> Reason = blackboard(K).
%
%  Dependencies also propagate UP and DOWN the tree: if a Sequence/Selector
%  is itself the child of a higher Sequence/Selector, then everything
%  inside that subtree inherits the dependency the subtree-as-a-whole has
%  on its own earlier siblings. This is implemented by threading an
%  "InheritedDeps" accumulator through the recursive tree traversal (see
%  traverse/5 below) - this is the mechanism that answers "if we go up the
%  tree ... we also depend on the success of that".
%
% ============================================================================

:- use_module(library(lists)).

% ----------------------------------------------------------------------------
% 1. BASIC TYPES
% ----------------------------------------------------------------------------

% The primitive value-types a blackboard key can hold.
blackboardKeyType(string).
blackboardKeyType(integer).
blackboardKeyType(float).
blackboardKeyType(boolean).

% The two composite ("meta") node kinds a Behaviour Tree can branch on.
metanodeType(sequence).
metanodeType(selector).

% Helper: accept atoms OR strings as identifiers (task names, key names...).
% This is what `string/1` in the draft was really trying to express.
taskAtomic(X) :- atomic(X).

% ----------------------------------------------------------------------------
% 2. BLACKBOARD
% ----------------------------------------------------------------------------

% bbkey(Key, Type) declares one blackboard slot.
bbkey(Key, Type) :-
    taskAtomic(Key),
    blackboardKeyType(Type).

% blackboard(+ListOfBbkeyTerms)
% A blackboard is just a list of declared keys. We also require the key
% *names* to be unique - two keys with the same name but different types
% would make dependency resolution ambiguous.
blackboard([]).
blackboard(BB) :-
    BB = [_|_],
    forall(member(K, BB), bbkey_term(K)),
    keyNames(BB, Names),
    is_set(Names).

bbkey_term(bbkey(K, T)) :- bbkey(K, T).

keyNames([], []).
keyNames([bbkey(K, _) | T], [K | Ns]) :- keyNames(T, Ns).

% ----------------------------------------------------------------------------
% 3. PARAMETERS
% ----------------------------------------------------------------------------
% A parameter attached to a task is one of:
%   param(Name, const)      - a plain literal value, no blackboard involved
%   param(Name, read(Key))  - the task READS blackboard key `Key`
%   param(Name, write(Key)) - the task WRITES blackboard key `Key`
%
% (`Name` is the parameter's own name/label inside the task, e.g. "target".)

parameter(param(Name, const)) :-
    taskAtomic(Name).
parameter(param(Name, read(Key))) :-
    taskAtomic(Name),
    taskAtomic(Key).
parameter(param(Name, write(Key))) :-
    taskAtomic(Name),
    taskAtomic(Key).

parameters([]).
parameters([H|T]) :-
    parameter(H),
    parameters(T).

% ----------------------------------------------------------------------------
% 4. TREE NODES
% ----------------------------------------------------------------------------
% task(Name, Params)   - a leaf node / a "service" to be executed.
% seq(Children)        - a Sequence meta-node.
% sel(Children)        - a Selector meta-node.
% Children is always a (possibly empty) list of nodes.

taskNode(task(Name, Params)) :-
    taskAtomic(Name),
    parameters(Params).

metaNode(seq(Children)) :-
    nodeList(Children).
metaNode(sel(Children)) :-
    nodeList(Children).

node(X) :- taskNode(X).
node(X) :- metaNode(X).

nodeList([]).
nodeList([H|T]) :-
    node(H),
    nodeList(T).

% A whole tree = a single root node plus the blackboard it operates on.
% bt(RootNode, Blackboard)
root(bt(Root, BB)) :-
    node(Root),
    blackboard(BB).

% ----------------------------------------------------------------------------
% 5. LINKING / VALIDATION
% ----------------------------------------------------------------------------
% isLinked(+Node, +Blackboard)
% Succeeds if every blackboard key referenced (read or write) by any task
% inside Node is actually declared in Blackboard. This catches typos such
% as a task reading a key that was never declared.
isLinked(task(_Name, Params), BB) :-
    !,
    forall(
        member(param(_PName, Mode), Params),
        ( Mode = read(Key)  -> member(bbkey(Key, _), BB)
        ; Mode = write(Key) -> member(bbkey(Key, _), BB)
        ; true                                  % const params: nothing to check
        )
    ).
isLinked(seq(Children), BB) :-
    !,
    forall(member(C, Children), isLinked(C, BB)).
isLinked(sel(Children), BB) :-
    !,
    forall(member(C, Children), isLinked(C, BB)).

% behaviourTree(+Tree)
% Top-level validity check: Tree = bt(Root, Blackboard) is well-formed AND
% every blackboard reference inside it resolves to a declared key.
behaviourTree(bt(Root, BB)) :-
    blackboard(BB),
    node(Root),
    isLinked(Root, BB).

% ----------------------------------------------------------------------------
% 6. STRUCTURAL DEPENDENCIES (Sequence / Selector ordering)
% ----------------------------------------------------------------------------
%
%  traverse(+Node, +InheritedDeps, -EntrySet, -ExitSet, -Edges)
%
%  InheritedDeps : list of dep(TaskName, Reason) terms this subtree's very
%                  FIRST executed task(s) must additionally depend on
%                  (this is how dependencies from ancestors flow down).
%  EntrySet      : the task(s) that would run FIRST if this subtree runs.
%  ExitSet       : the task(s) that could be the LAST ones to run in this
%                  subtree (used to build the InheritedDeps for the NEXT
%                  sibling at the level above).
%  Edges         : every edge(A, B, Reason) discovered inside this subtree.
%
%  Why ExitSet differs between sequence and selector:
%    - Sequence always finishes on its LAST child (all children run), so
%      ExitSet = ExitSet of the last child only.
%    - Selector finishes as soon as ONE child succeeds, and at "compile
%      time" we don't know which one that will be, so ExitSet = the union
%      of every child's ExitSet (any of them might turn out to be "last").

% --- Leaf task -------------------------------------------------------------
traverse(task(Name, _Params), InheritedDeps, [Name], [Name], Edges) :-
    !,
    findall(
        edge(Name, DepTask, Reason),
        member(dep(DepTask, Reason), InheritedDeps),
        Edges
    ).

% --- Sequence ---------------------------------------------------------------
traverse(seq(Children), InheritedDeps, EntrySet, ExitSet, Edges) :-
    !,
    Children = [First | Rest],
    traverse(First, InheritedDeps, EntrySet, FirstExit, FirstEdges),
    seqChain(Rest, FirstExit, FirstEdges, ExitSet, Edges).

% seqChain(+RemainingChildren, +PrevExit, +EdgesSoFar, -FinalExit, -AllEdges)
% Threads the "previous sibling's exit tasks" through the rest of the
% sequence, turning each PrevExit into a `sequence` dependency for the
% next child.
seqChain([], PrevExit, Edges, PrevExit, Edges).
seqChain([C | Rest], PrevExit, EdgesAcc, ExitSet, Edges) :-
    depsFromExits(PrevExit, sequence, Deps),
    traverse(C, Deps, _EntryC, ExitC, EdgesC),
    append(EdgesAcc, EdgesC, EdgesAcc2),
    seqChain(Rest, ExitC, EdgesAcc2, ExitSet, Edges).

% --- Selector -----------------------------------------------------------
traverse(sel(Children), InheritedDeps, EntrySet, ExitSet, Edges) :-
    !,
    Children = [First | Rest],
    traverse(First, InheritedDeps, EntrySet, FirstExit, FirstEdges),
    selChain(Rest, FirstExit, FirstExit, FirstEdges, ExitSet, Edges).

% selChain(+RemainingChildren, +PrevExit, +UnionExitSoFar, +EdgesSoFar,
%           -FinalUnionExit, -AllEdges)
% Same idea as seqChain, but (a) the dependency Reason is `selector`
% (a "ran only because the previous one failed" relationship) and
% (b) we accumulate the UNION of every child's exit tasks, since any
% child could be the one that ends up succeeding.
selChain([], _PrevExit, UnionExit, Edges, UnionExit, Edges).
selChain([C | Rest], PrevExit, UnionExit, EdgesAcc, ExitSet, Edges) :-
    depsFromExits(PrevExit, selector, Deps),
    traverse(C, Deps, _EntryC, ExitC, EdgesC),
    append(EdgesAcc, EdgesC, EdgesAcc2),
    union(UnionExit, ExitC, UnionExit2),
    selChain(Rest, ExitC, UnionExit2, EdgesAcc2, ExitSet, Edges).

% depsFromExits(+ExitTasks, +Reason, -DepTerms)
% Turns a list of task names into dep(Task, Reason) terms.
depsFromExits(Exits, Reason, Deps) :-
    findall(dep(T, Reason), member(T, Exits), Deps).

% ----------------------------------------------------------------------------
% 7. BLACKBOARD DEPENDENCIES
% ----------------------------------------------------------------------------
%
%  collectParamRefs(+Node, -Refs)
%  Walks the whole tree and collects ref(TaskName, Key, Mode) for every
%  blackboard-touching parameter, Mode in {read, write}.

collectParamRefs(task(Name, Params), Refs) :-
    !,
    findall(
        ref(Name, Key, Mode),
        ( member(param(_PName, ModeTerm), Params),
          ( ModeTerm = read(Key)  -> Mode = read
          ; ModeTerm = write(Key) -> Mode = write
          )
        ),
        Refs
    ).
collectParamRefs(seq(Children), Refs) :- !, collectParamRefsList(Children, Refs).
collectParamRefs(sel(Children), Refs) :- !, collectParamRefsList(Children, Refs).

collectParamRefsList([], []).
collectParamRefsList([C | Cs], Refs) :-
    collectParamRefs(C, R1),
    collectParamRefsList(Cs, R2),
    append(R1, R2, Refs).

% buildBlackboardEdges(+RootNode, -Edges)
% For every (Reader, Key) / (Writer, Key) pair on the SAME key where
% Reader \= Writer, add an edge Reader -> Writer labelled blackboard(Key).
%
% NOTE / SIMPLIFICATION: this pass is global - it does not check whether
% the writer is actually guaranteed to run before the reader according to
% the tree structure (e.g. two tasks living in different branches of a
% Selector, only one of which will ever execute). Doing that precisely
% would require cross-referencing this with the structural EntrySet/ExitSet
% computed above. For now we simply record "a data dependency exists if it
% is textually possible"; tightening this to structurally-guaranteed-only
% dependencies is a natural next step (see TODO at the bottom of the file).
buildBlackboardEdges(Root, Edges) :-
    collectParamRefs(Root, Refs),
    findall(
        edge(ReaderTask, WriterTask, blackboard(Key)),
        ( member(ref(ReaderTask, Key, read), Refs),
          member(ref(WriterTask, Key, write), Refs),
          ReaderTask \= WriterTask
        ),
        EdgesDup
    ),
    list_to_set(EdgesDup, Edges).

% ----------------------------------------------------------------------------
% 8. TOP-LEVEL: BUILD THE FULL SERVICE GRAPH
% ----------------------------------------------------------------------------
%
%  serviceGraph(+Tree, -Edges)
%  Tree = bt(Root, Blackboard). Validates the tree, then combines the
%  structural (sequence/selector) edges with the blackboard edges into one
%  deduplicated edge list.
serviceGraph(bt(Root, BB), Edges) :-
    behaviourTree(bt(Root, BB)),
    traverse(Root, [], _Entry, _Exit, StructEdges),
    buildBlackboardEdges(Root, BBEdges),
    append(StructEdges, BBEdges, AllEdges),
    list_to_set(AllEdges, Edges).

% printServiceGraph(+Edges)
% Pretty-prints "A depends on B  [because Reason]" for every edge.
printServiceGraph([]).
printServiceGraph([edge(A, B, Reason) | T]) :-
    format("~w depends on ~w  [~w]~n", [A, B, Reason]),
    printServiceGraph(T).

% ----------------------------------------------------------------------------
% 9. FUTURE EXTENSIONS (stubs / notes only - not implemented)
% ----------------------------------------------------------------------------
% The task mentioned "observers and service functions" without further
% detail. Two natural ways to fold those into this model, left as TODOs:
%
%   - Decorator / Observer nodes: a node that wraps a SINGLE child and
%     conditionally allows/blocks/repeats it, e.g. decorator(Type, Child).
%     traverse/5 would gain a clause:
%         traverse(decorator(_Type, Child), InheritedDeps, Entry, Exit, Edges) :-
%             traverse(Child, InheritedDeps, Entry, Exit, Edges).
%     i.e. it passes dependencies through unchanged, since it doesn't add
%     siblings - unless the decorator itself reads/writes the blackboard
%     (e.g. a "Cooldown" decorator storing a timestamp), in which case it
%     would need its own Params and would participate in the blackboard
%     pass exactly like a task.
%
%   - Service / observer functions running independently of tree ticking
%     (e.g. a background monitor that only WRITES to the blackboard): these
%     could be modelled as ordinary task/2 nodes that live outside the
%     seq/sel structure but are still passed through collectParamRefs/2, so
%     they'd automatically produce blackboard(Key) edges into any task that
%     reads what they write, without needing sequence/selector edges at all.
%
% ============================================================================
% 10. WORKED EXAMPLE / DEMO
% ============================================================================
%
%  A robot BT:
%
%    Sequence "root"
%      +-- Selector "reach_target"
%      |     +-- task "navigate_to"      writes bb(at_target)
%      |     +-- task "request_teleport" writes bb(at_target)
%      +-- task "pick_up"    reads bb(at_target), writes bb(holding_item)
%      +-- task "deliver"    reads bb(holding_item)
%
%  Expected dependencies:
%    - navigate_to        : none (first task overall)
%    - request_teleport    -> navigate_to        [selector]  (tried 2nd)
%    - pick_up              -> navigate_to        [sequence]  (exit of selector
%                                                    subtree = union of both
%                                                    branches)
%    - pick_up              -> request_teleport    [sequence]
%    - pick_up              -> navigate_to        [blackboard(at_target)]
%    - pick_up              -> request_teleport    [blackboard(at_target)]
%    - deliver              -> pick_up             [sequence]
%    - deliver              -> pick_up             [blackboard(holding_item)]

demoBlackboard([
    bbkey(at_target, boolean),
    bbkey(holding_item, boolean)
]).

demoTree(bt(Root, BB)) :-
    demoBlackboard(BB),
    Root = seq([
        sel([
            task(navigate_to,      [param(speed, const), param(dest, write(at_target))]),
            task(request_teleport, [param(dest, write(at_target))])
        ]),
        task(pick_up,  [param(item, read(at_target)), param(slot, write(holding_item))]),
        task(deliver,  [param(item, read(holding_item))])
    ]).

demo(Edges) :-
    newTree(Tree),
    serviceGraph(Tree, Edges),
    format("Service graph edges:~n"),
    printServiceGraph(Edges).

% Run with:  ?- demo.
