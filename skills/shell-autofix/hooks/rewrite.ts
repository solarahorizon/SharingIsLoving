/**
 * Pure planning for shell-autofix: turns a Bash command the shell-discipline
 * hook would deny into one allowed command that the shell runs the same way.
 * Only text rewrites are planned; pipes are never removed, so output is never
 * filtered in code. `choose` returns undefined otherwise; the caller then passes
 * the call through untouched and the hook decides.
 *
 * The lexer is an allowlist: it accepts only characters whose meaning is the same
 * under every zsh option, and refuses the whole command on anything else. The
 * output is rebuilt from its tokens, so what was checked is what runs.
 */

/** One Bash call to make in place of the original, and what was changed. */
export type Choice = {
  command: string
  notes: string[]
}

type Op = '&&' | '||' | '|' | ';' | '\n'
// `raw` is the source text; `quoted` is true when any part of a word was quoted.
type Token =
  | { kind: 'word'; raw: string; value: string; quoted: boolean }
  | { kind: 'dup' }
  | { kind: 'devnull' }
  | { kind: 'redir'; raw: string }
type Step = { tokens: Token[]; op: Op | '' }

// Unquoted characters that expand nothing under any zsh option; `=` and `~` have extra position rules.
const SAFE = /^[A-Za-z0-9_.\/:@%+,=~-]$/
// The redirect target must end at a token boundary: `2>/dev/null.bak` names another file.
const RE_DEVNULL = /^2>[ \t]*\/dev\/null(?=$|[ \t\n;&|])/
const RE_DUP = /^2>&1(?=$|[ \t\n;&|])/
// Standard output or input to or from a named file. Any other stderr redirect, `>&`, `&>`, `>|`,
// `<>`, heredocs and process substitution fall through to `lexWord`, which refuses them.
const RE_REDIR = /^(?:1?>>?|0?<)(?![<>&|(!])/
// A diagnostic print of the exit status and nothing else, as the last step.
const RE_ECHO_EXIT = /[;\n][ \t]*echo[ \t]+(?:\$\?|"[\w :=-]*\$\?[\w :=-]*")[ \t]*$/
// A step starting with one of these is part of a compound command or changes how the next word runs.
const RESERVED = new Set([
  'if', 'then', 'else', 'elif', 'fi', 'for', 'while', 'until', 'do', 'done', 'case', 'esac', 'select',
  'function', 'repeat', 'time', 'coproc', 'foreach', 'end', 'nocorrect', 'noglob',
])
// zsh `cd` removes `..` from the text while `-C` follows symlinks first, so the folders differ.
const RE_DOT_SEGMENT = /(?:^|\/)\.\.?(?:\/|$)/

/**
 * Splits into steps at top-level `&&`, `||`, `|`, `;` and newline, and types each
 * token. Undefined for any character outside the allowlist, an unbalanced quote,
 * or an empty step the shell would reject.
 */
function lex(cmd: string): Step[] | undefined {
  const steps: Step[] = []
  let tokens: Token[] = []
  const end = (op: Op | '') => {
    steps.push({ tokens, op })
    tokens = []
  }
  let i = 0
  while (i < cmd.length) {
    const c = cmd[i]!
    if (c === ' ' || c === '\t') {
      i++
      continue
    }
    const two = cmd.slice(i, i + 2)
    if (two === '&&' || two === '||') {
      end(two)
      i += 2
      continue
    }
    if (c === '|' || c === ';' || c === '\n') {
      // `|&` pipes stderr too; `;;`, `;&` and `;|` are case terminators.
      if (c !== '\n' && /^[&|;]$/.test(cmd[i + 1] ?? '') && two !== '||') return undefined
      // A newline after `&&`, `||` or `|` continues the command; it is not a separator.
      const prev = steps[steps.length - 1]
      if (c === '\n' && tokens.length === 0 && prev && ['&&', '||', '|'].includes(prev.op)) {
        i++
        continue
      }
      end(c)
      i++
      continue
    }
    const rest = cmd.slice(i)
    const devnull = RE_DEVNULL.exec(rest)
    if (devnull) {
      tokens.push({ kind: 'devnull' })
      i += devnull[0].length
      continue
    }
    if (RE_DUP.test(rest)) {
      tokens.push({ kind: 'dup' })
      i += 4
      continue
    }
    const redir = RE_REDIR.exec(rest)
    if (redir) {
      let j = i + redir[0].length
      while (cmd[j] === ' ' || cmd[j] === '\t') j++
      const target = lexWord(cmd, j)
      if (!target || target.token.kind !== 'word') return undefined
      tokens.push({ kind: 'redir', raw: `${redir[0]} ${target.token.raw}` })
      i = target.next
      continue
    }
    const word = lexWord(cmd, i)
    if (!word) return undefined
    tokens.push(word.token)
    i = word.next
  }
  end('')
  // A blank line is allowed; any other empty step is a syntax error or runs a null command.
  const out: Step[] = []
  for (const [n, s] of steps.entries()) {
    // A step of redirects alone runs zsh's NULLCMD.
    if (s.tokens.length > 0 && !s.tokens.some(t => t.kind === 'word')) return undefined
    if (s.tokens.length > 0) {
      out.push(s)
      continue
    }
    const last = n === steps.length - 1
    const before = out[out.length - 1]
    if (s.op === '\n' && (!before || before.op === ';' || before.op === '\n')) continue
    if (last && before && (before.op === ';' || before.op === '\n')) continue
    if (last && !before) continue
    return undefined
  }
  return out.length > 0 ? out : undefined
}

/** One word starting at `start`, or undefined if it holds anything outside the allowlist. */
function lexWord(cmd: string, start: number): { token: Token; next: number } | undefined {
  let value = ''
  let quoted = false
  let i = start
  let prevUnquoted = ''
  while (i < cmd.length) {
    const c = cmd[i]!
    if (c === ' ' || c === '\t' || c === '\n' || c === ';' || c === '|' || c === '&') {
      // Reached only by a lone `&`, which backgrounds the step before it.
      if (i === start) return undefined
      break
    }
    if (c === "'") {
      const close = cmd.indexOf("'", i + 1)
      if (close < 0) return undefined
      value += cmd.slice(i + 1, close)
      quoted = true
      prevUnquoted = ''
      i = close + 1
      continue
    }
    if (c === '"') {
      i++
      for (;;) {
        const q = cmd[i]
        if (q === undefined) return undefined
        i++
        if (q === '"') break
        // After a backslash `"` does not close the quote, and `$` and backtick expand nothing.
        if (q === '\\') {
          const n = cmd[i]
          if (n === undefined) return undefined
          value += '$`"\\\n'.includes(n) ? n : q + n
          i++
          continue
        }
        // Inside double quotes `$` and backtick expand, and `!` can trigger history expansion.
        if (q === '$' || q === '`' || q === '!') return undefined
        value += q
      }
      quoted = true
      prevUnquoted = ''
      continue
    }
    if (!SAFE.test(c)) return undefined
    const atStart = i === start
    // `=word` is EQUALS expansion; after `=` or `:` zsh's magicequalsubst expands `=` and `~`.
    if ((c === '=' || c === '~') && (atStart || prevUnquoted === '' || prevUnquoted === '=' || prevUnquoted === ':')) {
      return undefined
    }
    value += c
    prevUnquoted = c
    i++
  }
  if (i === start) return undefined
  return { token: { kind: 'word', raw: cmd.slice(start, i), value, quoted }, next: i }
}

function render(steps: Step[]): string {
  return steps
    .map(s => {
      const text = s.tokens
        .map(t => (t.kind === 'word' || t.kind === 'redir' ? t.raw : t.kind === 'dup' ? '2>&1' : ''))
        .filter(Boolean)
        .join(' ')
      return text + (s.op === '' ? '' : s.op === '\n' ? '\n' : ` ${s.op} `)
    })
    .join('')
    .trim()
}

const words = (s: Step) => s.tokens.filter((t): t is Extract<Token, { kind: 'word' }> => t.kind === 'word')

/**
 * A git step `-C` can move: it starts with a bare `git`, sets no `-C` of its own, and
 * opens no file, since a redirect target would resolve in the caller's folder.
 */
function movableGit(s: Step): boolean {
  const w = words(s)
  return (
    w.length >= 2 &&
    s.tokens[0] === w[0] &&
    w[0]!.raw === 'git' &&
    !w.some(t => t.value === '-C') &&
    !s.tokens.some(t => t.kind === 'redir')
  )
}

/** The fix for a command; undefined when no rewrite is both needed and the same by construction. */
export function choose(command: string): Choice | undefined {
  const notes: string[] = []
  let source = command
  // Only a final `echo $?` is dropped: one followed by `&&` / `||` decides what runs next.
  // The call then exits with the command's own status, the value the echo would have printed.
  const echo = RE_ECHO_EXIT.exec(command)
  // The separator stays in the lexed text so that `a;; echo $?` is still refused as `;;`.
  if (echo) source = command.slice(0, echo.index + 1)
  const lexed = lex(source)
  if (!lexed) return undefined
  if (lexed.some(s => RESERVED.has(words(s)[0]?.raw ?? ''))) return undefined
  let steps = lexed
  if (echo) {
    steps = [...steps.slice(0, -1), { ...steps[steps.length - 1]!, op: '' }]
    notes.push('dropped the `echo $?` step (the Bash result already carries the exit code)')
  }

  // `2>&1 2>/dev/null` silences stderr; dropping the second would send it into stdout.
  if (steps.some(s => s.tokens.some(t => t.kind === 'devnull') && s.tokens.some(t => t.kind === 'dup'))) {
    return undefined
  }
  if (steps.some(s => s.tokens.some(t => t.kind === 'devnull'))) {
    notes.push('dropped `2>/dev/null`')
    steps = steps.map(s => ({ ...s, tokens: s.tokens.filter(t => t.kind !== 'devnull') }))
  }

  const first = steps[0]!
  const cd = first.tokens.length === 2 ? words(first) : []
  const target = cd[1]
  const git = steps[1]
  if (
    cd.length === 2 &&
    target &&
    cd[0]!.raw === 'cd' &&
    !target.quoted &&
    target.raw.startsWith('/') &&
    !RE_DOT_SEGMENT.test(target.raw) &&
    first.op === '&&' &&
    // One git step only: the shell keeps the folder it entered, while each `-C` looks the path
    // up again, so a step that moves or removes the folder would change what a later step sees.
    steps.length === 2 &&
    git !== undefined &&
    movableGit(git)
  ) {
    const dir: Token = { kind: 'word', raw: target.raw, value: target.value, quoted: false }
    const flag: Token = { kind: 'word', raw: '-C', value: '-C', quoted: false }
    steps = [{ ...git, tokens: [git.tokens[0]!, flag, dir, ...git.tokens.slice(1)] }]
    notes.push(`turned \`cd ${target.raw} && git\` into \`git -C ${target.raw}\``)
  }

  if (notes.length === 0) return undefined
  return { command: render(steps), notes }
}
