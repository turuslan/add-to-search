import * as vscode from "vscode";

function cmp<T>(l: T, r: T) {
  return l < r ? -1 : l > r ? +1 : 0;
}
function cmpf<T, U>(f: (x: T) => U) {
  return (l: T, r: T) => cmp(f(l), f(r));
}
function cmpn<T>(...cs: ((l: T, r: T) => number)[]) {
  return (l: T, r: T) => {
    for (const c of cs) {
      const d = c(l, r);
      if (d) {
        return d;
      }
    }
    return 0;
  };
}
function* zip<T, U>(ls: Iterable<T>, rs: Iterable<U>): Generator<[T, U]> {
  const ri = rs[Symbol.iterator]();
  for (const l of ls) {
    const r = ri.next();
    if (r.done) {
      break;
    }
    yield [l, r.value];
  }
}

function filter2<T>(xs: Iterable<T>, f: (x: T) => boolean) {
  const r: [T[], T[]] = [[], []];
  for (const x of xs) {
    r[f(x) ? 1 : 0].push(x);
  }
  return r;
}

function getLines(document: vscode.TextDocument) {
  const lines: vscode.TextLine[] = [];
  for (let i = 0; i < document.lineCount; ++i) {
    lines.push(document.lineAt(i));
  }
  return lines;
}

const EXT = ".search";
const RE_FILE = /^([^ \t].*):$/;
const RE_LINE = /^ +([0-9]+):/;

const ADD_TO = "add_to";

async function withAddTo(
  context: vscode.ExtensionContext,
  cb?: (editor: vscode.TextEditor) => Promise<void>,
) {
  const add_to: string = context.workspaceState.get(ADD_TO);
  if (!add_to) {
    return;
  }
  const editor = await vscode.window.showTextDocument(vscode.Uri.file(add_to));
  await cb?.(editor);
}

function getSelectedLines(editor: vscode.TextEditor): Set<number> {
  const selected_lines = new Set<number>();
  for (const selection of editor.selections) {
    for (let line = selection.start.line; line <= selection.end.line; ++line) {
      selected_lines.add(line);
    }
  }
  return selected_lines;
}

type Arg = [string, [number, string][]];
function make_arg(editor: vscode.TextEditor): Arg {
  const { document } = editor;
  return [
    document.fileName,
    Array.from(getSelectedLines(editor)).sort(cmp).map((iline) => [
      iline,
      document.lineAt(iline).text,
    ]),
  ];
}

function make_arg2(editor: vscode.TextEditor): Arg[] {
  const selected_lines = getSelectedLines(editor);
  const lines = getLines(editor.document).map((x) => x.text);
  const args = new Map<string, Map<string, [number, string]>>();
  for (const [path, g] of g_files(lines)) {
    let _arg = args.get(path);
    const arg = () => (_arg ?? args.set(path, _arg = new Map()), _arg);
    if (selected_lines.has(g[0])) {
      arg();
    }
    for (const [i, [j, s]] of g[1]) {
      if (selected_lines.has(i)) {
        arg().set(ukey(j, s), [j, s.startsWith(" ") ? s.slice(1) : s]);
      }
    }
  }
  return Array.from(args).map(([path, lines]) => [
    path,
    Array.from(lines.values()).sort(cmpf((x) => x[0])),
  ]);
}

function ukey(i: number, s: string) {
  return `${i}:${s.trim()}`;
}

function* g_lines(lines: string[], i: number): Generator<_Group> {
  while (i < lines.length && !RE_FILE.test(lines[i])) {
    const m = lines[i].match(RE_LINE);
    if (m) {
      yield [i, [+m[1] - 1, lines[i].slice(m[0].length)]];
    }
    ++i;
  }
}
function _g_file(line: string) {
  const m = line.match(RE_FILE);
  return m && m[1];
}
type _Group = [number, [number, string]];
type Group = [number, _Group[]];
function* g_files(
  lines: string[],
): Generator<[string, Group]> {
  let i = 0;
  for (const line of lines) {
    const m = _g_file(line);
    if (m) {
      yield [m, [i, Array.from(g_lines(lines, i + 1))]];
    }
    ++i;
  }
}
function* g_merge(lines: string[], arg: Arg): Generator<[number, string]> {
  arg[1].sort(cmpf((x) => x[0]));
  const dlines = new Map(
    arg[1].map((js, i) => [ukey(...js), i]),
  );
  let glast: Group | null = null;
  for (const [path, g] of g_files(lines)) {
    if (path === arg[0]) {
      glast = g;
      for (const [_i, js] of g[1]) {
        // allow duplicate line number with different text
        dlines.delete(ukey(...js));
      }
    }
  }
  const alines = Array.from(dlines.values()).sort(cmp);
  if (!glast) {
    const i = lines.length;
    if (!lines.length || lines[lines.length - 1]) {
      yield [i, ""];
    }
    glast = [i - 1, []];
    yield [i, `${arg[0]}:`];
  }
  let mm = 0;
  const ii = [glast[0], ...glast[1].map((x) => x[0])];
  const jj = [...glast[1].map((x) => x[1][0]), null];
  for (const [i, jm] of zip(ii, jj)) {
    while (mm < alines.length) {
      const [j, s] = arg[1][alines[mm]];
      // duplicate line number with new text comes after old text
      if (jm !== null && j >= jm) {
        break;
      }
      yield [i + 1, `  ${`${j + 1}`.padStart(5)}: ${s}`];
      ++mm;
    }
  }
}

function* g_merge2(lines: string[], args: Arg[]): Generator<[number, string]> {
  const _args = new Map<string, Arg>();
  for (const arg of args) {
    const _arg = _args.get(arg[0]);
    if (_arg === undefined) {
      _args.set(arg[0], arg);
    } else {
      _arg[1].push(...arg[1]);
    }
  }
  args = Array.from(_args.values());
  const existing = new Set(lines.map(_g_file).filter((x) => x));
  args = filter2(args, (x) => existing.has(x[0])).reverse().flat();
  for (const arg of args) {
    yield* g_merge(lines, arg);
  }
}

export function activate(context: vscode.ExtensionContext) {
  context.subscriptions.push(
    vscode.commands.registerTextEditorCommand(
      "AddToSearch.use",
      async (editor) => {
        const add_to = editor.document.fileName;
        if (!add_to.endsWith(EXT)) {
          return;
        }
        await context.workspaceState.update(ADD_TO, add_to);
      },
    ),
  );
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "AddToSearch.open",
      async () => await withAddTo(context),
    ),
  );
  context.subscriptions.push(
    vscode.commands.registerTextEditorCommand(
      "AddToSearch.add",
      async (editor) => {
        const { document } = editor;
        const search = document.fileName.endsWith(EXT) ||
          document.languageId === "search-result";
        if (!search && !document.fileName) {
          return;
        }
        if (document.fileName === context.workspaceState.get(ADD_TO)) {
          return;
        }
        const args = search ? make_arg2(editor) : [make_arg(editor)];
        if (args.length === 0) {
          return;
        }
        await withAddTo(context, async (editor) => {
          const { document } = editor;
          const lines = getLines(document);
          const tlines = lines.map((x) => x.text);
          const last = lines[lines.length - 1].rangeIncludingLineBreak;
          if (last.isEmpty) {
            tlines.pop();
          }
          const insert = Array.from(g_merge2(tlines, args))
            .sort(cmpf((x) => x[0]));
          const ilines: number[] = [];
          await editor.edit((edit) => {
            let ioffset = 0;
            if (!last.isEmpty && last.isSingleLine) {
              edit.insert(lines[lines.length - 1].range.end, "\n");
            }
            for (const [iline, tline] of insert) {
              if (tline) {
                ilines.push(ioffset + iline);
              }
              edit.insert(new vscode.Position(iline, 0), tline + "\n");
              ++ioffset;
            }
          });
          if (ilines.length) {
            editor.selections = ilines.map((i) => document.lineAt(i).range).map(
              (r) => new vscode.Selection(r.start, r.end),
            );
          }
        });
      },
    ),
  );
}
