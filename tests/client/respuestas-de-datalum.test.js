'use strict';
// El cliente frente a las respuestas reales de Datalum. Las fixtures de `fixtures/`
// tienen la estructura que arma el servidor (v2.243.0): el sobre MCP con el JSON como
// texto, el resultado de `brain_write` dentro de `memory`, el detalle enmarcado con
// cada línea prefijada y el rechazo en dos bloques. El contenido y los ids son
// sintéticos.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const policy = require('../../client/policy');

const fixture = (name) => JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', name), 'utf8'));
const WRITE = fixture('escritura.json');
const AGENT = WRITE.agent_id;
const FACTS = {
  citas_humanas: { use_agent: 'user_choice_quote' },
  sin_selection_context: ['list_agents'],
};
const T0 = Date.parse('2026-10-05T10:00:00Z');
const iso = (ms) => new Date(ms).toISOString();
const TIMEOUT = 'MCP error -32001: Request timed out';
const MEMORIA = 'agents/ventas/memoria/cierre_de_ventas';
const COMPARTIDA = 'agents/ventas/memoria-compartida/moneda';

function sealed() {
  const state = policy.newState('2.0.2');
  policy.postToolUse(state, 'list_agents', {}, { agents: [{ agentId: AGENT, name: 'Ventas' }], message: '' }, { now: T0, at: iso(T0) });
  const input = { agent: 'Ventas', user_choice_quote: 'Ventas' };
  assert.equal(policy.preToolUse(state, 'use_agent', input, FACTS, { now: T0 + 100 }).decision, 'pass');
  policy.postToolUse(state, 'use_agent', input, {
    operating_as: 'operando como Ventas v9', selection_context: 'ctx-v', memory: { text: '' },
    agent: { id: AGENT, name: 'Ventas', version: 9, herramientasRetiradas: [] },
  }, { now: T0 + 200, at: iso(T0 + 200) });
  return state;
}

const brainWrite = (extra) => Object.assign({ concept_id: MEMORIA, kind: 'hecho', title: WRITE.title, body_md: WRITE.body_md }, extra);
const pre = (state, tool, input, ms, mode) => policy.preToolUse(state, tool, input, FACTS, { now: ms, mode: mode || 'default' });
const post = (state, tool, input, response, ms) => policy.postToolUse(state, tool, input, response, { now: ms, at: iso(ms) }, FACTS);

test('brain_write: una propuesta no se anuncia como guardada', () => {
  const state = sealed();
  const input = brainWrite({ concept_id: COMPARTIDA, title: 'Moneda', body_md: 'Reportamos en pesos.' });
  assert.equal(pre(state, 'brain_write', input, T0 + 1000).decision, 'ask', 'la memoria compartida la autoriza la persona');
  const note = post(state, 'brain_write', input, fixture('brain_write-propuesta.json'), T0 + 2000).context;
  assert.match(note, /proposal/);
  assert.doesNotMatch(note, /Write confirmed/);
  // Presentarla otra vez duplicaría la propuesta.
  const again = pre(state, 'brain_write', input, T0 + 3000);
  assert.equal(again.decision, 'deny');
  assert.match(again.reason, /proposal/);
});

test('brain_write: lo escrito se reconoce aunque llegue dentro de memory', () => {
  const state = sealed();
  const first = brainWrite();
  post(state, 'brain_write', first, fixture('brain_write-escrita.json'), T0 + 1000);
  // Una segunda versión se queda sin respuesta; la relectura sirve la memoria de antes,
  // con el mismo id: la segunda no se aplicó y se permite un reintento.
  const second = brainWrite({ body_md: WRITE.body_md + '\n- Pendiente: conciliar devoluciones' });
  policy.postToolUseFailure(state, 'brain_write', second, TIMEOUT, { now: T0 + 2000 }, FACTS);
  post(state, 'brain_read', { concept_id: MEMORIA }, fixture('brain_read-detalle.json'), T0 + 3000);
  assert.equal(pre(state, 'brain_write', second, T0 + 4000).decision, 'pass');
});

test('brain_read: el detalle real, con escapes en el texto, confirma la escritura', () => {
  const state = sealed();
  policy.postToolUseFailure(state, 'brain_write', brainWrite(), TIMEOUT, { now: T0 + 1000 }, FACTS);
  post(state, 'brain_read', { concept_id: MEMORIA }, fixture('brain_read-detalle.json'), T0 + 2000);
  assert.equal(pre(state, 'brain_write', brainWrite(), T0 + 3000).decision, 'deny');
});

test('list_memories: el detalle real también confirma la escritura de remember', () => {
  const state = sealed();
  const input = { kind: 'hecho', slug: 'cierre_de_ventas', title: WRITE.title, body_md: WRITE.body_md };
  policy.postToolUseFailure(state, 'remember', input, TIMEOUT, { now: T0 + 1000 }, FACTS);
  post(state, 'list_memories', { memory: 'cierre_de_ventas' }, fixture('list_memories-detalle.json'), T0 + 2000);
  assert.equal(pre(state, 'remember', input, T0 + 3000).decision, 'deny');
});

test('remember: el recibo real cuenta como escrito', () => {
  const state = sealed();
  const input = { kind: 'hecho', slug: 'cierre_de_ventas', title: WRITE.title, body_md: WRITE.body_md };
  assert.match(post(state, 'remember', input, fixture('remember-escrita.json'), T0 + 1000).context, /Write confirmed/);
});

test('un índice real nunca confirma, aunque traiga el mismo texto', () => {
  const state = sealed();
  policy.postToolUseFailure(state, 'brain_write', brainWrite(), TIMEOUT, { now: T0 + 1000 }, FACTS);
  post(state, 'list_memories', { memory: 'cierre_de_ventas' }, fixture('list_memories-indice.json'), T0 + 2000);
  assert.equal(pre(state, 'brain_write', brainWrite(), T0 + 3000).decision, 'ask');
});

test('el detalle de otro agente no confirma la escritura de éste', () => {
  const state = sealed();
  policy.postToolUseFailure(state, 'brain_write', brainWrite(), TIMEOUT, { now: T0 + 1000 }, FACTS);
  const other = fixture('list_memories-detalle.json');
  const detail = JSON.parse(other.content[0].text);
  detail.agent_id = '6f1c0000-0000-4000-8000-00000000a999';
  other.content[0].text = JSON.stringify(detail, null, 2);
  post(state, 'list_memories', { memory: 'cierre_de_ventas' }, other, T0 + 2000);
  assert.equal(pre(state, 'brain_write', brainWrite(), T0 + 3000).decision, 'ask');
});

test('que una memoria compartida no exista no prueba que la propuesta no se presentó', () => {
  const state = sealed();
  const input = brainWrite({ concept_id: COMPARTIDA, title: 'Moneda', body_md: 'Reportamos en pesos.' });
  pre(state, 'brain_write', input, T0 + 1000);
  policy.postToolUseFailure(state, 'brain_write', input, TIMEOUT, { now: T0 + 2000 }, FACTS);
  post(state, 'brain_read', { concept_id: COMPARTIDA }, fixture('memoria-no-existe.json'), T0 + 3000);
  // Puede estar esperando la aprobación de una persona: repetirla lo decide ella,
  // sabiendo que puede duplicarla.
  const verdict = pre(state, 'brain_write', input, T0 + 4000);
  assert.equal(verdict.decision, 'ask');
  assert.match(verdict.reason, /duplicarlo/);
});

test('una escritura confirmada cuya relectura falla sigue guardada', () => {
  const state = sealed();
  post(state, 'brain_write', brainWrite(), fixture('brain_write-escrita.json'), T0 + 1000);
  const note = policy.postToolUseFailure(state, 'brain_read', { concept_id: MEMORIA }, TIMEOUT, { now: T0 + 2000 }, FACTS).context;
  assert.match(note, /saved but not (yet )?verified/);
  assert.equal(pre(state, 'brain_write', brainWrite(), T0 + 3000).decision, 'deny');
});

test('los avisos de recuperación remiten al procedimiento de memoria del cerebro', () => {
  const state = sealed();
  policy.postToolUseFailure(state, 'brain_write', brainWrite(), TIMEOUT, { now: T0 + 1000 }, FACTS);
  const reason = pre(state, 'brain_write', brainWrite(), T0 + 2000).reason;
  const partial = post(state, 'use_agent', { agent: 'Ventas', user_choice_quote: 'Ventas' }, {
    operating_as: 'operando como Ventas v9', selection_context: 'ctx-v', memory: { text: '', truncated: true },
    agent: { id: AGENT, name: 'Ventas', version: 9, herramientasRetiradas: [] },
  }, T0 + 3000).context;
  const missing = post(state, 'use_agent', { agent: 'Ventas', user_choice_quote: 'Ventas' }, {
    operating_as: 'operando como Ventas v9', selection_context: 'ctx-v', memory: null,
    agent: { id: AGENT, name: 'Ventas', version: 9, herramientasRetiradas: [] },
  }, T0 + 4000).context;
  const resume = policy.resumeContext(state);
  for (const text of [reason, partial, missing, resume]) {
    assert.doesNotMatch(text, /list_memories|brain_index|brain_read/, 'no impone una herramienta');
    assert.match(text, /brain/, 'remite al cerebro del agente');
  }
});

test('la respuesta se lee capa por capa, sin tocar los escapes del texto', () => {
  const { data } = policy.readResponse(fixture('brain_read-detalle.json'));
  assert.ok(data.memory.block.includes('| - Fuente: C:\\datos\\cierre\\2026-10.csv, con \\n literal en el nombre.'));
  assert.ok(data.memory.block.includes('| - Moneda: pesos ("MXN"), sin centavos.'));
  // Igual si la aplicación entrega sólo la lista de bloques.
  assert.deepEqual(policy.readResponse(fixture('brain_read-detalle.json').content).data, data);
});

test('una respuesta sin recibo no cuenta como escrita', () => {
  const state = sealed();
  const input = { kind: 'hecho', slug: 'cierre_de_ventas', title: WRITE.title, body_md: WRITE.body_md };
  const note = post(state, 'remember', input, { content: [{ type: 'text', text: '{"notice":"ok"}' }], isError: false }, T0 + 1000).context;
  assert.match(note, /does not say whether this memory was saved/);
  const again = pre(state, 'remember', input, T0 + 2000);
  assert.equal(again.decision, 'deny');
  assert.match(again.reason, /read that memory/);
});

test('no encontrar una propuesta presentada es lo esperado, y se dice', () => {
  const state = sealed();
  const input = brainWrite({ concept_id: COMPARTIDA, title: 'Moneda', body_md: 'Reportamos en pesos.' });
  pre(state, 'brain_write', input, T0 + 1000);
  post(state, 'brain_write', input, fixture('brain_write-propuesta.json'), T0 + 2000);
  const note = post(state, 'brain_read', { concept_id: COMPARTIDA }, fixture('memoria-no-existe.json'), T0 + 3000).context;
  assert.match(note, /proposal and does not exist until a person approves it/);
  assert.match(policy.resumeContext(state), /1 proposal\(s\) filed and waiting/);
});

test('una relectura de una propuesta que falla por otra causa no se da por esperada', () => {
  const state = sealed();
  const input = brainWrite({ concept_id: COMPARTIDA, title: 'Moneda', body_md: 'Reportamos en pesos.' });
  pre(state, 'brain_write', input, T0 + 1000);
  post(state, 'brain_write', input, fixture('brain_write-propuesta.json'), T0 + 2000);
  const note = policy.postToolUseFailure(state, 'brain_read', { concept_id: COMPARTIDA }, TIMEOUT, { now: T0 + 3000 }, FACTS).context;
  assert.doesNotMatch(note || '', /expected/);
});
