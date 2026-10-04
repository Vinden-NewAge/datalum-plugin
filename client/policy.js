'use strict';
// Política común de los controles del cliente para Datalum.
//
// Todo aquí es función pura sobre el estado de la sesión: no lee disco, no llama a la
// red y no conoce el formato de ninguna aplicación. El adaptador de cada aplicación
// traduce sus eventos a estas funciones y sus respuestas al formato de la aplicación.
//
// La política sólo hace cumplir lo que el contrato de Datalum ya dice. No decide qué
// agente usar, qué herramienta resuelve un encargo ni qué se guarda en memoria: eso
// es del cerebro del agente y de la persona.

const crypto = require('crypto');

const MAX_ITEMS = 40;
const MAX_FAILURES = 3;
const FAILURE_WINDOW_MS = 10 * 60 * 1000;
const WRITE_WINDOW_MS = 30 * 60 * 1000;
const MEMORY_WRITES = new Set(['remember', 'brain_write', 'forget']);
const MEMORY_READS = new Set(['list_memories', 'brain_read', 'brain_index']);
const START_TOOLS = new Set(['list_agents', 'use_agent', 'release_agent']);

function newState(pluginVersion) {
  return {
    v: 1,
    plugin_version: pluginVersion || null,
    server: null,
    seal: null,
    seal_state: 'none', // none | sealed | expired | conflict
    newer_version: null,
    retired: [],
    reads: {},
    listings: {},
    previews: {},
    writes: {},
    failures: {},
  };
}

// ── Reconocer las herramientas de Datalum ───────────────────────────────────────
function parseToolName(toolName) {
  const m = /^mcp__(.+)__([A-Za-z0-9_]+)$/.exec(toolName || '');
  return m ? { server: m[1], tool: m[2] } : null;
}

function isDatalum(state, toolName) {
  const parsed = parseToolName(toolName);
  if (!parsed) return null;
  if (/datalum/i.test(parsed.server) || parsed.server === state.server) return parsed;
  // Un conector con otro nombre se reconoce por sus herramientas de arranque y se
  // confirma cuando contesta con la forma de Datalum (ver learnServer).
  return START_TOOLS.has(parsed.tool) ? parsed : null;
}

// ── Utilidades ──────────────────────────────────────────────────────────────────
function normalize(text) {
  return String(text || '')
    .normalize('NFC')
    .replace(/[«»“”"'‘’]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

function stable(value) {
  if (Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
  if (value && typeof value === 'object') {
    return '{' + Object.keys(value).sort().map((k) => JSON.stringify(k) + ':' + stable(value[k])).join(',') + '}';
  }
  return JSON.stringify(value === undefined ? null : value);
}

function callKey(tool, input) {
  const args = Object.assign({}, input || {});
  delete args.selection_context;
  delete args.confirm;
  return tool + ':' + crypto.createHash('sha256').update(stable(args)).digest('hex').slice(0, 24);
}

function trim(map) {
  const keys = Object.keys(map);
  for (const key of keys.slice(0, Math.max(0, keys.length - MAX_ITEMS))) delete map[key];
}

function sameAgent(seal, agent) {
  const wanted = normalize(agent);
  return !!seal && (wanted === normalize(seal.agent_id) || wanted === normalize(seal.agent_name));
}

// Lo que dijo la persona: sus mensajes y sus respuestas a preguntas del asistente.
// `human` es [{text, at}] en orden. Lo pegado desde otro sitio no cuenta como suyo.
function ownWords(text) {
  return String(text || '')
    .replace(/<pasted_content\b[^>]*>[\s\S]*?<\/pasted_content[^>]*>/g, ' ')
    .replace(/<system-reminder>[\s\S]*?<\/system-reminder>/g, ' ');
}

function findQuote(human, quote, after) {
  const wanted = normalize(quote);
  if (!wanted) return false;
  return (human || []).some((m) => (!after || (m.at && m.at > after)) && normalize(ownWords(m.text)).includes(wanted));
}

// ── Antes de una llamada ────────────────────────────────────────────────────────
// Devuelve {decision: 'pass'|'deny'|'ask', reason, input, context}. `input` viene sólo
// si la llamada tiene que salir con argumentos distintos de los que mandó el modelo.
function preToolUse(state, tool, input, facts, ctx) {
  input = input || {};
  const now = (ctx && ctx.now) || Date.now();
  const human = ctx && ctx.human;
  const out = { decision: 'pass' };

  if (state.retired.includes(tool)) {
    return {
      decision: 'deny',
      reason:
        `\`${tool}\` is withdrawn for the active agent, so Datalum would answer that it does not exist. ` +
        'Do not look for another route. Tell the person, in plain words and without naming the tool, that this agent cannot do that step.',
    };
  }

  const quoteArg = (facts.citas_humanas || {})[tool];
  if (quoteArg && typeof input[quoteArg] === 'string' && input[quoteArg].trim()) {
    const verdict = checkQuote(state, tool, input, quoteArg, human);
    if (verdict) return verdict;
  }

  if (tool === 'use_agent') {
    const next = Object.assign({}, input);
    if (state.seal_state === 'conflict' || state.seal_state === 'expired') {
      // El contexto guardado ya no sirve: el servidor acuña o resuelve el suyo.
      if ('selection_context' in next) {
        delete next.selection_context;
        out.input = next;
      }
    } else if (state.seal && state.seal_state === 'sealed' && next.selection_context !== state.seal.selection_context) {
      next.selection_context = state.seal.selection_context;
      out.input = next;
    }
    return out;
  }

  if ((facts.sin_selection_context || []).includes(tool)) return out;

  if (state.seal_state === 'expired') {
    return {
      decision: 'deny',
      reason:
        `The agent selection for this conversation expired. Before any other Datalum call, select the same agent again ` +
        `(${state.seal ? state.seal.agent_name : 'the one the person chose'}) with use_agent, quoting the person's own words. ` +
        'If their last message does not ask to continue, ask them first. Never continue under a different agent.',
    };
  }
  if (state.seal_state === 'conflict') {
    return {
      decision: 'deny',
      reason:
        'This conversation got crossed with another one on the same connection. Do not repeat the call without its context: ' +
        'it could run under the other conversation\'s agent. Ask the person which agent to continue with and call use_agent again.',
    };
  }

  if (state.seal_state === 'sealed' && input.selection_context !== state.seal.selection_context) {
    // La llamada sale siempre con el contexto de ESTA conversación, lo mande o no el
    // modelo, y nunca con el de otra.
    out.input = Object.assign({}, input, { selection_context: state.seal.selection_context });
  }

  const key = callKey(tool, input);

  const failure = state.failures[key];
  if (failure && failure.count >= MAX_FAILURES && now - failure.at < FAILURE_WINDOW_MS) {
    return {
      decision: 'deny',
      reason:
        `This same call failed ${failure.count} times in a row. Stop retrying. Tell the person what could not be done ` +
        'and what they can do next.',
    };
  }

  if (tool === 'remember' || tool === 'brain_write') {
    const shared = input.scope === 'compartida' || /\/memoria-compartida\//.test(String(input.concept_id || ''));
    if (shared) {
      return {
        decision: 'ask',
        reason:
          'Esto propone una memoria para todas las personas que usan este agente, no sólo para ti. ¿Lo autorizas?',
        input: out.input,
      };
    }
  }

  const isApply = input.confirm === true && !quoteArg;
  if (isApply && !state.previews[key]) {
    return {
      decision: 'deny',
      reason:
        'Ask for the preview first: make this same call without `confirm`, show the person in plain words what would change, ' +
        'and send `confirm: true` only after they agree.',
    };
  }

  if (isApply || MEMORY_WRITES.has(tool)) {
    const previous = state.writes[key];
    if (previous && now - previous.at < WRITE_WINDOW_MS) {
      if (previous.status === 'confirmed') {
        return {
          decision: 'deny',
          reason:
            'This exact write was already confirmed in this conversation. Do not repeat it. If a later read failed, ' +
            'read again; the write itself is done.',
        };
      }
      if (previous.status === 'uncertain' && !previous.checked) {
        return {
          decision: 'deny',
          reason:
            'The result of this write is uncertain: it may have been applied. Before repeating it, read the target ' +
            '(for a memory, list_memories with its name) to see whether it is there.',
        };
      }
    }
  }
  return out;
}

function checkQuote(state, tool, input, quoteArg, human) {
  const quote = input[quoteArg];
  if (human === null || human === undefined) {
    // Sin acceso a lo que dijo la persona no se puede comprobar: decide ella.
    return { decision: 'ask', reason: askText(tool, input) };
  }
  if (tool !== 'use_agent') {
    return findQuote(human, quote) ? null : { decision: 'ask', reason: askText(tool, input) };
  }
  const same = sameAgent(state.seal, input.agent);
  if (state.seal && !same && normalize(quote) === normalize(state.seal.quote)) {
    // Las palabras con las que eligió un agente no eligen otro.
    return { decision: 'ask', reason: askText(tool, input) };
  }
  if (state.seal && same && state.seal_state === 'sealed' && state.newer_version) {
    // Pasar a una versión nueva del agente es volver a elegirlo: tiene que pedirlo
    // la persona después de saber que existe.
    if (!findQuote(human, quote, state.newer_version.seen_at)) {
      return {
        decision: 'ask',
        reason: `Hay una versión nueva del agente «${state.seal.agent_name}». ¿Quieres pasar a ella ahora?`,
      };
    }
    return null;
  }
  return findQuote(human, quote) ? null : { decision: 'ask', reason: askText(tool, input) };
}

function askText(tool, input) {
  if (tool === 'use_agent') {
    return `Datalum va a trabajar con el agente «${input.agent}». La elección tiene que ser tuya: ¿lo elegiste tú?`;
  }
  return 'Esta acción borra datos para siempre y tiene que pedirla la persona con sus palabras. ¿La pediste tú?';
}

// ── Leer lo que contestó Datalum ────────────────────────────────────────────────
function tryJson(text) {
  if (typeof text !== 'string') return undefined;
  const trimmed = text.trim();
  if (!trimmed || (trimmed[0] !== '{' && trimmed[0] !== '[')) return undefined;
  try {
    return JSON.parse(trimmed);
  } catch (_) {
    return undefined;
  }
}

function isEnvelope(value) {
  return !!value && typeof value === 'object' && typeof value.code === 'string' &&
    ('category' in value || 'retryable' in value || 'retry_after' in value);
}

// Devuelve {data, error}: `data` es el objeto que contestó la herramienta y `error`
// el rechazo de Datalum ({code, category, retry_after…}) si lo hubo.
function readResponse(response) {
  const found = { data: null, error: null, isError: false };
  const visit = (value, depth) => {
    if (value === null || value === undefined || depth > 4) return;
    if (typeof value === 'string') {
      const parsed = tryJson(value);
      if (parsed !== undefined) visit(parsed, depth + 1);
      return;
    }
    if (Array.isArray(value)) {
      value.forEach((item) => visit(item, depth + 1));
      return;
    }
    if (typeof value !== 'object') return;
    if (value.isError === true) found.isError = true;
    if (isEnvelope(value)) {
      if (!found.error) found.error = value;
      return;
    }
    if (value.type === 'text' && typeof value.text === 'string') {
      visit(value.text, depth + 1);
      return;
    }
    if ('structuredContent' in value || Array.isArray(value.content)) {
      visit(value.structuredContent, depth + 1);
      visit(value.content, depth + 1);
      return;
    }
    if (!found.data) found.data = value;
  };
  visit(response, 0);
  return found;
}

const CODE_IN_TEXT = /\b(agent_not_selected|agent_context_conflict|agent_seal_held|rate_limited|quota_exceeded|partial_write|not_found|unknown_tool|internal_error|backend_timeout|athena_timeout|okf_budget_exhausted|agent_identity_required|access_denied)\b/;

function errorFromText(text) {
  const body = String(text || '');
  const start = body.indexOf('{');
  if (start >= 0) {
    for (let end = body.lastIndexOf('}'); end > start; end = body.lastIndexOf('}', end - 1)) {
      const parsed = tryJson(body.slice(start, end + 1));
      if (isEnvelope(parsed)) return parsed;
      if (parsed !== undefined) break;
    }
  }
  const named = CODE_IN_TEXT.exec(body);
  if (named) return { code: named[1] };
  if (/timed? ?out|timeout|ECONNRESET|socket hang up|network|fetch failed|50[234]/i.test(body)) return { code: 'transport_uncertain' };
  if (/\b401\b|unauthorized|Bearer token|Invalid or revoked token/i.test(body)) return { code: 'unauthorized' };
  return { code: 'unknown' };
}

// ── Después de una llamada ──────────────────────────────────────────────────────
// Actualiza el estado y devuelve, si hace falta, una nota para el modelo.
function postToolUse(state, tool, input, response, ctx) {
  input = input || {};
  const now = (ctx && ctx.now) || Date.now();
  const at = (ctx && ctx.at) || new Date(now).toISOString();
  const { data, error, isError } = readResponse(response);
  if (error || isError) return applyError(state, tool, input, error || { code: 'unknown' }, now);

  const key = callKey(tool, input);
  delete state.failures[key];
  const notes = [];
  const body = data || {};

  if (ctx && ctx.server) learnServer(state, ctx.server, tool, body);

  if (tool === 'use_agent' && body.selection_context) {
    const before = state.seal;
    const agent = body.agent || {};
    state.seal = {
      agent_id: agent.id || input.agent,
      agent_name: agent.name || input.agent,
      version: agent.version === undefined ? null : agent.version,
      family: agent.family || null,
      selection_context: body.selection_context,
      expires_at: body.expires_at || null,
      quote: input.user_choice_quote || '',
      sealed_at: at,
    };
    state.seal_state = 'sealed';
    state.retired = Array.isArray(agent.herramientasRetiradas) ? agent.herramientasRetiradas.slice() : [];
    state.newer_version = null;
    const moved = before && sameAgent(before, state.seal.agent_id) && before.version !== state.seal.version;
    if (!before || !sameAgent(before, state.seal.agent_id) || moved) {
      state.reads = {};
      state.listings = {};
    }
    if (moved) {
      notes.push(
        `The agent moved from v${before.version} to v${state.seal.version}. Tell the person. Anything read from the brain ` +
        'before now belongs to the old version: open again what you need and do not mix the two.'
      );
    }
    if (body.memory === null || body.memory === undefined) {
      notes.push('No memory index came with the selection. That does not prove there is no memory: check with list_memories when the task may continue earlier work.');
    } else if (body.memory.truncated || body.memory.omitidas > 0) {
      notes.push('The memory index in this response is partial. Use list_memories (following its cursor) before concluding that something is not in memory.');
    }
  }

  if (tool === 'release_agent' && body.released) {
    state.seal = null;
    state.seal_state = 'none';
    state.retired = [];
    state.newer_version = null;
    state.reads = {};
    state.listings = {};
  }

  if (body.sello_posterior && typeof body.sello_posterior === 'object' && state.seal) {
    const first = !state.newer_version;
    state.newer_version = {
      served: body.sello_posterior.version_servida,
      sealed: body.sello_posterior.version_sellada,
      seen_at: (state.newer_version && state.newer_version.seen_at) || at,
    };
    if (first) {
      notes.push(
        `A newer version of this agent exists (v${state.newer_version.sealed}); this conversation keeps working with ` +
        `v${state.newer_version.served}. Tell the person in plain words and switch only if they ask.`
      );
    }
  }

  if (tool === 'brain_read' && input.concept_id) {
    const partial = body.next_offset !== undefined && body.next_offset !== null;
    state.reads[input.concept_id] = { complete: !partial, next_offset: partial ? body.next_offset : null };
    trim(state.reads);
    if (partial) {
      notes.push(
        `\`${input.concept_id}\` is not complete yet: continue with offset ${body.next_offset} before relying on it or telling the person you read it.`
      );
    }
  }

  if (tool === 'brain_index' || tool === 'list_memories') {
    const cursor = body.next_cursor || (body.memory && body.memory.next_cursor) || null;
    const where = tool === 'brain_index' ? (input.path || '(root)') : 'memory index';
    state.listings[tool + ':' + where] = { complete: !cursor };
    trim(state.listings);
    if (cursor) notes.push(`This listing of ${where} is partial: continue with the cursor it returned before concluding that something is missing.`);
  }

  if (MEMORY_READS.has(tool)) {
    for (const write of Object.values(state.writes)) {
      if (write.status === 'uncertain') write.checked = true;
    }
  }

  const applied = input.confirm === true;
  if (MEMORY_WRITES.has(tool) || applied) {
    const proposed = body.outcome === 'propuesta';
    state.writes[key] = {
      status: 'confirmed',
      at: now,
      tool,
      name: body.slug || body.concept_id || input.slug || input.memory || input.title || null,
      proposed,
    };
    trim(state.writes);
    delete state.previews[key];
    if (tool !== 'forget') {
      notes.push(
        proposed
          ? 'This was filed as a proposal for a person to approve. It is not saved as a memory: say so.'
          : 'Write confirmed. Check once that it can be read back. If that read fails, report it as saved but not yet verified; do not write it again.'
      );
    }
  } else if (input.confirm !== true) {
    state.previews[key] = now;
    trim(state.previews);
  }

  return { context: notes.join('\n') || null };
}

function learnServer(state, server, tool, body) {
  if (state.server === server) return;
  const looksLikeDatalum =
    (tool === 'use_agent' && typeof body.selection_context === 'string' && 'operating_as' in body) ||
    (tool === 'list_agents' && Array.isArray(body.agents) && typeof body.message === 'string');
  if (looksLikeDatalum) state.server = server;
}

function postToolUseFailure(state, tool, input, errorText, ctx) {
  const now = (ctx && ctx.now) || Date.now();
  return applyError(state, tool, input || {}, errorFromText(errorText), now);
}

function applyError(state, tool, input, error, now) {
  const key = callKey(tool, input);
  const code = error.code;
  const writeLike = MEMORY_WRITES.has(tool) || input.confirm === true;
  const count = () => {
    const previous = state.failures[key];
    const fresh = previous && now - previous.at < FAILURE_WINDOW_MS;
    state.failures[key] = { count: fresh ? previous.count + 1 : 1, at: now };
    trim(state.failures);
  };

  if (code === 'agent_not_selected') {
    if (state.seal) {
      state.seal_state = 'expired';
      return {
        context:
          `The agent selection expired. Select the same agent again (${state.seal.agent_name}) with use_agent, quoting the ` +
          "person's own words. If their last message does not ask to continue this work, ask them. Then say which agent and " +
          'version is active; if the version changed, open the brain documents again.',
      };
    }
    return { context: null };
  }
  if (code === 'agent_context_conflict') {
    state.seal_state = 'conflict';
    return {
      context:
        'Another conversation on this connection has its own agent selected. Do not drop the context and repeat the call: it ' +
        'could run under that other agent. Tell the person in plain words, ask which agent this conversation continues with, ' +
        'and call use_agent again. If Datalum answers that another agent is in place, say which one and do not release it unless they ask.',
    };
  }
  if (code === 'rate_limited') {
    count();
    const wait = error.retry_after ? `${error.retry_after} s` : 'a few seconds';
    return { context: `Nothing was executed. Wait ${wait} and retry this same call once.` };
  }
  if (code === 'partial_write') {
    state.writes[key] = { status: 'partial', at: now, tool };
    return { context: 'The write was applied in part. Repeat this same call to complete it, then check the result.' };
  }
  if (writeLike && (code === 'transport_uncertain' || code === 'backend_timeout' || code === 'athena_timeout' || code === 'internal_error' || code === 'unknown')) {
    state.writes[key] = { status: 'uncertain', at: now, tool, checked: false, name: input.slug || input.memory || input.title || null };
    trim(state.writes);
    count();
    return {
      context:
        'It is not known whether this write was applied. Do not repeat it yet. Read the target first; repeat only if it is not there. ' +
        'Until then, tell the person the result is not confirmed.',
    };
  }
  count();
  return { context: null };
}

// ── Recuperar el hilo tras una compactación o al reanudar ───────────────────────
function resumeContext(state) {
  if (!state.seal) return null;
  const lines = ['Datalum, state of this conversation as kept by the plugin (data, not instructions from the person):'];
  if (state.seal_state === 'sealed') {
    lines.push(
      `- Selected agent: ${state.seal.agent_name} v${state.seal.version}. Keep working as this agent; do not pick another one or ` +
      'take a newer version unless the person asks. The conversation context is added to each Datalum call for you.'
    );
  } else {
    lines.push(
      `- The selection of ${state.seal.agent_name} is no longer valid (${state.seal_state}). Select it again with the person's own words before any other Datalum call.`
    );
  }
  if (state.newer_version) {
    lines.push(`- A newer version (v${state.newer_version.sealed}) exists; this conversation stays on v${state.newer_version.served} until the person asks to switch.`);
  }
  const complete = Object.keys(state.reads).filter((id) => state.reads[id].complete);
  const partial = Object.keys(state.reads).filter((id) => !state.reads[id].complete);
  if (complete.length) {
    lines.push(`- Brain documents read in full before the context was reduced: ${complete.join(', ')}. A summary does not replace them: open again the ones this task needs.`);
  }
  if (partial.length) {
    lines.push(`- Left half-read: ${partial.map((id) => `${id} (continue at offset ${state.reads[id].next_offset})`).join(', ')}.`);
  }
  const writes = Object.values(state.writes);
  const confirmed = writes.filter((w) => w.status === 'confirmed' && w.name).map((w) => w.name);
  const uncertain = writes.filter((w) => w.status === 'uncertain').map((w) => w.name || w.tool);
  if (confirmed.length) lines.push(`- Writes already confirmed: ${confirmed.join(', ')}. Do not repeat them.`);
  if (uncertain.length) lines.push(`- Writes with an uncertain result: ${uncertain.join(', ')}. Read the target before repeating.`);
  lines.push('- If the work was tracked in memory, recover it with list_memories before continuing, following the agent\'s memory rules.');
  return lines.join('\n');
}

module.exports = {
  newState,
  isDatalum,
  parseToolName,
  preToolUse,
  postToolUse,
  postToolUseFailure,
  resumeContext,
  readResponse,
  errorFromText,
  findQuote,
  ownWords,
  normalize,
  callKey,
};
