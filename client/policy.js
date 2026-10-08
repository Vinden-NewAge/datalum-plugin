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
//
// Dos reglas sostienen el resto:
// - Dejar pasar una llamada no es autorizarla. El cliente nunca aprueba por la persona:
//   cuando hace falta su consentimiento, o lo hay de una fuente confiable (lo que ella
//   eligió o aprobó en la aplicación) o se lo pide la aplicación.
// - Una operación se identifica por el agente que la hace, su ámbito, su destino, su
//   operación y su contenido. El estado guarda huellas de esas partes, no el texto.

const crypto = require('crypto');

const STATE_VERSION = 2;
const MAX_ITEMS = 40;
const MAX_FAILURES = 3;
const FAILURE_WINDOW_MS = 10 * 60 * 1000;
const WRITE_WINDOW_MS = 30 * 60 * 1000;
const PENDING_MS = 15 * 60 * 1000;
const MAX_PREVIEWS = 200;
const START_TOOLS = new Set(['list_agents', 'use_agent', 'release_agent']);
const DELETES = new Set(['delete_my_memories', 'workspace_purge']);
// Modos en que un «preguntar» de un hook llega a la persona como diálogo de la
// aplicación. En `dontAsk` la aplicación lo deniega sola; en `bypassPermissions` no
// pregunta nada.
const ASKING_MODES = new Set(['default', 'acceptEdits', 'plan', 'auto']);
const NO_AGENT = 'sin-agente';
// Estados de una operación que ya ocurrió: repetirla la duplicaría.
const DONE = new Set(['confirmed', 'proposed']);
// Cómo leer de vuelta una memoria: lo dice el cerebro del agente, no el cliente.
const READ_BACK = "the way the agent's brain says to read its memory";
// Una escritura migrada de la 2.0.0 cuyo agente no se puede saber.
const UNKNOWN_AGENT = 'agente-desconocido';
// Argumentos con palabras de la persona: no forman parte de la identidad de una
// operación ni se guardan.
const QUOTE_ARGS = ['user_choice_quote', 'user_request_quote', 'frase'];

function newState(pluginVersion) {
  return {
    v: STATE_VERSION,
    plugin_version: pluginVersion || null,
    server: null,
    seal: null, // {agent_id, agent_name, version, family, selection_context, expires_at, sealed_at}
    seal_state: 'none', // none | sealed | expired | conflict
    newer_version: null,
    retired: [],
    keyring: null, // [{id, name}] de la última respuesta de list_agents
    keyring_at: null,
    choice_floor: null, // la última elección de la persona que ya se usó: para elegir otra vez cuenta sólo lo posterior
    released_at: null, // desde que se soltó un agente, el único de la lista ya no se da por elegido
    authorized: {}, // agente → {via, at}: la persona eligió trabajar con él en esta conversación
    pending: {}, // llamadas en las que el cliente pidió a la aplicación que preguntara
    approved: {}, // operación → at: aprobada por la persona y todavía reintentable
    reads: {},
    listings: {},
    previews: {},
    ops: {}, // escrituras, por identidad de operación
    seen: {}, // destino de memoria → último memory_id visto
    failures: {},
    legacy: { writes: {}, previews: {} }, // lo que traía un estado de la 2.0.0
  };
}

// ── Estados de la 2.0.0 ─────────────────────────────────────────────────────────
// Un estado de la 2.0.0 guardaba la frase con que se eligió el agente y llaves de
// escritura sin agente. Se migra sin perder las escrituras pendientes, el agente
// elegido ni la continuidad de la conversación.
function migrate(raw, pluginVersion, at) {
  if (!raw || typeof raw !== 'object') return newState(pluginVersion);
  if (raw.v === STATE_VERSION) return raw;
  if (raw.v !== 1) return newState(pluginVersion);
  const state = newState(raw.plugin_version || pluginVersion);
  for (const key of ['server', 'seal_state', 'newer_version', 'retired', 'keyring', 'reads', 'listings']) {
    if (raw[key] !== undefined) state[key] = raw[key];
  }
  if (raw.seal) {
    const seal = Object.assign({}, raw.seal);
    delete seal.quote;
    state.seal = seal;
    // La conversación ya trabajaba con ese agente: la elección se conserva.
    state.authorized[seal.agent_id] = { via: 'migrado', at: seal.sealed_at || null };
  }
  // Lo que la persona eligió antes de actualizar ya lo usó la 2.0.0: para elegir otra
  // vez hace falta una elección nueva.
  state.choice_floor = at || (raw.seal && raw.seal.sealed_at) || null;
  // La 2.0.0 no guardaba qué agente hizo cada escritura. Lo posterior a la elección del
  // agente actual es suyo; lo anterior pudo hacerlo otro, y queda sin dueño.
  const sealedAt = raw.seal ? Date.parse(raw.seal.sealed_at) : NaN;
  const ownerOf = (at) =>
    raw.seal && Number.isFinite(sealedAt) && typeof at === 'number' && at >= sealedAt ? raw.seal.agent_id : UNKNOWN_AGENT;
  for (const [key, write] of Object.entries(raw.writes || {})) {
    // Sin el nombre ni el título: sólo lo que hace falta para seguir bloqueando.
    state.legacy.writes[key] = { status: write.status, at: write.at, tool: write.tool, agent: ownerOf(write.at) };
  }
  for (const [key, at] of Object.entries(raw.previews || {})) state.legacy.previews[key] = { at, agent: ownerOf(at) };
  return state;
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
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[«»“”"'‘’]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

// El nombre con que Datalum guarda una memoria: minúsculas, sin acentos, «_» en lugar
// de lo que no sea letra o número, sin «_» repetidos ni en los extremos, 80 caracteres.
function slugify(text) {
  return String(text || '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 80);
}

function stable(value) {
  if (Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
  if (value && typeof value === 'object') {
    return '{' + Object.keys(value).sort().map((k) => JSON.stringify(k) + ':' + stable(value[k])).join(',') + '}';
  }
  return JSON.stringify(value === undefined ? null : value);
}

function digest(text) {
  return crypto.createHash('sha256').update(String(text)).digest('hex').slice(0, 24);
}

// Los invisibles que Datalum reemplaza por un espacio al servir el archivo de una
// memoria: controles, ancho cero, marcas de dirección y aisladores bidi.
// eslint-disable-next-line no-control-regex
const INVISIBLES = /[\u0000-\u0009\u000b-\u001f\u007f-\u009f\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;

// Líneas significativas de un texto, para reconocer un cuerpo dentro de otro.
function lines(text) {
  return String(text || '')
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map((l) => l.replace(INVISIBLES, ' ').replace(/\s+/g, ' ').trim())
    .filter(Boolean);
}

// El archivo de una memoria dentro del bloque de detalle que sirve Datalum: va entre
// «--- archivo ---» y «--- fin del archivo ---», con cada línea prefijada con «| ».
const FILE_OPEN = '--- archivo ---';
const FILE_CLOSE = '--- fin del archivo ---';
function memoryFile(block) {
  const all = String(block || '').replace(/\r\n?/g, '\n').split('\n');
  const start = all.indexOf(FILE_OPEN);
  const end = all.lastIndexOf(FILE_CLOSE);
  const inner = start >= 0 && end > start ? all.slice(start + 1, end) : all;
  return inner.map((l) => (l.startsWith('| ') ? l.slice(2) : l === '|' ? '' : l)).join('\n');
}

function trim(map, max) {
  const keys = Object.keys(map);
  for (const key of keys.slice(0, Math.max(0, keys.length - (max || MAX_ITEMS)))) delete map[key];
}

function currentAgent(state) {
  return (state.seal && state.seal.agent_id) || NO_AGENT;
}

// La llave de la 2.0.0, sólo para reconocer lo migrado.
function legacyKey(tool, input) {
  const args = Object.assign({}, input || {});
  delete args.selection_context;
  delete args.confirm;
  return tool + ':' + crypto.createHash('sha256').update(stable(args)).digest('hex').slice(0, 24);
}

// ── Identidad de una operación ──────────────────────────────────────────────────
// agente · operación · ámbito · destino · contenido. El agente sale del sello que
// devolvió Datalum, nunca del contexto de la conversación: renovar el contexto del
// mismo agente no cambia la identidad de sus operaciones.

function memoryPath(conceptId) {
  // `agents/{slug}/memoria/{nombre}`, o la forma corta `memoria/{nombre}` que Datalum
  // también acepta.
  const m = /^(?:agents\/[^/]+\/)?(memoria|memoria-compartida)\/([^/]+)$/.exec(String(conceptId || ''));
  return m ? { scope: m[1] === 'memoria' ? 'personal' : 'compartida', name: m[2] } : null;
}

function operation(state, tool, input, facts) {
  const agent = currentAgent(state);
  const args = Object.assign({}, input || {});
  delete args.selection_context;
  delete args.confirm;
  const quoteArg = ((facts && facts.citas_humanas) || {})[tool];
  for (const arg of QUOTE_ARGS.concat(quoteArg ? [quoteArg] : [])) delete args[arg];
  let kind = 'other';
  let op = tool;
  let scope = '';
  let target = '';
  let memory = null;
  let before = null;
  if (tool === 'remember') {
    kind = 'memory';
    op = 'memoria.escribir';
    scope = input.scope === 'compartida' ? 'compartida' : 'personal';
    target = slugify(input.slug || input.title);
    memory = { title: input.title, body: input.body_md };
  } else if (tool === 'brain_write' && memoryPath(input.concept_id)) {
    const path = memoryPath(input.concept_id);
    kind = 'memory';
    op = 'memoria.escribir';
    scope = path.scope;
    target = slugify(path.name);
    memory = { title: input.title, body: input.body_md };
  } else if (tool === 'brain_write') {
    // Un agente nuevo por la puerta del paquete: se aplica en la primera llamada.
    kind = 'write';
    op = 'agente.proponer';
    target = String(input.concept_id || '');
  } else if (tool === 'forget') {
    kind = 'memory';
    op = 'memoria.retirar';
    scope = 'personal';
    target = slugify(input.memory);
  } else {
    // Cualquier otra herramienta: la vista previa y la aplicación de un mismo cambio
    // comparten identidad, porque `confirm` no forma parte de ella.
    kind = input.confirm === true || DELETES.has(tool) ? 'catalog' : 'tool';
    // El ámbito es el conector, que Datalum R12 nombra `connector`. Mientras el servidor
    // publicado no tenga R12 llega como `tenant`: se leen los dos. Sale del contenido,
    // porque ya está en el ámbito: el mismo cambio es el mismo con cualquiera de los dos.
    scope = String(input.connector || input.tenant || '');
    delete args.connector;
    delete args.tenant;
    // La 2.x dejaba el conector en el contenido, como `tenant`: así reconoce la 3.0.0 lo
    // que la 2.x guardó antes de actualizar el plugin en la misma conversación.
    if (scope) before = Object.assign({}, args, { tenant: scope });
    // El destino lo dice el contrato (client/contract-facts.json); sin él, `name`.
    const field = ((facts && facts.destinos) || {})[tool] || 'name';
    target = input[field] !== undefined ? `${field}=${stable(input[field])}` : '';
  }
  const targetKey = [agent, op, scope, digest(target)].join('|');
  const content = digest(stable(args));
  return {
    kind,
    agent,
    op,
    scope,
    targetKey,
    key: targetKey + '|' + content,
    contents: before ? [content, digest(stable(before))] : [content],
    memory,
  };
}

// ¿Es `key` la llave de esta misma escritura, aunque la haya guardado otra versión del
// plugin? Lo es si coinciden el agente, la operación, el ámbito y el contenido. El
// destino no hace falta compararlo: sale del contenido, y cada versión lo elige con su
// contrato, así que al actualizar puede cambiar.
function sameWrite(key, op) {
  if (key === op.key) return true;
  const parts = key.split('|');
  return parts.length === 5 && parts[0] === op.agent && parts[1] === op.op && parts[2] === op.scope && op.contents.includes(parts[4]);
}

// Huellas del contenido que se intentó escribir en una memoria: con ellas se reconoce
// el resultado al leerla después, sin guardar el texto.
function memoryEvidence(memory) {
  if (!memory) return null;
  const body = lines(memory.body);
  return {
    title_h: memory.title ? digest(normalize(memory.title)) : null,
    body_h: body.length ? digest(body.join('\n')) : null,
    body_n: body.length,
  };
}

function containsBody(block, evidence) {
  if (!evidence.body_h) return false;
  const have = lines(block);
  for (let i = 0; i + evidence.body_n <= have.length; i++) {
    if (digest(have.slice(i, i + evidence.body_n).join('\n')) === evidence.body_h) return true;
  }
  return false;
}

// ── Consentimiento de la persona ────────────────────────────────────────────────
// Lo que la persona escribió o eligió, como lo registró la aplicación: `human` es
// [{text, at, kind}] con kind 'message' (un mensaje suyo) o 'answer' (lo que eligió
// en una pregunta de la aplicación). Lo pegado desde otro sitio no cuenta como suyo.
function ownWords(text) {
  return String(text || '')
    .replace(/<pasted_content\b[^>]*>[\s\S]*?<\/pasted_content[^>]*>/g, ' ')
    .replace(/<system-reminder>[\s\S]*?<\/system-reminder>/g, ' ');
}

function agentEntry(state, agent) {
  const wanted = normalize(agent);
  return (state.keyring || []).find((a) => normalize(a.id) === wanted || normalize(a.name) === wanted) || null;
}

// El id estable de un agente nombrado por id o por nombre: de la lista de agentes,
// del sello vigente o de una elección anterior en esta conversación.
function agentIdOf(state, agent) {
  const entry = agentEntry(state, agent);
  if (entry && entry.id) return entry.id;
  const wanted = normalize(agent);
  if (state.seal && (normalize(state.seal.agent_id) === wanted || normalize(state.seal.agent_name) === wanted)) {
    return state.seal.agent_id;
  }
  for (const [id, auth] of Object.entries(state.authorized || {})) {
    if (normalize(id) === wanted || normalize(auth.name) === wanted) return id;
  }
  return String(agent || '');
}

// ¿Hay evidencia confiable de que la persona eligió este agente? Una cita que lo
// menciona no lo es: «No uses Finanzas» también menciona a Finanzas. Cuenta lo que la
// persona eligió en una pregunta de la aplicación, o un mensaje suyo que es sólo el
// nombre del agente, después de que el asistente obtuvo la lista de agentes; y, con
// un único agente, el contrato de Datalum, que manda usarlo. Devuelve {via, at}, con
// `at` el momento de la elección, o null.
function selectionEvidence(state, agent, human) {
  const entry = agentEntry(state, agent);
  // Una elección sirve una vez: la que ya eligió un agente no vuelve a elegir otro, ni
  // al mismo después de soltarlo. Y tras soltar, el único agente de la lista ya no se
  // da por elegido: lo vuelve a decidir la persona.
  const floor = [state.keyring_at, state.choice_floor].filter(Boolean).sort().pop() || null;
  if (state.keyring && state.keyring.length === 1 && entry && !state.released_at) return { via: 'unico', at: null };
  const names = new Set([normalize(agent)]);
  if (entry) {
    if (entry.name) names.add(normalize(entry.name));
    if (entry.id) names.add(normalize(entry.id));
  }
  for (const m of human || []) {
    if (floor && (!m.at || m.at <= floor)) continue;
    if (names.has(normalize(ownWords(m.text)))) return { via: m.kind === 'answer' ? 'pregunta' : 'mensaje', at: m.at };
  }
  return null;
}

// Pide que la aplicación le pregunte a la persona y anota qué se preguntó, para
// reconocer después su respuesta. En un modo sin diálogos niega: nadie vería la pregunta.
function askPerson(state, ctx, entry, reason, modelReason) {
  if (ctx && ctx.mode === 'bypassPermissions') {
    return { decision: 'deny', reason: modelReason };
  }
  expectOutcome(state, ctx, entry);
  return { decision: 'ask', reason };
}

function expectOutcome(state, ctx, entry) {
  const id = (ctx && ctx.toolUseId) || `${entry.kind}:${normalize(entry.agent)}:${entry.op || ''}`;
  state.pending[id] = Object.assign({ at: (ctx && ctx.now) || Date.now(), mode: (ctx && ctx.mode) || null }, entry);
  trim(state.pending);
}

function takePending(state, ctx, fallback) {
  const ids = [ctx && ctx.toolUseId, fallback].filter(Boolean);
  for (const id of ids) {
    const entry = state.pending[id];
    if (entry) {
      delete state.pending[id];
      const now = (ctx && ctx.now) || Date.now();
      return now - entry.at <= PENDING_MS ? entry : null;
    }
  }
  return null;
}

// ── Antes de una llamada ────────────────────────────────────────────────────────
// Devuelve {decision: 'pass'|'deny'|'ask', reason, input}. `pass` sólo quiere decir
// que el cliente no se opone: la aplicación y Datalum aplican después sus propios
// permisos. `input` viene si la llamada tiene que salir con otros argumentos.
function preToolUse(state, tool, input, facts, ctx) {
  input = input || {};
  const now = (ctx && ctx.now) || Date.now();
  const out = { decision: 'pass' };

  if (state.retired.includes(tool)) {
    return {
      decision: 'deny',
      reason:
        `\`${tool}\` is withdrawn for the active agent, so Datalum would answer that it does not exist. ` +
        'Do not look for another route. Tell the person, in plain words and without naming the tool, that this agent cannot do that step.',
    };
  }

  // Lo que el plugin tiene en pausa lo nombra el contrato derivado, no este código.
  const paused = facts && facts.en_pausa;
  if (paused && (paused.herramientas || []).includes(tool)) return { decision: 'deny', reason: paused.aviso };

  if (tool === 'use_agent') return preSelect(state, input, ctx, now);

  if (DELETES.has(tool)) {
    const context = withContext(state, tool, input, facts, out);
    if (context.decision !== 'pass') return context;
    const op = operation(state, tool, input, facts);
    const approvedAt = state.approved[op.key];
    if (approvedAt && now - approvedAt <= PENDING_MS) return out;
    const verdict = askPerson(
      state,
      ctx,
      { kind: 'borrar', agent: op.agent, op: op.key },
      'Esta acción borra datos de Datalum para siempre. ¿La autorizas?',
      'This deletes data for good and this app is running without permission prompts, so the person cannot confirm it here. ' +
        'Do not run it. Tell the person it needs their confirmation in an app or mode that asks for it.'
    );
    return Object.assign(verdict, out.input && verdict.decision !== 'deny' ? { input: out.input } : {});
  }

  const context = withContext(state, tool, input, facts, out);
  if (context.decision !== 'pass') return context;

  const op = operation(state, tool, input, facts);

  const failure = state.failures[op.key];
  if (failure && failure.count >= MAX_FAILURES && now - failure.at < FAILURE_WINDOW_MS) {
    return {
      decision: 'deny',
      reason:
        `This same call failed ${failure.count} times in a row. Stop retrying. Tell the person what could not be done ` +
        'and what they can do next.',
    };
  }

  if (op.kind === 'memory' && op.scope === 'compartida') {
    const repeated = checkRepeat(state, tool, input, op, ctx, now);
    if (repeated) return Object.assign(repeated, out.input && repeated.decision !== 'deny' ? { input: out.input } : {});
    return Object.assign(
      askPerson(
        state,
        ctx,
        { kind: 'compartida', agent: op.agent, op: op.key },
        'Esto propone una memoria para todas las personas que usan este agente, no sólo para ti. ¿Lo autorizas?',
        'Shared memory reaches everyone who uses this agent and this app cannot ask the person to confirm it. Do not use it.'
      ),
      out.input ? { input: out.input } : {}
    );
  }

  const isApply = input.confirm === true;
  if (isApply && op.kind === 'catalog') {
    const preview = state.previews[op.key];
    const legacy = state.legacy.previews[legacyKey(tool, input)];
    const fresh = (p) => p && now - p <= WRITE_WINDOW_MS;
    if (!fresh(preview) && !(legacy && legacy.agent === op.agent && fresh(legacy.at))) {
      return {
        decision: 'deny',
        reason:
          'Ask for the preview first: make this same call without `confirm`, show the person in plain words what would change, ' +
          'and send `confirm: true` only after they agree.',
      };
    }
  }

  if (op.kind === 'memory' || op.kind === 'write' || (isApply && op.kind === 'catalog')) {
    const verdict = checkRepeat(state, tool, input, op, ctx, now);
    if (verdict) return Object.assign(verdict, out.input && verdict.decision !== 'deny' ? { input: out.input } : {});
  }
  return out;
}

// Fija el contexto de la conversación y frena las llamadas mientras la selección no
// es válida.
function withContext(state, tool, input, facts, out) {
  if ((facts.sin_selection_context || []).includes(tool)) return out;
  if (state.seal_state === 'expired') {
    return {
      decision: 'deny',
      reason:
        `The agent selection for this conversation expired. Before any other Datalum call, select the same agent again ` +
        `(${state.seal ? state.seal.agent_name : 'the one the person chose'}) with use_agent, quoting the person's own words. ` +
        'Never continue under a different agent.',
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
  return out;
}

function preSelect(state, input, ctx, now) {
  const out = { decision: 'pass' };
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
  const withInput = (verdict) => Object.assign(verdict, out.input && verdict.decision !== 'deny' ? { input: out.input } : {});

  const agentId = agentIdOf(state, input.agent);
  const name = (agentEntry(state, input.agent) || {}).name || input.agent;
  const same = !!state.seal && (state.seal.agent_id === agentId || normalize(state.seal.agent_name) === normalize(input.agent));

  // Volver a elegir el mismo agente cuando hay una versión nueva es adoptarla: lo
  // decide la persona, aunque ya lo hubiera elegido antes.
  if (same && state.newer_version) {
    return withInput(
      askPerson(
        state,
        ctx,
        { kind: 'adoptar', agent: agentId },
        `Hay una versión nueva del agente «${name}». ¿Pasar a ella ahora?`,
        'Selecting the agent again would switch to its newer version, and this app cannot ask the person to confirm it. ' +
          'Keep working with the current version and tell the person a newer one exists.'
      )
    );
  }

  const authorization = state.authorized[agentId];
  if (authorization) return out; // La persona ya eligió este agente en esta conversación.

  const evidence = selectionEvidence(state, input.agent, ctx && ctx.human);
  if (evidence) {
    expectOutcome(state, ctx, { kind: 'elegir', agent: agentId, via: evidence.via, chosen_at: evidence.at });
    return out;
  }
  return withInput(
    askPerson(
      state,
      ctx,
      { kind: 'elegir', agent: agentId, via: 'anfitrion' },
      `Datalum va a trabajar con el agente «${name}». ¿Lo eliges tú?`,
      'The person has not chosen this agent in a way this app can confirm, and it cannot show them a confirmation here. ' +
        'Ask the person which agent to use, with a multiple-choice question offering the agent names if you can, and select ' +
        'only the one they pick.'
    )
  );
}

// ¿Se puede repetir esta escritura? Una escritura confirmada con el mismo contenido
// no se repite. Una incierta sólo se repite cuando una lectura del mismo destino
// demostró que no se aplicó, o cuando la persona lo aprueba en la aplicación.
function checkRepeat(state, tool, input, op, ctx, now) {
  const exact = Object.entries(state.ops).find(
    ([key, rec]) => sameWrite(key, op) && DONE.has(rec.status) && now - rec.at < WRITE_WINDOW_MS
  );
  if (exact) return duplicate(exact[1]);
  const legacy = state.legacy.writes[legacyKey(tool, input)];
  const legacyRecent = legacy && now - legacy.at < WRITE_WINDOW_MS;
  const legacyLive = legacyRecent && legacy.agent === op.agent;
  if (legacyLive && legacy.status === 'confirmed') return duplicate(legacy);
  // La persona aprobó repetir esta operación y la llamada falló: no se le vuelve a preguntar.
  if (state.approved[op.key] && now - state.approved[op.key] <= PENDING_MS) return null;
  if (legacyLive && (legacy.status === 'uncertain' || legacy.status === 'partial')) return askRetry(state, ctx, op);
  if (legacyRecent && legacy.agent === UNKNOWN_AGENT) {
    // De antes de actualizar el plugin y de agente desconocido: puede ser un duplicado
    // o una operación legítima de este agente. Decide la persona.
    return askPerson(
      state,
      ctx,
      { kind: 'reintentar', agent: op.agent, op: op.key },
      'Esta misma operación ya se pidió hace poco en esta conversación, quizá con otro agente. ¿La repito?',
      'This same operation was requested earlier in this conversation, possibly by another agent, and this app cannot ask the ' +
        'person whether to repeat it. Do not repeat it; tell the person.'
    );
  }

  const pending = Object.entries(state.ops).find(
    ([key, rec]) =>
      (key.startsWith(op.targetKey + '|') || sameWrite(key, op)) &&
      ['uncertain', 'absent', 'retrying'].includes(rec.status) &&
      now - rec.at < WRITE_WINDOW_MS
  );
  if (!pending) return null;
  const [, rec] = pending;
  if (rec.status === 'absent') {
    // Una lectura demostró que no se aplicó: se permite un reintento, uno solo.
    rec.status = 'retrying';
    rec.at = now;
    return null;
  }
  if (rec.status === 'retrying') {
    return {
      decision: 'deny',
      reason: 'A retry of this write is already under way. Wait for its result before writing this memory again.',
    };
  }
  if (op.kind === 'memory' && !rec.inconclusive) {
    return {
      decision: 'deny',
      reason:
        'It is not known whether an earlier write to this same memory was applied. Before writing it again, read that memory ' +
        `back by its name, ${READ_BACK}, so the result can be checked. Until then, tell the person it is not confirmed.`,
    };
  }
  return askRetry(state, ctx, op);
}

function duplicate(rec) {
  if (rec && rec.status === 'proposed') {
    return {
      decision: 'deny',
      reason:
        'This exact proposal was already filed in this conversation and waits for a person to approve it. Do not file it ' +
        'again; tell the person it is waiting for approval.',
    };
  }
  return {
    decision: 'deny',
    reason:
      'This exact write was already confirmed in this conversation for this agent. Do not repeat it. If a later read failed, ' +
      'read again; the write itself is done.',
  };
}

function askRetry(state, ctx, op) {
  return askPerson(
    state,
    ctx,
    { kind: 'reintentar', agent: op.agent, op: op.key },
    'No se pudo comprobar si el cambio anterior se guardó. Repetirlo puede duplicarlo. ¿Lo repito?',
    'It is not known whether the earlier write was applied, and this app cannot ask the person whether to repeat it. ' +
      'Do not repeat it. Tell the person the result is not confirmed.'
  );
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

const CODE_IN_TEXT = /\b(agent_memory_not_found|agent_not_selected|agent_context_conflict|agent_seal_held|rate_limited|quota_exceeded|partial_write|not_found|unknown_tool|internal_error|backend_timeout|athena_timeout|okf_budget_exhausted|agent_identity_required|access_denied)\b/;

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

// ── Lo que una lectura de memoria demuestra ─────────────────────────────────────
// Sólo una lectura del MISMO destino (agente, ámbito y nombre), hecha después de la
// escritura incierta y completa, puede resolverla:
//   aplicada    la memoria viva trae el título y el cuerpo que se intentó escribir
//   no aplicada no existe, o sigue viva la misma memoria (mismo id) que había antes
//   incierta    cualquier otra cosa: cortada, fallida, otro destino o un id nuevo con
//               otro contenido
function memoryRead(tool, input) {
  if (tool === 'list_memories' && input.memory) {
    return { scope: 'personal', target: slugify(input.memory) };
  }
  if (tool === 'brain_read' && memoryPath(input.concept_id)) {
    const path = memoryPath(input.concept_id);
    return { scope: path.scope, target: slugify(path.name) };
  }
  return null;
}

// El detalle de una memoria: `list_memories` lo devuelve en la raíz y `brain_read`,
// dentro de `memory`, junto al sobre del cerebro.
function memoryDetail(data) {
  const value = data || {};
  return value.memory && typeof value.memory === 'object' && value.memory.mode ? value.memory : value;
}

// El recibo de una escritura de memoria: `remember` lo devuelve en la raíz y
// `brain_write`, dentro de `memory`. Dice si quedó escrita o propuesta.
function writeReceipt(data) {
  const value = data || {};
  const receipt = value.memory && typeof value.memory === 'object' && 'outcome' in value.memory ? value.memory : value;
  if (receipt.outcome === 'propuesta' || (!receipt.outcome && receipt.proposal_id)) return { result: 'propuesta', receipt };
  if (receipt.outcome === 'escrita' || (!receipt.outcome && receipt.memory_id)) return { result: 'escrita', receipt };
  return { result: 'incierta', receipt };
}

function readTargetKey(state, read) {
  return [currentAgent(state), 'memoria.escribir', read.scope, digest(read.target)].join('|');
}

function resolveFromRead(state, tool, input, outcome, now) {
  const read = memoryRead(tool, input);
  if (!read) return;
  const targetKey = readTargetKey(state, read);
  const body = memoryDetail(outcome.data);
  // Una memoria de otro ámbito (una compartida con el mismo nombre) o de otro agente
  // es otro destino: no dice nada de esta escritura.
  const otherScope = outcome.ok && body.scope && normalize(body.scope) !== read.scope;
  const otherAgent = outcome.ok && body.agent_id && state.seal && body.agent_id !== state.seal.agent_id;
  const otherTarget = otherScope || otherAgent;
  if (outcome.ok && !otherTarget && body.memory_id && body.mode === 'detail') {
    state.seen[targetKey] = { id: body.memory_id, at: now };
    trim(state.seen);
  }
  for (const [key, rec] of Object.entries(state.ops)) {
    if (!key.startsWith(targetKey + '|') || rec.status !== 'uncertain' || now < rec.at) continue;
    const verdict = otherTarget ? 'uncertain' : judge(rec, outcome, body, read.scope);
    if (verdict === 'applied') {
      state.ops[key] = { status: 'confirmed', at: now, agent: rec.agent, op: rec.op };
    } else if (verdict === 'absent') {
      state.ops[key] = Object.assign({}, rec, { status: 'absent', at: now });
    } else {
      rec.inconclusive = true;
    }
  }
}

function judge(rec, outcome, body, scope) {
  // Una memoria compartida no existe hasta que una persona aprueba la propuesta: que no
  // esté, o que siga la de antes, no prueba que la propuesta no se presentó.
  const canBeAbsent = scope !== 'compartida';
  if (outcome.notFound) return canBeAbsent ? 'absent' : 'uncertain';
  if (!outcome.ok) return 'uncertain';
  if (body.mode && body.mode !== 'detail') return 'uncertain'; // un índice no prueba nada
  const truncated =
    body.truncado === true || body.truncated === true ||
    (body.next_offset !== undefined && body.next_offset !== null) ||
    (body.next_cursor !== undefined && body.next_cursor !== null);
  if (truncated) return 'uncertain';
  const text = body.block !== undefined ? memoryFile(body.block) : body.body;
  if (text === undefined) return 'uncertain';
  const state = String(body.state || (body.frontmatter && body.frontmatter.state) || '').toLowerCase();
  if (state && !/viva|live|activ/.test(state)) return 'uncertain';
  const title = body.title !== undefined ? body.title : body.frontmatter && body.frontmatter.title;
  const titleOk = !rec.title_h || (title !== undefined && digest(normalize(title)) === rec.title_h);
  if (titleOk && containsBody(text, rec)) return 'applied';
  if (canBeAbsent && rec.prior_id && body.memory_id && body.memory_id === rec.prior_id) return 'absent';
  return 'uncertain';
}

// ── Después de una llamada ──────────────────────────────────────────────────────
// Actualiza el estado y devuelve, si hace falta, una nota para el modelo.
function postToolUse(state, tool, input, response, ctx, facts) {
  input = input || {};
  const now = (ctx && ctx.now) || Date.now();
  const at = (ctx && ctx.at) || new Date(now).toISOString();
  const { data, error, isError } = readResponse(response);
  if (error || isError) return applyError(state, tool, input, error || { code: 'unknown' }, ctx, facts);

  const op = operation(state, tool, input, facts);
  delete state.failures[op.key];
  const notes = [];
  const body = data || {};
  const asked = takePending(state, ctx, null);

  if (ctx && ctx.server) learnServer(state, ctx.server, tool, body);

  if (tool === 'list_agents' && Array.isArray(body.agents)) {
    state.keyring = body.agents.map((a) => ({ id: a.agentId || a.id || null, name: a.name || null }));
    state.keyring_at = at;
  }

  if (tool === 'use_agent' && body.selection_context) {
    const before = state.seal;
    const agent = body.agent || {};
    const agentId = agent.id || agentIdOf(state, input.agent);
    state.seal = {
      agent_id: agentId,
      agent_name: agent.name || input.agent,
      version: agent.version === undefined ? null : agent.version,
      family: agent.family || null,
      selection_context: body.selection_context,
      expires_at: body.expires_at || null,
      sealed_at: at,
    };
    state.seal_state = 'sealed';
    state.retired = Array.isArray(agent.herramientasRetiradas) ? agent.herramientasRetiradas.slice() : [];
    state.newer_version = null;
    // Elegir un agente deja sin efecto la elección de cualquier otro.
    const kept = state.authorized[agentId];
    state.authorized = {};
    const named = [agentId, input.agent, agent.name].map(normalize);
    const fallback =
      asked ||
      named.map((n) => takePending(state, ctx, `elegir:${n}:`)).find(Boolean) ||
      named.map((n) => takePending(state, ctx, `adoptar:${n}:`)).find(Boolean);
    if (kept) state.authorized[agentId] = kept;
    if (fallback && fallback.kind === 'elegir' && named.includes(normalize(fallback.agent))) {
      // Con evidencia de la persona, o aprobada en un diálogo de la aplicación. En un
      // modo que no pregunta, que la llamada haya pasado no dice nada de la persona.
      const approvedHere = fallback.via !== 'anfitrion' || ASKING_MODES.has(fallback.mode || 'default');
      if (approvedHere) state.authorized[agentId] = { via: fallback.via, at, name: state.seal.agent_name };
      // La elección ya se usó: no vuelve a elegir.
      if (fallback.chosen_at && (!state.choice_floor || fallback.chosen_at > state.choice_floor)) {
        state.choice_floor = fallback.chosen_at;
      }
    }
    const moved = before && before.agent_id === agentId && before.version !== state.seal.version;
    if (!before || before.agent_id !== agentId || moved) {
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
      notes.push(
        'No memory index came with the selection. That does not prove there is no memory: when the task may continue earlier ' +
          "work, look in the agent's memory the way its brain says."
      );
    } else if (body.memory.truncated || body.memory.omitidas > 0) {
      notes.push(
        'The memory index in this response is partial. Before concluding that something is not in memory, look further the way ' +
          "the agent's brain says, following any cursor."
      );
    }
  }

  if (tool === 'release_agent' && body.released) {
    state.seal = null;
    state.seal_state = 'none';
    state.retired = [];
    state.newer_version = null;
    state.reads = {};
    state.listings = {};
    state.authorized = {}; // Soltar el agente retira la elección.
    state.released_at = at;
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

  if (tool === 'brain_read' && input.concept_id && !memoryPath(input.concept_id)) {
    const partial = body.next_offset !== undefined && body.next_offset !== null;
    state.reads[input.concept_id] = { complete: !partial, next_offset: partial ? body.next_offset : null };
    trim(state.reads);
    if (partial) {
      notes.push(
        `\`${input.concept_id}\` is not complete yet: continue with offset ${body.next_offset} before relying on it or telling the person you read it.`
      );
    }
  }

  if (tool === 'brain_index' || (tool === 'list_memories' && !input.memory)) {
    const cursor = body.next_cursor || (body.memory && body.memory.next_cursor) || null;
    const where = tool === 'brain_index' ? (input.path || '(root)') : 'memory index';
    state.listings[tool + ':' + where] = { complete: !cursor };
    trim(state.listings);
    if (cursor) notes.push(`This listing of ${where} is partial: continue with the cursor it returned before concluding that something is missing.`);
  }

  resolveFromRead(state, tool, input, { ok: true, data: body }, now);

  const written = op.kind === 'memory' || op.kind === 'write' || (op.kind === 'catalog' && input.confirm === true) || DELETES.has(tool);
  if (written) {
    delete state.approved[op.key];
    const memoryWrite = op.kind === 'memory' && op.op === 'memoria.escribir';
    const { result, receipt } = memoryWrite ? writeReceipt(body) : { result: 'escrita', receipt: body };
    if (result === 'incierta') {
      // La llamada no falló, pero la respuesta no dice si quedó escrita.
      markUncertain(state, op, now);
      notes.push(
        `The response does not say whether this memory was saved. Read it back by its name, ${READ_BACK}, before telling ` +
          'the person it is saved, and do not write it again until then.'
      );
      return { context: notes.join('\n') };
    }
    state.ops[op.key] = { status: result === 'propuesta' ? 'proposed' : 'confirmed', at: now, agent: op.agent, op: op.op };
    // Una escritura en el mismo destino resuelve las inciertas anteriores.
    for (const [key, rec] of Object.entries(state.ops)) {
      if (key !== op.key && key.startsWith(op.targetKey + '|') && !DONE.has(rec.status)) delete state.ops[key];
    }
    trim(state.ops);
    if (op.kind === 'memory' && result === 'escrita' && receipt.memory_id) {
      state.seen[op.targetKey] = { id: receipt.memory_id, at: now };
      trim(state.seen);
    }
    delete state.previews[op.key];
    if (memoryWrite) {
      notes.push(
        result === 'propuesta'
          ? 'This was filed as a proposal for a person to approve. It is not saved as a memory and will not appear as one ' +
              'until it is approved: tell the person it is waiting for approval.'
          : `Write confirmed. Read it back once by its name, ${READ_BACK}. If that read fails, report it as saved but not yet ` +
              'verified; do not write it again.'
      );
    }
  } else {
    keepPreview(state, op.key, now);
  }

  return { context: notes.join('\n') || null };
}

// Una vista previa vale para aplicar durante la misma ventana que protege una
// escritura; las viejas se descartan antes de recortar por número.
function keepPreview(state, key, now) {
  for (const [k, when] of Object.entries(state.previews)) {
    if (now - when > WRITE_WINDOW_MS) delete state.previews[k];
  }
  state.previews[key] = now;
  trim(state.previews, MAX_PREVIEWS);
}

function learnServer(state, server, tool, body) {
  if (state.server === server) return;
  const looksLikeDatalum =
    (tool === 'use_agent' && typeof body.selection_context === 'string' && 'operating_as' in body) ||
    (tool === 'list_agents' && Array.isArray(body.agents) && typeof body.message === 'string');
  if (looksLikeDatalum) state.server = server;
}

function postToolUseFailure(state, tool, input, errorText, ctx, facts) {
  return applyError(state, tool, input || {}, errorFromText(errorText), ctx, facts);
}

// La aplicación denegó la llamada sin preguntar (por ejemplo, el clasificador del
// modo automático). Lo que se había pedido para esa llamada queda sin efecto.
function permissionDenied(state, tool, input, ctx) {
  const entry = takePending(state, ctx, null);
  if (entry && entry.kind === 'elegir' && entry.agent) delete state.authorized[entry.agent];
  return { context: null };
}

function markUncertain(state, op, now) {
  const evidence = memoryEvidence(op.memory);
  const prior = state.seen[op.targetKey];
  // Un resultado incierto nuevo en el mismo destino reemplaza a los anteriores.
  for (const [key, rec] of Object.entries(state.ops)) {
    if (key !== op.key && key.startsWith(op.targetKey + '|') && !DONE.has(rec.status)) delete state.ops[key];
  }
  state.ops[op.key] = Object.assign(
    { status: 'uncertain', at: now, agent: op.agent, op: op.op, prior_id: prior ? prior.id : null },
    evidence || {}
  );
  trim(state.ops);
}

// Una lectura de memoria que falló sobre algo que ya se escribió o se propuso en esta
// conversación: lo hecho sigue hecho.
function failedReadNote(state, tool, input, notFound, now) {
  const read = memoryRead(tool, input);
  if (!read) return null;
  const targetKey = readTargetKey(state, read);
  const done = Object.entries(state.ops).find(
    ([key, rec]) => key.startsWith(targetKey + '|') && DONE.has(rec.status) && now - rec.at < WRITE_WINDOW_MS
  );
  if (!done) return null;
  if (done[1].status === 'proposed') {
    if (!notFound) return null;
    return 'That memory was filed in this conversation as a proposal and does not exist until a person approves it. Not ' +
      'finding it is expected. Do not file it again.';
  }
  if (notFound) return null; // Escrita y ahora no está: lo que diga la lectura, lo dice Datalum.
  return 'This memory was saved earlier in this conversation and this read failed. Tell the person it is saved but not yet ' +
    'verified, try the read again later, and do not write it again.';
}

function applyError(state, tool, input, error, ctx, facts) {
  const now = (ctx && ctx.now) || Date.now();
  const op = operation(state, tool, input, facts);
  const code = error.code;
  const asked = takePending(state, ctx, null);
  if (asked && asked.op && ASKING_MODES.has(asked.mode || 'default')) {
    // La persona aprobó la llamada en la aplicación y falló después: su aprobación
    // sigue valiendo para reintentar esa misma operación un rato.
    state.approved[asked.op] = now;
    trim(state.approved);
  }
  if (asked && asked.kind === 'elegir' && asked.agent && (asked.via !== 'anfitrion' || ASKING_MODES.has(asked.mode || 'default'))) {
    state.authorized[asked.agent] = { via: asked.via, at: new Date(now).toISOString() };
  }
  const writeLike = op.kind === 'memory' || op.kind === 'write' || input.confirm === true || DELETES.has(tool);
  const count = () => {
    const previous = state.failures[op.key];
    const fresh = previous && now - previous.at < FAILURE_WINDOW_MS;
    state.failures[op.key] = { count: fresh ? previous.count + 1 : 1, at: now };
    trim(state.failures);
  };

  const notFound = code === 'not_found' || code === 'agent_memory_not_found';
  resolveFromRead(state, tool, input, { ok: false, notFound }, now);
  const readNote = failedReadNote(state, tool, input, notFound, now);

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
    state.ops[op.key] = { status: 'partial', at: now, agent: op.agent, op: op.op };
    return { context: 'The write was applied in part. Repeat this same call to complete it, then check the result.' };
  }
  const uncertain = ['transport_uncertain', 'backend_timeout', 'athena_timeout', 'internal_error', 'unknown'].includes(code);
  if (writeLike && uncertain) {
    markUncertain(state, op, now);
    count();
    return {
      context:
        `It is not known whether this write was applied. Do not repeat it yet. Read the same target back by its name first, ${READ_BACK}; ` +
        'repeat only if that read shows it is not there. Until then, tell the person the result is not confirmed.',
    };
  }
  count();
  return { context: readNote };
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
  const agent = currentAgent(state);
  const mine = Object.values(state.ops).filter((rec) => rec.agent === agent);
  const confirmed = mine.filter((rec) => rec.status === 'confirmed').length;
  const proposed = mine.filter((rec) => rec.status === 'proposed').length;
  const uncertain = mine.filter((rec) => rec.status === 'uncertain').length;
  if (confirmed) lines.push(`- ${confirmed} write(s) already confirmed for this agent. The plugin blocks repeating them.`);
  if (proposed) lines.push(`- ${proposed} proposal(s) filed and waiting for a person's approval. They are not memories yet; do not file them again.`);
  if (uncertain) lines.push(`- ${uncertain} write(s) with an uncertain result. Read each target by its name before repeating.`);
  lines.push("- If the work was tracked in memory, recover it the way the agent's brain says before continuing.");
  return lines.join('\n');
}

module.exports = {
  STATE_VERSION,
  newState,
  migrate,
  isDatalum,
  parseToolName,
  preToolUse,
  postToolUse,
  postToolUseFailure,
  permissionDenied,
  resumeContext,
  readResponse,
  errorFromText,
  ownWords,
  normalize,
  slugify,
  operation,
};
