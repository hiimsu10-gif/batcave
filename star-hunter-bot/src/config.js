const fs = require('node:fs');
const path = require('node:path');

const configPath = path.resolve(process.env.BOT_CONFIG || path.join(__dirname, '..', 'config', 'star-hunter.json'));

if (!fs.existsSync(configPath)) {
  console.error(`Config file not found: ${configPath}\nCopy config/star-hunter.example.json to config/star-hunter.json and fill in your IDs.`);
  process.exit(1);
}

const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));

// Label + flag for a DeepL language code, falling back to the code itself.
function language(code) {
  return config.languages?.[code] ?? { name: code, flag: '🌐' };
}

module.exports = { config, language, configPath };
