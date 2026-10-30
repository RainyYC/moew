/* Greedy sample solution for the MoE EP/PP problem.
 *
 *   cc -O2 -std=c11 -o sample_solution_c sample_solution.c
 *   ./sample_solution_c <case.txt>
 *
 * The construction is the same greedy family as sample_solution.py:
 * legal (V,P) enumeration, even cuts, LPT expert placement, and list
 * scheduling with a fixed set of tie-break keys.  It prints one legal mapping.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>

#define MAX_OPS 10

enum { OP_S, OP_DISP, OP_GEMM, OP_COMB, OP_S_BWD, OP_COMB_BWD,
       OP_GEMM_DX, OP_GEMM_DW, OP_DISP_BWD, OP_S_DW };
static const char *OPNAME[MAX_OPS] = {
    "s", "disp", "gemm", "comb", "s_bwd", "comb_bwd",
    "gemm_dx", "gemm_dw", "disp_bwd", "s_dw"
};
static const int IS_COMM[MAX_OPS] = {0,1,0,1,0,1,0,0,1,0};
static const int IS_C[MAX_OPS] = {1,0,1,0,1,0,1,1,0,1};

typedef struct {
    int N, S;
    long long M, Bin, Bout;
    int L, E;
    long long Z, Zs, U, Uact;
    int k, nmb;
    long long Fs, Fio, Fin, ax, bx, d, b;
    long long *T;
    long long **load;
    int has_load;
} Inst;

typedef struct { int V, P, K; long long est; } Grid;

static long long cdiv(long long a, long long b) {
    return b > 0 ? (a + b - 1) / b : 0;
}

static long long llmax(long long a, long long b) { return a > b ? a : b; }
static int imax(int a, int b) { return a > b ? a : b; }

static int parse_ints(const char *line, long long *out, int maxn) {
    int n = 0;
    const char *p = line;
    while (*p && n < maxn) {
        while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
        if (!*p) break;
        char *end = NULL;
        long long v = strtoll(p, &end, 10);
        if (end == p) break;
        out[n++] = v;
        p = end;
    }
    return n;
}

static int read_case(const char *path, Inst *in) {
    FILE *f = fopen(path, "r");
    if (!f) { perror(path); return 0; }
    char line[1 << 16];
    long long v[1024];
    int n;

    if (!fgets(line, sizeof line, f)) { fclose(f); return 0; }
    n = parse_ints(line, v, 5);
    if (n != 5) { fclose(f); return 0; }
    in->N = (int)v[0]; in->S = (int)v[1]; in->M = v[2];
    in->Bin = v[3]; in->Bout = v[4];

    if (!fgets(line, sizeof line, f)) { fclose(f); return 0; }
    n = parse_ints(line, v, 13);
    if (n != 13) { fclose(f); return 0; }
    in->L = (int)v[0]; in->E = (int)v[1]; in->Z = v[2]; in->Zs = v[3];
    in->U = v[4]; in->Uact = v[5]; in->k = (int)v[6]; in->nmb = (int)v[7];
    in->Fs = v[8]; in->Fio = v[9]; in->Fin = v[10];
    in->ax = v[11]; in->bx = v[12];

    if (!fgets(line, sizeof line, f)) { fclose(f); return 0; }
    n = parse_ints(line, v, 2);
    if (n != 2) { fclose(f); return 0; }
    in->d = v[0]; in->b = v[1];

    in->T = calloc((size_t)in->L, sizeof(long long));
    in->load = calloc((size_t)in->L, sizeof(long long *));
    in->has_load = 0;
    if (!in->T || !in->load) { fclose(f); return 0; }

    for (int l = 0; l < in->L; l++) {
        if (!fgets(line, sizeof line, f)) { fclose(f); return 0; }
        n = parse_ints(line, v, 1024);
        if (n < 1) { fclose(f); return 0; }
        in->T[l] = v[0];
        if (n == in->E + 1) {
            in->load[l] = malloc((size_t)in->E * sizeof(long long));
            if (!in->load[l]) { fclose(f); return 0; }
            for (int e = 0; e < in->E; e++) in->load[l][e] = v[e + 1];
            in->has_load = 1;
        } else if (n == 1) {
            in->load[l] = NULL;
        } else {
            fclose(f); return 0;
        }
    }
    fclose(f);
    return 1;
}

static void free_case(Inst *in) {
    if (!in) return;
    if (in->load) {
        for (int l = 0; l < in->L; l++) free(in->load[l]);
        free(in->load);
    }
    free(in->T);
}

/* ---------- placement ---------- */

typedef struct { long long load; int e; } ELoad;

static int cmpeload(const void *a, const void *b) {
    const ELoad *x = a, *y = b;
    if (x->load != y->load) return x->load > y->load ? -1 : 1;
    return x->e < y->e ? -1 : (x->e > y->e);
}

static int **make_map(const Inst *in, int P) {
    int per = in->E / P;
    int **map = calloc((size_t)in->L, sizeof(int *));
    ELoad *ord = malloc((size_t)in->E * sizeof(ELoad));
    if (!map || !ord) exit(2);
    for (int l = 0; l < in->L; l++) {
        map[l] = calloc((size_t)in->E, sizeof(int));
        if (!map[l]) exit(2);
        for (int e = 0; e < in->E; e++) {
            long long load;
            if (in->load[l]) load = in->load[l][e];
            else load = in->T[l] / in->E + (e < in->T[l] % in->E ? 1 : 0);
            ord[e].load = load; ord[e].e = e;
        }
        qsort(ord, (size_t)in->E, sizeof(ELoad), cmpeload);
        long long *rank_load = calloc((size_t)P, sizeof(long long));
        int *rank_free = malloc((size_t)P * sizeof(int));
        if (!rank_load || !rank_free) exit(2);
        for (int r = 0; r < P; r++) rank_free[r] = per;
        for (int i = 0; i < in->E; i++) {
            int e = ord[i].e, best = -1;
            for (int r = 0; r < P; r++) {
                if (rank_free[r] <= 0) continue;
                if (best < 0 || rank_load[r] < rank_load[best] ||
                    (rank_load[r] == rank_load[best] && r < best)) best = r;
            }
            map[l][e] = best;
            rank_load[best] += ord[i].load;
            rank_free[best]--;
        }
        free(rank_load); free(rank_free);
    }
    free(ord);
    return map;
}

static void free_map(int **map, int L) {
    if (!map) return;
    for (int l = 0; l < L; l++) free(map[l]);
    free(map);
}

/* ---------- durations ---------- */

static long long lceil_double(double x) { return (long long)ceil(x); }

static long long *make_durations(const Inst *in, int P, int **map) {
    long long H = (in->d * in->b) / in->k;
    double a = (double)in->ax / 1e6;
    double b = (double)in->bx / 1e6;
    long long *dur = malloc((size_t)in->L * MAX_OPS * sizeof(long long));
    long long *rank_load = malloc((size_t)P * sizeof(long long));
    if (!dur || !rank_load) exit(2);
    for (int l = 0; l < in->L; l++) {
        for (int r = 0; r < P; r++) rank_load[r] = 0;
        for (int e = 0; e < in->E; e++) {
            long long load;
            if (in->load[l]) load = in->load[l][e];
            else load = in->T[l] / in->E + (e < in->T[l] % in->E ? 1 : 0);
            rank_load[map[l][e]] += load;
        }
        long long ml = 0;
        for (int r = 0; r < P; r++) ml = llmax(ml, rank_load[r]);
        long long T = in->T[l];
        long long X = cdiv(T * H, P);
        int pin = 0, pout;
        for (int q = 1; q < P; q++) if (q / in->S == 0) pin++;
        pout = P - 1 - pin;
        long long x = llmax(cdiv((long long)pin * X, in->Bin),
                            cdiv((long long)pout * X, in->Bout)) * in->Fio;
        long long s = T * in->Fs;
        long long gemm = ml * in->Fin;
        long long *d = dur + (size_t)l * MAX_OPS;
        d[OP_S] = s;
        d[OP_DISP] = x;
        d[OP_GEMM] = gemm;
        d[OP_COMB] = x;
        d[OP_S_BWD] = lceil_double(a * (double)s);
        d[OP_COMB_BWD] = lceil_double(a * (double)x);
        d[OP_GEMM_DX] = lceil_double(a * (double)gemm);
        d[OP_GEMM_DW] = lceil_double(a * b * (double)gemm);
        d[OP_DISP_BWD] = lceil_double(a * (double)x);
        d[OP_S_DW] = lceil_double(a * b * (double)s);
    }
    free(rank_load);
    return dur;
}

/* ---------- graph, heaps, list scheduling ---------- */

typedef struct {
    int V, P, K;
    int *psi;
    int *group;
    int **map;
    long long *dur;
    long long *start;
    long long *finish;
    int N;
} Plan;

static int node_id(int mb, int l, int op, int L) {
    return (mb * L + l) * MAX_OPS + op;
}

static int preds_of(int mb, int l, int op, int L, int nmb, int out[2]) {
    (void)nmb;
    int n = 0;
    switch (op) {
    case OP_S:
    case OP_DISP:
        if (l >= 1) out[n++] = node_id(mb, l - 1, OP_COMB, L);
        break;
    case OP_GEMM:
        out[n++] = node_id(mb, l, OP_DISP, L);
        break;
    case OP_COMB:
        out[n++] = node_id(mb, l, OP_GEMM, L);
        out[n++] = node_id(mb, l, OP_S, L);
        break;
    case OP_S_BWD:
    case OP_COMB_BWD:
        out[n++] = node_id(mb, l, OP_COMB, L);
        if (l + 1 < L) out[n++] = node_id(mb, l + 1, OP_DISP_BWD, L);
        break;
    case OP_GEMM_DX:
    case OP_GEMM_DW:
    case OP_S_DW:
        out[n++] = node_id(mb, l, OP_COMB_BWD, L);
        break;
    case OP_DISP_BWD:
        out[n++] = node_id(mb, l, OP_GEMM_DX, L);
        out[n++] = node_id(mb, l, OP_S_BWD, L);
        break;
    }
    return n;
}

static long long node_key(int mb, int l, int op, int nmb, int mode) {
    switch (mode) {
    case 0: return (long long)mb * 1000000 + (long long)l * 100 + op;
    case 1: return (long long)l * 1000000 + (long long)mb * 100 + op;
    case 2: return (long long)l * 1000000 + (long long)(nmb - 1 - mb) * 100 + op;
    case 3: return (long long)op * 1000000 + (long long)l * 1000 + mb;
    default:return (long long)(9 - op) * 1000000 + (long long)l * 1000 + mb;
    }
}

/* binary heap of ready nodes, ordered by (start,key,counter) */
typedef struct {
    int n;
    int *node;
    long long *start;
    long long *key;
    int *counter;
    int *stage;
} Heap;

static int heap_less(const Heap *h, int i, int j) {
    if (h->start[i] != h->start[j]) return h->start[i] < h->start[j];
    if (h->key[i] != h->key[j]) return h->key[i] < h->key[j];
    return h->counter[i] < h->counter[j];
}

static void heap_swap(Heap *h, int i, int j) {
    int ti = h->node[i]; h->node[i] = h->node[j]; h->node[j] = ti;
    long long ts = h->start[i]; h->start[i] = h->start[j]; h->start[j] = ts;
    long long tk = h->key[i]; h->key[i] = h->key[j]; h->key[j] = tk;
    int tc = h->counter[i]; h->counter[i] = h->counter[j]; h->counter[j] = tc;
    int tg = h->stage[i]; h->stage[i] = h->stage[j]; h->stage[j] = tg;
}

static void heap_push(Heap *h, int node, long long start, long long key,
                      int counter, int stage) {
    int i = h->n++;
    h->node[i] = node; h->start[i] = start; h->key[i] = key;
    h->counter[i] = counter; h->stage[i] = stage;
    while (i > 0) {
        int p = (i - 1) / 2;
        if (!heap_less(h, i, p)) break;
        heap_swap(h, i, p); i = p;
    }
}

static int heap_pop(Heap *h) {
    int top = h->node[0];
    int last = --h->n;
    if (h->n == 0) return top;
    h->node[0] = h->node[last]; h->start[0] = h->start[last];
    h->key[0] = h->key[last]; h->counter[0] = h->counter[last];
    h->stage[0] = h->stage[last];
    int i = 0;
    for (;;) {
        int l = 2 * i + 1, r = l + 1, m = i;
        if (l < h->n && heap_less(h, l, m)) m = l;
        if (r < h->n && heap_less(h, r, m)) m = r;
        if (m == i) break;
        heap_swap(h, i, m); i = m;
    }
    return top;
}

static int build_cuts(Plan *pl, const Inst *in, int V, int P, int K) {
    pl->V = V; pl->P = P; pl->K = K;
    pl->psi = K > 1 ? malloc((size_t)(K - 1) * sizeof(int)) : NULL;
    pl->group = malloc((size_t)in->L * sizeof(int));
    if (!pl->group || (K > 1 && !pl->psi)) return 0;
    for (int j = 1; j < K; j++) pl->psi[j - 1] = j * in->L / K;
    int chunk = 0;
    for (int l = 0; l < in->L; l++) {
        while (chunk + 1 < K && l >= (chunk + 1) * in->L / K) chunk++;
        int g = chunk < V ? chunk : 2 * V - 1 - chunk;
        pl->group[l] = g;
    }
    return 1;
}

static int make_schedule(const Inst *in, Plan *pl, int key_mode) {
    int L = in->L, nmb = in->nmb;
    int N = nmb * L * MAX_OPS;
    pl->N = N;
    pl->start = malloc((size_t)N * sizeof(long long));
    pl->finish = malloc((size_t)N * sizeof(long long));
    int *indeg = malloc((size_t)N * sizeof(int));
    int *pred1 = malloc((size_t)N * sizeof(int));
    int *pred2 = malloc((size_t)N * sizeof(int));
    int *head = malloc((size_t)N * sizeof(int));
    int *to = malloc((size_t)(2 * N) * sizeof(int));
    int *nxt = malloc((size_t)(2 * N) * sizeof(int));
    long long *ready = malloc((size_t)N * sizeof(long long));
    long long *cfree = calloc((size_t)pl->V, sizeof(long long));
    long long *nfree = calloc((size_t)pl->V, sizeof(long long));
    Heap h;
    h.n = 0;
    h.node = malloc((size_t)N * sizeof(int));
    h.start = malloc((size_t)N * sizeof(long long));
    h.key = malloc((size_t)N * sizeof(long long));
    h.counter = malloc((size_t)N * sizeof(int));
    h.stage = malloc((size_t)N * sizeof(int));
    if (!pl->start || !pl->finish || !indeg || !pred1 || !pred2 || !head ||
        !to || !nxt || !ready || !cfree || !nfree || !h.node || !h.start ||
        !h.key || !h.counter || !h.stage) return 0;

    for (int i = 0; i < N; i++) { head[i] = -1; pred1[i] = pred2[i] = -1; }
    int ec = 0;
    for (int mb = 0; mb < nmb; mb++) {
        for (int l = 0; l < L; l++) {
            for (int op = 0; op < MAX_OPS; op++) {
                int n = node_id(mb, l, op, L);
                int p[2];
                int np = preds_of(mb, l, op, L, nmb, p);
                indeg[n] = np;
                if (np > 0) pred1[n] = p[0];
                if (np > 1) pred2[n] = p[1];
                for (int j = 0; j < np; j++) {
                    to[ec] = n; nxt[ec] = head[p[j]]; head[p[j]] = ec++;
                }
            }
        }
    }

    int counter = 0;
    for (int mb = 0; mb < nmb; mb++) {
        for (int l = 0; l < L; l++) {
            for (int op = 0; op < MAX_OPS; op++) {
                int n = node_id(mb, l, op, L);
                if (indeg[n] == 0) {
                    int stage = pl->group[l];
                    long long key = node_key(mb, l, op, nmb, key_mode);
                    heap_push(&h, n, 0, key, counter++, stage);
                }
            }
        }
    }

    int done = 0;
    while (done < N) {
        if (h.n == 0) { free(indeg); free(pred1); free(pred2); free(head);
                        free(to); free(nxt); free(ready); free(cfree); free(nfree);
                        free(h.node); free(h.start); free(h.key); free(h.counter); free(h.stage);
                        return 0; }
        long long st = h.start[0];
        int stage = h.stage[0];
        int n = heap_pop(&h);
        long long d = pl->dur[(size_t)(n / MAX_OPS % L) * MAX_OPS + (n % MAX_OPS)];
        long long t;
        if (d <= 0) {
            t = st;
        } else {
            long long room = IS_C[n % MAX_OPS] ? cfree[stage] : nfree[stage];
            t = st > room ? st : room;
            if (IS_C[n % MAX_OPS]) cfree[stage] = t + d;
            else nfree[stage] = t + d;
        }
        pl->start[n] = t;
        pl->finish[n] = t + d;
        done++;
        for (int e = head[n]; e != -1; e = nxt[e]) {
            int q = to[e];
            indeg[q]--;
            if (indeg[q] == 0) {
                long long rt = 0;
                if (pred1[q] >= 0) rt = pl->finish[pred1[q]];
                if (pred2[q] >= 0 && pl->finish[pred2[q]] > rt) rt = pl->finish[pred2[q]];
                int qmb = q / (L * MAX_OPS);
                int rem = q % (L * MAX_OPS);
                int ql = rem / MAX_OPS, qop = rem % MAX_OPS;
                long long key = node_key(qmb, ql, qop, nmb, key_mode);
                heap_push(&h, q, rt, key, counter++, pl->group[ql]);
            }
        }
    }

    free(indeg); free(pred1); free(pred2); free(head); free(to); free(nxt);
    free(ready); free(cfree); free(nfree);
    free(h.node); free(h.start); free(h.key); free(h.counter); free(h.stage);
    return 1;
}

/* ---------- memory check ---------- */

typedef struct { long long t; int group; int delta; int kind; } Event;

static int cmp_event_time(const void *a, const void *b) {
    const Event *x = a, *y = b;
    if (x->t != y->t) return x->t < y->t ? -1 : 1;
    if (x->kind != y->kind) return x->kind < y->kind ? -1 : 1;
    if (x->group != y->group) return x->group < y->group ? -1 : 1;
    return 0;
}

static int memory_ok(const Inst *in, const Plan *pl) {
    int V = pl->V, P = pl->P, L = in->L, nmb = in->nmb;
    long long *exp = calloc((size_t)V, sizeof(long long));
    long long *ovl = calloc((size_t)V, sizeof(long long));
    long long *act = calloc((size_t)V, sizeof(long long));
    long long *cnt = calloc((size_t)V, sizeof(long long));
    long long *tmp = calloc((size_t)V, sizeof(long long));
    Event *ev = malloc((size_t)(2 * nmb * L + 2 * nmb * L + 8) * sizeof(Event));
    if (!exp || !ovl || !act || !cnt || !tmp || !ev) return 0;

    for (int l = 0; l < L; l++)
        exp[pl->group[l]] += (long long)(in->E / P) * in->Z + in->Zs;

    int ne = 0;
    for (int mb = 0; mb < nmb; mb++) for (int l = 0; l < L; l++) for (int op = 0; op < MAX_OPS; op++) {
        if (!IS_COMM[op]) continue;
        int n = node_id(mb, l, op, L);
        long long d = pl->dur[(size_t)l * MAX_OPS + op];
        if (d <= 0) continue;
        ev[ne].t = pl->start[n]; ev[ne].group = pl->group[l]; ev[ne].delta = 1; ev[ne].kind = 0; ne++;
        ev[ne].t = pl->finish[n]; ev[ne].group = pl->group[l]; ev[ne].delta = -1; ev[ne].kind = 0; ne++;
    }
    qsort(ev, (size_t)ne, sizeof(Event), cmp_event_time);
    for (int i = 0; i < ne; ) {
        int j = i;
        while (j < ne && ev[j].t == ev[i].t) j++;
        for (int k = i; k < j; k++) tmp[ev[k].group] += ev[k].delta;
        for (int k = i; k < j; k++) {
            int g = ev[k].group;
            if (tmp[g]) { cnt[g] += tmp[g]; tmp[g] = 0; }
            if (cnt[g] > ovl[g]) ovl[g] = cnt[g];
        }
        i = j;
    }

    ne = 0;
    for (int mb = 0; mb < nmb; mb++) for (int l = 0; l < L; l++) {
        int nc = node_id(mb, l, OP_COMB, L);
        int ns = node_id(mb, l, OP_S_BWD, L);
        ev[ne].t = pl->finish[nc]; ev[ne].group = pl->group[l]; ev[ne].delta = 1; ev[ne].kind = 0; ne++;
        ev[ne].t = pl->start[ns]; ev[ne].group = pl->group[l]; ev[ne].delta = -1; ev[ne].kind = 1; ne++;
    }
    qsort(ev, (size_t)ne, sizeof(Event), cmp_event_time);
    for (int g = 0; g < V; g++) cnt[g] = 0;
    for (int i = 0; i < ne; ) {
        int j = i;
        while (j < ne && ev[j].t == ev[i].t) j++;
        for (int k = i; k < j; k++) {
            int g = ev[k].group;
            if (ev[k].delta > 0) {
                cnt[g]++;
                if (cnt[g] > act[g]) act[g] = cnt[g];
            }
        }
        for (int k = i; k < j; k++) {
            int g = ev[k].group;
            if (ev[k].delta < 0) cnt[g]--;
        }
        i = j;
    }

    int ok = 1;
    for (int g = 0; g < V; g++) {
        long long mem = exp[g] + in->U * ovl[g] + in->Uact * act[g];
        if (mem > in->M) ok = 0;
    }
    free(exp); free(ovl); free(act); free(cnt); free(tmp); free(ev);
    return ok;
}

/* ---------- grid order ---------- */

static long long peak_est(const Inst *in, int V, int P, int K) {
    int *chunks = malloc((size_t)K * sizeof(int));
    int lv = 0;
    if (!chunks) exit(2);
    for (int k = 0; k < K; k++) chunks[k] = (k + 1) * in->L / K - k * in->L / K;
    if (K == 2 * V) {
        for (int g = 0; g < V; g++) lv = imax(lv, chunks[g] + chunks[2 * V - 1 - g]);
    } else {
        for (int k = 0; k < K; k++) lv = imax(lv, chunks[k]);
    }
    free(chunks);
    long long exp = (long long)lv * ((long long)(in->E / P) * in->Z + in->Zs);
    return exp + in->U * 2 + in->Uact * (long long)lv * in->nmb;
}

static int cmp_grid(const void *a, const void *b) {
    const Grid *x = a, *y = b;
    if (x->est != y->est) return x->est < y->est ? -1 : 1;
    if (x->P != y->P) return x->P < y->P ? -1 : 1;
    if (x->V != y->V) return x->V < y->V ? -1 : 1;
    return x->K < y->K ? -1 : (x->K > y->K);
}

static Grid *enumerate_grids(const Inst *in, int *count) {
    int R = in->N * in->S;
    int cap = 512, n = 0;
    Grid *g = malloc((size_t)cap * sizeof(Grid));
    if (!g) exit(2);
    for (int P = 1; P <= in->E; P++) {
        if (in->E % P) continue;
        if (!(in->S % P == 0 || P % in->S == 0)) continue;
        int Vmax = in->L < R / P ? in->L : R / P;
        for (int V = 1; V <= Vmax; V++) {
            for (int km = 1; km <= 2; km++) {
                int K = km * V;
                if (K > in->L) continue;
                if (n == cap) { cap *= 2; g = realloc(g, (size_t)cap * sizeof(Grid)); }
                g[n].V = V; g[n].P = P; g[n].K = K;
                g[n].est = peak_est(in, V, P, K);
                n++;
            }
        }
    }
    qsort(g, (size_t)n, sizeof(Grid), cmp_grid);
    *count = n;
    return g;
}

/* ---------- output ---------- */

typedef struct { long long t; int mb, l, op; } Row;

static int cmp_row(const void *a, const void *b) {
    const Row *x = a, *y = b;
    if (x->t != y->t) return x->t < y->t ? -1 : 1;
    if (x->mb != y->mb) return x->mb < y->mb ? -1 : 1;
    if (x->l != y->l) return x->l < y->l ? -1 : 1;
    return x->op < y->op ? -1 : (x->op > y->op);
}

static void print_plan(const Inst *in, const Plan *pl) {
    printf("%d %d\n", pl->V, pl->P);
    printf("PSI\n");
    printf("%d", pl->K);
    for (int j = 0; j < pl->K - 1; j++) printf(" %d", pl->psi[j]);
    printf("\nMAP\n");
    for (int l = 0; l < in->L; l++) {
        for (int e = 0; e < in->E; e++) {
            if (e) printf(" ");
            printf("%d", pl->map[l][e]);
        }
        printf("\n");
    }
    Row *rows = malloc((size_t)pl->N * sizeof(Row));
    if (!rows) exit(2);
    for (int mb = 0; mb < in->nmb; mb++)
        for (int l = 0; l < in->L; l++)
            for (int op = 0; op < MAX_OPS; op++) {
                int n = node_id(mb, l, op, in->L);
                rows[n].t = pl->start[n]; rows[n].mb = mb; rows[n].l = l; rows[n].op = op;
            }
    qsort(rows, (size_t)pl->N, sizeof(Row), cmp_row);
    printf("SCHEDULE\n");
    long long cur = -1;
    for (int i = 0; i < pl->N; i++) {
        if (rows[i].t != cur) {
            if (cur >= 0) printf("\n");
            printf("%lld", rows[i].t);
            cur = rows[i].t;
        }
        printf(" %d:%d:%s", rows[i].mb, rows[i].l, OPNAME[rows[i].op]);
    }
    printf("\n");
    free(rows);
}

/* ---------- main ---------- */

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s <case.txt>\n", argv[0]);
        return 2;
    }
    Inst in;
    memset(&in, 0, sizeof in);
    if (!read_case(argv[1], &in)) {
        fprintf(stderr, "failed to read %s\n", argv[1]);
        return 1;
    }

    int ng = 0;
    Grid *grids = enumerate_grids(&in, &ng);
    int solved = 0;

    for (int gi = 0; gi < ng && !solved; gi++) {
        int V = grids[gi].V, P = grids[gi].P, K = grids[gi].K;
        Plan pl;
        memset(&pl, 0, sizeof pl);
        if (!build_cuts(&pl, &in, V, P, K)) continue;
        pl.map = make_map(&in, P);
        pl.dur = make_durations(&in, P, pl.map);
        for (int key = 0; key < 5 && !solved; key++) {
            if (!make_schedule(&in, &pl, key)) break;
            if (memory_ok(&in, &pl)) {
                print_plan(&in, &pl);
                solved = 1;
            } else {
                free(pl.start); free(pl.finish);
                pl.start = pl.finish = NULL;
            }
        }
        free(pl.start); free(pl.finish);
        free_map(pl.map, in.L);
        free(pl.dur);
        free(pl.psi);
        free(pl.group);
    }

    if (!solved) {
        fprintf(stderr, "no memory-feasible greedy plan found\n");
        return 1;
    }
    free(grids);
    free_case(&in);
    return 0;
}
