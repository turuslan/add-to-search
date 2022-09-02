import typing
import sublime
import sublime_plugin
import re

RE_FILE = re.compile("^([^ \t].*):$")
RE_LINE = re.compile("^ +([0-9]+):")

EXT = ".search"
SYNTAX = "Packages/Default/Find Results.hidden-tmLanguage"
def is_ext(path: typing.Optional[str]):
  return path.endswith(EXT) if path else False
def is_ext_view(view: sublime.View):
  return is_ext(view.file_name())
def set_syntax(view: sublime.View):
  # https://forum.sublimetext.com/t/find-results-files-a-way-to-open-it-after-it-was-saved/16094
  view.assign_syntax(SYNTAX)
  settings = view.settings()
  settings.set("detect_indentation", False)
  settings.set("line_numbers", False)
  settings.set("output_tag", 1)
  settings.set("result_base_dir", "")
  settings.set("result_file_regex", RE_FILE.pattern)
  settings.set("result_line_regex", RE_LINE.pattern)
  settings.set("scroll_past_end", True)
  settings.set("translate_tabs_to_spaces", False)

T = typing.TypeVar("T")

def filter2(xs: typing.List[T], f):
  return ([x for x in xs if not f(x)], [x for x in xs if f(x)])

class Settings:
  PROJECT = "AddToSearch"
  ADD_TO = "add_to"
  @classmethod
  def cmd(cls, cmd: sublime_plugin.TextCommand):
    return cls(cmd.view.window())
  def __init__(self, window: sublime.Window):
    self.window = window
    self._data = window.project_data().get(self.PROJECT, {})
    self._apply = {}
  def apply(self):
    project = dict(self.window.project_data())
    project[self.PROJECT] = {**project.get(self.PROJECT, {}), **self._apply}
    self.window.set_project_data(project)
  @property
  def add_to(self):
    return self._apply.get(self.ADD_TO) or self._data.get(self.ADD_TO)
  @add_to.setter
  def add_to(self, add_to: str):
    self._apply[self.ADD_TO] = add_to

class WithPath:
  @property
  def path(self):
    return self.view.file_name()

class AddToSearchUseCommand(sublime_plugin.TextCommand, WithPath):
  def run(self, edit: sublime.Edit):
    settings = Settings.cmd(self)
    settings.add_to = self.path
    settings.apply()
  def is_enabled(self):
    return is_ext(self.path)

class AddToSearchOpenCommand(sublime_plugin.TextCommand):
  def run(self, edit: sublime.Edit):
    settings = Settings.cmd(self)
    settings.window.open_file(settings.add_to)
  def is_enabled(self):
    settings = Settings.cmd(self)
    return bool(settings.add_to)

def get_lines(view: sublime.View):
  full = sublime.Region(0, view.size())
  text = view.substr(full)
  rlines = list(view.lines(full))
  return full, rlines, [text[r.a:r.b] for r in rlines]

Arg = typing.Tuple[str, typing.List[typing.Tuple[int, str]]]
def make_arg(view: sublime.View) -> Arg:
  path = view.file_name()
  assert isinstance(path, str)
  rs = sorted(sublime.Region(*r) for r in {r.to_tuple() for s in view.sel() for r in view.lines(s)})
  lines = [(view.rowcol(r.a)[0], view.substr(r)) for r in rs]
  return (path, lines)

def make_arg2(view: sublime.View) -> typing.List[Arg]:
  selected_lines = {view.rowcol(x)[0] for x in {r.a for s in view.sel() for r in view.lines(s)}}
  _, _, lines = get_lines(view)
  _args: typing.Dict[str, typing.Dict[str, typing.Tuple[int, str]]] = dict()
  for path, g in g_files(lines):
    _arg = _args.get(path, None)
    def arg():
      nonlocal _arg
      if _arg is None:
        _arg = dict()
        _args[path] = _arg
      return _arg
    if g[0] in selected_lines:
      arg()
    for i, (j, s) in g[1]:
      if i in selected_lines:
        arg()[ukey(j, s)] = [j, s[1:] if s.startswith(" ") else s]
  return [(path, sorted(_arg.values(), key=lambda x: x[0])) for path, _arg in _args.items()]

def ukey(i: int, s: str):
  return "%d:%s" % (i, s.strip())

def g_lines(lines: typing.List[str], i: int):
  while i < len(lines) and not RE_FILE.match(lines[i]):
    m = RE_LINE.match(lines[i])
    if m:
      g: _Group = (i, (int(m[1]) - 1, lines[i][len(m[0]):]))
      yield g
    i += 1
_Group = typing.Tuple[int, typing.Tuple[int, str]]
Group = typing.Tuple[int, typing.List[_Group]]
def _g_file(line: str):
  m = RE_FILE.match(line)
  return m and str(m[1])
def g_files(lines: typing.List[str]):
  for i, line in enumerate(lines):
    m = _g_file(line)
    if m:
      yield (m, (i, list(g_lines(lines, i + 1))))

def g_merge(lines: typing.List[str], arg: Arg):
  arg[1] = sorted(arg[1], key=lambda x: x[0])
  dlines = {ukey(*js): i for i, js in enumerate(arg[1])}
  glast: Group = None
  for path, g in g_files(lines):
    if path == arg[0]:
      glast = g
      for _, js in g[1]:
        # allow duplicate line number with different text
        dlines.pop(ukey(*js), None)
  alines = sorted(dlines.values())
  if not glast:
    i = len(lines)
    if not lines or lines[-1]:
      yield (i, "")
    glast = (i - 1, [])
    yield (i, "%s:" % arg[0])
  mm = 0
  ii = [glast[0], *(i for i, _ in glast[1])]
  jj = [*(j for _, (j, _) in glast[1]), None]
  for i, jm in zip(ii, jj):
    for m in range(mm, len(alines)):
      j, s = arg[1][alines[m]]
      # duplicate line number with new text comes after old text
      if jm is not None and j >= jm:
        break
      yield (i + 1, " %4d: %s" % (j + 1, s))
      mm = m + 1

def g_merge2(lines: typing.List[str], args: typing.List[Arg]):
  _args: typing.Dict[str, Arg] = dict()
  for arg in args:
    _arg = _args.get(arg[0], None)
    if _arg is None:
      _args[arg[0]] = arg
    else:
      _arg[1].extend(arg[1])
  args = list(_args.values())
  existing = set(filter(None, map(_g_file, lines)))
  args = [x for xs in reversed(filter2(args, lambda x: x[0] in existing)) for x in xs]
  for arg in args:
    yield from g_merge(lines, arg)

LOADING = "AddToSearch"
class AddToSearchAddToCommand(sublime_plugin.TextCommand):
  def run(self, edit: sublime.Edit, args: typing.List[Arg]):
    eol = "\n"
    full, rlines, tlines = get_lines(self.view)
    insert = sorted(g_merge2(tlines, args), key=lambda x: x[0])
    toffset = 0
    selection = self.view.sel()
    selection.clear()
    if rlines[-1].b == full.b:
      self.view.insert(edit, full.b, eol)
      full.b += len(eol)
    for iline, tline in insert:
      at = toffset + (rlines[iline].a if iline < len(rlines) else full.b)
      self.view.insert(edit, at, tline + eol)
      if tline:
        selection.add(sublime.Region(at, at + len(tline)))
      toffset += len(tline) + len(eol)

class AddToSearchAddCommand(sublime_plugin.TextCommand, WithPath):
  @property
  def search(self):
    return is_ext(self.path) or self.view.settings().get("syntax") == SYNTAX
  def run(self, edit: sublime.Edit):
    settings = Settings.cmd(self)
    view = settings.window.open_file(settings.add_to)
    args = make_arg2(self.view) if self.search else [make_arg(self.view)]
    if not args: return
    if view.is_loading():
      view.settings().set(LOADING, args)
    else:
      view.run_command("add_to_search_add_to", dict(args=args))
  def is_enabled(self):
    if not self.search and not self.path: return False
    settings = Settings.cmd(self)
    if self.path == settings.add_to: return False
    return bool(settings.add_to)

class ViewEvents(sublime_plugin.EventListener):
  def on_init(self, views: typing.List[sublime.View]):
    for view in views:
      if is_ext_view(view):
        set_syntax(view)

  def on_load(self, view: sublime.View):
    if is_ext_view(view):
      set_syntax(view)
    args = view.settings().get(LOADING)
    if args:
      del view.settings()[LOADING]
      view.run_command("add_to_search_add_to", dict(args=args))

  def on_post_save(self, view: sublime.View):
    if is_ext_view(view):
      set_syntax(view)
