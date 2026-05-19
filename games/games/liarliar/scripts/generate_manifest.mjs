import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const playersIndex = process.argv.indexOf('--players');
const count = playersIndex >= 0 ? Number(process.argv[playersIndex + 1]) : 6;
if (!Number.isInteger(count) || count < 2) {
  console.error('Usage: node scripts/generate_manifest.mjs --players N');
  process.exit(2);
}

const manifest = JSON.parse(await readFile(resolve('coworld_manifest.json'), 'utf8'));
manifest.game.config_schema.properties.tokens.minItems = count;
manifest.game.config_schema.properties.tokens.maxItems = count;
manifest.game.config_schema.properties.players.minItems = count;
manifest.game.config_schema.properties.players.maxItems = count;
for (const key of ['scores', 'survived', 'detonated', 'modules_solved', 'modules_failed', 'hint_recoveries']) {
  manifest.game.results_schema.properties[key].minItems = count;
  manifest.game.results_schema.properties[key].maxItems = count;
}

const players = Array.from({ length: count }, (_, slot) => ({ name: `Player ${slot + 1}` }));
const defaultCircle = () => ({ type: 'circle', radius: count > 1 ? Math.min(2, Math.floor(count / 2)) : 0 });
for (const variant of manifest.variants) {
  variant.game_config.players = players;
  if (variant.game_config.communication_graph?.type === 'circle') {
    variant.game_config.communication_graph = defaultCircle();
    variant.game_config.hint_graph = { ...variant.game_config.communication_graph };
  }
}
manifest.certification.game_config.players = players;
manifest.certification.game_config.communication_graph = defaultCircle();
manifest.certification.game_config.hint_graph = { ...manifest.certification.game_config.communication_graph };
manifest.certification.players = Array.from({ length: count }, () => ({ player_id: 'scripted-helper' }));

console.log(JSON.stringify(manifest, null, 2));
