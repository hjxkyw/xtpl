#!/usr/bin/env python3
# --------------------------------------------------------------------------------
# xtpl_transpiler.py
# --------------------------------------------------------------------------------

import difflib
import pathlib
import re
import sys

# Read from VERSION.TXT beside this file when it is there, so the number lives
# in one place. The fallback is for a transpiler copied out on its own.
def _version():
  stamp = pathlib.Path(__file__).with_name("VERSION.TXT")
  try:
    return stamp.read_text().strip() or "unknown"
  except OSError:
    return "unknown"

# --------------------------------------------------------------------------------
# String / comment masking
#
# Every line-scanning regex in this transpiler used to run against the raw source,
# so identifiers, "if", "fallback" and friends were rewritten inside string
# literals and comments. We mask those regions with a Unicode private-use
# sentinel (not a \w character, so identifier scans skip it) and restore them
# just before emitting.
# --------------------------------------------------------------------------------

_MASK_BASE = 0xE000
_re_mask_token = re.compile(r'\x00([\ue000-\uf8ff])\x00')


def _mask_token(index):
  return "\x00" + chr(_MASK_BASE + index) + "\x00"


def mask_literals(text, parts=None):
  """Replace string literals and trailing // comments with opaque tokens."""
  if parts is None:
    parts = []
  out = []
  i = 0
  n = len(text)
  while i < n:
    char = text[i]
    if char in ('"', "'"):
      quote = char
      j = i + 1
      while j < n and text[j] != quote:
        j += 1
      end = j + 1 if j < n else n
      out.append(_mask_token(len(parts)))
      parts.append(text[i:end])
      i = end
    elif char == '/' and text.startswith("//", i):
      out.append(_mask_token(len(parts)))
      parts.append(text[i:])
      i = n
    else:
      out.append(char)
      i += 1
  return "".join(out), parts


def unmask_literals(text, parts):
  if not parts:
    return text
  return _re_mask_token.sub(lambda m: parts[ord(m.group(1)) - _MASK_BASE], text)


# --------------------------------------------------------------------------------
# Balanced-delimiter helpers
#
# Argument lists are extracted by counting delimiters rather than by non-greedy
# regex, so nested calls such as take("x" + cValToChar(k)) survive intact.
# --------------------------------------------------------------------------------

CONST_NOTE = ("// <const> fixes the name, not the contents: a callee that\n  //          receives this array can still change its elements")

# Spelled out on a <const> array, because the guarantee is shallower than the
# word suggests.
CONST_NOTE = ("// <const> fixes the name, not the contents: a callee given "
              "this array can still change its elements")

_OPENERS = "([{"
_CLOSERS = ")]}"


def extract_parens(text, open_idx):
  """text[open_idx] must be '('. Returns (inner_text, index_after_close)."""
  if open_idx >= len(text) or text[open_idx] != '(':
    return None, -1
  depth = 0
  for i in range(open_idx, len(text)):
    char = text[i]
    if char == '(':
      depth += 1
    elif char == ')':
      depth -= 1
      if depth == 0:
        return text[open_idx + 1:i], i + 1
  return None, -1


def split_top_level(text, sep=","):
  """Split on sep at nesting depth zero."""
  parts = []
  depth = 0
  start = 0
  i = 0
  while i < len(text):
    char = text[i]
    if char in _OPENERS:
      depth += 1
    elif char in _CLOSERS:
      depth -= 1
    elif depth == 0 and text.startswith(sep, i):
      parts.append(text[start:i])
      i += len(sep)
      start = i
      continue
    i += 1
  parts.append(text[start:])
  return [p.strip() for p in parts]


# --------------------------------------------------------------------------------
# Feed-chain nodes
#
# The '|>' scanner used to count delimiters by hand in three separate places,
# each with a guard on the previous character so that the '||' opening a
# zero-argument code block could not be read as a feed. All of that is now one
# tokenizer -- the XtplExpr grammar when rakulang is installed, expr_tokens
# below when it is not -- producing a flat list of nodes:
#
#   {"k": "text",  "t": ...}    anything that is not structure
#   {"k": "feed"}               a '|>'
#   {"k": "comma"}              a separator, at whatever depth it sits
#   {"k": "group", "open": ..., "head": ..., "items": [...], "close": ...}
#
# A group's 'head' is a code block's parameter list, '|x, y|' or '||',
# consumed by the brace that opens it. That is what removes the
# previous-character guard, and it is also what tells '{|o| o:nValue}' from
# the array literal '{1, 2}' -- a distinction the line scanner could not make.
#
# 'close' is empty when the group was never closed, so rendering a node list
# reproduces the text it was built from and never invents a bracket.
# --------------------------------------------------------------------------------

_NODE_CLOSERS = {"(": ")", "[": "]", "{": "}"}


def expr_tokens(text, pos=0, closer=None):
  """The fallback tokenizer. Returns (nodes, index_after, closer_was_found)."""
  nodes = []
  buffer = []

  def flush():
    if buffer:
      nodes.append({"k": "text", "t": "".join(buffer)})
      del buffer[:]

  i = pos
  while i < len(text):
    char = text[i]
    if closer and char == closer:
      flush()
      return nodes, i + 1, True
    if char in _NODE_CLOSERS:
      flush()
      head = ""
      start = i + 1
      # A '|' straight after '{' opens a code block's parameter list. Taking
      # it here is what stops '{||' from reading as a feed.
      if char == "{" and text.startswith("|", start):
        end = text.find("|", start + 1)
        if end >= 0:
          head, start = text[start:end + 1], end + 1
      items, start, closed = expr_tokens(text, start, _NODE_CLOSERS[char])
      nodes.append({"k": "group", "open": char, "head": head, "items": items,
                    "close": _NODE_CLOSERS[char] if closed else ""})
      i = start
      continue
    if text.startswith("|>", i):
      flush()
      nodes.append({"k": "feed"})
      i += 2
      continue
    if char == ",":
      flush()
      nodes.append({"k": "comma"})
      i += 1
      continue
    buffer.append(char)
    i += 1
  flush()
  return nodes, i, False


def render_nodes(nodes):
  """The text a node list was built from, exactly."""
  out = []
  for node in nodes:
    kind = node["k"]
    if kind == "text":
      out.append(node["t"])
    elif kind == "feed":
      out.append("|>")
    elif kind == "comma":
      out.append(",")
    else:
      out.append(node["open"] + node["head"] +
                 render_nodes(node["items"]) + node["close"])
  return "".join(out)


def feed_segments(nodes):
  """The chain's segments, split on the feeds at this level.

  Commas are ordinary here: a chain is divided by '|>' and nothing else. They
  matter only to feed_slice, which uses them to bound an argument.
  """
  segments = []
  current = []
  for node in nodes:
    if node["k"] == "feed":
      segments.append(render_nodes(current).strip())
      current = []
    else:
      current.append(node)
  segments.append(render_nodes(current).strip())
  return segments


def feed_anywhere(nodes):
  return any(node["k"] == "feed" or
             (node["k"] == "group" and feed_anywhere(node["items"]))
             for node in nodes)


def feed_outside_block(nodes):
  """A '|>' that survived the feed pass without a code block to explain it."""
  return any(node["k"] == "feed" or
             (node["k"] == "group" and node["open"] != "{" and
              feed_outside_block(node["items"]))
             for node in nodes)


def feed_in_block(nodes):
  """A '|>' inside a code block, at any depth.

  The block's body runs later; lifting a stage out of it would run that stage
  now. The scanner this replaces could not see the containing block, so it
  lifted anyway and emitted a call with a block delimiter for an argument.
  """
  for node in nodes:
    if node["k"] != "group":
      continue
    if node["head"] and feed_anywhere(node["items"]):
      return True
    if feed_in_block(node["items"]):
      return True
  return False


def _feed_slice_bounds(nodes, index):
  """The comma-delimited run of nodes holding nodes[index]."""
  start, end = 0, len(nodes)
  for i in range(index, -1, -1):
    if nodes[i]["k"] == "comma":
      start = i + 1
      break
  for i in range(index, len(nodes)):
    if nodes[i]["k"] == "comma":
      end = i
      break
  return start, end


def split_nodes(nodes, kind="comma"):
  """The node list divided at the separators sitting at this level."""
  parts, current = [], []
  for node in nodes:
    if node["k"] == kind:
      parts.append(current)
      current = []
    else:
      current.append(node)
  parts.append(current)
  return parts


def split_nodes_text(nodes, sep):
  """Divide at the first 'sep' at this level, or None.

  A separator inside a nested group belongs to that group's items, so it is
  never a text node here -- which is the whole reason this needs no depth
  counting.
  """
  for index, node in enumerate(nodes):
    if node["k"] != "text" or sep not in node["t"]:
      continue
    at = node["t"].index(sep)
    return (nodes[:index] + [{"k": "text", "t": node["t"][:at]}],
            [{"k": "text", "t": node["t"][at + len(sep):]}] + nodes[index + 1:])
  return None


def hash_subscript(nodes):
  """The first 'name{...}' subscript, as (before, holder, key, after, closed).

  A brace directly after a name is a hash access -- AdvPL never puts one
  there. The grammar has already separated a code block from a literal by its
  parameter list, so a subscript is simply a headless brace group whose left
  neighbour ends in an identifier. No lookahead at the next character, and no
  scan for the matching brace.
  """
  for index, node in enumerate(nodes):
    if node["k"] != "group":
      continue
    if (node["open"] == "{" and not node["head"] and index > 0 and
        nodes[index - 1]["k"] == "text"):
      name = re.search(r'[a-zA-Z_][a-zA-Z0-9_]*$', nodes[index - 1]["t"])
      if name:
        before = (render_nodes(nodes[:index - 1]) +
                  nodes[index - 1]["t"][:name.start()])
        return (before, name.group(0), render_nodes(node["items"]),
                render_nodes(nodes[index + 1:]), bool(node["close"]))
    found = hash_subscript(node["items"])
    if found is None:
      continue
    before, holder, key, after, closed = found
    return (render_nodes(nodes[:index]) + node["open"] + node["head"] + before,
            holder, key,
            after + node["close"] + render_nodes(nodes[index + 1:]), closed)
  return None


# The operand of an infix operator ends where its slice does. These walk the
# node list the same way feed_slice does: a comma or a bracket at this level
# bounds the operand, and one inside a nested group belongs to that group.
_re_in_word = re.compile(r'\bin\b', re.IGNORECASE)
# A name, a number or a string literal. Only a name was accepted, so
# '5 in aNums' was left with the 'in' still in it -- valid xtpl, and not AdvPL
# at all. It compiled for as long as no fixture put a literal on the left.
_re_operand_before = re.compile(
  r'((?:\d+(?:\.\d+)?|\x00[\ue000-\uf8ff]\x00|[A-Za-z_][A-Za-z0-9_]*)'
  r'(?:\[[^\]]*\]|:[A-Za-z_][A-Za-z0-9_]*|\([^()]*\))*)\s+$')
_re_connective = re.compile(r'\.(?:and|or)\.', re.IGNORECASE)
_re_divisor = re.compile(r'\s*([A-Za-z0-9_.]+)')
_re_dividend = re.compile(
  r'((?:\d+(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]]*\])?)\s*$')


def _in_group(nodes, index, found):
  """Lift a hit found inside nodes[index] back out to this level."""
  before, mid, tail, after = found
  node = nodes[index]
  return (render_nodes(nodes[:index]) + node["open"] + node["head"] + before,
          mid, tail,
          after + node["close"] + render_nodes(nodes[index + 1:]))



# The note names storage, which no longer starts with '__'.
_NOTE_PAIR = r'(?:__|[A-Za-z]+_\d+_)\w+ = \w+'
_re_origin_note = re.compile(
  r'^(.*?)\s*//\s*((?:' + _NOTE_PAIR + r')(?:, ' + _NOTE_PAIR + r')*)\s*$')
# When the line already carried a comment, the note is folded into it in
# parentheses instead. Both forms have to be read, or a line that happened to
# have a comment keeps its slot numbers while its neighbours do not.
_re_origin_tail = re.compile(
  r'^(.*?)\s*\(((?:' + _NOTE_PAIR + r')(?:, ' + _NOTE_PAIR + r')*)\)\s*$')


def split_origin_note(line):
  """(before, pairs, how) for a line carrying origin notes, or None."""
  found = _re_origin_note.match(line)
  if found:
    return found.group(1), found.group(2).split(", "), "//"
  found = _re_origin_tail.match(line)
  if found:
    return found.group(1), found.group(2).split(", "), "()"
  return None


def rejoin_origin_note(body, pairs, how):
  if not pairs:
    return body.rstrip()
  return (f"{body}  // {', '.join(pairs)}" if how == "//"
          else f"{body}  ({', '.join(pairs)})")


# A generated temporary: one of the short kinds, then _<depth>_<index>.
# Nothing written by hand looks like this, which is the point of keeping the
# two numbers after shortening the prefix.
_re_generated_temp = re.compile(
  r'^(?:f(?:a|al|ar|bg|bs|ch|dr|fs|hd|hi|i|j|ky|ls|lm|lo|n|ok|ol|op|o|pv|pb|rd|rc|sn|sp|s|v)'
  r'|et|gt|ht|pt)_\d+_\d+$', re.IGNORECASE)


_re_generated_slot = re.compile(r'^[sb]_\d+_\w+$', re.IGNORECASE)


def is_generated_name(word):
  """Did the transpiler make this name, rather than the programmer?"""
  return (word.startswith("__") or bool(_re_generated_temp.match(word))
          or bool(_re_generated_slot.match(word)))


# Types that cannot be walked. 'array' and 'object' are absent on purpose:
# an object may well be iterable through a method, and an array is the point.
_SCALAR_TYPES = {"numeric", "character", "logical", "date", "json"}


def membership_span(nodes):
  """(before, value, collection, after) for the first 'x in y', or None.

  The collection ends at a comma, a bracket, or a logical connective -- all
  three at THIS level. The regex this replaces looked ahead for ')' or
  '.and.' by position and had no notion of depth, so 'f(cCod in aCodes, nX)'
  swallowed the sibling argument and emitted a three-argument u_xtpl_in.
  Adding ',' to that lookahead would have broken 'nX in {1, 2, 3}' instead;
  only the node list gets both right.
  """
  for index, node in enumerate(nodes):
    if node["k"] == "group":
      found = membership_span(node["items"])
      if found is not None:
        return _in_group(nodes, index, found)
      continue
    if node["k"] != "text":
      continue
    for word in _re_in_word.finditer(node["t"]):
      head = node["t"][:word.start()]
      value = _re_operand_before.search(head)
      if value is None:
        continue
      tail = [{"k": "text", "t": node["t"][word.end():]}] + list(nodes[index + 1:])
      taken, left, done = [], [], False
      for item in tail:
        if done:
          left.append(item)
        elif item["k"] == "comma":
          done = True
          left.append(item)
        elif item["k"] == "text" and _re_connective.search(item["t"]):
          at = _re_connective.search(item["t"]).start()
          # Back up over the space in front of the connective so it stays on
          # the tail, where it was written. Without this the rewrite emitted
          # 'u_xtpl_in(c, a).and. x'.
          while at > 0 and item["t"][at - 1] in " \t":
            at -= 1
          taken.append({"k": "text", "t": item["t"][:at]})
          left.append({"k": "text", "t": item["t"][at:]})
          done = True
        else:
          taken.append(item)
      collection = render_nodes(taken).strip()
      if not collection:
        continue
      return (render_nodes(nodes[:index]) + head[:value.start(1)],
              value.group(1), collection, render_nodes(left))
  return None


def divisible_span(nodes):
  """(before, dividend, divisor, after) for the first '%%', or None.

  The dividend may be a parenthesised expression, which the regex could not
  express -- '(nX + 1) %% 3' was left in the output untouched.
  """
  for index, node in enumerate(nodes):
    if node["k"] == "group":
      found = divisible_span(node["items"])
      if found is not None:
        return _in_group(nodes, index, found)
      continue
    if node["k"] != "text" or "%%" not in node["t"]:
      continue
    at = node["t"].index("%%")
    head, tail = node["t"][:at], node["t"][at + 2:]
    divisor = _re_divisor.match(tail)
    if divisor is None:
      continue
    after = tail[divisor.end():] + render_nodes(nodes[index + 1:])
    named = _re_dividend.search(head)
    if named is not None:
      return (render_nodes(nodes[:index]) + head[:named.start(1)],
              named.group(1), divisor.group(1), after)
    if not head.strip() and index > 0 and nodes[index - 1]["k"] == "group":
      group = nodes[index - 1]
      return (render_nodes(nodes[:index - 1]),
              group["open"] + group["head"] + render_nodes(group["items"]) +
              group["close"], divisor.group(1), after)
  return None


def guard_slice(nodes):
  """Where a nested 'fallback' sits, as (before, inner, after), or None.

  The guard is peeled at the top of a line, so one inside brackets went
  unnoticed and 'fallback' reached the undeclared-name check as a word. It is
  lifted into its own statement instead -- which is the shape the fusion
  warning recommends, so it had better work.
  """
  for index, node in enumerate(nodes):
    if node["k"] != "group":
      continue
    found = guard_slice(node["items"])
    if found is not None:
      before, inner, after = found
      return (render_nodes(nodes[:index]) + node["open"] + node["head"] + before,
              inner,
              after + node["close"] + render_nodes(nodes[index + 1:]))
    inner_text = render_nodes(node["items"])
    if find_top_level(inner_text, " fallback ") < 0:
      continue
    return (render_nodes(nodes[:index]), inner_text,
            render_nodes(nodes[index + 1:]))
  return None


def feed_slice(nodes, line_no, top=True):
  """Where the first NESTED chain sits, as (before, inner, after), or None.

  'inner' is the innermost slice that holds the feed -- bounded by the
  brackets around it and by the commas separating it from its siblings, so a
  chain in one argument does not drag the others out with it.

  Feeds at the top level are skipped: those are the statement's own chain, and
  the caller splits them into stages. Only what is nested inside a group is
  lifted -- including when there IS a chain at this level, which is the case
  'take(len(a |> distinct))' hits.
  """
  for index, node in enumerate(nodes):
    if node["k"] == "feed" and not top:
      start, end = _feed_slice_bounds(nodes, index)
      return (render_nodes(nodes[:start]), render_nodes(nodes[start:end]),
              render_nodes(nodes[end:]))
    if node["k"] != "group":
      continue
    found = feed_slice(node["items"], line_no, top=False)
    if found is None:
      continue
    before, inner, after = found
    return (render_nodes(nodes[:index]) + node["open"] + node["head"] + before,
            inner,
            after + node["close"] + render_nodes(nodes[index + 1:]))
  return None


def find_top_level(text, sub):
  depth = 0
  i = 0
  while i < len(text):
    char = text[i]
    if char in _OPENERS:
      depth += 1
    elif char in _CLOSERS:
      depth -= 1
    elif depth == 0 and text.startswith(sub, i):
      return i
    i += 1
  return -1


def split_by_top_level_comma(text):
  parts = split_top_level(text, ",")
  if len(parts) < 2:
    return text, None
  return parts[0], ",".join(parts[1:]).strip()


def leading_indent(text):
  return re.match(r'^[ \t]*', text).group(0)


re_assign_prefix = re.compile(r'^([ \t]*[a-zA-Z_][a-zA-Z0-9_]*\s*:=\s*)(.+)$')
re_return_prefix = re.compile(r'^([ \t]*return\s+)(.+)$', re.IGNORECASE)


def split_prefix(line):
  """Peel off an 'lhs :=' or 'return ' head so expression rewrites never eat it."""
  match = re_assign_prefix.match(line)
  if match:
    return match.group(1), match.group(2).strip()
  match = re_return_prefix.match(line)
  if match:
    return match.group(1), match.group(2).strip()
  indent = leading_indent(line)
  return indent, line[len(indent):]


re_number_literal = re.compile(r'^[+-]?\d+(?:\.\d+)?$')
re_word_literal = re.compile(r'^(?:\.T\.|\.F\.|NIL)$', re.IGNORECASE)
re_string_token = re.compile(r'^\x00[\ue000-\uf8ff]\x00$')


def is_literal_expr(expr):
  """True for constants that are safe to fold into a hoisted declaration."""
  expr = expr.strip()
  if not expr:
    return False
  if re_number_literal.match(expr) or re_word_literal.match(expr):
    return True
  if re_string_token.match(expr):
    return True
  if expr.startswith("{") and expr.endswith("}"):
    inner = expr[1:-1].strip()
    if not inner:
      return True
    return all(is_literal_expr(part) for part in split_top_level(inner))
  return False


def scope_sort_key(var_name):
  match_stk = re.match(r'^s_(\d+)_(\d+)$', var_name)
  if match_stk:
    # Stack slots sort ahead of everything, by nesting depth then slot index.
    return (-1, int(match_stk.group(1)), int(match_stk.group(2)))
  match_tmp = re.match(r'^__([a-z_]+?)_(\d+)_(\d+)$', var_name)
  if match_tmp:
    # Generated temporaries: group by kind, then by scope and order created.
    return (9998, match_tmp.group(1), int(match_tmp.group(2)), int(match_tmp.group(3)))
  match = re.match(r'^b_(\d+)_(.*)$', var_name)
  if match:
    return (int(match.group(1)), 1, match.group(2).lower())
  return (9999, 2, var_name.lower())


# The declaration grammar is parsed by Raku when rakulang is installed, and
# by the regex below when it is not. Both must produce the same declarators;
# the golden tests are what hold them to that.
_GRAMMAR_PATH = pathlib.Path(__file__).with_name("xtpl_grammar.raku")
_grammars = {}


def raku_grammar(name, actions):
  """A compiled Raku grammar, or None when rakulang is unavailable."""
  if name in _grammars:
    return _grammars[name] or None
  try:
    import rakulang
    _grammars[name] = rakulang.Grammar.from_source(
      _GRAMMAR_PATH.read_text(), name=name, actions=actions)
  except Exception:
    _grammars[name] = False             # asked once, then remembered
  return _grammars[name] or None


def declaration_grammar():
  return raku_grammar("XtplDecl", "XtplDeclActions")


def postfix_grammar():
  return raku_grammar("XtplPostfix", "XtplPostfixActions")


def peel_comment(text, parts):
  """A trailing comment, split off the line: (code, comment).

  Masking turns a comment into a single token, so a construct anchored to the
  end of its line stops seeing the line's end as soon as one is written. Only
  the transpiler knows whether a trailing token is a comment or a string
  literal, so this runs before either the grammar or the regex sees the line
  and both are given the same text.
  """
  found = re.search(r'\x00([\ue000-\uf8ff])\x00\s*$', text)
  if not found:
    return text, ""
  index = ord(found.group(1)) - _MASK_BASE
  if index >= len(parts) or not parts[index].startswith("//"):
    return text, ""                   # a string literal, not a comment
  code = text[:found.start()]
  if not code.strip():
    # A line that is only a comment has no code to protect, and peeling it
    # would leave nothing to put the comment back on.
    return text, ""
  return code.rstrip(), text[found.start():]


def for_grammar():
  return raku_grammar("XtplFor", "XtplForActions")


def expr_grammar():
  return raku_grammar("XtplExpr", "XtplExprActions")


def expr_nodes(text):
  """A line's structure, from the grammar when it is there, else the scanner.

  The grammar refuses a line whose brackets do not balance; expr_tokens is
  tolerant of one, and whatever is actually wrong gets reported by a later
  pass with a better message than this one could give.
  """
  grammar = expr_grammar()
  if grammar is not None:
    parsed = grammar.parse(text)
    if parsed:
      return parsed.made
  return expr_tokens(text)[0]


class _Postfix:
  """Presents a grammar result the way the regex match objects did."""

  def __init__(self, body, cond, keyword):
    self._parts = {"body": body, "val": body, "cond": cond, "kw": keyword}

  def group(self, name):
    return self._parts[name]


def load_dictionary(path):
  """{alias: {field, ...}} from an exported SX3.

  The column names of an export are not something this can rely on, so the
  table and field columns are found by what their headers contain -- ARQUIVO
  or ALIAS or TABELA for one, CAMPO or FIELD for the other -- and a file with
  no recognisable header falls back to the first two columns. SX3 pads its
  character fields, so everything is stripped.
  """
  import csv

  def column(header, *wanted):
    for index, name in enumerate(header):
      upper = name.strip().upper()
      if any(word in upper for word in wanted):
        return index
    return None

  rows = list(csv.reader(pathlib.Path(path).read_text(
    encoding="utf-8", errors="replace").splitlines()))
  if not rows:
    raise SystemExit(f"{path}: empty dictionary")

  alias_at = column(rows[0], "ARQUIVO", "ALIAS", "TABELA", "TABLE")
  field_at = column(rows[0], "CAMPO", "FIELD")
  # Optional: an export without them still gives name checking.
  type_at = column(rows[0], "TIPO", "TYPE")
  size_at = column(rows[0], "TAMANHO", "SIZE", "LEN")
  if alias_at is None or field_at is None:
    alias_at, field_at, type_at, size_at, body = 0, 1, None, None, rows
  else:
    body = rows[1:]

  dictionary = {}
  for row in body:
    if len(row) <= max(alias_at, field_at):
      continue
    alias = row[alias_at].strip().upper()
    field = row[field_at].strip().upper()
    if not (alias and field):
      continue
    kind = (row[type_at].strip().upper()[:1]
            if type_at is not None and len(row) > type_at else "")
    size = 0
    if size_at is not None and len(row) > size_at:
      digits = row[size_at].strip()
      size = int(digits) if digits.isdigit() else 0
    dictionary.setdefault(alias, {})[field] = (kind, size)
  return dictionary


def fold_block_comments(raw_lines):
  """Rewrite '/* ... */' as '//' comments, keeping the line count.

  Block comments span lines, and mask_literals works one line at a time and
  knows only the '//' form -- so a block comment's body was scanned as code
  and reported whatever it happened to contain as an undeclared name. Folding
  them here, before anything else runs, means no other pass has to learn a
  second comment form.

  A block that ends part-way through a line has its text moved to the end of
  that line, since '//' runs to the end and there is nowhere else to put it.
  Nothing is discarded and no line is added or removed, so every line number
  still points where it did.
  """
  result = []
  whole = set()
  inside = False
  for line in raw_lines:
    code, note = [], []
    i, n = 0, len(line)
    while i < n:
      if inside:
        end = line.find("*/", i)
        if end < 0:
          note.append(line[i:])
          i = n
        else:
          note.append(line[i:end])
          i = end + 2
          inside = False
      elif line.startswith("/*", i):
        inside = True
        i += 2
      elif line.startswith("//", i):
        code.append(line[i:])          # already the form we want
        i = n
      elif line[i] in ('"', "'"):
        quote = line[i]
        close = line.find(quote, i + 1)
        close = n if close < 0 else close + 1
        code.append(line[i:close])     # '/*' inside a string is not a comment
        i = close
      else:
        code.append(line[i])
        i += 1

    text = "".join(code)
    comment = " ".join(" ".join(note).split())
    if comment and not text.strip():
      # The whole line is comment. Kept exactly as written -- a Protheus.doc
      # block is read by other tools, and rewriting '/*/' into '//' would
      # quietly destroy it. The index is recorded so the line is passed
      # through rather than scanned.
      whole.add(len(result))
      result.append(line.rstrip())
      continue
    if comment:
      text = f"{text.rstrip()}  // {comment}"
    result.append(text.rstrip() if text.strip() else "")
  return result, whole


def join_continuations(raw_lines):
  """Fold AdvPL's trailing ';' continuations into one logical line.

  The joined text sits at the first line of the group and the rest become
  blank, so line numbers in errors still point at the source and anything
  indexing by line position keeps working.
  """
  result = [None] * len(raw_lines)
  buffer = []
  notes = []
  start = None

  def close(at):
    joined = " ".join(buffer)
    # A comment written on a continued line has nowhere to sit once the lines
    # are one, so it moves to the end of the joined statement.
    if notes:
      joined = f"{joined}  {' '.join(notes)}"
    result[start] = joined
    for j in range(start + 1, at + 1):
      result[j] = ""

  for i, line in enumerate(raw_lines):
    masked, parts = mask_literals(line)
    # The ';' is looked for past a trailing comment. It used to be tested
    # against the end of the masked line, where a comment is one token sitting
    # after the ';' -- so 'x := a ;  // note' did not continue at all. The ';'
    # was then emitted as written, and the orphaned second line was transpiled
    # as a statement of its own.
    code, note = peel_comment(masked, parts)
    continues = code.rstrip().endswith(";")
    if start is None:
      start = i
    if continues:
      if note:
        notes.append(unmask_literals(note, parts).strip())
      text = unmask_literals(code.rstrip()[:-1].rstrip(), parts)
    else:
      text = line.rstrip()
    buffer.append(text if not buffer else text.strip())
    if not continues:
      close(i)
      buffer, notes, start = [], [], None
  if buffer:
    close(len(raw_lines) - 1)
  return result


def transpile(source_code, dictionary=None, dict_strict=False,
              legacy=False, map_lines=False):
  # Block comments are folded into the '//' form before anything else looks
  # at the source, so every later pass sees one comment form.
  # A non-breaking space where a space belongs. Real files have them -- some
  # editor put them there -- and Protheus accepts them, while '\s' does not,
  # so a declaration would simply fail to parse. Replaced outside string
  # literals only, since inside one it is data.
  def plain_spaces(line):
    if "\u00a0" not in line:
      return line
    masked, parts = mask_literals(line)
    return unmask_literals(masked.replace("\u00a0", " "), parts)

  folded_lines, block_comment_lines = fold_block_comments(
    [plain_spaces(l) for l in source_code.splitlines()])
  lines = join_continuations(folded_lines)
  out_lines = []

  in_function = False
  function_buffer = []
  # Positions in function_buffer that hold a preserved block comment.
  buffer_comment_at = set()
  # (index, mangled, source name) for every block local, in order.
  declared_lines = []
  native_hoisted = []
  private_hoisted = []
  generated_hoisted = []
  hoisted_inits = {}
  # A trailing comment on a declaration whose value was folded into the
  # hoisted Local: it goes on that line, not onto the value.
  hoisted_notes = {}
  defer_stack = []

  scope_stack = [0]
  scope_counter = 0
  scope_vars = {0: set()}
  scope_var_mangling = {0: {}}

  # Internal scope handles are allocated on block entry, but the number that
  # appears in a mangled name is handed out lazily on first use, so blocks that
  # declare nothing don't burn an index and b_ numbering stays contiguous.
  scope_display = {0: 0}
  display_counter = 0

  # Declarations are only legal in a block's prologue: the run of declarations,
  # comments and blank lines before its first executable statement.
  prologue_open = {0: True}

  # A comment run that opens the function body documents the function, so it
  # belongs above the generated declarations. A comment appearing after the
  # first declaration or statement belongs to the code it sits on.
  doc_comment = []
  capturing_doc = False

  # Inside 'raw', unknown words are commands the AdvPL preprocessor will
  # rewrite, not undeclared variables.
  lenient_names = False
  in_raw_block = False

  # Open 'using' blocks, innermost last. Each holds the lines that put the
  # work area back, so a return from inside one can emit them too.
  using_stack = []
  # Scopes opened by 'for each x in lines(f)', which close with EndDo and a
  # FT_FUse() rather than a Next.
  file_loops = {}

  # --legacy turns the two rules that stop xtpl being a superset of AdvPL into
  # warnings, and counts what it saw. The counts are the point as much as the
  # warnings: they measure how far an existing file is from compiling.
  legacy_prologue = []
  legacy_undeclared = {}
  # Names a write brought into being as PRIVATEs, and where.
  legacy_privates = {}

  # Aliases this function is known to have opened, and where every return
  # with and without a value sits.
  open_aliases = set()
  returns_value = []
  returns_bare = []

  # C++-style stack slots: one pool per nesting depth. The pool resets when a
  # block at that depth is entered, so sibling blocks reuse the same storage.
  stack_slot_next = {0: 0}
  block_locals = {}
  retired_locals = {}
  pinned_decls = set()
  current_line_no = 0

  # Generated name -> the source variable it currently holds, and the full list
  # of everything that has ever shared it. Slots are recycled, so the first map
  # is rewritten on each declaration and always reflects the live binding.
  origin_names = {}
  slot_origins = {}

  # Every source-level declaration in the function, and how each name is used,
  # so a variable that is never read can be reported.
  declared_at = {}
  reads = {}
  writes = {}

  # Mangled names declared <const>, and those whose note has to be printed.
  const_names = {}
  const_notes = set()
  # TLPP type annotations, by generated name, so a hoisted Local keeps the
  # 'as object' the source wrote.
  declared_types = {}

  # Words that are not variables: AdvPL keywords, literals, and the structural
  # words this transpiler emits into generated lines.
  known_words = {
    "nil", "to", "step", "exit", "loop", "self", "super", "iif", "in",
    "and", "or", "not", "t", "f", "class", "data", "method", "endclass",
    "begin", "sequence", "recover", "always", "endsequence", "try", "catch",
    "endtry", "case", "endcase", "switch", "default", "parameters", "then",
    "as", "from", "of", "nonempty", "_super",
  }

  reserved_words = {
    "function", "static", "user", "return", "if", "else", "elseif", "endif",
    "for", "next", "while", "enddo", "do", "local", "private", "public",
    "with", "without", "orwith", "given", "when", "otherwise", "end",
    "conout", "len", "eval", "array", "aadd", "substr", "userexception"
  }

  def add_native(name):
    if name not in native_hoisted:
      native_hoisted.append(name)

  def add_private(name):
    if name not in private_hoisted:
      private_hoisted.append(name)

  def add_generated(name):
    if name not in generated_hoisted:
      generated_hoisted.append(name)

  def reject_if_const(var_name, line_no, what):
    v_lower = var_name.lower()
    for s_id in reversed(scope_stack):
      if v_lower in scope_vars[s_id]:
        mangled = scope_var_mangling[s_id][v_lower]
        if mangled in const_names:
          raise SyntaxError(
            f"Line {line_no}: '{var_name}' is <const> (declared on line "
            f"{const_names[mangled]}) and cannot be {what}.")
        return
    return

  def resolve_declared(var_name, line_no):
    v_lower = var_name.lower()
    for s_id in reversed(scope_stack):
      if v_lower in scope_vars[s_id]:
        return scope_var_mangling[s_id][v_lower]
    raise SyntaxError(f"Line {line_no}: '{var_name}' is not declared.")

  def looks_like_container(expr):
    """An array or object literal -- the case where <const> is only skin deep."""
    expr = expr.strip()
    return expr.startswith("{") and not expr.startswith("{|")

  def check_attributes(names, line_no):
    for word in names:
      if word not in known_attributes:
        raise SyntaxError(
          f"Line {line_no}: unknown attribute '<{word}>'. "
          f"Known: {', '.join(sorted(known_attributes))}.")
    return set(names)

  # TLPP puts the type on either side of the initialiser: 'x as numeric := 1'
  # and 'x := 1 as numeric' are both written. The grammar and the regex both
  # take the first; the second arrives inside the value, where nothing else
  # would ever put an 'as'.
  re_value_typing = re.compile(
    r'^(.*?)\s+as\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*$', re.IGNORECASE | re.DOTALL)

  def split_trailing_type(found):
    name, operator, value, attrs, typing = found
    if not typing and value:
      tail = re_value_typing.match(value)
      if tail:
        value, typing = tail.group(1).strip(), tail.group(2)
    return name, operator, value, attrs, typing

  def parse_declarators(text, line_no, parts=None):
    """Split 'a := 1, b, c := {1,2}' into its declarators.

    Commas inside braces, brackets or parentheses are not separators, so an
    array literal initialiser stays with its own declarator.
    """
    # A trailing comment is not a declarator. It went unnoticed while the last
    # one always had an initialiser -- the comment was absorbed into the value
    # and emitted with it -- but 'local a := 1, b  // nota' ends on a bare
    # name with nowhere to put it, and the grammar, which anchors to the end
    # of the line, refused the whole list.
    text, _ = peel_comment(text, literal_parts if parts is None else parts)
    grammar = declaration_grammar()
    if grammar is not None:
      parsed = grammar.parse(text.strip())
      if not parsed:
        raise SyntaxError(f"Line {line_no}: cannot read declaration '{text.strip()}'.")
      return [split_trailing_type(
                (d["name"], d["assign"] or None, d["value"].strip(),
                 check_attributes([a.lower() for a in d["attrs"]], line_no),
                 d["typing"]))
              for d in parsed.made]

    # An attribute list holds commas of its own, and '<' '>' are not
    # delimiters to split_top_level -- so '<const, contained>' was cut in half
    # and 'contained' became a declarator of its own. Set aside before the
    # split and put back after, the same move masking makes for literals.
    kept = []

    def stash(found):
      kept.append(found.group(0))
      return f"\x01{len(kept) - 1}\x01"

    def restore(text_part):
      return re.sub(r'\x01(\d+)\x01',
                    lambda m: kept[int(m.group(1))], text_part)

    out = []
    for part in split_top_level(re_attributes.sub(stash, text)):
      part = restore(part).strip()
      if not part:
        # An empty declarator means a stray comma -- 'local a := 1,'. The
        # grammar refuses it, so this must too, or the two paths disagree on
        # a typo. A real continuation is written with a trailing ';'.
        raise SyntaxError(
          f"Line {line_no}: cannot read declaration '{text.strip()}'.")
      attrs = check_attributes(
        [w.strip().lower() for f in re_attributes.finditer(part)
         for w in f.group(1).split(",")], line_no)
      part = re_attributes.sub(" ", part).strip()
      typing = ""
      typed = re_typing.match(part)
      if typed:
        typing = typed.group(2)
        part = f"{typed.group(1)} {typed.group(3)}".strip()
      match = re_declarator.match(part)
      if not match:
        raise SyntaxError(f"Line {line_no}: cannot read declaration '{part}'.")
      out.append(split_trailing_type(
        (match.group(1), match.group(2), match.group(3).strip(), attrs, typing)))
    return out

  # One entry is enough: re.sub walks a single string at a time.
  alias_scope_memo = {}
  re_alias_scope = re.compile(r'\b[A-Za-z_][A-Za-z0-9_]*->\(')

  def alias_scopes(text):
    """Spans of every 'ALIAS->( ... )' in the line."""
    if text in alias_scope_memo:
      return alias_scope_memo[text]
    spans = []
    for opener in re_alias_scope.finditer(text):
      inner, after = extract_parens(text, opener.end() - 1)
      if inner is not None:
        spans.append((opener.end(), after - 1))
    alias_scope_memo.clear()
    alias_scope_memo[text] = spans
    return spans

  re_block_head = re.compile(r'\{\s*\|([^|]*)\|')
  block_param_memo = {}

  def block_params(text):
    """(span, names) for every native '{|a, b| ... }' in the line.

    AdvPL's own code block declares its parameters between the bars. xtpl's
    '[x] body' form registered its alias; the native form did not, so every
    use of 'u' inside '{|u| ... }' was an undeclared name -- which is most
    code blocks in most real files.
    """
    if text in block_param_memo:
      return block_param_memo[text]
    found = []
    for head in re_block_head.finditer(text):
      opener = text.rfind("{", 0, head.end())
      depth, close = 0, len(text)
      for i in range(opener, len(text)):
        if text[i] == "{":
          depth += 1
        elif text[i] == "}":
          depth -= 1
          if depth == 0:
            close = i
            break
      names = {n.strip().lower() for n in head.group(1).split(",")
               if n.strip()}
      if names:
        # From the opening brace, so the names between the bars are covered
        # too -- that is where they are declared.
        found.append(((opener, close), names))
    block_param_memo.clear()
    block_param_memo[text] = found
    return found

  def resolve_identifier(match):
    word = match.group(0)
    word_lower = word.lower()
    if word_lower in reserved_words:
      return word
    for s_id in reversed(scope_stack):
      if word_lower in scope_vars[s_id]:
        mangled = scope_var_mangling[s_id][word_lower]
        # A name alone on the left of ':=' is being written, not read.
        head = match.string[:match.start()].strip()
        tail = match.string[match.end():].lstrip()
        if not head and tail.startswith(":="):
          writes[mangled] = writes.get(mangled, 0) + 1
        else:
          reads[mangled] = reads.get(mangled, 0) + 1
        return mangled

    text = match.string
    before = text[:match.start()].rstrip()
    after = text[match.end():].lstrip()

    if word_lower in retired_locals:
      if not after.startswith("("):
        raise SyntaxError(
          f"Line {current_line_no}: '{word}' is out of scope here "
          f"(block local declared on line {retired_locals[word_lower]}).")
      return word

    # Not a variable reference: a call, a member or field access, a logical
    # literal such as .T., a name this transpiler generated, or a #define.
    # A TLPP namespace: 'totvs.tools.Foo():New()'. The middle segments already
    # pass as dot-flanked, like '.And.', but the root does not. Told apart
    # from 'nA.And.nB' -- lexically identical -- by the whole dotted path
    # ending in a call.
    if re_namespaced.match(after):
      return word

    if (after.startswith("(") or after.startswith("->") or
        before.endswith("->") or before.endswith(":") or
        (text[:match.start()].endswith(".") and text[match.end():].startswith(".")) or
        is_generated_name(word) or word_lower in known_words or
        word_lower in defined_constants or word_lower in external_names or
        word_lower in private_names):
      return word

    # A parameter of the native code block this name sits inside.
    for (start, end), names in block_params(match.string):
      if start <= match.start() < end and word_lower in names:
        return word

    # Inside 'ALIAS->( ... )' the expression is evaluated in that work area,
    # so a bare name there is one of its fields. This is the case the
    # reference used to say had no answer.
    if any(start <= match.start() < end
           for start, end in alias_scopes(match.string)):
      return word

    if lenient_names:
      return word

    if legacy:
      # A name an earlier write turned into a PRIVATE exists by now, so
      # reading it is ordinary and there is nothing to report.
      if word_lower in legacy_privates:
        return word
      # Left exactly as written, and NOT registered: declaring it here would
      # add a Local the source never had and change the output. The point of
      # legacy mode is that the file still compiles to what it compiled to.
      seen = legacy_undeclared.get(word_lower)
      # Keyed by lowercase, since AdvPL does not care, but reported as the
      # source spells it -- 'SAY' reads as a command, 'say' as a mistake.
      legacy_undeclared[word_lower] = ((seen[0] if seen else word),
                                       (seen[1] if seen else 0) + 1)
      if seen is None:
        print(f"warning: line {current_line_no}: '{word}' is not declared",
              file=sys.stderr)
      return word

    raise SyntaxError(
      f"Line {current_line_no}: '{word}' is not declared. Everything used in "
      f"xtpl must be declared.")

  # One qualifier at most: 'User Function', 'Static Function', 'Main Function'.
  # All three are just a function as far as xtpl is concerned. 'Main' was
  # missing, and the cost of missing a header form is that no function is
  # recognised at all -- so nothing is ever inside one and the whole file
  # falls out untouched, with nothing said.
  re_func = re.compile(
    r'^\s*(?:(?:User|Static|Main)\s+)?(?:Function|Method)\b', re.IGNORECASE)
  re_scope_out = re.compile(r'^\s*(?:ENDIF|NEXT|ENDDO|ENDCASE|END\s+CASE|END\s+SCOPE)\b', re.IGNORECASE)

  re_local_decl = re.compile(r'^([ \t]*)LOCAL\s+(.+)$', re.IGNORECASE)
  # PRIVATE is dynamically scoped: declared here, visible to everything this
  # function calls. That is what a Protheus dialog uses to let its button
  # blocks reach a control built in the caller, and xtpl had no way to say it
  # -- so the only honest conversion of such a file was --legacy.
  re_private_decl = re.compile(r'^([ \t]*)PRIVATE\s+(.+)$', re.IGNORECASE)
  re_declarator = re.compile(
    r'^([a-zA-Z_][a-zA-Z0-9_]*)\s*(:=|\?=)?\s*(.*)$', re.DOTALL)
  # 'local oTool as object' -- TLPP's type annotation, kept and emitted back.
  re_typing = re.compile(
    r'^([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s+([a-zA-Z_][a-zA-Z0-9_]*)\b\s*(.*)$',
    re.IGNORECASE | re.DOTALL)
  re_defined_or = re.compile(r'^\s*([a-zA-Z0-9_]+)\s*\?=\s*(.+)$', re.IGNORECASE)

  re_assign = re.compile(r'^\s*([a-zA-Z0-9_]+)\s*:=\s*', re.IGNORECASE)

  re_fortimes = re.compile(r'^([ \t]*)FOR\s+(.+?)\s+TIMES\s*$', re.IGNORECASE)
  re_foreach = re.compile(
    r'^([ \t]*)FOR\s+([a-zA-Z0-9_]+)(?:\s*,\s*([a-zA-Z0-9_]+))?\s+IN\s+(.+)$',
    re.IGNORECASE)
  # 'for each' was the old spelling; say so rather than reporting 'each' as an
  # undeclared variable, which is what would happen otherwise.
  re_foreach_each = re.compile(r'^\s*FOR\s+EACH\s+', re.IGNORECASE)
  re_for = re.compile(r'^\s*FOR\s+(?P<is_local>LOCAL\s+)?([a-zA-Z0-9_]+)\s*:=\s*(.+)$', re.IGNORECASE)
  re_if_local = re.compile(r'^\s*IF\s+LOCAL\s+([a-zA-Z0-9_]+)\s*:=\s*(.+)$', re.IGNORECASE)
  re_while_local = re.compile(r'^\s*WHILE\s+LOCAL\s+([a-zA-Z0-9_]+)\s*:=\s*(.+)$', re.IGNORECASE)

  # 'raw' hands a line to the AdvPL preprocessor untouched. Declared
  # variables are still renamed, so block locals keep working inside it.
  re_external = re.compile(r'^\s*external\s+', re.IGNORECASE)

  re_raw_line = re.compile(r'^(\s*)raw\s+(.+)$', re.IGNORECASE)
  re_raw_start = re.compile(r'^\s*raw\s*$', re.IGNORECASE)
  re_raw_end = re.compile(r'^\s*end\s+raw\b', re.IGNORECASE)

  # 'let' was folded into 'local'; flag leftovers instead of emitting garbage.
  re_let_removed = re.compile(r'^\s*LET\s+[a-zA-Z0-9_]+\s*(?::=|\?=|$)', re.IGNORECASE)

  re_defer = re.compile(r'^\s*defer\s+(.+)$', re.IGNORECASE)
  re_explicit_return = re.compile(r'^\s*return\b', re.IGNORECASE)
  re_postfix_return = re.compile(r'^\s*return\b(?P<val>.*?)\s+if\s+(?P<cond>.+)$', re.IGNORECASE)
  re_postfix_exec = re.compile(r'^\s*exec\s+(?P<body>.+?)\s+if\s+(?P<cond>.+)$', re.IGNORECASE)
  re_postfix_general = re.compile(r'^\s*(?P<body>.+?)\s+(?P<kw>if|while)\s+(?P<cond>.+)$', re.IGNORECASE)

  # 'given' dispatches on one subject, evaluated once and optionally bound.
  # do case with [local] x := expr -- evaluate the subject once and name it.
  # Plain 'do case' is untouched.
  re_docase = re.compile(
    r'^(\s*)DO\s+CASE\s+WITH\s+(LOCAL\s+)?([a-zA-Z0-9_]+)\s*:=\s*(.+)$',
    re.IGNORECASE)

  # Removed constructs, flagged rather than silently mistranspiled.
  re_removed_block = re.compile(
    r'^\s*(with(?!\s+object\b)|orwith|without|given|when)\b'
    r'|^\s*end\s+(without|given)\b',
    re.IGNORECASE)

  # with object <expr> ... end with -- a leading ':' means the subject.
  re_with_object = re.compile(r'^([ \t]*)WITH\s+OBJECT\s+(.+)$', re.IGNORECASE)
  re_end_with = re.compile(r'^\s*END\s+WITH\b', re.IGNORECASE)

  # using alias SA1 order 1 do ... end using -- select the area, and put back
  # what was there at every way out, early returns included.
  re_using = re.compile(
    r'^([ \t]*)USING\s+ALIAS\s+(.+?)(?:\s+ORDER\s+(.+?))?\s+DO\s*$',
    re.IGNORECASE)
  re_end_using = re.compile(r'^\s*END\s+USING\b', re.IGNORECASE)


  # gather/take was removed; flag it rather than emitting a stray function call.
  re_gather_removed = re.compile(
    r'^\s*(?:(?:LOCAL\s+)?[a-zA-Z0-9_]+\s*(?::=|=)\s*)?gather\b|^\s*end\s+gather\b',
    re.IGNORECASE)

  re_xtpl_print = re.compile(r'\bxconout\s*\(', re.IGNORECASE)

  # 'rows' and 'lines' name a source to walk, not a function, so these names
  # are taken -- a function of your own called either one is redirected.
  re_source_call = re.compile(r'\b(rows|lines)\s*\(', re.IGNORECASE)

  # x in aArray  /  x in lo..hi
  re_range = re.compile(r'^(.+?)\.\.(.+)$')

  # n %% 3  ->  (n % 3) == 0
  re_divisible = re.compile(
    r'([A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?)\s*%%\s*([A-Za-z0-9_.]+)')

  # The fold operators were replaced by asum/aprod/amax/amin.
  re_reduce_operator = re.compile(r'\[\s*(\+|\-|\*|/|max|min)\s*\]', re.IGNORECASE)

  re_pipe_segment = re.compile(r'^([a-zA-Z_][a-zA-Z0-9_]*)\s*(\(?)')

  # The whole chain, however many links. The two-link version left a third
  # '?.' sitting in the output.
  re_optional_chain = re.compile(
    r'\b([a-zA-Z_][a-zA-Z0-9_]*)((?:\s*\?\.\s*[a-zA-Z_][a-zA-Z0-9_]*)+)')

  def register_native_variable(var_name, curr_scope, line_no=None, private=False):
    v_lower = var_name.lower()
    if v_lower in reserved_words:
      raise SyntaxError(f"Cannot use reserved word '{var_name}' as a variable name.")
    # The generated names are short now, so the shapes they take are reserved
    # explicitly rather than by a '__' prefix nobody would type by accident.
    # A collision would be silent: two different variables, one slot.
    if is_generated_name(var_name):
      raise SyntaxError(
        f"Line {line_no}: '{var_name}' has the shape of a name xtpl "
        f"generates, so it cannot be declared. Reserved: a leading '__', and "
        f"'<kind>_<depth>_<index>' -- fo_0_0, fv_1_2, s_1_0, b_0_x.")
    if line_no is not None and v_lower in scope_vars[curr_scope]:
      # Real files declare a local over a parameter of the same name, and
      # Protheus takes it. Under --legacy the point is to read the file as it
      # is, so this is said rather than refused.
      if not legacy:
        raise SyntaxError(
          f"Line {line_no}: '{var_name}' is already declared in this function.")
      print(f"warning: line {line_no}: '{var_name}' is already declared in "
            f"this function", file=sys.stderr)
      return scope_var_mangling[curr_scope][v_lower]
    if v_lower not in scope_vars[curr_scope]:
      mangled = var_name
      scope_vars[curr_scope].add(v_lower)
      scope_var_mangling[curr_scope][v_lower] = mangled
      (add_private if private else add_native)(mangled)
      if line_no is not None:
        declared_at[mangled] = (var_name, line_no)
      return mangled
    return scope_var_mangling[curr_scope][v_lower]

  def record_origin(mangled, var_name):
    origin_names[mangled] = var_name
    seen = slot_origins.setdefault(mangled, [])
    if var_name not in seen:
      seen.append(var_name)

  def scope_number(handle):
    nonlocal display_counter
    if handle not in scope_display:
      display_counter += 1
      scope_display[handle] = display_counter
    return scope_display[handle]

  def register_xtpl_variable(var_name, curr_scope, name_scope=None):
    """Declare in curr_scope; name after name_scope (defaults to curr_scope)."""
    v_lower = var_name.lower()
    if v_lower in reserved_words:
      raise SyntaxError(f"Cannot use reserved word '{var_name}' as a variable name.")
    if v_lower not in scope_vars[curr_scope]:
      owner = curr_scope if name_scope is None else name_scope
      mangled = f"b_{scope_number(owner)}_{var_name}"
      record_origin(mangled, var_name)
      scope_vars[curr_scope].add(v_lower)
      scope_var_mangling[curr_scope][v_lower] = mangled
      add_generated(mangled)
      return mangled
    return scope_var_mangling[curr_scope][v_lower]

  def register_block_local(var_name, target_scope, line_no, name_scope=None):
    """Declare a block local, choosing shared or private storage.

    A name is 'pinned' when the function ever captures it in a code block or
    passes it by reference with @. Either one outlives the block, so the
    variable gets its own b_ storage instead of a recycled slot.
    """
    v_lower = var_name.lower()
    if v_lower in reserved_words:
      raise SyntaxError(f"Cannot use reserved word '{var_name}' as a variable name.")
    if v_lower in scope_vars[target_scope]:
      raise SyntaxError(
        f"Line {line_no}: '{var_name}' is already declared in this block.")

    depth = scope_stack.index(target_scope)
    if depth == 0 or line_no in pinned_decls:
      owner = target_scope if name_scope is None else name_scope
      mangled = f"b_{scope_number(owner)}_{var_name}"
    else:
      ordinal = stack_slot_next.get(depth, 0)
      stack_slot_next[depth] = ordinal + 1
      mangled = f"s_{depth}_{ordinal}"

    record_origin(mangled, var_name)
    # Where this declaration will land. Two blocks may declare the same name
    # into the same slot -- different variables that never coexist -- and each
    # is a declaration in its own right, so each wants its own 'let'.
    declared_lines.append((len(function_buffer), mangled, var_name))
    # '__each' and friends are the transpiler's, not the programmer's.
    if not is_generated_name(var_name):
      declared_at[mangled] = (var_name, line_no)
    scope_vars[target_scope].add(v_lower)
    scope_var_mangling[target_scope][v_lower] = mangled
    block_locals.setdefault(target_scope, {})[v_lower] = line_no
    add_generated(mangled)
    return mangled

  def register_parameter(var_name, line_no):
    """Parameters are already declared by the signature: in scope, not hoisted."""
    v_lower = var_name.lower()
    if v_lower in reserved_words:
      raise SyntaxError(
        f"Line {line_no}: cannot use reserved word '{var_name}' as a parameter name.")
    if v_lower in scope_vars[0]:
      raise SyntaxError(f"Line {line_no}: parameter '{var_name}' is declared twice.")
    scope_vars[0].add(v_lower)
    scope_var_mangling[0][v_lower] = var_name

  def register_declaration(var_name, target_scope, line_no, name_scope=None):
    """Function-level locals stay native; block-level ones get stack semantics."""
    if target_scope == 0 and name_scope is None:
      return register_native_variable(var_name, target_scope, line_no)
    return register_block_local(var_name, target_scope, line_no, name_scope=name_scope)

  def register_in_scope(var_name, target_scope):
    """Function-level declarations stay unmangled; block-level ones get a prefix."""
    if target_scope == 0:
      return register_native_variable(var_name, target_scope)
    return register_xtpl_variable(var_name, target_scope)

  def open_new_scope():
    nonlocal scope_counter
    scope_counter += 1
    scope_stack.append(scope_counter)
    scope_vars[scope_counter] = set()
    scope_var_mangling[scope_counter] = {}
    prologue_open[scope_counter] = True
    # Entering a block hands its depth a fresh slot pool.
    stack_slot_next[len(scope_stack) - 1] = 0
    return scope_counter

  def close_scope():
    if len(scope_stack) > 1:
      dead = scope_stack.pop()
      # Leaving the block destroys its locals.
      for name, line_no in block_locals.pop(dead, {}).items():
        retired_locals[name] = line_no

  def spell_shared_slots():
    """Give each occupant of a shared slot its own spelling of it.

    A slot holding four different variables cannot be named after any of them,
    so it kept a number and every line carried a comment saying which variable
    it was that time. The preprocessor can do better: '~' is legal in a
    pattern and illegal in an identifier, so

        #translate aTmp~1~0   => s_1_0
        #translate aOther~1~0 => s_1_0

    gives two readable spellings of one piece of storage, and no rule can ever
    collide with a name somebody wrote.

    The name carries the depth and the ordinal, so 'aTmp~1~0' can only mean
    's_1_0' in any function. Two functions emit the identical rule, which
    is harmless -- so the rules live at the top of the file and nothing is
    needed per block, nor an '#untranslate'.

    Which occupant each line belongs to is already recorded, in the origin
    comments. They are what this reads, and what it then removes.
    """
    shared = {}
    for slot, names in slot_origins.items():
      match = re.match(r'^s_(\d+)_(\d+)$', slot)
      if match and len(names) > 1:
        shared[slot] = (match.group(1), match.group(2))
    if not shared:
      return

    for index in range(len(function_buffer) - 1, -1, -1):
      found = split_origin_note(function_buffer[index])
      if found is None:
        continue
      body, pairs, how = found
      kept = []
      for pair in pairs:
        slot, _, origin = pair.partition(" = ")
        if slot not in shared:
          kept.append(pair)
          continue
        depth, ordinal = shared[slot]
        # Closed with a '!' as well. Without a terminator the last marker
        # runs on and swallows what follows, which shows up as a mangled
        # 'For' header rather than as an error.
        spelled = f"!{origin.lstrip('_')}^{depth}^{ordinal}!"
        body = re.sub(rf'\b{re.escape(slot)}\b', spelled, body)
        translate_rules.add(True)     # one rule covers every slot
      function_buffer[index] = rejoin_origin_note(body, kept, how)

    # The first line a spelling appears on is its declaration; 'let' marks it,
    # and expands to nothing.


  def drop_unused_generated():
    """Forget generated storage that nothing in the body refers to.

    Substituting a block's parameter for the value the loop already holds
    leaves its slot declared and never mentioned. The name was the
    transpiler's, so there is nothing to warn about -- it just goes, along
    with the 'let' that marked it.
    """
    body = "\n".join(function_buffer[1:])
    alive = []
    for name in generated_hoisted:
      spelled = re.match(r'^__(stk|blk)_(\d+)_(.+)$', name)
      forms = [rf'\b{re.escape(name)}\b']
      if spelled:
        kind, depth, tail = spelled.groups()
        if kind == "blk":
          forms.append(rf'%{re.escape(tail)}\^{depth}%')
        elif tail.isdigit():
          forms.append(rf'![A-Za-z_]\w*\^{depth}\^{tail}!')
        else:
          forms.append(rf'!{re.escape(tail)}\^{depth}!')
      if any(re.search(f, body) for f in forms):
        alive.append(name)
    if len(alive) == len(generated_hoisted):
      return
    gone = [n for n in generated_hoisted if n not in alive]
    generated_hoisted[:] = alive
    function_buffer[1:] = [
      l for l in function_buffer[1:]
      if not any(re.match(rf'\s*let \w+ as {re.escape(n)}\s*$', l)
                 for n in gone)]

  def space_out_blocks():
    """A blank line either side of a control structure at the outer level.

    A fused chain emits a dozen lines with a loop in the middle, and without
    this the whole function reads as one block of text. Only the outermost
    level: spacing a nested 'If' as well would pull the loop apart.
    """
    opens = re.compile(
      r'^  (?:If|For|While|Do\s+Case|Begin\s+Sequence|Try)\b', re.IGNORECASE)
    closes = re.compile(
      r'^  (?:EndIf|Next|EndDo|EndCase|End\s+Sequence|EndTry)\b',
      re.IGNORECASE)
    spaced = []
    for index, line in enumerate(function_buffer):
      if opens.match(line) and spaced:
        # A comment run directly above belongs to the block it documents, so
        # the blank goes above the comment, not between them.
        at = len(spaced)
        while at > 0 and spaced[at - 1].strip().startswith("//"):
          at -= 1
        # Only when there is real body above it. Position 1 is straight after
        # the signature, where the declarations already separate.
        if at > 1 and spaced[at - 1].strip():
          spaced.insert(at, "")
      spaced.append(line)
      if closes.match(line):
        following = function_buffer[index + 1] if index + 1 < len(
          function_buffer) else ""
        if following.strip():
          spaced.append("")
    # A ';' continuation leaves its lines blank so the numbering still points
    # at the source, which can put five blanks in a row where one statement
    # was spread over five lines. One is enough anywhere.
    collapsed = []
    for line in spaced:
      if not line.strip() and collapsed and not collapsed[-1].strip():
        continue
      collapsed.append(line)
    function_buffer[:] = collapsed

  def mark_block_declarations():
    """'let <name> as <storage>' in front of every block-local declaration.

    A block variable is one whether it landed in a recycled slot or in private
    storage of its own -- a captured one gets 'b_1_nFator' and is no less
    block-scoped for it. The marker says so uniformly, and expands to nothing.

    Last of the three passes, so the storage it names is the final one.
    """
    if not declared_lines:
      return

    # Where each line's enclosing block opens. A declaration goes to the top
    # of the block it belongs to, so the generated code shows the same shape
    # xtpl requires of the source: declarations, then statements.
    opens_at = {}
    stack = []
    for index, line in enumerate(function_buffer):
      opens_at[index] = stack[-1] if stack else None
      if re_block_open.match(line):
        stack.append(index)
      elif re_block_close.match(line):
        if stack:
          stack.pop()

    marks = []
    for index, storage, source in declared_lines:
      if index >= len(function_buffer):
        continue
      text = (f"{leading_indent(function_buffer[index])}"
              f"let {source.lstrip('_')} as {storage}")
      # A variable declared BY a header -- 'for local nI := 1 to 3' -- cannot
      # move: the header that opens its block is also what uses it. Anything
      # else joins the prologue of the block it sits in.
      if re_block_open.match(function_buffer[index]):
        marks.append((index, 0, text))
      else:
        opener = opens_at.get(index)
        marks.append((index if opener is None else opener + 1, index, text))

    # Grouped by position and inserted whole, so declarations keep their
    # order. Inserting one at a time at the same index reverses them.
    grouped = {}
    for where, order, text in sorted(marks, key=lambda m: (m[0], m[1])):
      grouped.setdefault(where, []).append(text)
    for where in sorted(grouped, reverse=True):
      function_buffer[where:where] = grouped[where]
    if marks:
      translate_rules.add(True)

  def spell_named_slots():
    """'!nInner^2!' for a slot named after the one variable that uses it.

    Without this the body mixes two idioms: '!aTmp^1^0!' where storage is
    shared and a bare 's_2_nInner' where it is not. Both are block
    variables and both should look like one.

    The two rules cannot be confused: a shared slot carries two numbers and a
    named one carries a single depth, so '!x^1^0!' never matches the
    one-number pattern.
    """
    named = {}
    for slot in list(slot_origins):
      match = re.match(r'^s_(\d+)_([A-Za-z_]\w*)$', slot)
      if match:
        named[slot] = (match.group(1), match.group(2))
    if not named:
      return
    for index, line in enumerate(function_buffer):
      if re.match(r'\s*let \w+ as ', line):
        continue                      # the marker names the storage itself
      for slot, (depth, name) in named.items():
        line = re.sub(rf'\b{re.escape(slot)}\b', f"!{name}^{depth}!", line)
      function_buffer[index] = line
    translate_rules.add(True)

  def spell_private_storage():
    """'%nFator^1%' for storage that never got a slot.

    A variable pinned by a capture, a '@', a 'raw' line or a 'defer' gets
    private 'b_' storage, and so does a lambda's parameter. Both are block
    variables, and with this they read like the other two kinds.

    Verified by running it: a block built with the alias still sees an
    assignment made afterwards, which is the whole reason these have storage
    of their own. Had the alias broken the capture, xtpl's escape analysis
    would have stopped being true, silently.
    """
    private = {}
    for index, line in enumerate(function_buffer):
      for found in re.finditer(r'\bb_(\d+)_([A-Za-z_]\w*)\b', line):
        private[found.group(0)] = (found.group(1), found.group(2))
    if not private:
      return
    for index, line in enumerate(function_buffer):
      if re.match(r'\s*let \w+ as ', line):
        continue                      # the marker names the storage itself
      for raw, (depth, name) in private.items():
        line = re.sub(rf'\b{re.escape(raw)}\b', f"%{name}^{depth}%", line)
      function_buffer[index] = line
    for name in generated_hoisted:
      if name in private:
        translate_rules.add(True)
    translate_rules.add(True)

  def name_single_slots():
    """Give a slot the name of its occupant when it only ever has one.

    Four fifths of recycled slots are used by exactly one source variable, and
    for those 's_1_0' tells a reader nothing that 's_1_aTmp' would not
    tell them better. The depth stays in the name, so two variables of the
    same name at different depths remain distinct.

    A slot genuinely shared by several variables keeps its number: there is no
    honest name for storage that holds 'aTmp' on one line and 'cOutro' on the
    next, which is what the origin comments are for.
    """
    rename = {}
    for slot, names in slot_origins.items():
      match = re.match(r'^s_(\d+)_(\d+)$', slot)
      if match and len(names) == 1:
        # The transpiler's own names lead with underscores -- '__each',
        # '__usearea'. Stripped, since 's_1_each' is the readable form and
        # 's_1___each' is not.
        rename[slot] = f"s_{match.group(1)}_{names[0].lstrip('_')}"
    if not rename:
      # Even with nothing to rename, a note the spelling pass left behind may
      # now say what the name already says.
      for index, line in enumerate(function_buffer):
        function_buffer[index] = drop_stale_origins(line)
      return

    word = re.compile(r'\b(' + "|".join(map(re.escape, rename)) + r')\b')
    for index, line in enumerate(function_buffer):
      function_buffer[index] = drop_stale_origins(
        word.sub(lambda m: rename[m.group(1)], line))
    for index, name in enumerate(generated_hoisted):
      if name in rename:
        generated_hoisted[index] = rename[name]
    for index, entry in enumerate(declared_lines):
      where, storage, source = entry
      if storage in rename:
        declared_lines[index] = (where, rename[storage], source)
    for old_name, new_name in rename.items():
      slot_origins[new_name] = slot_origins.pop(old_name)
      if old_name in origin_names:
        origin_names[new_name] = origin_names.pop(old_name)
      if old_name in hoisted_inits:
        hoisted_inits[new_name] = hoisted_inits.pop(old_name)
      if old_name in declared_at:
        declared_at[new_name] = declared_at.pop(old_name)
      for table in (reads, writes):
        if old_name in table:
          table[new_name] = table.pop(old_name)

  def drop_stale_origins(line):
    """Remove 'X = Y' notes where X now spells Y out."""
    found = split_origin_note(line)
    if found is None:
      return line
    body, pairs, how = found

    def says_it(pair):
      name, _, origin = pair.partition(" = ")
      return name.endswith("_" + origin.lstrip("_"))

    return rejoin_origin_note(body, [p for p in pairs if not says_it(p)], how)

  def flush_function(line_num):
    if not function_buffer:
      return
    spell_shared_slots()
    name_single_slots()
    mark_block_declarations()
    space_out_blocks()
    drop_unused_generated()
    if using_stack:
      # Without this the block silently swallows the rest of the function and
      # the area is never put back.
      raise SyntaxError(
        f"Line {using_stack[-1]['line']}: 'using' was never closed with "
        f"'end using'.")
    out_lines.append(function_buffer[0])
    out_lines.append("")

    body_lines = function_buffer[1:]

    # Trailing comments are not code: the last STATEMENT is what a defer goes
    # in front of, and what says whether the body can be reached its end
    # without returning.
    code_at = [i for i, l in enumerate(body_lines)
               if l.strip() and not l.strip().startswith("//")
               and (i + 1) not in buffer_comment_at]
    last = body_lines[code_at[-1]] if code_at else None

    # Any deferred statements still pending run at the natural end of the body.
    if defer_stack:
      # With no statement at all -- a body of declarations, which are hoisted,
      # and comments -- there is no last line to insert after, and the defers
      # used to be dropped without a word. They are still the function's exit
      # path, so they become the body.
      at = code_at[-1] + 1 if code_at else 0
      if last is None or not re_explicit_return.match(last):
        indent = leading_indent(last) if last is not None else "  "
        pending = [f"{indent}{unmask_literals(part, literal_parts)}"
                   for body in reversed(defer_stack)
                   for part in body.split("\n") if part.strip()]
        for offset, text in enumerate(pending):
          body_lines.insert(at + offset, text)

    for line in doc_comment:
      out_lines.append(line)
    remaining_body = body_lines

    if native_hoisted:
      # Declaration order, not alphabetical: a later Local may read an earlier one.
      for var in native_hoisted:
        # 'Local x := 1 as numeric', not 'Local x as numeric := 1'. Both are
        # written in xtpl; TLPP puts the type last when there is a value.
        kind = declared_types.get(var)
        note = f"  {hoisted_notes[var]}" if var in hoisted_notes else ""
        if var in hoisted_inits:
          tail = f" as {kind}" if kind else ""
          out_lines.append(f"  Local {var} := {hoisted_inits[var]}{tail}{note}")
        else:
          out_lines.append(
            f"  Local {var}{f' as {kind}' if kind else ''}{note}")
        if var in const_notes:
          out_lines.append(f"  {CONST_NOTE}")

    if native_hoisted:
      out_lines.append("")

    if generated_hoisted:
      width = max((len(v) for v in generated_hoisted), default=0)
      for var in sorted(generated_hoisted, key=scope_sort_key):
        shared = slot_origins.get(var) or []
        # A recycled slot lists every source variable that ever used it;
        # private storage already spells the name out, so it needs no note.
        if len(shared) == 1 and var.endswith(f"_{shared[0].lstrip('_')}"):
          shared = []                 # the name already says it
        note = f"  // {', '.join(shared)}" if shared else ""
        typed = f" as {declared_types[var]}" if var in declared_types else ""
        if var in hoisted_inits:
          out_lines.append(
            f"  Local {var} := {hoisted_inits[var]}{typed}{note}")
          if var in const_notes:
            out_lines.append(f"  {CONST_NOTE}")
        elif typed:
          out_lines.append(f"  Local {var}{typed}{note}")
        else:
          out_lines.append(f"  Local {var.ljust(width) if note else var}{note}")

    # After every Local, and not before. 'Private x := v' is an executable
    # statement, so a Local following one is rejected:
    #   appre0(21) Error C2051  LOCAL declaration follows executable statement
    for var in private_hoisted:
      typed = f" as {declared_types[var]}" if var in declared_types else ""
      if var in hoisted_inits:
        out_lines.append(f"  Private {var} := {hoisted_inits[var]}{typed}")
      else:
        out_lines.append(f"  Private {var}{typed}")

    if native_hoisted or generated_hoisted or private_hoisted:
      out_lines.append("")

    for line in remaining_body:
      # The declaration block already ends with a blank; the body often
      # begins with one too, and two in a row reads as a gap.
      if not line.strip() and out_lines and not out_lines[-1].strip():
        continue
      out_lines.append(line)

    # A function that returns a value on one path and nothing on another
    # hands the caller Nil, which is found out somewhere else and later.
    if returns_value:
      for line_no in returns_bare:
        print(f"warning: line {line_no}: this returns nothing, but the "
              f"function returns a value on line {returns_value[0]}",
              file=sys.stderr)
      if last is None or not re_explicit_return.match(last):
        print(f"warning: line {line_num}: the function can reach its end "
              f"without a return, but returns a value on line "
              f"{returns_value[0]}", file=sys.stderr)

    for mangled, (source_name, line_no) in sorted(
        declared_at.items(), key=lambda item: item[1][1]):
      if reads.get(mangled):
        continue
      # A PRIVATE exists for the functions this one calls. Not being read
      # here is the normal case, not a mistake.
      if mangled in private_hoisted:
        continue
      if writes.get(mangled):
        print(f"warning: line {line_no}: '{source_name}' is assigned but "
              f"never read", file=sys.stderr)
      else:
        print(f"warning: line {line_no}: '{source_name}' is declared but "
              f"never used", file=sys.stderr)
    declared_at.clear()
    reads.clear()
    writes.clear()

    function_buffer.clear()
    buffer_comment_at.clear()
    declared_lines.clear()
    doc_comment.clear()
    const_notes.clear()
    declared_types.clear()
    native_hoisted.clear()
    private_hoisted.clear()
    generated_hoisted.clear()
    hoisted_inits.clear()
    hoisted_notes.clear()
    defer_stack.clear()

  known_attributes = {"contained", "const"}

  # Markers that existed in earlier versions.
  re_stale_marker = re.compile(r'\[\s*(copyref|safe|internal|controlled|contained|discard)\s*\]', re.IGNORECASE)


  # local [controlled] x -- x may never leave its block: no call, no code
  # block, no @. Checked, not trusted.
  # local x <contained> -- attributes on a declarator, comma separated.
  # Between a name and ':=' no AdvPL expression can appear, so '<' and '>'
  # are unambiguous there.
  re_attributes = re.compile(r'<\s*([a-zA-Z_][a-zA-Z0-9_,\s]*?)\s*>')

  re_raw_any = re.compile(r'^\s*raw\b', re.IGNORECASE)
  re_directive = re.compile(r'^\s*#')

  re_by_ref = re.compile(r'@\s*([a-zA-Z_][a-zA-Z0-9_]*)')
  # A call: a name directly followed by '(', not preceded by ':' or '>'.
  re_call_name = re.compile(r'(?<![:>\w])([a-zA-Z_][a-zA-Z0-9_]*)\s*\(')
  re_any_local_decl = re.compile(
    r'^\s*(IF\s+|WHILE\s+|FOR\s+)?LOCAL\s+([a-zA-Z0-9_]+)\s*((?::=|\?=)?\s*.*)$',
    re.IGNORECASE)
  re_any_ident = re.compile(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b')
  re_namespaced = re.compile(r'^(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+\s*\(')

  re_block_open = re.compile(
    r'^\s*(?:IF|FOR|WHILE)\b(?!\s*\()|^\s*DO\s+CASE\b', re.IGNORECASE)
  re_block_close = re.compile(
    r'^\s*(?:ENDIF|NEXT|ENDDO|ENDCASE|END\s+CASE)\b', re.IGNORECASE)

  def block_ranges(body):
    """For each line, the block that encloses it and where that block ends."""
    enclosing = {}
    closes = {}
    open_stack = []
    for i, l in enumerate(body):
      enclosing[i] = open_stack[-1] if open_stack else -1
      if re_block_open.match(l):
        open_stack.append(i)
      elif re_block_close.match(l):
        if open_stack:
          closes[open_stack.pop()] = i
    for leftover in open_stack:
      closes[leftover] = len(body) - 1
    return enclosing, closes

  def leaves_the_block(name, text):
    """Can this line let the variable outlive the block it was declared in?

    Passing an array or object hands over the OBJECT; rebinding our name
    afterwards cannot reach it, so a call is not a hazard whatever it does
    with what it was given. A code block is different: it captures the
    VARIABLE as a detached local, so a later write to a recycled slot changes
    what the block sees. That is the whole rule, and it applies to numbers and
    strings exactly as it does to arrays.

    Two more routes to the same place: @ hands over the variable itself, and a
    raw line goes to a command this transpiler cannot see into -- GET in
    particular binds the variable to a dialog that outlives the block.
    """
    if "{|" in text:
      return True
    if re.search(rf'@\s*{re.escape(name)}\b', text, re.IGNORECASE):
      return True
    if re_raw_any.match(text):
      return True
    # A 'defer' body runs at an exit from the FUNCTION, long after the block
    # holding the variable has gone. Recycling its slot to a sibling block in
    # between leaves the defer reading whatever that sibling put there --
    # silently, and with the right-looking name in the origin comment.
    if re_defer.match(text):
      return True
    return False

  def collect_pinned():
    """Per function, the DECLARATIONS whose variable cannot share storage.

    Keyed by declaration line, not by name: two blocks may both declare aTmp,
    and one being captured says nothing about the other. Each declaration is
    checked only against the lines its own variable is live for.
    """
    result = {}
    bounds = []
    current, start = None, None
    for i, raw in enumerate(lines):
      if re_func.search(raw):
        if current is not None:
          bounds.append((start, i, current))
        current, start = set(), i
        result[i] = current
    if current is not None:
      bounds.append((start, len(lines), current))

    for start, end, pinned in bounds:
      body = []
      decls = []
      for offset, raw in enumerate(lines[start + 1:end]):
        if (start + 1 + offset) in block_comment_lines:
          body.append("")             # prose, not a statement
          continue
        masked, here = mask_literals(raw)
        if re_attributes.search(masked) and not re_any_local_decl.match(
            re_attributes.sub(" ", masked)):
          raise SyntaxError(
            f"Line {start + offset + 2}: attributes may only mark a declaration.")
        body.append(masked)
        decl = re_any_local_decl.match(masked)
        if decl:
          intro = (decl.group(1) or "").strip().upper()
          if intro in ("IF", "WHILE", "FOR"):
            # A block header declares exactly one variable, before its comma.
            names = [(decl.group(2), False)]
          else:
            names = [(n, "contained" in a) for n, _, _, a, _t in
                     # A space between them: the pattern ate the one that
                     # was there, which did not matter while the rest always
                     # began with ':=' and does now that 'as' can follow.
                     parse_declarators(f"{decl.group(2)} {decl.group(3)}",
                                       start + offset + 2, here)]
          for name, marked in names:
            decls.append({
              "index": offset,
              "line": start + offset + 2,
              "name": name,
              "opens_block": intro in ("IF", "WHILE", "FOR"),
              "contained": marked,
            })

      enclosing, closes = block_ranges(body)

      for d in decls:
        # The variable is live from its declaration to the end of the block it
        # belongs to -- the block it opens, or the one it sits inside.
        if d["opens_block"]:
          last = closes.get(d["index"], len(body) - 1)
        else:
          owner = enclosing.get(d["index"], -1)
          last = closes.get(owner, len(body) - 1) if owner >= 0 else len(body) - 1

        name = d["name"].lower()
        word = re.compile(rf'\b{re.escape(name)}\b', re.IGNORECASE)

        for offset in range(d["index"], min(last, len(body) - 1) + 1):
          l = body[offset]
          if not word.search(l) or not leaves_the_block(name, l):
            continue
          if d["contained"]:
            raise SyntaxError(
              f"Line {start + offset + 2}: '{d['name']}' is <contained> "
              f"(declared on line {d['line']}) and cannot leave its block.")
          pinned.add(d["line"])
          break
    return result

  # Names promised by an 'external' line: constants from an #include the
  # transpiler cannot read, and PUBLIC variables set by a caller. They are
  # readable, never assignable, and emit nothing.
  external_names = {}
  # Aliases the caller opens. The same promise 'external' makes about a name:
  # it exists, this file just cannot see where it came from.
  external_aliases = set()
  for line_no, raw in enumerate(folded_lines, start=1):
    masked_line, parts_here = mask_literals(raw)
    # Without peeling, a comment after the declaration is read as one of the
    # names -- the same end-of-line anchor that broke the loop headers.
    masked_line, _ = peel_comment(masked_line, parts_here)
    found = re.match(r'^\s*external\s+(.+)$', masked_line, re.IGNORECASE)
    if not found:
      continue
    aliased = re.match(r'^\s*alias\s+(.+)$', found.group(1), re.IGNORECASE)
    if aliased:
      for name in split_top_level(aliased.group(1)):
        name = name.strip()
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', name):
          raise SyntaxError(
            f"Line {line_no}: 'external alias' takes plain names, got '{name}'.")
        external_aliases.add(name.upper())
      continue
    for name in split_top_level(found.group(1)):
      name = name.strip()
      if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', name):
        raise SyntaxError(
          f"Line {line_no}: 'external' takes plain names, got '{name}'.")
      external_names[name.lower()] = line_no

  # A PRIVATE is dynamically scoped: declared in one function, visible to
  # everything it calls. So the name is known for the whole file -- readable
  # and assignable, unlike 'external', which promises only that it exists.
  # Collected up front for the same reason 'external' is: the function that
  # reads one is usually above the function that declares it.
  private_names = {}
  for line_no, raw in enumerate(source_code.splitlines(), start=1):
    masked_line, masked_parts = mask_literals(raw)
    found = re.match(r'^\s*private\s+(.+)$', masked_line, re.IGNORECASE)
    if not found:
      continue
    for name, _op, _v, _a, _t in parse_declarators(found.group(1), line_no,
                                                   masked_parts):
      private_names[name.lower()] = line_no

  # Names introduced by the preprocessor are not variables either.
  defined_constants = {
    m.group(1).lower()
    for m in re.finditer(r'^\s*#\s*define\s+([a-zA-Z_][a-zA-Z0-9_]*)',
                         "\n".join(folded_lines), re.IGNORECASE | re.MULTILINE)
  }

  # Every function declared in this file, and how many parameters it takes.
  # AdvPL checks none of this: a call with too many arguments compiles, and
  # the extras are simply unreachable.
  re_signature = re.compile(
    r'^\s*(?:(?P<kind>User|Static|Main)\s+)?Function\s+'
    r'(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\s*\(', re.IGNORECASE)
  local_functions = {}
  # How each is declared, so a call can be checked against it: a User Function
  # is reached as 'u_name' because the compiler adds the prefix, and a Static
  # one by its plain name. Getting that backwards compiles and links and then
  # fails at run time with 'cannot find function U_ENVDIR in AppMap'.
  local_kind = {}
  for line_no, raw in enumerate(folded_lines, start=1):
    masked_line, _ = mask_literals(raw)
    named = re_signature.match(masked_line)
    if not named:
      continue
    params, _ = extract_parens(masked_line, masked_line.find("("))
    if params is None:
      continue
    listed = [x for x in split_top_level(params) if x.strip()]
    local_functions[named.group("name").lower()] = (named.group("name"),
                                                    len(listed), line_no)
    local_kind[named.group("name").lower()] = (named.group("kind") or "").lower()

  pinned_by_func = collect_pinned()
  # '#translate' rules for slots shared by more than one block variable,
  # gathered across the file and emitted at the top of it.
  translate_rules = set()

  temp_counters = {}
  object_stack = []
  literal_parts = []

  re_generated_name = re.compile(r'\b[sb]_\d+_\w+\b')

  def annotate_origins(text):
    """Tag a line with the source variable behind each generated name.

    Masking first means names inside string literals or an existing comment are
    left alone, so re-annotating is a no-op and quoted code stays untouched.
    """
    masked, parts = mask_literals(text)
    seen = []
    for m in re_generated_name.finditer(masked):
      name = m.group(0)
      origin = origin_names.get(name)
      # Private storage spells the source name out already.
      if origin and not name.endswith(f"_{origin}") and name not in [n for n, _ in seen]:
        seen.append((name, origin))
    if not seen:
      return text
    note = ", ".join(f"{name} = {origin}" for name, origin in seen)
    tail = re.search(r'\x00([\ue000-\uf8ff])\x00\s*$', masked)
    if tail and parts[ord(tail.group(1)) - _MASK_BASE].startswith("//"):
      # Fold into the comment already at the end of the line.
      idx = ord(tail.group(1)) - _MASK_BASE
      parts = list(parts)
      parts[idx] = f"{parts[idx].rstrip()}  ({note})"
      return unmask_literals(masked, parts)
    return f"{unmask_literals(masked, parts)}  // {note}"

  # 'M->' and 'FIELD->' name a memory variable and the current record rather
  # than a table, so they are not aliases to look up.
  not_aliases = {"m", "field", "memvar"}
  re_field_ref = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)->([A-Za-z_][A-Za-z0-9_]*)\b')
  reported_fields = set()
  reported_aliases = set()

  # What counts as opening an alias. 'using alias' and 'rows()' both emit a
  # DbSelectArea, so they are covered without naming them here.
  re_alias_open = re.compile(
    r'\b(?:DbSelectArea|dbUseArea|ChkFile)\s*\(', re.IGNORECASE)

  def note_open_aliases(text):
    for opener in re_alias_open.finditer(text):
      args, _ = extract_parens(text, opener.end() - 1)
      if args is None:
        continue
      for argument in split_top_level(args):
        argument = argument.strip()
        if not re_string_token.match(argument):
          continue
        name = unmask_literals(argument, literal_parts).strip("\"'")
        if re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', name):
          open_aliases.add(name.upper())

  def check_fields(text):
    """Check every 'ALIAS->FIELD': that it is open, and that it exists.

    Run on emitted lines rather than source, so a field named through
    'rows(\"SA1\") |> map([r] r:A1_VALOR)' is checked too -- the chain has by
    then become an ordinary SA1->A1_VALOR, and it is the one place the alias
    and the field are known together beyond doubt.
    """
    for found in re_field_ref.finditer(text):
      alias, field = found.group(1), found.group(2)
      lowered = alias.lower()
      if alias.startswith("__") or lowered in not_aliases:
        continue
      # A variable holding an alias, as in '(cAlias)->A1_COD': what it holds
      # is not known here, so there is nothing to check it against.
      if any(lowered in scope_vars[s_id] for s_id in scope_stack):
        continue
      seen = (current_line_no, alias.upper(), field.upper())
      if seen in reported_fields:
        continue
      reported_fields.add(seen)

      # Nothing in this function opened it. Reported once per alias, not per
      # use: a function naming SA1 twenty times has one problem, not twenty.
      # Off under --legacy, where an alias opened by the caller is the norm.
      if (not legacy and alias.upper() not in open_aliases
          and alias.upper() not in external_aliases
          and alias.upper() not in reported_aliases):
        reported_aliases.add(alias.upper())
        print(f"warning: line {current_line_no}: nothing in this function "
              f"opened {alias.upper()}. Wrap the use in 'using alias "
              f"{alias.upper()} do', or declare 'external alias "
              f"{alias.upper()}' if the caller opens it.", file=sys.stderr)

      if not dictionary:
        continue
      if alias.upper() not in dictionary:
        report_dictionary(
          f"alias '{alias}' is not in the dictionary. A table that is missing "
          f"usually means the export is out of date.")
        continue
      if not dictionary:
        continue
      fields = dictionary[alias.upper()]
      if field.upper() in fields:
        continue
      near = difflib.get_close_matches(field.upper(), sorted(fields), 1, 0.7)
      hint = f" Did you mean {near[0]}?" if near else ""
      report_dictionary(
        f"'{alias}->{field}' is not a field of {alias.upper()}.{hint}")

  # AdvPL's own letters. A memo holds characters, so it takes the same
  # literals as C.
  _TYPE_NAMES = {"C": "character", "N": "numeric", "D": "date",
                 "L": "logical", "M": "memo"}
  _LITERAL = r'(?:\x00[\ue000-\uf8ff]\x00|[+-]?\d+(?:\.\d+)?|\.[TtFf]\.)'
  _FIELD = r'[A-Za-z_][A-Za-z0-9_]*->[A-Za-z_][A-Za-z0-9_]*'
  _COMPARE = r'(?::=|==|!=|<>|>=|<=|#|=|>|<|\$)'
  re_field_literal = re.compile(
    rf'\b({_FIELD})\s*({_COMPARE})\s*({_LITERAL})')
  re_literal_field = re.compile(
    rf'({_LITERAL})\s*({_COMPARE})\s*\b({_FIELD})')

  def literal_kind(text):
    """(type letter, text) for an AdvPL literal, or (None, None).

    Only literals are typed. Anything else would need inference across an
    untyped language, which is how a checker turns into a false-positive
    machine -- and Nil is left alone, since assigning it is ordinary.
    """
    text = text.strip()
    if re_string_token.match(text):
      return "C", unmask_literals(text, literal_parts).strip("\"'")
    if re_number_literal.match(text):
      return "N", text
    if re.fullmatch(r'\.[TtFf]\.', text):
      return "L", text
    return None, None

  re_any_call = re.compile(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(')

  def check_arity(text):
    """A call to a function in this file, given more arguments than it takes.

    Only too MANY is reported. AdvPL fills a missing parameter with Nil and
    plenty of code relies on that, so fewer is ordinary; more is always a
    mistake, because the extras cannot be reached.
    """
    if not local_functions:
      return
    at = 0
    while True:
      called = re_any_call.search(text, at)
      if not called:
        return
      at = called.end()
      known = local_functions.get(called.group(1).lower())
      # A declaration is not a call, and neither is a name this transpiler
      # generated around one.
      if not known or re_signature.match(text.strip()):
        continue
      args, _ = extract_parens(text, called.end() - 1)
      if args is None:
        continue
      passed = len([x for x in split_top_level(args) if x.strip()])
      name, wanted, declared_at = known
      if passed <= wanted:
        continue
      message = (f"Line {current_line_no}: {name}() takes {wanted} "
                 f"parameter{'' if wanted == 1 else 's'} (line {declared_at}), "
                 f"but is given {passed}.")
      if legacy:
        print(f"warning: {message}", file=sys.stderr)
      else:
        raise SyntaxError(message)

  def check_types(text):
    """A field used with a literal of the wrong type, or one too long."""
    if not dictionary:
      return
    pairs = ([(m.group(1), m.group(2), m.group(3)) for m in
              re_field_literal.finditer(text)] +
             [(m.group(3), m.group(2), m.group(1)) for m in
              re_literal_field.finditer(text)])
    for reference, operator, literal in pairs:
      alias, _, field = reference.partition("->")
      known = dictionary.get(alias.upper())
      if not known or not isinstance(known, dict):
        continue
      declared = known.get(field.upper())
      if not declared or not declared[0]:
        continue
      kind, size = declared
      seen, value = literal_kind(literal)
      if seen is None:
        continue

      wanted = "C" if kind == "M" else kind
      if seen != wanted:
        report_dictionary(
          f"{reference} is {_TYPE_NAMES.get(kind, kind)}, "
          f"{'assigned' if operator == ':=' else 'compared with'} a "
          f"{_TYPE_NAMES.get(seen, seen)} value.")
        continue

      # Silent truncation: AdvPL writes what fits and drops the rest.
      if operator == ":=" and wanted == "C" and size and len(value) > size:
        report_dictionary(
          f"{reference} holds {size} characters, but is assigned "
          f"{len(value)}.")

  def report_dictionary(message):
    # A warning by default: a field being added may not be in an export yet,
    # and a stale dictionary should not stop a build. --dict-strict for CI.
    #
    # Errors say 'Line', warnings say 'line', throughout -- so the prefix is
    # added here rather than written into each message twice.
    if dict_strict:
      raise SyntaxError(f"Line {current_line_no}: {message}")
    print(f"warning: line {current_line_no}: {message}", file=sys.stderr)

  def emit(text):
    """Restore masked literals and push one or more physical lines.

    A statement that expands to several lines is followed by a blank, so the
    tail of one and the head of the next do not run together -- 'n := fo_0_0'
    sitting directly above 'fok_0_0 := File(cB)' reads as one statement when
    it is two. Runs of blanks are collapsed afterwards, so this never doubles
    up with the spacing around control structures.
    """
    note_open_aliases(text)
    check_fields(text)
    check_types(text)
    check_arity(text)
    produced = unmask_literals(text, literal_parts).split("\n")
    for sub_line in produced:
      if not sub_line.strip():
        function_buffer.append(sub_line)
        continue
      written = annotate_origins(sub_line)
      if map_lines:
        # Every emitted line carries the source line it came from, so a
        # runtime error in the .tlpp can be read back to what was written.
        # One source line often becomes a dozen, so the marker goes on all of
        # them rather than the first -- scanning upwards is exactly the work
        # this exists to remove.
        written = f"{written}  // xtpl:{current_line_no}"
      function_buffer.append(written)
    if len(produced) > 1 and function_buffer and function_buffer[-1].strip():
      function_buffer.append("")

  def apply_with_object(text):
    """Replace a subject-relative ':' with the innermost with-object holder.

    A ':' following a name, ')' or ']' is member access and is left alone, as
    are '::' for self and ':=' for assignment. What remains is a colon in a
    position where AdvPL could not have put one, which is the shorthand.
    """
    if not object_stack:
      return text
    holder = object_stack[-1]
    out = []
    i = 0
    while i < len(text):
      char = text[i]
      if char != ":":
        out.append(char)
        i += 1
        continue
      if text.startswith("::", i) or text.startswith(":=", i):
        out.append(text[i:i + 2])
        i += 2
        continue
      before = "".join(out).rstrip()
      if before and (before[-1].isalnum() or before[-1] in "_)]:"):
        out.append(char)
      else:
        out.append(holder + ":")
      i += 1
    return "".join(out)

  # The key ends at a comma as well as at a bracket or a connective. Without
  # that, 'f(h has "k", 0, @a)' took the whole argument list as the key and
  # generated 'h:Get("k", 0, @a, @tmp)' -- the same fault 'in' had, which is
  # why both now stop at the first separator of the expression they sit in.
  re_hash_has = re.compile(
    r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s+has\s+(.+?)(?=\s*(?:\.and\.|\.or\.|,|\)|$))',
    re.IGNORECASE)

  def hash_literal_pairs(expr):
    """The key/value pairs if expr is a whole hash literal, else None.

    A brace group is a hash when its top-level parts are all 'k => v'. An
    array literal has none, so the two are told apart by shape.
    """
    nodes = expr_nodes(expr.strip())
    if len(nodes) != 1:
      return None
    node = nodes[0]
    if node["k"] != "group" or node["open"] != "{" or not node["close"]:
      return None
    if node["head"]:
      return None                     # a code block, not a literal
    inner = render_nodes(node["items"]).strip()
    if inner == "=>":
      return []                       # {=>} is the empty hash
    if not inner:
      return None
    pairs = []
    for part in split_nodes(node["items"]):
      halves = split_nodes_text(part, "=>")
      if halves is None:
        return None                   # no pairs: an array literal
      pairs.append((render_nodes(halves[0]).strip(),
                    render_nodes(halves[1]).strip()))
    return pairs

  def build_hash(target, pairs, indent):
    out = [f"{indent}{target} := THashMap():New()"]
    out.extend(f"{indent}{target}:Set({key}, {value})" for key, value in pairs)
    return out

  def transpile_hash(line, curr_scope):
    """Hash literals and h{key} access.

    '{' after a name is a hash subscript -- AdvPL never puts a brace there --
    so arrays keep '[' and there is no need to track which variables are
    hashes.
    """
    prefix, expr = split_prefix(line)
    statements = []

    # 'h has k' -- Get returns a logical, so the test costs nothing extra.
    while True:
      probe = re_hash_has.search(line)
      if not probe:
        break
      temp = next_temp("hash_tmp", curr_scope)
      statements.append(f"{leading_indent(line)}{temp} := Nil")
      line = (line[:probe.start()] +
              f"{probe.group(1)}:Get({probe.group(2).strip()}, @{temp})" +
              line[probe.end():])

    # A whole literal on the right of an assignment builds into the target.
    pairs = hash_literal_pairs(expr)
    if pairs is not None and prefix.strip().endswith(":="):
      return "\n".join(build_hash(prefix.strip()[:-2].strip(), pairs,
                                   leading_indent(prefix)))

    while True:
      found = hash_subscript(expr_nodes(line))
      if found is None:
        break
      before, holder, key, rest, closed = found
      if not closed:
        raise SyntaxError(f"Line {current_line_no}: unbalanced '{{' in a hash access.")
      key = key.strip()
      indent = leading_indent(line)

      assign_at = find_top_level(rest, ":=")
      if assign_at >= 0 and not rest[:assign_at].strip():
        # h{k} := v  ->  h:Set(k, v)
        value = rest[assign_at + 2:].strip()
        line = f"{indent}{holder}:Set({key}, {value})"
        continue

      # Reading: Get leaves the variable alone when the key is absent, so the
      # temp is cleared first and a miss reads back as Nil.
      temp = next_temp("hash_tmp", curr_scope)
      statements.append(f"{indent}{temp} := Nil")
      statements.append(f"{indent}{holder}:Get({key}, @{temp})")
      line = before + temp + rest

    if statements:
      return "\n".join(statements + [line])
    return line

  def emit_raw(text):
    """Rename declared variables, leave every other word alone."""
    nonlocal lenient_names
    lenient_names = True
    try:
      rendered = re.sub(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', resolve_identifier, text)
    finally:
      lenient_names = False

    # A command can write to whatever it is given -- GET in particular -- and
    # this transpiler cannot see inside one. Say so in both places.
    touched = sorted(origin_names.get(m, m) for m in const_names
                     if re.search(rf'\b{re.escape(m)}\b', rendered))
    if touched:
      names = ", ".join(touched)
      print(f"warning: line {current_line_no}: <const> {names} passed to a raw "
            f"command, which may write to it", file=sys.stderr)
      emit(f"{leading_indent(text)}// WARNING: <const> {names} handed to a raw "
           f"command -- xtpl cannot check that it is not written to")
    emit(rendered)

  # Short names for the generated temporaries. '__fuse_out_0_0' said nothing
  # that 'fo_0_0' does not, and a fused chain puts six of them on screen at
  # once. The trailing '_<depth>_<index>' is what makes them impossible to
  # collide with anything written by hand, and it is kept.
  _SHORT_TEMP = {
    "fuse_acc": "fa", "fuse_alias": "fal", "fuse_area": "far",
    "fuse_bag": "fbg", "fuse_best": "fbs", "fuse_chunk": "fch",
    "fuse_drop": "fdr", "fuse_first": "ffs", "fuse_had": "fhd",
    "fuse_hi": "fhi", "fuse_i": "fi", "fuse_j": "fj", "fuse_key": "fky",
    "fuse_last": "fls", "fuse_lim": "flm", "fuse_lo": "flo", "fuse_n": "fn",
    "fuse_older": "fol", "fuse_open": "fop", "fuse_out": "fo",
    "fuse_prev": "fpv", "fuse_probe": "fpb", "fuse_ready": "frd",
    "fuse_ok": "fok", "fuse_rec": "frc", "fuse_seen": "fsn", "fuse_sep": "fsp",
    "fuse_src": "fs", "fuse_v": "fv",
    "elvis_tmp": "et", "guard_tmp": "gt", "hash_tmp": "ht", "pipe_tmp": "pt",
  }

  def next_temp(kind, curr_scope):
    """A generated temporary, drawn from a pool reset at every statement.

    These live for exactly one statement -- a chain's accumulator, a lifted
    fold, the saved error block -- so no analysis is needed to know they are
    dead by the next line. Two of the same kind only coexist when one
    statement needs both, which is what the counter tracks.
    """
    index = temp_counters.get(kind, 0)
    temp_counters[kind] = index + 1
    name = f"{_SHORT_TEMP[kind]}_{scope_number(curr_scope)}_{index}"
    add_generated(name)
    return name

  def rewrite_lambda_body(body, aliases, curr_scope):
    mangled = []
    for alias in aliases:
      mangled_alias = register_xtpl_variable(alias, curr_scope)
      body = re.sub(rf'\b{re.escape(alias)}\b', mangled_alias, body, flags=re.IGNORECASE)
      mangled.append(mangled_alias)
    return mangled, body

  # Everything the runtime provides. These are ordinary calls, so a pipeline
  # stage naming one needs no special handling -- the generic rule composes
  # them, and the prefix keeps them clear of same-named functions elsewhere.
  runtime_verbs = (
    "map", "filter", "reject", "reduce", "fold", "take", "drop", "distinct",
    "sort", "sortby", "reverse", "flatten", "enumerate", "chunks", "zip",
    "asum", "aprod", "amax", "amin",
    "anyof", "allof", "noneof",
    # Hashes. A hash was invisible to the pipeline: 'for' walks arrays, so
    # there was no way to iterate one at all. These return arrays, so
    # everything else composes with no further work.
    "keys", "values", "pairs",
    # Strings. Only names AdvPL does not already have: Upper, AllTrim, PadL
    # and the rest take their subject first, so they already compose with
    # '|>' and intercepting them would shadow the originals on every existing
    # call in the codebase.
    "takewhile", "dropwhile", "chunkby", "first", "count",
    "distinctadjacent", "maxby", "minby",
    "scan", "expand", "tap", "pairwise",
    "queue",
    "split", "join", "starts", "ends", "contains",
  )
  # Not after ':' or '->': a METHOD or a field-scoped call that happens to
  # share a name with a runtime verb is not that verb. 'oFila:Count()' was
  # being rewritten to 'oFila:u_xtpl_count()', and so would any object with a
  # Map, First or Take method.
  re_verb_call = re.compile(
    r'(?<![:>])\b(' + "|".join(runtime_verbs) + r')\s*\(', re.IGNORECASE)

  # Up to six names, for zip over several arrays.
  re_lambda_head = re.compile(
    r'\[\s*([a-zA-Z_][a-zA-Z0-9_]*(?:\s*,\s*[a-zA-Z_][a-zA-Z0-9_]*){0,5})\s*\]')

  def transpile_lambdas(line, curr_scope):
    """Turn '[x] body' in argument position into a code block.

    Only in argument position: a '[' that follows a name, ')' or ']' is an
    index, and '<contained>' / '[+]' are handled elsewhere.
    """
    while True:
      replaced = False
      for m in re_lambda_head.finditer(line):
        before = line[:m.start()].rstrip()
        if before and before[-1] not in "(,":
          continue
        aliases = [a.strip() for a in m.group(1).split(",")]
        if any(a.lower() in known_words or a.lower() in reserved_words
               for a in aliases):
          continue
        end = argument_end(line, m.end())
        body = line[m.end():end].strip()
        if not body:
          continue
        mangled, rewritten = rewrite_lambda_body(body, aliases, curr_scope)
        block = "{|" + ", ".join(mangled) + "| " + rewritten + "}"
        line = line[:m.start()] + block + line[end:]
        replaced = True
        break
      if not replaced:
        return line

  def argument_end(text, start):
    """End of the argument beginning at start: a top-level comma or close."""
    depth = 0
    for i in range(start, len(text)):
      char = text[i]
      if char in _OPENERS:
        depth += 1
      elif char in _CLOSERS:
        if depth == 0:
          return i
        depth -= 1
      elif char == "," and depth == 0:
        return i
    return len(text)

  def transpile_membership(line, curr_scope):
    """'x in a' and 'x in lo..hi'.

    '$' searches a string only, so an array needs aScan. A range is two
    comparisons and needs no runtime at all.
    """
    while True:
      found = membership_span(expr_nodes(line))
      if found is None:
        break
      before, value, collection, after = found
      span = re_range.match(collection)
      if span:
        low, high = span.group(1).strip(), span.group(2).strip()
        built = f"({value} >= {low} .And. {value} <= {high})"
      else:
        built = f"u_xtpl_in({value}, {collection})"
      line = before + built + after
    return line

  def transpile_feed_chains(line, curr_scope, line_idx, guarded=False,
                            for_value=False):
    """'guarded' says a 'fallback' was peeled off this statement.

    It used to be read straight out of the enclosing loop's 'fallback_val',
    which meant this function only worked when called from that one place.
    Passing it makes the pipeline callable from anywhere.
    """
    nodes = expr_nodes(line)
    if feed_in_block(nodes):
      raise SyntaxError(
        f"Line {line_idx + 1}: '|>' cannot chain inside a code block -- "
        f"lifting its stages out would run them before the block does.")

    # A chain nested inside an expression is lifted into its own statement
    # first -- the same move the fold and elvis passes make -- and a temp left
    # where it stood. This runs whether or not there is also a chain at this
    # level, because one can appear inside the other's argument:
    # 'a |> take(len(b |> distinct))'.
    lifted = []
    while True:
      found = feed_slice(expr_nodes(line), line_idx + 1)
      if found is None:
        break
      before, inner, after = found
      inner = inner.strip()
      if len(feed_segments(expr_nodes(inner))) < 2:
        break
      # Transpiled as a bare expression: the chain's own last temp becomes the
      # holder, so no extra assignment is generated.
      produced = transpile_feed_chains(
        f"{leading_indent(line)}{inner}", curr_scope, line_idx,
        guarded, for_value=True).split("\n")
      lifted.extend(produced[:-1])
      line = before + produced[-1].strip() + after

    prefix, expr = split_prefix(line)
    # 'lines(f)' with no stages is still a chain -- every line of the file --
    # so it takes the walk below rather than being left as a call to a
    # function that does not exist.
    whole = re_lines_head.match(expr.strip())
    if whole:
      inner, after_call = extract_parens(expr.strip(), whole.end() - 1)
      whole = inner is not None and not expr.strip()[after_call:].strip()
    if len(feed_segments(expr_nodes(line))) < 2 and not (whole and prefix.strip()):
      return "\n".join(lifted + [line]) if lifted else line

    indent = leading_indent(prefix)

    parts = feed_segments(expr_nodes(expr))

    # The whole left side becomes the first argument, which is the rule and is
    # exactly what someone writing 'a == 3 .and. aList |> allof(...)' did not
    # mean. It compiles and quietly passes the comparison as the collection.
    if len(parts) > 1 and not for_value:
      head_text = parts[0]
      # At depth zero only. A complete call whose arguments contain a
      # comparison -- 'zip(a, b, [x, y] len(x) == len(y))' -- is not a loose
      # left side, and warning about it taught people to ignore the warning.
      bare, depth = [], 0
      for char in head_text:
        if char in "([{":
          depth += 1
        elif char in ")]}":
          depth -= 1
        elif depth == 0:
          bare.append(char)
      loose = re.search(r'\.(?:and|or)\.|[<>]=?|==|!=|<>', "".join(bare),
                        re.IGNORECASE)
      if loose:
        print(f"warning: line {line_idx + 1}: the whole left side of '|>' is "
              f"the first argument, so '{head_text.strip()[:40]}' is what "
              f"gets fed in. Put brackets around the part you meant to chain.",
              file=sys.stderr)

    head_expr = parts[0].strip()
    if not head_expr:
      # Nothing to feed. Reached by a continuation that failed to join, which
      # left '|> filter(...)' standing on its own -- and the stage was then
      # composed with an empty first argument rather than refused.
      raise SyntaxError(f"Line {line_idx + 1}: '|>' has nothing on its left.")

    fused, fused_result, remaining, blocked_by = fuse_chain(
      prefix, parts, curr_scope, line_idx, for_value, guarded)
    if blocked_by is not None and len(parts) > 2:
      name, known = blocked_by
      why = ("it needs the whole collection" if known else
             "xtpl cannot see inside it")
      print(f"warning: line {line_idx + 1}: this chain does not fuse -- "
            f"'{name}' stops it, because {why}, so it and every stage after "
            f"it builds an array", file=sys.stderr)

    statements = lifted + list(fused)
    if fused and fused_result is None:
      return "\n".join(statements)    # run for effects: there is no result line
    current_expr = fused_result if fused else head_expr

    # With no assignment or return in front, the chain is being run for its
    # effects. The last stage is then a statement in its own right and needs
    # no temp -- assigning one would leave a bare variable on a line of its
    # own, which is dead code.
    discards_result = not prefix.strip() and not guarded

    for position, raw_segment in enumerate(remaining, start=1):
      last_stage = position == len(remaining)
      segment = raw_segment.strip()
      if not segment:
        continue
      if re_reduce_operator.match(segment):
        raise SyntaxError(
          f"Line {line_idx + 1}: '{segment}' folds an array, it is not a "
          f"pipeline stage. Write it as '{segment}<array>'.")

      # One rule: the running value becomes the first argument.
      head = re_pipe_segment.match(segment)
      if not head:
        raise SyntaxError(f"Line {line_idx + 1}: cannot parse pipeline stage '{segment}'.")
      name = head.group(1)
      if head.group(2):
        args, end_idx = extract_parens(segment, head.end() - 1)
        if args is None:
          raise SyntaxError(
            f"Line {line_idx + 1}: unbalanced parentheses in pipeline stage '{segment}'.")
        if segment[end_idx:].strip():
          raise SyntaxError(
            f"Line {line_idx + 1}: trailing text after pipeline stage '{segment}'.")
        args = args.strip()
        composed = f"{name}({current_expr}, {args})" if args else f"{name}({current_expr})"
      else:
        composed = f"{name}({current_expr})"

      if last_stage and discards_result:
        statements.append(f"{indent}{composed}")
        return "\n".join(statements)

      temp_pipe = next_temp("pipe_tmp", curr_scope)
      statements.append(f"{indent}{temp_pipe} := {composed}")
      current_expr = temp_pipe

    statements.append(f"{prefix}{current_expr}")
    return "\n".join(statements)

  # Stages that look at one element at a time, so a chain of them is one
  # pass over the source and needs no array between the stages.
  _FUSE_STEPS = ("map", "filter", "reject", "take", "drop",
                 "takewhile", "dropwhile", "distinctadjacent",
                 "scan", "expand", "tap", "pairwise")
  # Stages that collapse the elements into one value, as the last stage.
  # 'join' is the only one that takes an argument, which is why it is
  # recognised separately below rather than by having none.
  _FUSE_FOLDS = {"asum": "0", "aprod": "1", "amax": "Nil", "amin": "Nil",
                 "join": '""'}
  # Predicates: they answer as soon as they can, so the loop leaves early
  # rather than reading the rest of the source for an answer it already has.
  _FUSE_PREDICATES = {"anyof": ".F.", "allof": ".T.", "noneof": ".T."}
  # 'reduce' and 'fold' carry their own combining step, so they need no name
  # to be known in advance -- which is what stops the fusable terminals being
  # a closed list. The four above stay as sugar over what reduce spells out.
  _FUSE_TERMINALS = (set(_FUSE_FOLDS) | {"reduce", "fold", "chunkby",
                                         "first", "count",
                                         "maxby", "minby"}
                     | set(_FUSE_PREDICATES))
  # Terminals that read the ELEMENT rather than a value made from it, so a
  # chain over rows() needs no map before one. 'first' is not among them: it
  # hands the element back, and a work-area record is not a value.
  _FUSE_ELEMENTWISE_OK = set(_FUSE_PREDICATES) | {"count"}
  # Everything else has to see the whole collection before it can produce
  # anything: sorting, reversing and flattening cannot start until the last
  # element is known, and distinct has to remember what it has seen.
  re_block_literal = re.compile(r'^\{\s*\|([^|]*)\|(.*)\}$', re.DOTALL)

  def read_stage(segment):
    """(name, args) for a pipeline stage, or None if it is not one."""
    head = re_pipe_segment.match(segment)
    if not head:
      return None
    if not head.group(2):
      return head.group(1).lower(), ""
    inner, end_idx = extract_parens(segment, head.end() - 1)
    if inner is None or segment[end_idx:].strip():
      return None
    return head.group(1).lower(), inner.strip()

  def expand_bare_blocks(line, curr_scope):
    """Rewrite 'verb(name)' into 'verb([x] name(x))' before anything else."""
    for found in list(re_verb_call.finditer(line)):
      verb = found.group(1).lower()
      if verb not in _TAKES_A_BLOCK:
        continue
      args, end_idx = extract_parens(line, found.end() - 1)
      if args is None:
        continue
      pieces = split_top_level(args)
      changed = False
      # The LAST argument only. For every one of these verbs the block comes
      # last, and converting any bare name turned the collection into a block
      # too -- 'allof(b, ehOk)' inside a lambda, where 'b' is the lambda's own
      # parameter and is not in scope yet when this runs.
      if pieces:
        index = len(pieces) - 1
        widened = name_as_block(verb, pieces[index].strip(), curr_scope)
        if widened != pieces[index].strip():
          pieces[index] = widened
          changed = True
      if changed:
        return expand_bare_blocks(
          line[:found.end()] + ", ".join(pieces) + line[end_idx - 1:],
          curr_scope)
    return line

  # Verbs whose argument is a block, and which therefore accept a bare
  # function name standing for one.
  _TAKES_A_BLOCK = {
    "map", "filter", "reject", "tap", "takewhile", "dropwhile", "expand",
    "maxby", "minby", "sortby", "chunkby", "distinctadjacent", "first",
    "count", "anyof", "allof", "noneof",
  }
  re_bare_name = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

  def name_as_block(verb, args, curr_scope):
    """'map(alltrim)' means 'map([x] alltrim(x))'.

    Writing the lambda out is three tokens of ceremony for something the
    reader already understands, and 'alltrim' on its own read as an
    undeclared name -- a poor error for a reasonable thing to write.

    A name that IS a variable in scope is left alone: a block held in a
    variable is a perfectly good argument, and that is what it means.
    """
    if verb not in _TAKES_A_BLOCK or not re_bare_name.match(args):
      return args
    lower = args.lower()
    if any(lower in scope_vars[s_id] for s_id in scope_stack):
      return args
    return f"[it] {args}(it)"

  re_rows_head = re.compile(r'^rows\s*\(', re.IGNORECASE)
  re_lines_head = re.compile(r'^lines\s*\(', re.IGNORECASE)

  def source_argument(head, name, matched, line_idx):
    """The single argument of a source at the head of a chain."""
    inner, end_idx = extract_parens(head, matched.end() - 1)
    if inner is None or head[end_idx:].strip() or not inner.strip():
      raise SyntaxError(
        f"Line {line_idx + 1}: {name}() takes one argument.")
    return inner.strip()

  def masked_literal(text):
    """A string literal the transpiler generates, as a mask token.

    Written out with real quotes it would be rescanned as code and whatever
    is inside it reported as an undeclared name.
    """
    token = _mask_token(len(literal_parts))
    literal_parts.append(text)
    return token

  def workarea_prefix(alias_arg, curr_scope, before, indent):
    """How to reach a field of the source: 'SA1->' or '(cVar)->'.

    A literal alias is written out, because 'SA1->A1_COD' is what a Protheus
    developer reads. Anything else is bound once and used through the
    parenthesised form, which AdvPL accepts just as well.
    """
    literal = re_string_token.match(alias_arg.strip())
    if literal:
      name = unmask_literals(alias_arg.strip(), literal_parts).strip("\"'")
      if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        # The literal goes back as the masked token it arrived as. Rebuilt
        # with real quotes it would be rescanned as code, and the alias inside
        # it reported as an undeclared variable.
        return name, alias_arg.strip()
    holder = next_temp("fuse_alias", curr_scope)
    before.append(f"{indent}{holder} := {alias_arg.strip()}")
    return f"({holder})", holder

  def fuse_chain(prefix, parts, curr_scope, line_idx, for_value=False,
                 guarded=False):
    """Fuse the leading run of element-wise stages into one loop.

    Returns (lines, result_expr, remaining_segments, blocked_by).

    A chain is otherwise one call per stage, each walking its input and
    building a new array, so three stages over 500,000 rows is three loops and
    two throwaway arrays -- to produce, perhaps, ten values. Fused, the stages
    become the body of a single loop: no array between them, and a 'take'
    becomes an Exit, so the loop stops instead of running to the end and
    discarding the rest.

    The source is an array, or 'rows(alias)' for a work area -- which is
    already a lazy sequence with an ugly calling convention, DbGoTop to start,
    Eof to test, DbSkip to advance. Fusing over one walks the table without
    loading it, which is the difference between possible and impossible on a
    real SA1.

    Only the LEADING run is fused. A stage like 'sort' cannot produce anything
    until it has seen the last element, so it and everything after it carry on
    as ordinary stages, starting from the array the loop built.
    """
    nothing = ([], None, parts[1:], None)
    # No prefix means one of two things. A chain lifted out of an expression
    # wants its result -- that is what 'for_value' says. A chain written as a
    # statement is run for its effects and wants no result at all: it still
    # fuses, but with no accumulator, so a 'tap' pipeline becomes exactly the
    # loop someone would have written, instead of two loops and an array.
    for_effect = not prefix.strip() and not for_value
    stages = []
    for segment in parts[1:]:
      read = read_stage(segment.strip())
      if read is None:
        return nothing                # not a shape this understands
      stages.append(read)

    head = parts[0].strip()
    rows = re_rows_head.match(head)
    reading = re_lines_head.match(head)
    alias_arg = path_arg = seek_arg = range_ends = None
    # 'lo..hi' at the head of a chain. The same spelling 'in 1..100' uses, and
    # the only source that walks without a collection behind it.
    at = find_top_level(head, "..")
    if at > 0 and not rows and not reading:
      low, high = head[:at].strip(), head[at + 2:].strip()
      if low and high:
        range_ends = (low, high)
    if rows:
      inner, after_call = extract_parens(head, rows.end() - 1)
      if inner is None or head[after_call:].strip() or not inner.strip():
        raise SyntaxError(
          f"Line {line_idx + 1}: rows() takes an alias and, optionally, a key "
          f"to seek.")
      given = [x for x in split_top_level(inner) if x.strip()]
      if len(given) > 2:
        raise SyntaxError(
          f"Line {line_idx + 1}: rows() takes an alias and, optionally, a key "
          f"to seek -- {len(given)} arguments were given.")
      alias_arg = given[0].strip()
      seek_arg = given[1].strip() if len(given) == 2 else None
    elif reading:
      path_arg = source_argument(head, "lines", reading, line_idx)

    # 'fallback' folds everything the line generates into one code block, as
    # comma-separated expressions -- and a fused loop is not an expression.
    # An array chain simply goes unfused, back to the runtime calls it used
    # before fusion existed, which are expressions. A source has no unfused
    # form, so it cannot be guarded at all.
    if guarded and (alias_arg is not None or path_arg is not None):
      raise SyntaxError(
        f"Line {line_idx + 1}: 'fallback' cannot guard a walk over "
        f"{'rows' if alias_arg is not None else 'lines'}(). The guard needs "
        f"an expression and a walk is a loop. Assign the chain first, then "
        f"guard what uses it.")

    def inlinable(stage):
      name, args = stage
      if name not in _FUSE_STEPS:
        return False
      if name in ("take", "drop"):
        return bool(args.strip())
      if name == "distinctadjacent":
        if not args.strip():
          return True                 # compares the element against the last
        block = re_block_literal.match(args)
        return block is not None and len(block.group(1).split(",")) == 1
      if name == "pairwise":
        return not args.strip()
      if name == "scan":
        given = [x for x in split_top_level(args) if x.strip()]
        if len(given) != 2:
          return False
        block = re_block_literal.match(given[0].strip())
        return block is not None and len(block.group(1).split(",")) == 2
      block = re_block_literal.match(args)
      return block is not None and len(block.group(1).split(",")) == 1

    run = 0
    while run < len(stages) and inlinable(stages[run]):
      run += 1

    fold = separator = fold_block = fold_args = None
    fold_seed = None
    # A terminal does not have to be the LAST stage. 'chunkby' hands back an
    # array of groups, so 'expand |> chunkby |> map' should fuse up to the
    # chunkby and carry on from what it built -- which the remaining-stages
    # machinery already supports.
    if run < len(stages) and stages[run][0] in _FUSE_TERMINALS:
      terminal, terminal_args = stages[run]
      if terminal == "count":
        given = [x for x in split_top_level(terminal_args) if x.strip()]
        if not given:
          fold, fold_args, fold_seed = terminal, None, "0"
        elif len(given) == 1:
          block = re_block_literal.match(given[0].strip())
          if block is not None and len(block.group(1).split(",")) == 1:
            fold, fold_args, fold_seed = terminal, given[0].strip(), "0"
      elif terminal in ("maxby", "minby"):
        given = [x for x in split_top_level(terminal_args) if x.strip()]
        if len(given) == 1:
          block = re_block_literal.match(given[0].strip())
          if block is not None and len(block.group(1).split(",")) == 1:
            fold, fold_args, fold_seed = terminal, given[0].strip(), "Nil"
      elif terminal == "first":
        given = [x for x in split_top_level(terminal_args) if x.strip()]
        if len(given) == 1:
          block = re_block_literal.match(given[0].strip())
          if block is not None and len(block.group(1).split(",")) == 1:
            fold, fold_args, fold_seed = terminal, given[0].strip(), "Nil"
      elif terminal == "chunkby":
        given = [x for x in split_top_level(terminal_args) if x.strip()]
        if len(given) == 1:
          block = re_block_literal.match(given[0].strip())
          if block is not None and len(block.group(1).split(",")) == 1:
            fold, fold_args, fold_seed = terminal, given[0].strip(), "{}"
      elif terminal in _FUSE_PREDICATES:
        given = [x for x in split_top_level(terminal_args) if x.strip()]
        if len(given) == 1:
          block = re_block_literal.match(given[0].strip())
          if block is not None and len(block.group(1).split(",")) == 1:
            fold, fold_args = terminal, given[0].strip()
            fold_seed = _FUSE_PREDICATES[terminal]
      elif terminal in ("reduce", "fold"):
        given = [x for x in split_top_level(terminal_args) if x.strip()]
        # reduce takes a block and a seed, fold just the block and starts
        # from the first element.
        if len(given) == (2 if terminal == "reduce" else 1):
          block = re_block_literal.match(given[0].strip())
          if block is not None and len(block.group(1).split(",")) == 2:
            fold, fold_block = terminal, block
            fold_seed = given[1].strip() if terminal == "reduce" else "Nil"
      elif terminal == "join":
        # One argument at most: the separator. 'join' with none joins with
        # nothing, which is what the runtime version does too.
        given = [x for x in split_top_level(terminal_args) if x.strip()]
        if len(given) <= 1:
          fold = terminal
          separator = given[0].strip() if given else None
      elif not terminal_args:
        fold = terminal

    # Run for effects: every stage must be element-wise, since there is no
    # result for a terminal to build.
    if for_effect and (fold is not None or run != len(stages) or run < 1):
      return nothing

    taken = run + (1 if fold else 0)

    # A guard folds the line into a code block, as comma-separated
    # expressions, and a fused loop is not one. So the chain goes back to the
    # runtime calls -- correct, but a pass and an array more than it was. Said
    # out loud, because it is invisible in the source.
    if guarded:
      if taken >= 2 or (for_effect and run >= 1):
        print(f"warning: line {line_idx + 1}: 'fallback' turns off fusion for "
              f"this chain -- a guard needs an expression and a fused loop is "
              f"not one, so each stage builds an array again. Guard the part "
              f"that can fail instead, and leave the chain outside it.",
              file=sys.stderr)
      return nothing

    if taken < len(stages):
      name = stages[taken][0]
      written = parts[1:][taken].strip()
      as_written = re_pipe_segment.match(written)
      # 'sort' is a verb xtpl knows and cannot fuse; 'meuAuxiliar' is one it
      # has never heard of. Different reasons, so different messages.
      blocked_by = (as_written.group(1) if as_written else name,
                    name in runtime_verbs)
    else:
      blocked_by = None
    # A terminal ends the fused section by design, so what follows it is not
    # something that "cannot be fused" -- it simply carries on from the array
    # the terminal built. Reporting it would be blaming the wrong stage.
    if fold is not None:
      blocked_by = None

    # A chain walks a collection. A single value at the head produces
    # 'Len(1)' and '1[1]', which nothing else catches: AdvPL is dynamically
    # typed, so the compiler takes it and it fails at run time complaining
    # about something else.
    if not rows and not reading and range_ends is None and len(parts) > 1:
      bare = head.strip()
      scalar_why = None
      if is_literal_expr(bare) and not bare.startswith("{"):
        scalar_why = ""
      else:
        # A variable declared in this function may say what it holds: an
        # initialiser that is a scalar literal, or a type annotation. A
        # parameter says nothing, and guessing from a Hungarian prefix would
        # be wrong every time somebody names an array 'nRows'.
        kind = declared_types.get(bare, "").lower()
        if kind in _SCALAR_TYPES:
          scalar_why = f" -- it is declared 'as {kind}'"
        else:
          seeded = hoisted_inits.get(bare, "").strip()
          if (seeded and is_literal_expr(seeded)
              and not seeded.startswith("{")):
            scalar_why = f" -- it was declared as {seeded}"
      if scalar_why is not None:
        shown = unmask_literals(bare, literal_parts)
        raise SyntaxError(
          f"Line {line_idx + 1}: {shown} is a single value{scalar_why}, and "
          f"a chain walks a collection. Write {{{shown}}} for a one-element "
          f"array, or 'lo..hi' for a range.")

    if alias_arg is not None and taken < 1:
      raise SyntaxError(
        f"Line {line_idx + 1}: rows() is a source to walk, not a value. It has "
        f"to be followed by stages that can be fused into the walk.")

    # One stage on its own is a loop either way, so fusing an array chain
    # would only make the output longer. A source has no other lowering, and
    # a file with no stages at all is still meaningful -- every line of it.
    # A range has to fuse whatever else the chain does: there is no array
    # behind it, so '1..999' handed to a runtime verb is not an expression
    # AdvPL can evaluate. '1..999 |> asum' generated 'u_xtpl_asum(1..999)'.
    if (taken < 2 and alias_arg is None and path_arg is None
        and range_ends is None and not for_effect):
      return [], None, parts[1:], blocked_by

    indent = leading_indent(prefix)
    value = next_temp("fuse_v", curr_scope)
    result = next_temp("fuse_out", curr_scope)
    before, after, finish = [], [], []
    field = None

    if path_arg is not None:
      # FT_FUse opens the file and FT_FUse() with no argument closes it. This
      # is the idiom Protheus already uses for a text file, and it reads one
      # line at a time -- so a 'take' really does stop the read rather than
      # trimming something already loaded.
      # A path that is already a name is used as it is. The temp exists so an
      # expression is evaluated once, and a name is already evaluated.
      if re_bare_name.match(path_arg.strip()):
        source = path_arg.strip()
      else:
        source = next_temp("fuse_src", curr_scope)
        before.append(f"{indent}{source} := {path_arg}")
      opened = next_temp("fuse_ok", curr_scope)
      # The file is tested ONCE, not in the loop condition. On a file that
      # never opened FT_FEof() stays .F. and the walk never ends -- a hang
      # rather than an error -- but asking File() per line is a filesystem
      # call per line, which on a large file costs more than the read.
      # Both the open and the close are guarded. A failed FT_FUse is NOT
      # inert -- probed, and it displaces whatever file was current, after
      # which the argument-less FT_FUse() closes somebody else's. A caller
      # with a file open and a lines() over a path that does not exist would
      # lose their handle, and the damage would surface elsewhere.
      before.extend([f"{indent}{opened} := File({source})",
                     f"{indent}If {opened}",
                     f"{indent}  FT_FUse({source})",
                     f"{indent}  FT_FGoTop()",
                     f"{indent}EndIf"])
      opener = f"{indent}While {opened} .And. !FT_FEof()"
      closer = f"{indent}EndDo"
      first = [f"{indent}  {value} := FT_FReadLn()"]
      step = [f"{indent}  FT_FSkip()"]
      after.extend([f"{indent}If {opened}",
                    f"{indent}  FT_FUse()",
                    f"{indent}EndIf"])
      has_value = True
    elif range_ends is not None:
      # A range is the one source that needs no collection at all: the loop
      # counter IS the element, so there is nothing to index and nothing to
      # build. '1..999 |> filter(...) |> asum' walks a thousand numbers and
      # allocates none of them.
      low, high = range_ends
      for name, part in (("fuse_lo", low), ("fuse_hi", high)):
        # A literal goes in the header, and so does a bare name: the temp is
        # there to evaluate an expression once, and a name is evaluated.
        if not is_literal_expr(part) and not re_bare_name.match(part.strip()):
          bound = next_temp(name, curr_scope)
          before.append(f"{indent}{bound} := {part}")
          if name == "fuse_lo":
            low = bound
          else:
            high = bound
      # The counter and the element are separate. Making the counter itself
      # the element saved one assignment and broke the loop: a 'map' writes
      # to the element, and writing to a For counter changes what it iterates.
      index = next_temp("fuse_i", curr_scope)
      opener = f"{indent}For {index} := {low} To {high}"
      closer = f"{indent}Next"
      first = [f"{indent}  {value} := {index}"]
      step = []
      has_value = True
    elif alias_arg is None:
      if re_bare_name.match(head.strip()):
        source = head.strip()
      else:
        source = next_temp("fuse_src", curr_scope)
        before.append(f"{indent}{source} := {head}")
      index = next_temp("fuse_i", curr_scope)
      opener = f"{indent}For {index} := 1 To Len({source})"
      closer = f"{indent}Next"
      first = [f"{indent}  {value} := {source}[{index}]"]
      step = []
      has_value = True
    else:
      field, select = workarea_prefix(alias_arg, curr_scope, before, indent)
      area = next_temp("fuse_area", curr_scope)
      record = next_temp("fuse_rec", curr_scope)
      # The area and the record pointer are put back afterwards. Leaving an
      # alias somewhere else is a classic Protheus bug whose damage shows up
      # in code that had nothing to do with this line.
      before.extend([f"{indent}{area} := Alias()",
                     f"{indent}DbSelectArea({select})",
                     f"{indent}{record} := {field}->(RecNo())"])
      if seek_arg is None:
        before.append(f"{indent}{field}->(DbGoTop())")
      else:
        # Positioned by the index rather than read up to. A seek that finds
        # nothing lands on Eof, so the walk produces nothing -- which is the
        # right answer and needs no test of its own.
        #
        # The index order is whatever is set: 'using alias SC6 order 1 do'
        # around the chain is how to be sure which one.
        before.append(f"{indent}{field}->(DbSeek({seek_arg}))")
      opener = f"{indent}While !{field}->(Eof())"
      closer = f"{indent}EndDo"
      first = []
      step = [f"{indent}  {field}->(DbSkip())"]
      after.extend([f"{indent}{field}->(DbGoto({record}))",
                    f"{indent}If !Empty({area})",
                    f"{indent}  DbSelectArea({area})",
                    f"{indent}EndIf"])
      has_value = False

    body, closers = list(first), []
    prologue = len(first)             # the lines that fetch the element

    def push(text):
      # 'closers' is what each open block ends with, innermost last -- not a
      # count. A stage that opens a For rather than an If closes differently,
      # and the depth alone could not say which.
      body.append(f"{indent}  {'  ' * len(closers)}{text}")

    def writes_to(name, text):
      """Does this block body assign to its own parameter?"""
      return bool(
        re.search(rf'\b{re.escape(name)}\s*(?::=|\+=|-=|\*=|/=)', text)
        or re.search(rf'@\s*{re.escape(name)}\b', text))

    def read_body(args):
      """The block's parameter and body, with field access resolved.

      Over a work area the element is the current record, not a value, so
      'r:A1_COD' is compiled to a field reference. Any other use of the name
      has nothing to refer to and is refused rather than emitted.
      """
      block = re_block_literal.match(args)
      param, expr = block.group(1).strip(), block.group(2).strip()
      # Only while the element is still the record. Once a map has run, the
      # element is whatever it produced -- an ordinary value that binds to the
      # name in the ordinary way -- so the field rewrite must not apply to
      # stages after it.
      if field is None or has_value:
        # The parameter is a name for the value the loop is already holding,
        # so put the value in directly and skip the binding. That removes a
        # copy per stage per element -- and where the body never mentions the
        # name at all, as in 'tap([l] nConta += 1)', it removed a binding that
        # was assigned and never read.
        #
        # Not when the body WRITES to the parameter: the value temp carries
        # the element between stages, and a stage that rebinds its own
        # parameter must not disturb it.
        if not writes_to(param, expr):
          return None, re.sub(rf'\b{re.escape(param)}\b', value, expr)
        return param, expr
      expr = re.sub(rf'\b{re.escape(param)}\s*:\s*([A-Za-z_][A-Za-z0-9_]*)',
                    rf'{field}->\1', expr)
      if re.search(rf'\b{re.escape(param)}\b', expr):
        raise SyntaxError(
          f"Line {line_idx + 1}: over rows() the element is the current "
          f"record, not a value, so it can only be used to name a field.")
      return None, expr

    for name, args in stages[:run]:
      if name in ("map", "filter", "reject"):
        param, expr = read_body(args)
        if param is not None:
          push(f"{param} := {value}")
        if name == "map":
          push(f"{value} := {expr}")
          has_value = True
        else:
          push(f"If {expr}" if name == "filter" else f"If !({expr})")
          closers.append("EndIf")
        continue

      if name == "tap":
        # The value is untouched; the block runs for its effect alone.
        param, effect = read_body(args)
        if param is not None:
          push(f"{param} := {value}")
        push(effect)
        continue

      if name == "expand":
        param, inner_expr = read_body(args)
        if param is not None:
          push(f"{param} := {value}")
        bag = next_temp("fuse_bag", curr_scope)
        at = next_temp("fuse_j", curr_scope)
        push(f"{bag} := {inner_expr}")
        # A loop inside the loop, so the rest of the chain runs once per
        # inner element. This closes with Next, not EndIf -- which is why
        # what closes a block is tracked rather than counted.
        push(f"For {at} := 1 To Len({bag})")
        closers.append("Next")
        push(f"{value} := {bag}[{at}]")
        has_value = True
        continue

      if name == "scan":
        if not has_value:
          raise SyntaxError(
            f"Line {line_idx + 1}: scan over rows() needs a value to carry -- "
            f"map the record to one first.")
        given = [x for x in split_top_level(args) if x.strip()]
        block = re_block_literal.match(given[0].strip())
        carried, element = [x.strip() for x in block.group(1).split(",")]
        step_expr = block.group(2).strip()
        running = next_temp("fuse_acc", curr_scope)
        before.append(f"{indent}{running} := {given[1].strip()}")
        if writes_to(carried, step_expr):
          push(f"{carried} := {running}")
        else:
          step_expr = re.sub(rf'\b{re.escape(carried)}\b', running, step_expr)
        if writes_to(element, step_expr):
          push(f"{element} := {value}")
        else:
          step_expr = re.sub(rf'\b{re.escape(element)}\b', value, step_expr)
        push(f"{running} := {step_expr}")
        # The running value is what continues down the chain.
        push(f"{value} := {running}")
        continue

      if name == "pairwise":
        if not has_value:
          raise SyntaxError(
            f"Line {line_idx + 1}: pairwise over rows() needs values to pair "
            f"-- map the record to one first.")
        prior = next_temp("fuse_prev", curr_scope)
        had = next_temp("fuse_had", curr_scope)
        before.extend([f"{indent}{prior} := Nil", f"{indent}{had} := .F."])
        older = next_temp("fuse_older", curr_scope)
        ready = next_temp("fuse_ready", curr_scope)
        # Both are read before they are overwritten, because the pair has to
        # be built from the PREVIOUS element while 'prev' is already being
        # set up for the next pass. There is no room after the block below.
        push(f"{older} := {prior}")
        push(f"{ready} := {had}")
        push(f"{prior} := {value}")
        push(f"{had} := .T.")
        push(f"If {ready}")
        closers.append("EndIf")
        push(f"{value} := " + "{" + f"{older}, {value}" + "}")
        continue

      if name == "distinctadjacent":
        if not args.strip() and not has_value:
          raise SyntaxError(
            f"Line {line_idx + 1}: distinctAdjacent over rows() needs a key "
            f"-- the record is not a value to compare against the previous "
            f"one. Give it one, as distinctAdjacent([r] r:C6_NUM), or map "
            f"first.")
        opened = next_temp("fuse_open", curr_scope)
        last = next_temp("fuse_last", curr_scope)
        probe = next_temp("fuse_probe", curr_scope)
        before.extend([f"{indent}{opened} := .F.", f"{indent}{last} := Nil",
                       f"{indent}{probe} := Nil"])
        if args.strip():
          param, key_expr = read_body(args)
          if param is not None:
            push(f"{param} := {value}")
        else:
          key_expr = value
        push(f"{probe} := {key_expr}")
        push(f"If !({opened} .And. ({probe} == {last}))")
        closers.append("EndIf")
        push(f"{opened} := .T.")
        push(f"{last} := {probe}")
        continue

      if name in ("takewhile", "dropwhile"):
        param, test = read_body(args)
        if param is not None:
          push(f"{param} := {value}")
        if name == "takewhile":
          # The first failure ends the whole walk, which is what separates
          # this from filter. Over an ordered source that is the point: the
          # rest is known not to match, so reading it learns nothing.
          push(f"If !({test})")
          push(f"  Exit")
          push(f"EndIf")
        else:
          # A flag, because once the leading run is over an element that
          # would have matched must still pass.
          flag = next_temp("fuse_drop", curr_scope)
          before.append(f"{indent}{flag} := .T.")
          push(f"If !({flag} .And. ({test}))")
          closers.append("EndIf")
          push(f"{flag} := .F.")
        continue

      limit = args.strip()
      if not is_literal_expr(limit):
        bound = next_temp("fuse_lim", curr_scope)
        before.append(f"{indent}{bound} := {limit}")
        limit = bound
      counter = next_temp("fuse_n", curr_scope)
      before.append(f"{indent}{counter} := 0")
      if name == "take":
        # Tested on arrival, so at most one element past the limit is read
        # before the loop stops -- against walking all the rest.
        push(f"If {counter} >= {limit}")
        push(f"  Exit")
        push(f"EndIf")
        push(f"{counter} := {counter} + 1")
      else:
        push(f"If {counter} < {limit}")
        push(f"  {counter} := {counter} + 1")
        push(f"Else")
        closers.append("EndIf")

    # A predicate reads the element, not a value made from it, so a chain
    # over rows() needs no map before one.
    if for_effect:
      pass                            # nothing is collected, so nothing is needed
    elif not has_value and fold not in _FUSE_ELEMENTWISE_OK:
      raise SyntaxError(
        f"Line {line_idx + 1}: a chain over rows() has to map the record to a "
        f"value before anything can be collected from it.")

    if for_effect:
      pass                            # the steps above were the whole point
    elif fold in ("maxby", "minby"):
      best = next_temp("fuse_best", curr_scope)
      opened = next_temp("fuse_open", curr_scope)
      probe = next_temp("fuse_probe", curr_scope)
      before.extend([f"{indent}{best} := Nil", f"{indent}{opened} := .F.",
                     f"{indent}{probe} := Nil"])
      param, key_expr = read_body(fold_args)
      if param is not None:
        push(f"{param} := {value}")
      push(f"{probe} := {key_expr}")
      # A flag rather than testing the accumulator against Nil, since an
      # element may legitimately be Nil.
      compare = ">" if fold == "maxby" else "<"
      push(f"If !{opened} .Or. {probe} {compare} {best}")
      push(f"  {opened} := .T.")
      push(f"  {best} := {probe}")
      push(f"  {result} := {value}")
      push(f"EndIf")
    elif fold == "count":
      if fold_args is None:
        push(f"{result} := {result} + 1")
      else:
        param, test = read_body(fold_args)
        if param is not None:
          push(f"{param} := {value}")
        push(f"If {test}")
        push(f"  {result} := {result} + 1")
        push(f"EndIf")
    elif fold == "first":
      param, test = read_body(fold_args)
      if param is not None:
        push(f"{param} := {value}")
      push(f"If {test}")
      push(f"  {result} := {value}")
      push(f"  Exit")
      push(f"EndIf")
    elif fold == "chunkby":
      chunk = next_temp("fuse_chunk", curr_scope)
      last = next_temp("fuse_key", curr_scope)
      opened = next_temp("fuse_open", curr_scope)
      before.extend([f"{indent}{chunk} := {{}}", f"{indent}{last} := Nil",
                     f"{indent}{opened} := .F."])
      param, key_expr = read_body(fold_args)
      if param is not None:
        push(f"{param} := {value}")
      seen = next_temp("fuse_seen", curr_scope)
      before.append(f"{indent}{seen} := Nil")
      push(f"{seen} := {key_expr}")
      # A flag rather than comparing against Nil: Nil is a legitimate key,
      # and the first element must open the first group either way.
      push(f"If !{opened}")
      push(f"  {opened} := .T.")
      push(f"  {last} := {seen}")
      push(f"ElseIf !({seen} == {last})")
      push(f"  AAdd({result}, {chunk})")
      push(f"  {chunk} := {{}}")
      push(f"  {last} := {seen}")
      push(f"EndIf")
      push(f"AAdd({chunk}, {value})")
      # The last group is still open when the loop ends.
      finish.extend([f"{indent}If {opened}",
                     f"{indent}  AAdd({result}, {chunk})",
                     f"{indent}EndIf"])
    elif fold in _FUSE_PREDICATES:
      param, test = read_body(fold_args)
      if param is not None:
        push(f"{param} := {value}")
      answered = ".T." if fold == "anyof" else ".F."
      push(f"If {test}" if fold != "allof" else f"If !({test})")
      push(f"  {result} := {answered}")
      push(f"  Exit")
      push(f"EndIf")
    elif fold in ("reduce", "fold"):
      carried, element = [p.strip() for p in fold_block.group(1).split(",")]
      step_expr = fold_block.group(2).strip()
      # Same as the single-parameter stages: both names stand for something
      # the loop already holds, so they go in directly unless the body
      # writes to one of them.
      keeps_carried = writes_to(carried, step_expr)
      keeps_element = writes_to(element, step_expr)
      if not keeps_carried:
        step_expr = re.sub(rf'\b{re.escape(carried)}\b', result, step_expr)
      if not keeps_element:
        step_expr = re.sub(rf'\b{re.escape(element)}\b', value, step_expr)
      if fold == "fold":
        # Seedless: the first element IS the starting value, so there is
        # nothing to combine it with. Nil until one arrives, as amax does.
        push(f"If {result} == Nil")
        push(f"  {result} := {value}")
        push(f"Else")
        if keeps_carried:
          push(f"  {carried} := {result}")
        if keeps_element:
          push(f"  {element} := {value}")
        push(f"  {result} := {step_expr}")
        push(f"EndIf")
      else:
        if keeps_carried:
          push(f"{carried} := {result}")
        if keeps_element:
          push(f"{element} := {value}")
        push(f"{result} := {step_expr}")
    elif fold == "join":
      # A flag, not a test on the accumulator: an empty first element would
      # leave the string empty and lose its separator.
      if separator is not None:
        if not is_literal_expr(separator):
          bound = next_temp("fuse_sep", curr_scope)
          before.append(f"{indent}{bound} := {separator}")
          separator = bound
        first = next_temp("fuse_first", curr_scope)
        before.append(f"{indent}{first} := .T.")
        push(f"If {first}")
        push(f"  {first} := .F.")
        push(f"Else")
        push(f"  {result} := {result} + {separator}")
        push(f"EndIf")
      push(f"{result} := {result} + cValToChar({value})")
    elif fold is None:
      push(f"AAdd({result}, {value})")
    elif fold == "asum":
      push(f"{result} := {result} + {value}")
    elif fold == "aprod":
      push(f"{result} := {result} * {value}")
    else:
      # Max and Min start from the first element: there is no neutral value to
      # seed with, so the accumulator stays Nil until one arrives.
      pick = "Max" if fold == "amax" else "Min"
      push(f"If {result} == Nil")
      push(f"  {result} := {value}")
      push(f"Else")
      push(f"  {result} := {pick}({result}, {value})")
      push(f"EndIf")

    while closers:
      ending = closers.pop()
      push(ending)

    if not for_effect:
      if fold_seed is not None:
        seed = fold_seed              # reduce's own, evaluated once
      elif fold:
        seed = _FUSE_FOLDS[fold]
      else:
        seed = "{}"
      before.append(f"{indent}{result} := {seed}")
    # A source whose element nothing reads: 'count' with no test never looks
    # at the line, but the read still has to happen for FT_FSkip to advance.
    # The value is fetched and dropped, so the assignment goes.
    if prologue:
      rest = body[prologue:] + step + finish + after
      if not any(re.search(rf'\b{re.escape(value)}\b', l) for l in rest):
        for at in range(prologue):
          body[at] = re.sub(rf'^(\s*){re.escape(value)}\s*:=\s*(\w+\()',
                            r'\1\2', body[at])

    # 'finish' runs after the loop but before a work area is put back.
    lines = before + [opener] + body + step + [closer] + finish + after
    return lines, (None if for_effect else result), parts[1:][taken:], blocked_by

  def wrap_fallback(prefix, statements, final_expr, fallback_val, curr_scope):
    """Hand the guarded work to the runtime.

    Both sides are code blocks: the fallback must not be evaluated unless the
    protected side actually fails. A chain's stages become comma-separated
    expressions inside the block, so every stage sits under the guard while
    the temps keep each stage evaluated once.
    """
    steps = [st.strip() for st in statements] + [final_expr]

    # A code block body is comma-separated EXPRESSIONS. Anything that
    # generates control flow cannot go inside one, and folding it in produces
    # AdvPL that does not compile -- which a golden file recorded from that
    # output will happily agree with forever. Checked here so a future pass
    # that starts emitting loops under a guard fails loudly instead.
    for step in steps:
      keyword = re.match(
        r'\s*(While|EndDo|For|Next|If|ElseIf|Else|EndIf|Do\s+Case|Case|'
        r'Otherwise|EndCase|Exit|Loop|Return)\b', step, re.IGNORECASE)
      if keyword:
        raise SyntaxError(
          f"Line {current_line_no}: 'fallback' can only guard expressions, "
          f"and this line generates a '{keyword.group(1)}'. Assign it first, "
          f"then guard what uses the result.")

    return (f"{prefix}u_xtpl_safe_pipe({{|| {', '.join(steps)}}}, "
            f"{{|| {fallback_val}}})")

  def transpile_optional_chaining(line):
    def replace_optional(match):
      # Every link but the last has to be tested: the last one is only read.
      links = [p.strip() for p in match.group(2).split("?.") if p.strip()]
      reached = match.group(1)
      guards = [f"{reached} != Nil"]
      for link in links[:-1]:
        reached = f"{reached}:{link}"
        guards.append(f"{reached} != Nil")
      return f"If({' .And. '.join(guards)}, {reached}:{links[-1]}, Nil)"

    return re_optional_chain.sub(replace_optional, line)

  def elvis_operand_span(text, pos):
    """Bounds of the ?: expression at pos, stopping at the enclosing , ( [ {."""
    depth = 0
    start = 0
    i = pos - 1
    while i >= 0:
      char = text[i]
      if char in ")]}":
        depth += 1
      elif char in "([{":
        if depth == 0:
          start = i + 1
          break
        depth -= 1
      elif char == "," and depth == 0:
        start = i + 1
        break
      i -= 1

    depth = 0
    end = len(text)
    j = pos + 2
    while j < len(text):
      char = text[j]
      if char in "([{":
        depth += 1
      elif char in ")]}":
        if depth == 0:
          end = j
          break
        depth -= 1
      elif char == "," and depth == 0:
        end = j
        break
      j += 1
    return start, end

  def elvis_chain(temp, parts, indent):
    """Nested tests so each fallback runs only after the previous gave Nil."""
    out = [f"{indent}{temp} := {parts[0]}"]
    for level, part in enumerate(parts[1:]):
      pad = indent + "  " * level
      out.append(f"{pad}If {temp} == Nil")
      out.append(f"{pad}  {temp} := {part}")
    for level in range(len(parts) - 2, -1, -1):
      out.append(f"{indent}{'  ' * level}EndIf")
    return out

  def transpile_elvis(line, curr_scope):
    prefix, expr = split_prefix(line)
    if "?:" not in expr:
      return line
    indent = leading_indent(prefix)

    if find_top_level(expr, "?:") >= 0:
      parts = split_top_level(expr, "?:")
      temp = next_temp("elvis_tmp", curr_scope)
      # Bind first so each operand is evaluated exactly once.
      if len(parts) == 2:
        return f"{indent}{temp} := {parts[0]}\n{prefix}If({temp} != Nil, {temp}, {parts[1]})"
      return "\n".join(elvis_chain(temp, parts, indent) + [f"{prefix}{temp}"])

    # Nested inside an expression: lift the whole chain into statements ahead of
    # the line, then put the temp where the chain was. Lifting the chain rather
    # than just its head is what keeps the later operands from being evaluated.
    statements = []
    while True:
      pos = expr.find("?:")
      if pos < 0:
        break
      span_start, span_end = elvis_operand_span(expr, pos)
      parts = split_top_level(expr[span_start:span_end], "?:")
      temp = next_temp("elvis_tmp", curr_scope)
      statements.extend(elvis_chain(temp, parts, indent))
      expr = expr[:span_start] + temp + expr[span_end:]
    return "\n".join(statements + [f"{prefix}{expr}"])

  def transpile_safe_pipelines(line, curr_scope):
    prefix, expr = split_prefix(line)
    idx = find_top_level(expr, " fallback ")
    if idx < 0:
      return line
    return wrap_fallback(prefix, [], expr[:idx].strip(),
                         expr[idx + len(" fallback "):].strip(), curr_scope)

  def transpile_xtpl_print(line):
    match = re_xtpl_print.search(line)
    if not match:
      return line
    args, end_idx = extract_parens(line, match.end() - 1)
    if args is None:
      return line
    # Literals are already strings; anything else needs converting first.
    pieces = [
      part if re_string_token.match(part) else f"cValToChar({part})"
      for part in split_top_level(args) if part
    ]
    joined = " + ".join(pieces) if pieces else '""'
    return f"{line[:match.start()]}conout({joined}){line[end_idx:]}"

  def interpolate(text):
    """'${expr}' inside a string literal becomes a concatenation.

    Literals are masked before any pass runs, so this reaches into the mask
    table, rebuilds the literal chunks as fresh tokens, and leaves the
    expressions as ordinary code between them. Everything downstream then sees
    an ordinary concatenation -- which is what lets '${h{"k"}}' work, since
    the hash pass meets it as a normal subscript.
    """
    result, last = [], 0
    for found in _re_mask_token.finditer(text):
      index = ord(found.group(1)) - _MASK_BASE
      content = literal_parts[index]
      quote = content[:1]
      if quote not in ('"', "'") or "${" not in content:
        continue                      # a comment, or a string with nothing in it
      body = content[1:-1] if content[-1:] == quote and len(content) > 1 else content[1:]

      pieces, at = [], 0
      while at < len(body):
        start = body.find("${", at)
        if start < 0:
          pieces.append(("text", body[at:]))
          break
        pieces.append(("text", body[at:start]))
        depth, scan = 1, start + 2
        while scan < len(body) and depth:
          if body[scan] == "{":
            depth += 1
          elif body[scan] == "}":
            depth -= 1
          scan += 1
        if depth:
          raise SyntaxError(
            f"Line {current_line_no}: '${{' in a string is never closed. An "
            f"interpolated expression cannot use the same quote as the string "
            f"around it -- write '...' inside \"...\".")
        pieces.append(("code", body[start + 2:scan - 1]))
        at = scan

      built = []
      for kind, piece in pieces:
        if kind == "text":
          if piece:
            token, _ = mask_literals(f"{quote}{piece}{quote}", literal_parts)
            built.append(token)
          continue
        if not piece.strip():
          raise SyntaxError(
            f"Line {current_line_no}: '${{}}' has nothing in it.")
        # Masked on the way out. The literal this came from was one token, so
        # its contents are raw text -- and an expression carrying a string of
        # its own, as in "${h{'moeda'}}", would otherwise put bare quotes back
        # into the line for the identifier scan to trip over.
        inner, _ = mask_literals(piece.strip(), literal_parts)
        built.append(f"cValToChar({inner})")
      if not built:
        token, _ = mask_literals(f"{quote}{quote}", literal_parts)
        built.append(token)

      # Parenthesised when there is more than one part, so the concatenation
      # binds before whatever the string sat next to.
      joined = built[0] if len(built) == 1 else "(" + " + ".join(built) + ")"
      result.append(text[last:found.start()])
      result.append(joined)
      last = found.end()
    result.append(text[last:])
    return "".join(result)

  def rewrite_statement(line, curr_scope, line_idx, for_value=False):
    """Every expression-level rewrite, in order, for one statement.

    Returns what the statement becomes, which may be several physical lines:
    a hash read lifts a Get above the line using it, a chain lands each stage
    in its own temp.

    This was inline in the main loop, which meant any branch that 'continue'd
    before reaching it skipped the lot -- silently. That is how a 'defer' body
    came to be spliced into the output untranslated. Having it callable is
    what lets 'defer' run its body through the same passes as everything else.
    """
    # Everything below wraps the TAIL of the line in generated syntax -- a
    # code block for 'fallback', an If() for elvis. A comment left in place
    # ends up inside that syntax and comments out the closing bracket, so
    # 'x := f() fallback 0  // note' produced '{|| 0  // note})' and the line
    # no longer balanced. Peel once, put it back once, rather than teaching
    # each pass about comments.
    line, line_note = peel_comment(line, literal_parts)

    # Before everything else, because it turns one literal into an expression
    # and the passes below should see the expression, not the string.
    line = interpolate(line)

    # A guard inside brackets is lifted into its own statement first, so the
    # peel below only ever meets one at the top of the line.
    guarded_lift = []
    while True:
      spot = guard_slice(expr_nodes(line))
      if spot is None:
        break
      ahead, inner, behind = spot
      holder = next_temp("guard_tmp", curr_scope)
      guarded_lift.extend(rewrite_statement(
        f"{leading_indent(line)}{holder} := {inner}",
        curr_scope, line_idx).split("\n"))
      line = ahead + holder + behind

    # 'fallback' is peeled before anything else rewrites the line, so every
    # statement the line goes on to generate ends up inside the guard.
    #
    # It has to be genuinely first. It used to sit after the hash pass, which
    # can turn one line into three -- and split_prefix, having no MULTILINE,
    # then failed and handed back the whole block as the expression. The
    # prefix came out empty, so 'nA := hCfg{"k"} fallback 0' put the
    # assignment INSIDE the guard: on failure nA kept its old value and the
    # fallback went nowhere.
    fb_prefix, fb_expr = split_prefix(line)
    fallback_val = None
    fb_at = find_top_level(fb_expr, " fallback ")
    if fb_at >= 0:
      fallback_val = fb_expr[fb_at + len(" fallback "):].strip()
      line = fb_prefix + fb_expr[:fb_at].strip()

    while True:
      hit = divisible_span(expr_nodes(line))
      if hit is None:
        break
      before, dividend, divisor, after = hit
      line = f"{before}({dividend} % {divisor}) == 0{after}"
    line = expand_bare_blocks(line, curr_scope)
    line = transpile_lambdas(line, curr_scope)
    line = transpile_hash(line, curr_scope)

    # Folds run first: a fold over a chain lifts the chain into its own
    # statement, where the feed pass can then see it at statement level.
    line = "\n".join(
      transpile_feed_chains(sub_line, curr_scope, line_idx,
                            fallback_val is not None, for_value)
      for sub_line in line.split("\n"))
    # The four array functions live in the runtime under prefixed names.
    line = re_verb_call.sub(lambda m: f"u_xtpl_{m.group(1).lower()}(", line)

    if fallback_val is not None:
      produced = line.split("\n")
      final = produced[-1]
      final = final[len(fb_prefix):] if final.startswith(fb_prefix) else final.strip()
      line = wrap_fallback(fb_prefix, produced[:-1], final, fallback_val, curr_scope)

    rewritten = []
    for sub_line in line.split("\n"):
      sub_line = transpile_membership(sub_line, curr_scope)
      sub_line = transpile_optional_chaining(sub_line)
      sub_line = transpile_elvis(sub_line, curr_scope)
      sub_line = "\n".join(transpile_xtpl_print(s) for s in sub_line.split("\n"))
      rewritten.append(sub_line)
    line = "\n".join(rewritten)

    if line_note:
      # Back on the last physical line, which is the one the source comment
      # was attached to. The postfix pass sees it again, as before.
      tail = line.split("\n")
      tail[-1] = f"{tail[-1]}  {line_note}"
      line = "\n".join(tail)
    if guarded_lift:
      line = "\n".join(guarded_lift + [line])
    return line

  def parse_postfix(text):
    """The trailing 'if'/'while' modifier on a line, or None.

    Read off the SOURCE line, before any pass rewrites it. It used to be read
    off the last physical line afterwards, by which point the chain pass had
    already eaten it: 'nB := aNums |> asum if lFlag' left the last stage as
    'asum if lFlag', and the bare-stage branch takes only the name and drops
    the rest, so the condition vanished without a word.
    """
    stripped = text.strip()
    grammar = postfix_grammar()
    if grammar is not None:
      # The grammar tells a postfix modifier from a block opener by structure,
      # so no blacklist of line prefixes is needed.
      parsed = grammar.parse(stripped)
      return parsed.made if parsed else None

    hit = re_postfix_return.match(stripped)
    if hit:
      return {"kind": "return", "body": hit.group("val").strip(),
              "op": "if", "cond": hit.group("cond").strip()}
    hit = re_postfix_exec.match(stripped)
    if hit:
      return {"kind": "exec", "body": hit.group("body").strip(),
              "op": "if", "cond": hit.group("cond").strip()}
    hit = re_postfix_general.match(stripped)
    if hit and not stripped.upper().startswith(
        ("IF", "WHILE", "FOR", "ELSE", "END", "NEXT")):
      return {"kind": "plain", "body": hit.group("body").strip(),
              "op": hit.group("kw").lower(), "cond": hit.group("cond").strip()}
    return None

  def rewrite_value(value, curr_scope, line_idx, indent=""):
    """An expression in a header or an initialiser: (lead_lines, final_expr).

    Headers and declarations are handled by branches that 'continue' before
    the main loop reaches rewrite_statement, so their expressions used to go
    straight to resolve_identifier with nothing rewritten. A '|>' chain in one
    was reported as an undeclared function name, '?.' as an undeclared member,
    'fallback' as an undeclared variable -- and 'h{key}', '?:', 'in' and '%%'
    were emitted with their own syntax intact, which only failed at the AdvPL
    compiler. Running the expression through the same passes as a statement
    fixes all seven at once.

    'lead_lines' are the statements the expression had to lift out of itself
    -- the Get above a hash read, a temp per chain stage. The caller emits
    those first and then uses final_expr wherever it was going to put the
    value.
    """
    # for_value: an initialiser has no assignment in front of it, and without
    # this the chain reads that as being run for its effects -- it drops the
    # accumulator and the caller takes the walk's closing line as the value.
    # 'local a := lines(f) |> map(g)' produced 'a := FT_FUse()'.
    produced = rewrite_statement(f"{indent}{value}", curr_scope, line_idx,
                                 for_value=True).split("\n")
    resolve = lambda text: re.sub(
      r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', resolve_identifier, text)
    return [resolve(part) for part in produced[:-1]], resolve(produced[-1].strip())

  for idx, raw_line in enumerate(lines):
    if re_func.search(raw_line):
      # Protheus refuses a bare 'Function' outright:
      #   Regular functions are not allowed in code.
      #   Use USER FUNCTION or STATIC FUNCTION.
      # Caught here rather than at compile time, since it can never be right.
      bare = re.match(r'^\s*Function\b', raw_line, re.IGNORECASE)
      if bare and not legacy:
        raise SyntaxError(
          f"Line {idx + 1}: a bare 'function' is not allowed by Protheus. "
          f"Write 'user function', 'static function' or 'main function'.")
      flush_function(idx)
      in_function = True
      scope_stack = [0]
      scope_counter = 0
      scope_vars = {0: set()}
      scope_var_mangling = {0: {}}
      scope_display = {0: 0}
      display_counter = 0
      prologue_open = {0: True}
      doc_comment = []
      capturing_doc = True
      in_raw_block = False
      object_stack.clear()
      using_stack.clear()
      file_loops.clear()
      open_aliases.clear()
      returns_value.clear()
      returns_bare.clear()
      reported_aliases.clear()
      stack_slot_next = {0: 0}
      block_locals = {}
      retired_locals = {}
      origin_names = {}
      slot_origins = {}
      const_names = {}
      const_notes = set()
      declared_at = {}
      reads = {}
      writes = {}
      pinned_decls = pinned_by_func.get(idx, set())
      native_hoisted.clear()
      private_hoisted.clear()
      generated_hoisted.clear()
      hoisted_inits.clear()
      defer_stack.clear()
      literal_parts = []
      function_buffer.append(raw_line)

      # Without this the signature is invisible: writes to a parameter were
      # rejected as undeclared, and '?=' on one could never work.
      signature, _ = mask_literals(raw_line)
      open_at = signature.find("(")
      if open_at >= 0:
        params, _ = extract_parens(signature, open_at)
        for param in split_top_level(params or ""):
          bare = re.sub(r'^\s*@\s*', "", param).strip()
          # A parameter carries a type as readily as a local does:
          # 'method process(jPayLoad as json)'.
          typed = re_value_typing.match(bare)
          if typed:
            bare = typed.group(1).strip()
          if re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', bare):
            register_parameter(bare, idx + 1)
      continue

    if not in_function:
      # 'external' is a promise to this transpiler and emits nothing.
      if not re_external.match(raw_line):
        out_lines.append(re.sub(r'(\.xtpl\b)', '.tlpp', raw_line, flags=re.IGNORECASE))
      continue

    if idx in block_comment_lines:
      # Entirely a block comment: emitted as written, and nothing scans it.
      # Its position is noted so the checks that ask what the last STATEMENT
      # was do not mistake a doc block for code.
      buffer_comment_at.add(len(function_buffer))
      function_buffer.append(raw_line)
      continue

    # A statement whose brackets do not close cannot be one. It is almost
    # always a line continued without the ';' that AdvPL needs, and the
    # preprocessor reports it much later and much less clearly:
    #   appre0(440) Error C2002 Statement unterminated at end of line
    if (in_function and not in_raw_block and not re_raw_any.match(raw_line)
        and raw_line.strip() and not re_directive.match(raw_line)):
      depth = 0
      for char in mask_literals(raw_line)[0]:
        if char in "([{":
          depth += 1
        elif char in ")]}":
          depth -= 1
      if depth > 0:
        raise SyntaxError(
          f"Line {idx + 1}: this line's brackets do not close. If it carries "
          f"on to the next one, end it with ';'.")
      if depth < 0:
        raise SyntaxError(
          f"Line {idx + 1}: this line closes a bracket it did not open.")

    current_line_no = idx + 1
    out_of_prologue = False
    temp_counters.clear()
    line, literal_parts = mask_literals(raw_line, literal_parts)

    stripped = line.strip()
    stripped_upper = stripped.upper()

    is_scope_start = (
      stripped_upper.startswith(("IF ", "IF\t", "FOR ", "WHILE ", "WITH OBJECT ",
                                "USING ALIAS ")) or
      stripped_upper == "IF" or
      stripped_upper.startswith("DO CASE")
    )
    # Classify against the scope the line sits IN, before any block it opens.
    outer_scope = scope_stack[-1]
    declares_here = bool(re_local_decl.match(line) or re_private_decl.match(line))
    is_comment_only = (
      not stripped or
      bool(re.fullmatch(r'\x00[\ue000-\uf8ff]\x00', stripped)))

    # Anything matching to the end of a line has to look past a trailing
    # comment, which masking turns into a token sitting after it. This is the
    # fourth construct to need it -- the loop headers, 'fallback' and '?:'
    # were the others -- so it is peeled once here and put back by whichever
    # branch handles the line.
    anchored, anchored_note = peel_comment(line, literal_parts)
    anchored_note = f"  {anchored_note}" if anchored_note else ""

    if in_raw_block:
      if re_raw_end.match(line):
        in_raw_block = False
        continue
      emit_raw(line)
      continue

    if re_raw_start.match(anchored):
      in_raw_block = True
      prologue_open[scope_stack[-1]] = False
      continue

    raw_match = re_raw_line.match(line)
    if raw_match:
      emit_raw(raw_match.group(1) + raw_match.group(2))
      prologue_open[scope_stack[-1]] = False
      continue

    if capturing_doc:
      if is_comment_only:
        if stripped:
          doc_comment.append(unmask_literals(line, literal_parts))
        continue
      capturing_doc = False

    if declares_here and not prologue_open.get(outer_scope, True):
      name = re.search(r'\bLOCAL\s+([a-zA-Z0-9_]+)', line, re.IGNORECASE)
      found = name.group(1) if name else '?'
      if not legacy:
        raise SyntaxError(
          f"Line {idx + 1}: declaration of '{found}' must come "
          f"before the first statement of its function or block.")
      # Not a compatibility relaxation: AdvPL requires a prologue too, so no
      # existing file has a declaration outside one -- it would not have
      # compiled. This is a convenience, and it is reported as one.
      legacy_prologue.append((idx + 1, found))
      out_of_prologue = True
      print(f"warning: line {idx + 1}: declaration of '{found}' is not in a "
            f"prologue", file=sys.stderr)

    if is_scope_start:
      # open_new_scope already pushes; pushing again here leaked every scope.
      open_new_scope()
      # The header itself is a statement in the scope that encloses it.
      if len(scope_stack) > 1:
        prologue_open[scope_stack[-2]] = False
    elif not is_comment_only and not declares_here:
      prologue_open[outer_scope] = False

    curr_scope = scope_stack[-1]
    parent_scope = scope_stack[-2] if len(scope_stack) > 1 else 0

    defer_match = re_defer.search(line)
    if defer_match:
      # Keep it masked: a deferred body is spliced into a return line later,
      # and unmasked quotes there would be rescanned as code.
      # The body goes through the same passes as any other statement, so a
      # chain, a hash read or an xconout in one is translated rather than
      # spliced as written. It may become several physical lines -- a hash
      # read lifts a Get above the line using it -- and the stack holds them
      # as one block, which stays contiguous wherever it is spliced.
      # A deferred body is a statement, so it may carry a postfix modifier of
      # its own: 'defer exec oQuery:Destroy() if oQuery <> nil' runs the
      # cleanup on every exit, but only when there is something to clean up.
      body_text = defer_match.group(1).strip()
      body_modifier = parse_postfix(body_text)
      if body_modifier is not None and body_modifier["kind"] != "return":
        inner = rewrite_statement(body_modifier["body"], curr_scope, idx)
        produced = rewrite_statement(body_modifier["cond"], curr_scope,
                                     idx).split("\n")
        lead, cond = produced[:-1], produced[-1].strip()
        opener, closer = (("If", "EndIf") if body_modifier["op"] == "if"
                          else ("While", "EndDo"))
        deferred = "\n".join(
          [part for part in lead if part.strip()] + [f"{opener} {cond}"] +
          [f"  {part.strip()}" for part in inner.split("\n") if part.strip()] +
          [closer])
      else:
        deferred = rewrite_statement(body_text, curr_scope, idx)

      # Resolved here, once, rather than wherever it is spliced. A defer
      # reaching a 'return' used to be resolved as part of that line while one
      # reaching the end of the function was not, so the same body could be
      # renamed in one exit path and not the other -- and a variable read only
      # by an end-of-function defer was reported as never read, because the
      # pass that counts reads never saw it.
      deferred = "\n".join(
        re.sub(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', resolve_identifier, part)
        for part in deferred.split("\n"))
      defer_stack.append(deferred)
      continue

    if find_top_level(line, "==>") >= 0 or find_top_level(line, "=>") >= 0:
      raise SyntaxError(
        f"Line {idx + 1}: the feed operator is now '|>'.")

    if find_top_level(line, "?=>") >= 0:
      raise SyntaxError(
        f"Line {idx + 1}: '?=>' was removed; chain with '=>' and guard the "
        f"whole chain with 'fallback'.")

    stale = re_stale_marker.search(line)
    if stale:
      raise SyntaxError(
        f"Line {idx + 1}: '[{stale.group(1)}]' was removed. Attributes go on "
        f"the declaration, in angle brackets: '<contained>' and '<const>'. "
        f"Passing a variable to a function needs no marker.")

    stale_fold = re_reduce_operator.search(line)
    if stale_fold and not re_lambda_head.match(stale_fold.group(0)):
      raise SyntaxError(
        f"Line {idx + 1}: the fold operators were replaced by functions: "
        f"asum(), aprod(), amax(), amin(), or fold() for anything else.")

    if re_external.match(line):
      continue

    if re_removed_block.match(line):
      raise SyntaxError(
        f"Line {idx + 1}: 'with', 'orwith', 'without', 'given' and 'when' were "
        f"removed; use 'do case with [local] x := expr' and ordinary 'case' "
        f"conditions, or '?:' for first-non-Nil.")

    if re_gather_removed.match(line):
      raise SyntaxError(
        f"Line {idx + 1}: gather/take was removed; build the array explicitly "
        f"with aadd(), or use a '==>' pipeline.")

    if re_foreach_each.match(line):
      raise SyntaxError(
        f"Line {idx + 1}: 'for each' is now just 'for' -- the three for-forms "
        f"are told apart by their shape, so the word said nothing.")

    if re_let_removed.match(line):
      raise SyntaxError(
        f"Line {idx + 1}: 'let' was removed; 'local' now has stack semantics.")

    if_local_match = re_if_local.search(line)
    while_local_match = re_while_local.search(line)
    local_decl_match = re_local_decl.match(line)
    private_decl_match = re_private_decl.match(line)
    dor_match = re_defined_or.search(line)
    for_match = re_for.search(line)

    object_match = re_with_object.match(line)
    if object_match:
      indent, subject = object_match.group(1), object_match.group(2).strip()
      holder = register_block_local("__obj", curr_scope, idx + 1)
      lead, resolved = rewrite_value(subject, curr_scope, idx, indent)
      for part in lead:
        emit(part)
      # Evaluated once, however many lines refer to it.
      emit(f"{indent}{holder} := {apply_with_object(resolved)}")
      object_stack.append(holder)
      continue

    using_match = re_using.match(anchored)
    if using_match:
      indent = using_match.group(1)
      alias_text, order = using_match.group(2).strip(), using_match.group(3)
      # A bare word is the alias itself -- 'using alias SA1' -- unless it is a
      # variable in scope, in which case it holds one. Without that test a
      # parameter named cAlias compiled to DbSelectArea("cAlias").
      literal = None
      if re_string_token.match(alias_text):
        literal = unmask_literals(alias_text, literal_parts).strip("\"'")
      elif (re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', alias_text) and
            not any(alias_text.lower() in scope_vars[s_id]
                    for s_id in scope_stack)):
        literal = alias_text

      area = register_block_local("__usearea", curr_scope, idx + 1)
      record = register_block_local("__userec", curr_scope, idx + 1)

      if literal and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', literal):
        # Written out, because SA1->A1_COD is what gets read in review.
        field, select = literal, masked_literal(f'"{literal}"')
      else:
        lead, resolved = rewrite_value(alias_text, curr_scope, idx, indent)
        for part in lead:
          emit(part)
        holder = register_block_local("__usealias", curr_scope, idx + 1)
        emit(f"{indent}{holder} := {resolved}")
        field, select = f"({holder})", holder

      emit(f"{indent}{area} := Alias()")
      emit(f"{indent}DbSelectArea({select}){anchored_note}")
      emit(f"{indent}{record} := {field}->(RecNo())")

      restore = []
      if order is not None:
        keep = register_block_local("__useord", curr_scope, idx + 1)
        lead, resolved = rewrite_value(order.strip(), curr_scope, idx, indent)
        for part in lead:
          emit(part)
        emit(f"{indent}{keep} := {field}->(IndexOrd())")
        emit(f"{indent}{field}->(DbSetOrder({resolved}))")
        restore.append(f"{field}->(DbSetOrder({keep}))")
      # The record pointer goes back too: a walk inside the block leaves the
      # area at Eof, and the caller did not ask for that.
      restore.append(f"{field}->(DbGoto({record}))")
      restore.extend([f"If !Empty({area})", f"  DbSelectArea({area})", "EndIf"])
      using_stack.append({"restore": restore, "line": idx + 1})
      continue

    # 'next' closing a file loop is an EndDo, and closes the file after it.
    if re_block_close.match(line) and scope_stack[-1] in file_loops:
      closing = file_loops.pop(scope_stack[-1])
      emit(f"{closing}EndDo")
      for part in using_stack.pop()["restore"]:
        emit(f"{closing}{part}")
      close_scope()
      continue

    if re_end_using.match(line):
      if not using_stack:
        raise SyntaxError(f"Line {idx + 1}: 'end using' without a 'using'.")
      block = using_stack.pop()
      for part in block["restore"]:
        emit(f"{leading_indent(line)}{part}")
      close_scope()
      continue

    if re_end_with.match(line) and object_stack:
      object_stack.pop()
      close_scope()
      continue

    line = apply_with_object(line)

    # The header is matched without its comment, then the comment is put back
    # on the emitted For line, where the programmer wrote it.
    loop_code, loop_note = anchored, anchored_note
    loop = None
    for_rules = for_grammar()
    if for_rules is not None:
      parsed = for_rules.parse(loop_code)
      loop = parsed.made if parsed else None
    else:
      times_hit = re_fortimes.match(loop_code)
      each_hit = re_foreach.match(loop_code)
      if each_hit:
        loop = {"kind": "foreach", "indent": each_hit.group(1),
                "elem": each_hit.group(2), "index": each_hit.group(3) or "",
                "source": each_hit.group(4).strip()}
      elif times_hit:
        loop = {"kind": "fortimes", "indent": times_hit.group(1),
                "count": times_hit.group(2).strip()}

    if loop and loop["kind"] == "fortimes":
      indent, count = loop["indent"], loop["count"]
      counter = register_block_local("__times", curr_scope, idx + 1)
      lead, resolved = rewrite_value(count, curr_scope, idx, indent)
      for part in lead:
        emit(part)
      if not is_literal_expr(count):
        # Bound first, so a call sits above the loop rather than in its header
        # where a reader would not expect one.
        limit = register_block_local("__ntimes", curr_scope, idx + 1)
        emit(f"{indent}{limit} := {resolved}")
        resolved = limit
      emit(f"{indent}For {counter} := 1 To {resolved}{loop_note}")
      continue

    if loop and loop["kind"] == "foreach":
      indent = loop["indent"]
      elem_name, index_name = loop["elem"], loop["index"]
      source = loop["source"]

      # The array and the counter live for the whole loop, so they are
      # ordinary block locals of the loop's own scope -- slot-recycled with
      # everything else, and never touched by a body statement's temps.
      holder = register_block_local("__each", curr_scope, idx + 1)
      mangled_elem = register_block_local(elem_name, curr_scope, idx + 1)
      if index_name:
        counter = register_block_local(index_name, curr_scope, idx + 1)
      else:
        counter = register_block_local("__eachi", curr_scope, idx + 1)

      # A file source walks instead of indexing. Unlike rows(), the element
      # here IS a value -- the line -- so it binds to the name in the ordinary
      # way and the body needs no rewriting.
      reading = re_lines_head.match(source)
      if reading:
        path = source_argument(source, "lines", reading, idx)
        lead, resolved = rewrite_value(path, curr_scope, idx, indent)
        for part in lead:
          emit(part)
        emit(f"{indent}{holder} := {resolved}")
        # Asked once, into a flag. On a file that never opened FT_FEof()
        # stays .F. and the walk would never end, but File() in the condition
        # is a filesystem call per line. The body here is the programmer's,
        # so an 'If' around it would mean tracking a closer their 'next' does
        # not know about -- a flag does the same work.
        opened = register_block_local("__opened", curr_scope, idx + 1)
        emit(f"{indent}{opened} := File({holder})")
        emit(f"{indent}If {opened}")
        emit(f"{indent}  FT_FUse({holder})")
        emit(f"{indent}  FT_FGoTop()")
        emit(f"{indent}EndIf")
        emit(f"{indent}{counter} := 0")
        emit(f"{indent}While {opened} .And. !FT_FEof(){loop_note}")
        emit(f"{indent}  {counter} := {counter} + 1")
        emit(f"{indent}  {mangled_elem} := FT_FReadLn()")
        # Advanced straight after reading, not at the foot of the loop. The
        # body is the programmer's, so it may contain a 'Loop' -- and a Loop
        # over a skip at the foot would never advance the file and hang.
        emit(f"{indent}  FT_FSkip()")
        file_loops[curr_scope] = indent
        # Closing the file is an exit-path job, like restoring a work area:
        # a 'return' out of the middle of the loop has to close it too.
        # A list of lines, like every other entry: a bare string here is
        # iterated character by character where the stack is read.
        # Guarded, like the open: an argument-less FT_FUse() after a failed
        # open closes whatever file was current before this loop.
        using_stack.append({"restore": [f"If {opened}", "  FT_FUse()", "EndIf"],
                            "line": idx + 1})
        continue

      lead, resolved = rewrite_value(source, curr_scope, idx, indent)
      for part in lead:
        emit(part)
      # Bound once: the source may be a call, and it is indexed every pass.
      emit(f"{indent}{holder} := {resolved}")
      emit(f"{indent}For {counter} := 1 To Len({holder}){loop_note}")
      emit(f"{indent}  {mangled_elem} := {holder}[{counter}]")
      continue

    if if_local_match:
      var_name, rest = if_local_match.group(1), if_local_match.group(2).strip()
      expr, cond = split_by_top_level_comma(rest)
      if cond is None:
        raise SyntaxError(f"Line {idx + 1}: 'if local' requires a comma and a condition.")

      indent = leading_indent(line)
      mangled = register_declaration(var_name, curr_scope, idx + 1)
      lead, resolved_expr = rewrite_value(expr, curr_scope, idx, indent)
      for part in lead:
        emit(part)
      emit(f"{indent}{mangled} := {resolved_expr}")
      line = f"{indent}If {cond}"

    elif while_local_match:
      var_name, rest = while_local_match.group(1), while_local_match.group(2).strip()
      expr, cond = split_by_top_level_comma(rest)
      if cond is None:
        raise SyntaxError(f"Line {idx + 1}: 'while local' requires a comma and a condition.")

      indent = leading_indent(line)
      mangled = register_declaration(var_name, curr_scope, idx + 1)
      lead, resolved_expr = rewrite_value(expr, curr_scope, idx, indent)
      cond_lead, resolved_cond = rewrite_value(cond, curr_scope, idx, indent)

      # ':=' is an expression in AdvPL and yields the value assigned, so the
      # whole thing fits in the condition and the loop-and-a-half disappears:
      #
      #   While (s_1_x := proximo(o)) != Nil
      #
      # Only when the variable's first appearance in the condition is
      # evaluated unconditionally. Behind a '.and.' or inside an 'iif' it may
      # never be reached, and then the assignment -- which is usually what
      # advances something -- would not happen at all.
      before_it = re.split(rf'\b{re.escape(mangled)}\b', resolved_cond, 1)[0]
      reachable = not re.search(r'\.(?:and|or)\.|\biif\b', before_it,
                                re.IGNORECASE)
      if (not lead and not cond_lead and reachable
          and re.search(rf'\b{re.escape(mangled)}\b', resolved_cond)):
        folded = re.sub(rf'\b{re.escape(mangled)}\b',
                        f"({mangled} := {resolved_expr})", resolved_cond, 1)
        emit(f"{indent}While {folded}")
        continue

      emit(f"{indent}While .T.")
      for part in lead + cond_lead:
        emit(f"  {part}")
      emit(f"{indent}  {mangled} := {resolved_expr}")
      emit(f"{indent}  If !({resolved_cond})")
      emit(f"{indent}    Exit")
      emit(f"{indent}  EndIf")
      continue

    elif for_match:
      is_local = bool(for_match.group("is_local"))
      var_name, loop_init = for_match.group(2), for_match.group(3).strip()
      indent = leading_indent(line)

      if is_local:
        mangled = register_declaration(var_name, curr_scope, idx + 1)
      else:
        var_lower = var_name.lower()
        declared, mangled = False, var_name
        for s_id in reversed(scope_stack):
          if var_lower in scope_vars[s_id]:
            declared, mangled = True, scope_var_mangling[s_id][var_lower]
            break
        if not declared:
          if not legacy:
            raise SyntaxError(f"Line {idx + 1}: Variable '{var_name}' used without prior declaration.")
          mangled = var_name

      line = f"{indent}for {mangled} := {loop_init}"

    elif private_decl_match:
      indent = private_decl_match.group(1)
      declarators, decl_note = peel_comment(private_decl_match.group(2),
                                            literal_parts)
      parsed_private = parse_declarators(declarators, idx + 1)
      for position, (var_name, operator, expr, attrs, typing) in enumerate(
          parsed_private):
        if attrs:
          raise SyntaxError(
            f"Line {idx + 1}: a PRIVATE cannot carry attributes -- it is "
            f"visible to everything this function calls, so nothing here can "
            f"promise what happens to it.")
        note_here = decl_note if position == len(parsed_private) - 1 else ""
        mangled = register_native_variable(var_name, 0, idx + 1, private=True)
        if typing:
          declared_types[mangled] = typing
        if operator is None:
          continue
        if is_literal_expr(expr):
          resolved = re.sub(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', resolve_identifier, expr)
          hoisted_inits[mangled] = unmask_literals(resolved, literal_parts)
          if note_here:
            hoisted_notes[mangled] = unmask_literals(note_here, literal_parts)
          continue
        # An initialiser that is not a constant is a statement of its own,
        # where the declaration stands.
        lead, final = rewrite_value(expr, curr_scope, idx, indent)
        for produced in lead:
          emit(produced)
        emit(f"{indent}{mangled} := {final}"
             + (f"  {note_here.strip()}" if note_here.strip() else ""))
      continue

    elif local_decl_match:
      indent = local_decl_match.group(1)
      # Peeled once for the whole list, and put back on the last declarator --
      # which is where it was written. It used to ride inside that
      # declarator's value, which worked only while the last one had one.
      declarators, decl_note = peel_comment(local_decl_match.group(2),
                                            literal_parts)
      parsed = parse_declarators(declarators, idx + 1)
      for position, (var_name, operator, expr, attrs, typing) in enumerate(parsed):
        note_here = decl_note if position == len(parsed) - 1 else ""
        if "const" in attrs and operator != ":=":
          raise SyntaxError(
            f"Line {idx + 1}: '{var_name}' is <const> and must be given a "
            f"value, since it can never be assigned again.")
        if operator == "?=":
          raise SyntaxError(
            f"Line {idx + 1}: '?=' is an operator, not a declaration form; "
            f"a new local is always Nil. Write 'local {var_name} := ...' instead.")

        if curr_scope == 0:
          mangled = register_native_variable(var_name, 0, idx + 1)
          if typing:
            declared_types[mangled] = typing
          if "const" in attrs:
            const_names[mangled] = idx + 1
            if looks_like_container(expr):
              const_notes.add(mangled)
          if operator is None:
            continue
          # Only a declaration in the FUNCTION's prologue may fold its
          # initialiser into the hoisted Local. One written after the first
          # statement keeps its initialiser where it was: folding it would run
          # at function entry instead, which is a different program.
          in_function_prologue = curr_scope == 0 and prologue_open.get(0, True)
          if is_literal_expr(expr) and (not legacy or in_function_prologue):
            # Constant: safe to fold into the hoisted declaration.
            resolved = re.sub(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', resolve_identifier, expr)
            hoisted_inits[mangled] = unmask_literals(resolved, literal_parts)
            if note_here:
              hoisted_notes[mangled] = unmask_literals(note_here, literal_parts)
            continue
        else:
          mangled = register_block_local(var_name, curr_scope, idx + 1)
          # A recycled slot is shared, so a type from one declaration cannot
          # be claimed for it; only private storage keeps the annotation.
          if typing and mangled.startswith("b_"):
            declared_types[mangled] = typing
          if "const" in attrs:
            const_names[mangled] = idx + 1

        # Entering the block gives a fresh variable, so an uninitialised one
        # is cleared rather than left holding a sibling block's value.
        if note_here:
          expr = f"{expr}{note_here}" if expr else expr
        value = expr if operator else "Nil"
        # A trailing comment travels with the value; peel it so it cannot sit
        # between a hash literal and the '}' that ends it.
        value, value_note = peel_comment(value, literal_parts)
        lead, resolved = rewrite_value(value, curr_scope, idx, indent)
        note = f"  {value_note}" if value_note else ""
        pairs = hash_literal_pairs(resolved)
        if pairs is not None:
          emit("\n".join(lead + build_hash(mangled, pairs, indent)) + note)
        else:
          emit("\n".join(lead + [f"{indent}{mangled} := {resolved}{note}"]))
        if mangled in const_names and looks_like_container(expr):
          emit(f"{indent}{CONST_NOTE}")
      continue

    elif dor_match:
      var_name, default_expr = dor_match.group(1), dor_match.group(2).strip()
      indent = leading_indent(line)
      var_lower = var_name.lower()
      mangled = None
      for s_id in reversed(scope_stack):
        if var_lower in scope_vars[s_id]:
          mangled = scope_var_mangling[s_id][var_lower]
          break
      if not mangled:
        if not legacy:
          raise SyntaxError(f"Line {idx + 1}: Variable '{var_name}' used with '?=' without prior declaration.")
        mangled = var_name
      reject_if_const(var_name, idx + 1, "assigned")
      line = f"{indent}If {mangled} == Nil\n{indent}  {mangled} := {default_expr}\n{indent}EndIf"

    else:
      assign_match = re_assign.search(line)
      if True:
        if assign_match:
          var_name, var_lower = assign_match.group(1), assign_match.group(1).lower()
          if var_lower in external_names:
            raise SyntaxError(
              f"Line {idx + 1}: '{var_name}' is external (line "
              f"{external_names[var_lower]}) and cannot be assigned.")
          reject_if_const(var_name, idx + 1, "assigned")
          if var_lower not in reserved_words and var_lower not in private_names:
            declared = any(var_lower in scope_vars[s_id] for s_id in scope_stack)
            if not declared:
              if not legacy:
                raise SyntaxError(f"Line {idx + 1}: Variable '{var_name}' used without declaration.")
              # In AdvPL a write to an undeclared name CREATES a PRIVATE.
              # That is legal and an anti-pattern, so under --legacy it is
              # reported once, where it happens, rather than at every later
              # use -- those reads are of a variable that by then exists.
              if var_lower not in legacy_privates:
                legacy_privates[var_lower] = (var_name, idx + 1)
                print(f"warning: line {idx + 1}: '{var_name}' is not declared, "
                      f"so this creates a PRIVATE", file=sys.stderr)

    docase_match = re_docase.match(line)
    if docase_match:
      indent, is_local = docase_match.group(1), bool(docase_match.group(2))
      subject, expr = docase_match.group(3), docase_match.group(4).strip()
      if is_local:
        mangled = register_declaration(subject, curr_scope, idx + 1)
      else:
        mangled = resolve_declared(subject, idx + 1)
        reject_if_const(subject, idx + 1, "assigned")
      lead, resolved = rewrite_value(expr, curr_scope, idx, indent)
      for part in lead:
        emit(part)
      # The subject is evaluated once, before the chain of Case tests.
      emit(f"{indent}{mangled} := {resolved}")
      emit(f"{indent}Do Case")
      continue

    # Peeled here so the passes below see only the statement, and every line
    # the statement becomes ends up inside the generated If or While rather
    # than the last one alone.
    modifier = parse_postfix(line)
    if modifier is not None:
      line = f"{leading_indent(line)}{modifier['body']}"

    line = rewrite_statement(line, curr_scope, idx)

    segments = line.split("\n")
    last_stripped = segments[-1].strip()

    if modifier is not None:
      indent = leading_indent(segments[-1])
      # The condition is a statement's worth of expression too: it may lift a
      # hash read or a chain stage, and those go above the block, as they did
      # when the whole line was rewritten together.
      produced = rewrite_statement(f"{indent}{modifier['cond']}",
                                   curr_scope, idx).split("\n")
      cond_lead, cond = produced[:-1], produced[-1].strip()
      body = [f"{indent}  {part.strip()}" for part in segments if part.strip()]

      if modifier["kind"] == "return":
        (returns_value if body else returns_bare).append(idx + 1)
        # The value is computed, then the defers run, then the return -- so a
        # deferred statement cannot change what is being returned.
        value = body[-1].strip() if body else ""
        # Deferred statements first -- they may still want the area -- and
        # then the work areas go back, innermost block first.
        defers = [f"{indent}  {part}" for d in reversed(defer_stack)
                  for part in d.split("\n") if part.strip()]
        defers += [f"{indent}  {part}" for block in reversed(using_stack)
                   for part in block["restore"]]
        segments = (cond_lead + [f"{indent}If {cond}"] + body[:-1] + defers +
                    [f"{indent}  Return {value}" if value else f"{indent}  Return",
                     f"{indent}EndIf"])
      elif modifier["op"] == "if":
        segments = (cond_lead + [f"{indent}If {cond}"] + body +
                    [f"{indent}EndIf"])
      else:
        segments = (cond_lead + [f"{indent}While {cond}"] + body +
                    [f"{indent}EndDo"])

    elif re_explicit_return.match(last_stripped):
      # Peeled, or a comment after a bare 'Return' reads as the value it
      # returns and the function looks consistent when it is not.
      carried, _ = peel_comment(last_stripped, literal_parts)
      carried = carried[len("return"):].strip()
      (returns_value if carried else returns_bare).append(idx + 1)
      indent = leading_indent(segments[-1])
      defers = [f"{indent}{part}" for d in reversed(defer_stack)
                for part in d.split("\n") if part.strip()]
      defers += [f"{indent}{part}" for block in reversed(using_stack)
                 for part in block["restore"]]
      if defers:
        segments = segments[:-1] + defers + [segments[-1]]

    line = "\n".join(segments)

    # A chain only composes at statement level. Anything left over is nested
    # inside an expression, where it would pass through as invalid AdvPL.
    if feed_outside_block(expr_nodes(line)):
      raise SyntaxError(
        f"Line {idx + 1}: '|>' only chains at statement level; assign the "
        f"chain to a variable first.")

    # '?=' is a statement, not an expression: it is only 'name ?= value' on a
    # line of its own. Anywhere else nothing rewrites it and it used to reach
    # the output verbatim, which is not AdvPL.
    # At any depth: '(f() ?= {})' is exactly the case that reached the output
    # untouched, and it is nested.
    if "?=" in line:
      raise SyntaxError(
        f"Line {idx + 1}: '?=' assigns to a variable and is only a statement "
        f"of its own. For a value that falls back when Nil, inside an "
        f"expression, use '?:'.")

    # A source that survived the feed pass was not at the head of a chain, and
    # there is no function of that name to call.
    stranded = re_source_call.search(line)
    if stranded:
      raise SyntaxError(
        f"Line {idx + 1}: '{stranded.group(1)}()' is a source, and only reads "
        f"at the head of a chain. Assign it, or feed it into stages with "
        f"'|>'.")

    for called in re_call_name.finditer(line):
      name = called.group(1)
      plain = name.lower()
      if plain.startswith("u_") and plain[2:] in local_kind:
        if local_kind[plain[2:]] == "static":
          raise SyntaxError(
            f"Line {idx + 1}: '{name}' -- {local_functions[plain[2:]][0]} is a "
            f"static function in this file, so it is called by its plain "
            f"name, without the 'u_'.")
      elif plain in local_kind and local_kind[plain] == "user":
        raise SyntaxError(
          f"Line {idx + 1}: '{name}' is a user function (line "
          f"{local_functions[plain][2]}), so it is called as 'u_{name}' -- "
          f"the compiler puts the prefix on the declaration.")

    for by_ref in re_by_ref.finditer(line):
      reject_if_const(by_ref.group(1), idx + 1, "passed by reference with '@'")

    processed_line = re.sub(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', resolve_identifier, line)

    if not line.strip():
      function_buffer.append("")
    else:
      emit(processed_line)

    if re_scope_out.search(line):
      close_scope()

  flush_function(len(lines))

  # Every generated file needs these. Added at the top, and only the ones the
  # source has not already asked for -- a file that includes totvs.ch itself
  # should not end up with it twice.
  have = source_code.lower()
  wanted = [name for name in ("totvs.ch", "tlpp-core.th")
            if not re.search(rf'#\s*include\s+["\']{re.escape(name)}["\']',
                             have)]
  header = [f'#include "{name}"' for name in wanted]
  if translate_rules:
    header += [
      "",
      "// Armazenamento dividido por mais de uma variavel de bloco.",
      "//",
      "// 'let' marca onde uma variavel de bloco e declarada e qual",
      "// armazenamento ela recebeu. Nao gera nada.",
      "//",
      "// Onde um slot e dividido por mais de uma variavel ele nao tem nome",
      "// honesto, entao cada linha o escreve com o nome de quem o ocupa ali:",
      "// '!aTmp^1^0!' e '!cOutro^1^0!' sao o mesmo slot. Os outros nomes ja",
      "// dizem de quem sao -- 's_1_aTmp', 'b_0_nFator'.",
      "//",
      "// Uma regra so, para todos os slots: os marcadores entram no proprio",
      "// nome do resultado. O '!' na frente impede que a regra case com uma",
      "// potenciacao de verdade, 'a^2^3'; o '!' no fim fecha o padrao, sem",
      "// o qual o ultimo marcador engole o que vem depois.",
      "#translate let <name1> as <name2> =>",
      "#translate !<name>^<num1>^<num2>! => s_<num1>_<num2>",

    ]
  if header:
    out_lines[:0] = header + [""]

  if not any(re_func.search(raw) for raw in lines):
    print("warning: no function was recognised in this file, so nothing was "
          "transpiled -- every line was copied through as it was",
          file=sys.stderr)

  if legacy and (legacy_prologue or legacy_undeclared or legacy_privates):
    uses = sum(count for _, count in legacy_undeclared.values())
    common = sorted(legacy_undeclared.values(), key=lambda p: -p[1])[:5]
    out = len(legacy_prologue)
    print(f"legacy: {out} declaration{'' if out == 1 else 's'} outside a "
          f"prologue, {uses} use{'' if uses == 1 else 's'} of "
          f"{len(legacy_undeclared)} undeclared "
          f"name{'' if len(legacy_undeclared) == 1 else 's'}",
          file=sys.stderr)
    if legacy_privates:
      named = ", ".join(sorted(name for name, _ in legacy_privates.values()))
      print(f"legacy: {len(legacy_privates)} implicit "
            f"PRIVATE{'' if len(legacy_privates) == 1 else 's'} -- {named}",
            file=sys.stderr)
    if common:
      # The frequent ones say what KIND of file this is: SAY, GET and PICTURE
      # at the top mean the file is command-shaped and wants 'raw', not
      # declarations.
      listed = ", ".join(f"{name} ({count})" for name, count in common)
      print(f"legacy: most used undeclared -- {listed}", file=sys.stderr)

  return "\n".join(out_lines)


if __name__ == "__main__":
  args = sys.argv[1:]
  strict = "--dict-strict" in args
  legacy = "--legacy" in args
  mapped = "--map" in args
  # Parse and report, write nothing. The output path becomes optional, since
  # there is nothing to put in it.
  check_only = "--check" in args
  args = [a for a in args
          if a not in ("--dict-strict", "--legacy", "--map", "--check")]
  sx3 = None
  if "--dict" in args:
    at = args.index("--dict")
    if at + 1 >= len(args):
      print("--dict needs the path to an exported SX3")
      sys.exit(1)
    sx3 = args[at + 1]
    del args[at:at + 2]

  if "--version" in sys.argv:
    print(f"xtpl {_version()}")
    sys.exit(0)

  if not args:
    print(f"xtpl {_version()}")
    print("Uso / Usage:")
    print("  xtpl_transpiler.py <entrada.xtpl> [saida.tlpp]")
    print()
    print("  Sem o segundo argumento, a saída fica ao lado da entrada com")
    print("  extensão .tlpp.  Without the second argument, the output goes")
    print("  beside the input with a .tlpp extension.")
    print()
    print("  --dict sx3.csv   verificar campos contra um SX3 exportado")
    print("  --dict-strict    esses avisos viram erros")
    print("  --legacy         aceitar um .prw existente, avisando")
    print("  --map            marcar cada linha com a linha de origem")
    print("  --check          analisar e relatar, sem escrever nada")
    sys.exit(1)

  def read_source(path):
    """(text, encoding, newline) -- read it however it was written.

    Protheus source is commonly ISO-8859-1 with CRLF, and assuming UTF-8 met
    a real file with a raw UnicodeDecodeError. The encoding and the line
    ending are both carried back to the output: writing UTF-8 from a
    latin-1 source would corrupt every accented string on the way to a
    compiler that is not expecting it.
    """
    raw = path.read_bytes()
    ending = "\r\n" if b"\r\n" in raw else "\n"
    for name in ("utf-8", "cp1252", "latin-1"):
      try:
        return raw.decode(name), name, ending
      except UnicodeDecodeError:
        continue
    return raw.decode("latin-1", errors="replace"), "latin-1", ending

  source = pathlib.Path(args[0])
  # The output name is the convention, so it need not be typed. Running the
  # transpiler on one file is the commonest thing anyone does with it, and
  # answering that with a usage message is a poor greeting.
  target = pathlib.Path(args[1]) if len(args) > 1 else source.with_suffix(".tlpp")

  if not source.exists():
    print(f"não encontrado / not found: {source}")
    sys.exit(1)
  if not check_only and target == source:
    print(f"a saída sobrescreveria a entrada / output would overwrite the "
          f"input: {source}")
    sys.exit(1)

  # Off unless a dictionary is given: field checking is worth having, not
  # worth requiring an export of everyone who wants to compile a file.
  sx3_fields = load_dictionary(sx3) if sx3 else None
  code, encoding, ending = read_source(source)
  produced = transpile(code, sx3_fields, strict, legacy, mapped)
  if not check_only:
    target.write_bytes(produced.replace("\n", ending).encode(encoding,
                                                             errors="replace"))

# --------------------------------------------------------------------------------
# the end
