#!/usr/bin/env node
'use strict';
// Punto de entrada de los controles en toda aplicación que corre hooks/hooks.json.
//
// Lee el evento por stdin, elige el adaptador de la aplicación que lo lanzó y escribe
// lo que el adaptador devuelve. Codex se reconoce porque a los hooks de un plugin les da
// su propia variable de carpeta, PLUGIN_ROOT, con el mismo valor que CLAUDE_PLUGIN_ROOT;
// Claude Code sólo da CLAUDE_PLUGIN_ROOT. Si la aplicación no se reconoce bien, ningún
// adaptador aprueba nada: el de Codex sólo niega o deja pasar.
//
// Si algo falla aquí, la llamada sigue su curso y el hook termina con código 0: los
// controles nunca dejan a la persona sin su herramienta, y lo que de verdad no se puede
// hacer lo rechaza Datalum.

function isCodex(env) {
  return !!env.PLUGIN_ROOT && env.PLUGIN_ROOT === env.CLAUDE_PLUGIN_ROOT;
}

function pick(env) {
  return isCodex(env) ? require('./codex') : require('./claude-code');
}

function run(adapter) {
  let raw = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', (chunk) => (raw += chunk));
  process.stdin.on('end', () => {
    try {
      const output = adapter.handle(JSON.parse(raw));
      if (output) process.stdout.write(JSON.stringify(output));
    } catch (error) {
      // Al registro de depuración va sólo la clase del error: su mensaje puede citar
      // la entrada, y la entrada puede traer palabras de la persona.
      const kind = (error && (error.code || error.name)) || 'Error';
      process.stderr.write(`datalum: control omitido (${kind})\n`);
    }
    process.exit(0);
  });
}

module.exports = { isCodex, pick, run };

if (require.main === module) run(pick(process.env));
