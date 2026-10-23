import { describe, expect, test } from 'claude-code/testing'
import { choose } from '../hooks/rewrite'

describe('rewritten', () => {
  test('cd && git', () => {
    expect(choose('cd /r/worktrees/wt && git log --oneline -5')?.command).toBe('git -C /r/worktrees/wt log --oneline -5')
  })

  test('git words that expand nothing in the shell folder', () => {
    expect(choose('cd /r && git diff HEAD~1 --stat')?.command).toBe('git -C /r diff HEAD~1 --stat')
    expect(choose("cd /r && git log --format='%h %s' -3")?.command).toBe("git -C /r log --format='%h %s' -3")
    expect(choose('cd /r && git push origin wt 2>&1')?.command).toBe('git -C /r push origin wt 2>&1')
    expect(choose('cd /r/.hidden && git status')?.command).toBe('git -C /r/.hidden status')
  })

  test('drops 2>/dev/null', () => {
    expect(choose('ls -la /r/build/.lock 2>/dev/null')?.command).toBe('ls -la /r/build/.lock')
    expect(choose('ls /r 2> /dev/null; ls /s')?.command).toBe('ls /r ; ls /s')
    expect(choose('ls /r 2>/dev/null;')?.command).toBe('ls /r ;')
  })

  test('drops a final echo $? step', () => {
    expect(choose('git -C /r log --oneline -3; echo "EXIT=$?"')?.command).toBe('git -C /r log --oneline -3')
    expect(choose('ls /r\necho $?')?.command).toBe('ls /r')
  })

  test('a rewrite keeps every pipe', () => {
    expect(choose('ls /r 2>/dev/null | head -3')?.command).toBe('ls /r | head -3')
  })

  test('layout the shell ignores', () => {
    expect(choose('ls /r 2>/dev/null\n\nls /s')?.command).toBe('ls /r\nls /s')
    expect(choose('cd /r &&\n  git status')?.command).toBe('git -C /r status')
    expect(choose('cd /r\t&&\tgit status')?.command).toBe('git -C /r status')
    expect(choose('cd /r 2>/dev/null && git status')?.command).toBe('git -C /r status')
  })

  test('quoted text is kept byte for byte', () => {
    expect(choose('cd /r && git commit -m "café: fix  spacing"')?.command).toBe('git -C /r commit -m "café: fix  spacing"')
    expect(choose("cd /r && git log --grep='a$b*' -1")?.command).toBe("git -C /r log --grep='a$b*' -1")
    expect(choose('cd /r && git log --author=dev@example.com -1')?.command).toBe('git -C /r log --author=dev@example.com -1')
    expect(choose('cd /r && git commit -m "say \\"hi\\" for \\$5 \\`x\\`"')?.command).toBe(
      'git -C /r commit -m "say \\"hi\\" for \\$5 \\`x\\`"',
    )
  })

  test('a step that writes a file keeps its redirect', () => {
    expect(choose('python3 /r/t.py > /r/log 2>&1; echo "exit=$?"')?.command).toBe('python3 /r/t.py > /r/log 2>&1')
    expect(choose('ls /r >>/r/out 2>/dev/null')?.command).toBe('ls /r >> /r/out')
    expect(choose('wc -l </r/in 2>/dev/null')?.command).toBe('wc -l < /r/in')
    expect(choose('python3 /r/c.py 1>/dev/null; echo $?')?.command).toBe('python3 /r/c.py 1> /dev/null')
  })
})

describe('left alone', () => {
  for (const cmd of [
    'git -C /r status',
    'echo $(date)',
    'ls `pwd`',
    "python3 - <<'PY'\nprint(1)\nPY",
    'grep -n "2>/dev/null" /r/file',
    'ls /r | head -3',
    // A longer redirect target is another file, not /dev/null.
    'rm -f /tmp/x 2>/dev/null.bak',
    'ls /r 2>/dev/nullx',
    // An echo that writes a file or prints more than the status is a real step.
    'make; echo $? > /tmp/exit-code',
    'make; echo "$?" >> /r/log',
    'make; echo $? $HOME',
    'make; printf "%s" $?',
    'false; echo $? || rm /r/file',
    // A shell redirect, glob or variable in a git step resolves in the caller's folder after `-C`.
    'cd /repo && git diff > patch.txt',
    'cd /repo && git apply < fix.patch',
    'cd /repo && git add *.swift',
    'cd /repo && git log $REF',
    'cd /repo && git status 2>&1 | head -5',
    'cd /repo && git add ~+/file',
    'cd /repo && git diff ~-/a',
    'cd /repo && git log --output=~+/x',
    // Under zsh's extendedglob, `#` and `^` glob in the shell's folder.
    'cd /repo && git log -1 a#',
    'cd /repo && git log HEAD^',
    // `${...}` may hold `;` or `|` that are not operators.
    'ls ${x:-a;b} 2>/dev/null',
    // An escaped space before a separator would be trimmed away.
    'printf "%s" foo\\ ; echo $?',
    // `cd` does not carry between calls in a subagent, so a cd chain is never split.
    'cd /r/wt && grep -n foo CLAUDE.md',
    'cd /r/wt && git status && rm -rf build',
    'cd - && git status',
    'cd wt && git status',
    'cd ~/r && git status',
    'cd "/a b" && git status',
    'cd /missing && git fetch; git status',
    'cd /r && git -C sub status',
    // The shell keeps the folder it entered; a second `-C` would look the path up again.
    'cd /r && git fetch origin && git status --short',
    'cd /r/wt && git worktree move /r/wt /r/wt2 && git status --short',
    // zsh `cd` drops `..` from the text; `-C` resolves symlinks first, so the folders differ.
    'cd /r/lnk/.. && git rev-parse --show-toplevel',
    'cd /tmp/.. && git status',
    'cd /r/./wt && git status',
    // `-C` goes after a bare `git `; a quoted or escaped git, or git with no arguments, has none.
    'cd /r && \\git rev-parse --show-toplevel',
    'cd /r && "git" status',
    'cd /r && git',
    // An escaped space or `$'...'` quoting makes `2>/dev/null` part of a word.
    'touch /w/a\\ 2>/dev/null /w/b',
    "touch $'/w/q\\' 2>/dev/null ''\\'",
    // An empty command is a syntax error; the original runs nothing.
    'ls 2>/dev/null;; echo hi',
    '; ls /r 2>/dev/null',
    'ls /r 2>/dev/null &&',
    // zsh EQUALS: `=cmd` is a PATH lookup, folder-dependent with a relative PATH entry.
    'cd /r && git log =git',
    // magicequalsubst expands `=` and `~` after `=` or `:`.
    'cd /r && git log --x==git',
    'cd /r && git log a:=git',
    "cd /r && git log 'a'=b",
    // Background, stderr pipes and case terminators.
    'ls /r 2>/dev/null &',
    'ls /r 2>/dev/null & ls /s',
    'ls /r 2>/dev/null |& cat',
    'ls /r 2>/dev/null ;& ls',
    'ls /r 2>/dev/null ;| ls',
    // `2>&1 2>/dev/null` silences stderr; dropping the second would merge it into stdout.
    'ls /r 2>&1 2>/dev/null | cat',
    // A step of redirects alone runs NULLCMD.
    'ls /r; 2>/dev/null',
    'ls /r 2>/dev/null; 2>&1',
    // `-C` must follow the git word itself.
    'cd /r && 2>&1 git status',
    'cd /r 2>&1 && git status',
    // Anything outside the allowlist, unquoted or in double quotes.
    'cd /r && git log café',
    'cd /r && git log "$HOME"',
    'cd /r && git commit -m "fix!"',
    'cd /r && git log {a,b}',
    'cd /r && git log a!b',
    "cd /r && git log 'unterminated",
    // Redirects other than plain stdout/stdin to a named file.
    'ls /r 2>/r/err; echo $?',
    'ls /r >&2 2>/dev/null',
    'ls /r &>/r/out; echo $?',
    'ls /r >| /r/out 2>/dev/null',
    'ls /r >! /r/out 2>/dev/null',
    'cat <> /r/f 2>/dev/null',
    'diff <(ls /a) /b 2>/dev/null',
    'ls /r > 2>/dev/null',
    'ls /r >; echo $?',
    'ls /r >',
    'ls /r > $OUT 2>/dev/null',
    'ls /r > ~/out 2>/dev/null',
    'ls /r 1>&2 2>/dev/null',
    // A redirect in a moved git step would open the file in the caller's folder.
    'cd /r && git diff >> patch.txt',
    'cd /r && git diff 1>patch.txt',
    // A syntax error before the final echo stays an error.
    'ls /r;; echo $?',
    'ls /r && ; echo $?',
    // Precommand words and control flow are never cut apart.
    'cd /r && time git status',
    'noglob ls /r 2>/dev/null',
    'repeat 3 ls /r 2>/dev/null',
    '{ ls /r 2>/dev/null; }',
    '[[ -f /r ]] 2>/dev/null',
    'if git -C /r diff --quiet; then\n  echo clean\nelse\n  git -C /r stash\nfi',
    'if true; then git -C /r log; echo $?; fi',
    'until [ -f /r/x ]; do sleep 5; done',
  ]) {
    test(JSON.stringify(cmd), () => {
      expect(choose(cmd)).toBe(undefined)
    })
  }
})

describe('in the engine', () => {
  test('runs the fixed command and adds a note', async ($, on) => {
    const seen: string[] = []
    on('tool.call', { tool: 'Bash' }, async (_$, e) => {
      seen.push(e.command)
      return { result: { stdout: 'l1\nl2\n', stderr: '', interrupted: false } }
    })
    const r = await $.tool.call({ tool: 'Bash', command: 'cd /wt && git log' })
    expect(seen).toEqual(['git -C /wt log'])
    expect((r.result as { stdout?: string } | undefined)?.stdout).toBe('l1\nl2\n')
    expect(String(r.context?.[r.context.length - 1])).toContain('git -C /wt log')
  })

  test('a background command is rewritten the same way', async ($, on) => {
    const seen: string[] = []
    on('tool.call', { tool: 'Bash' }, async (_$, e) => {
      seen.push(e.command)
      return { result: { stdout: '', stderr: '', interrupted: false } }
    })
    await $.tool.call({ tool: 'Bash', command: 'cd /wt && git fetch', run_in_background: true })
    expect(seen).toEqual(['git -C /wt fetch'])
  })

  test('a rewrite the settings hook still denies is reported as sent, not run', async ($, on) => {
    on('classic.PreToolUse', async () => ({ deny: 'BLOCKED by the deny hook' }))
    const r = await $.tool.call({ tool: 'Bash', command: 'ls /r 2>/dev/null | head -3' })
    expect(r.isError).toBe(true)
    const note = String(r.context?.[r.context.length - 1])
    expect(note).toContain('sent `ls /r | head -3`')
    expect(note).not.toContain(' ran ')
  })

  test('passes an unfixable command through unchanged', async ($, on) => {
    const seen: string[] = []
    on('tool.call', { tool: 'Bash' }, async (_$, e) => {
      seen.push(e.command)
      return { result: { stdout: '', stderr: '', interrupted: false } }
    })
    await $.tool.call({ tool: 'Bash', command: 'echo $(date)' })
    expect(seen).toEqual(['echo $(date)'])
  })
})
