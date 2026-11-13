/**
 * wait-compact: compacts the main conversation while it waits, on background work or on the user.
 *
 * When a main-loop turn ends (classic Stop) with the context at or over COMPACT_AT_TOKENS,
 * it waits IDLE_BEFORE_COMPACT_MS and then compacts, telling the summary to keep any
 * open question and, when background jobs are in flight, every running job and what follows it.
 * Any main-loop turn that starts first (the person typed, a job reported) cancels it,
 * so a wait that ends inside the idle period leaves the conversation alone.
 * Each compaction it completes is kept in the mod's store (FIRING_KEY_PREFIX), one key
 * per firing, so firings can be counted across sessions.
 */
import type { Register } from 'claude-code'

export const COMPACT_AT_TOKENS = 120_000
// The compact call is refused while a turn runs, and Stop fires just before the turn ends.
export const TICK_MS = 1_000
export const MAX_TRIES = 5
// Short waits cost more to compact than they save; under 5 minutes so compaction still reads a cached conversation.
export const IDLE_BEFORE_COMPACT_MS = 240_000
export const FIRING_KEY_PREFIX = 'firing:'

export type Job = { id: string; type: string; description: string }

/**
 * The summary instructions: keep the plan, each running job by id, any scheduled wake-up, and any open question.
 * `crons` is the count of session crons (CronCreate, ScheduleWakeup, /loop) still armed; 0 when none.
 */
export function instructionsFor(jobs: readonly Job[], crons = 0): string {
  const cronLine = crons > 0 ? ['- every scheduled wake-up (cron, wakeup or loop) still armed, and what to do when it fires;'] : []
  if (jobs.length === 0) {
    return [
      crons > 0 ? 'This session is waiting on a scheduled wake-up or the user. Keep, in full:' : 'This session is waiting on the user. Keep, in full:',
      '- the task in progress, its plan, and the step that comes after the user answers;',
      ...cronLine,
      '- any question put to the user that is still unanswered, word for word, with the options offered.',
    ].join('\n')
  }
  return [
    'This session is waiting on background work. Keep, in full:',
    '- the task in progress, its plan, and the step that comes after each job below ends;',
    '- every background job still running, by id, and what to do with its result:',
    ...jobs.map(j => `  - ${j.type} ${j.id}: ${j.description}`),
    ...cronLine,
    '- any question put to the user that is still unanswered, word for word.',
  ].join('\n')
}

/** The toast shown after a compaction, naming what the session was waiting on. */
export function toastFor(jobs: number, crons: number): string {
  if (jobs > 0) return `Compacted while waiting on ${jobs} background job(s)`
  if (crons > 0) return 'Compacted while waiting on a scheduled wake-up or you'
  return 'Compacted while waiting on you'
}

/** One completed compaction; `tokensBefore` is the context size when the turn ended. */
export type Firing = { at: string; sessionId: string; cwd: string; tokensBefore: number; jobs: number }

type Wanted = { jobs: readonly Job[]; crons: number; armedAt: number; idleTicks: number; tries: number; sessionId: string; cwd: string; tokensBefore: number }

export const register: Register = on => {
  let mainTurnsStarted = 0
  let wanted: Wanted | undefined
  let isCompacting = false

  // The timer starts here because a Stop dispatch ends before its turn does.
  on('session.start', async ($, e, next) => {
    $.clock.every(TICK_MS, () => {
      const want = wanted
      if (want === undefined || isCompacting) return
      if (want.armedAt !== mainTurnsStarted || want.tries >= MAX_TRIES) {
        wanted = undefined
        return
      }
      want.idleTicks += 1
      if (want.idleTicks * TICK_MS < IDLE_BEFORE_COMPACT_MS) return
      want.tries += 1
      isCompacting = true
      $.session.compact({ instructions: instructionsFor(want.jobs, want.crons) }).then(
        async done => {
          if (wanted === want) wanted = undefined
          if (done.skip !== undefined) return
          $.ui.toast(toastFor(want.jobs.length, want.crons))
          const now = await $.clock.now()
          const firing: Firing = {
            at: new Date(now).toISOString(),
            sessionId: want.sessionId,
            cwd: want.cwd,
            tokensBefore: want.tokensBefore,
            jobs: want.jobs.length,
          }
          await $.store.set(`${FIRING_KEY_PREFIX}${want.sessionId}:${now}`, firing)
        },
        () => undefined,
      ).catch(() => undefined).finally(() => {
        isCompacting = false
      })
    })
    return next(e)
  })

  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined) {
      mainTurnsStarted += 1
      wanted = undefined
    }
    return next(e)
  })

  on('classic.Stop', async ($, e, next) => {
    const result = await next(e)
    if (e.agent_id !== undefined || e.stop_hook_active || result.block !== undefined) return result
    const jobs = e.background_tasks ?? []
    const { context } = await $.session.usage()
    const tokens = context.tokens ?? 0
    if (tokens < COMPACT_AT_TOKENS) return result
    const crons = e.session_crons?.length ?? 0
    wanted = { jobs, crons, armedAt: mainTurnsStarted, idleTicks: 0, tries: 0, sessionId: e.session_id, cwd: e.cwd, tokensBefore: tokens }
    return result
  })
}
