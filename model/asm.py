"""Assembler for the engine instruction set (docs/isa.md, v0.1).

    prog = assemble(text)       ->  Program(words, wrap_bottom, wrap_top, side_count, labels)

Directives: .side_set N [opt]   .wrap_target   .wrap
Syntax per line:  [label:]  op args  [side N]  [[D]]   ; comment
"""
import re
from dataclasses import dataclass, field

OPS = {"jmp": 0, "wait": 1, "in": 2, "out": 3, "push": 4, "pull": 4, "mov": 5, "set": 6, "time": 7}
JMP_COND = {"": 0, "!x": 1, "x--": 2, "!y": 3, "y--": 4, "x!=y": 5, "pin": 6, "!osre": 7}
IN_SRC = {"pins": 0, "x": 1, "y": 2, "null": 3, "isr": 4, "osr": 5, "sw": 6}
OUT_DST = {"pins": 0, "x": 1, "y": 2, "null": 3, "pindirs": 4, "pc": 5, "isr": 6}
MOV_DST = {"pins": 0, "x": 1, "y": 2, "pc": 5, "isr": 6, "osr": 7}
MOV_SRC = {"pins": 0, "x": 1, "y": 2, "null": 3, "sw": 4, "status": 5, "isr": 6, "osr": 7}
SET_DST = {"pins": 0, "x": 1, "y": 2, "pindirs": 4}
TIME_ACT = {"start": 0, "stop": 1, "capture x": 2, "capture y": 3, "capture isr": 4}


class AsmError(Exception):
    pass


@dataclass
class Program:
    words: list
    wrap_bottom: int
    wrap_top: int
    side_count: int
    side_opt: bool = False
    labels: dict = field(default_factory=dict)


def _num(s, labels=None):
    s = s.strip()
    if labels is not None and s in labels:
        return labels[s]
    try:
        return int(s, 0)
    except ValueError:
        raise AsmError(f"not a number or label: {s!r}")


def assemble(text):
    side_count = 0
    side_opt = False
    lines = []          # (lineno, label-free source)
    labels = {}
    wrap_bottom = wrap_top = None
    # pass 1: labels and directives
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split(";")[0].strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z_]\w*):\s*(.*)$", line)
        if m:
            labels[m.group(1)] = len(lines)
            line = m.group(2).strip()
            if not line:
                continue
        if line.startswith(".side_set"):
            parts = line.split()
            side_count = _num(parts[1])
            side_opt = len(parts) > 2 and parts[2] == "opt"
            if not 0 <= side_count <= 2:
                raise AsmError(f"line {lineno}: side_set must be 0-2")
            continue
        if line == ".wrap_target":
            wrap_bottom = len(lines)
            continue
        if line == ".wrap":
            wrap_top = len(lines) - 1
            continue
        lines.append((lineno, line))
    if len(lines) > 32:
        raise AsmError(f"{len(lines)} instructions: the engine holds 32")
    words = [_encode(lineno, line, labels, side_count, side_opt) for lineno, line in lines]
    return Program(words,
                   0 if wrap_bottom is None else wrap_bottom,
                   len(words) - 1 if wrap_top is None else wrap_top,
                   side_count, side_opt, labels)


def _encode(lineno, line, labels, side_count, side_opt=False):
    try:
        # pull off [delay] and side N from the end
        delay = 0
        m = re.search(r"\[\s*(\w+)\s*\]\s*$", line)
        if m:
            delay = _num(m.group(1))
            line = line[:m.start()].strip()
        side = None
        m = re.search(r"\bside\s+(\w+)\s*$", line)
        if m:
            side = _num(m.group(1))
            line = line[:m.start()].strip()
        delay_bits = 5 - side_count - (1 if side_opt else 0)
        if not 0 <= delay < (1 << delay_bits):
            raise AsmError(f"delay {delay} does not fit {delay_bits} bits")
        if side_count == 0 and side is not None:
            raise AsmError("side-set used but .side_set is 0")
        enable = side is not None
        if side is None:
            side = 0
            if side_count and not side_opt:
                raise AsmError("every instruction needs 'side N' (use .side_set N opt to make it optional)")
        if not 0 <= side < (1 << side_count):
            raise AsmError(f"side value {side} does not fit {side_count} bits")
        middle = (side << delay_bits) | delay
        if side_opt:
            middle |= (1 if enable else 0) << 4

        op, _, rest = line.partition(" ")
        op = op.lower()
        args = [a.strip() for a in rest.split(",")] if rest.strip() else []
        if op not in OPS:
            raise AsmError(f"unknown instruction {op!r}")
        a = _args(op, args, labels)
        return (OPS[op] << 13) | (middle << 8) | a
    except AsmError as e:
        raise AsmError(f"line {lineno}: {e}") from None


def _count(s):
    n = _num(s)
    if not 1 <= n <= 16:
        raise AsmError(f"bit count {n} must be 1-16")
    return n & 15          # 16 is encoded as 0


def _args(op, args, labels):
    if op == "jmp":
        cond, target = ("", args[0]) if len(args) == 1 else (args[0].replace(" ", "").lower(), args[1])
        if cond not in JMP_COND:
            raise AsmError(f"unknown jump condition {cond!r}")
        addr = _num(target, labels)
        return (JMP_COND[cond] << 5) | (addr & 31)
    if op == "wait":
        level = _num(args[0])
        kind, idx = args[1].split()
        timeout = 1 if len(args) > 2 and args[2].lower() == "timeout" else 0
        rel = {"pin": 0, "rel": 1}[kind.lower()]
        return (level << 7) | (timeout << 6) | (rel << 5) | (_num(idx) & 31)
    if op == "in":
        return (IN_SRC[args[0].lower()] << 5) | _count(args[1])
    if op == "out":
        return (OUT_DST[args[0].lower()] << 5) | _count(args[1])
    if op in ("push", "pull"):
        words = " ".join(args).lower().split()
        is_pull = 1 if op == "pull" else 0
        cond = 1 if ("iffull" in words or "ifempty" in words) else 0
        block = 0 if "noblock" in words else 1
        return (is_pull << 7) | (cond << 6) | (block << 5)
    if op == "mov":
        dst = MOV_DST[args[0].lower()]
        src = args[1].replace(" ", "").lower()
        mop = 0
        if src.startswith("~") or src.startswith("!"):
            mop, src = 1, src[1:]
        elif src.startswith("::"):
            mop, src = 2, src[2:]
        return (dst << 5) | (mop << 3) | MOV_SRC[src]
    if op == "set":
        v = _num(args[1])
        if not 0 <= v <= 31:
            raise AsmError("set value must be 0-31")
        return (SET_DST[args[0].lower()] << 5) | v
    if op == "time":
        act = " ".join(args).lower()
        if act not in TIME_ACT:
            raise AsmError(f"unknown time action {act!r}")
        return TIME_ACT[act] << 5
    raise AsmError(op)
