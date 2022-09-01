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

type Arg = [string, [number, string][]];
function make_arg(editor: vscode.TextEditor): Arg {
  const { document } = editor;
  const ilines = new Set<number>();
  for (const sel of editor.selections) {
    for (let line = sel.start.line; line <= sel.end.line; ++line) {
      ilines.add(line);
    }
  }
  return [
    document.fileName,
    Array.from(ilines).sort(cmp).map((iline) => document.lineAt(iline)).map(
      (line) => [line.lineNumber, line.text],
    ),
  ];
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
type _Group = [number, [number, string]];
type Group = [number, _Group[]];
function* g_files(
  lines: string[],
): Generator<[string, Group]> {
  let i = 0;
  for (const line of lines) {
    const m = line.match(RE_FILE);
    if (m) {
      yield [m[1], [i, Array.from(g_lines(lines, i + 1))]];
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
      yield [i + 1, `${`${j + 1}`.padStart(5)}: ${s}`];
      ++mm;
    }
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
        if (!document.fileName) {
          return;
        }
        if (document.fileName === context.workspaceState.get(ADD_TO)) {
          return;
        }
        const arg = make_arg(editor);
        await withAddTo(context, async (editor) => {
          const { document } = editor;
          const lines = getLines(document);
          const tlines = lines.map((x) => x.text);
          const last = lines[lines.length - 1].rangeIncludingLineBreak;
          if (last.isEmpty) {
            tlines.pop();
          }
          const insert = Array.from(g_merge(tlines, arg))
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
