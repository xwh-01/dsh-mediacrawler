import assert from 'node:assert/strict'
import test from 'node:test'

import { apply, inject, name } from '../skill-provider.js'

test('registers the packaged MediaCrawler skill', async () => {
  let provider
  const ctx = {
    skills: {
      registerProvider(create) {
        provider = create({
          signal: new AbortController().signal,
          invalidate() {},
        })
      },
    },
  }

  apply(ctx)

  assert.equal(name, 'mediacrawler-skill-provider')
  assert.deepEqual(inject, ['skills'])
  assert.equal(provider.name, 'dsh-mediacrawler')

  const candidates = await provider.list({})
  assert.equal(candidates.length, 1)
  assert.equal(candidates[0].name, 'mediacrawler-collector')
  assert.equal(candidates[0].source, 'bundled')

  const skill = await provider.get(candidates[0], {})
  assert.match(skill.content, /^# MediaCrawler Collector/m)
  assert.doesNotMatch(skill.content, /^---$/m)
  assert.equal(skill.resourceBase.kind, 'directory')
})
