import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const PROVIDER_NAME = 'dsh-mediacrawler'
const SKILL_NAME = 'mediacrawler-collector'
const SKILL_URL = new URL('./.dsh/skills/mediacrawler-collector/SKILL.md', import.meta.url)
const SKILL_PATH = fileURLToPath(SKILL_URL)
const RESOURCE_BASE = {
  kind: 'directory',
  path: fileURLToPath(new URL('./.dsh/skills/mediacrawler-collector/', import.meta.url)),
}
const INVOCATION = { modelInvocable: true, userInvocable: true }
const CANDIDATE = {
  name: SKILL_NAME,
  invocation: INVOCATION,
  provider: PROVIDER_NAME,
  source: 'bundled',
  resourceBase: RESOURCE_BASE,
  rank: 600,
  locator: SKILL_URL.href,
  path: SKILL_PATH,
}

function parseSkill(markdown) {
  const match = /^---\r?\n[\s\S]*?\r?\n---\r?\n/.exec(markdown)
  if (match === null) {
    throw new Error(`dsh-mediacrawler: ${SKILL_PATH} has no YAML frontmatter`)
  }
  const descriptionMatch = /^description:\s*(.+)$/m.exec(match[0])
  if (descriptionMatch === null) {
    throw new Error(`dsh-mediacrawler: ${SKILL_PATH} has no description`)
  }
  return {
    description: descriptionMatch[1].trim(),
    content: markdown.slice(match[0].length),
  }
}

let documentPromise
function loadSkill() {
  documentPromise ??= readFile(SKILL_URL, 'utf8').then(parseSkill)
  return documentPromise
}

const provider = {
  name: PROVIDER_NAME,
  async list() {
    const document = await loadSkill()
    return [{ ...CANDIDATE, description: document.description }]
  },
  async get() {
    const document = await loadSkill()
    return {
      name: CANDIDATE.name,
      description: document.description,
      invocation: CANDIDATE.invocation,
      provider: CANDIDATE.provider,
      source: CANDIDATE.source,
      resourceBase: CANDIDATE.resourceBase,
      path: CANDIDATE.path,
      content: document.content,
    }
  },
}

export const name = 'mediacrawler-skill-provider'
export const inject = ['skills']

export function apply(ctx) {
  ctx.skills.registerProvider(() => provider)
}
