import typing
import sublime
import sublime_plugin
import re

RE_FILE = re.compile("^([^ \t].*):$")
RE_LINE = re.compile("^ +([0-9]+):")

EXT = ".search"
def is_ext(path: typing.Optional[str]):
  return path.endswith(EXT) if path else False
def is_ext_view(view: sublime.View):
  return is_ext(view.file_name())
def set_syntax(view: sublime.View):
  # https://forum.sublimetext.com/t/find-results-files-a-way-to-open-it-after-it-was-saved/16094
  view.assign_syntax("Packages/Default/Find Results.hidden-tmLanguage")
  settings = view.settings()
  settings.set("detect_indentation", False)
  settings.set("line_numbers", False)
  settings.set("output_tag", 1)
  settings.set("result_base_dir", "")
  settings.set("result_file_regex", RE_FILE.pattern)
  settings.set("result_line_regex", RE_LINE.pattern)
  settings.set("scroll_past_end", True)
  settings.set("translate_tabs_to_spaces", False)

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

Arg = typing.Tuple[str, typing.List[typing.Tuple[int, str]]]
def make_arg(view: sublime.View) -> Arg:
  path = view.file_name()
  assert isinstance(path, str)
  rs = sorted(sublime.Region(*r) for r in set(r.to_tuple() for s in view.sel() for r in view.lines(s)))
  lines = [(view.rowcol(r.a)[0], view.substr(r)) for r in rs]
  return (path, lines)

def g_lines(lines: typing.List[str], i: int):
  while i < len(lines) and not RE_FILE.match(lines[i]):
    m = RE_LINE.match(lines[i])
    if m:
      yield (i, int(m[1]) - 1)
    i += 1
Group = typing.Tuple[int, typing.List[typing.Tuple[int, int]]]
def g_files(lines: typing.List[str]):
  for i, line in enumerate(lines):
    m = RE_FILE.match(line)
    if m:
      s: str = m[1]
      yield (s, (i, list(g_lines(lines, i + 1))))

def g_merge(lines: typing.List[str], arg: Arg):
  dlines = {"%5d: %s" % (j + 1, line): j for j, line in arg[1]}
  glast: Group = None
  for path, g in g_files(lines):
    if path == arg[0]:
      glast = g
      for i, _ in g[1]:
        # allow duplicate line number with different text
        dlines.pop(lines[i], None)
  alines = sorted(dlines.items())
  if not glast:
    i = len(lines)
    if not lines or lines[-1]:
      yield (i, "")
    glast = (i, [])
    yield (i, "%s:" % arg[0])
  mm = 0
  ii = [glast[0], *(i for i, _ in glast[1])]
  jj = [*(j for _, j in glast[1]), None]
  for i, jm in zip(ii, jj):
    for m in range(mm, len(alines)):
      line, j = alines[m]
      # duplicate line number with new text comes after old text
      if jm is not None and j >= jm:
        break
      yield (i + 1, line)
      mm = m + 1

LOADING = "AddToSearch"
class AddToSearchAddToCommand(sublime_plugin.TextCommand):
  def run(self, edit: sublime.Edit, arg: Arg):
    eol = "\n"
    full = sublime.Region(0, self.view.size())
    text = self.view.substr(full)
    rlines = list(self.view.lines(full))
    insert = sorted(g_merge([text[r.a:r.b] for r in rlines], arg))
    toffset = 0
    selection = self.view.sel()
    selection.clear()
    if rlines[-1].b == full.b:
      self.view.insert(edit, full.b, eol)
      toffset += len(eol)
    for iline, tline in insert:
      at = toffset + (rlines[iline].a if iline < len(rlines) else full.b)
      self.view.insert(edit, at, tline + eol)
      if tline:
        selection.add(sublime.Region(at, at + len(tline)))
      toffset += len(tline) + len(eol)

class AddToSearchAddCommand(sublime_plugin.TextCommand, WithPath):
  def run(self, edit: sublime.Edit):
    settings = Settings.cmd(self)
    view = settings.window.open_file(settings.add_to)
    if view.is_loading():
      view.settings().set(LOADING, make_arg(self.view))
    else:
      view.run_command("add_to_search_add_to", dict(arg=make_arg(self.view)))
  def is_enabled(self):
    if not self.path: return False
    settings = Settings.cmd(self)
    return bool(settings.add_to)

class ViewEvents(sublime_plugin.EventListener):
  def on_init(self, views: typing.List[sublime.View]):
    for view in views:
      if is_ext_view(view):
        set_syntax(view)

  def on_load(self, view: sublime.View):
    if is_ext_view(view):
      set_syntax(view)
    arg = view.settings().get(LOADING)
    if arg:
      view.run_command("add_to_search_add_to", dict(arg=arg))

  def on_post_save(self, view: sublime.View):
    if is_ext_view(view):
      set_syntax(view)
