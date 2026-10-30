# Memory-Constrained MoE Partitioning and Overlap Throughput Optimization

## 1. Background

In large-model training, an MoE (Mixture of Experts) layer replaces "one large FFN" with $E$ small experts: each token is routed to only a few experts, and the computation is carried out by the NPUs hosting those experts. This can scale the parameter count up by an order of magnitude while the compute stays essentially unchanged — the price is that **the data has to flow**: a token must first be sent to the card hosting its expert, and sent back once the computation is done.

To make a cluster run fast, systems usually use two kinds of parallelism at the same time:

- **Expert Parallelism (EP)**: the $E$ experts of the same layer are placed on different NPUs. Tokens are sent to the cards hosting the target experts through AllToAll, and sent back through AllToAll once the computation is done.
- **Pipeline Parallelism (PP)**: the $L$ layers are cut into several segments (stages), and microbatches flow through the stages one after another like a pipeline. Schemes such as DualPipe inject microbatches from both ends at the same time in order to reduce bubbles.

The two are entangled with each other: EP decides whether AllToAll traffic goes intra-node or inter-node (the two bandwidths often differ by an order of magnitude), while PP decides which layers share a card and how many bubbles the pipeline has; and the HBM (high-bandwidth memory) of each card is a hard cap, with expert parameters, communication buffers and activations all fighting over the same memory.

**This problem:** given the cluster topology, the per-card memory, the model scale and the per-layer load, output a complete mapping (grid, cut points, per-layer expert placement, whole-step schedule) that minimizes the wall-clock time of one training step while every card stays within its memory cap.

### Problem challenges

Three layers of decisions are coupled together:

- **Grid** $(V,P)$: the number of stages and the expert-parallel size. It determines how many experts each card must keep resident ($E/P$ per layer), and is also the direct source of the memory taken by expert parameters; it further determines over how many nodes the communication peers are spread, and hence whether traffic goes intra-node or inter-node.
- **Cut points** $\psi$: how the $L$ layers are cut contiguously into $V$ segments. It determines which layers share a card, and therefore the memory budget of each card and how slow the slowest stage is.
- **Schedule**: how communication and computation interleave along the time axis. It determines all overlap and all bubbles, and at the same time determines how much buffer and how many activations have not yet been released at a given moment.

The total running time is determined by several interacting bottlenecks: the most congested communication edge, the slowest stage, and the longest chain of dependent operations.  The memory cap further restricts which configurations are feasible.  The four decisions of the contestant (the grid, the cut points, the expert placement and the schedule) therefore affect time and memory jointly, and must be chosen together rather than one after another.

### Business value

MoE is the core structure of mainstream large models, and the joint EP/PP mapping directly determines training throughput and memory usage. Automated mapping and scheduling search can reduce large-model training's dependence on expert hand-tuning and provides reusable layout and scheduling capability for AI compilers and cluster scheduling stacks.

---

### 1.1 The four steps of one forward pass, and where overlap comes from

The forward pass of one MoE layer on each card consists of four steps:

1. **Shared expert**: every token goes through it. Pure computation, with no cross-card communication involved.
2. **Dispatch AllToAll**: send the local tokens, according to the routing result, to the cards hosting the target experts. Pure communication.
3. **GroupGEMM**: compute the experts that landed on this card. Pure computation.
4. **Combine AllToAll**: send the experts' outputs back to the cards the tokens originally came from. Pure communication.

The backward pass correspondingly produces six steps: the input gradient and the weight gradient of the shared expert, the gradient of the expert inputs and the gradient of the expert weights, plus the backward communication of dispatch and of combine respectively.

**The forward and backward passes combined give ten steps for each layer on each card.**  The key point is that each NPU has a fixed communication capability and a fixed computation capability: communication occupies the communication engine and computation occupies the computation engine, so the two can run at the same time.  Section 4.1 gives the engine and the duration of each step and Section 4.2 the dependencies between them, and the gain in running time comes from designing the overlaps while satisfying those dependencies.  A layer's ten steps are not one chain: the forward pass has the shared expert `s` beside the dispatch, and the backward pass mirrors it -- the routed chain is `comb_bwd → gemm_dx → disp_bwd`, the shared expert's input gradient `s_bwd` is released beside `comb_bwd` and only has to finish before `disp_bwd`, and the two weight-gradient steps only have to follow `comb_bwd`.  Overlap can therefore also come from hiding `s_bwd` under the combine backward and from sliding the weight-gradient steps of one layer into a gap of another, on top of interleaving between different microbatches or between different layers.

**Three classical patterns appear in existing papers.**  All of them can be expressed in the output format of this problem, but we allow more general schedules: what a contestant submits is a complete schedule, and the three patterns are merely special cases of it.

- **1F1B** (one forward, one backward): once the pipeline is full, each stage alternates between the forward pass of a new microbatch and the backward pass of an older one, so the stage stays busy in both directions while only a bounded number of microbatches are in flight.  See PipeDream [3].
- **ZB1P** (split the backward pass and slide its lighter half): rule 1 of Section 4.2 splits the backward pass of a layer into the input-gradient half -- the routed chain `comb_bwd → gemm_dx → disp_bwd`, with the shared expert's input gradient `s_bwd` released beside `comb_bwd` and only required to finish before `disp_bwd` -- and the two weight-gradient steps `gemm_dw`, `s_dw`, which need the incoming gradient and nothing else; the routed chain is chained but the two weight-gradient steps may be placed anywhere after `comb_bwd`, so they can be moved into moments when the computation engine would otherwise be idle.  Rule 2 anchors the neighbouring layer's backward pass on `disp_bwd`, the end of the routed input-gradient chain, so the deferral is structural rather than merely permitted: pushing the weight gradient back delays no other layer.  See the ZB-H1 schedule of the zero-bubble pipeline work [2].
- **DUALPIPE** (two chunks on one card): with $K=2V$ a card group holds chunk $k$ and its mirror $2V-1-k$, so one of them can run a forward pass while the other runs the backward pass of a different microbatch; with $K=V$ a card holds a single chunk and the pattern is out of reach.  See the DualPipe arrangement of the DeepSeek-V3 report [1].

**To keep the problem manageable, we make several simplifications.**  Operations are atomic: tile-level chunking is not allowed, so an operation of Section 4.1 is never divided into parts (Section 3.2).  AllToAll and GroupGEMM are never fused into one kernel, as in UniEP [4], because that would require consuming a payload before it has fully arrived (Section 4.2, rule 1).  What does overlap the dispatch *within* one microbatch is the shared expert: it reads the layer's incoming activation and writes into the layer's `comb`, so it can run beside the AllToAll the same layer is waiting on -- the overlap rule 1 of Section 4.2 is built around, and the one DualPipe hides.  The load distribution is fixed and known in advance: $a_{\ell,e}$ does not change during the step, and a schedule declares all of its start times up front rather than adapting them at run time.  Finally, computation and communication are assumed not to slow each other down: each operation lasts exactly as long as Section 4.1 says.
## 2. Input

All quantities are non-negative integers, separated by whitespace on the same line.

This problem does not simulate a real clock: **all time quantities are measured in the same abstract "time unit"**, and the absolute value of `Time` has no physical meaning; it is used only for ranking comparisons. The bandwidths $B_{\mathrm{in}},B_{\mathrm{out}}$ are measured in bytes per time unit, and the time coefficients $F_{\mathrm{s}},F_{\mathrm{io}},F_{\mathrm{in}}$ are measured in time units.

**Line 1** $N\ S\ M\ B_{\mathrm{in}}\ B_{\mathrm{out}}$: cluster and memory.

| Symbol | Meaning |
|------|------|
| $N$ | Number of nodes |
| $S$ | Number of NPUs per node; total number of cards $R=N\cdot S$ |
| $M$ | HBM cap per card (bytes) |
| $B_{\mathrm{in}}$ | Intra-node bandwidth (bytes/time unit). All communication within the same node goes through it, and it is usually far larger than the inter-node bandwidth |
| $B_{\mathrm{out}}$ | Inter-node bandwidth (bytes/time unit), $B_{\mathrm{out}}\le B_{\mathrm{in}}$ |

**Line 2** $L\ E\ Z\ Z_{\mathrm{s}}\ U\ U_{\mathrm{act}}\ k\ n_{\mathrm{mb}}\ F_{\mathrm{s}}\ F_{\mathrm{io}}\ F_{\mathrm{in}}\ \alpha_{\times}\ \beta_{\times}$: model scale, buffers and time coefficients.

| Symbol | Meaning |
|------|------|
| $L$ | Number of MoE layers |
| $E$ | Number of routable experts per layer (the same for every layer) |
| $Z$ | Parameter size of a single routable expert (bytes). Each card keeps $E/P$ experts resident per layer, so each layer occupies $(E/P)Z$ bytes |
| $Z_{\mathrm{s}}$ | Size of the shared expert (one copy per card per layer, may be 0) |
| $U$ | Number of bytes of one communication buffer. Each card group has only one communication engine (Section 4.2, rule 3), so at most one communication operation is in flight on a card at a time, occupying $U$ bytes; see 4.6 |
| $U_{\mathrm{act}}$ | Number of activation bytes of one (microbatch, layer); see 4.6 |
| $k$ | Number of experts each token is routed to (top-$k$, the same for every layer) |
| $n_{\mathrm{mb}}$ | Number of microbatches (even). It determines how many microbatches are in flight in the pipeline at the same time |
| $F_{\mathrm{s}}$ | Shared-expert time coefficient (per slot): how many time units the shared expert of one slot takes |
| $F_{\mathrm{io}}$ | AllToAll communication coefficient (time units per unit of bandwidth time, see 4.4) |
| $F_{\mathrm{in}}$ | GroupGEMM computation coefficient (how many time units per slot, see 4.3) |
| $\alpha_{\times},\beta_{\times}$ | Backward coefficients (micro-units): $\alpha=10^{-6}\alpha_{\times}$, $\beta=10^{-6}\beta_{\times}$.  They fix the relative length of the forward pass, of the backward pass and of its weight-gradient part; Section 4.1 says exactly where each of them applies |

**Line 3** $d\ b$: hidden width (number of elements) and element size in bytes.  The activations of each token are $d\cdot b$ bytes, partitioned over the $k$ experts it is routed to, so the payload each slot hands to one peer is $H=\lfloor d\,b/k\rfloor$ bytes.

**From line 4 on, $L$ lines in total**, each describing the load of one layer. Line $\ell$ is $T_\ell$ together with an optional load vector:

- $T_\ell$ is the number of token-slots of layer $\ell$ (top-$k$ already expanded, i.e. $T_\ell=k\cdot B_\ell$, where $B_\ell$ is the number of tokens of that layer).
- If the layer is load-balanced, the line contains only $T_\ell$.
- Otherwise $E$ integers $a_{\ell,0}\dots a_{\ell,E-1}$ follow it, giving the number of slots routed to each expert, satisfying $\sum_e a_{\ell,e}=T_\ell$.

Two conditions hold across the $L$ layers of one instance: every $T_\ell$ is a multiple of $k$, and $\max_\ell T_\ell/\min_\ell T_\ell\le1.2$; Section 6 states them together with the other data ranges.

Note that the input gives **a static load distribution**: how many slots each expert of each layer receives is fixed in the input and does not change from training step to training step. The model also does not assume that it is uniform — in real training the gating output is naturally skewed, and different layers are skewed by different amounts. Since the load is known, how the experts are placed (see Section 4.3) becomes a decision that can be optimized on that basis.

---

## 3. Output

Output the complete mapping in the following format:

```text
V P
PSI
K ψ_1 ψ_2 ... ψ_{K-1}
MAP
σ_0,0 σ_0,1 ... σ_0,E-1
...
SCHEDULE
t mb:ℓ:op mb:ℓ:op ...
...
```

### 3.1 Field-by-field description

| Field | Meaning |
|------|------|
| `V` | Number of pipeline stages (a cut along the layers) |
| `P` | Expert-parallel size (across how many ranks the experts of one layer are cut).  It must satisfy $P\mid S$ or $S\mid P$, so that EP groups are aligned with nodes (Section 4.4) |
| `PSI` | The chunk count $K$, followed on the same line by the $K-1$ cut points $\psi_1,\dots,\psi_{K-1}$, strictly increasing.  $K$ must be $V$ (one chunk per card group, the default) or $2V$ (two chunks per card group); any other count is illegal, and when $K=1$ the line holds only the count `1` itself, with no cut points.  Chunk $k$ contains the layers $[\psi_k,\psi_{k+1})$, and chunk $k$ belongs to card group $g(k)=k$ for $k<V$ and $g(k)=2V-1-k$ for $k\ge V$; this is the mirror pairing, so with $K=2V$ every card group holds one early chunk and one late chunk |
| `MAP` | Per-layer expert placement, $L$ lines in total. Line $\ell$ holds $E$ integers $\sigma_{\ell,e}\in[0,P)$: the rank within this EP group at which expert $e$ is placed. Each value occurs exactly $E/P$ times |
| `SCHEDULE` | The whole-step schedule, see below |

**The grid and the physical cards.**  The contestant chooses $V$ and $P$, and that choice fixes how many stages the pipeline has and how wide an EP group is.  What the contestant does not choose is how the $V\times P$ grid is embedded in the physical cards: given those two numbers, the checker applies the fixed rule $q=v\cdot P+p$, with $p$ varying fastest, and it is this rule that decides which consecutive $P$ cards form one EP group and where each stage's block of cards sits.  Physical card $q$ is therefore the card with grid coordinates $(v,p)$, so the $P$ ranks of one EP group are consecutive cards and each stage owns a contiguous block of $P$ cards.  The grid has to fit in the cluster, $V\cdot P\le R$: when $V\cdot P<R$, only the first $V\cdot P$ cards in this order carry layers, and the remaining $R-V\cdot P$ cards are idle -- they run no operation and are charged no memory.  Because $P\mid S$ or $S\mid P$, an EP group either lies entirely inside a node or crosses nodes evenly, which makes the number of intra-node peers of Section 4.4 well defined.  The $P$ cards that share one stage are called a **card group**: it owns the layers of that stage, and it is the unit at which engine occupancy and memory are accounted (Sections 4.2 and 4.6).

### 3.2 Schedule format

A schedule is a timetable. **Each line is one time instant**: the line begins with the integer time instant $t$, followed by several operations written as `mb:ℓ:op`:

- `mb` is the microbatch index, in the range $[0,n_{\mathrm{mb}})$;
- `ℓ` is the layer index, in the range $[0,L)$; which chunk it belongs to is determined by the count $K$ and the cut points declared on the `PSI` line, and the stage is the card group that owns that chunk, so the stage need not be written in the entry;
- `op` is the operation name, one of the ten in Section 4.1.

**All operations on the same line start at the same instant and execute concurrently.** Each layer has exactly the ten operations of Section 4.1, once per microbatch; an operation name outside those ten is invalid.

The output schedule specifies the actions of one representative node for each card group, hence a total of $V$ nodes in a single schedule.  The $P$ cards of a group are equivalent for scheduling purposes: each works on its own expert shards and its own data, so every other card of the group follows the same schedule.  An entry gives a start time and a triple $mb{:}\ell{:}op$: at that time, the card group that owns layer $\ell$ performs operation $op$ of that layer for microbatch $mb$, on all of its cards at once.  Every (microbatch, layer, operation) triple appears in the list exactly once.

Which group carries out which entries follows from the layer index and the `PSI` line, whose cut points split the layers into $K$ chunks.  With $K=V$ each group owns one consecutive range of layers, namely chunk $k$ for card group $k$: that range serves both the forward and the backward passes of the layers in it, and a microbatch's forward pass visits each group once.  With $K=2V$ the chunk-to-group rule is the mirror pairing, chunk $k$ belonging to group $k$ for $k<V$ and to group $2V-1-k$ for $k\ge V$.  Each group therefore owns two pieces of the model, one from the first half of the layer range and one from the second, and the parameters of both pieces are resident on its cards.  The two pieces sit one near the start of the layer order and one near its end.  Since forward passes travel from the start towards the end while backward passes travel the other way, a steady-state schedule can occupy the early piece with the forward passes of young microbatches and the late piece with the backward passes of older ones, so that the group's two engines work on two different microbatches at once.  This is the property a `DUALPIPE`-style schedule uses.  The pipeline is $2V$ chunks deep, and a microbatch's forward pass visits each group twice.

**Constraints on the output**:

1. $t$ must be non-decreasing — the schedule is written in chronological order.
2. No two operations occupying the same engine may appear on the same line (see 4.2 for the exact rules).
3. Lines need not be equally spaced: once one line has been written, simply write the next time instant at which there are new operations.

A minimal complete example (the first microbatch of Section 7.1):

```text
1 2
PSI
1
MAP
0 1
SCHEDULE
0 0:0:disp 0:0:s
70 0:0:gemm
94 0:0:comb
```

**Explanation**: at time 0 the dispatch (duration 70) and the shared expert (duration 16) start together: they are the two entry operations of the layer, dispatch has no predecessor at all, and the shared expert needs only the layer's incoming activation, so it hides under the dispatch. At time 70 GroupGEMM starts (duration 24), and at time 94 combine starts (duration 70) -- it waits for the GroupGEMM and for the shared expert, which finished long before. The last operation ends at $94+70=164$, so $\mathrm{Time}=164$.

---

## 4. Score computation (simulation)

### 4.1 The ten basic operations

Each operation occupies one of the two engines, and its duration is one of the expressions in the table below.  Those expressions are built from three quantities of each layer, $m_\ell$, $x_\ell$ and $s_\ell$ (defined in Sections 4.3 and 4.4), and from the global coefficients.

| Operation | Engine | Duration | Meaning |
|------|------|------|------|
| `s` | Compute | $s_\ell$ | Shared expert forward |
| `disp` | Communication | $x_\ell$ | Dispatch AllToAll |
| `gemm` | Compute | $m_\ell F_{\mathrm{in}}$ | Forward of the experts that landed on this card |
| `comb` | Communication | $x_\ell$ | Combine AllToAll |
| `s_bwd` | Compute | $\alpha\,s_\ell$ | Shared expert input gradient |
| `comb_bwd` | Communication | $\alpha\,x_\ell$ | Combine backward |
| `gemm_dx` | Compute | $\alpha\,m_\ell F_{\mathrm{in}}$ | Expert input gradient |
| `gemm_dw` | Compute | $\alpha\beta\,m_\ell F_{\mathrm{in}}$ | Expert weight gradient |
| `disp_bwd` | Communication | $\alpha\,x_\ell$ | Dispatch backward |
| `s_dw` | Compute | $\alpha\beta\,s_\ell$ | Shared expert weight gradient |

All durations are rounded up to integers.  The forward pass is divided into four steps and the backward pass into six, so that communication and computation can be overlapped at the granularity of individual steps.  The coefficients scale them: the four input-gradient steps of the backward pass cost $\alpha$ times their forward counterparts and the two weight-gradient steps a further factor $\beta$, so a backward pass costs about $\alpha(1+\beta)$ forward passes, of which the weight gradient takes the share $\beta/(1+\beta)$.

### 4.2 Dependencies and resources

A legal schedule must satisfy:

1. **Intra-layer dependencies**: the routed-expert chain is
   `disp → gemm → comb` in the forward pass and `comb_bwd → gemm_dx → disp_bwd` in the backward pass, each step after the one before it.  The shared expert is off those chains: `s` depends only on the layer's input (the edge that releases `disp`, rule 2) and must end before `comb`; `s_bwd` depends only on the incoming gradient (the edge that releases `comb_bwd`, or the layer's own `comb` for the last layer) and must end before `disp_bwd`, whose gradient addition includes the shared-expert part.  The two **weight-gradient steps** `gemm_dw` and `s_dw` need only `comb_bwd` and may be placed anywhere after it in that layer's backward pass.  Both first backward steps, `s_bwd` and `comb_bwd`, may not start before the layer's own `comb`.
2. **Pipeline dependencies (layer order)**: within one microbatch the activation flows from layer to layer, and the gradient flows back the same way.  The two first forward operations of layer $\ell$ (`s` and `disp`) may start only after the forward pass of layer $\ell-1$ is finished, that is, after its `comb`, for every $\ell\ge1$; the two first backward operations of layer $\ell$ (`s_bwd` and `comb_bwd`) may start only after the backward pass of layer $\ell+1$ has delivered the input gradient, that is, after its `disp_bwd`, for every $\ell\le L-2$, on top of their dependence on their own layer's `comb` stated in rule 1.  The anchor is `disp_bwd` and not the last step of layer $\ell+1$'s backward pass because layer $\ell$ consumes the gradient only: everything layer $\ell+1$ does after `disp_bwd` is its own weight gradient, which nothing downstream reads, so it does not hold layer $\ell$ back.  Both statements are made on layers rather than on chunks: they also order two layers that share a card group, and no chunk-level statement is needed on top of them.
3. **Resource exclusivity**: a card group has one computation engine and one communication engine (Section 3.1).  At any instant it may run at most one computation-class operation and at most one communication-class operation; when $K=2V$ this applies to both of its chunks together, so their operations contend for the same two engines.
4. **Causality**: the $t$ declared by an entry may not be earlier than the completion time of what it depends on; a violation makes the mapping illegal.

These four rules are the only scheduling constraints: the contestant is not limited to the classical patterns introduced in Section 1.1, and any schedule satisfying 4.2 may be submitted.

### 4.3 Load, placement and computation time

Each layer places $E/P$ experts per rank (which ones is decided by `MAP`). Let the number of slots carried by rank $r$ in this layer be

$$
L_{\ell,r}=\sum_{e:\ \sigma_{\ell,e}=r}a_{\ell,e},
\qquad
m_\ell=\max_r L_{\ell,r}.
$$

Computation-class operations are determined by **the slowest rank of the layer's EP group**, so $m_\ell$ is used rather than an average: the hotter the experts on one rank, the more the whole layer has to wait for it.

If a layer line carries no load vector, the checker splits its $T_\ell$ slots over the $E$ experts as evenly as possible before computing $m_\ell$, so the per-expert counts differ by at most one.  When the load is balanced, $m_\ell=\lceil T_\ell/P\rceil$, in agreement with the usual formula; when the load is skewed, $m_\ell$ also depends on `MAP` — spreading the hot experts over different ranks pushes $m_\ell$ down. Note that the communication volume $X_\ell$ depends only on the total $T_\ell$ (see 4.4), so **skew raises only the computation and does not change the communication**; the two engines differ in how sensitive they are to skew.

### 4.4 Communication time

The number of bytes each rank sends per layer to **each** of the other $P-1$ ranks in the EP group is:

$$
X_\ell=\left\lceil \frac{T_\ell\,H}{P}\right\rceil,
\qquad H=\left\lfloor \frac{d\,b}{k}\right\rfloor .
$$

A rank holds $T_\ell/P$ slots and sends the $(P-1)/P$ of them that belong to other ranks, about $T_\ell H(P-1)/P$ bytes in all, or $X_\ell$ to each of the $P-1$ peers.  It sends $p_{\mathrm{in}}X_\ell$ bytes to peers inside its node and $p_{\mathrm{out}}X_\ell$ to peers outside it, the two at the same time over their own bandwidths, so the AllToAll lasts as long as the slower of the two.

**Notation for the payload.**  $H=\lfloor d\,b/k\rfloor$ is derived from $d,b,k$ and is not an input.  The model is a **sharded expert model**: the $d\,b$-byte activation of a **token** is partitioned across the $k$ experts it is routed to, that is across its $k$ slots, so each slot carries only its own $H$-byte part and its expert computes a partial result, and the combine step joins the parts again.  A token therefore puts about $d\,b$ bytes on the wire, whatever $k$ is (the floor may leave a few bytes unused).  Computation is charged per slot, so this split changes only the volume sent; $H$ is the same for every MoE layer, and only $T_\ell$ varies.

The set of physical cards occupied by one EP group is determined by the embedding of Section 3.1; it depends only on $P$, so it is the same for every EP group and every layer. Let $p_{\mathrm{in}}$ be the **number of intra-node peers** of a rank within that set and $p_{\mathrm{out}}=P-1-p_{\mathrm{in}}$ its **number of inter-node peers** (computed directly from the embedding, not chosen by the contestant). The duration of one AllToAll of that layer is taken over the slowest class of peers:

$$
x_\ell=\max\!\left(\left\lceil\frac{p_{\mathrm{in}}X_\ell}{B_{\mathrm{in}}}\right\rceil,\
\left\lceil\frac{p_{\mathrm{out}}X_\ell}{B_{\mathrm{out}}}\right\rceil\right)\cdot F_{\mathrm{io}} .
$$

Traffic is broken down by the **actual number of peers** and is not extrapolated linearly with $P$.

The volume does not depend on how the slots are split over the experts: whatever $a_{\ell,e}$, a rank sends the same total, so imbalance moves only the computation, through $m_\ell$.  $B_{\mathrm{in}}$ and $B_{\mathrm{out}}$ are the aggregate bandwidths of the two classes, shared by their peers. The reason is very practical: inter-node bandwidth is usually an order of magnitude lower than intra-node bandwidth, so raising $P$ thins out the per-card computation but pushes more and more traffic onto the narrow link, and the two must be traded off explicitly (see Section 7.3).

### 4.5 Time of one training step

Given $(\mu,V,P)$, the chunk count $K$ declared on the `PSI` line, $\psi$, $\sigma$ and a schedule, the checker:

1. computes the duration of each operation as it is referenced, according to 4.1, 4.3 and 4.4;
2. checks dependencies and resources according to 4.2 and simulates to obtain the actual start and end of each operation;
3. takes the time of one training step to be the maximum completion time over all operations:

$$
\mathrm{Time}=\max_{\text{all operations}}\bigl(t+\text{duration}\bigr).
$$

The checker performs only a forward simulation and **does no optimization or search whatsoever**: the schedule is provided by the contestant, and the checker is responsible only for scoring. This is also why contestants may freely use any heuristic or even an incomplete search — the checker does not need to know what the optimal value is.

### 4.6 Per-card memory

Physical card $q=v\cdot P+p$ (Section 3.1) belongs to card group $v$, which owns the layers of every chunk mapped to it: chunk $v$ in general, and additionally chunk $2V-1-v$ when $K=2V$. Every card of a group holds the same layers, so the check below is the same for all $P$ cards of a group. There are three blocks of usage:

$$
\begin{aligned}
M_{\mathrm{exp}}(q)
&=\sum_{\ell\in\text{card }q}\left(\frac{E}{P}Z+Z_{\mathrm{s}}\right),\\[2mm]
M_{\mathrm{ovl}}(q)
&=U\cdot\max_{t}\ \#\{\text{communication operations started but not finished at } t\},\\[2mm]
M_{\mathrm{act}}(q)
&=U_{\mathrm{act}}\cdot
\max_{t}\ \#\{\text{$(mb,\ell)$ with forward finished and backward unfinished at } t\}.
\end{aligned}
$$

The intuition for the three blocks is as follows:

- $M_{\mathrm{exp}}$ is static: as many experts as are placed, that many copies of parameters are consumed, accumulated linearly with the number of layers. This is the memory that the "cut points" and the "grid" affect directly.
- $M_{\mathrm{ovl}}$ is the communication buffer: a card group has one network engine (Section 4.2, rule 3), so two of its communication operations never run at the same time, and the charge is the peak number of buffers in use.  A communication operation that ends exactly when the next begins counts as two, because the finished buffer is released while the next is being filled; a schedule that leaves a gap instead trades one unit of time for one buffer of memory.
- $M_{\mathrm{act}}$ is the activations, which also change with the schedule: the more spread out the forward pass and the later the backward pass is pushed, the more activations are alive at the same time. An activation $(mb,\ell)$ is counted as **live** from the moment its forward pass finishes, that is, the end of that $(mb,\ell)$'s `comb`, until its backward pass starts, that is, the start of its `s_bwd`; a forward that ends exactly when a backward starts holds its activation at that instant.

The communication operations in $M_{\mathrm{ovl}}$ are the four kinds `disp`, `comb`, `comb_bwd` and `disp_bwd`. Every card of the grid must satisfy $M_{\mathrm{exp}}+M_{\mathrm{ovl}}+M_{\mathrm{act}}\le M$, otherwise the mapping is illegal and scores 0.

### 4.7 Legality constraints

1. $V\cdot P\le R$, $V,P\ge 1$, $P\mid E$, and $P\mid S$ or $S\mid P$;
2. the `PSI` line declares the count $K$ first and then exactly $K-1$ cut points, strictly increasing and covering $0..L$, with $K=V$ or $K=2V$;
3. every line of `MAP` is legal: $\sigma_{\ell,e}\in[0,P)$, and each value occurs exactly $E/P$ times;
4. the schedule satisfies the four rules of 4.2 and references only operation names from the table in 4.1;
5. $n_{\mathrm{mb}}$ is even (guaranteed by the input).

---

## 5. Judging

1. The solver outputs one complete mapping for each test case. Every test case is guaranteed to admit a legal mapping, so no "no solution" marker needs to be output.
2. If the mapping is illegal, out of range, or fails to parse, the test case scores $0$.
3. A legal output is simulated by the checker according to Section 4 to obtain $\mathrm{Time}$, and **the smaller $\mathrm{Time}$ is, the higher the score**; test cases are aggregated into a ranking by relative performance. Ties are broken first by the solver's CPU time, then by submission time.
4. The time limit for each test case is $10$ seconds (wall-clock time; the checker's own simulation time is not counted); a test case that exceeds it scores $0$.

This problem does not require an exactly optimal solution, and contestants are encouraged to explore different mapping and scheduling strategies within the time budget: the checker is responsible only for simulation and scoring, so contestants are free to trade off the depth and breadth of their search.

---

## 6. Data ranges

- **Cluster**: $N\le 32$, $S\le 16$ ($R=NS\le 512$).
- **Model**: $3\le E\le 512$, $L\le 64$, $k\le 64$, $n_{\mathrm{mb}}\le 10^3$ and even, $T_\ell\le 10^9$, $d\le 2^{16}$, $b\in\{1,2,4\}$.
- **Per-layer load**: the input guarantees that every $T_\ell$ is a multiple of $k$, and that for the $L$ layers of one instance $\max_\ell T_\ell/\min_\ell T_\ell\le1.2$.  The first condition makes $B_\ell=T_\ell/k$ an integer, the second keeps the busiest layer within $20\%$ of the lightest.
- **Grid and partitioning**: $V\le 64$ ($V\le L$ is implied by the cut-point rules), $V\cdot P\le R$, $P\mid E$, and $P\mid S$ or $S\mid P$.
- **Time coefficients**: $F_{\mathrm{s}},F_{\mathrm{io}},F_{\mathrm{in}}\le 10^6$, $\alpha_\times,\beta_\times\le 2\times10^6$.
- **Memory and buffers**: $Z,Z_{\mathrm{s}}\le 10^9$; $1\le U,U_{\mathrm{act}}\le 2^{20}$ (1 MiB); $M\le 10^{18}$, and no smaller than the minimum residency $\min_{(V,P)}\left[(L/V)(E/P)Z+(L/V)Z_{\mathrm{s}}\right]$.
- **Bandwidth**: $1\le B_{\mathrm{out}}\le B_{\mathrm{in}}\le 2\times10^5$; the intra-node bandwidth affects the score only when $B_{\mathrm{in}}$ and $B_{\mathrm{out}}$ are of the same order of magnitude.

The number of schedule entries does not exceed $2\times10^7$. Use 128-bit intermediate values for products.

---

## 7. Samples

The six samples below each give an input and an output so that the format can be compared against them; the numbers in the explanations can all be verified by hand from the formulas of Section 4, and every output also satisfies the legality constraints of Section 4.7.


**These outputs are feasible solutions, not optimal solutions**, and serve only to illustrate the format and the mechanics: all the numbers in the listings come from the formulas of Section 4, but the arrangements themselves have not been optimized, and every `SCHEDULE` still has room to be compressed (finer chunking, tighter interleaving, a better `MAP`). The samples are scaled down to the point of being computable by hand, and the optimizations that would separate contestants at real scale are often not fully developed here. The samples also do not represent the scale and difficulty of the test cases: test cases are generated according to the ranges of Section 6, where $L$ and $E$ can both be far larger than here, and the samples need not satisfy the value ranges of Section 6 (for example, $E=2$ in 7.1, 7.5 and 7.6).

### 7.1 Sample 1 (the shared expert hides under the dispatch; two microbatches interleave on the two engines)

**Input**

```text
1 2 39 10 1
1 2 20 0 1 1 1 2 2 10 6 1000000 1000000
8 2
8
```

$R=2$, same node. $H=\lfloor8\cdot2/1\rfloor=16$, $X=\lceil8\cdot16/2\rceil=64$, $p_{\mathrm{in}}=1$, $p_{\mathrm{out}}=0$, $x=\lceil64/10\rceil\cdot10=70$. With $P=2$ there is one expert per rank, $m_0=\lceil8/2\rceil=4$, so `gemm`$=4\cdot6=24$; `s`$=8\cdot2=16$. The only layer is the whole model and sits in the one chunk of the one card group, so there is no layer edge at all.

**Memory forces $P$ up**: $M=39$, and $P=1$ would already exceed it by making every card swallow both experts on its own ($2\times20=40$ bytes of parameters), so $P\ge2$; with $P=2$ each card holds only 1 expert, so $M_{\mathrm{exp}}=20$ bytes of parameters, plus $M_{\mathrm{ovl}}=1$ buffer and $M_{\mathrm{act}}=1$ activation, 22 in total $\le39$, which is feasible.

**Output**

```text
1 2
PSI
1
MAP
0 1
SCHEDULE
0 0:0:disp 0:0:s
16 1:0:s
70 0:0:gemm 1:0:disp
140 0:0:comb 1:0:gemm
210 0:0:s_bwd 1:0:comb
280 0:0:comb_bwd 1:0:s_bwd
350 0:0:gemm_dx 1:0:comb_bwd
374 0:0:gemm_dw
398 0:0:s_dw
420 0:0:disp_bwd 1:0:gemm_dx
444 1:0:gemm_dw
468 1:0:s_dw
490 1:0:disp_bwd
```

**Explanation**: $n_{\mathrm{mb}}=2$, so one step contains the work of two microbatches, 20 operations in total.  **One microbatch is no longer four dependent steps.**  Layer 0 is the first layer of the model, so its two entry operations have nothing to wait for: at time 0 the dispatch (duration 70) and the shared expert (duration 16) start together, and the shared expert disappears under the AllToAll.  `gemm` follows the dispatch and `comb` has to wait for the GroupGEMM *and* for the shared expert, so one microbatch on its own runs $0\to70\to94\to164$ instead of the 180 of the strictly serial order.  **The two microbatches have no dependency between them**, so they can be staggered by one communication step, and the single card group's network engine then never idles: it runs the eight AllToAlls (two microbatches, four each) back to back, $8\times70=560$.  Communication is far heavier than computation here (one AllToAll costs 70 while `gemm` is only 24), so the network engine is the bottleneck, and the schedule above reaches exactly its lower bound, $\mathrm{Time}=560$: with these decisions nothing can be shorter.  On a single card group the two engines are the only resource, and the whole gain comes from keeping the communication engine busy.

### 7.2 Sample 2 (skewed load: computation follows the slowest rank)

**Input**

```text
1 4 79 10 1
2 4 20 0 1 1 1 2 0 100 4 1000000 1000000
8 1
8
8 6 1 1 0
```

$M=79$ rules out $P=1$ (with $P=1$ each card would have to hold 8 experts across two layers, $8\times20=160>79$), so $P\ge2$. Take $P=2$ with two experts per rank: layer 0 is balanced (2 slots per expert) and the load of layer 1 is $(6,1,1,0)$ with $T_1=8$. $H=8$, $X=\lceil8\cdot8/2\rceil=32$, $p_{\mathrm{in}}=1$, $x=\lceil32/10\rceil\cdot100=400$.

**Computation follows the slowest rank**: after `MAP` arranges layer 1 as `0 1 1 0`, the two ranks carry $\{6,0\}=6$ and $\{1,1\}=2$ respectively, so $m_1=6$ and `gemm`$=6\cdot4=24$; layer 0 is balanced, $m_0=4$, `gemm`$=16$. **If layer 1 were also computed under the balanced-load assumption as $\lceil8/2\rceil=4$, the result would be only 16 — an underestimate by a factor of 1.5.** And $X$ depends only on $T_\ell$, so skew does not change the communication volume at all.

The `PSI` line cuts the two layers apart, so they sit on two card groups: the layer edge is a stage boundary, but the model charges nothing for crossing it.  Rule 2 simply chains layer 1's entry operations to layer 0's `comb` and layer 0's first backward steps to layer 1's `disp_bwd`.

**Output**

```text
2 2
PSI
2 1
MAP
0 1 0 1
0 1 1 0
SCHEDULE
0 0:0:s 1:0:disp 1:0:s
400 1:0:gemm
416 1:0:comb
816 0:0:disp 1:1:disp 1:1:s
1216 0:0:gemm 1:1:gemm
1232 0:0:comb
1240 1:1:comb
1632 0:1:s
1640 1:1:comb_bwd 1:1:s_bwd
2040 0:1:disp 1:1:gemm_dw
2064 1:1:gemm_dx
2088 1:1:s_dw
2440 0:1:gemm 1:1:disp_bwd
2840 0:1:comb 1:0:comb_bwd 1:0:s_bwd
3240 0:1:comb_bwd 0:1:s_bwd 1:0:gemm_dx
3256 1:0:disp_bwd 1:0:gemm_dw
3272 1:0:s_dw
3640 0:1:gemm_dx
3664 0:1:disp_bwd 0:1:gemm_dw
3688 0:1:s_dw
4064 0:0:comb_bwd 0:0:s_bwd
4464 0:0:gemm_dx
4480 0:0:disp_bwd 0:0:gemm_dw
4496 0:0:s_dw
```

**Explanation**: the `PSI` line `2 1` cuts the two layers into two chunks, one per card group (Section 3.1; see the two timelines in Section 3.2), and $P=2$; hence $V\cdot P=2\times2=4=R$. Each card group owns the 8 communication-class operations of its own layer and runs them one at a time on its single network engine, $8\times400=3200$ in all, so $\mathrm{Time}\ge3200$; the schedule above gives $\mathrm{Time}=4880$. Rule 2 draws the layer boundary at the input gradient: `0:0:s_bwd` starts at 4064, exactly when layer 1's `disp_bwd` of the same microbatch (3664, duration 400) has delivered it.  The forward boundary is equally direct: `1:1:disp` starts at 816 $=416+400$, when layer 0's combine of the same microbatch ends, and `1:0:s_bwd` starts at 2840 together with `1:0:comb_bwd`, again with nothing between them.  The deferral of the weight gradient is worth little on this instance — `0:1:gemm_dw` sits at 3664, alongside `0:1:disp_bwd` instead of in front of it — because both cards are held by their communication chains, which come to 3200 before any computation is counted.  The cut points and the placement are not optimized here, so **this output is feasible but not necessarily optimal for the instance as a whole**.

### 7.3 Sample 3 (inter-node: the trade-off in $P$)

**Input**

```text
2 2 79 10 1
2 4 20 0 1 1 1 2 0 100 3 1000000 0
8 1
12
12
```

$R=4$, two nodes.  There are $L=2$ layers, each with $T_\ell=12$ slots.

With two layers $V\le L=2$.  The full width $V\cdot P=R=4$ leaves $P=2$ ($V=2$) and $P=4$ ($V=1$), and the narrower grids do not help: $P=1$ would need $V=4$ stages and a card holding all four experts of a layer, and $V=1, P=2$ would hold two experts for two layers on one card -- both exceed $M=79$ ($4\times20=80$).  Two affordable values of $P$:

- $P=2$ (the EP group stays inside a node): $H=8$, $X=\lceil12\cdot8/2\rceil=48$, $p_{\mathrm{in}}=1$, $p_{\mathrm{out}}=0$, $x=\lceil48/10\rceil\cdot100=500$; $m_\ell=\lceil12/2\rceil=6$, `gemm`$=18$.  The `PSI` line gives each group one layer, so the edge between them is a stage boundary; crossing it costs nothing beyond the two groups' own AllToAlls.
- $P=4$ (the EP group spans nodes): $X=\lceil12\cdot8/4\rceil=24$, $p_{\mathrm{in}}=1$, $p_{\mathrm{out}}=2$, $x=\max(\lceil24/10\rceil,\lceil2\cdot24/1\rceil)\cdot100=4800$; but $m_\ell=\lceil12/4\rceil=3$, `gemm`$=9$.  Here $V=1$: all the layers are in the one chunk of the one card group, so there is no layer edge at all.

$P=4$ halves the load per rank (`gemm` drops from 18 to 9) but raises each AllToAll from 500 to 4800.  **This is the most common trade-off in this problem**: more expert parallelism always saves computation, but whether the saved computation is worth the extra inter-node traffic depends on $B_{\mathrm{in}}/B_{\mathrm{out}}$ and on the ratio of communication to computation.  Both plans fit the cap: at $P=2$ a stage owns one layer and a card holds $E/P=2$ experts (40 bytes), while at $P=4$ a card holds one expert per layer for two layers (again 40 bytes), well below $M=79$.

**Output ($P=2$, the EP group stays inside a node)**

```text
2 2
PSI
2 1
MAP
0 1 0 1
0 1 0 1
SCHEDULE
0 0:0:disp 0:0:s 1:0:s
500 0:0:gemm 1:0:disp
1000 0:0:comb 1:0:gemm
1500 0:1:disp 0:1:s 1:0:comb
2000 0:1:gemm 1:1:disp
2018 1:1:s
2500 0:1:comb 1:1:gemm
3000 0:1:s_bwd 1:1:comb
3500 0:1:comb_bwd 1:1:s_bwd
4000 0:1:gemm_dx 1:1:comb_bwd
4018 0:1:gemm_dw 0:1:s_dw
4500 0:1:disp_bwd 1:1:gemm_dx
4518 1:1:gemm_dw 1:1:s_dw
5000 0:0:comb_bwd 0:0:s_bwd 1:1:disp_bwd
5500 0:0:gemm_dx 1:0:comb_bwd
5518 0:0:gemm_dw 0:0:s_dw 1:0:s_bwd
6000 0:0:disp_bwd 1:0:gemm_dx
6018 1:0:gemm_dw 1:0:s_dw
6500 1:0:disp_bwd
```

The `PSI` line `2 1` has one cut point, $\psi_1=1$, so the two layers sit one per stage: card group 0 owns layer 0 and card group 1 owns layer 1.  This schedule gives $\mathrm{Time}=7000$.  Each group's network engine runs the eight AllToAlls of its layer (two microbatches, four per (microbatch, layer)) at 500 each, 4000 of busy time; the two groups cannot overlap those chains freely, because rule 2 ties layer 1's entry operations to layer 0's `comb` and layer 0's `s_bwd` to layer 1's `disp_bwd`, so the timetable above interleaves them and ends at 7000.

**A layer edge carries no charge of its own.**  Layer 0's combine of microbatch 0 ends at 1500, and layer 1's `disp` and `s` start exactly there; the same holds on the forward path of microbatch 1 (`1:1:disp` starts at 2000) and on each backward edge.  The difference is small because on this instance it is the network engine, and not the layer chain, that sets the pace.  A cut still buys concurrency between the two groups; what a cut costs is the serialisation rule 2 imposes, not a link between the cards.

For the same instance with $P=4$ ($V=1$, the EP group spans the two nodes), $\mathrm{Time}=76800$, about 11 times the former: each AllToAll now costs $x=4800$ and there are 16 of them (two layers, two microbatches, four communication-class operations per (microbatch, layer)), so the single network engine of the one card group is busy for $16\times4800=76800$, and the step is entirely communication-bound.  With one card group there is no layer edge, so nothing is charged between layers in that number.  Both outputs are feasible, but neither is necessarily optimal.  The schedule for $P=4$ is omitted here: the timetable above assumes $x=500$, so it is not legal at $x=4800$ and its timestamps would have to be laid out afresh.

### 7.4 Sample 4 (the same group of loads, different placements)

**Input**

```text
1 2 79 10 1
1 4 20 0 1 1 1 2 0 100 4 1000000 1000000
8 1
10 3 3 2 2
```

$M=79$ rules out $P=1$ ($4\times20=80>79$), so $P\ge2$. $E=4$, $T_0=10$, and the load is $(3,3,2,2)$. With $P=2$ there are two experts per rank (rank $r$ carries experts $2r,2r+1$). Here $p_{\mathrm{in}}=1$, $X=\lceil10\cdot8/2\rceil=40$, $x=\lceil40/10\rceil\cdot100=400$.  This is a $V=1$ plan: one card group holds the layer, so there is no layer edge.

| `MAP` | rank 0 carries | rank 1 carries | $m_0$ | `gemm` |
|------|------|------|------|------|
| `0 0 1 1` | $\{3,3\}=6$ | $\{2,2\}=4$ | 6 | 24 |
| `0 1 0 1` | $\{3,2\}=5$ | $\{3,2\}=5$ | 5 | 20 |
| `0 1 1 0` | $\{3,2\}=5$ | $\{3,2\}=5$ | 5 | 20 |

With the same group of loads and the same communication volume $x=400$, `gemm` drops from 24 to 20. **Placement is a decision**: putting the two hot experts on different ranks evens out the number of slots per rank. The more experts each rank carries, $E/P$, the more room there is for tuning.

**Output**

Take `MAP`$=$`0 1 0 1` (the better placement):

```text
1 2
PSI
1
MAP
0 1 0 1
SCHEDULE
0 0:0:disp 0:0:s 1:0:s
400 0:0:gemm 1:0:disp
800 0:0:comb 1:0:gemm
1200 0:0:s_bwd 1:0:comb
1600 0:0:comb_bwd 1:0:s_bwd
2000 0:0:gemm_dx 1:0:comb_bwd
2020 0:0:gemm_dw
2400 0:0:disp_bwd 1:0:gemm_dx
2420 1:0:gemm_dw
2440 0:0:s_dw 1:0:s_dw
2800 1:0:disp_bwd
```

This schedule gives $\mathrm{Time}=3200$.  With `MAP`$=$`0 0 1 1` instead, rank 0 carries $\{3,3\}=6$ and `gemm` rises from 20 to 24; $\mathrm{Time}$ stays at 3200, because the run is communication-bound (8 AllToAlls of 400 on the single network engine of the group), so the better placement buys compute headroom rather than time.  The shared expert is free on this instance ($F_{\mathrm{s}}=0$), so its overlap with the dispatch changes no number here.  **This output is feasible but not necessarily optimal.**

### 7.5 Sample 5 ($V=2$: the two layers land on two cards)

**Input**

```text
1 2 50 10 1
2 2 20 0 1 1 1 2 2 10 6 1000000 500000
8 2
8
8
```

$R=2$, two layers with $T=8$ each. Here $P=1$, so a rank has no EP peers: $X=\lceil T H/P\rceil=T H=128$ is never sent, $p_{\mathrm{in}}=p_{\mathrm{out}}=0$ and $x=0$, and the communication-class operations appear in the schedule with duration 0. Each rank keeps all 2 experts resident, $H=\lfloor8\cdot2/1\rfloor=16$ and $m=\lceil8/1\rceil=8$, so `gemm`$=8\cdot6=48$; `s`$=8\cdot2=16$. For the backward pass $\alpha=1$, $\beta=0.5$: `s_bwd`$=16$, `comb_bwd`$=0$, `gemm_dx`$=48$, `gemm_dw`$=24$, `disp_bwd`$=0$, `s_dw`$=8$.

The `PSI` line `2 1` puts layer 0 in the chunk of card group 0 and layer 1 in the chunk of card group 1 (Section 3.1), so the two cards hold one layer each.  The layer edge is therefore a stage boundary; with every AllToAll of length 0, only rule 2's dependency remains.

**Output**

```text
2 1
PSI
2 1
MAP
0 0
0 0
SCHEDULE
0 0:0:disp 0:0:s
16 0:0:gemm
64 0:0:comb 0:1:disp 0:1:s 1:0:disp 1:0:s
80 0:1:gemm 1:0:gemm
128 0:1:comb 0:1:comb_bwd 0:1:s_bwd 1:0:comb
144 0:1:gemm_dx
192 0:0:comb_bwd 0:0:s_bwd 0:1:disp_bwd 1:1:disp 1:1:s
208 0:0:s_dw 1:1:gemm
216 0:0:gemm_dx
256 1:1:comb 1:1:comb_bwd 1:1:s_bwd
264 0:0:disp_bwd 0:0:gemm_dw
272 1:1:gemm_dx
320 0:1:s_dw 1:0:comb_bwd 1:0:s_bwd 1:1:disp_bwd
328 1:1:s_dw
336 1:0:s_dw 1:1:gemm_dw
344 1:0:gemm_dx
360 0:1:gemm_dw
392 1:0:disp_bwd 1:0:gemm_dw
```

**Explanation**: this table writes two timelines, one per card group (Section 3.1; see Section 3.2). After the `PSI` line `2 1`, the operations of layer 0 appear only on the card of group 0 and those of layer 1 only on the card of group 1; when operations from both timelines appear on the same line, they run concurrently, each on its own card. $\mathrm{Time}=416$: layer 0's combine of microbatch 0 ends at 64 (it has duration 0), so layer 1's `disp` and `s` start at 64, and the backward edge is equally immediate.  The step has four layer edges and none of them carries a lag: rule 2 chains the two layers and the step ends at 416.  The two layers are still chained by rule 2 in both directions: layer 1's entry operations wait for layer 0's `comb` (64), and layer 0's `s_bwd` waits for layer 1's `disp_bwd` (`0:1:disp_bwd` at 192, duration 0), starting at 192 together with `0:0:comb_bwd`. That second anchor is the whole point of the relaxation: `0:0:s_bwd` starts while layer 1's weight gradient is still ahead of it — `0:1:s_dw` at 320, `1:1:gemm_dw` at 336 and `0:1:gemm_dw` at 360 — and rule 1 lets those wait for `comb_bwd` alone, so nothing downstream pays for them.  A cut buys concurrency between the cards at no extra charge, and the weight-gradient split is what stops the slower of the two cards from holding the faster one back.  **This output is feasible but not necessarily optimal for the instance as a whole**: the cut is fixed by the sample, not chosen.

### 7.6 Sample 6 (long communication, short computation)

**Input**

```text
1 4 39 10 1
2 2 20 0 1 1 1 2 2 20 1 1000000 1000000
8 2
8
8
```

$H=16$, $X=\lceil8\cdot16/2\rceil=64$, $p_{\mathrm{in}}=1$, $p_{\mathrm{out}}=0$, $x=\lceil64/10\rceil\cdot20=140$; $m=\lceil8/2\rceil=4$, `gemm`$=4\cdot1=4$; `s`$=8\cdot2=16$. The computation-class operations of one (microbatch, layer) total $16+4+16+4+4+16=60$, and the communication-class ones total $4\times140=560$ — a typical communication-dominated scenario.  The two layers sit on two card groups, so rule 2 chains layer 1's entry operations to layer 0's `comb` and layer 0's first backward steps to layer 1's `disp_bwd`; the model charges nothing else on that edge.

**Output**

```text
2 2
PSI
2 1
MAP
0 1
0 1
SCHEDULE
0 0:0:disp 0:0:s
16 1:0:s
140 0:0:gemm
144 0:0:comb
284 0:1:disp 0:1:s 1:0:disp
424 0:1:gemm 1:0:gemm
428 0:1:comb 1:0:comb
568 1:1:disp 1:1:s
584 0:1:s_bwd
708 0:1:comb_bwd 1:1:gemm
848 0:1:gemm_dx 1:1:comb
852 0:1:gemm_dw
856 0:1:s_dw
988 0:1:disp_bwd 1:1:s_bwd
1128 0:0:comb_bwd 0:0:s_bwd 1:1:comb_bwd
1268 0:0:gemm_dx 1:1:gemm_dx
1272 0:0:disp_bwd 0:0:gemm_dw 1:1:disp_bwd 1:1:gemm_dw
1276 0:0:s_dw 1:1:s_dw
1412 1:0:comb_bwd 1:0:s_bwd
1552 1:0:gemm_dx
1556 1:0:disp_bwd 1:0:gemm_dw
1560 1:0:s_dw
```

**Explanation**: $V=2$, and the `PSI` line `2 1` puts the two layers on two card groups (Section 3.1; see the two timelines in Section 3.2); with $P=2$ each card holds 1 expert per layer. $\mathrm{Time}=1696$.  The shared expert no longer waits behind anything: at 0 `0:0:disp` and `0:0:s` start together, and the 16-unit `s` hides under the 140-unit dispatch, which is where the 16 units the old serial order wasted have gone.  Rule 2 chains the two layers of a microbatch in both directions, so the two card groups' AllToAlls can no longer run side by side, and on an instance this communication-dominated it is that serial chain, not the duration of a single AllToAll, that the makespan measures.  An edge itself costs nothing: layer 1's entry operations start at 284, exactly when layer 0's combine of the same microbatch ends, and layer 0's `s_bwd` starts at 1128, exactly when layer 1's `disp_bwd` (988, duration 140) has delivered.  Rule 1 decides where the weight gradient sits: for (microbatch 0, layer 1) the `comb_bwd` at 708 ends at 848, and `gemm_dw` and `s_dw` run at 852 and 856, as soon as the compute engine is free, while the dispatch `disp_bwd` only follows at 988; layer 0's `s_bwd` is anchored on that dispatch, so it pays for the 140-unit AllToAll and not for the weight gradient.  Rule 1 mirrors the forward pass, so the backward overlap is visible too: at 1128 `0:0:s_bwd` (16 units) starts together with `0:0:comb_bwd` (140 units), exactly as `0:0:s` starts together with `0:0:disp` at time 0.  The shared-expert input gradient hides under the combine backward, `disp_bwd` waits for the longer of the two, and that 16-unit head start pulls the whole tail in: `1:0` repeats the pattern at 1412, and the last dispatch ends at 1696.  $P=1$ is ruled out by memory in this example: $M=39$, while $P=1$ would require each card to hold 4 experts across two layers ($4\times20=80>39$). **This output is feasible but not necessarily optimal for the instance as a whole.**

---

## 8. Notes

This problem does not require an exactly optimal solution, and no official optimal values are provided either. The checker performs only the forward simulation of Section 4 and ranks according to it (see Section 5); any method that can produce a smaller $\mathrm{Time}$ within the time budget is valid.

---

## 9. References

The modeling in this problem draws on the following works. **They provide background and ideas only; for the concrete formulas Section 4 is authoritative throughout**, and quite a few of those formulas are simplifications or rewrites of these works.

1. DeepSeek-AI. *DeepSeek-V3 Technical Report.* arXiv:2412.19437, 2024. — the division of a layer into segments (attention / dispatch / MLP / combine), DualPipe's arrangement and parameter co-location, and the two-level bandwidth of inter-node communication.
2. P. Qi, X. Wan, G. Huang, M. Lin. *Zero Bubble Pipeline Parallelism.* arXiv:2401.10241. — the idea of splitting the backward pass into an input-gradient part and a weight-gradient part and using the weight gradient to fill bubbles, and the practice of searching for schedules with integer linear programming.
3. A. Harlap, D. Narayanan, A. Phanishayee, V. Seshadri, N. Devanur, G. Ganger, P. Gibbons. *PipeDream: Fast and Efficient Pipeline Parallel DNN Training.* arXiv:1806.03377, 2018; SOSP 2019. — the 1F1B arrangement.
4. S. Zheng, X. Zheng, L. Chang, J. Zhai. *UniEP: Unified Expert-Parallel MoE MegaKernel for LLM Training.* arXiv:2604.19241. — the practice of fusing AllToAll and GroupGEMM into the same kernel.

The ten operations of Section 4, the duration formula of each operation, the way the three memory blocks are divided, and the interface conventions of `PSI` / `MAP` / `SCHEDULE` are all model definitions of this problem itself and are not given by the works cited above.
