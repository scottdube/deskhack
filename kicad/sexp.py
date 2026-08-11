"""Minimal s-expression reader/writer for KiCad files."""


def parse(text):
    """Return nested lists. Atoms stay as strings; quoted strings keep quotes."""
    out, stack, i, n = [], [], 0, len(text)
    cur = out
    while i < n:
        c = text[i]
        if c == "(":
            new = []
            cur.append(new)
            stack.append(cur)
            cur = new
            i += 1
        elif c == ")":
            cur = stack.pop()
            i += 1
        elif c == '"':
            j = i + 1
            buf = ['"']
            while j < n:
                if text[j] == "\\":
                    buf.append(text[j:j + 2])
                    j += 2
                    continue
                buf.append(text[j])
                if text[j] == '"':
                    j += 1
                    break
                j += 1
            cur.append("".join(buf))
            i = j
        elif c.isspace():
            i += 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in "()":
                j += 1
            cur.append(text[i:j])
            i = j
    return out[0]


def find(node, tag):
    return [x for x in node if isinstance(x, list) and x and x[0] == tag]


def first(node, tag):
    got = find(node, tag)
    return got[0] if got else None


def dump(node, indent=0):
    if not isinstance(node, list):
        return node
    pad = "\t" * indent
    head = node[0] if node and not isinstance(node[0], list) else ""
    simple = all(not isinstance(x, list) for x in node)
    if simple:
        return pad + "(" + " ".join(node) + ")"
    parts = [pad + "(" + head]
    for x in node[1:]:
        if isinstance(x, list):
            parts.append(dump(x, indent + 1))
        else:
            parts[-1] += " " + x
    parts.append(pad + ")")
    return "\n".join(parts)
