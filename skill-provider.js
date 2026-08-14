import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const PROVIDER_NAME = 'dsh-mediacrawler'
const SKILL_NAME = 'mediacrawler-collector'
const SKILL_DESCRIPTION = 'Use when DeepSeek Harness needs bounded, reproducible collection of posts, creator pages, first-level comments, or nested comments from Xiaohongshu, Douyin, Kuaishou, Bilibili, Weibo, Tieba, or Zhihu through a separately installed MediaCrawler checkout. Prefer ordinary web search for quick facts or a few already-indexed pages.'
const SKILL_URL = new URL('./.dsh/skills/mediacrawler-collector/SKILL.md', import.meta.url)
const SKILL_PATH = fileURLToPath(SKILL_URL)
const RESOURCE_BASE = {
  kind: 'directory',
  path: fileURLToPath(new URL('./.dsh/skills/mediacrawler-collector/', import.meta.url)),
}
const INVOCATION = { modelInvocable: true, userInvocable: true }
const CANDIDATE = {
  name: SKILL_NAME,
  description: SKILL_DESCRIPTION,
  invocation: INVOCATION,
  provider: PROVIDER_NAME,
  source: 'bundled',
  resourceBase: RESOURCE_BASE,
  rank: 600,
  locator: SKILL_URL.href,
  path: SKILL_PATH,
}

function skillBody(markdown) {
  const match = /^---\r?\n[\s\S]*?\r?\n---\r?\n/.exec(markdown)
  if (match === null) {
    throw new Error(`dsh-mediacrawler: ${SKILL_PATH} has no YAML frontmatter`)
  }
  return markdown.slice(match[0].length)
}

const provider = {
  name: PROVIDER_NAME,
  list: () => Promise.resolve([CANDIDATE]),
  async get() {
    return {
      name: CANDIDATE.name,
      description: CANDIDATE.description,
      invocation: CANDIDATE.invocation,
      provider: CANDIDATE.provider,
      source: CANDIDATE.source,
      resourceBase: CANDIDATE.resourceBase,
      path: CANDIDATE.path,
      content: skillBody(await readFile(SKILL_URL, 'utf8')),
    }
  },
}

export const name = 'mediacrawler-skill-provider'
export const inject = ['skills']

export function apply(ctx) {
  ctx.skills.registerProvider(() => provider)
}
