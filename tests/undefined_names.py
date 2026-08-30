#!/usr/bin/env python3
"""Fail if a Python module references a global name it never defines or imports.

WHY: `py_compile` does NOT catch this. A name lookup is resolved at RUNTIME, so a module full
of undefined references compiles perfectly and then raises NameError only on the code path that
touches it — which, for an MCP tool, means it fails in front of a user, mid-task.

Two of these were written into server.py inside ten minutes while adding one function:
`PLUGIN_ROOT` (never defined) and `re` (never imported). Both passed py_compile. The Lua side of
this project already has an equivalent check (tests/undefined_helpers.py) because the same class
of bug cost two game restarts there; Python had no equivalent until now.

Uses the compiler's own symbol tables rather than regex, so it understands scopes, comprehensions,
globals/nonlocals and star-imports.

Usage: undefined_names.py <file.py> [file.py ...]
"""
import builtins
import symtable
import sys

BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__", "__package__"}


def module_defined(st):
    """Names bound at module scope: assignments, defs, classes, imports."""
    names = set()
    for sym in st.get_symbols():
        if sym.is_assigned() or sym.is_imported() or sym.is_parameter():
            names.add(sym.get_name())
    return names


def walk(st, defined, reported, path):
    """Report free names in nested scopes that nothing in an enclosing scope defines."""
    for child in st.get_children():
        local = {s.get_name() for s in child.get_symbols()
                 if s.is_assigned() or s.is_parameter() or s.is_imported()}
        for sym in child.get_symbols():
            name = sym.get_name()
            if name in local or name in defined or name in BUILTINS or name in reported:
                continue
            # a referenced-but-nowhere-bound global is the bug we are hunting
            if sym.is_referenced() and sym.is_global():
                reported.add(name)
                print("  \033[31mFAIL\033[0m  %s: '%s' is referenced but never defined or "
                      "imported" % (path, name))
        walk(child, defined | local, reported, path)


def main() -> int:
    bad = False
    for path in sys.argv[1:]:
        src = open(path).read()
        st = symtable.symtable(src, path, "exec")
        defined = module_defined(st)
        reported = set()
        walk(st, defined, reported, path)
        # module scope itself
        for sym in st.get_symbols():
            n = sym.get_name()
            if (sym.is_referenced() and not sym.is_assigned() and not sym.is_imported()
                    and n not in BUILTINS and n not in reported):
                reported.add(n)
                print("  \033[31mFAIL\033[0m  %s: '%s' is referenced but never defined or "
                      "imported" % (path, n))
        if reported:
            bad = True
    if not bad:
        print("  \033[32mPASS\033[0m  every referenced global name is defined or imported")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
