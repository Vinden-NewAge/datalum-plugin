'use strict';
// Lo que dijo y eligió la persona en esta conversación, leído de la transcripción que
// entrega la aplicación. Sirve para reconocer cuándo eligió un agente. No se copia a
// ningún lado: se lee, se usa para la comprobación y se descarta.

const fs = require('fs');

const MAX_BYTES = 8 * 1024 * 1024;
const QUESTION_TOOL = 'AskUserQuestion';

// Devuelve [{text, at, kind}] en orden, o null si la transcripción no se puede leer.
// kind es 'message' para un mensaje que escribió la persona y 'answer' para lo que
// eligió en una pregunta de la aplicación.
function read(transcriptPath) {
  if (!transcriptPath) return null;
  let raw;
  try {
    const stat = fs.statSync(transcriptPath);
    const fd = fs.openSync(transcriptPath, 'r');
    const length = Math.min(stat.size, MAX_BYTES);
    const buffer = Buffer.alloc(length);
    fs.readSync(fd, buffer, 0, length, stat.size - length);
    fs.closeSync(fd);
    raw = buffer.toString('utf8');
  } catch (_) {
    return null;
  }
  const questions = new Set(); // ids de las preguntas que hizo la aplicación
  const human = [];
  for (const line of raw.split('\n')) {
    if (!line.startsWith('{')) continue;
    let entry;
    try {
      entry = JSON.parse(line);
    } catch (_) {
      continue;
    }
    if (entry.isSidechain) continue;
    const content = entry.message && entry.message.content;
    if (entry.type === 'assistant' && Array.isArray(content)) {
      for (const block of content) {
        if (block && block.type === 'tool_use' && block.name === QUESTION_TOOL && block.id) questions.add(block.id);
      }
      continue;
    }
    if (entry.type !== 'user' || entry.isMeta) continue;
    const at = entry.timestamp || null;
    // Lo que la persona eligió en una pregunta: sólo cuenta si contesta a una pregunta
    // de la herramienta de preguntas de la aplicación. Una respuesta de otra
    // herramienta, aunque traiga un campo con el mismo nombre, es un dato.
    const result = entry.toolUseResult;
    if (result && result.answers && typeof result.answers === 'object' && Array.isArray(content)) {
      const answersQuestion = content.some((b) => b && b.type === 'tool_result' && questions.has(b.tool_use_id));
      if (answersQuestion) {
        for (const answer of Object.values(result.answers)) {
          if (typeof answer === 'string') human.push({ text: answer, at, kind: 'answer' });
        }
      }
      continue;
    }
    // Sólo cuenta lo que escribió una persona: no lo que mandó otro agente, ni el texto
    // que la aplicación añade al cargar una skill o al devolver una herramienta.
    if (entry.origin && entry.origin.kind && entry.origin.kind !== 'human') continue;
    if (entry.sourceToolUseID) continue;
    if (typeof content === 'string') {
      human.push({ text: content, at, kind: 'message' });
    } else if (Array.isArray(content)) {
      for (const block of content) {
        if (block && block.type === 'text' && typeof block.text === 'string') human.push({ text: block.text, at, kind: 'message' });
      }
    }
  }
  return human;
}

module.exports = { read };
