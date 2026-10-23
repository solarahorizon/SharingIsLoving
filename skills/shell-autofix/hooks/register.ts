/**
 * shell-autofix: rewrites Bash commands into the forms the shell-discipline
 * PreToolUse hook allows, then sends them on. Plugin `tool.call` hooks run above
 * settings PreToolUse hooks, so that hook still judges every rewritten command
 * and denies what is left.
 */
import type { Register } from 'claude-code'
import { choose } from './rewrite'

export const register: Register = on => {
  let rewritten = 0

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const choice = choose(e.command)
    if (!choice) return next(e)
    const ran = await next({ ...e, command: choice.command })
    if (ran.deny !== undefined) return ran
    // A settings-hook denial arrives as an error result like a failed command, so the
    // note says what was sent, never that it ran.
    $.ui.status(`${++rewritten} rewritten`)
    const note = `shell-autofix sent \`${choice.command}\` in place of \`${e.command}\`: ${choice.notes.join('; ')}.`
    return { ...ran, context: [...(ran.context ?? []), note] }
  })
}
