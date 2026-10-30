#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Grader (evaluator) for the problem in problem-statement.md (the tracked English
statement; the Chinese source lives outside the repository).

Usage
-----
    python3 grader.py <input_file> <output_file>
    python3 grader.py --self-test

Prints the score (``Time``, an integer) on stdout, or ``INVALID: <reason>`` if
the submitted mapping violates section 4.4 / 4.7 of the statement.

The grader is a *forward simulator only*: it never searches.  It

  1. parses the instance (section 2) and the mapping (section 3), rejecting a
     schedule whose timestamps decrease (3.2 constraint 1),
  2. checks that every (microbatch, layer, operation) triple appears exactly
     once (3.2),
  3. derives each operation's duration from sections 4.1 / 4.3 / 4.4,
  4. checks the dependency and resource rules of section 4.2,
  5. computes the two buffer peaks of section 4.6 and checks the HBM limit,
  6. returns the makespan of section 4.5.

Chunking (VPP)
--------------
`K` is declared as the first field of the `PSI` line, which then carries the
`K-1` cut points on that same line: ``K <psi_1> ... <psi_{K-1}>``.  With
`K = 1` (legal only when `V = 1`) the line is the bare ``1``.  The cut count
must be exactly `K-1`, and 4.7 rule 2 admits only `K = V` (one chunk per card
group, the default model) or `K = 2V` (two chunks per card group, the VPP
model); any other count is illegal.  Chunk `k` owns the layers
`[psi_k, psi_{k+1})` with the implicit `psi_0 = 0` and `psi_K = L`, and belongs
to card group

    g(k) = k            for k <  V      (the "early" chunk)
    g(k) = 2V-1-k       for k >= V      (the mirror of chunk 2V-1-k)

Card groups, not chunks, own the engines: with `K = 2V` the two chunks of a group
share its one compute engine and its one network engine, so their operations
contend (4.2 rule 3), and `M_exp` counts every layer of every chunk of the group
(4.6).  The pipeline dependency of 4.2 rule 2 is stated on *layers*, not on
chunks: the activation of a microbatch flows layer to layer, so the dispatch of
layer `l` (and the layer's shared expert, which needs the same incoming
activation) waits for the `comb` of layer `l-1`, and the gradient flows back the
same way, so both first backward steps of layer `l` -- `s_bwd` and `comb_bwd`
-- wait for the `disp_bwd` that delivers the input gradient of layer `l+1`.
Both hold for every chunking, including the layers that share one chunk; the
layer-order statement implies the chunk-boundary barrier and says strictly
more, so no chunk-level version remains.

The backward pass of 4.2 rule 1 is the exact mirror of the forward pass.
The *routed* chain is `comb_bwd -> gemm_dx -> disp_bwd`; the shared expert's
input gradient `s_bwd` is not on it -- it is released by the incoming gradient,
the same edge that releases `comb_bwd`, and only has to finish before
`disp_bwd`, whose gradient addition includes the shared-expert part, so it can
hide under the combine backward.  The two *weight gradient* steps `gemm_dw` and
`s_dw` need only the incoming gradient, so each waits for `comb_bwd` alone and
may then be placed anywhere later in that layer's backward pass.  Deferring
them into a bubble is therefore legal, and rule 2 no longer charges the
deferral to the neighbouring layer, whose first backward steps are anchored on
`disp_bwd`.  The forward pass is not one chain either: `disp -> gemm -> comb` is
the routed-expert chain, and the shared expert `s` runs beside the dispatch --
it needs only the layer's incoming activation and has to finish before `comb`.

Every place where the statement leaves a choice open is marked ``NOTE``.
"""

import collections
import math
import os
import sys

# --------------------------------------------------------------------------
# the idle-cards switch (on by default: the shipped rule is V*P <= R)
# --------------------------------------------------------------------------
# Section 4.7 rule 1 of the statement requires V*P <= R.  This module-level
# switch selects that rule (on) or the older exact-width rule V*P = R (off):
# the grid may use only the first V*P cards,
# and the remaining R - V*P cards are idle (no operations, no memory charge).
# The embedding 3.1, q = v*P + p, already addresses only the first V*P cards,
# so no other part of the model changes.
#
# It is deliberately a plain module variable so an experiment can flip it at
# run time (``grader.ALLOW_IDLE = True``); the environment variable is read
# once at import so a multiprocessing child gets the same setting.
# `greedy_solver.legal_grid` reads this flag live and is the single place every
# solver (and `certify.py` / `classic_solvers.py`) gets its grid space from.
ALLOW_IDLE = os.environ.get('ALLOW_IDLE', '1').strip().lower() in (
    '1', 'true', 'yes', 'on')


# --------------------------------------------------------------------------
# section 4.1: the ten operations
# --------------------------------------------------------------------------
FWD = ('s', 'disp', 'gemm', 'comb')
BWD = ('s_bwd', 'comb_bwd', 'gemm_dx', 'gemm_dw', 'disp_bwd', 's_dw')
OPS = FWD + BWD
# 4.2 rule 1, the backward pass, now the mirror of the forward pass.  The
# *routed* backward chain is `comb_bwd -> gemm_dx -> disp_bwd`; the shared
# expert's input gradient `s_bwd` is not on it: it is released by the incoming
# gradient -- the same edge that releases `comb_bwd` -- and only has to finish
# before `disp_bwd`, whose gradient addition includes the shared-expert part.
# The two weight-gradient steps hang off `comb_bwd` and are free after it.
# `BWD` above keeps the order of the 4.1 table, which is only the canonical
# listing order, not the dependency order; `BWD_ORDER` is one legal serial order
# (the one a strictly serial schedule uses).
BWD_CHAIN = ('comb_bwd', 'gemm_dx', 'disp_bwd')
BWD_SHARED = ('s_bwd',)
BWD_ORDER = ('s_bwd', 'comb_bwd', 'gemm_dx', 'gemm_dw', 'disp_bwd', 's_dw')
BWD_IN_GRAD = ('gemm_dw', 's_dw')
ENGINE = {
    's': 'C', 'disp': 'N', 'gemm': 'C', 'comb': 'N',
    's_bwd': 'C', 'comb_bwd': 'N', 'gemm_dx': 'C', 'gemm_dw': 'C',
    'disp_bwd': 'N', 's_dw': 'C',
}
# operations that occupy the communication buffer (section 4.6, M_ovl)
COMM_OPS = ('disp', 'comb', 'comb_bwd', 'disp_bwd')



class Invalid(Exception):
    """The submitted mapping is not legal."""


def cdiv(a, b):
    return -(-a // b) if b > 0 else 0


def _round_half_even(x):
    return int(round(x))          # Python's round() is half-to-even


# --------------------------------------------------------------------------
# instance (section 2)
# --------------------------------------------------------------------------
class Instance(object):
    __slots__ = ('N', 'S', 'M', 'Bin', 'Bout', 'L', 'E', 'Z', 'Zs', 'U',
                 'Uact', 'k', 'nmb', 'Fs', 'Fio', 'Fin', 'ax', 'bx', 'd', 'b',
                 'layers')


def parse_instance(text):
    rows = [ln.split() for ln in text.splitlines()]
    rows = [r for r in rows if r]
    if len(rows) < 3:
        raise Invalid('input: at least 3 header lines expected')
    inst = Instance()
    if len(rows[0]) != 5:
        raise Invalid('input: line 1 must be "N S M B_in B_out" (5 fields), '
                      'got %d (section 2)' % len(rows[0]))
    try:
        (inst.N, inst.S, inst.M, inst.Bin, inst.Bout) = [int(x) for x in rows[0]]
        (inst.L, inst.E, inst.Z, inst.Zs, inst.U, inst.Uact, inst.k, inst.nmb,
         inst.Fs, inst.Fio, inst.Fin, inst.ax, inst.bx) = [int(x) for x in rows[1]]
        inst.d, inst.b = [int(x) for x in rows[2]]
    except ValueError:
        raise Invalid('input: bad integer in the header')
    if inst.N * inst.S < 1:
        raise Invalid('input: no cards')
    if inst.nmb % 2:
        raise Invalid('input: n_mb must be even (4.7 rule 5)')
    if inst.E < 1 or inst.k < 1 or inst.d < 1 or inst.L < 1:
        raise Invalid('input: L, E, k, d must be >= 1')
    if len(rows) < 3 + inst.L:
        raise Invalid('input: expected %d layer lines, found %d'
                      % (inst.L, len(rows) - 3))
    inst.layers = []
    for i in range(inst.L):
        try:
            vals = [int(x) for x in rows[3 + i]]
        except ValueError:
            raise Invalid('input: bad integer on layer line %d' % i)
        T = vals[0]
        if len(vals) == 1:
            loads = None
        elif len(vals) == inst.E + 1:
            loads = vals[1:]
            if sum(loads) != T:
                raise Invalid('input: layer %d loads sum to %d but T=%d'
                              % (i, sum(loads), T))
        else:
            raise Invalid('input: layer %d has %d fields (want 1 or E+1=%d)'
                          % (i, len(vals), inst.E + 1))
        inst.layers.append((T, loads))
    return inst


# --------------------------------------------------------------------------
# mapping (section 3)
# --------------------------------------------------------------------------
class Mapping(object):
    __slots__ = ('V', 'P', 'D', 'K', 'psi', 'map', 'sched')


def parse_mapping(text, inst):
    rows = [ln.split() for ln in text.splitlines()]
    rows = [r for r in rows if r]
    if not rows:
        raise Invalid('output: empty')
    m = Mapping()
    if len(rows[0]) != 2:
        raise Invalid('output: first line must be "V P", got %d fields'
                      % len(rows[0]))
    try:
        m.V, m.P = [int(x) for x in rows[0]]
    except ValueError:
        raise Invalid('output: bad integer on the first line')
    m.D = 1

    i = 1
    if i >= len(rows) or rows[i] != ['PSI']:
        raise Invalid('output: expected a PSI line')
    i += 1
    # NOTE: the PSI line declares the chunk count first and then the K-1 cut
    # points, all on that one line.  K = 1 is written as a bare "1" and has no
    # cut points.  4.7 rule 2 fixes K to V or 2V and the cut count to K-1.
    if i >= len(rows) or rows[i] == ['MAP']:
        raise Invalid('output: expected the chunk count K on the PSI line '
                      '(4.7 rule 2)')
    try:
        m.K = int(rows[i][0])
    except ValueError:
        raise Invalid('output: bad chunk count %r on the PSI line (4.7 rule 2)'
                      % rows[i][0])
    try:
        m.psi = [int(x) for x in rows[i][1:]]
    except ValueError:
        raise Invalid('output: bad cut point %r' % rows[i])
    if m.K != m.V and m.K != 2 * m.V:
        raise Invalid('output: K = %d declared but V = %d, so K must be %d or '
                      '%d (4.7 rule 2)' % (m.K, m.V, m.V, 2 * m.V))
    n = len(m.psi)
    if n != m.K - 1:
        raise Invalid('output: K = %d declared but %d cut point%s %s '
                      '(4.7 rule 2)'
                      % (m.K, n, '' if n == 1 else 's',
                         'follows' if n == 1 else 'follow'))
    i += 1

    if i >= len(rows) or rows[i] != ['MAP']:
        raise Invalid('output: expected a MAP line')
    i += 1
    m.map = []
    for _ in range(inst.L):
        if i >= len(rows):
            raise Invalid('output: MAP needs %d rows' % inst.L)
        try:
            m.map.append([int(x) for x in rows[i]])
        except ValueError:
            raise Invalid('output: bad integer in MAP')
        i += 1

    if i >= len(rows) or rows[i] != ['SCHEDULE']:
        raise Invalid('output: expected a SCHEDULE line')
    i += 1
    m.sched = []
    prev_t = None
    for ln in rows[i:]:
        if ln[0].startswith('...'):          # NOTE: an elided excerpt marker
            continue
        if len(ln) < 2:
            raise Invalid('output: schedule entry %r has no operation' % (ln,))
        try:
            t = int(ln[0])
        except ValueError:
            raise Invalid('output: bad timestamp %r' % ln[0])
        # 3.2 constraint 1: t must be non-decreasing, so the lines are in
        # chronological order.  Equal times are allowed (several operations can
        # start on one instant), a decrease is not.
        if prev_t is not None and t < prev_t:
            raise Invalid('output: schedule timestamps must be non-decreasing '
                          '(3.2 constraint 1): t=%d follows t=%d'
                          % (t, prev_t))
        prev_t = t
        for item in ln[1:]:
            parts = item.split(':')
            if len(parts) != 3:
                raise Invalid('output: bad operation %r (want mb:layer:op)' % item)
            try:
                mb, layer = int(parts[0]), int(parts[1])
            except ValueError:
                raise Invalid('output: bad operation %r' % item)
            if parts[2] not in OPS:
                raise Invalid('output: unknown operation %r (the ten operations of 4.1, '
                              'each appearing once per microbatch and layer)' % parts[2])
            op = parts[2]
            m.sched.append((t, mb, layer, op, item))
    return m


# --------------------------------------------------------------------------
# geometry, durations (sections 4.3, 4.4)
# --------------------------------------------------------------------------
def balanced_loads(T, E):
    """NOTE: when a layer line is balanced we spread T over E experts evenly."""
    return [(T // E) + (1 if e < T % E else 0) for e in range(E)]


def layer_geometry(inst, m, l):
    T, loads = inst.layers[l]
    if loads is None:
        loads = balanced_loads(T, inst.E)
    # one pass over the experts; scanning per rank instead is O(E*P) per layer and
    # dominates everything else at realistic E
    per_rank = [0] * m.P
    row = m.map[l]
    for e in range(inst.E):
        per_rank[row[e]] += loads[e]
    ml = max(per_rank)
    H = (inst.d * inst.b) // inst.k
    # X is the per-peer volume: the layer's T*H bytes split evenly over the P
    # ranks, i.e. the T*H*(P-1)/P bytes of group traffic split over the P-1 peers.
    X = cdiv(T * H, m.P)
    # embedding q = v*P + p ; EP peers of p=0 are q = 0..P-1
    p_in = sum(1 for q in range(m.P) if q != 0 and q // inst.S == 0)
    p_out = m.P - 1 - p_in
    x = max(cdiv(p_in * X, inst.Bin), cdiv(p_out * X, inst.Bout)) * inst.Fio
    return dict(T=T, loads=loads, per_rank=per_rank, ml=ml, H=H, X=X,
                p_in=p_in, p_out=p_out, x=x)


def op_preds(L, l, op):
    """`[(layer, operation, rule)]`: what one operation of layer `l` depends on.

    This is 4.2 rules 1 and 2 in one place, so a solver's graph cannot drift from
    the checker's:

    * rule 1 -- the *routed-expert* chain `disp -> gemm -> comb`; the shared
      expert `s`, which depends only on the layer's own input (the same edge that
      releases `disp`) and has to finish before that layer's `comb`; the *routed
      backward chain* `comb_bwd -> gemm_dx -> disp_bwd`; the shared expert's
      input gradient `s_bwd`, released by the incoming gradient (the same edge
      that releases `comb_bwd`) and required to finish before `disp_bwd`, whose
      gradient addition includes the shared-expert part; the dependence of both
      first backward steps on their own layer's `comb`; and the two
      *weight-gradient steps* `gemm_dw` and `s_dw`, each of which follows
      `comb_bwd` and nothing else in its layer, so that deferring them costs no
      other operation anything;
    * rule 2 -- `s` and `disp` of layer `l >= 1` follow the `comb` of layer `l-1`,
      and both first backward steps of layer `l` -- `s_bwd` and `comb_bwd` --
      follow the `disp_bwd` of layer `l+1`, the step that delivers the input
      gradient to the token owners.  The anchor is not `s_dw`: layer `l`
      consumes the gradient only, and the weight gradient the next layer still
      owes is consumed by nobody downstream.
    """
    out = []
    if op == 'disp':
        if l >= 1:
            out.append((l - 1, 'comb', '2'))
    elif op == 's':
        # the shared expert needs the same incoming activation as the dispatch;
        # 4.2 rule 1 no longer puts it before `disp`, it only has to beat `comb`
        if l >= 1:
            out.append((l - 1, 'comb', '2'))
    elif op == 'gemm':
        out.append((l, 'disp', '1'))
    elif op == 'comb':
        out.append((l, 'gemm', '1'))
        out.append((l, 's', '1'))
    elif op == 'comb_bwd':
        # rule 1: the backward pass begins only after the forward pass ends; the
        # incoming gradient (rule 2) releases this step as it releases `s_bwd`
        out.append((l, 'comb', '1'))
        if l + 1 < L:
            out.append((l + 1, 'disp_bwd', '2'))
    elif op == 's_bwd':
        # the mirror of `s`: same incoming gradient as `comb_bwd`, own `comb` as
        # the forward-finished barrier, and no other dependency; `disp_bwd`
        # waits for it below
        out.append((l, 'comb', '1'))
        if l + 1 < L:
            out.append((l + 1, 'disp_bwd', '2'))
    if op in BWD_CHAIN and BWD_CHAIN.index(op) > 0:
        out.append((l, BWD_CHAIN[BWD_CHAIN.index(op) - 1], '1'))
    if op == 'disp_bwd':
        out.append((l, 's_bwd', '1'))
    if op in BWD_IN_GRAD:
        out.append((l, 'comb_bwd', '1'))
    return out


def durations(inst, m, l):
    g = layer_geometry(inst, m, l)
    a, b = inst.ax / 1e6, inst.bx / 1e6
    s = g['T'] * inst.Fs
    gemm = g['ml'] * inst.Fin
    return {
        's': s,
        'disp': g['x'],
        'gemm': gemm,
        'comb': g['x'],
        's_bwd': math.ceil(a * s),
        'comb_bwd': math.ceil(a * g['x']),
        'gemm_dx': math.ceil(a * gemm),
        'gemm_dw': math.ceil(a * b * gemm),
        'disp_bwd': math.ceil(a * g['x']),
        's_dw': math.ceil(a * b * s),
    }


# --------------------------------------------------------------------------
# legality (section 4.7)
# --------------------------------------------------------------------------
def chunk_count(m, inst):
    """``K``, the number of chunks, checked against 4.7 rule 2.

    ``K`` is declared as the first field of the ``PSI`` line, which then carries
    exactly ``K-1`` cut points; it has to be either ``V`` (one chunk per card
    group) or ``2V`` (two).  A mapping built in Python without a declared ``K``
    (``parse_mapping`` always sets one) falls back to ``len(PSI) + 1``, the value
    its cut points express on their own.
    """
    K = getattr(m, 'K', None)
    if K is None:
        K = len(m.psi) + 1
    if K != m.V and K != 2 * m.V:
        raise Invalid('output: K = %d declared but V = %d, so K must be %d or '
                      '%d (4.7 rule 2)' % (K, m.V, m.V, 2 * m.V))
    return K


def group_of_chunk(m, k):
    """The card group that owns chunk ``k`` (3.1, the mirror pairing).

    ``g(k) = k`` for the first ``V`` chunks and ``g(k) = 2V-1-k`` for the rest, so
    with ``K = 2V`` group ``g`` owns the chunks ``g`` and ``2V-1-g``.
    """
    return k if k < m.V else 2 * m.V - 1 - k


def chunk_index(m, inst):
    """``(chunk_of_layer, bounds)`` with ``bounds = [0, psi_1, ..., psi_{K-1}, L]``.

    The name ``stage_index`` is kept as an alias: with ``K = V`` a chunk *is* the
    stage of the earlier statement, and every caller outside this module uses it
    that way.
    """
    K = chunk_count(m, inst)
    bounds = [0] + list(m.psi) + [inst.L]
    if len(bounds) != K + 1:
        raise Invalid('output: PSI length does not match K (4.7 rule 2)')
    # every written cut point has to sit strictly inside (0, L): that is what
    # makes the K chunks cover 0..L with a non-empty first and last chunk
    for p in bounds[1:-1]:
        if not (0 < p < inst.L):
            raise Invalid('output: cut point %d is outside (0, L=%d), so the cuts do '
                          'not cover 0..L (4.7 rule 2)' % (p, inst.L))
    for i in range(len(bounds) - 1):
        if bounds[i] >= bounds[i + 1]:
            raise Invalid('output: cut points must be strictly increasing (4.7 rule 2)')
    if bounds[-1] != inst.L:
        raise Invalid('output: cut points must end at L=%d (4.7 rule 2)' % inst.L)
    st = {}
    for k in range(K):
        for l in range(bounds[k], bounds[k + 1]):
            st[l] = k
    return st, bounds


# with K = V this is exactly the stage index of the earlier statement
stage_index = chunk_index


def group_index(m, inst):
    """``group_of_layer[l]``: the card group that holds layer ``l`` (3.1)."""
    st, bounds = chunk_index(m, inst)
    K = len(bounds) - 1
    grp = [group_of_chunk(m, k) for k in range(K)]
    return [grp[st[l]] for l in range(inst.L)]


def check_legality(m, inst):
    grid_arithmetic(inst, m.V, m.P)
    if len(m.map) != inst.L:
        raise Invalid('output: MAP needs %d rows' % inst.L)
    per = inst.E // m.P
    for l, row in enumerate(m.map):
        if len(row) != inst.E:
            raise Invalid('output: MAP row %d has %d entries, want E=%d'
                          % (l, len(row), inst.E))
        for e, r in enumerate(row):
            if not (0 <= r < m.P):
                raise Invalid('output: MAP[%d][%d]=%d not in [0,P) (4.7 rule 3)'
                              % (l, e, r))
        cnt = collections.Counter(row)
        for r in range(m.P):
            if cnt[r] != per:
                raise Invalid('output: MAP row %d: rank %d holds %d experts, want %d '
                              '(4.7 rule 3)' % (l, r, cnt[r], per))


def grid_arithmetic(inst, V, P):
    """The arithmetic half of 4.7 rule 1, shared by ``check_legality``/``simulate``.

    With the idle switch off this is exactly the shipped rule ``V*P = R``.  With
    it on, it is ``V*P <= R``: the grid occupies the first ``V*P`` cards and the
    rest idle.  The other two conditions (``P | E``, ``P | S`` or ``S | P``) are
    unchanged, and ``V >= 1`` still holds.  ``V <= L`` is enforced by the
    cut-point rules, not here.
    """
    R = inst.N * inst.S
    if V < 1 or P < 1:
        raise Invalid('output: V and P must both be >= 1 (4.7 rule 1)')
    if ALLOW_IDLE:
        if V * P > R:
            raise Invalid('output: V*P = %d > R = %d (4.7 rule 1)'
                          % (V * P, R))
    elif V * P != R:
        raise Invalid('output: V*P = %d, but R = %d (4.7 rule 1)'
                      % (V * P, R))
    if inst.E % P:
        raise Invalid('output: P=%d must divide E=%d (4.7 rule 1)' % (P, inst.E))
    if not (inst.S % P == 0 or P % inst.S == 0):
        raise Invalid('output: need P|S or S|P, got P=%d S=%d (4.7 rule 1)'
                      % (P, inst.S))


# --------------------------------------------------------------------------
# simulation (sections 4.2, 4.5, 4.6)
# --------------------------------------------------------------------------
def simulate(inst, m):
    # cheap arithmetic constraints first, so the error message is the specific one
    grid_arithmetic(inst, m.V, m.P)
    st, bounds = stage_index(m, inst)          # st[l] = chunk of layer l
    grp = group_index(m, inst)                 # grp[l] = card group of layer l
    check_legality(m, inst)

    D = {l: durations(inst, m, l) for l in range(inst.L)}

    if not m.sched:
        raise Invalid('output: empty SCHEDULE')
    for t, mb, l, op, raw in m.sched:
        if t < 0:
            raise Invalid('output: negative timestamp')
        if not (0 <= l < inst.L):
            raise Invalid('output: layer %d out of range' % l)
        if not (0 <= mb < inst.nmb):
            raise Invalid('output: microbatch %d out of range' % mb)

    # 3.2: every (microbatch, layer, operation) triple appears exactly once.
    # The range checks above already bound mb and layer and parse_mapping already
    # restricted op to OPS, so the required universe is exactly nmb * L * 10
    # triples.  Presence is structural: a zero-duration operation is required
    # just like any other and must not be dropped.
    seen = {}
    for t, mb, l, op, raw in m.sched:
        k = (mb, l, op)
        if k in seen:
            raise Invalid('output: duplicate operation %d:%d:%s at t=%d '
                          '(first at t=%d); every (microbatch, layer, '
                          'operation) triple must appear exactly once (3.2)'
                          % (mb, l, op, t, seen[k]))
        seen[k] = t
    required = inst.nmb * inst.L * len(OPS)
    if len(seen) != required:
        # every seen triple is inside the required universe (mb/layer were
        # range-checked and op came from OPS), so the shortfall is the count
        n_missing = required - len(seen)
        first = []
        for mb in range(inst.nmb):
            for l in range(inst.L):
                for op in OPS:
                    if (mb, l, op) not in seen:
                        first.append('%d:%d:%s' % (mb, l, op))
                        if len(first) == 8:
                            break
                if len(first) == 8:
                    break
            if len(first) == 8:
                break
        shown = ', '.join(first) + (' ...' if n_missing > 8 else '')
        raise Invalid('output: schedule is incomplete: %d of the %d required '
                      '(microbatch, layer, operation) triples are missing '
                      '(3.2); first missing: %s' % (n_missing, required, shown))

    # earliest start time of each (mb, layer, op).  Uniqueness above makes these
    # exact starts and ends; min/max are kept so the representation cannot
    # silently change if the uniqueness rule is ever relaxed.
    first_start = {}
    last_end = {}
    order = []
    for t, mb, l, op, raw in m.sched:
        k = (mb, l, op)
        first_start[k] = min(first_start.get(k, t), t)
        last_end[k] = max(last_end.get(k, t + D[l][op]), t + D[l][op])
        order.append((t, mb, l, op, raw))

    # rule 1 + 2 + 4: dependencies
    # NOTE: checked against the whole submission; parse_mapping has already
    # enforced the non-decreasing line order of 3.2 constraint 1, so the file
    # order and the dependency order cannot disagree about chronology.
    # NOTE: 4.2 rule 2 is the *layer-order* statement, and it holds whatever the
    # chunking is: the activation of a microbatch flows layer to layer, so both
    # entry operations of layer l -- the shared expert `s` and the dispatch
    # `disp` -- wait for the combine of layer l-1 (l >= 1); the gradient flows
    # the other way, so both first backward steps of layer l -- `s_bwd` and
    # `comb_bwd` -- wait for the `disp_bwd` of layer l+1 (l <= L-2).  It implies
    # the old chunk-boundary barrier.
    # NOTE: 4.2 rule 1's forward half is the routed-expert chain
    # `disp -> gemm -> comb` plus the shared expert `s`, which needs only the
    # layer's incoming activation and has to finish before `comb`: it can run
    # under the dispatch, which is the overlap the model is built around.  The
    # backward half is its mirror: the routed chain `comb_bwd -> gemm_dx ->
    # disp_bwd` plus the shared expert's input gradient `s_bwd`, which is
    # released by the same incoming gradient as `comb_bwd` and has to finish
    # before `disp_bwd`: it can run under the combine backward.  The two
    # weight-gradient steps of BWD_IN_GRAD wait for `comb_bwd` alone, so a
    # deferred `gemm_dw`/`s_dw` is legal and costs the neighbouring layer
    # nothing, because rule 2 anchors on `disp_bwd`.
    # `op_preds` below is the single statement of both rules, and the solvers
    # build their graphs from it, so a rule cannot drift from its implementers.
    for t, mb, l, op, raw in order:
        for dl, dop, rule in op_preds(inst.L, l, op):
            k = (mb, dl, dop)
            if k not in last_end:
                raise Invalid('output: %d:%d:%s needs %d:%d:%s, which is missing '
                              '(4.2 rule %s)'
                              % (mb, l, op, mb, dl, dop, rule))
            if t < last_end[k]:
                raise Invalid('output: %d:%d:%s starts at %d but %d:%d:%s ends at %d '
                              '(4.2 rule %s/4)'
                              % (mb, l, op, t, mb, dl, dop, last_end[k], rule))

    # rule 3: per card, per engine, at most one operation at a time.  The engine
    # belongs to the *card group* the layer's chunk sits on: with K=2V the two
    # chunks of a group contend for the same two engines (4.2 rule 3).
    ev = collections.defaultdict(list)
    for t, mb, l, op, raw in order:
        d = D[l][op]
        if d <= 0:
            continue
        key = (grp[l], ENGINE[op])
        ev[key].append((t, +1, (mb, l, op, raw)))
        ev[key].append((t + d, -1, (mb, l, op, raw)))
    for key, events in ev.items():
        events.sort(key=lambda z: (z[0], z[1]))       # ends (-1) before starts (+1)
        cur = 0
        for t, delta, who in events:
            cur += delta
            if cur > 1:
                raise Invalid('output: card group %d runs two %s operations at once '
                              'at t=%d (%s) (4.2 rule 3)'
                              % (key[0], 'compute' if key[1] == 'C' else 'network',
                                 t, who))

    makespan = max(t + D[l][op] for t, mb, l, op, raw in order)

    # ---------------- memory (section 4.6) ----------------
    # NOTE: the peaks are computed from an event sweep rather than by scanning
    # every timestamp against every operation, so large instances stay cheap.
    # NOTE: the residency of card group q is the sum over *every chunk it owns*,
    # so with K=2V it covers both g and 2V-1-g.
    geo = {l: layer_geometry(inst, m, l) for l in range(inst.L)}
    mem = {}
    for v in range(m.V):
        layers_v = [l for l in range(inst.L) if grp[l] == v]
        exp = sum(inst.E // m.P * inst.Z + inst.Zs for l in layers_v)

        # peak concurrent communication buffers on this card group.  A buffer is
        # held on [start, end); at equal timestamps the starts are processed
        # before the ends, so an operation that ends exactly when the next begins
        # counts as two (4.6: the finished buffer is released while the next is
        # being filled).
        starts = collections.defaultdict(int)
        ends = collections.defaultdict(int)
        for t0, mb, l, op, raw in order:
            if grp[l] != v or op not in COMM_OPS or D[l][op] <= 0:
                continue
            starts[t0] += 1
            ends[t0 + D[l][op]] += 1
        cur = 0
        ovl = 0
        for tt in sorted(set(starts) | set(ends)):
            cur += starts.get(tt, 0)
            if cur > ovl:
                ovl = cur
            cur -= ends.get(tt, 0)

        # peak live activations: forward finished, backward not started
        pts = set()
        fwd_end = {}
        bwd_start = {}
        for mb in range(inst.nmb):
            for l in layers_v:
                k = (mb, l, 'comb')
                if k in last_end:
                    fwd_end[(mb, l)] = last_end[k]
                    pts.add(last_end[k])
                k = (mb, l, 's_bwd')
                if k in first_start:
                    bwd_start[(mb, l)] = first_start[k]
                    pts.add(first_start[k])
        # an activation is live from the moment its forward finishes (its
        # backward cannot have started yet) until its backward starts
        ev2 = collections.defaultdict(int)
        for key, fe in fwd_end.items():
            ev2[fe] += 1
            bs = bwd_start.get(key)
            if bs is not None:
                ev2[bs] -= 1
        # NOTE: a forward that ends exactly when a backward starts still holds
        # its activation at that instant, so at equal timestamps the arrivals
        # are counted before the departures.
        arr = collections.defaultdict(int)
        dep = collections.defaultdict(int)
        for key, fe in fwd_end.items():
            arr[fe] += 1
            bs = bwd_start.get(key)
            if bs is not None:
                dep[bs] += 1
        cur = 0
        act = 0
        for tt in sorted(set(arr) | set(dep)):
            cur += arr.get(tt, 0)
            if cur > act:
                act = cur
            cur -= dep.get(tt, 0)
        mem[v] = exp + inst.U * ovl + inst.Uact * act
    worst = max(mem.values())
    if worst > inst.M:
        raise Invalid('output: HBM limit exceeded: %d > M=%d (per card group: %s) (4.6)'
                      % (worst, inst.M, {k: v for k, v in sorted(mem.items())}))
    return makespan, dict(makespan=makespan, mem=mem, stage=st, chunk=st,
                          group=grp, bounds=bounds, dur=D, geo=geo)


def grade(input_text, output_text):
    inst = parse_instance(input_text)
    m = parse_mapping(output_text, inst)
    return simulate(inst, m)


def main(argv):
    if len(argv) == 2 and argv[1] == '--self-test':
        ok = True
        for name, inp, out, exp in SELF_TEST:
            try:
                got, info = grade(inp, out)
                if exp == 'INVALID':
                    ok = False
                    print('BAD %-45s accepted (Time=%d), expected rejection'
                          % (name, got))
                else:
                    good = (got == exp)
                    ok &= good
                    print('%s %-45s Time=%-6s expected=%-6s mem=%s'
                          % ('OK ' if good else 'BAD', name, got, exp,
                             info['mem']))
            except Invalid as e:
                if exp == 'INVALID':
                    print('OK  %-45s rejected: %s' % (name, str(e)[:40]))
                else:
                    ok = False
                    print('BAD %-45s %s' % (name, e))
        return 0 if ok else 1
    if len(argv) != 3:
        sys.stderr.write(__doc__)
        return 2
    with open(argv[1], encoding='utf-8') as f:
        inp = f.read()
    with open(argv[2], encoding='utf-8') as f:
        out = f.read()
    try:
        makespan, _ = grade(inp, out)
    except Invalid as e:
        print('INVALID: %s' % e)
        return 1
    print(makespan)
    return 0


SELF_TEST = [
    # sample 7.1's instance with a roomier cap, but only microbatch 0: this was
    # the old one-microbatch shortcut.  4.7 rule 5 forces n_mb to be even, so a
    # 2-microbatch instance cannot be served by one microbatch's operations; the
    # schedule omits 16 of the 20 triples and 3.2 requires it to be rejected.
    ('illegal: one microbatch of a two-microbatch instance',
     '\n'.join(['1 2 80 10 1',
                 '1 2 20 0 1 1 1 2 2 10 6 1000000 1000000',
                 '8 2', '8', '']),
     '\n'.join(['1 2', 'PSI', '1', 'MAP', '0 1', 'SCHEDULE',
                 '0 0:0:s', '16 0:0:disp', '86 0:0:gemm', '110 0:0:comb',
                 '']),
     'INVALID'),
    # the same instance, both microbatches, fully serial: 20 triples, one
    # operation at a time, the second microbatch after the first
    ('sample 7.1, fully serial (both microbatches)',
     '\n'.join(['1 2 80 10 1',
                 '1 2 20 0 1 1 1 2 2 10 6 1000000 1000000',
                 '8 2', '8', '']),
     '\n'.join(['1 2', 'PSI', '1', 'MAP', '0 1', 'SCHEDULE',
                 '0 0:0:s', '16 0:0:disp', '86 0:0:gemm', '110 0:0:comb',
                 '180 0:0:s_bwd', '196 0:0:comb_bwd', '266 0:0:gemm_dx',
                 '290 0:0:gemm_dw', '314 0:0:disp_bwd', '384 0:0:s_dw',
                 '400 1:0:s', '416 1:0:disp', '486 1:0:gemm', '510 1:0:comb',
                 '580 1:0:s_bwd', '596 1:0:comb_bwd', '666 1:0:gemm_dx',
                 '690 1:0:gemm_dw', '714 1:0:disp_bwd', '784 1:0:s_dw',
                 '']),
     800),
    # an illegal mapping: comb is scheduled before its gemm.  The schedule is
    # otherwise the complete sample 7.1 one, so the dependency check is reached.
    ('illegal: comb before gemm',
     '\n'.join(['1 2 80 10 1',
                 '1 2 20 0 1 1 1 2 2 10 6 1000000 1000000',
                 '8 2', '8', '']),
     '\n'.join(['1 2', 'PSI', '1', 'MAP', '0 1', 'SCHEDULE',
                 '0 0:0:disp 0:0:s', '16 1:0:s', '70 0:0:gemm 1:0:disp',
                 '93 0:0:comb', '140 1:0:gemm', '210 0:0:s_bwd 1:0:comb',
                 '280 0:0:comb_bwd 1:0:s_bwd', '350 0:0:gemm_dx 1:0:comb_bwd',
                 '374 0:0:gemm_dw', '398 0:0:s_dw',
                 '420 0:0:disp_bwd 1:0:gemm_dx', '444 1:0:gemm_dw',
                 '468 1:0:s_dw', '490 1:0:disp_bwd', '']),
     'INVALID'),
    # the new freedom: `comb_bwd` is released by the incoming gradient, not by
    # `s_bwd`, so the two can start together -- the mirror of `disp` and `s` at
    # time 0.  `disp_bwd` still waits for both.  Both microbatches are present;
    # the second repeats the first at +344, so the schedule ends at 688.
    ('new freedom: comb_bwd starts with s_bwd',
     '\n'.join(['1 2 80 10 1',
                  '1 2 20 0 1 1 1 2 2 10 6 1000000 1000000',
                  '8 2', '8', '']),
     '1 2\nPSI\n1\nMAP\n0 1\nSCHEDULE\n0 0:0:s\n16 0:0:disp\n86 0:0:gemm\n110 0:0:comb\n180 0:0:s_bwd 0:0:comb_bwd\n250 0:0:gemm_dx\n274 0:0:disp_bwd 0:0:s_dw\n290 0:0:gemm_dw\n344 1:0:s\n360 1:0:disp\n430 1:0:gemm\n454 1:0:comb\n524 1:0:s_bwd 1:0:comb_bwd\n594 1:0:gemm_dx\n618 1:0:disp_bwd 1:0:s_dw\n642 1:0:gemm_dw\n',
     688),
    # an illegal mapping: `disp_bwd` waits for `s_bwd`, whose gradient addition
    # includes the shared-expert part (the only new edge the mirror adds).  The
    # complete sample 7.1 schedule is used and `s_bwd` of 0:0 is deferred to the
    # instant `disp_bwd` starts, so the edge is the one that fires.
    ('illegal: disp_bwd before s_bwd',
     '\n'.join(['1 2 80 10 1',
                  '1 2 20 0 1 1 1 2 2 10 6 1000000 1000000',
                  '8 2', '8', '']),
     '1 2\nPSI\n1\nMAP\n0 1\nSCHEDULE\n0 0:0:disp 0:0:s\n16 1:0:s\n70 0:0:gemm 1:0:disp\n140 0:0:comb 1:0:gemm\n210 1:0:comb\n280 0:0:comb_bwd 1:0:s_bwd\n350 0:0:gemm_dx 1:0:comb_bwd\n374 0:0:gemm_dw\n398 0:0:s_dw\n420 0:0:disp_bwd 0:0:s_bwd 1:0:gemm_dx\n444 1:0:gemm_dw\n468 1:0:s_dw\n490 1:0:disp_bwd\n',
     'INVALID'),
    ('sample 7.1',
     '1 2 39 10 1\n1 2 20 0 1 1 1 2 2 10 6 1000000 1000000\n8 2\n8\n',
     '1 2\nPSI\n1\nMAP\n0 1\nSCHEDULE\n0 0:0:disp 0:0:s\n16 1:0:s\n70 0:0:gemm 1:0:disp\n140 0:0:comb 1:0:gemm\n210 0:0:s_bwd 1:0:comb\n280 0:0:comb_bwd 1:0:s_bwd\n350 0:0:gemm_dx 1:0:comb_bwd\n374 0:0:gemm_dw\n398 0:0:s_dw\n420 0:0:disp_bwd 1:0:gemm_dx\n444 1:0:gemm_dw\n468 1:0:s_dw\n490 1:0:disp_bwd\n',
     560),
    ('sample 7.2',
     '1 4 79 10 1\n2 4 20 0 1 1 1 2 0 100 4 1000000 1000000\n8 1\n8\n8 6 1 1 0\n',
     '2 2\nPSI\n2 1\nMAP\n0 1 0 1\n0 1 1 0\nSCHEDULE\n0 0:0:s 1:0:disp 1:0:s\n400 1:0:gemm\n416 1:0:comb\n816 0:0:disp 1:1:disp 1:1:s\n1216 0:0:gemm 1:1:gemm\n1232 0:0:comb\n1240 1:1:comb\n1632 0:1:s\n1640 1:1:comb_bwd 1:1:s_bwd\n2040 0:1:disp 1:1:gemm_dw\n2064 1:1:gemm_dx\n2088 1:1:s_dw\n2440 0:1:gemm 1:1:disp_bwd\n2840 0:1:comb 1:0:comb_bwd 1:0:s_bwd\n3240 0:1:comb_bwd 0:1:s_bwd 1:0:gemm_dx\n3256 1:0:disp_bwd 1:0:gemm_dw\n3272 1:0:s_dw\n3640 0:1:gemm_dx\n3664 0:1:disp_bwd 0:1:gemm_dw\n3688 0:1:s_dw\n4064 0:0:comb_bwd 0:0:s_bwd\n4464 0:0:gemm_dx\n4480 0:0:disp_bwd 0:0:gemm_dw\n4496 0:0:s_dw\n',
     4880),
    ('sample 7.3',
     '2 2 79 10 1\n2 4 20 0 1 1 1 2 0 100 3 1000000 0\n8 1\n12\n12\n',
     '2 2\nPSI\n2 1\nMAP\n0 1 0 1\n0 1 0 1\nSCHEDULE\n0 0:0:disp 0:0:s 1:0:s\n500 0:0:gemm 1:0:disp\n1000 0:0:comb 1:0:gemm\n1500 0:1:disp 0:1:s 1:0:comb\n2000 0:1:gemm 1:1:disp\n2018 1:1:s\n2500 0:1:comb 1:1:gemm\n3000 0:1:s_bwd 1:1:comb\n3500 0:1:comb_bwd 1:1:s_bwd\n4000 0:1:gemm_dx 1:1:comb_bwd\n4018 0:1:gemm_dw 0:1:s_dw\n4500 0:1:disp_bwd 1:1:gemm_dx\n4518 1:1:gemm_dw 1:1:s_dw\n5000 0:0:comb_bwd 0:0:s_bwd 1:1:disp_bwd\n5500 0:0:gemm_dx 1:0:comb_bwd\n5518 0:0:gemm_dw 0:0:s_dw 1:0:s_bwd\n6000 0:0:disp_bwd 1:0:gemm_dx\n6018 1:0:gemm_dw 1:0:s_dw\n6500 1:0:disp_bwd\n',
     7000),
    ('sample 7.4',
     '1 2 79 10 1\n1 4 20 0 1 1 1 2 0 100 4 1000000 1000000\n8 1\n10 3 3 2 2\n',
     '1 2\nPSI\n1\nMAP\n0 1 0 1\nSCHEDULE\n0 0:0:disp 0:0:s 1:0:s\n400 0:0:gemm 1:0:disp\n800 0:0:comb 1:0:gemm\n1200 0:0:s_bwd 1:0:comb\n1600 0:0:comb_bwd 1:0:s_bwd\n2000 0:0:gemm_dx 1:0:comb_bwd\n2020 0:0:gemm_dw\n2400 0:0:disp_bwd 1:0:gemm_dx\n2420 1:0:gemm_dw\n2440 0:0:s_dw 1:0:s_dw\n2800 1:0:disp_bwd\n',
     3200),
    ('sample 7.5',
     '1 2 50 10 1\n2 2 20 0 1 1 1 2 2 10 6 1000000 500000\n8 2\n8\n8\n',
     '2 1\nPSI\n2 1\nMAP\n0 0\n0 0\nSCHEDULE\n0 0:0:disp 0:0:s\n16 0:0:gemm\n64 0:0:comb 0:1:disp 0:1:s 1:0:disp 1:0:s\n80 0:1:gemm 1:0:gemm\n128 0:1:comb 0:1:comb_bwd 0:1:s_bwd 1:0:comb\n144 0:1:gemm_dx\n192 0:0:comb_bwd 0:0:s_bwd 0:1:disp_bwd 1:1:disp 1:1:s\n208 0:0:s_dw 1:1:gemm\n216 0:0:gemm_dx\n256 1:1:comb 1:1:comb_bwd 1:1:s_bwd\n264 0:0:disp_bwd 0:0:gemm_dw\n272 1:1:gemm_dx\n320 0:1:s_dw 1:0:comb_bwd 1:0:s_bwd 1:1:disp_bwd\n328 1:1:s_dw\n336 1:0:s_dw 1:1:gemm_dw\n344 1:0:gemm_dx\n360 0:1:gemm_dw\n392 1:0:disp_bwd 1:0:gemm_dw\n',
     416),
    ('sample 7.6',
     '1 4 39 10 1\n2 2 20 0 1 1 1 2 2 20 1 1000000 1000000\n8 2\n8\n8\n',
     '2 2\nPSI\n2 1\nMAP\n0 1\n0 1\nSCHEDULE\n0 0:0:disp 0:0:s\n16 1:0:s\n140 0:0:gemm\n144 0:0:comb\n284 0:1:disp 0:1:s 1:0:disp\n424 0:1:gemm 1:0:gemm\n428 0:1:comb 1:0:comb\n568 1:1:disp 1:1:s\n584 0:1:s_bwd\n708 0:1:comb_bwd 1:1:gemm\n848 0:1:gemm_dx 1:1:comb\n852 0:1:gemm_dw\n856 0:1:s_dw\n988 0:1:disp_bwd 1:1:s_bwd\n1128 0:0:comb_bwd 0:0:s_bwd 1:1:comb_bwd\n1268 0:0:gemm_dx 1:1:gemm_dx\n1272 0:0:disp_bwd 0:0:gemm_dw 1:1:disp_bwd 1:1:gemm_dw\n1276 0:0:s_dw 1:1:s_dw\n1412 1:0:comb_bwd 1:0:s_bwd\n1552 1:0:gemm_dx\n1556 1:0:disp_bwd 1:0:gemm_dw\n1560 1:0:s_dw\n',
     1696),
]


if __name__ == '__main__':
    sys.exit(main(sys.argv))
