/* DEMO-ONLY static fixtures for ui/ (?demo=1).
 * Shapes follow CONTRACT §2 and are produced by judge.core.evaluate_detailed; they are
 * canned server responses, never computed by the viewer.  The live path never loads this file.
 */
window.__UI_FIXTURES__ = {
 "generated_by": "judge.core.evaluate_detailed（静态夹具，仅界面演示；非 ui 计算）",
 "generated_at": "2026-10-20T12:30:00Z",
 "health": {
  "ok": true,
  "ledger_lines": 8,
  "versions": 4,
  "sse_clients": 0
 },
 "versions": [
  {
   "version": "v0.6",
   "commit": "8f2c1d9",
   "run_id": "r-0004",
   "actor": "solver",
   "origin": "cli",
   "created_at": "2026-10-20T12:28:00Z",
   "state": "done",
   "notes": "演示夹具：静态样例（?demo=1），不是实时账本。",
   "score": 0.9863939238321437,
   "rank": 1,
   "ok": true,
   "cases": {
    "ex1": {
     "time": 576,
     "base": 592,
     "ok": true
    },
    "ex2": {
     "time": 4880,
     "base": 4880,
     "ok": true
    }
   }
  },
  {
   "version": "v0.5",
   "commit": "3ad9f07",
   "run_id": "r-0003",
   "actor": "solver",
   "origin": "cli",
   "created_at": "2026-10-20T11:40:00Z",
   "state": "done",
   "notes": "演示夹具：静态样例（?demo=1），不是实时账本。",
   "score": 1.0,
   "rank": 2,
   "ok": true,
   "cases": {
    "ex1": {
     "time": 592,
     "base": 592,
     "ok": true
    },
    "ex2": {
     "time": 4880,
     "base": 4880,
     "ok": true
    },
    "ex3": {
     "time": 4000,
     "base": 4000,
     "ok": true
    },
    "ex4": {
     "time": 3200,
     "base": 3200,
     "ok": true
    }
   }
  },
  {
   "version": "base",
   "commit": "0000000",
   "run_id": "r-0001",
   "actor": "captain",
   "origin": "cli",
   "created_at": "2026-10-20T10:05:00Z",
   "state": "done",
   "notes": "演示夹具：静态样例（?demo=1），不是实时账本。",
   "score": 1.0,
   "rank": 3,
   "ok": true,
   "cases": {
    "ex1": {
     "time": 592,
     "base": 592,
     "ok": true
    },
    "ex2": {
     "time": 4880,
     "base": 4880,
     "ok": true
    }
   }
  },
  {
   "version": "v0.5-hotfix",
   "commit": "3ad9f07",
   "run_id": "r-0002",
   "actor": "solver",
   "origin": "cli",
   "created_at": "2026-10-20T11:05:00Z",
   "state": "done",
   "notes": "演示夹具：静态样例（?demo=1），不是实时账本。",
   "score": null,
   "rank": null,
   "ok": false,
   "cases": {
    "ex1": {
     "time": 0,
     "base": 592,
     "ok": false
    },
    "ex2": {
     "time": 4880,
     "base": 4880,
     "ok": true
    }
   }
  },
  {
   "version": "v0.6-timeout",
   "commit": "8f2c1d9",
   "run_id": "r-0007",
   "actor": "solver",
   "origin": "cli",
   "created_at": "2026-10-20T12:20:00Z",
   "state": "timeout",
   "notes": "演示夹具：终态 run（timeout），score:null 仍出现在列表里。",
   "score": null,
   "rank": null,
   "ok": false,
   "cases": {
    "ex3": {
     "time": null,
     "base": 4000,
     "ok": false
    }
   }
  },
  {
   "version": "v0.6-fail",
   "commit": "8f2c1d9",
   "run_id": "r-0006",
   "actor": "cli",
   "origin": "cli",
   "created_at": "2026-10-20T12:10:00Z",
   "state": "failed",
   "notes": "演示夹具：终态 run（failed），score:null 仍出现在列表里。",
   "score": null,
   "rank": null,
   "ok": false,
   "cases": {}
  }
 ],
 "runs": [
  {
   "run_id": "r-0010",
   "state": "queued",
   "version": "v0.7-rc",
   "commit": "91be2aa",
   "actor": "solver",
   "origin": "cli",
   "created_at": "2026-10-20T12:42:00Z",
   "started_at": null,
   "deadline_at": null,
   "done": 0,
   "total": 6,
   "solver_cmd": "python3 solver/solve_all.py",
   "notes": "排队中（演示）",
   "results": [],
   "errors": []
  },
  {
   "run_id": "r-0009",
   "state": "queued",
   "version": "v0.7-rc",
   "commit": "91be2aa",
   "actor": "solver",
   "origin": "cli",
   "created_at": "2026-10-20T12:40:00Z",
   "started_at": "2026-10-20T12:40:00Z",
   "deadline_at": null,
   "done": 0,
   "total": 6,
   "solver_cmd": "python3 solver/solve_all.py",
   "notes": "排队中（演示）",
   "results": [],
   "errors": []
  },
  {
   "run_id": "r-0008",
   "state": "running",
   "version": "v0.7-rc",
   "commit": "91be2aa",
   "actor": "solver",
   "origin": "cli",
   "created_at": "2026-10-20T12:36:00Z",
   "started_at": "2026-10-20T12:36:00Z",
   "deadline_at": null,
   "done": 3,
   "total": 6,
   "solver_cmd": "python3 solver/solve_all.py",
   "notes": "跑 6 例（演示）",
   "results": [
    {
     "case": "ex1",
     "ok": true,
     "time": 592,
     "solve_ms": 190
    }
   ],
   "errors": []
  },
  {
   "run_id": "r-0007",
   "state": "timeout",
   "version": "v0.6",
   "commit": "8f2c1d9",
   "actor": "solver",
   "origin": "cli",
   "created_at": "2026-10-20T12:20:00Z",
   "started_at": "2026-10-20T12:20:00Z",
   "deadline_at": null,
   "done": 2,
   "total": 6,
   "solver_cmd": "python3 solver/solve_all.py",
   "notes": "ex3 超 10s 被 kill（演示）",
   "results": [
    {
     "case": "ex3",
     "ok": false,
     "time": null,
     "state": "timeout"
    }
   ],
   "errors": []
  },
  {
   "run_id": "r-0006",
   "state": "failed",
   "version": "v0.6",
   "commit": "8f2c1d9",
   "actor": "cli",
   "origin": "cli",
   "created_at": "2026-10-20T12:10:00Z",
   "started_at": "2026-10-20T12:10:00Z",
   "deadline_at": null,
   "done": 0,
   "total": 2,
   "solver_cmd": "python3 solver/solve_all.py --broken",
   "notes": "solver 退出码 1（演示）",
   "results": [],
   "errors": []
  },
  {
   "run_id": "r-0004",
   "state": "done",
   "version": "v0.6",
   "commit": "8f2c1d9",
   "actor": "solver",
   "origin": "cli",
   "created_at": "2026-10-20T12:28:00Z",
   "started_at": "2026-10-20T12:28:00Z",
   "deadline_at": null,
   "done": 2,
   "total": 2,
   "solver_cmd": "python3 solver/solve_all.py",
   "notes": "6 种优先级：ex1 576（演示夹具）",
   "results": [
    {
     "case": "ex1",
     "ok": true,
     "time": 576,
     "solve_ms": 240
    },
    {
     "case": "ex2",
     "ok": true,
     "time": 4880,
     "solve_ms": 310
    }
   ],
   "errors": []
  },
  {
   "run_id": "r-0003",
   "state": "done",
   "version": "v0.5",
   "commit": "3ad9f07",
   "actor": "solver",
   "origin": "cli",
   "created_at": "2026-10-20T11:40:00Z",
   "started_at": "2026-10-20T11:40:00Z",
   "deadline_at": null,
   "done": 4,
   "total": 4,
   "solver_cmd": "python3 solver/solve_all.py",
   "notes": "基线：题面公布的 4 个值",
   "results": [
    {
     "case": "ex1",
     "ok": true,
     "time": 592,
     "solve_ms": 210
    },
    {
     "case": "ex2",
     "ok": true,
     "time": 4880,
     "solve_ms": 290
    },
    {
     "case": "ex3",
     "ok": true,
     "time": 4000,
     "solve_ms": 260
    },
    {
     "case": "ex4",
     "ok": true,
     "time": 3200,
     "solve_ms": 250
    }
   ],
   "errors": []
  },
  {
   "run_id": "r-0002",
   "state": "done",
   "version": "v0.5-hotfix",
   "commit": "3ad9f07",
   "actor": "solver",
   "origin": "cli",
   "created_at": "2026-10-20T11:05:00Z",
   "started_at": "2026-10-20T11:05:00Z",
   "deadline_at": null,
   "done": 2,
   "total": 2,
   "solver_cmd": "python3 solver/solve_all.py --hotfix",
   "notes": "注入非法调度：ex1 少一行（演示）",
   "results": [
    {
     "case": "ex1",
     "ok": false,
     "time": null,
     "solve_ms": 180
    },
    {
     "case": "ex2",
     "ok": true,
     "time": 4880,
     "solve_ms": 300
    }
   ],
   "errors": []
  },
  {
   "run_id": "r-0001",
   "state": "done",
   "version": "base",
   "commit": "0000000",
   "actor": "captain",
   "origin": "cli",
   "created_at": "2026-10-20T10:05:00Z",
   "started_at": "2026-10-20T10:05:00Z",
   "deadline_at": null,
   "done": 2,
   "total": 2,
   "solver_cmd": "python3 -m judge run --cases ex1 ex2",
   "notes": "题面样例直接登记",
   "results": [
    {
     "case": "ex1",
     "ok": true,
     "time": 592,
     "solve_ms": 205
    },
    {
     "case": "ex2",
     "ok": true,
     "time": 4880,
     "solve_ms": 295
    }
   ],
   "errors": []
  },
  {
   "run_id": "r-0011",
   "state": "done",
   "version": "demo-slice",
   "commit": "5f00d00",
   "actor": "fixture",
   "origin": "demo",
   "created_at": "2026-10-20T12:05:00Z",
   "started_at": "2026-10-20T12:05:00Z",
   "deadline_at": null,
   "done": 1,
   "total": 1,
   "solver_cmd": "python3 solver/solve_all.py",
   "notes": "切片演示：?demo=1&run=r-0011，ops total 放大到 640000 以展示截断徽标",
   "results": [
    {
     "case": "ex1",
     "ok": true,
     "time": 576,
     "solve_ms": 240
    }
   ],
   "errors": []
  }
 ],
 "cases": {
  "r-0004/ex1": {
   "ok": true,
   "time": 576,
   "lb": 560,
   "groups": [
    {
     "v": 0,
     "mexp": 20,
     "movl": 2,
     "mact": 1,
     "limit": 39
    }
   ],
   "engines": [
    {
     "v": 0,
     "comp": 240,
     "comm": 560,
     "comm_first": 16,
     "comm_last": 576
    }
   ],
   "grid": {
    "V": 1,
    "P": 2,
    "D": 1
   },
   "K": 1,
   "psi": [],
   "errors": [],
   "solve_ms": 390,
   "output_sha256": "a1b2c3d4e5f60718",
   "ops_total": 20
  },
  "r-0004/ex2": {
   "ok": true,
   "time": 4880,
   "lb": 3200,
   "groups": [
    {
     "v": 0,
     "mexp": 40,
     "movl": 2,
     "mact": 2,
     "limit": 79
    },
    {
     "v": 1,
     "mexp": 40,
     "movl": 2,
     "mact": 1,
     "limit": 79
    }
   ],
   "engines": [
    {
     "v": 0,
     "comp": 96,
     "comm": 3200,
     "comm_first": 0,
     "comm_last": 4880
    },
    {
     "v": 1,
     "comp": 144,
     "comm": 3200,
     "comm_first": 816,
     "comm_last": 4064
    }
   ],
   "grid": {
    "V": 2,
    "P": 2,
    "D": 1
   },
   "K": 2,
   "psi": [
    1
   ],
   "errors": [],
   "solve_ms": 360,
   "output_sha256": "b2c3d4e5f6071829",
   "ops_total": 40
  },
  "r-0003/ex1": {
   "ok": true,
   "time": 592,
   "lb": 560,
   "groups": [
    {
     "v": 0,
     "mexp": 20,
     "movl": 2,
     "mact": 1,
     "limit": 39
    }
   ],
   "engines": [
    {
     "v": 0,
     "comp": 240,
     "comm": 560,
     "comm_first": 16,
     "comm_last": 576
    }
   ],
   "grid": {
    "V": 1,
    "P": 2,
    "D": 1
   },
   "K": 1,
   "psi": [],
   "errors": [],
   "solve_ms": 390,
   "output_sha256": "c3d4e5f607182a3b",
   "ops_total": 20
  },
  "r-0003/ex2": {
   "ok": true,
   "time": 4880,
   "lb": 3200,
   "groups": [
    {
     "v": 0,
     "mexp": 40,
     "movl": 2,
     "mact": 2,
     "limit": 79
    },
    {
     "v": 1,
     "mexp": 40,
     "movl": 2,
     "mact": 1,
     "limit": 79
    }
   ],
   "engines": [
    {
     "v": 0,
     "comp": 96,
     "comm": 3200,
     "comm_first": 0,
     "comm_last": 4880
    },
    {
     "v": 1,
     "comp": 144,
     "comm": 3200,
     "comm_first": 816,
     "comm_last": 4064
    }
   ],
   "grid": {
    "V": 2,
    "P": 2,
    "D": 1
   },
   "K": 2,
   "psi": [
    1
   ],
   "errors": [],
   "solve_ms": 360,
   "output_sha256": "c3d4e5f607182a3b",
   "ops_total": 40
  },
  "r-0003/ex3": {
   "ok": true,
   "time": 4000,
   "lb": 4000,
   "groups": [
    {
     "v": 0,
     "mexp": 40,
     "movl": 2,
     "mact": 1,
     "limit": 79
    }
   ],
   "engines": [
    {
     "v": 0,
     "comp": 72,
     "comm": 4000,
     "comm_first": 0,
     "comm_last": 4000
    }
   ],
   "grid": {
    "V": 1,
    "P": 2,
    "D": 2
   },
   "K": 1,
   "psi": [],
   "errors": [],
   "solve_ms": 390,
   "output_sha256": "c3d4e5f607182a3b",
   "ops_total": 20
  },
  "r-0003/ex4": {
   "ok": true,
   "time": 3200,
   "lb": 3200,
   "groups": [
    {
     "v": 0,
     "mexp": 40,
     "movl": 2,
     "mact": 1,
     "limit": 79
    }
   ],
   "engines": [
    {
     "v": 0,
     "comp": 120,
     "comm": 3200,
     "comm_first": 0,
     "comm_last": 3200
    }
   ],
   "grid": {
    "V": 1,
    "P": 2,
    "D": 2
   },
   "K": 1,
   "psi": [],
   "errors": [],
   "solve_ms": 390,
   "output_sha256": "c3d4e5f607182a3b",
   "ops_total": 20
  },
  "r-0002/ex1": {
   "ok": false,
   "time": null,
   "lb": 560,
   "groups": [],
   "engines": [],
   "grid": {
    "V": 1,
    "P": 2,
    "D": 1
   },
   "K": 1,
   "psi": [],
   "errors": [
    {
     "category": "missing",
     "message": "调度缺少操作 1:0:s_dw（每层每 microbatch 需十个操作，题面 §3.2）",
     "t": null,
     "at": "1:0:s_dw"
    }
   ],
   "solve_ms": 210,
   "output_sha256": "d4e5f607182a3b4c",
   "ops_total": 0
  },
  "r-0002/ex2": {
   "ok": true,
   "time": 4880,
   "lb": 3200,
   "groups": [
    {
     "v": 0,
     "mexp": 40,
     "movl": 2,
     "mact": 2,
     "limit": 79
    },
    {
     "v": 1,
     "mexp": 40,
     "movl": 2,
     "mact": 1,
     "limit": 79
    }
   ],
   "engines": [
    {
     "v": 0,
     "comp": 96,
     "comm": 3200,
     "comm_first": 0,
     "comm_last": 4880
    },
    {
     "v": 1,
     "comp": 144,
     "comm": 3200,
     "comm_first": 816,
     "comm_last": 4064
    }
   ],
   "grid": {
    "V": 2,
    "P": 2,
    "D": 1
   },
   "K": 2,
   "psi": [
    1
   ],
   "errors": [],
   "solve_ms": 360,
   "output_sha256": "e5f607182a3b4c5d",
   "ops_total": 40
  },
  "r-0001/ex1": {
   "ok": true,
   "time": 592,
   "lb": 560,
   "groups": [
    {
     "v": 0,
     "mexp": 20,
     "movl": 2,
     "mact": 1,
     "limit": 39
    }
   ],
   "engines": [
    {
     "v": 0,
     "comp": 240,
     "comm": 560,
     "comm_first": 16,
     "comm_last": 576
    }
   ],
   "grid": {
    "V": 1,
    "P": 2,
    "D": 1
   },
   "K": 1,
   "psi": [],
   "errors": [],
   "solve_ms": 390,
   "output_sha256": "f607182a3b4c5d6e",
   "ops_total": 20
  },
  "r-0001/ex2": {
   "ok": true,
   "time": 4880,
   "lb": 3200,
   "groups": [
    {
     "v": 0,
     "mexp": 40,
     "movl": 2,
     "mact": 2,
     "limit": 79
    },
    {
     "v": 1,
     "mexp": 40,
     "movl": 2,
     "mact": 1,
     "limit": 79
    }
   ],
   "engines": [
    {
     "v": 0,
     "comp": 96,
     "comm": 3200,
     "comm_first": 0,
     "comm_last": 4880
    },
    {
     "v": 1,
     "comp": 144,
     "comm": 3200,
     "comm_first": 816,
     "comm_last": 4064
    }
   ],
   "grid": {
    "V": 2,
    "P": 2,
    "D": 1
   },
   "K": 2,
   "psi": [
    1
   ],
   "errors": [],
   "solve_ms": 360,
   "output_sha256": "07182a3b4c5d6e7f",
   "ops_total": 40
  },
  "r-0011/ex1": {
   "ok": true,
   "time": 576,
   "lb": 560,
   "groups": [
    {
     "v": 0,
     "mexp": 20,
     "movl": 2,
     "mact": 1,
     "limit": 39
    }
   ],
   "engines": [
    {
     "v": 0,
     "comp": 240,
     "comm": 560,
     "comm_first": 16,
     "comm_last": 576
    }
   ],
   "grid": {
    "V": 1,
    "P": 2,
    "D": 1
   },
   "K": 1,
   "psi": [],
   "errors": [],
   "solve_ms": 390,
   "output_sha256": "a1b2c3d4e5f60718",
   "ops_total": 20
  }
 },
 "outputs": {
  "r-0004/ex1": "1 2 1\nPSI\n1\nMAP\n0 1\nSCHEDULE\n0 0:0:s\n16 0:0:disp 1:0:s\n86 0:0:gemm 1:0:disp\n156 0:0:comb 1:0:gemm\n226 0:0:s_bwd 1:0:comb\n296 0:0:comb_bwd 1:0:s_bwd\n366 0:0:gemm_dx 1:0:comb_bwd\n390 0:0:gemm_dw\n436 0:0:disp_bwd 1:0:gemm_dx\n460 1:0:gemm_dw\n506 0:0:s_dw 1:0:disp_bwd\n544 1:0:s_dw\n",
  "r-0003/ex1": "1 2 1\nPSI\n1\nMAP\n0 1\nSCHEDULE\n0 0:0:s\n16 0:0:disp 1:0:s\n86 0:0:gemm 1:0:disp\n156 0:0:comb 1:0:gemm\n226 0:0:s_bwd 1:0:comb\n296 0:0:comb_bwd 1:0:s_bwd\n366 0:0:gemm_dx 1:0:comb_bwd\n390 0:0:gemm_dw\n436 0:0:disp_bwd 1:0:gemm_dx\n460 1:0:gemm_dw\n506 0:0:s_dw 1:0:disp_bwd\n576 1:0:s_dw\n",
  "r-0003/ex2": "2 2 1\nPSI\n2 1\nMAP\n0 1 0 1\n0 1 1 0\nSCHEDULE\n0 0:0:s 1:0:disp 1:0:s\n400 1:0:gemm\n416 1:0:comb\n816 0:0:disp 1:1:disp 1:1:s\n1216 0:0:gemm 1:1:gemm\n1232 0:0:comb\n1240 1:1:comb\n1632 0:1:s\n1640 1:1:comb_bwd 1:1:s_bwd\n2040 0:1:disp 1:1:gemm_dw 1:1:s_dw\n2064 1:1:gemm_dx\n2440 0:1:gemm 1:1:disp_bwd\n2840 0:1:comb 1:0:comb_bwd 1:0:s_bwd\n3240 0:1:comb_bwd 0:1:s_bwd 1:0:gemm_dx 1:0:s_dw\n3256 1:0:disp_bwd 1:0:gemm_dw\n3640 0:1:gemm_dx 0:1:s_dw\n3664 0:1:disp_bwd 0:1:gemm_dw\n4064 0:0:comb_bwd 0:0:s_bwd\n4464 0:0:gemm_dx 0:0:s_dw\n4480 0:0:disp_bwd 0:0:gemm_dw\n",
  "r-0003/ex3": "1 2 2\nPSI\n1\nMAP\n0 1 0 1\nSCHEDULE\n0 0:0:disp 0:0:s 1:0:s\n500 0:0:gemm 1:0:disp\n1000 0:0:comb 1:0:gemm\n1500 0:0:s_bwd 1:0:comb\n2000 0:0:comb_bwd 1:0:s_bwd\n2500 0:0:gemm_dx 1:0:comb_bwd\n2518 0:0:gemm_dw\n3000 0:0:disp_bwd 1:0:gemm_dx\n3018 1:0:gemm_dw\n3500 0:0:s_dw 1:0:disp_bwd\n4000 1:0:s_dw\n",
  "r-0003/ex4": "1 2 2\nPSI\n1\nMAP\n0 1 0 1\nSCHEDULE\n0 0:0:disp 0:0:s 1:0:s\n400 0:0:gemm 1:0:disp\n800 0:0:comb 1:0:gemm\n1200 0:0:s_bwd 1:0:comb\n1600 0:0:comb_bwd 1:0:s_bwd\n2000 0:0:gemm_dx 1:0:comb_bwd\n2020 0:0:gemm_dw\n2400 0:0:disp_bwd 1:0:gemm_dx\n2420 1:0:gemm_dw\n2800 0:0:s_dw 1:0:disp_bwd\n3200 1:0:s_dw\n",
  "r-0002/ex1": "1 2 1\nPSI\n1\nMAP\n0 1\nSCHEDULE\n0 0:0:s\n16 0:0:disp 1:0:s\n86 0:0:gemm 1:0:disp\n156 0:0:comb 1:0:gemm\n226 0:0:s_bwd 1:0:comb\n296 0:0:comb_bwd 1:0:s_bwd\n366 0:0:gemm_dx 1:0:comb_bwd\n390 0:0:gemm_dw\n436 0:0:disp_bwd 1:0:gemm_dx\n460 1:0:gemm_dw\n506 0:0:s_dw 1:0:disp_bwd\n",
  "r-0001/ex1": "1 2 1\nPSI\n1\nMAP\n0 1\nSCHEDULE\n0 0:0:s\n16 0:0:disp 1:0:s\n86 0:0:gemm 1:0:disp\n156 0:0:comb 1:0:gemm\n226 0:0:s_bwd 1:0:comb\n296 0:0:comb_bwd 1:0:s_bwd\n366 0:0:gemm_dx 1:0:comb_bwd\n390 0:0:gemm_dw\n436 0:0:disp_bwd 1:0:gemm_dx\n460 1:0:gemm_dw\n506 0:0:s_dw 1:0:disp_bwd\n576 1:0:s_dw\n",
  "r-0004/ex2": "2 2 1\nPSI\n2 1\nMAP\n0 1 0 1\n0 1 1 0\nSCHEDULE\n0 0:0:s 1:0:disp 1:0:s\n400 1:0:gemm\n416 1:0:comb\n816 0:0:disp 1:1:disp 1:1:s\n1216 0:0:gemm 1:1:gemm\n1232 0:0:comb\n1240 1:1:comb\n1632 0:1:s\n1640 1:1:comb_bwd 1:1:s_bwd\n2040 0:1:disp 1:1:gemm_dw 1:1:s_dw\n2064 1:1:gemm_dx\n2440 0:1:gemm 1:1:disp_bwd\n2840 0:1:comb 1:0:comb_bwd 1:0:s_bwd\n3240 0:1:comb_bwd 0:1:s_bwd 1:0:gemm_dx 1:0:s_dw\n3256 1:0:disp_bwd 1:0:gemm_dw\n3640 0:1:gemm_dx 0:1:s_dw\n3664 0:1:disp_bwd 0:1:gemm_dw\n4064 0:0:comb_bwd 0:0:s_bwd\n4464 0:0:gemm_dx 0:0:s_dw\n4480 0:0:disp_bwd 0:0:gemm_dw\n",
  "r-0001/ex2": "2 2 1\nPSI\n2 1\nMAP\n0 1 0 1\n0 1 1 0\nSCHEDULE\n0 0:0:s 1:0:disp 1:0:s\n400 1:0:gemm\n416 1:0:comb\n816 0:0:disp 1:1:disp 1:1:s\n1216 0:0:gemm 1:1:gemm\n1232 0:0:comb\n1240 1:1:comb\n1632 0:1:s\n1640 1:1:comb_bwd 1:1:s_bwd\n2040 0:1:disp 1:1:gemm_dw 1:1:s_dw\n2064 1:1:gemm_dx\n2440 0:1:gemm 1:1:disp_bwd\n2840 0:1:comb 1:0:comb_bwd 1:0:s_bwd\n3240 0:1:comb_bwd 0:1:s_bwd 1:0:gemm_dx 1:0:s_dw\n3256 1:0:disp_bwd 1:0:gemm_dw\n3640 0:1:gemm_dx 0:1:s_dw\n3664 0:1:disp_bwd 0:1:gemm_dw\n4064 0:0:comb_bwd 0:0:s_bwd\n4464 0:0:gemm_dx 0:0:s_dw\n4480 0:0:disp_bwd 0:0:gemm_dw\n",
  "r-0002/ex2": "2 2 1\nPSI\n2 1\nMAP\n0 1 0 1\n0 1 1 0\nSCHEDULE\n0 0:0:s 1:0:disp 1:0:s\n400 1:0:gemm\n416 1:0:comb\n816 0:0:disp 1:1:disp 1:1:s\n1216 0:0:gemm 1:1:gemm\n1232 0:0:comb\n1240 1:1:comb\n1632 0:1:s\n1640 1:1:comb_bwd 1:1:s_bwd\n2040 0:1:disp 1:1:gemm_dw 1:1:s_dw\n2064 1:1:gemm_dx\n2440 0:1:gemm 1:1:disp_bwd\n2840 0:1:comb 1:0:comb_bwd 1:0:s_bwd\n3240 0:1:comb_bwd 0:1:s_bwd 1:0:gemm_dx 1:0:s_dw\n3256 1:0:disp_bwd 1:0:gemm_dw\n3640 0:1:gemm_dx 0:1:s_dw\n3664 0:1:disp_bwd 0:1:gemm_dw\n4064 0:0:comb_bwd 0:0:s_bwd\n4464 0:0:gemm_dx 0:0:s_dw\n4480 0:0:disp_bwd 0:0:gemm_dw\n",
  "r-0011/ex1": "1 2 1\nPSI\n1\nMAP\n0 1\nSCHEDULE\n0 0:0:s\n16 0:0:disp 1:0:s\n86 0:0:gemm 1:0:disp\n156 0:0:comb 1:0:gemm\n226 0:0:s_bwd 1:0:comb\n296 0:0:comb_bwd 1:0:s_bwd\n366 0:0:gemm_dx 1:0:comb_bwd\n390 0:0:gemm_dw\n436 0:0:disp_bwd 1:0:gemm_dx\n460 1:0:gemm_dw\n506 0:0:s_dw 1:0:disp_bwd\n544 1:0:s_dw\n"
 },
 "ops": {
  "r-0004/ex1": [
   {
    "t": 0,
    "mb": 0,
    "l": 0,
    "op": "s",
    "dur": 16,
    "g": 0
   },
   {
    "t": 16,
    "mb": 0,
    "l": 0,
    "op": "disp",
    "dur": 70,
    "g": 0
   },
   {
    "t": 16,
    "mb": 1,
    "l": 0,
    "op": "s",
    "dur": 16,
    "g": 0
   },
   {
    "t": 86,
    "mb": 0,
    "l": 0,
    "op": "gemm",
    "dur": 24,
    "g": 0
   },
   {
    "t": 86,
    "mb": 1,
    "l": 0,
    "op": "disp",
    "dur": 70,
    "g": 0
   },
   {
    "t": 156,
    "mb": 0,
    "l": 0,
    "op": "comb",
    "dur": 70,
    "g": 0
   },
   {
    "t": 156,
    "mb": 1,
    "l": 0,
    "op": "gemm",
    "dur": 24,
    "g": 0
   },
   {
    "t": 226,
    "mb": 0,
    "l": 0,
    "op": "s_bwd",
    "dur": 16,
    "g": 0
   },
   {
    "t": 226,
    "mb": 1,
    "l": 0,
    "op": "comb",
    "dur": 70,
    "g": 0
   },
   {
    "t": 296,
    "mb": 0,
    "l": 0,
    "op": "comb_bwd",
    "dur": 70,
    "g": 0
   },
   {
    "t": 296,
    "mb": 1,
    "l": 0,
    "op": "s_bwd",
    "dur": 16,
    "g": 0
   },
   {
    "t": 366,
    "mb": 0,
    "l": 0,
    "op": "gemm_dx",
    "dur": 24,
    "g": 0
   },
   {
    "t": 366,
    "mb": 1,
    "l": 0,
    "op": "comb_bwd",
    "dur": 70,
    "g": 0
   },
   {
    "t": 390,
    "mb": 0,
    "l": 0,
    "op": "gemm_dw",
    "dur": 24,
    "g": 0
   },
   {
    "t": 436,
    "mb": 0,
    "l": 0,
    "op": "disp_bwd",
    "dur": 70,
    "g": 0
   },
   {
    "t": 436,
    "mb": 1,
    "l": 0,
    "op": "gemm_dx",
    "dur": 24,
    "g": 0
   },
   {
    "t": 460,
    "mb": 1,
    "l": 0,
    "op": "gemm_dw",
    "dur": 24,
    "g": 0
   },
   {
    "t": 506,
    "mb": 0,
    "l": 0,
    "op": "s_dw",
    "dur": 16,
    "g": 0
   },
   {
    "t": 506,
    "mb": 1,
    "l": 0,
    "op": "disp_bwd",
    "dur": 70,
    "g": 0
   },
   {
    "t": 544,
    "mb": 1,
    "l": 0,
    "op": "s_dw",
    "dur": 16,
    "g": 0
   }
  ],
  "r-0003/ex1": [
   {
    "t": 0,
    "mb": 0,
    "l": 0,
    "op": "s",
    "dur": 16,
    "g": 0
   },
   {
    "t": 16,
    "mb": 0,
    "l": 0,
    "op": "disp",
    "dur": 70,
    "g": 0
   },
   {
    "t": 16,
    "mb": 1,
    "l": 0,
    "op": "s",
    "dur": 16,
    "g": 0
   },
   {
    "t": 86,
    "mb": 0,
    "l": 0,
    "op": "gemm",
    "dur": 24,
    "g": 0
   },
   {
    "t": 86,
    "mb": 1,
    "l": 0,
    "op": "disp",
    "dur": 70,
    "g": 0
   },
   {
    "t": 156,
    "mb": 0,
    "l": 0,
    "op": "comb",
    "dur": 70,
    "g": 0
   },
   {
    "t": 156,
    "mb": 1,
    "l": 0,
    "op": "gemm",
    "dur": 24,
    "g": 0
   },
   {
    "t": 226,
    "mb": 0,
    "l": 0,
    "op": "s_bwd",
    "dur": 16,
    "g": 0
   },
   {
    "t": 226,
    "mb": 1,
    "l": 0,
    "op": "comb",
    "dur": 70,
    "g": 0
   },
   {
    "t": 296,
    "mb": 0,
    "l": 0,
    "op": "comb_bwd",
    "dur": 70,
    "g": 0
   },
   {
    "t": 296,
    "mb": 1,
    "l": 0,
    "op": "s_bwd",
    "dur": 16,
    "g": 0
   },
   {
    "t": 366,
    "mb": 0,
    "l": 0,
    "op": "gemm_dx",
    "dur": 24,
    "g": 0
   },
   {
    "t": 366,
    "mb": 1,
    "l": 0,
    "op": "comb_bwd",
    "dur": 70,
    "g": 0
   },
   {
    "t": 390,
    "mb": 0,
    "l": 0,
    "op": "gemm_dw",
    "dur": 24,
    "g": 0
   },
   {
    "t": 436,
    "mb": 0,
    "l": 0,
    "op": "disp_bwd",
    "dur": 70,
    "g": 0
   },
   {
    "t": 436,
    "mb": 1,
    "l": 0,
    "op": "gemm_dx",
    "dur": 24,
    "g": 0
   },
   {
    "t": 460,
    "mb": 1,
    "l": 0,
    "op": "gemm_dw",
    "dur": 24,
    "g": 0
   },
   {
    "t": 506,
    "mb": 0,
    "l": 0,
    "op": "s_dw",
    "dur": 16,
    "g": 0
   },
   {
    "t": 506,
    "mb": 1,
    "l": 0,
    "op": "disp_bwd",
    "dur": 70,
    "g": 0
   },
   {
    "t": 576,
    "mb": 1,
    "l": 0,
    "op": "s_dw",
    "dur": 16,
    "g": 0
   }
  ],
  "r-0003/ex2": [
   {
    "t": 0,
    "mb": 0,
    "l": 0,
    "op": "s",
    "dur": 0,
    "g": 0
   },
   {
    "t": 0,
    "mb": 1,
    "l": 0,
    "op": "disp",
    "dur": 400,
    "g": 0
   },
   {
    "t": 0,
    "mb": 1,
    "l": 0,
    "op": "s",
    "dur": 0,
    "g": 0
   },
   {
    "t": 400,
    "mb": 1,
    "l": 0,
    "op": "gemm",
    "dur": 16,
    "g": 0
   },
   {
    "t": 416,
    "mb": 1,
    "l": 0,
    "op": "comb",
    "dur": 400,
    "g": 0
   },
   {
    "t": 816,
    "mb": 0,
    "l": 0,
    "op": "disp",
    "dur": 400,
    "g": 0
   },
   {
    "t": 816,
    "mb": 1,
    "l": 1,
    "op": "disp",
    "dur": 400,
    "g": 1
   },
   {
    "t": 816,
    "mb": 1,
    "l": 1,
    "op": "s",
    "dur": 0,
    "g": 1
   },
   {
    "t": 1216,
    "mb": 0,
    "l": 0,
    "op": "gemm",
    "dur": 16,
    "g": 0
   },
   {
    "t": 1216,
    "mb": 1,
    "l": 1,
    "op": "gemm",
    "dur": 24,
    "g": 1
   },
   {
    "t": 1232,
    "mb": 0,
    "l": 0,
    "op": "comb",
    "dur": 400,
    "g": 0
   },
   {
    "t": 1240,
    "mb": 1,
    "l": 1,
    "op": "comb",
    "dur": 400,
    "g": 1
   },
   {
    "t": 1632,
    "mb": 0,
    "l": 1,
    "op": "s",
    "dur": 0,
    "g": 1
   },
   {
    "t": 1640,
    "mb": 1,
    "l": 1,
    "op": "comb_bwd",
    "dur": 400,
    "g": 1
   },
   {
    "t": 1640,
    "mb": 1,
    "l": 1,
    "op": "s_bwd",
    "dur": 0,
    "g": 1
   },
   {
    "t": 2040,
    "mb": 0,
    "l": 1,
    "op": "disp",
    "dur": 400,
    "g": 1
   },
   {
    "t": 2040,
    "mb": 1,
    "l": 1,
    "op": "gemm_dw",
    "dur": 24,
    "g": 1
   },
   {
    "t": 2040,
    "mb": 1,
    "l": 1,
    "op": "s_dw",
    "dur": 0,
    "g": 1
   },
   {
    "t": 2064,
    "mb": 1,
    "l": 1,
    "op": "gemm_dx",
    "dur": 24,
    "g": 1
   },
   {
    "t": 2440,
    "mb": 0,
    "l": 1,
    "op": "gemm",
    "dur": 24,
    "g": 1
   },
   {
    "t": 2440,
    "mb": 1,
    "l": 1,
    "op": "disp_bwd",
    "dur": 400,
    "g": 1
   },
   {
    "t": 2840,
    "mb": 0,
    "l": 1,
    "op": "comb",
    "dur": 400,
    "g": 1
   },
   {
    "t": 2840,
    "mb": 1,
    "l": 0,
    "op": "comb_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 2840,
    "mb": 1,
    "l": 0,
    "op": "s_bwd",
    "dur": 0,
    "g": 0
   },
   {
    "t": 3240,
    "mb": 0,
    "l": 1,
    "op": "comb_bwd",
    "dur": 400,
    "g": 1
   },
   {
    "t": 3240,
    "mb": 0,
    "l": 1,
    "op": "s_bwd",
    "dur": 0,
    "g": 1
   },
   {
    "t": 3240,
    "mb": 1,
    "l": 0,
    "op": "gemm_dx",
    "dur": 16,
    "g": 0
   },
   {
    "t": 3240,
    "mb": 1,
    "l": 0,
    "op": "s_dw",
    "dur": 0,
    "g": 0
   },
   {
    "t": 3256,
    "mb": 1,
    "l": 0,
    "op": "disp_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 3256,
    "mb": 1,
    "l": 0,
    "op": "gemm_dw",
    "dur": 16,
    "g": 0
   },
   {
    "t": 3640,
    "mb": 0,
    "l": 1,
    "op": "gemm_dx",
    "dur": 24,
    "g": 1
   },
   {
    "t": 3640,
    "mb": 0,
    "l": 1,
    "op": "s_dw",
    "dur": 0,
    "g": 1
   },
   {
    "t": 3664,
    "mb": 0,
    "l": 1,
    "op": "disp_bwd",
    "dur": 400,
    "g": 1
   },
   {
    "t": 3664,
    "mb": 0,
    "l": 1,
    "op": "gemm_dw",
    "dur": 24,
    "g": 1
   },
   {
    "t": 4064,
    "mb": 0,
    "l": 0,
    "op": "comb_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 4064,
    "mb": 0,
    "l": 0,
    "op": "s_bwd",
    "dur": 0,
    "g": 0
   },
   {
    "t": 4464,
    "mb": 0,
    "l": 0,
    "op": "gemm_dx",
    "dur": 16,
    "g": 0
   },
   {
    "t": 4464,
    "mb": 0,
    "l": 0,
    "op": "s_dw",
    "dur": 0,
    "g": 0
   },
   {
    "t": 4480,
    "mb": 0,
    "l": 0,
    "op": "disp_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 4480,
    "mb": 0,
    "l": 0,
    "op": "gemm_dw",
    "dur": 16,
    "g": 0
   }
  ],
  "r-0003/ex3": [
   {
    "t": 0,
    "mb": 0,
    "l": 0,
    "op": "disp",
    "dur": 500,
    "g": 0
   },
   {
    "t": 0,
    "mb": 0,
    "l": 0,
    "op": "s",
    "dur": 0,
    "g": 0
   },
   {
    "t": 0,
    "mb": 1,
    "l": 0,
    "op": "s",
    "dur": 0,
    "g": 0
   },
   {
    "t": 500,
    "mb": 0,
    "l": 0,
    "op": "gemm",
    "dur": 18,
    "g": 0
   },
   {
    "t": 500,
    "mb": 1,
    "l": 0,
    "op": "disp",
    "dur": 500,
    "g": 0
   },
   {
    "t": 1000,
    "mb": 0,
    "l": 0,
    "op": "comb",
    "dur": 500,
    "g": 0
   },
   {
    "t": 1000,
    "mb": 1,
    "l": 0,
    "op": "gemm",
    "dur": 18,
    "g": 0
   },
   {
    "t": 1500,
    "mb": 0,
    "l": 0,
    "op": "s_bwd",
    "dur": 0,
    "g": 0
   },
   {
    "t": 1500,
    "mb": 1,
    "l": 0,
    "op": "comb",
    "dur": 500,
    "g": 0
   },
   {
    "t": 2000,
    "mb": 0,
    "l": 0,
    "op": "comb_bwd",
    "dur": 500,
    "g": 0
   },
   {
    "t": 2000,
    "mb": 1,
    "l": 0,
    "op": "s_bwd",
    "dur": 0,
    "g": 0
   },
   {
    "t": 2500,
    "mb": 0,
    "l": 0,
    "op": "gemm_dx",
    "dur": 18,
    "g": 0
   },
   {
    "t": 2500,
    "mb": 1,
    "l": 0,
    "op": "comb_bwd",
    "dur": 500,
    "g": 0
   },
   {
    "t": 2518,
    "mb": 0,
    "l": 0,
    "op": "gemm_dw",
    "dur": 0,
    "g": 0
   },
   {
    "t": 3000,
    "mb": 0,
    "l": 0,
    "op": "disp_bwd",
    "dur": 500,
    "g": 0
   },
   {
    "t": 3000,
    "mb": 1,
    "l": 0,
    "op": "gemm_dx",
    "dur": 18,
    "g": 0
   },
   {
    "t": 3018,
    "mb": 1,
    "l": 0,
    "op": "gemm_dw",
    "dur": 0,
    "g": 0
   },
   {
    "t": 3500,
    "mb": 0,
    "l": 0,
    "op": "s_dw",
    "dur": 0,
    "g": 0
   },
   {
    "t": 3500,
    "mb": 1,
    "l": 0,
    "op": "disp_bwd",
    "dur": 500,
    "g": 0
   },
   {
    "t": 4000,
    "mb": 1,
    "l": 0,
    "op": "s_dw",
    "dur": 0,
    "g": 0
   }
  ],
  "r-0003/ex4": [
   {
    "t": 0,
    "mb": 0,
    "l": 0,
    "op": "disp",
    "dur": 400,
    "g": 0
   },
   {
    "t": 0,
    "mb": 0,
    "l": 0,
    "op": "s",
    "dur": 0,
    "g": 0
   },
   {
    "t": 0,
    "mb": 1,
    "l": 0,
    "op": "s",
    "dur": 0,
    "g": 0
   },
   {
    "t": 400,
    "mb": 0,
    "l": 0,
    "op": "gemm",
    "dur": 20,
    "g": 0
   },
   {
    "t": 400,
    "mb": 1,
    "l": 0,
    "op": "disp",
    "dur": 400,
    "g": 0
   },
   {
    "t": 800,
    "mb": 0,
    "l": 0,
    "op": "comb",
    "dur": 400,
    "g": 0
   },
   {
    "t": 800,
    "mb": 1,
    "l": 0,
    "op": "gemm",
    "dur": 20,
    "g": 0
   },
   {
    "t": 1200,
    "mb": 0,
    "l": 0,
    "op": "s_bwd",
    "dur": 0,
    "g": 0
   },
   {
    "t": 1200,
    "mb": 1,
    "l": 0,
    "op": "comb",
    "dur": 400,
    "g": 0
   },
   {
    "t": 1600,
    "mb": 0,
    "l": 0,
    "op": "comb_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 1600,
    "mb": 1,
    "l": 0,
    "op": "s_bwd",
    "dur": 0,
    "g": 0
   },
   {
    "t": 2000,
    "mb": 0,
    "l": 0,
    "op": "gemm_dx",
    "dur": 20,
    "g": 0
   },
   {
    "t": 2000,
    "mb": 1,
    "l": 0,
    "op": "comb_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 2020,
    "mb": 0,
    "l": 0,
    "op": "gemm_dw",
    "dur": 20,
    "g": 0
   },
   {
    "t": 2400,
    "mb": 0,
    "l": 0,
    "op": "disp_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 2400,
    "mb": 1,
    "l": 0,
    "op": "gemm_dx",
    "dur": 20,
    "g": 0
   },
   {
    "t": 2420,
    "mb": 1,
    "l": 0,
    "op": "gemm_dw",
    "dur": 20,
    "g": 0
   },
   {
    "t": 2800,
    "mb": 0,
    "l": 0,
    "op": "s_dw",
    "dur": 0,
    "g": 0
   },
   {
    "t": 2800,
    "mb": 1,
    "l": 0,
    "op": "disp_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 3200,
    "mb": 1,
    "l": 0,
    "op": "s_dw",
    "dur": 0,
    "g": 0
   }
  ],
  "r-0002/ex1": [],
  "r-0001/ex1": [
   {
    "t": 0,
    "mb": 0,
    "l": 0,
    "op": "s",
    "dur": 16,
    "g": 0
   },
   {
    "t": 16,
    "mb": 0,
    "l": 0,
    "op": "disp",
    "dur": 70,
    "g": 0
   },
   {
    "t": 16,
    "mb": 1,
    "l": 0,
    "op": "s",
    "dur": 16,
    "g": 0
   },
   {
    "t": 86,
    "mb": 0,
    "l": 0,
    "op": "gemm",
    "dur": 24,
    "g": 0
   },
   {
    "t": 86,
    "mb": 1,
    "l": 0,
    "op": "disp",
    "dur": 70,
    "g": 0
   },
   {
    "t": 156,
    "mb": 0,
    "l": 0,
    "op": "comb",
    "dur": 70,
    "g": 0
   },
   {
    "t": 156,
    "mb": 1,
    "l": 0,
    "op": "gemm",
    "dur": 24,
    "g": 0
   },
   {
    "t": 226,
    "mb": 0,
    "l": 0,
    "op": "s_bwd",
    "dur": 16,
    "g": 0
   },
   {
    "t": 226,
    "mb": 1,
    "l": 0,
    "op": "comb",
    "dur": 70,
    "g": 0
   },
   {
    "t": 296,
    "mb": 0,
    "l": 0,
    "op": "comb_bwd",
    "dur": 70,
    "g": 0
   },
   {
    "t": 296,
    "mb": 1,
    "l": 0,
    "op": "s_bwd",
    "dur": 16,
    "g": 0
   },
   {
    "t": 366,
    "mb": 0,
    "l": 0,
    "op": "gemm_dx",
    "dur": 24,
    "g": 0
   },
   {
    "t": 366,
    "mb": 1,
    "l": 0,
    "op": "comb_bwd",
    "dur": 70,
    "g": 0
   },
   {
    "t": 390,
    "mb": 0,
    "l": 0,
    "op": "gemm_dw",
    "dur": 24,
    "g": 0
   },
   {
    "t": 436,
    "mb": 0,
    "l": 0,
    "op": "disp_bwd",
    "dur": 70,
    "g": 0
   },
   {
    "t": 436,
    "mb": 1,
    "l": 0,
    "op": "gemm_dx",
    "dur": 24,
    "g": 0
   },
   {
    "t": 460,
    "mb": 1,
    "l": 0,
    "op": "gemm_dw",
    "dur": 24,
    "g": 0
   },
   {
    "t": 506,
    "mb": 0,
    "l": 0,
    "op": "s_dw",
    "dur": 16,
    "g": 0
   },
   {
    "t": 506,
    "mb": 1,
    "l": 0,
    "op": "disp_bwd",
    "dur": 70,
    "g": 0
   },
   {
    "t": 576,
    "mb": 1,
    "l": 0,
    "op": "s_dw",
    "dur": 16,
    "g": 0
   }
  ],
  "r-0004/ex2": [
   {
    "t": 0,
    "mb": 0,
    "l": 0,
    "op": "s",
    "dur": 0,
    "g": 0
   },
   {
    "t": 0,
    "mb": 1,
    "l": 0,
    "op": "disp",
    "dur": 400,
    "g": 0
   },
   {
    "t": 0,
    "mb": 1,
    "l": 0,
    "op": "s",
    "dur": 0,
    "g": 0
   },
   {
    "t": 400,
    "mb": 1,
    "l": 0,
    "op": "gemm",
    "dur": 16,
    "g": 0
   },
   {
    "t": 416,
    "mb": 1,
    "l": 0,
    "op": "comb",
    "dur": 400,
    "g": 0
   },
   {
    "t": 816,
    "mb": 0,
    "l": 0,
    "op": "disp",
    "dur": 400,
    "g": 0
   },
   {
    "t": 816,
    "mb": 1,
    "l": 1,
    "op": "disp",
    "dur": 400,
    "g": 1
   },
   {
    "t": 816,
    "mb": 1,
    "l": 1,
    "op": "s",
    "dur": 0,
    "g": 1
   },
   {
    "t": 1216,
    "mb": 0,
    "l": 0,
    "op": "gemm",
    "dur": 16,
    "g": 0
   },
   {
    "t": 1216,
    "mb": 1,
    "l": 1,
    "op": "gemm",
    "dur": 24,
    "g": 1
   },
   {
    "t": 1232,
    "mb": 0,
    "l": 0,
    "op": "comb",
    "dur": 400,
    "g": 0
   },
   {
    "t": 1240,
    "mb": 1,
    "l": 1,
    "op": "comb",
    "dur": 400,
    "g": 1
   },
   {
    "t": 1632,
    "mb": 0,
    "l": 1,
    "op": "s",
    "dur": 0,
    "g": 1
   },
   {
    "t": 1640,
    "mb": 1,
    "l": 1,
    "op": "comb_bwd",
    "dur": 400,
    "g": 1
   },
   {
    "t": 1640,
    "mb": 1,
    "l": 1,
    "op": "s_bwd",
    "dur": 0,
    "g": 1
   },
   {
    "t": 2040,
    "mb": 0,
    "l": 1,
    "op": "disp",
    "dur": 400,
    "g": 1
   },
   {
    "t": 2040,
    "mb": 1,
    "l": 1,
    "op": "gemm_dw",
    "dur": 24,
    "g": 1
   },
   {
    "t": 2040,
    "mb": 1,
    "l": 1,
    "op": "s_dw",
    "dur": 0,
    "g": 1
   },
   {
    "t": 2064,
    "mb": 1,
    "l": 1,
    "op": "gemm_dx",
    "dur": 24,
    "g": 1
   },
   {
    "t": 2440,
    "mb": 0,
    "l": 1,
    "op": "gemm",
    "dur": 24,
    "g": 1
   },
   {
    "t": 2440,
    "mb": 1,
    "l": 1,
    "op": "disp_bwd",
    "dur": 400,
    "g": 1
   },
   {
    "t": 2840,
    "mb": 0,
    "l": 1,
    "op": "comb",
    "dur": 400,
    "g": 1
   },
   {
    "t": 2840,
    "mb": 1,
    "l": 0,
    "op": "comb_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 2840,
    "mb": 1,
    "l": 0,
    "op": "s_bwd",
    "dur": 0,
    "g": 0
   },
   {
    "t": 3240,
    "mb": 0,
    "l": 1,
    "op": "comb_bwd",
    "dur": 400,
    "g": 1
   },
   {
    "t": 3240,
    "mb": 0,
    "l": 1,
    "op": "s_bwd",
    "dur": 0,
    "g": 1
   },
   {
    "t": 3240,
    "mb": 1,
    "l": 0,
    "op": "gemm_dx",
    "dur": 16,
    "g": 0
   },
   {
    "t": 3240,
    "mb": 1,
    "l": 0,
    "op": "s_dw",
    "dur": 0,
    "g": 0
   },
   {
    "t": 3256,
    "mb": 1,
    "l": 0,
    "op": "disp_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 3256,
    "mb": 1,
    "l": 0,
    "op": "gemm_dw",
    "dur": 16,
    "g": 0
   },
   {
    "t": 3640,
    "mb": 0,
    "l": 1,
    "op": "gemm_dx",
    "dur": 24,
    "g": 1
   },
   {
    "t": 3640,
    "mb": 0,
    "l": 1,
    "op": "s_dw",
    "dur": 0,
    "g": 1
   },
   {
    "t": 3664,
    "mb": 0,
    "l": 1,
    "op": "disp_bwd",
    "dur": 400,
    "g": 1
   },
   {
    "t": 3664,
    "mb": 0,
    "l": 1,
    "op": "gemm_dw",
    "dur": 24,
    "g": 1
   },
   {
    "t": 4064,
    "mb": 0,
    "l": 0,
    "op": "comb_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 4064,
    "mb": 0,
    "l": 0,
    "op": "s_bwd",
    "dur": 0,
    "g": 0
   },
   {
    "t": 4464,
    "mb": 0,
    "l": 0,
    "op": "gemm_dx",
    "dur": 16,
    "g": 0
   },
   {
    "t": 4464,
    "mb": 0,
    "l": 0,
    "op": "s_dw",
    "dur": 0,
    "g": 0
   },
   {
    "t": 4480,
    "mb": 0,
    "l": 0,
    "op": "disp_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 4480,
    "mb": 0,
    "l": 0,
    "op": "gemm_dw",
    "dur": 16,
    "g": 0
   }
  ],
  "r-0001/ex2": [
   {
    "t": 0,
    "mb": 0,
    "l": 0,
    "op": "s",
    "dur": 0,
    "g": 0
   },
   {
    "t": 0,
    "mb": 1,
    "l": 0,
    "op": "disp",
    "dur": 400,
    "g": 0
   },
   {
    "t": 0,
    "mb": 1,
    "l": 0,
    "op": "s",
    "dur": 0,
    "g": 0
   },
   {
    "t": 400,
    "mb": 1,
    "l": 0,
    "op": "gemm",
    "dur": 16,
    "g": 0
   },
   {
    "t": 416,
    "mb": 1,
    "l": 0,
    "op": "comb",
    "dur": 400,
    "g": 0
   },
   {
    "t": 816,
    "mb": 0,
    "l": 0,
    "op": "disp",
    "dur": 400,
    "g": 0
   },
   {
    "t": 816,
    "mb": 1,
    "l": 1,
    "op": "disp",
    "dur": 400,
    "g": 1
   },
   {
    "t": 816,
    "mb": 1,
    "l": 1,
    "op": "s",
    "dur": 0,
    "g": 1
   },
   {
    "t": 1216,
    "mb": 0,
    "l": 0,
    "op": "gemm",
    "dur": 16,
    "g": 0
   },
   {
    "t": 1216,
    "mb": 1,
    "l": 1,
    "op": "gemm",
    "dur": 24,
    "g": 1
   },
   {
    "t": 1232,
    "mb": 0,
    "l": 0,
    "op": "comb",
    "dur": 400,
    "g": 0
   },
   {
    "t": 1240,
    "mb": 1,
    "l": 1,
    "op": "comb",
    "dur": 400,
    "g": 1
   },
   {
    "t": 1632,
    "mb": 0,
    "l": 1,
    "op": "s",
    "dur": 0,
    "g": 1
   },
   {
    "t": 1640,
    "mb": 1,
    "l": 1,
    "op": "comb_bwd",
    "dur": 400,
    "g": 1
   },
   {
    "t": 1640,
    "mb": 1,
    "l": 1,
    "op": "s_bwd",
    "dur": 0,
    "g": 1
   },
   {
    "t": 2040,
    "mb": 0,
    "l": 1,
    "op": "disp",
    "dur": 400,
    "g": 1
   },
   {
    "t": 2040,
    "mb": 1,
    "l": 1,
    "op": "gemm_dw",
    "dur": 24,
    "g": 1
   },
   {
    "t": 2040,
    "mb": 1,
    "l": 1,
    "op": "s_dw",
    "dur": 0,
    "g": 1
   },
   {
    "t": 2064,
    "mb": 1,
    "l": 1,
    "op": "gemm_dx",
    "dur": 24,
    "g": 1
   },
   {
    "t": 2440,
    "mb": 0,
    "l": 1,
    "op": "gemm",
    "dur": 24,
    "g": 1
   },
   {
    "t": 2440,
    "mb": 1,
    "l": 1,
    "op": "disp_bwd",
    "dur": 400,
    "g": 1
   },
   {
    "t": 2840,
    "mb": 0,
    "l": 1,
    "op": "comb",
    "dur": 400,
    "g": 1
   },
   {
    "t": 2840,
    "mb": 1,
    "l": 0,
    "op": "comb_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 2840,
    "mb": 1,
    "l": 0,
    "op": "s_bwd",
    "dur": 0,
    "g": 0
   },
   {
    "t": 3240,
    "mb": 0,
    "l": 1,
    "op": "comb_bwd",
    "dur": 400,
    "g": 1
   },
   {
    "t": 3240,
    "mb": 0,
    "l": 1,
    "op": "s_bwd",
    "dur": 0,
    "g": 1
   },
   {
    "t": 3240,
    "mb": 1,
    "l": 0,
    "op": "gemm_dx",
    "dur": 16,
    "g": 0
   },
   {
    "t": 3240,
    "mb": 1,
    "l": 0,
    "op": "s_dw",
    "dur": 0,
    "g": 0
   },
   {
    "t": 3256,
    "mb": 1,
    "l": 0,
    "op": "disp_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 3256,
    "mb": 1,
    "l": 0,
    "op": "gemm_dw",
    "dur": 16,
    "g": 0
   },
   {
    "t": 3640,
    "mb": 0,
    "l": 1,
    "op": "gemm_dx",
    "dur": 24,
    "g": 1
   },
   {
    "t": 3640,
    "mb": 0,
    "l": 1,
    "op": "s_dw",
    "dur": 0,
    "g": 1
   },
   {
    "t": 3664,
    "mb": 0,
    "l": 1,
    "op": "disp_bwd",
    "dur": 400,
    "g": 1
   },
   {
    "t": 3664,
    "mb": 0,
    "l": 1,
    "op": "gemm_dw",
    "dur": 24,
    "g": 1
   },
   {
    "t": 4064,
    "mb": 0,
    "l": 0,
    "op": "comb_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 4064,
    "mb": 0,
    "l": 0,
    "op": "s_bwd",
    "dur": 0,
    "g": 0
   },
   {
    "t": 4464,
    "mb": 0,
    "l": 0,
    "op": "gemm_dx",
    "dur": 16,
    "g": 0
   },
   {
    "t": 4464,
    "mb": 0,
    "l": 0,
    "op": "s_dw",
    "dur": 0,
    "g": 0
   },
   {
    "t": 4480,
    "mb": 0,
    "l": 0,
    "op": "disp_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 4480,
    "mb": 0,
    "l": 0,
    "op": "gemm_dw",
    "dur": 16,
    "g": 0
   }
  ],
  "r-0002/ex2": [
   {
    "t": 0,
    "mb": 0,
    "l": 0,
    "op": "s",
    "dur": 0,
    "g": 0
   },
   {
    "t": 0,
    "mb": 1,
    "l": 0,
    "op": "disp",
    "dur": 400,
    "g": 0
   },
   {
    "t": 0,
    "mb": 1,
    "l": 0,
    "op": "s",
    "dur": 0,
    "g": 0
   },
   {
    "t": 400,
    "mb": 1,
    "l": 0,
    "op": "gemm",
    "dur": 16,
    "g": 0
   },
   {
    "t": 416,
    "mb": 1,
    "l": 0,
    "op": "comb",
    "dur": 400,
    "g": 0
   },
   {
    "t": 816,
    "mb": 0,
    "l": 0,
    "op": "disp",
    "dur": 400,
    "g": 0
   },
   {
    "t": 816,
    "mb": 1,
    "l": 1,
    "op": "disp",
    "dur": 400,
    "g": 1
   },
   {
    "t": 816,
    "mb": 1,
    "l": 1,
    "op": "s",
    "dur": 0,
    "g": 1
   },
   {
    "t": 1216,
    "mb": 0,
    "l": 0,
    "op": "gemm",
    "dur": 16,
    "g": 0
   },
   {
    "t": 1216,
    "mb": 1,
    "l": 1,
    "op": "gemm",
    "dur": 24,
    "g": 1
   },
   {
    "t": 1232,
    "mb": 0,
    "l": 0,
    "op": "comb",
    "dur": 400,
    "g": 0
   },
   {
    "t": 1240,
    "mb": 1,
    "l": 1,
    "op": "comb",
    "dur": 400,
    "g": 1
   },
   {
    "t": 1632,
    "mb": 0,
    "l": 1,
    "op": "s",
    "dur": 0,
    "g": 1
   },
   {
    "t": 1640,
    "mb": 1,
    "l": 1,
    "op": "comb_bwd",
    "dur": 400,
    "g": 1
   },
   {
    "t": 1640,
    "mb": 1,
    "l": 1,
    "op": "s_bwd",
    "dur": 0,
    "g": 1
   },
   {
    "t": 2040,
    "mb": 0,
    "l": 1,
    "op": "disp",
    "dur": 400,
    "g": 1
   },
   {
    "t": 2040,
    "mb": 1,
    "l": 1,
    "op": "gemm_dw",
    "dur": 24,
    "g": 1
   },
   {
    "t": 2040,
    "mb": 1,
    "l": 1,
    "op": "s_dw",
    "dur": 0,
    "g": 1
   },
   {
    "t": 2064,
    "mb": 1,
    "l": 1,
    "op": "gemm_dx",
    "dur": 24,
    "g": 1
   },
   {
    "t": 2440,
    "mb": 0,
    "l": 1,
    "op": "gemm",
    "dur": 24,
    "g": 1
   },
   {
    "t": 2440,
    "mb": 1,
    "l": 1,
    "op": "disp_bwd",
    "dur": 400,
    "g": 1
   },
   {
    "t": 2840,
    "mb": 0,
    "l": 1,
    "op": "comb",
    "dur": 400,
    "g": 1
   },
   {
    "t": 2840,
    "mb": 1,
    "l": 0,
    "op": "comb_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 2840,
    "mb": 1,
    "l": 0,
    "op": "s_bwd",
    "dur": 0,
    "g": 0
   },
   {
    "t": 3240,
    "mb": 0,
    "l": 1,
    "op": "comb_bwd",
    "dur": 400,
    "g": 1
   },
   {
    "t": 3240,
    "mb": 0,
    "l": 1,
    "op": "s_bwd",
    "dur": 0,
    "g": 1
   },
   {
    "t": 3240,
    "mb": 1,
    "l": 0,
    "op": "gemm_dx",
    "dur": 16,
    "g": 0
   },
   {
    "t": 3240,
    "mb": 1,
    "l": 0,
    "op": "s_dw",
    "dur": 0,
    "g": 0
   },
   {
    "t": 3256,
    "mb": 1,
    "l": 0,
    "op": "disp_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 3256,
    "mb": 1,
    "l": 0,
    "op": "gemm_dw",
    "dur": 16,
    "g": 0
   },
   {
    "t": 3640,
    "mb": 0,
    "l": 1,
    "op": "gemm_dx",
    "dur": 24,
    "g": 1
   },
   {
    "t": 3640,
    "mb": 0,
    "l": 1,
    "op": "s_dw",
    "dur": 0,
    "g": 1
   },
   {
    "t": 3664,
    "mb": 0,
    "l": 1,
    "op": "disp_bwd",
    "dur": 400,
    "g": 1
   },
   {
    "t": 3664,
    "mb": 0,
    "l": 1,
    "op": "gemm_dw",
    "dur": 24,
    "g": 1
   },
   {
    "t": 4064,
    "mb": 0,
    "l": 0,
    "op": "comb_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 4064,
    "mb": 0,
    "l": 0,
    "op": "s_bwd",
    "dur": 0,
    "g": 0
   },
   {
    "t": 4464,
    "mb": 0,
    "l": 0,
    "op": "gemm_dx",
    "dur": 16,
    "g": 0
   },
   {
    "t": 4464,
    "mb": 0,
    "l": 0,
    "op": "s_dw",
    "dur": 0,
    "g": 0
   },
   {
    "t": 4480,
    "mb": 0,
    "l": 0,
    "op": "disp_bwd",
    "dur": 400,
    "g": 0
   },
   {
    "t": 4480,
    "mb": 0,
    "l": 0,
    "op": "gemm_dw",
    "dur": 16,
    "g": 0
   }
  ],
  "r-0011/ex1": {
   "items": [
    {
     "t": 0,
     "mb": 0,
     "l": 0,
     "op": "s",
     "dur": 16,
     "g": 0
    },
    {
     "t": 16,
     "mb": 0,
     "l": 0,
     "op": "disp",
     "dur": 70,
     "g": 0
    },
    {
     "t": 16,
     "mb": 1,
     "l": 0,
     "op": "s",
     "dur": 16,
     "g": 0
    },
    {
     "t": 86,
     "mb": 0,
     "l": 0,
     "op": "gemm",
     "dur": 24,
     "g": 0
    },
    {
     "t": 86,
     "mb": 1,
     "l": 0,
     "op": "disp",
     "dur": 70,
     "g": 0
    },
    {
     "t": 156,
     "mb": 0,
     "l": 0,
     "op": "comb",
     "dur": 70,
     "g": 0
    },
    {
     "t": 156,
     "mb": 1,
     "l": 0,
     "op": "gemm",
     "dur": 24,
     "g": 0
    },
    {
     "t": 226,
     "mb": 0,
     "l": 0,
     "op": "s_bwd",
     "dur": 16,
     "g": 0
    },
    {
     "t": 226,
     "mb": 1,
     "l": 0,
     "op": "comb",
     "dur": 70,
     "g": 0
    },
    {
     "t": 296,
     "mb": 0,
     "l": 0,
     "op": "comb_bwd",
     "dur": 70,
     "g": 0
    },
    {
     "t": 296,
     "mb": 1,
     "l": 0,
     "op": "s_bwd",
     "dur": 16,
     "g": 0
    },
    {
     "t": 366,
     "mb": 0,
     "l": 0,
     "op": "gemm_dx",
     "dur": 24,
     "g": 0
    },
    {
     "t": 366,
     "mb": 1,
     "l": 0,
     "op": "comb_bwd",
     "dur": 70,
     "g": 0
    },
    {
     "t": 390,
     "mb": 0,
     "l": 0,
     "op": "gemm_dw",
     "dur": 24,
     "g": 0
    },
    {
     "t": 436,
     "mb": 0,
     "l": 0,
     "op": "disp_bwd",
     "dur": 70,
     "g": 0
    },
    {
     "t": 436,
     "mb": 1,
     "l": 0,
     "op": "gemm_dx",
     "dur": 24,
     "g": 0
    },
    {
     "t": 460,
     "mb": 1,
     "l": 0,
     "op": "gemm_dw",
     "dur": 24,
     "g": 0
    },
    {
     "t": 506,
     "mb": 0,
     "l": 0,
     "op": "s_dw",
     "dur": 16,
     "g": 0
    },
    {
     "t": 506,
     "mb": 1,
     "l": 0,
     "op": "disp_bwd",
     "dur": 70,
     "g": 0
    },
    {
     "t": 544,
     "mb": 1,
     "l": 0,
     "op": "s_dw",
     "dur": 16,
     "g": 0
    }
   ],
   "total": 640000,
   "next_cursor": 4000,
   "note": "切片演示：items 为 20 条真实 ops，total 放大到 640000 以演示 Gantt 截断徽标与按 next_cursor 翻页；仅 ?demo=1 可见。"
  }
 },
 "evaluate": {
  "ex1": {
   "1 2 1\nPSI\n1\nMAP\n0 1\nSCHEDULE\n0 0:0:s\n16 0:0:disp 1:0:s\n86 0:0:gemm 1:0:disp\n156 0:0:comb 1:0:gemm\n226 0:0:s_bwd 1:0:comb\n296 0:0:comb_bwd 1:0:s_bwd\n366 0:0:gemm_dx 1:0:comb_bwd\n390 0:0:gemm_dw\n436 0:0:disp_bwd 1:0:gemm_dx\n460 1:0:gemm_dw\n506 0:0:s_dw 1:0:disp_bwd\n576 1:0:s_dw\n": {
    "ok": true,
    "time": 592,
    "lb": 560,
    "groups": [
     {
      "v": 0,
      "mexp": 20,
      "movl": 2,
      "mact": 1,
      "limit": 39
     }
    ],
    "engines": [
     {
      "v": 0,
      "comp": 240,
      "comm": 560,
      "comm_first": 16,
      "comm_last": 576
     }
    ],
    "grid": {
     "V": 1,
     "P": 2,
     "D": 1
    },
    "K": 1,
    "psi": [],
    "errors": []
   },
   "1 2 1\nPSI\n1\nMAP\n0 1\nSCHEDULE\n0 0:0:s\n16 0:0:disp 1:0:s\n86 0:0:gemm 1:0:disp\n156 0:0:comb 1:0:gemm\n226 0:0:s_bwd 1:0:comb\n296 0:0:comb_bwd 1:0:s_bwd\n366 0:0:gemm_dx 1:0:comb_bwd\n390 0:0:gemm_dw\n436 0:0:disp_bwd 1:0:gemm_dx\n460 1:0:gemm_dw\n506 0:0:s_dw 1:0:disp_bwd\n544 1:0:s_dw\n": {
    "ok": true,
    "time": 576,
    "lb": 560,
    "groups": [
     {
      "v": 0,
      "mexp": 20,
      "movl": 2,
      "mact": 1,
      "limit": 39
     }
    ],
    "engines": [
     {
      "v": 0,
      "comp": 240,
      "comm": 560,
      "comm_first": 16,
      "comm_last": 576
     }
    ],
    "grid": {
     "V": 1,
     "P": 2,
     "D": 1
    },
    "K": 1,
    "psi": [],
    "errors": []
   },
   "1 2 1\nPSI\n1\nMAP\n0 1\nSCHEDULE\n0 0:0:s\n16 0:0:disp 1:0:s\n86 0:0:gemm 1:0:disp\n156 0:0:comb 1:0:gemm\n226 0:0:s_bwd 1:0:comb\n296 0:0:comb_bwd 1:0:s_bwd\n366 0:0:gemm_dx 1:0:comb_bwd\n390 0:0:gemm_dw\n436 0:0:disp_bwd 1:0:gemm_dx\n460 1:0:gemm_dw\n506 0:0:s_dw 1:0:disp_bwd\n": {
    "ok": false,
    "time": null,
    "lb": 560,
    "groups": [],
    "engines": [],
    "grid": {
     "V": 1,
     "P": 2,
     "D": 1
    },
    "K": 1,
    "psi": [],
    "errors": [
     {
      "category": "missing",
      "message": "调度缺少操作 1:0:s_dw（每层每 microbatch 需十个操作，题面 §3.2）",
      "t": null,
      "at": "1:0:s_dw"
     }
    ]
   }
  },
  "ex2": {
   "2 2 1\nPSI\n2 1\nMAP\n0 1 0 1\n0 1 1 0\nSCHEDULE\n0 0:0:s 1:0:disp 1:0:s\n400 1:0:gemm\n416 1:0:comb\n816 0:0:disp 1:1:disp 1:1:s\n1216 0:0:gemm 1:1:gemm\n1232 0:0:comb\n1240 1:1:comb\n1632 0:1:s\n1640 1:1:comb_bwd 1:1:s_bwd\n2040 0:1:disp 1:1:gemm_dw 1:1:s_dw\n2064 1:1:gemm_dx\n2440 0:1:gemm 1:1:disp_bwd\n2840 0:1:comb 1:0:comb_bwd 1:0:s_bwd\n3240 0:1:comb_bwd 0:1:s_bwd 1:0:gemm_dx 1:0:s_dw\n3256 1:0:disp_bwd 1:0:gemm_dw\n3640 0:1:gemm_dx 0:1:s_dw\n3664 0:1:disp_bwd 0:1:gemm_dw\n4064 0:0:comb_bwd 0:0:s_bwd\n4464 0:0:gemm_dx 0:0:s_dw\n4480 0:0:disp_bwd 0:0:gemm_dw\n": {
    "ok": true,
    "time": 4880,
    "lb": 3200,
    "groups": [
     {
      "v": 0,
      "mexp": 40,
      "movl": 2,
      "mact": 2,
      "limit": 79
     },
     {
      "v": 1,
      "mexp": 40,
      "movl": 2,
      "mact": 1,
      "limit": 79
     }
    ],
    "engines": [
     {
      "v": 0,
      "comp": 96,
      "comm": 3200,
      "comm_first": 0,
      "comm_last": 4880
     },
     {
      "v": 1,
      "comp": 144,
      "comm": 3200,
      "comm_first": 816,
      "comm_last": 4064
     }
    ],
    "grid": {
     "V": 2,
     "P": 2,
     "D": 1
    },
    "K": 2,
    "psi": [
     1
    ],
    "errors": []
   }
  }
 },
 "events": [
  {
   "type": "run.queued",
   "data": {
    "run_id": "r-0009",
    "state": "queued",
    "done": 0,
    "total": 6
   }
  },
  {
   "type": "run.running",
   "data": {
    "run_id": "r-0009",
    "state": "running",
    "done": 2,
    "total": 6
   }
  },
  {
   "type": "run.running",
   "data": {
    "run_id": "r-0009",
    "state": "running",
    "done": 4,
    "total": 6
   }
  },
  {
   "type": "run.timeout",
   "data": {
    "run_id": "r-0009",
    "state": "timeout",
    "done": 4,
    "total": 6
   }
  }
 ],
 "meta": {
  "service": "judge",
  "version": "2.0.0",
  "ledger_lines": 8,
  "versions": 4,
  "active_runs": [
   {
    "run_id": "r-0010",
    "state": "queued",
    "done": 0,
    "total": 6
   },
   {
    "run_id": "r-0008",
    "state": "running",
    "done": 3,
    "total": 6
   }
  ],
  "last_run": {
   "run_id": "r-0010",
   "state": "queued",
   "version": "v0.7-rc",
   "commit": "91be2aa",
   "created_at": "2026-10-20T12:42:00Z"
  }
 }
};
