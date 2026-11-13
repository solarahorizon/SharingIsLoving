import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'
import { describe, expect, mock, test } from 'claude-code/testing'
import { COMPACT_AT_TOKENS, FIRING_KEY_PREFIX, IDLE_BEFORE_COMPACT_MS, MAX_TRIES, TICK_MS, toastFor } from '../hooks/register'

const BUILD = { id: 'b1', type: 'shell', status: 'running', description: 'gold build' }
const REVIEW = { id: 'a7', type: 'subagent', status: 'running', description: 'dev review' }

/** The engine beneath the plugin: a context size, and a compact that records its instructions. */
function bottom(on: On, tokens: number, failFirst = 0, stopResult: { block?: string } = {}, skip?: string) {
  const compacts: (string | undefined)[] = []
  let failures = failFirst
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('turn.start', ($, e) => ({ turnId: e.turnId }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens, window: 200_000 }, rateLimits: [] } }))
  on('session.compact', ($, e) => {
    if (failures > 0) {
      failures -= 1
      throw new Error('a turn is running')
    }
    if (skip !== undefined) return { skip }
    compacts.push(e.instructions)
    return { messages: [{ role: 'user' as const, text: 'summary', toolUses: [] }] }
  })
  on('classic.Stop', () => stopResult)
  return compacts
}

/** The mod's store beneath the plugin: records every key it sets. */
function store(on: On) {
  const sets: { key: string; value: unknown }[] = []
  on('store.set', ($, e) => {
    sets.push({ key: e.key, value: e.value })
    return { value: undefined }
  })
  on('ui.toast', () => ({ value: undefined }))
  return sets
}

async function start($: Engine) {
  await $.session.start({ cwd: '/home/u/p', surface: null, isInteractive: true })
}

function stop($: Engine, fields: Record<string, unknown> = {}) {
  return $.classic.Stop({ stop_hook_active: false, background_tasks: [BUILD, REVIEW], ...fields })
}

describe('compacts', () => {
  test('a turn ending with jobs in flight over the line compacts, keeping each job', async ($, on) => {
    const clock = mock.clock(on)
    const compacts = bottom(on, COMPACT_AT_TOKENS)
    await start($)
    await stop($)
    expect(compacts).toEqual([])
    await clock.advance(IDLE_BEFORE_COMPACT_MS)
    expect(compacts).toHaveLength(1)
    expect(compacts[0]).toContain('shell b1: gold build')
    expect(compacts[0]).toContain('subagent a7: dev review')
  })

  test('a turn ending with no job in flight compacts as a wait on the user', async ($, on) => {
    const clock = mock.clock(on)
    const compacts = bottom(on, COMPACT_AT_TOKENS)
    const sets = store(on)
    await start($)
    await stop($, { background_tasks: [] })
    await clock.advance(IDLE_BEFORE_COMPACT_MS - TICK_MS)
    expect(compacts).toEqual([])
    await clock.advance(TICK_MS)
    expect(compacts).toHaveLength(1)
    expect(compacts[0]).toContain('waiting on the user')
    expect(compacts[0]).toContain('word for word')
    expect(compacts[0]).not.toContain('background job')
    expect(sets[0]?.value).toMatchObject({ jobs: 0 })
  })

  test('a turn ending with a cron armed keeps the scheduled wake-up in the summary', async ($, on) => {
    const clock = mock.clock(on)
    const compacts = bottom(on, COMPACT_AT_TOKENS)
    await start($)
    await stop($, { background_tasks: [], session_crons: [{ id: 'c1' }] })
    await clock.advance(IDLE_BEFORE_COMPACT_MS)
    expect(compacts).toHaveLength(1)
    expect(compacts[0]).toContain('scheduled wake-up')
    expect(compacts[0]).not.toContain('waiting on the user.')
  })

  test('a turn ending with jobs and a cron keeps both', async ($, on) => {
    const clock = mock.clock(on)
    const compacts = bottom(on, COMPACT_AT_TOKENS)
    await start($)
    await stop($, { session_crons: [{ id: 'c1' }] })
    await clock.advance(IDLE_BEFORE_COMPACT_MS)
    expect(compacts[0]).toContain('shell b1: gold build')
    expect(compacts[0]).toContain('scheduled wake-up')
  })

  test('the toast names what the session was waiting on', () => {
    expect(toastFor(2, 1)).toBe('Compacted while waiting on 2 background job(s)')
    expect(toastFor(0, 1)).toBe('Compacted while waiting on a scheduled wake-up or you')
    expect(toastFor(0, 0)).toBe('Compacted while waiting on you')
  })

  test('a Stop with no background_tasks field compacts as a wait on the user', async ($, on) => {
    const clock = mock.clock(on)
    const compacts = bottom(on, COMPACT_AT_TOKENS)
    await start($)
    await stop($, { background_tasks: undefined })
    await clock.advance(IDLE_BEFORE_COMPACT_MS)
    expect(compacts).toHaveLength(1)
  })

  test('a user reply inside the idle period cancels a wait on the user', async ($, on) => {
    const clock = mock.clock(on)
    const compacts = bottom(on, COMPACT_AT_TOKENS)
    await start($)
    await stop($, { background_tasks: [] })
    await clock.advance(IDLE_BEFORE_COMPACT_MS - TICK_MS)
    await $.turn.start({ text: '1', turnId: 't2' })
    await clock.advance(IDLE_BEFORE_COMPACT_MS * 2)
    expect(compacts).toEqual([])
  })

  test('a completed compaction is recorded once in the store', async ($, on) => {
    const clock = mock.clock(on)
    bottom(on, COMPACT_AT_TOKENS + 5)
    const sets = store(on)
    await start($)
    await stop($, { session_id: 's1', cwd: '/home/u/p' })
    await clock.advance(IDLE_BEFORE_COMPACT_MS)
    expect(sets).toHaveLength(1)
    expect(sets[0]?.key.startsWith(`${FIRING_KEY_PREFIX}s1:`)).toBe(true)
    expect(sets[0]?.value).toMatchObject({ sessionId: 's1', cwd: '/home/u/p', tokensBefore: COMPACT_AT_TOKENS + 5, jobs: 2 })
  })

  test('a skipped compaction is not recorded', async ($, on) => {
    const clock = mock.clock(on)
    bottom(on, COMPACT_AT_TOKENS, 0, {}, 'blocked by a PreCompact hook')
    const sets = store(on)
    await start($)
    await stop($)
    await clock.advance(IDLE_BEFORE_COMPACT_MS)
    expect(sets).toEqual([])
  })

  test('a refused compact is tried again, at most MAX_TRIES times', async ($, on) => {
    const clock = mock.clock(on)
    const compacts = bottom(on, COMPACT_AT_TOKENS, MAX_TRIES - 1)
    await start($)
    await stop($)
    await clock.advance(IDLE_BEFORE_COMPACT_MS)
    for (let i = 1; i < MAX_TRIES; i++) await clock.advance(TICK_MS)
    expect(compacts).toHaveLength(1)
  })

  test('gives up after MAX_TRIES refusals', async ($, on) => {
    const clock = mock.clock(on)
    const compacts = bottom(on, COMPACT_AT_TOKENS, MAX_TRIES)
    await start($)
    await stop($)
    await clock.advance(IDLE_BEFORE_COMPACT_MS)
    for (let i = 0; i < MAX_TRIES + 2; i++) await clock.advance(TICK_MS)
    expect(compacts).toEqual([])
  })

  test('a subagent turn starting does not cancel it', async ($, on) => {
    const clock = mock.clock(on)
    const compacts = bottom(on, COMPACT_AT_TOKENS)
    await start($)
    await stop($)
    await $.turn.start({ text: '', turnId: 't2', agentId: 'a7' })
    await clock.advance(IDLE_BEFORE_COMPACT_MS)
    expect(compacts).toHaveLength(1)
  })
})

describe('leaves the conversation alone', () => {
  test('when the context is under the line', async ($, on) => {
    const clock = mock.clock(on)
    const compacts = bottom(on, COMPACT_AT_TOKENS - 1)
    await start($)
    await stop($)
    await clock.advance(IDLE_BEFORE_COMPACT_MS * 2)
    expect(compacts).toEqual([])
  })

  test('while the idle period has not yet passed', async ($, on) => {
    const clock = mock.clock(on)
    const compacts = bottom(on, COMPACT_AT_TOKENS)
    await start($)
    await stop($)
    await clock.advance(IDLE_BEFORE_COMPACT_MS - TICK_MS)
    expect(compacts).toEqual([])
    await clock.advance(TICK_MS)
    expect(compacts).toHaveLength(1)
  })

  test('when a main-loop turn starts inside the idle period', async ($, on) => {
    const clock = mock.clock(on)
    const compacts = bottom(on, COMPACT_AT_TOKENS)
    await start($)
    await stop($)
    await clock.advance(IDLE_BEFORE_COMPACT_MS - TICK_MS)
    await $.turn.start({ text: 'job done', turnId: 't2' })
    await clock.advance(IDLE_BEFORE_COMPACT_MS * 2)
    expect(compacts).toEqual([])
  })

  test('when a main-loop turn starts between retries', async ($, on) => {
    const clock = mock.clock(on)
    const compacts = bottom(on, COMPACT_AT_TOKENS, 1)
    await start($)
    await stop($)
    await clock.advance(IDLE_BEFORE_COMPACT_MS)
    await $.turn.start({ text: '', turnId: 't2' })
    await clock.advance(IDLE_BEFORE_COMPACT_MS * 2)
    expect(compacts).toEqual([])
  })

  test('when another hook blocks the stop, so the turn goes on', async ($, on) => {
    const clock = mock.clock(on)
    const compacts = bottom(on, COMPACT_AT_TOKENS, 0, { block: 'keep going' })
    await start($)
    await stop($)
    await clock.advance(IDLE_BEFORE_COMPACT_MS * 2)
    expect(compacts).toEqual([])
  })

  test('when the Stop is a subagent loop or a continuing stop', async ($, on) => {
    const clock = mock.clock(on)
    const compacts = bottom(on, COMPACT_AT_TOKENS)
    await start($)
    await stop($, { agent_id: 'a7' })
    await stop($, { stop_hook_active: true })
    await clock.advance(IDLE_BEFORE_COMPACT_MS * 2)
    expect(compacts).toEqual([])
  })
})
